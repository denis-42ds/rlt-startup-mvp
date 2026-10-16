"""Точка входа API с демонстрационными данными."""

from rlt_startup.api import app
from rlt_startup.demo import create_demo_adapters


def configure_demo_app() -> None:
    """Подключает демонстрационные адаптеры поставщиков."""
    app.state.supplier_adapters = create_demo_adapters()


configure_demo_app()
