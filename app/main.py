"""Capa HTTP de CodeMentor.

Expone /health, /upload y /chat, además de la página y sus recursos estáticos
en / y /static. Solo interpreta la petición y delega en rag.py (indexado) y
bot.py (respuesta); la presentación vive en static/. No implementa chunking,
búsqueda ni llamadas al modelo.
"""

import logging
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Request,
    Response,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from app import bot, rag
from app.models import (
    ApiReason,
    ChatMessage,
    ChatReason,
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    IndexReason,
    IndexResult,
    UploadResponse,
)
from app.rag import MAX_FILE_BYTES

logger = logging.getLogger(__name__)

#: Margen del formulario multipart sobre el archivo (RF-17).
MULTIPART_MARGIN_BYTES = 4_096

#: Tamaño máximo del cuerpo de `POST /upload`, en bytes (RF-17).
UPLOAD_BODY_LIMIT = MAX_FILE_BYTES + MULTIPART_MARGIN_BYTES

#: Tamaño máximo del cuerpo de `POST /chat`, en bytes (RF-17).
CHAT_BODY_LIMIT = 262_144

#: Longitud máxima de la ruta de archivo efectiva (RF-4).
MAX_PATH_CHARS = 255

#: Archivo de entorno, relativo al directorio de trabajo (RF-19).
DOTENV_PATH = Path(".env")

#: Directorio de los recursos de la interfaz, resuelto desde este archivo.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

#: Mensajes propios de esta capa, fijados literalmente en el plan (RNF-4).
MSG_INVALID_REQUEST = "La petición no es válida. Revisa los datos enviados."
MSG_INVALID_PATH = (
    "La ruta del archivo no es válida: no puede estar vacía, superar 255 "
    "caracteres ni contener saltos de línea u otros caracteres de control."
)
MSG_INVALID_EXTENSION = "Solo se aceptan archivos de Python (.py)."
MSG_INVALID_ENCODING = (
    "No se pudo leer el archivo como texto UTF-8. Guárdalo con codificación "
    "UTF-8 y vuelve a subirlo."
)
MSG_UPLOAD_TOO_LARGE = (
    "La petición es demasiado grande: el límite son 1.052.672 bytes (1 MiB de "
    "archivo más el margen del formulario de subida)."
)
MSG_CHAT_TOO_LARGE = "El mensaje y el historial son demasiado grandes."
MSG_LENGTH_REQUIRED = "La petición debe indicar su tamaño (cabecera Content-Length)."
MSG_NOT_FOUND = "No existe esa ruta."
MSG_METHOD_NOT_ALLOWED = "Ese método no está permitido en esta ruta."
MSG_INTERNAL_ERROR = (
    "Ocurrió un error interno. Inténtalo de nuevo; si sigue fallando, revisa "
    "los registros."
)

#: Descripciones de la documentación automática (RF-23). Son texto de
#: documentación para `/docs`, no los mensajes de error que ve el usuario.
_DOC_METHOD_NOT_ALLOWED = "Este método no está permitido en esta ruta."
_DOC_UPLOAD_INVALID_REQUEST = (
    "La petición no es válida: revisa el formulario, la ruta o la codificación "
    "del archivo."
)
_DOC_CHAT_INVALID_REQUEST = (
    "La petición no es válida: revisa el formato del cuerpo y de la cabecera de tamaño."
)
_DOC_LENGTH_REQUIRED = (
    "Falta la cabecera Content-Length, necesaria para comprobar el tamaño "
    "antes de leer el cuerpo."
)
_DOC_UPLOAD_TOO_LARGE = (
    "El archivo o el formulario de subida superan el tamaño máximo permitido."
)
_DOC_CHAT_TOO_LARGE = "La pregunta o el historial superan el tamaño máximo permitido."
_DOC_UPLOAD_UNPROCESSABLE = (
    "El formulario no es válido o no incluye el campo de archivo obligatorio."
)
_DOC_CHAT_UNPROCESSABLE = (
    "El cuerpo JSON no es válido o no cumple el contrato de la petición."
)
_DOC_INTERNAL_ERROR = "Ocurrió un error interno; no se exponen detalles técnicos."
_DOC_API_ERROR = "El servicio del modelo respondió con un error."
_DOC_API_UNAVAILABLE = (
    "El servicio del modelo no está disponible o falta la clave de acceso."
)
_DOC_API_TIMEOUT = (
    "El servicio del modelo tardó demasiado y se agotó el tiempo de espera."
)

