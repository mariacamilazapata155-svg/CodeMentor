"""Pruebas de la clave de acceso y del cliente diferido del modelo.

Cubren RF-13 (sin clave no se llama al modelo), RNF-3 (importar el módulo no
exige clave ni abre conexiones), RNF-4 (el mensaje de falta de clave está en
español y nombra la variable) y RNF-7 (espera de 30 s y un reintento). No usan
red, claves reales ni el cliente de verdad: `anthropic.Anthropic` se sustituye
por un doble.

Estrategia de la prueba de recarga: se recarga `bot` con `ANTHROPIC_API_KEY`
eliminada y `anthropic.Anthropic` sustituido por un doble que falla si se
llama, dentro de un `pytest.MonkeyPatch.context()` que deshace los cambios al
salir; después se recarga el módulo otra vez con el entorno normal, para no
dejar una versión recargada a las pruebas siguientes.
"""

import importlib
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

from app import bot
from app.models import ChatReason

#: Mensaje exacto del motivo `missing_api_key`.
MISSING_API_KEY_MESSAGE = (
    "Falta la clave de acceso al modelo. Configúrala en la variable de entorno "
    "ANTHROPIC_API_KEY y vuelve a intentarlo."
)

#: Clave falsa usada para comprobar que no se filtra a los mensajes.
SECRET_KEY = "clave-secreta-de-prueba"


# --- RF-13: hay o no hay clave -----------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("", False),
        ("   ", False),
        ("\n\t ", False),
        ("clave-valida", True),
    ],
)
def test_api_key_present_accepts_only_a_non_blank_key(
    set_api_key: Callable[[str | None], None],
    value: str | None,
    expected: bool,
) -> None:
    """La variable ausente, vacía o de solo espacios no es una clave."""
    set_api_key(value)

    assert bot._api_key_present() is expected


# --- RNF-3: el cliente es diferido y no se crea al importar ------------------


def test_reloading_bot_without_key_does_not_fail_nor_create_the_client() -> None:
    """Recargar `bot` sin clave ni red no construye el cliente."""
    created: list[dict[str, Any]] = []

    def failing_client(**kwargs: Any) -> None:
        created.append(kwargs)
        raise AssertionError("no se debe crear el cliente al recargar bot")

    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("ANTHROPIC_API_KEY", raising=False)
        patch.setattr(anthropic, "Anthropic", failing_client)

        importlib.reload(bot)

        assert bot._api_key_present() is False
        assert callable(bot._get_client)

    importlib.reload(bot)

    assert created == []
    assert bot._get_client.cache_info().currsize == 0


# --- RNF-7: espera, reintentos y reutilización del cliente -------------------


def test_get_client_uses_timeout_and_retries_and_reuses_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El cliente se crea una sola vez, con `timeout=30.0` y `max_retries=1`."""
    calls: list[dict[str, Any]] = []
    client = SimpleNamespace(name="cliente-falso")

    def fake_anthropic(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return client

    monkeypatch.setattr(anthropic, "Anthropic", fake_anthropic)

    first = bot._get_client()
    second = bot._get_client()

    assert first is client
    assert second is client
    assert calls == [{"timeout": 30.0, "max_retries": 1}]
    assert bot._get_client.cache_info().maxsize == 1


# --- RNF-4 y RF-19: mensaje de falta de clave --------------------------------


def test_missing_api_key_failure_has_the_exact_spanish_message(
    set_api_key: Callable[[str | None], None],
) -> None:
    """El fallo usa el mensaje exacto, sin citas y en español."""
    set_api_key(SECRET_KEY)

    response = bot._failure(ChatReason.MISSING_API_KEY)

    assert response.reply == MISSING_API_KEY_MESSAGE
    assert response.reason == ChatReason.MISSING_API_KEY
    assert response.citations == []


def test_missing_api_key_message_names_the_variable_without_leaking_details(
    set_api_key: Callable[[str | None], None],
) -> None:
    """El mensaje nombra `ANTHROPIC_API_KEY`, explica cómo configurarla y no filtra."""
    set_api_key(SECRET_KEY)

    reply = bot._failure(ChatReason.MISSING_API_KEY).reply

    assert "ANTHROPIC_API_KEY" in reply
    assert "entorno" in reply
    assert "Configúrala" in reply
    assert SECRET_KEY not in reply
    for sdk_name in ("AnthropicError", "APIStatusError", "AuthenticationError"):
        assert sdk_name not in reply


def test_missing_api_key_failure_keeps_rf19() -> None:
    """Un fallo tiene motivo y cero citas; nunca las dos cosas a la vez."""
    response = bot._failure(ChatReason.MISSING_API_KEY)

    has_citations = bool(response.citations)
    assert (response.reason is None) is has_citations
    assert response.reason is not None
    assert response.citations == []
