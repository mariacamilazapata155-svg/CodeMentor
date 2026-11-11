"""Pruebas de las funciones puras de la capa HTTP.

Comprueban las reglas de ruta y codificación, las tablas de estados, el
formato de error, los mensajes propios de `app.main` y el middleware de
tamaño llamado directamente. No levantan el servidor, no usan `TestClient`,
no leen cuerpos ni llaman al modelo.
"""

import asyncio
import codecs
import json

import pytest
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from app import main
from app.models import ApiReason, ChatReason, IndexReason

#: Copia literal de la tabla de mensajes del plan (RNF-4).
OWN_MESSAGES = {
    "MSG_INVALID_REQUEST": "La petición no es válida. Revisa los datos enviados.",
    "MSG_INVALID_PATH": (
        "La ruta del archivo no es válida: no puede estar vacía, superar 255 "
        "caracteres ni contener saltos de línea u otros caracteres de control."
    ),
    "MSG_INVALID_EXTENSION": "Solo se aceptan archivos de Python (.py).",
    "MSG_INVALID_ENCODING": (
        "No se pudo leer el archivo como texto UTF-8. Guárdalo con codificación "
        "UTF-8 y vuelve a subirlo."
    ),
    "MSG_UPLOAD_TOO_LARGE": (
        "La petición es demasiado grande: el límite son 1.052.672 bytes (1 MiB "
        "de archivo más el margen del formulario de subida)."
    ),
    "MSG_CHAT_TOO_LARGE": "El mensaje y el historial son demasiado grandes.",
    "MSG_LENGTH_REQUIRED": (
        "La petición debe indicar su tamaño (cabecera Content-Length)."
    ),
    "MSG_NOT_FOUND": "No existe esa ruta.",
    "MSG_METHOD_NOT_ALLOWED": "Ese método no está permitido en esta ruta.",
    "MSG_INTERNAL_ERROR": (
        "Ocurrió un error interno. Inténtalo de nuevo; si sigue fallando, "
        "revisa los registros."
    ),
}


def make_path(length: int) -> str:
    """Crea una ruta que termina en `.py` con la longitud exacta pedida."""
    return "a" * (length - len(".py")) + ".py"


# --- _validate_path (RF-4 y RF-5) -------------------------------------------


def test_path_of_exactly_255_characters_is_accepted() -> None:
    """255 caracteres es el máximo permitido y se acepta."""
    path = make_path(main.MAX_PATH_CHARS)

    assert len(path) == 255
    assert main._validate_path(path) is None


def test_path_of_256_characters_is_invalid() -> None:
    """Un carácter más de lo permitido ya es una ruta inválida."""
    assert main._validate_path(make_path(256)) is ApiReason.INVALID_PATH


@pytest.mark.parametrize("path", ["", "   "])
def test_empty_or_blank_path_is_invalid(path: str) -> None:
    """Una ruta vacía o de solo espacios no se puede usar."""
    assert main._validate_path(path) is ApiReason.INVALID_PATH


@pytest.mark.parametrize(
    "path",
    ["a\n.py", "a\t.py", "a\x00.py", "a\u2028.py", "a\u2029.py"],
    ids=["salto", "tabulador", "nulo", "u2028", "u2029"],
)
def test_control_characters_make_the_path_invalid(path: str) -> None:
    """Los caracteres Cc, Zl y Zp no se aceptan en la ruta."""
    assert main._validate_path(path) is ApiReason.INVALID_PATH


@pytest.mark.parametrize("path", ["a.PY", "app/Main.PY", ".py", "  a.py", "a b.py"])
def test_valid_python_extensions_are_accepted(path: str) -> None:
    """La extensión no distingue mayúsculas y no se recorta la ruta."""
    assert main._validate_path(path) is None


@pytest.mark.parametrize("path", ["a.txt", "a.js", "a.py.txt", "py", "a.pyi", "a.py "])
def test_invalid_extensions_are_rejected(path: str) -> None:
    """Solo se acepta una ruta que termine exactamente en `.py`."""
    assert main._validate_path(path) is ApiReason.INVALID_EXTENSION


def test_invalid_path_wins_over_invalid_extension() -> None:
    """RF-4 se comprueba antes que RF-5: `a\\n.txt` es ruta inválida."""
    assert main._validate_path("a\n.txt") is ApiReason.INVALID_PATH


# --- _decode_source (RF-6) ---------------------------------------------------


def test_utf8_text_with_accents_is_kept() -> None:
    """Un texto UTF-8 válido se devuelve tal cual."""
    text = "def saludar():\n    return 'año'\n"

    assert main._decode_source(text.encode("utf-8")) == text


