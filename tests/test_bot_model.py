"""Pruebas de los fallos del modelo y de su traducción a motivos.

Cubren RF-14 (tiempo agotado), RF-15 (sin conexión, límite de peticiones y
error del servidor), RF-16 (clave rechazada), RF-17 (cualquier otro error del
cliente oficial y propagación de los que no lo son), RF-18 (sin detalles
técnicos ni citas), RNF-4 (mensajes en español) y RNF-5 (registro solo del
nombre de la clase). No usan red, claves reales ni el cliente de verdad.
"""

import logging
import re
from collections.abc import Callable

import anthropic
import pytest
from conftest import (
    FakeClient,
    build_authentication_error,
    build_bad_request_error,
    build_connection_error,
    build_internal_server_error,
    build_overloaded_error,
    build_permission_denied_error,
    build_rate_limit_error,
    build_timeout_error,
    make_message_response,
)

from app import bot
from app.models import ChatReason, ChatResponse

#: Clave falsa: se comprueba que no aparece en mensajes ni en registros.
SECRET_KEY = "clave-secreta-de-prueba"
#: Pregunta e historial falsos: tampoco deben filtrarse a los registros.
QUESTION = "¿Dónde se calculan los embeddings?"
CODE_SAMPLE = "def autenticar(token: str) -> bool:\n    return token == 'secreto'"

#: Mensajes exactos de los cuatro motivos de fallo del modelo.
FAILURE_MESSAGES: dict[ChatReason, str] = {
    ChatReason.API_TIMEOUT: (
        "El modelo tardó demasiado en responder. Inténtalo de nuevo en un momento."
    ),
    ChatReason.API_UNAVAILABLE: (
        "No se pudo conectar con el modelo o está muy ocupado. Inténtalo de nuevo "
        "en unos minutos."
    ),
    ChatReason.INVALID_API_KEY: (
        "La clave de acceso al modelo no es válida o no tiene permiso. Revisa la "
        "variable ANTHROPIC_API_KEY."
    ),
    ChatReason.API_ERROR: (
        "El modelo no pudo procesar la petición. Inténtalo de nuevo; si sigue "
        "fallando, revisa los registros."
    ),
}

#: Nombres de clases del SDK que nunca deben llegar al usuario.
SDK_NAMES = (
    "AnthropicError",
    "APIError",
    "APIStatusError",
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "AuthenticationError",
    "PermissionDeniedError",
    "BadRequestError",
    "InternalServerError",
    "OverloadedError",
)

#: Palabras que delatan un texto en español.
SPANISH_WORDS = re.compile(r"\b(el|la|los|las|de|en|no|que|un|una|se|con|muy)\b")


def build_generic_error() -> anthropic.AnthropicError:
    """Construye un `AnthropicError` genérico del SDK (no de estado)."""
    return anthropic.AnthropicError("error genérico del SDK")


#: Cada error del cliente oficial y el motivo que debe producir.
ERROR_CASES = [
    pytest.param(build_timeout_error, ChatReason.API_TIMEOUT, id="timeout"),
    pytest.param(build_connection_error, ChatReason.API_UNAVAILABLE, id="connection"),
    pytest.param(
        build_rate_limit_error, ChatReason.API_UNAVAILABLE, id="rate_limit_429"
    ),
    pytest.param(
        build_internal_server_error, ChatReason.API_UNAVAILABLE, id="server_500"
    ),
    pytest.param(
        build_overloaded_error, ChatReason.API_UNAVAILABLE, id="overloaded_529"
    ),
    pytest.param(
        build_authentication_error, ChatReason.INVALID_API_KEY, id="authentication_401"
    ),
    pytest.param(
        build_permission_denied_error,
        ChatReason.INVALID_API_KEY,
        id="permission_denied_403",
    ),
    pytest.param(build_bad_request_error, ChatReason.API_ERROR, id="bad_request_400"),
    pytest.param(build_generic_error, ChatReason.API_ERROR, id="generic"),
]


def install_fake_client(
    monkeypatch: pytest.MonkeyPatch, client: FakeClient
) -> FakeClient:
    """Sustituye el cliente diferido por el doble durante la prueba."""
    monkeypatch.setattr(bot, "_get_client", lambda: client)
    return client


def assert_rf19_failure(response: ChatResponse) -> None:
    """Comprueba el invariante de RF-19 en una respuesta de fallo."""
    has_citations = bool(response.citations)
    assert (response.reason is None) is has_citations
    assert response.reason is not None
    assert response.citations == []


# --- RF-14 a RF-17: traducción de los errores del cliente -------------------


@pytest.mark.parametrize(("builder", "expected_reason"), ERROR_CASES)
def test_sdk_error_is_translated_to_the_expected_reason(
    monkeypatch: pytest.MonkeyPatch,
    builder: Callable[[], anthropic.AnthropicError],
    expected_reason: ChatReason,
) -> None:
    """Cada error del cliente oficial produce su motivo de chat."""
    install_fake_client(monkeypatch, FakeClient(error=builder()))

    with pytest.raises(bot._ModelError) as caught:
        bot._call_model([{"role": "user", "content": QUESTION}])

    assert caught.value.reason == expected_reason


