import json
import sys
from uuid import UUID

import httpx

BASE_URL = "http://127.0.0.1:8000"

BUYER_ID = "30000000-0000-4000-8000-000000000001"
SUPPLIER_A_ID = "10000000-0000-4000-8000-000000000001"
SUPPLIER_B_ID = "10000000-0000-4000-8000-000000000002"
SUPPLIER_C_ID = "10000000-0000-4000-8000-000000000003"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)



def show(label: str, response: httpx.Response) -> dict:
    print(f"\n=== {label}: HTTP {response.status_code} ===")
    try:
        payload = response.json()
    except ValueError:
        print(response.text)
        return {}

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        health = client.get("/health")
        show("health", health)

        # 1. Создаём RFQ: 100 кг стального листа.
        rfq = show(
            "create RFQ",
            client.post(
                "/rfqs",
                json={
                    "buyer_organization_id": BUYER_ID,
                    "items": [
                        {
                            "product_name": "Стальной лист",
                            "quantity": "100",
                            "unit": "кг",
                        }
                    ],
                    "currency": "RUB",
                    "max_unit_price": "200.00",
                    "delivery_destination": "Демонстрационный склад",
                    "constraints": ["Демонстрационный сценарий"],
                    "status": "rfq_submitted",
                },
            ),
        )
        rfq_id = rfq["id"]

        # 2. Запускаем подготовку предложений всех трёх поставщиков.
        workflow = show(
            "seller offer workflow",
            client.post(
                f"/rfqs/{rfq_id}/seller-offer-workflow",
                json={
                    "supplier_ids": [
                        SUPPLIER_A_ID,
                        SUPPLIER_B_ID,
                        SUPPLIER_C_ID,
                    ]
                },
            ),
        )

        preparations = workflow["preparations"]
        for supplier_id, result in preparations.items():
            print(
                f"Поставщик {supplier_id}: "
                f"ready={result['ready']}, "
                f"reasons={result['reasons']}"
            )

        result_a = preparations[SUPPLIER_A_ID]
        result_b = preparations[SUPPLIER_B_ID]
        result_c = preparations[SUPPLIER_C_ID]

        require(result_a["ready"], "Поставщик A должен быть готов")
        require(result_b["ready"], "Поставщик B должен быть готов")
        require(not result_c["ready"], "Поставщик C должен быть не готов")

        offer_a_id = result_a["offer"]["id"]
        offer_b_id = result_b["offer"]["id"]

        # 3. Создаём заказ по предложению A.
        order = show(
            "create order",
            client.post(
                f"/rfqs/{rfq_id}/orders",
                json={"offer_id": offer_a_id},
            ),
        )

        order_id = order["id"]
        require(
            order["status"] == "pending_buyer_confirmation",
            "Новый заказ должен ожидать подтверждения покупателя",
        )

        # 4. До подтверждений документы должны быть недоступны.
        documents_before = client.get(f"/orders/{order_id}/documents")
        show("documents before confirmation", documents_before)
        require(
            documents_before.status_code == 422,
            "До подтверждений ожидается HTTP 422",
        )

        # 5. Подтверждение покупателем.
        buyer_result = show(
            "buyer confirmation",
            client.post(f"/orders/{order_id}/buyer-confirmation"),
        )
        require(
            buyer_result["status"] == "pending_supplier_confirmation",
            "После подтверждения покупателя ожидается статус "
            "pending_supplier_confirmation",
        )

        # 6. Подтверждение поставщиком: сервер повторно проверяет политику
        # и складские остатки через демо-адаптер.
        supplier_result = show(
            "supplier confirmation",
            client.post(f"/orders/{order_id}/supplier-confirmation"),
        )
        require(
            supplier_result["status"] == "order_confirmed",
            "Заказ должен стать order_confirmed",
        )

        # 7. Получаем три черновика документов.
        documents = show(
            "confirmed order documents",
            client.get(f"/orders/{order_id}/documents"),
        )

        document_types = {
            documents.get("commercial_offer", {}).get("document_type"),
            documents.get("order", {}).get("document_type"),
            documents.get("shipping_specification", {}).get("document_type"),
        }
        require(
            document_types
            == {"commercial_offer", "order", "shipping_specification"},
            f"Неожиданный комплект документов: {document_types}",
        )

        for key in (
            "commercial_offer",
            "order",
            "shipping_specification",
        ):
            require(
                documents[key]["status"] == "draft",
                f"Документ {key} должен быть черновиком",
            )

        # 8. Отдельно убеждаемся, что более дешёвое предложение B
        # действительно существовало, но заказ был создан по A.
        require(
            order["offer_id"] == offer_a_id,
            "Заказ должен ссылаться на выбранное предложение A",
        )
        print("\nE2E PASS: весь сценарий завершился успешно.")
        print(f"RFQ ID: {rfq_id}")
        print(f"Order ID: {order_id}")
        print(f"Offer A ID: {offer_a_id}")
        print(f"Offer B ID: {offer_b_id}")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, httpx.HTTPError) as exc:
        print(f"\nE2E FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
