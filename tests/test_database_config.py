import pytest

from app.core.config import DatabaseSettings


def test_native_connection_preserves_special_characters_and_custom_port(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", "55438")
    monkeypatch.setenv("DB_NAME", "local_dev")
    monkeypatch.setenv("DB_USER", "developer")
    monkeypatch.setenv("DB_PASSWORD", "local:p@ss/word")
    url = DatabaseSettings(_env_file=None).connection_url()
    assert (url.host, url.port, url.database) == ("127.0.0.1", 55438, "local_dev")
    assert (url.username, url.password) == ("developer", "local:p@ss/word")


def test_full_url_overrides_individual_settings(monkeypatch):
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://user@override.example:5544/service"
    )
    url = DatabaseSettings(_env_file=None).connection_url()
    assert (url.host, url.port, url.database) == ("override.example", 5544, "service")


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_hosted_database_urls_use_psycopg(monkeypatch, scheme):
    monkeypatch.setenv(
        "DATABASE_URL",
        f" {scheme}://service:demo%40pass@dpg-demo/db?sslmode=require ",
    )
    url = DatabaseSettings(_env_file=None).connection_url()
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "demo@pass"
    assert url.host == "dpg-demo"
    assert url.query["sslmode"] == "require"
