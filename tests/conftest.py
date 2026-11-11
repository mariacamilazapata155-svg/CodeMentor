"""Dobles compartidos de las pruebas del bot.

Ofrece un cliente falso de Anthropic que registra las llamadas y devuelve una
respuesta configurable, un constructor de respuestas con bloques de texto y
constructores de los errores del cliente oficial apoyados en `httpx2` (la
dependencia transitiva que usa `anthropic==2.1.0`, no una dependencia del
proyecto). No abre red, no usa claves reales y no importa
`sentence_transformers`.
"""

from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app import bot

#: URL usada para fabricar las peticiones y respuestas falsas de `httpx2`.
FAKE_URL = "https://api.anthropic.com/v1/messages"


def make_text_block(text: str) -> SimpleNamespace:
    """Crea un bloque de texto con la forma que expone el SDK."""
    return SimpleNamespace(type="text", text=text)


def make_message_response(*texts: str) -> SimpleNamespace:
    """Crea una respuesta falsa con un bloque de texto por argumento.

    Sin argumentos devuelve una respuesta con la lista de bloques vacía.
    """
    return SimpleNamespace(content=[make_text_block(text) for text in texts])


class FakeMessages:
    """Sustituto de `client.messages`: registra y responde o lanza el error."""

    def __init__(self, client: "FakeClient") -> None:
        self._client = client

    def create(self, **kwargs: Any) -> SimpleNamespace:
        """Guarda los argumentos recibidos y devuelve la respuesta configurada."""
        self._client.calls.append(kwargs)
        if self._client.error is not None:
            raise self._client.error
        return self._client.response


class FakeClient:
    """Doble del cliente de Anthropic que no abre conexiones.

    `messages.create` guarda todos los argumentos en `calls` (el último queda
    también en `last_call`) y devuelve `response` o lanza `error`.
    """

    def __init__(
        self,
        response: SimpleNamespace | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.response = (
            response
            if response is not None
            else make_message_response("Respuesta de prueba [F1]")
        )
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.messages = FakeMessages(self)

    @property
    def last_call(self) -> dict[str, Any]:
        """Argumentos de la última llamada a `messages.create`."""
        return self.calls[-1]


def make_request() -> httpx2.Request:
    """Crea la petición falsa que exigen los errores del cliente."""
    return httpx2.Request("POST", FAKE_URL)


def make_response(status_code: int) -> httpx2.Response:
    """Crea la respuesta falsa con el código de estado del error."""
    return httpx2.Response(status_code, request=make_request())


def build_status_error(
    error_class: type[anthropic.APIStatusError],
    status_code: int,
) -> anthropic.APIStatusError:
    """Construye un error de estado real del SDK con una respuesta falsa."""
    return error_class(
        "error de prueba", response=make_response(status_code), body=None
    )


def build_timeout_error() -> anthropic.APITimeoutError:
    """Construye el error de tiempo agotado del SDK."""
    return anthropic.APITimeoutError(make_request())


def build_connection_error() -> anthropic.APIConnectionError:
    """Construye el error de conexión del SDK."""
    return anthropic.APIConnectionError(request=make_request())


def build_rate_limit_error() -> anthropic.RateLimitError:
    """Construye el error 429 de límite de peticiones."""
    return build_status_error(anthropic.RateLimitError, 429)


def build_bad_request_error() -> anthropic.BadRequestError:
    """Construye el error 400 de petición rechazada."""
    return build_status_error(anthropic.BadRequestError, 400)


def build_authentication_error() -> anthropic.AuthenticationError:
    """Construye el error 401 de clave inválida."""
    return build_status_error(anthropic.AuthenticationError, 401)


def build_permission_denied_error() -> anthropic.PermissionDeniedError:
    """Construye el error 403 de falta de permiso."""
    return build_status_error(anthropic.PermissionDeniedError, 403)


def build_internal_server_error() -> anthropic.InternalServerError:
    """Construye el error 500 del servidor."""
    return build_status_error(anthropic.InternalServerError, 500)


def build_overloaded_error() -> anthropic.OverloadedError:
    """Construye el error 529 de servicio sobrecargado."""
    return build_status_error(anthropic.OverloadedError, 529)


#: Constructores de los errores que puede lanzar el cliente oficial.
ERROR_BUILDERS: dict[str, Callable[[], anthropic.AnthropicError]] = {
    "timeout": build_timeout_error,
    "connection": build_connection_error,
    "rate_limit": build_rate_limit_error,
    "bad_request": build_bad_request_error,
    "authentication": build_authentication_error,
    "permission_denied": build_permission_denied_error,
    "internal_server": build_internal_server_error,
    "overloaded": build_overloaded_error,
}


def _clear_client_cache() -> None:
    """Limpia `bot._get_client` si ya existe y expone `cache_clear`."""
    get_client = getattr(bot, "_get_client", None)
    cache_clear = getattr(get_client, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


@pytest.fixture(autouse=True)
def reset_client_cache() -> Iterator[None]:
    """Vacía la caché del cliente antes y después de cada prueba.

    Si `_get_client` no existe o no expone `cache_clear`, el fixture no hace
    nada. Así el cliente cacheado de una prueba (y la clave con la que se
    creó) no se filtra a la siguiente.
    """
    _clear_client_cache()
    yield
    _clear_client_cache()


@pytest.fixture
def set_api_key(monkeypatch: pytest.MonkeyPatch) -> Callable[[str | None], None]:
    """Devuelve una función para fijar o eliminar `ANTHROPIC_API_KEY`.

    Uso: `set_api_key("clave")` fija la variable y `set_api_key(None)` la
    elimina. `monkeypatch` restaura el estado original al terminar la prueba.
    """

    def apply(value: str | None) -> None:
        if value is None:
            monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        else:
            monkeypatch.setenv("ANTHROPIC_API_KEY", value)

    return apply