#: Respuestas de error declaradas en la documentación de `POST /upload` (RF-23).
_UPLOAD_ERROR_RESPONSES: dict[int, dict[str, object]] = {
    400: {"model": ErrorResponse, "description": _DOC_UPLOAD_INVALID_REQUEST},
    411: {"model": ErrorResponse, "description": _DOC_LENGTH_REQUIRED},
    413: {"model": ErrorResponse, "description": _DOC_UPLOAD_TOO_LARGE},
    422: {"model": ErrorResponse, "description": _DOC_UPLOAD_UNPROCESSABLE},
    500: {"model": ErrorResponse, "description": _DOC_INTERNAL_ERROR},
}

#: Respuestas de error declaradas en la documentación de `POST /chat` (RF-23).
_CHAT_ERROR_RESPONSES: dict[int, dict[str, object]] = {
    400: {"model": ErrorResponse, "description": _DOC_CHAT_INVALID_REQUEST},
    411: {"model": ErrorResponse, "description": _DOC_LENGTH_REQUIRED},
    413: {"model": ErrorResponse, "description": _DOC_CHAT_TOO_LARGE},
    422: {"model": ErrorResponse, "description": _DOC_CHAT_UNPROCESSABLE},
    500: {"model": ErrorResponse, "description": _DOC_INTERNAL_ERROR},
    502: {"model": ErrorResponse, "description": _DOC_API_ERROR},
    503: {"model": ErrorResponse, "description": _DOC_API_UNAVAILABLE},
    504: {"model": ErrorResponse, "description": _DOC_API_TIMEOUT},
}

#: Categorías Unicode que no se aceptan en una ruta (RF-4).
_FORBIDDEN_PATH_CATEGORIES = frozenset({"Cc", "Zl", "Zp"})

#: Estado HTTP de cada motivo de rechazo del indexado (RF-7).
_INDEX_STATUS: dict[IndexReason, int] = {
    IndexReason.EMPTY_CONTENT: 400,
    IndexReason.TOO_LARGE: 413,
    IndexReason.TOO_MANY_CHUNKS: 413,
    IndexReason.EMBEDDING_FAILED: 500,
}

#: Estado HTTP de cada motivo de fallo del chat (RF-11).
_CHAT_STATUS: dict[ChatReason, int] = {
    ChatReason.EMPTY_QUERY: 422,
    ChatReason.QUERY_TOO_LONG: 422,
    ChatReason.MISSING_API_KEY: 503,
    ChatReason.INVALID_API_KEY: 503,
    ChatReason.API_UNAVAILABLE: 503,
    ChatReason.API_TIMEOUT: 504,
    ChatReason.API_ERROR: 502,
}

#: Motivos del chat que son un resultado sin respuesta, no un error (RF-10).
_CHAT_OK_REASONS: frozenset[ChatReason] = frozenset(
    {
        ChatReason.EMPTY_INDEX,
        ChatReason.NO_RELEVANT,
        ChatReason.INSUFFICIENT_CONTEXT,
        ChatReason.UNGROUNDED_ANSWER,
    }
)

#: Mensaje de cada motivo de rechazo de ruta (RNF-4). Se reutilizan las
#: constantes ya fijadas para no duplicar los literales.
_PATH_MESSAGES: dict[ApiReason, str] = {
    ApiReason.INVALID_PATH: MSG_INVALID_PATH,
    ApiReason.INVALID_EXTENSION: MSG_INVALID_EXTENSION,
}


