"""Esquemas Pydantic compartidos entre todas las capas de CodeMentor.

Define solo los contratos de datos que cruzan de una capa a otra.
No contiene lógica de negocio, ni acceso al almacenamiento, ni llamadas al modelo.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class Chunk(BaseModel):
    """Fragmento de código indexado, con lo necesario para poder citarlo.

    `kind` indica cómo se obtuvo el fragmento: "function", "class", "module"
    o "window" cuando el archivo no se pudo analizar y se troceó por líneas.
    """

    file_path: str
    symbol_name: str
    start_line: int
    end_line: int
    content: str
    kind: Literal["function", "class", "module", "window"]


class SearchResult(BaseModel):
    """Fragmento recuperado junto con su puntuación de relevancia (0 a 1)."""

    chunk: Chunk
    score: float


class SearchReason(StrEnum):
    """Motivo por el que una búsqueda no devuelve fragmentos."""

    EMPTY_INDEX = "empty_index"
    NO_RELEVANT = "no_relevant"
    EMPTY_QUERY = "empty_query"
    QUERY_TOO_LONG = "query_too_long"


class SearchResponse(BaseModel):
    """Resultado de una búsqueda.

    `reason` y `message` solo se rellenan cuando no hay fragmentos; el mensaje
    va en español para que la interfaz lo muestre tal cual.
    """

    results: list[SearchResult]
    reason: SearchReason | None = None
    message: str | None = None


class IndexReason(StrEnum):
    """Motivo por el que un archivo no se ha indexado."""

    EMPTY_CONTENT = "empty_content"
    TOO_LARGE = "too_large"
    TOO_MANY_CHUNKS = "too_many_chunks"
    EMBEDDING_FAILED = "embedding_failed"


class IndexResult(BaseModel):
    """Resultado de intentar indexar un archivo.

    El éxito se reconoce porque `reason` es `None`; no hay un booleano aparte.
    `chunks_indexed` cuenta los fragmentos de ese archivo (0 en un rechazo) y
    `total_chunks` es el total del índice después del reemplazo. `used_windows`
    solo es `True` cuando el archivo se troceó por ventanas. `message` es
    siempre obligatorio, también en el éxito, y va en español para que la
    interfaz lo muestre tal cual.
    """

    file_path: str
    chunks_indexed: int
    total_chunks: int
    used_windows: bool
    reason: IndexReason | None = None
    message: str


class ChatMessage(BaseModel):
    """Mensaje del historial de conversación, tal como lo aporta quien llama.

    Solo transporta el rol y el texto. No valida si el contenido está vacío,
    no lo recorta y no lo envía a nadie: esas reglas se aplican al preparar
    la llamada al modelo.
    """

    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """Pregunta del usuario junto con el historial previo de la conversación.

    El historial es opcional y cada instancia tiene su propia lista. No valida
    la pregunta (vacía o demasiado larga): eso lo decide la búsqueda, que
    devuelve su propio motivo.
    """

    message: str
    history: list[ChatMessage] = []


class Citation(BaseModel):
    """Referencia a un fragmento real del código indexado.

    Sirve para abrir el archivo y comprobar la respuesta: lleva el número de
    la marca (`F2` → 2), la ruta, el símbolo y el rango de líneas. No incluye
    el texto del fragmento ni la parte de la respuesta que respalda, y sus
    datos salen del fragmento entregado, no del texto del modelo.
    """

    number: int
    file_path: str
    symbol_name: str
    start_line: int
    end_line: int


class ChatReason(StrEnum):
    """Motivo por el que no se pudo dar una respuesta fundamentada.

    Los cuatro primeros valores coinciden con los de `SearchReason`, para
    poder convertir el motivo de la búsqueda sin una tabla intermedia.
    """

    EMPTY_QUERY = "empty_query"
    QUERY_TOO_LONG = "query_too_long"
    EMPTY_INDEX = "empty_index"
    NO_RELEVANT = "no_relevant"
    MISSING_API_KEY = "missing_api_key"
    INVALID_API_KEY = "invalid_api_key"
    API_TIMEOUT = "api_timeout"
    API_UNAVAILABLE = "api_unavailable"
    API_ERROR = "api_error"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    UNGROUNDED_ANSWER = "ungrounded_answer"


class ChatResponse(BaseModel):
    """Resultado de una pregunta, siempre con la misma forma.

    `reply` es texto en español listo para mostrar; `citations` solo se llena
    cuando la respuesta está fundamentada, y `reason` está ausente exactamente
    en ese caso. No decide el éxito ni redacta los mensajes: eso es del bot.
    """

    reply: str
    citations: list[Citation] = []
    reason: ChatReason | None = None


class UploadResponse(BaseModel):
    """Confirmación de un archivo indexado.

    Solo se usa cuando la indexación va bien: `file_path` es la ruta efectiva,
    `chunks_indexed` cuenta los fragmentos de ese archivo, `total_chunks` es el
    total del índice tras el reemplazo, `used_windows` indica si se troceó por
    ventanas y `message` es el aviso en español. Los rechazos usan
    `ErrorResponse`, así que aquí no hay `reason`. No indexa ni decide el
    éxito: eso es de `main.py`.
    """

    file_path: str
    chunks_indexed: int
    total_chunks: int
    used_windows: bool
    message: str


class ApiReason(StrEnum):
    """Motivo de un rechazo propio de la capa HTTP.

    Los motivos de las specs 002 (`IndexReason`) y 003 (`ChatReason`) se
    reutilizan sin cambiar su significado; este enum solo añade los que nacen
    al traducir HTTP. No decide estados ni redacta mensajes: eso es de
    `main.py`.
    """

    INVALID_REQUEST = "invalid_request"
    INVALID_PATH = "invalid_path"
    INVALID_EXTENSION = "invalid_extension"
    INVALID_ENCODING = "invalid_encoding"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    LENGTH_REQUIRED = "length_required"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    INTERNAL_ERROR = "internal_error"


class ErrorResponse(BaseModel):
    """Cuerpo único de error de la API.

    `message` es texto en español listo para mostrar y `reason` identifica el
    motivo, que puede ser un `ApiReason`, un `IndexReason` o un `ChatReason`.
    Por eso `reason` es `str` y no un enum. No valida reglas de negocio ni
    traduce motivos a estados HTTP: eso es de `main.py`.
    """

    message: str
    reason: str
