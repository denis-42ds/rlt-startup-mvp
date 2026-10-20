import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "tests/fixtures/rfq_extraction.json"
OUTPUT = Path("/tmp/rlt-llm-eval-qwen2.5-3b.json")

MODEL = "qwen2.5:3b"
API_URL = "http://127.0.0.1:11434/api/generate"
TIMEOUT_SECONDS = 180

FIELDS = [
    "product_name",
    "quantity",
    "unit",
    "max_unit_price",
    "currency",
    "delivery_destination",
    "missing_fields",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "product_name": {"type": ["string", "null"]},
        "quantity": {"type": ["number", "null"]},
        "unit": {"type": ["string", "null"]},
        "max_unit_price": {"type": ["number", "null"]},
        "currency": {"type": ["string", "null"]},
        "delivery_destination": {"type": ["string", "null"]},
        "missing_fields": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": FIELDS,
    "additionalProperties": False,
}

SYSTEM_INSTRUCTIONS = """
Ты извлекаешь структурированные данные из заявки покупателя B2B.
Верни только JSON по заданной схеме.

Правила:
- Не придумывай значения, отсутствующие в тексте.
- Если значение неизвестно или неоднозначно, верни null.
- Все неизвестные поля перечисли в missing_fields.
- Не выводи единицу измерения только из типа товара.
- quantity — количество товара, не бюджет и не цена.
- max_unit_price — максимальная цена за одну указанную единицу.
- Общая цена заказа не равна цене за единицу.
- Если указаны противоречивые значения одного поля, верни null
  для этого поля и добавь его в missing_fields.
- Если цена указана, но валюта не названа и не следует явно
  из текста, верни null для currency.
- Не пересчитывай единицы измерения и не меняй смысл заявки.
- product_name должен обозначать товар, а не всю заявку.
- missing_fields должен содержать имена всех полей, значение
  которых неизвестно или неоднозначно.
""".strip()


def load_cases():
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    if not cases:
        raise ValueError("Набор RFQ пуст")
    return cases


def request_model(case):
    payload = {
        "model": MODEL,
        "stream": False,
        "format": SCHEMA,
        "keep_alive": "5m",
        "options": {
            "temperature": 0,
            "num_predict": 192,
            "num_thread": 4,
        },
        "prompt": (
            f"{SYSTEM_INSTRUCTIONS}\n\n"
            f"Заявка:\n{case['text']}"
        ),
    }

    request = Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    started = time.perf_counter()
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            http_status = response.status
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        return {
            "http_status": exc.code,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "error": f"HTTPError: {body_text}",
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "http_status": None,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }

    result = {
        "http_status": http_status,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "ollama_total_seconds": round(
            body.get("total_duration", 0) / 1e9, 3
        ),
        "ollama_load_seconds": round(
            body.get("load_duration", 0) / 1e9, 3
        ),
        "prompt_eval_count": body.get("prompt_eval_count"),
        "eval_count": body.get("eval_count"),
        "raw_response": body.get("response", ""),
    }

    try:
        result["parsed"] = json.loads(body["response"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        result["parse_error"] = str(exc)

    return result


def score(case, result):
    parsed = result.get("parsed")
    if not isinstance(parsed, dict):
        return {
            "valid_object": False,
            "exact_field_matches": 0,
            "field_count": len(FIELDS),
            "field_matches": {},
        }

    field_matches = {}
    for field in FIELDS:
        expected = case["expected"].get(field)
        actual = parsed.get(field)

        if field == "missing_fields" and isinstance(actual, list):
            matches = sorted(actual) == sorted(expected)
        else:
            matches = actual == expected

        field_matches[field] = matches

    return {
        "valid_object": set(parsed) == set(FIELDS),
        "exact_field_matches": sum(field_matches.values()),
        "field_count": len(FIELDS),
        "field_matches": field_matches,
    }


def main():
    cases = load_cases()
    results = []

    print(f"Модель: {MODEL}")
    print(f"RFQ: {len(cases)}")
    print(f"Тайм-аут на заявку: {TIMEOUT_SECONDS} с")
    print("Начинаем последовательный прогон.\n", flush=True)

    for index, case in enumerate(cases, start=1):
        print(
            f"[{index}/{len(cases)}] {case['id']} ...",
            end=" ",
            flush=True,
        )

        result = request_model(case)
        result["score"] = score(case, result)

        record = {
            "id": case["id"],
            "text": case["text"],
            "expected": case["expected"],
            **result,
        }
        results.append(record)

        if result.get("error"):
            print(f"ERROR: {result['error']}")
        elif result.get("parse_error"):
            print(f"JSON ERROR: {result['parse_error']}")
        else:
            print(
                f"{result['elapsed_seconds']:.2f} с; "
                f"точных полей: "
                f"{result['score']['exact_field_matches']}/{len(FIELDS)}"
            )

        # Сохраняем прогресс после каждого запроса.
        report = {
            "model": MODEL,
            "dataset": str(DATASET),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed": len(results),
            "total_cases": len(cases),
            "results": results,
        }
        OUTPUT.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    successful = [
        r for r in results
        if isinstance(r.get("parsed"), dict)
    ]
    elapsed = [
        r["elapsed_seconds"]
        for r in results
        if "elapsed_seconds" in r
    ]

    print("\n--- ИТОГ ---")
    print(f"Успешно разобрано как JSON-объектов: {len(successful)}/{len(cases)}")
    print(f"Ошибки/тайм-ауты: {len(cases) - len(successful)}")

    if elapsed:
        print(f"Среднее время ответа: {sum(elapsed) / len(elapsed):.2f} с")
        print(f"Максимальное время ответа: {max(elapsed):.2f} с")

    exact = sum(
        r.get("score", {}).get("exact_field_matches", 0)
        for r in results
    )
    possible = len(cases) * len(FIELDS)
    print(f"Точное совпадение полей: {exact}/{possible}")
    print("ВНИМАНИЕ: это предварительная метрика, не экспертная оценка.")
    print(f"Полный отчёт: {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(1)
