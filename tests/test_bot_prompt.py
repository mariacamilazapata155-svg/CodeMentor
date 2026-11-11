"""Pruebas del historial enviado al modelo y de los dobles compartidos.

Cubren RF-11: descartar mensajes vacíos antes de contar, enviar como máximo los
últimos diez, recortar cada mensaje a 4.000 caracteres, quitar los mensajes
iniciales del asistente y unir consecutivos del mismo rol. También comprueban
que los dobles de `tests/conftest.py` construyen los errores reales del SDK y
que los fixtures dejan limpio el entorno. No llaman al modelo ni usan red.
"""

import os
from collections.abc import Callable

import anthropic
import pytest
from conftest import (
    ERROR_BUILDERS,
    FAKE_URL,
    FakeClient,
    _clear_client_cache,
    make_message_response,
)

from app import bot
from app.models import ChatMessage


def message(role: str, content: str) -> ChatMessage:
    """Crea un mensaje del historial para las pruebas."""
    return ChatMessage(role=role, content=content)


# --- RF-11: historial enviado ------------------------------------------------


def test_prepare_history_with_no_messages_returns_empty() -> None:
    """Un historial vacío no produce ningún mensaje."""
    assert bot._prepare_history([]) == []


def test_prepare_history_keeps_only_the_last_ten_messages() -> None:
    """De 25 mensajes solo se envían los últimos diez, con su contenido."""
    history = [message("user", f"mensaje {index}") for index in range(25)]

    prepared = bot._prepare_history(history)

    assert prepared == [
        {"role": "user", "content": f"mensaje {index}"} for index in range(15, 25)
    ]


def test_prepare_history_discards_blanks_before_counting() -> None:
    """Los mensajes vacíos no consumen puestos de los últimos diez."""
    history = [message("user", f"mensaje {index}") for index in range(11)]
    history += [message("assistant", "   "), message("user", "\n\t ")]

    prepared = bot._prepare_history(history)

    assert prepared == [
        {"role": "user", "content": f"mensaje {index}"} for index in range(1, 11)
    ]


def test_prepare_history_discards_leading_assistant_messages() -> None:
    """Los mensajes iniciales del asistente se descartan hasta que empiece el usuario."""
    history = [
        message("assistant", "respuesta previa uno"),
        message("assistant", "respuesta previa dos"),
        message("user", "pregunta"),
        message("assistant", "respuesta"),
    ]

    prepared = bot._prepare_history(history)

    assert prepared == [
        {"role": "user", "content": "pregunta"},
        {"role": "assistant", "content": "respuesta"},
    ]


def test_prepare_history_with_only_assistant_messages_returns_empty() -> None:
    """Un historial formado solo por el asistente se queda vacío."""
    history = [
        message("assistant", "una"),
        message("assistant", "otra"),
        message("assistant", "y otra"),
    ]

    assert bot._prepare_history(history) == []


def test_prepare_history_truncates_long_messages_and_keeps_short_ones() -> None:
    """Un mensaje de 5.000 caracteres se recorta a 4.000; uno de 4.000 queda intacto."""
    long_content = "a" * 5_000
    exact_content = "b" * 4_000

    prepared = bot._prepare_history(
        [message("user", long_content), message("assistant", exact_content)]
    )

    assert prepared[0]["content"] == "a" * 4_000
    assert prepared[1]["content"] == exact_content


def test_merge_same_role_joins_with_a_blank_line() -> None:
    """Dos consecutivos del mismo rol se unen con una línea en blanco."""
    messages = [
        {"role": "user", "content": "uno"},
        {"role": "user", "content": "dos"},
        {"role": "assistant", "content": "tres"},
        {"role": "assistant", "content": "cuatro"},
        {"role": "user", "content": "cinco"},
    ]

    assert bot._merge_same_role(messages) == [
        {"role": "user", "content": "uno\n\ndos"},
        {"role": "assistant", "content": "tres\n\ncuatro"},
        {"role": "user", "content": "cinco"},
    ]


def test_merge_same_role_does_not_mutate_the_input() -> None:
    """La lista y los diccionarios de entrada quedan igual; se devuelven copias."""
    messages = [{"role": "user", "content": "uno"}]
    original = [dict(message_) for message_ in messages]

    merged = bot._merge_same_role(messages)

    assert messages == original
    assert merged == original
    assert merged[0] is not messages[0]


def test_merge_same_role_with_no_messages_returns_empty() -> None:
    """Un historial vacío no produce ningún mensaje."""
    assert bot._merge_same_role([]) == []


# --- Dobles: errores reales del SDK ------------------------------------------