@pytest.mark.parametrize(("builder", "expected_reason"), ERROR_CASES)
def test_model_error_message_does_not_leak_details(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
    builder: Callable[[], anthropic.AnthropicError],
    expected_reason: ChatReason,
) -> None:
    """La excepción traducida no lleva la clave ni el texto original (RF-18)."""
    set_api_key(SECRET_KEY)
    error = builder()
    install_fake_client(monkeypatch, FakeClient(error=error))

    with pytest.raises(bot._ModelError) as caught:
        bot._call_model([{"role": "user", "content": QUESTION}])

    message = str(caught.value)
    assert caught.value.reason == expected_reason
    assert SECRET_KEY not in message
    assert str(error) not in message
    for sdk_name in SDK_NAMES:
        assert sdk_name not in message
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_non_sdk_error_is_not_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un error ajeno al cliente oficial se propaga sin traducción (RF-17)."""
    install_fake_client(monkeypatch, FakeClient(error=ValueError("fallo propio")))

    with pytest.raises(ValueError, match="fallo propio") as caught:
        bot._call_model([{"role": "user", "content": QUESTION}])

    assert not isinstance(caught.value, bot._ModelError)


# --- La llamada: configuración exacta y texto de la respuesta ---------------


def test_call_model_sends_the_configured_request_and_returns_the_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La llamada lleva modelo, tokens, sistema y mensajes exactos (RF-1, RF-5)."""
    client = FakeClient(response=make_message_response("uno [F1]", " y dos"))
    install_fake_client(monkeypatch, client)
    messages = [
        {"role": "user", "content": "primera"},
        {"role": "assistant", "content": "segunda"},
        {"role": "user", "content": "tercera"},
    ]

    text = bot._call_model(messages)

    assert text == "uno [F1] y dos"
    assert client.calls == [
        {
            "model": bot.MODEL_NAME,
            "max_tokens": bot.MAX_TOKENS,
            "system": bot.SYSTEM_PROMPT,
            "messages": messages,
        }
    ]
    assert bot.MODEL_NAME == "claude-sonnet-5-5"
    assert bot.MAX_TOKENS == 1_000


# --- RNF-4 y RF-19: mensajes de los cuatro motivos --------------------------


@pytest.mark.parametrize(("reason", "message"), list(FAILURE_MESSAGES.items()))
def test_failure_returns_the_exact_spanish_message_without_citations(
    set_api_key: Callable[[str | None], None],
    reason: ChatReason,
    message: str,
) -> None:
    """Cada motivo de fallo tiene su mensaje exacto, en español y sin citas."""
    set_api_key(SECRET_KEY)

    response = bot._failure(reason)

    assert response.reply == message
    assert response.reason == reason
    assert response.citations == []
    assert SECRET_KEY not in response.reply
    assert SPANISH_WORDS.search(response.reply) is not None
    assert "error de prueba" not in response.reply
    assert "error genérico del SDK" not in response.reply
    for sdk_name in SDK_NAMES:
        assert sdk_name not in response.reply
    assert_rf19_failure(response)


def test_all_own_failure_messages_are_spanish_and_free_of_details(
    set_api_key: Callable[[str | None], None],
) -> None:
    """RNF-4: los siete mensajes propios están en español y sin datos técnicos."""
    set_api_key(SECRET_KEY)
    own_reasons = (
        ChatReason.MISSING_API_KEY,
        ChatReason.INVALID_API_KEY,
        ChatReason.API_TIMEOUT,
        ChatReason.API_UNAVAILABLE,
        ChatReason.API_ERROR,
        ChatReason.INSUFFICIENT_CONTEXT,
        ChatReason.UNGROUNDED_ANSWER,
    )

    for reason in own_reasons:
        reply = bot._FAILURE_MESSAGES[reason]
        assert reply.strip(), reason
        assert SPANISH_WORDS.search(reply) is not None, reason
        assert SECRET_KEY not in reply, reason
        for sdk_name in SDK_NAMES:
            assert sdk_name not in reply, reason


def test_every_model_reason_has_a_message() -> None:
    """Los cuatro motivos de fallo del modelo están en la tabla de mensajes."""
    for reason in (
        ChatReason.API_TIMEOUT,
        ChatReason.API_UNAVAILABLE,
        ChatReason.INVALID_API_KEY,
        ChatReason.API_ERROR,
    ):
        assert bot._failure(reason).reply == FAILURE_MESSAGES[reason]


# --- RNF-5: registros sin datos sensibles y sin `print` --------------------


@pytest.mark.parametrize(("builder", "expected_reason"), ERROR_CASES)
def test_each_failure_logs_only_the_error_class(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    set_api_key: Callable[[str | None], None],
    builder: Callable[[], anthropic.AnthropicError],
    expected_reason: ChatReason,
) -> None:
    """Se registra la clase del error y nada más; no se imprime (RNF-5)."""
    set_api_key(SECRET_KEY)
    error = builder()
    install_fake_client(monkeypatch, FakeClient(error=error))
    messages = [
        {"role": "user", "content": f"{QUESTION}\n{CODE_SAMPLE}"},
        {"role": "assistant", "content": CODE_SAMPLE},
    ]

    with caplog.at_level(logging.WARNING), pytest.raises(bot._ModelError) as caught:
        bot._call_model(messages)

    assert caught.value.reason == expected_reason
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert type(error).__name__ in record.getMessage()
    assert record.exc_info is None

    logged = caplog.text
    assert SECRET_KEY not in logged
    assert QUESTION not in logged
    assert CODE_SAMPLE not in logged
    assert str(error) not in logged
    assert "error de prueba" not in logged
    assert "error genérico del SDK" not in logged

    captured = capsys.readouterr()
    assert captured.out == ""
