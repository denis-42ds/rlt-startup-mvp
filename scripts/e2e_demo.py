import json
import sys
import argparse
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



def prompt_field(label: str, value, optional: bool = False):
    """Позволяет пользователю проверить или исправить поле RFQ."""
    current = "—" if value is None else str(value)
    answer = input(
        f"{label} [{current}] "
        "(Enter — оставить, '-' — очистить необязательное): "
    ).strip()

    if not answer:
        return value
    if answer == "-" and optional:
        return None
    return answer


def create_interactive_rfq(client: httpx.Client) -> dict:
    """Извлекает RFQ локальной LLM и создаёт её только после подтверждения."""
    text = input(
        "\nОпишите потребность покупателя одним сообщением:\n> "
    ).strip()

    require(bool(text), "Текст заявки не должен быть пустым")

    response = client.post("/rfqs/extract", json={"text": text}, timeout=60.0,)
    extraction = show("local LLM extraction", response)

    require(
        response.status_code == 200,
        "Не удалось извлечь заявку. Проверьте API и доступность Ollama.",
    )

    print("\nПроверьте извлечённые поля. Enter сохраняет предложенное значение.")
    if extraction.get("missing_fields"):
        print("Модель отметила неполные поля:", extraction["missing_fields"])

    product_name = prompt_field(
        "Товар", extraction.get("product_name")
    )
    quantity = prompt_field("Количество", extraction.get("quantity"))
    unit = prompt_field("Единица измерения", extraction.get("unit"))
    max_unit_price = prompt_field(
        "Максимальная цена за единицу",
        extraction.get("max_unit_price"),
        optional=True,
    )
    currency = prompt_field(
        "Валюта (например, RUB)",
        extraction.get("currency"),
        optional=True,
    )

    while max_unit_price is not None and not currency:
        answer = input(
            "Для указанной цены валюта обязательна "
            "(например, RUB). '-' — убрать цену: "
        ).strip()

        if answer == "-":
            max_unit_price = None
            currency = None
            break

        if answer:
            currency = answer.upper()
    destination = prompt_field(
        "Место доставки",
        extraction.get("delivery_destination"),
        optional=True,
    )

    require(
        isinstance(product_name, str) and bool(product_name.strip()),
        "Не указано название товара",
    )
    require(
        isinstance(quantity, str) and bool(quantity.strip()),
        "Не указано количество",
    )
    require(
        isinstance(unit, str) and bool(unit.strip()),
        "Не указана единица измерения",
    )
    require(
        max_unit_price is None or currency is not None,
        "Для указанной цены необходимо указать валюту",
    )

    generic_names = {"товар", "продукт", "вещь", "item", "product"}
    require(
        product_name.strip().casefold() not in generic_names,
        "Укажите конкретный товар, а не общее название",
    )

    print("\nИтоговая заявка:")
    print(f"  Товар: {product_name}")
    print(f"  Количество: {quantity} {unit}")
    print(
        f"  Максимальная цена: "
        f"{max_unit_price if max_unit_price is not None else 'не задана'} "
        f"{currency or ''}"
    )
    print(f"  Доставка: {destination or 'не задана'}")

    confirmation = input(
        "\nСоздать RFQ с этими данными? [y/N]: "
    ).strip().casefold()

    require(
        confirmation == "y",
        "Пользователь отменил создание RFQ",
    )

    payload = {
        "buyer_organization_id": BUYER_ID,
        "items": [
            {
                "product_name": product_name.strip(),
                "quantity": quantity,
                "unit": unit.strip(),
            }
        ],
        "constraints": ["Демонстрационный сценарий"],
        "status": "rfq_submitted",
    }

    if max_unit_price is not None:
        payload["max_unit_price"] = max_unit_price
    if currency is not None:
        payload["currency"] = currency.strip().upper()
    if destination is not None:
        payload["delivery_destination"] = destination.strip()

    response = client.post("/rfqs", json=payload)
    rfq = show("create confirmed RFQ", response)

    require(
        response.status_code == 201,
        "API не смогло создать RFQ",
    )
    return rfq


def main(interactive: bool = False) -> None:
    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        health = client.get("/health")
        show("health", health)

        # 1. Создаём RFQ автоматически или после подтверждения покупателем.
        if interactive:
            rfq = create_interactive_rfq(client)
        else:
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
            require(
                "id" in rfq,
                "API не вернул ID созданной RFQ",
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

        print("\n=== Результаты обработки заявки ===")

        supplier_names = {
            SUPPLIER_A_ID: "Поставщик A",
            SUPPLIER_B_ID: "Поставщик B",
            SUPPLIER_C_ID: "Поставщик C",
        }

        for supplier_id, result in preparations.items():
            name = supplier_names.get(supplier_id, f"Поставщик {supplier_id}")

            if result["ready"]:
                offer = result.get("offer") or {}
                print(f"\n{name}: ПРЕДЛОЖЕНИЕ ГОТОВО")
                if offer.get("unit_price") is not None:
                    print(f"  Цена за единицу: {offer['unit_price']}")
                if offer.get("currency"):
                    print(f"  Валюта: {offer['currency']}")
                if offer.get("quantity") is not None:
                    print(f"  Количество: {offer['quantity']}")
            else:
                print(f"\n{name}: ПРЕДЛОЖЕНИЕ НЕ ПОДГОТОВЛЕНО")
                for reason in result.get("reasons", []):
                    print(f"  Причина: {reason}")

        comparisons = workflow.get("comparisons", [])

        print("\n=== Сравнение предложений ===")
        if comparisons:
            for index, comparison in enumerate(comparisons, start=1):
                print(f"{index}. {comparison}")
        else:
            print("Нет предложений, прошедших проверку.")

        result_a = preparations[SUPPLIER_A_ID]
        result_b = preparations[SUPPLIER_B_ID]
        result_c = preparations[SUPPLIER_C_ID]

        if interactive and not any(
            result["ready"] for result in preparations.values()
        ):
            print(
                "\nE2E STOP: ни один демо-поставщик не смог подготовить "
                "предложение по этой заявке."
            )
            print(
                "RFQ создана, но заказ не создавался. "
                "Проверьте товар, единицу измерения и количество."
            )
            print(f"RFQ ID: {rfq_id}")
            return

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
    parser = argparse.ArgumentParser(
        description="RLT.Startup E2E demo"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Извлечь RFQ локальной LLM и запросить подтверждение",
    )
    args = parser.parse_args()

    try:
        main(interactive=args.interactive)
    except (AssertionError, KeyError, ValueError, httpx.HTTPError) as exc:
        print(f"\nE2E FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