def test_utf8_bom_is_removed() -> None:
    """Un BOM inicial se descarta y no queda en el texto."""
    raw = codecs.BOM_UTF8 + "año = 1\n".encode()

    source = main._decode_source(raw)

    assert source == "año = 1\n"
    assert source is not None
    assert not source.startswith("\ufeff")


@pytest.mark.parametrize(
    "raw",
    [b"\xff\xfe\x00", "año".encode("latin-1")],
    ids=["bytes-invalidos", "latin-1"],
)
def test_non_utf8_bytes_are_rejected(raw: bytes) -> None:
    """Lo que no es UTF-8 no se sustituye: se rechaza."""
    assert main._decode_source(raw) is None


def test_empty_bytes_decode_to_empty_text() -> None:
    """Un archivo vacío no es un error de codificación."""
    assert main._decode_source(b"") == ""


# --- _status_for_index (RF-7) -----------------------------------------------


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        (IndexReason.EMPTY_CONTENT, 400),
        (IndexReason.TOO_LARGE, 413),
        (IndexReason.TOO_MANY_CHUNKS, 413),
        (IndexReason.EMBEDDING_FAILED, 500),
    ],
    ids=lambda value: value.value if isinstance(value, IndexReason) else value,
)
def test_index_reasons_map_to_their_status(reason: IndexReason, status: int) -> None:
    """Cada rechazo del indexado conserva su estado del plan."""
    assert main._status_for_index(reason) == status


@pytest.mark.parametrize("reason", list(IndexReason), ids=lambda r: r.value)
def test_every_index_reason_has_a_status(reason: IndexReason) -> None:
    """Un motivo nuevo sin estado hace fallar esta prueba (nunca hay 200 por omisión)."""
    assert reason in main._INDEX_STATUS
    assert main._status_for_index(reason) == main._INDEX_STATUS[reason]


# --- _status_for_chat (RF-10 y RF-11) ---------------------------------------


def test_no_chat_reason_is_a_success() -> None:
    """Una respuesta fundamentada no tiene motivo y devuelve 200."""
    assert main._status_for_chat(None) == 200


@pytest.mark.parametrize(
    "reason",
    [
        ChatReason.EMPTY_INDEX,
        ChatReason.NO_RELEVANT,
        ChatReason.INSUFFICIENT_CONTEXT,
        ChatReason.UNGROUNDED_ANSWER,
    ],
    ids=lambda reason: reason.value,
)
def test_results_without_answer_are_200(reason: ChatReason) -> None:
    """Los resultados sin respuesta son un resultado, no un error."""
    assert main._status_for_chat(reason) == 200


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        (ChatReason.EMPTY_QUERY, 422),
        (ChatReason.QUERY_TOO_LONG, 422),
        (ChatReason.MISSING_API_KEY, 503),
        (ChatReason.INVALID_API_KEY, 503),
        (ChatReason.API_UNAVAILABLE, 503),
        (ChatReason.API_TIMEOUT, 504),
        (ChatReason.API_ERROR, 502),
    ],
    ids=lambda value: value.value if isinstance(value, ChatReason) else value,
)
def test_chat_failures_map_to_their_status(reason: ChatReason, status: int) -> None:
    """Cada fallo del chat conserva el estado del plan."""
    assert main._status_for_chat(reason) == status


@pytest.mark.parametrize("reason", list(ChatReason), ids=lambda r: r.value)
def test_every_chat_reason_is_classified(reason: ChatReason) -> None:
    """Un motivo nuevo sin estado ni entrada en 200 hace fallar esta prueba."""
    assert reason in main._CHAT_OK_REASONS or reason in main._CHAT_STATUS


def test_status_tables_cover_exactly_the_known_reasons() -> None:
    """Las tablas no tienen huecos ni motivos de más, y no se solapan."""
    chat_reasons = set(main._CHAT_OK_REASONS) | set(main._CHAT_STATUS)

    assert set(main._INDEX_STATUS) == set(IndexReason)
    assert chat_reasons == set(ChatReason)
    assert not set(main._CHAT_OK_REASONS) & set(main._CHAT_STATUS)


# --- _error (RF-14) ----------------------------------------------------------


def test_error_builds_the_json_error_format() -> None:
    """El error lleva el estado pedido y exactamente `message` y `reason`."""
    response = main._error(404, ApiReason.NOT_FOUND, "No existe esa ruta.")

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"

    body = json.loads(response.body)
    assert body == {"message": "No existe esa ruta.", "reason": "not_found"}
    assert set(body) == {"message", "reason"}