def _error(
    status: int,
    reason: ApiReason | IndexReason | ChatReason | str,
    message: str,
) -> JSONResponse:
    """Construye el cuerpo único de error con el estado indicado.

    Traduce el motivo a su valor de texto y usa el mensaje tal cual. No elige
    el estado ni redacta el mensaje: eso lo decide quien la llama.
    """
    payload = ErrorResponse(message=message, reason=str(reason))
    return JSONResponse(status_code=status, content=payload.model_dump())


def _validate_path(path: str) -> ApiReason | None:
    """Aplica las reglas de ruta de RF-4 y RF-5, en ese orden.

    Devuelve el motivo del rechazo o `None` si la ruta vale. No recorta ni
    normaliza el valor: solo lo comprueba.
    """
    if path.strip() == "" or len(path) > MAX_PATH_CHARS:
        return ApiReason.INVALID_PATH

    if any(
        unicodedata.category(character) in _FORBIDDEN_PATH_CATEGORIES
        for character in path
    ):
        return ApiReason.INVALID_PATH

    if not path.lower().endswith(".py"):
        return ApiReason.INVALID_EXTENSION

    return None


def _decode_source(raw: bytes) -> str | None:
    """Decodifica el archivo como UTF-8 descartando un BOM inicial (RF-6).

    Devuelve `None` si los bytes no son UTF-8 válido. No sustituye caracteres
    ni mide tamaños: solo decodifica.
    """
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _status_for_index(reason: IndexReason) -> int:
    """Traduce un motivo del indexado a su estado HTTP (RF-7).

    Un motivo sin estado asignado lanza `KeyError`, para que la prueba
    exhaustiva lo detecte en lugar de responder un estado inventado.
    """
    return _INDEX_STATUS[reason]


def _status_for_chat(reason: ChatReason | None) -> int:
    """Traduce un motivo del chat a su estado HTTP (RF-10 y RF-11).

    Devuelve 200 para una respuesta fundamentada y para los resultados sin
    respuesta; los demás motivos están en la tabla de fallos. Un motivo
    desconocido lanza `KeyError`, nunca cae en 200 por omisión.
    """
    if reason is None or reason in _CHAT_OK_REASONS:
        return 200

    return _CHAT_STATUS[reason]


def _limit_for(method: str, path: str) -> int | None:
    """Devuelve el límite de cuerpo de la ruta exacta, o `None` si no aplica.

    Solo `POST /upload` y `POST /chat` leen cuerpo y tienen límite. La
    comparación es por método y ruta exactos, nunca por prefijo: `GET /upload`,
    `/health` o una ruta inexistente no lo tienen.
    """
    if (method, path) == ("POST", "/upload"):
        return UPLOAD_BODY_LIMIT

    if (method, path) == ("POST", "/chat"):
        return CHAT_BODY_LIMIT

    return None


