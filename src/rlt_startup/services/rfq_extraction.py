"""Извлечение полей B2B-заявки с помощью локальной LLM Ollama."""

import json
import os
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    computed_field,
)

DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_TIMEOUT = 45

EXTRACTABLE_FIELDS = (
    "product_name",
    "quantity",
    "unit",
    "max_unit_price",
    "currency",
    "delivery_destination",
)


def detect_explicit_currency(text: str) -> str | None:
    """Распознаёт валюту только по явным обозначениям в тексте."""
    import re

    patterns = {
        "RUB": r"(?<!\w)(?:руб(?:лей|ля|ль)?|руб\.?|₽)(?!\w)",
        "USD": r"(?<!\w)(?:USD|доллар(?:ов|а)?|\$)(?!\w)",
        "EUR": r"(?<!\w)(?:EUR|евро|€)(?!\w)",
        "CNY": r"(?<!\w)(?:CNY|юан(?:ей|я)?)(?!\w)",
        "TRY": r"(?<!\w)(?:TRY|лир(?:ы|а|у)?|₺)(?!\w)",
    }

    matches = {
        currency
        for currency, pattern in patterns.items()
        if re.search(pattern, text, flags=re.IGNORECASE)
    }

    return next(iter(matches)) if len(matches) == 1 else None


class RFQExtractionError(RuntimeError):
    """Базовая ошибка извлечения заявки."""


class RFQModelUnavailableError(RFQExtractionError):
    """Локальная модель недоступна или не ответила вовремя."""


class RFQModelResponseError(RFQExtractionError):
    """Ответ модели не удалось безопасно разобрать."""


class RFQExtraction(BaseModel):
    """Результат извлечения. Не является созданной RFQ."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_name: str | None = Field(default=None, max_length=200)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=32)
    max_unit_price: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    delivery_destination: str | None = Field(default=None, max_length=500)
    missing_fields: list[str] = Field(default_factory=list)

    @classmethod
    def from_model_data(cls, data: dict[str, Any]) -> "RFQExtraction":
        """Проверяет поля и самостоятельно вычисляет список пропусков."""
        data = dict(data)
        data.pop("missing_fields", None)

        try:
            result = cls.model_validate(data)
        except ValidationError as exc:
            raise RFQModelResponseError(
                "Поля ответа модели не прошли проверку"
            ) from exc

        missing = [
            name
            for name in EXTRACTABLE_FIELDS
            if getattr(result, name) is None
        ]

        # Цена без валюты не может быть использована в RFQ.
        if result.max_unit_price is not None and result.currency is None:
            if "currency" not in missing:
                missing.append("currency")

        return result.model_copy(update={"missing_fields": missing})

    @computed_field
    @property
    def ready_to_create_rfq(self) -> bool:
        product_name = (self.product_name or "").strip().casefold()

        generic_product_names = {
            "",
            "товар",
            "продукт",
            "вещь",
            "item",
            "product",
        }

        has_specific_product = product_name not in generic_product_names
        has_required_fields = (
            self.quantity is not None
            and self.unit is not None
            and bool(self.unit.strip())
        )
        has_valid_price_currency = (
            self.max_unit_price is None
            or self.currency is not None
        )

        return (
            has_specific_product
            and has_required_fields
            and has_valid_price_currency
        )

SYSTEM_PROMPT = """
Ты извлекаешь структурированные данные из заявки покупателя B2B.
Верни только JSON по заданной схеме.

Правила:
- Не придумывай отсутствующие значения.
- Неизвестное или неоднозначное значение обозначай null.
- product_name — название товара, не описание всей заявки.
- quantity — количество товара, не бюджет и не цена.
- unit — единица измерения, явно указанная или однозначно следующая
  из формулировки. Не угадывай её по названию товара.
- max_unit_price — максимальная цена за единицу товара.
- Общая стоимость заказа не равна цене за единицу.
- Не пересчитывай единицы измерения.
- Если одно поле имеет противоречивые значения, верни null.
- Не выводи валюту, если она не указана и не следует однозначно
  из текста.
- Неопределённое место доставки обозначай null.
- Все неизвестные поля включи в missing_fields.
""".strip()


OUTPUT_SCHEMA = {
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
    "required": [
        "product_name",
        "quantity",
        "unit",
        "max_unit_price",
        "currency",
        "delivery_destination",
        "missing_fields",
    ],
    "additionalProperties": False,
}


def extract_rfq(text: str) -> RFQExtraction:
    """Извлекает данные через локальный Ollama API."""
    text = text.strip()
    if not text:
        raise ValueError("Текст заявки не должен быть пустым")

    model = os.getenv("RLT_OLLAMA_MODEL", DEFAULT_MODEL)
    api_url = os.getenv("RLT_OLLAMA_URL", DEFAULT_URL)

    payload = {
        "model": model,
        "stream": False,
        "format": OUTPUT_SCHEMA,
        "keep_alive": "5m",
        "options": {
            "temperature": 0,
            "num_predict": 192,
            "num_thread": 4,
        },
        "prompt": f"{SYSTEM_PROMPT}\n\nЗаявка покупателя:\n{text}",
    }

    request = Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RFQModelUnavailableError(
            f"Ollama вернула HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RFQModelUnavailableError(
            "Не удалось получить ответ от локальной Ollama"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RFQModelResponseError(
            "Ollama вернула некорректный HTTP-ответ"
        ) from exc

    if not isinstance(body, dict) or not isinstance(body.get("response"), str):
        raise RFQModelResponseError("В ответе Ollama отсутствует response")

    try:
        model_data = json.loads(body["response"])
    except json.JSONDecodeError as exc:
        raise RFQModelResponseError(
            "Модель вернула некорректный JSON"
        ) from exc

    if not isinstance(model_data, dict):
        raise RFQModelResponseError("Ожидался JSON-объект")

    try:
        result = RFQExtraction.from_model_data(model_data)

        # Явное обозначение валюты в исходном тексте приоритетнее
        # предположения модели. Если маркер неоднозначен, функция
        # возвращает None и автоматическая подстановка не выполняется.
        detected_currency = detect_explicit_currency(text)

        if detected_currency is not None:
            result = RFQExtraction.from_model_data(
                {
                    **result.model_dump(
                        exclude={"missing_fields", "ready_to_create_rfq"}
                    ),
                    "currency": detected_currency,
                }
            )

        return result

    except (ValidationError, TypeError, ValueError) as exc:
        raise RFQModelResponseError(
            "Поля ответа модели не прошли проверку"
        ) from exc