@pytest.mark.parametrize(
    "reason",
    [
        IndexReason.TOO_LARGE,
        ChatReason.API_TIMEOUT,
        ApiReason.INVALID_ENCODING,
        "reason_libre",
    ],
    ids=["index", "chat", "api", "cadena"],
)
def test_error_accepts_reasons_from_every_capability(
    reason: ApiReason | IndexReason | ChatReason | str,
) -> None:
    """`reason` se serializa como su valor de texto, venga de donde venga."""
    response = main._error(500, reason, "No se pudo completar la operación.")

    body = json.loads(response.body)

    assert body["reason"] == str(reason)


# --- Mensajes propios (RNF-4) ------------------------------------------------


@pytest.mark.parametrize(
    ("name", "text"), OWN_MESSAGES.items(), ids=OWN_MESSAGES.keys()
)
def test_own_messages_match_the_plan_exactly(name: str, text: str) -> None:
    """Cada mensaje propio coincide con el texto literal del plan."""
    assert getattr(main, name) == text


@pytest.mark.parametrize("name", OWN_MESSAGES)
def test_own_messages_end_with_a_period(name: str) -> None:
    """Todos los mensajes son frases completas."""
    assert getattr(main, name).endswith(".")


@pytest.mark.parametrize("name", OWN_MESSAGES)
@pytest.mark.parametrize("forbidden", ["Traceback", "Exception", "api_key", "detail"])
def test_own_messages_have_no_technical_details(name: str, forbidden: str) -> None:
    """Los mensajes no filtran detalles técnicos ni la clave."""
    assert forbidden not in getattr(main, name)


# --- _limit_for y _check_body_size (RF-16 y RF-17) --------------------------


async def _refuse_to_read_body() -> None:
    """Falla si alguien intenta leer el cuerpo de la petición."""
    raise AssertionError("el middleware no debe leer el cuerpo")


def make_request(
    method: str,
    path: str,
    content_length: str | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    """Construye una petición HTTP mínima con la cabecera pedida.

    `content_length=None` omite la cabecera; la cadena vacía la envía vacía.
    El `receive` falla si se intenta leer el cuerpo.
    """
    headers = list(extra_headers or [])
    if content_length is not None:
        headers.insert(0, (b"content-length", content_length.encode("latin-1")))

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "receive": _refuse_to_read_body,
        }
    )


def run_body_size(
    method: str,
    path: str,
    content_length: str | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[Response, list[Request]]:
    """Ejecuta el middleware con un `call_next` falso que registra llamadas."""
    request = make_request(method, path, content_length, extra_headers)
    calls: list[Request] = []

    async def call_next(next_request: Request) -> Response:
        calls.append(next_request)
        return Response(content=b"paso", status_code=200)

    response = asyncio.run(main._check_body_size(request, call_next))

    return response, calls


def assert_api_error(
    response: Response, status: int, reason: ApiReason, message: str
) -> None:
    """Comprueba el formato de error único con el estado y el motivo dados."""
    assert response.status_code == status
    assert json.loads(response.body) == {"message": message, "reason": str(reason)}


#: Rutas con límite de cuerpo y el mensaje de su 413.
LIMITED_ROUTES = [
    ("/upload", main.UPLOAD_BODY_LIMIT, main.MSG_UPLOAD_TOO_LARGE),
    ("/chat", main.CHAT_BODY_LIMIT, main.MSG_CHAT_TOO_LARGE),
]


def test_body_limits_match_the_plan() -> None:
    """Los límites son los que fija el plan para cada ruta."""
    assert main.UPLOAD_BODY_LIMIT == 1_052_672
    assert main.CHAT_BODY_LIMIT == 262_144


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/upload", main.UPLOAD_BODY_LIMIT),
        ("POST", "/chat", main.CHAT_BODY_LIMIT),
        ("GET", "/upload", None),
        ("GET", "/chat", None),
        ("GET", "/health", None),
        ("POST", "/health", None),
        ("POST", "/uploads", None),
        ("GET", "/desconocida", None),
    ],
    ids=[
        "post-upload",
        "post-chat",
        "get-upload",
        "get-chat",
        "get-health",
        "post-health",
        "post-uploads",
        "get-inexistente",
    ],
)
def test_limit_for_uses_exact_method_and_path(
    method: str, path: str, expected: int | None
) -> None:
    """Solo `POST /upload` y `POST /chat` tienen límite; no se compara por prefijo."""
    assert main._limit_for(method, path) == expected


@pytest.mark.parametrize(
    ("path", "limit", "message"),
    LIMITED_ROUTES,
    ids=[route[0].lstrip("/") for route in LIMITED_ROUTES],
)
def test_missing_content_length_is_411(path: str, limit: int, message: str) -> None:
    """Sin `Content-Length` no se puede acotar la lectura y se responde 411."""
    response, calls = run_body_size("POST", path)

    assert_api_error(response, 411, ApiReason.LENGTH_REQUIRED, main.MSG_LENGTH_REQUIRED)
    assert calls == []