ERROR_EXPECTATIONS = [
    ("timeout", anthropic.APITimeoutError, None),
    ("connection", anthropic.APIConnectionError, None),
    ("rate_limit", anthropic.RateLimitError, 429),
    ("bad_request", anthropic.BadRequestError, 400),
    ("authentication", anthropic.AuthenticationError, 401),
    ("permission_denied", anthropic.PermissionDeniedError, 403),
    ("internal_server", anthropic.InternalServerError, 500),
    ("overloaded", anthropic.OverloadedError, 529),
]


@pytest.mark.parametrize(
    ("name", "expected_class", "expected_status"), ERROR_EXPECTATIONS
)
def test_error_builders_create_the_expected_error(
    name: str,
    expected_class: type[anthropic.AnthropicError],
    expected_status: int | None,
) -> None:
    """Cada constructor produce una instancia de la clase real esperada."""
    error = ERROR_BUILDERS[name]()

    assert type(error) is expected_class
    if expected_status is not None:
        assert error.status_code == expected_status


def test_timeout_and_connection_errors_keep_a_request() -> None:
    """Los errores sin estado llevan la petición falsa de `httpx2`."""
    timeout = ERROR_BUILDERS["timeout"]()
    connection = ERROR_BUILDERS["connection"]()

    assert str(timeout.request.url) == FAKE_URL
    assert str(connection.request.url) == FAKE_URL


# --- Dobles: cliente falso ---------------------------------------------------


def test_fake_client_records_arguments_and_returns_one_text_block() -> None:
    """`messages.create` guarda los kwargs y devuelve el bloque configurado."""
    client = FakeClient(make_message_response("Los embeddings están en rag.py. [F1]"))

    response = client.messages.create(
        model="modelo-falso",
        max_tokens=100,
        system="sistema",
        messages=[{"role": "user", "content": "¿Dónde están los embeddings?"}],
    )

    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "modelo-falso"
    assert client.last_call["system"] == "sistema"
    assert response.content[0].type == "text"
    assert response.content[0].text == "Los embeddings están en rag.py. [F1]"


def test_fake_client_returns_several_text_blocks() -> None:
    """Con varios textos se devuelve un bloque por cada uno, en orden."""
    client = FakeClient(make_message_response("uno ", "dos"))

    response = client.messages.create(model="modelo-falso")

    assert [block.text for block in response.content] == ["uno ", "dos"]


def test_fake_client_can_return_no_text_blocks() -> None:
    """Una respuesta configurada sin textos devuelve una lista vacía de bloques."""
    client = FakeClient(make_message_response())

    response = client.messages.create(model="modelo-falso")

    assert response.content == []


def test_fake_client_raises_the_configured_error() -> None:
    """El cliente falso lanza el error configurado y registra la llamada."""
    client = FakeClient(error=ERROR_BUILDERS["rate_limit"]())

    with pytest.raises(anthropic.RateLimitError):
        client.messages.create(model="modelo-falso")

    assert client.last_call == {"model": "modelo-falso"}


# --- Fixtures: clave y caché del cliente -------------------------------------


def test_api_key_fixture_sets_removes_and_restores_the_variable(
    set_api_key: Callable[[str | None], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """El fixture fija, deja vacía y elimina la clave; `monkeypatch` la restaura."""
    original = os.environ.get("ANTHROPIC_API_KEY")

    set_api_key("clave-de-prueba")
    assert os.environ["ANTHROPIC_API_KEY"] == "clave-de-prueba"

    set_api_key("")
    assert os.environ["ANTHROPIC_API_KEY"] == ""

    set_api_key("   ")
    assert os.environ["ANTHROPIC_API_KEY"] == "   "

    set_api_key(None)
    assert "ANTHROPIC_API_KEY" not in os.environ

    monkeypatch.undo()
    assert os.environ.get("ANTHROPIC_API_KEY") == original


def test_clear_client_cache_tolerates_a_missing_get_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `_get_client` el fixture autouse no falla."""
    monkeypatch.delattr(bot, "_get_client", raising=False)

    _clear_client_cache()


def test_clear_client_cache_ignores_a_client_without_cache_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si `_get_client` no expone `cache_clear`, el fixture no falla."""
    monkeypatch.setattr(bot, "_get_client", lambda: object(), raising=False)

    _clear_client_cache()


def test_clear_client_cache_calls_cache_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si `_get_client` tiene caché, el fixture la vacía."""
    calls: list[str] = []

    def fake_get_client() -> object:
        return object()

    fake_get_client.cache_clear = lambda: calls.append("cleared")  # type: ignore[attr-defined]
    monkeypatch.setattr(bot, "_get_client", fake_get_client, raising=False)

    _clear_client_cache()

    assert calls == ["cleared"]