async def _check_body_size(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Rechaza por `Content-Length` antes de leer el cuerpo (RF-16 y RF-17).

    Solo comprueba esa cabecera en `POST /upload` y `POST /chat`: no lee el
    cuerpo, no decide nada de la ruta y no toca las demás rutas. Mira
    cabeceras porque el cuerpo multipart o JSON ya se habría cargado en
    memoria o disco cuando el enrutado lo procesa.
    """
    limit = _limit_for(request.method, request.url.path)
    if limit is None:
        return await call_next(request)

    raw = request.headers.get("content-length")
    if raw is None:
        return _error(411, ApiReason.LENGTH_REQUIRED, MSG_LENGTH_REQUIRED)

    if not (raw.isascii() and raw.isdigit()):
        return _error(400, ApiReason.INVALID_REQUEST, MSG_INVALID_REQUEST)

    # La longitud se mide antes de convertir: en Python 3.11+ un `int` de más
    # de 4.300 dígitos lanza `ValueError`.
    if len(raw) > 15 or int(raw) > limit:
        message = (
            MSG_UPLOAD_TOO_LARGE
            if request.url.path == "/upload"
            else MSG_CHAT_TOO_LARGE
        )
        return _error(413, ApiReason.PAYLOAD_TOO_LARGE, message)

    return await call_next(request)


async def _on_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Traduce un error de validación del framework a 422 `invalid_request`.

    No incluye `exc.errors()` ni la petición: el detalle de validación puede
    contener fragmentos de lo enviado (RNF-3).
    """
    return _error(422, ApiReason.INVALID_REQUEST, MSG_INVALID_REQUEST)


async def _on_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Traduce 404 y 405 del framework y responde con el formato de error.

    Cualquier otro estado conserva su código pero usa `invalid_request`, que es
    el único motivo propio para un error HTTP genérico. No registra ni devuelve
    `exc.detail`, porque puede describir la petición.
    """
    if exc.status_code == 404:
        return _error(404, ApiReason.NOT_FOUND, MSG_NOT_FOUND)

    if exc.status_code == 405:
        return _error(405, ApiReason.METHOD_NOT_ALLOWED, MSG_METHOD_NOT_ALLOWED)

    return _error(exc.status_code, ApiReason.INVALID_REQUEST, MSG_INVALID_REQUEST)


async def _on_unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Responde 500 `internal_error` sin exponer detalles del error.

    Registra solo el tipo de la excepción: `str(exc)` y la traza pueden llevar
    contenido, rutas o la pregunta (RNF-3). No marca el error como resuelto
    para el servidor web, que sigue siendo quien decide qué registra.
    """
    logger.error("error interno: %s", type(exc).__name__)
    return _error(500, ApiReason.INTERNAL_ERROR, MSG_INTERNAL_ERROR)


def _load_env(path: Path = DOTENV_PATH) -> None:
    """Carga las variables de `path` sin pisar las que ya están definidas.

    La ruta es explícita (relativa al directorio de trabajo) para no depender
    de la búsqueda automática de `load_dotenv` ni cargar sin querer el `.env`
    real durante las pruebas. Si el archivo no existe, no hace nada; con
    `override=False`, el entorno siempre gana (RF-19, RF-21).
    """
    if path.exists():
        load_dotenv(dotenv_path=path, override=False)


def _warm_up() -> None:
    """Intenta cargar el modelo de embeddings sin impedir el arranque.

    Si falla, registra solo el tipo de la excepción y sigue: el servicio queda
    disponible y la primera petición que necesite el modelo lo reintenta
    (RF-20). No registra `str(exc)` ni la traza, que podrían llevar datos de la
    petición (RNF-3).
    """
    try:
        rag.warm_up()
    except Exception as exc:  # noqa: BLE001 - RF-20: cualquier fallo solo se registra
        logger.warning("no se pudo calentar el modelo: %s", type(exc).__name__)


async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Carga el entorno y calienta el modelo antes de aceptar peticiones.

    Se ejecuta dentro del `lifespan` de la aplicación, de modo que el servidor
    no atiende ninguna petición, `/health` incluida, hasta que termina (RF-1).
    """
    _load_env()
    _warm_up()
    yield


app = FastAPI(
    title="CodeMentor: asistente de código",
    description="Asistente RAG que responde preguntas sobre tu código Python.",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_exception_handler(RequestValidationError, _on_validation_error)
app.add_exception_handler(StarletteHTTPException, _on_http_exception)
app.add_exception_handler(Exception, _on_unhandled)
app.middleware("http")(_check_body_size)
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")


@app.get("/", include_in_schema=False)
async def index_page() -> FileResponse:
    """Sirve la página de la interfaz desde `static/index.html`.

    Solo devuelve el archivo: no redacta textos, no valida datos ni consulta el
    índice. Queda fuera de la documentación automática porque no forma parte
    del contrato de la API (RF-23 de la 004).
    """
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """Sirve el icono SVG también en la ruta automática `/favicon.ico`.

    Devuelve el mismo archivo que `/static/favicon.svg` para que el navegador
    no reciba un 404 al pedir el icono (RF-2 y RF-32). No transforma el SVG.
    """
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


def get_index_file() -> Callable[[str, str], IndexResult]:
    """Devuelve la capacidad de indexado de `rag.py` para esta petición.

    Es el punto donde las pruebas sustituyen el indexado con
    `app.dependency_overrides` o `monkeypatch`: se lee el atributo del módulo
    en cada petición, no una copia hecha al importar. No indexa nada por sí
    misma.
    """
    return rag.index_file


def get_answer() -> Callable[[str, list[ChatMessage]], ChatResponse]:
    """Devuelve la capacidad de respuesta de `bot.py` para esta petición.

    Es el punto donde las pruebas sustituyen la respuesta con
    `app.dependency_overrides` o `monkeypatch`: se lee el atributo del módulo
    en cada petición, no una copia hecha al importar. No responde nada por sí
    misma.
    """
    return bot.answer


@app.get(
    "/health",
    summary="Comprobación del estado del servicio",
    description=(
        "Indica si la API está viva sin depender de la clave, del modelo ni del índice."
    ),
    responses={
        405: {"model": ErrorResponse, "description": _DOC_METHOD_NOT_ALLOWED},
    },
)
async def health() -> dict[str, str]:
    """Comprueba que la API está viva."""
    return {"status": "ok"}


@app.post(
    "/upload",
    response_model=UploadResponse,
    summary="Indexación de un archivo de Python",
    description=(
        "Recibe un archivo .py con su ruta opcional y lo añade al índice para "
        "poder consultarlo."
    ),
    responses=_UPLOAD_ERROR_RESPONSES,
)
def upload(
    file: Annotated[UploadFile, File()],
    index_file: Annotated[Callable[[str, str], IndexResult], Depends(get_index_file)],
    path: Annotated[str | None, Form()] = None,
) -> UploadResponse | JSONResponse:
    """Valida la ruta efectiva, decodifica el archivo y delega el indexado.

    La ruta efectiva es `path` si llega con contenido y, si no, el nombre del
    archivo; se entrega tal cual, sin recortar ni normalizar (RF-3). Valida
    ruta y extensión, decodifica como UTF-8 sin BOM y traduce el resultado de
    `index_file` a `UploadResponse` o a un rechazo con su estado. No trocea,
    no calcula embeddings, no toca el almacén ni busca: eso es de `rag.py`.
    """
    effective_path = path if path else (file.filename or "")

    reason = _validate_path(effective_path)
    if reason is not None:
        return _error(400, reason, _PATH_MESSAGES[reason])

    source = _decode_source(file.file.read())
    if source is None:
        return _error(400, ApiReason.INVALID_ENCODING, MSG_INVALID_ENCODING)

    result = index_file(effective_path, source)
    if result.reason is None:
        return UploadResponse(
            file_path=result.file_path,
            chunks_indexed=result.chunks_indexed,
            total_chunks=result.total_chunks,
            used_windows=result.used_windows,
            message=result.message,
        )

    return _error(
        _status_for_index(result.reason),
        result.reason.value,
        result.message,
    )


@app.post(
    "/chat",
    response_model=ChatResponse,
    summary="Consulta sobre el código indexado",
    description=(
        "Responde una pregunta con el contexto del código indexado y devuelve "
        "las citas de los fragmentos usados."
    ),
    responses=_CHAT_ERROR_RESPONSES,
)
def chat(
    payload: ChatRequest,
    answer: Annotated[
        Callable[[str, list[ChatMessage]], ChatResponse], Depends(get_answer)
    ],
) -> ChatResponse | JSONResponse:
    """Responde una pregunta delegando en la capacidad de la spec 003.

    Entrega el mensaje y el historial tal cual los recibe y traduce el motivo
    del resultado a su estado HTTP: 200 para una respuesta fundamentada y para
    los resultados sin respuesta, y el formato de error con el `reply` como
    `message` en los fallos. No busca, no redacta ni reescribe los mensajes:
    eso es de `bot.py`.
    """
    result = answer(payload.message, payload.history)

    status = _status_for_chat(result.reason)
    if status == 200:
        return result

    return _error(status, result.reason.value, result.reply)