@pytest.mark.parametrize(
    ("path", "limit", "message"),
    LIMITED_ROUTES,
    ids=[route[0].lstrip("/") for route in LIMITED_ROUTES],
)
@pytest.mark.parametrize(
    "raw",
    ["abc", "-1", "1.5", "²", "", "+5", " 5"],
    ids=["abc", "negativo", "decimal", "no-ascii", "vacio", "signo", "espacio"],
)
def test_invalid_content_length_is_400(
    path: str, limit: int, message: str, raw: str
) -> None:
    """Un valor que no es un entero no negativo es una petición inválida."""
    response, calls = run_body_size("POST", path, raw)

    assert_api_error(response, 400, ApiReason.INVALID_REQUEST, main.MSG_INVALID_REQUEST)
    assert calls == []


@pytest.mark.parametrize(
    ("path", "limit", "message"),
    LIMITED_ROUTES,
    ids=[route[0].lstrip("/") for route in LIMITED_ROUTES],
)
def test_huge_content_length_is_413_without_value_error(
    path: str, limit: int, message: str
) -> None:
    """5.000 dígitos dan 413: se mide la longitud antes de convertir a `int`."""
    response, calls = run_body_size("POST", path, "7" * 5000)

    assert_api_error(response, 413, ApiReason.PAYLOAD_TOO_LARGE, message)
    assert calls == []


@pytest.mark.parametrize(
    ("path", "limit", "message"),
    LIMITED_ROUTES,
    ids=[route[0].lstrip("/") for route in LIMITED_ROUTES],
)
def test_content_length_at_the_limit_passes(
    path: str, limit: int, message: str
) -> None:
    """Un valor exactamente igual al límite se acepta y llega a `call_next`."""
    response, calls = run_body_size("POST", path, str(limit))

    assert response.status_code == 200
    assert response.body == b"paso"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("path", "limit", "message"),
    LIMITED_ROUTES,
    ids=[route[0].lstrip("/") for route in LIMITED_ROUTES],
)
def test_content_length_one_over_the_limit_is_413(
    path: str, limit: int, message: str
) -> None:
    """Un byte por encima del límite se rechaza con el mensaje de la ruta."""
    response, calls = run_body_size("POST", path, str(limit + 1))

    assert_api_error(response, 413, ApiReason.PAYLOAD_TOO_LARGE, message)
    assert calls == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/upload"),
        ("GET", "/chat"),
        ("GET", "/health"),
        ("POST", "/health"),
        ("POST", "/uploads"),
        ("GET", "/desconocida"),
        ("HEAD", "/upload"),
    ],
    ids=[
        "get-upload",
        "get-chat",
        "get-health",
        "post-health",
        "post-uploads",
        "get-inexistente",
        "head-upload",
    ],
)
def test_other_routes_are_not_size_checked(method: str, path: str) -> None:
    """Fuera de las dos rutas limitadas no se exige `Content-Length` ni hay 411."""
    response, calls = run_body_size(method, path)

    assert response.status_code == 200
    assert response.body == b"paso"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("path", "limit", "message"),
    LIMITED_ROUTES,
    ids=[route[0].lstrip("/") for route in LIMITED_ROUTES],
)
@pytest.mark.parametrize(
    "raw",
    [" 99999999", "+99999999"],
    ids=["espacio", "signo"],
)
def test_invalid_content_length_wins_over_an_excessive_value(
    path: str, limit: int, message: str, raw: str
) -> None:
    """El formato se comprueba antes que el tamaño: un valor enorme mal formado es 400."""
    response, calls = run_body_size("POST", path, raw)

    assert_api_error(response, 400, ApiReason.INVALID_REQUEST, main.MSG_INVALID_REQUEST)
    assert calls == []


@pytest.mark.parametrize(
    ("path", "limit", "message"),
    LIMITED_ROUTES,
    ids=[route[0].lstrip("/") for route in LIMITED_ROUTES],
)
def test_excessive_content_length_wins_over_other_request_problems(
    path: str, limit: int, message: str
) -> None:
    """El middleware solo mira cabeceras: el 413 llega antes que cualquier otro error."""
    extra_headers = [
        (b"content-type", b"text/plain"),
        (b"x-campo-invalido", b"a.txt"),
    ]

    response, calls = run_body_size("POST", path, str(limit + 1), extra_headers)

    assert_api_error(response, 413, ApiReason.PAYLOAD_TOO_LARGE, message)
    assert calls == []
