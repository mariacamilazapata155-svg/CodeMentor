"""Chunking de código, generación de embeddings y búsqueda semántica.

Es el corazón del RAG: convierte archivos en fragmentos citables y encuentra
los más relevantes para una pregunta.

No sabe nada de HTTP, no arma prompts y no llama al modelo de lenguaje.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from functools import lru_cache
from typing import TYPE_CHECKING, Literal, NamedTuple

import numpy as np

from app.models import (
    Chunk,
    IndexReason,
    IndexResult,
    SearchReason,
    SearchResponse,
)
from app.storage import store

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

MAX_RESULTS = 5
MIN_SCORE = 0.30
MAX_QUERY_LENGTH = 1000

# Indexado: límite de tamaño de un archivo, en bytes UTF-8 (RF-14).
MAX_FILE_BYTES = 1_048_576

# Indexado: tope de fragmentos que puede producir un archivo (RF-21).
MAX_CHUNKS_PER_FILE = 1_000

# Troceado: tamaño máximo de un trozo de bloque de módulo (RF-20).
MAX_MODULE_BLOCK_LINES = 120

# Troceado: tamaño de ventana del plan B para contenido no analizable (RF-8).
WINDOW_LINES = 60

_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")

EMPTY_INDEX_MESSAGE = (
    "Todavía no hay código indexado. Sube un archivo .py para poder buscar en él."
)
NO_RELEVANT_MESSAGE = (
    "No encontré fragmentos relevantes para esa consulta. Prueba con otras palabras."
)
EMPTY_QUERY_MESSAGE = (
    "La consulta es obligatoria: escribe una pregunta sobre el código."
)
QUERY_TOO_LONG_MESSAGE = (
    "La consulta es demasiado larga: el límite es de "
    f"{MAX_QUERY_LENGTH:,} caracteres.".replace(",", ".")
)

EMPTY_CONTENT_MESSAGE = (
    "El archivo está vacío o solo contiene espacios en blanco, "
    "así que no se ha indexado."
)
TOO_LARGE_MESSAGE = (
    "El archivo ocupa {size} bytes y el límite es de {limit} bytes (1 MiB), "
    "así que no se ha indexado."
)
TOO_MANY_CHUNKS_MESSAGE = (
    "El archivo produciría {produced} y el tope es de {limit} por archivo, "
    "así que no se ha indexado."
)
EMBEDDING_FAILED_MESSAGE = (
    "No se pudo preparar el archivo para la búsqueda: es un archivo no "
    "indexable y no se ha añadido nada al índice."
)

INDEX_SUCCESS_MESSAGE = (
    "Archivo indexado: {chunks} de este archivo; el índice tiene {total} en total."
)
WINDOWS_CHUNKING_NOTE = (
    "Como el archivo no se pudo analizar como Python, se troceó en ventanas de "
    "líneas y ese troceado es aproximado."
)

_STATIC_REJECTION_MESSAGES = {
    IndexReason.EMPTY_CONTENT: EMPTY_CONTENT_MESSAGE,
    IndexReason.EMBEDDING_FAILED: EMBEDDING_FAILED_MESSAGE,
}


class _Definition(NamedTuple):
    """Definición que genera un fragmento propio, con su nombre cualificado.

    Es un detalle interno del troceado, no un contrato entre capas: por eso no
    vive en `models.py`. `node` es el nodo de `ast` de la definición.
    """

    symbol_name: str
    kind: Literal["function", "class"]
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def chunk_python_file(source: str, file_path: str) -> list[Chunk]:
    """Parte el código de un archivo en chunks citables, sin tocar el índice.

    Con Python válido devuelve un fragmento por definición (con decoradores y
    comentarios pegados) más un fragmento `module` por cada bloque de código de
    nivel de módulo, de modo que ninguna línea con código queda fuera. Si el
    texto no se puede analizar (prosa, otro lenguaje, sintaxis o indentación
    rotas), no aborta: lo parte en ventanas de `WINDOW_LINES` líneas. La ruta se
    copia tal cual y el resultado va ordenado según RF-17.

    Es pura y determinista: mismo texto y misma ruta dan los mismos fragmentos.
    No calcula embeddings, no escribe en el almacén, no toca el disco y no
    ejecuta el código recibido.
    """
    lines = _split_lines(source)
    tree = _parse_module(source)
    if tree is None:
        return _window_chunks(file_path, lines)

    chunks, covered = _symbol_chunks(lines, tree, file_path)
    chunks.extend(_module_blocks(lines, covered, file_path))
    return _sort_chunks(chunks)


def index_file(file_path: str, source: str) -> IndexResult:
    """Indexa un archivo: valida, trocea, calcula embeddings y reemplaza la ruta.

    Es la única función de la capacidad que escribe en el índice, y lo hace en
    un solo punto (`store.replace_path`) cuando ya está todo calculado: si hay un
    rechazo o falla el modelo, la versión anterior de esa ruta queda intacta
    (RF-19, RF-22, RF-25). Devuelve el motivo, el mensaje en español, los
    fragmentos del archivo y el total del índice posterior al reemplazo. No lee
    del disco, no valida extensiones, no ejecuta el código recibido y no
    responde preguntas: para eso están la capa de subida y `search`.
    """
    invalid = _validate_content(source)
    if invalid is not None:
        return _rejected(file_path, *invalid)

    chunks = chunk_python_file(source, file_path)
    if _too_many_chunks(len(chunks)):
        reason = IndexReason.TOO_MANY_CHUNKS
        return _rejected(
            file_path, reason, _rejection_message(reason, produced=len(chunks))
        )

    try:
        matrix = _embed_chunks(chunks)
        store.replace_path(file_path, chunks, matrix)
    except Exception:  # noqa: BLE001 - RF-19: cualquier fallo acaba en el mismo rechazo
        reason = IndexReason.EMBEDDING_FAILED
        return _rejected(file_path, reason, _rejection_message(reason))

    used_windows = any(chunk.kind == "window" for chunk in chunks)
    total_chunks = store.count
    return IndexResult(
        file_path=file_path,
        chunks_indexed=len(chunks),
        total_chunks=total_chunks,
        used_windows=used_windows,
        reason=None,
        message=_success_message(
            chunks_indexed=len(chunks),
            total_chunks=total_chunks,
            used_windows=used_windows,
        ),
    )


def search(query: str) -> SearchResponse:
    """Busca los chunks más parecidos a la pregunta del usuario.

    Valida y normaliza la consulta, calcula su embedding, pide candidatos al
    store y aplica el umbral. Devuelve el motivo y el mensaje en español cuando
    no hay resultados. No redacta la respuesta ni llama a Claude.
    """
    invalid = _validate_query(query)
    if invalid is not None:
        reason, message = invalid
        return SearchResponse(results=[], reason=reason, message=message)

    if store.count == 0:
        return SearchResponse(
            results=[],
            reason=SearchReason.EMPTY_INDEX,
            message=EMPTY_INDEX_MESSAGE,
        )

    candidates = store.search(_embed_query(query), top_k=MAX_RESULTS)
    results = [result for result in candidates if _is_relevant(result.score)]

    if not results:
        return SearchResponse(
            results=[],
            reason=SearchReason.NO_RELEVANT,
            message=NO_RELEVANT_MESSAGE,
        )

    return SearchResponse(results=results)


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Carga el modelo de embeddings una sola vez por proceso, de forma diferida.

    Se importa dentro de la función para que `import app.rag` no arrastre
    `sentence_transformers` ni intente descargar nada.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def warm_up() -> None:
    """Carga el modelo de embeddings si aún no está cargado, sin calcular nada.

    Solo pide el modelo a `_get_model`, que es quien aplica el `lru_cache`: la
    primera llamada del proceso lo descarga y lo construye, y las siguientes lo
    reutilizan. No indexa, no busca, no calcula embeddings y no devuelve el
    modelo: su único efecto es dejar la carga hecha antes de la primera petición.
    """
    _get_model()


def _embed_query(query: str) -> np.ndarray:
    """Calcula el vector normalizado de la consulta ya normalizada."""
    vector = _get_model().encode(_normalize_query(query), normalize_embeddings=True)
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(array))
    if norm == 0:
        return array
    return array / norm


def _embed_chunks(chunks: list[Chunk]) -> np.ndarray:
    """Calcula una fila normalizada por fragmento, con su texto exacto.

    Envía al modelo el `content` de cada fragmento sin recortarlo (RNF-7) y
    devuelve una matriz `float32` recién construida con una fila por fragmento.
    Aunque el modelo ya normalice, cada fila se renormaliza para garantizar
    `|norma - 1| <= 1e-5` (RF-11). No trocea, no escribe en el índice y no
    ejecuta el código recibido.
    """
    if not chunks:
        return np.zeros((0, 0), dtype=np.float32)
    texts = [chunk.content for chunk in chunks]
    vectors = _get_model().encode(texts, normalize_embeddings=True)
    matrix = np.array(vectors, dtype=np.float32).reshape(len(chunks), -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    np.divide(matrix, norms, out=matrix, where=norms > 0)
    return matrix


def _is_relevant(score: float) -> bool:
    """Indica si una puntuación alcanza el umbral mínimo."""
    return round(score, 6) >= MIN_SCORE


def _validate_query(query: str) -> tuple[SearchReason, str] | None:
    """Comprueba que la consulta no esté vacía ni supere el límite de longitud.

    Devuelve el motivo y el mensaje en español si no es válida, o `None` si lo es.
    Primero descarta el vacío y después la longitud, sobre el texto recibido.
    """
    if not query.strip():
        return (SearchReason.EMPTY_QUERY, EMPTY_QUERY_MESSAGE)
    if len(query) > MAX_QUERY_LENGTH:
        return (SearchReason.QUERY_TOO_LONG, QUERY_TOO_LONG_MESSAGE)
    return None


def _validate_content(source: str) -> tuple[IndexReason, str] | None:
    """Comprueba que el contenido no esté vacío ni supere el tamaño permitido.

    Primero descarta el vacío o solo blancos y después el tamaño en bytes UTF-8,
    en ese orden (RF-13, RF-14). Devuelve el motivo y el mensaje en español si
    no es indexable, o `None` si lo es. No trocea, no calcula embeddings y no
    toca el índice.
    """
    if not source.strip():
        return (
            IndexReason.EMPTY_CONTENT,
            _rejection_message(IndexReason.EMPTY_CONTENT),
        )
    size = len(source.encode("utf-8"))
    if size > MAX_FILE_BYTES:
        return (
            IndexReason.TOO_LARGE,
            _rejection_message(IndexReason.TOO_LARGE, size=size),
        )
    return None


def _too_many_chunks(count: int) -> bool:
    """Indica si `count` fragmentos superan el tope por archivo (RF-21).

    Es el único sitio donde se decide el tope: la comprobación se hace antes de
    calcular embeddings, para no gastar el modelo en un archivo que se rechaza.
    """
    return count > MAX_CHUNKS_PER_FILE


def _normalize_query(query: str) -> str:
    """Pasa la consulta a minúsculas, sin tildes y con espacios simples.

    Es el texto con el que se calcula la relevancia, para que mayúsculas,
    acentos y espacios repetidos no cambien los resultados.
    """
    decomposed = unicodedata.normalize("NFKD", query.lower())
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(without_accents.split())


def _split_lines(source: str) -> list[str]:
    """Parte el texto en líneas conservando el separador de cada una.

    Solo `\\n`, `\\r\\n` y `\\r` abren una línea nueva; cualquier otro carácter
    de control, como `\\f`, se queda dentro de la línea. Un archivo que termina
    en salto de línea no produce una línea vacía de más.
    """
    lines: list[str] = []
    start = 0
    for match in _LINE_BREAK_RE.finditer(source):
        lines.append(source[start : match.end()])
        start = match.end()
    if start < len(source):
        lines.append(source[start:])
    return lines


def _line_body(line: str) -> str:
    """Devuelve la línea sin su separador final, sin recortar nada más.

    Quita un único separador y comprueba `\\r\\n` antes que `\\r` y `\\n`.
    """
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\r", "\n")):
        return line[:-1]
    return line


def _chunk_text(lines: list[str], start_line: int, end_line: int) -> str:
    """Devuelve el texto exacto de las líneas `start_line` a `end_line`.

    Es la subcadena real del archivo desde el inicio de la primera línea hasta
    el final de la última, sin el separador que cierra esa última línea y sin
    recortar espacios ni líneas de los bordes.
    """
    return "".join(lines[start_line - 1 : end_line - 1]) + _line_body(
        lines[end_line - 1]
    )


def _format_number(value: int) -> str:
    """Formatea un entero con punto como separador de miles (1.048.576)."""
    return f"{value:,}".replace(",", ".")


def _fragment_count(count: int) -> str:
    """Expresa una cantidad de fragmentos con su cifra y el plural correcto."""
    unit = "fragmento" if count == 1 else "fragmentos"
    return f"{_format_number(count)} {unit}"


def _success_message(
    *, chunks_indexed: int, total_chunks: int, used_windows: bool
) -> str:
    """Devuelve el mensaje en español de una indexación con éxito.

    Incluye los fragmentos de ese archivo y el total del índice después del
    reemplazo (RF-24). Solo añade el aviso de troceado aproximado cuando
    `used_windows` es `True` (RF-10, RNF-3). No toca el índice ni calcula nada.
    """
    message = INDEX_SUCCESS_MESSAGE.format(
        chunks=_fragment_count(chunks_indexed),
        total=_fragment_count(total_chunks),
    )
    if not used_windows:
        return message
    return f"{message} {WINDOWS_CHUNKING_NOTE}"


def _rejection_message(
    reason: IndexReason, *, size: int | None = None, produced: int | None = None
) -> str:
    """Devuelve el mensaje en español de un rechazo de indexación.

    `size` es obligatorio para `TOO_LARGE` y `produced` para
    `TOO_MANY_CHUNKS`; si falta, es un fallo de programación y se avisa con
    `ValueError`. No calcula embeddings, no trocea y no toca el índice.
    """
    if reason in _STATIC_REJECTION_MESSAGES:
        return _STATIC_REJECTION_MESSAGES[reason]
    if reason is IndexReason.TOO_LARGE:
        if size is None:
            raise ValueError("el rechazo por tamaño necesita el tamaño recibido")
        return TOO_LARGE_MESSAGE.format(
            size=_format_number(size),
            limit=_format_number(MAX_FILE_BYTES),
        )
    if reason is IndexReason.TOO_MANY_CHUNKS:
        if produced is None:
            raise ValueError("el rechazo por tope necesita la cantidad producida")
        return TOO_MANY_CHUNKS_MESSAGE.format(
            produced=_fragment_count(produced),
            limit=_fragment_count(MAX_CHUNKS_PER_FILE),
        )
    raise ValueError(f"motivo de rechazo sin mensaje: {reason}")


def _rejected(file_path: str, reason: IndexReason, message: str) -> IndexResult:
    """Construye el resultado de un rechazo sin tocar el índice.

    Recibe el motivo y el mensaje ya redactado en español, deja
    `chunks_indexed` en 0 y cuenta los fragmentos que siguen en el índice. No
    escribe, no embebe, no decide el motivo y no trocea nada.
    """
    return IndexResult(
        file_path=file_path,
        chunks_indexed=0,
        total_chunks=store.count,
        used_windows=False,
        reason=reason,
        message=message,
    )


def _parse_module(source: str) -> ast.Module | None:
    """Analiza el texto como Python y devuelve su árbol, o `None` si no puede.

    Solo compila la sintaxis: no ejecuta, no importa y no evalúa el contenido
    recibido. Un error de sintaxis, de indentación o de bytes nulos se trata
    como contenido no analizable, nunca como un fallo de la indexación.
    """
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def _string_lines(tree: ast.Module) -> set[int]:
    """Devuelve las líneas que cubren cadenas literales de varias líneas.

    `ast` no expone los comentarios, así que el troceado los reconoce por el
    texto; sin esta protección, una línea que empiece por `#` dentro de una
    cadena triple se confundiría con un comentario pegado (RF-2, RF-3). Se
    protegen las constantes `str`/`bytes` y las `f-string` (`JoinedStr`) que
    ocupan más de una línea. Se resuelve con el árbol y no con `tokenize`
    porque `tokenize` no numera bien los finales de línea `\\r` aislados.
    """
    protected: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) or (
            isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))
        ):
            end = node.end_lineno
            if end is not None and end > node.lineno:
                protected.update(range(node.lineno, end + 1))
    return protected


def _iter_definitions(tree: ast.Module) -> list[_Definition]:
    """Devuelve las definiciones que generan fragmento propio, en orden.

    Recorre el nivel de módulo, incluidos sus bloques condicionales, y el cuerpo
    directo de cada clase. No desciende dentro de funciones ni dentro de los
    bloques condicionales de una clase: esas definiciones quedan en su contenedor.
    """
    definitions: list[_Definition] = []
    _collect_module_level(tree.body, "", definitions)
    return definitions


def _child_bodies(node: ast.AST) -> list[list[ast.stmt]]:
    """Devuelve los cuerpos de un bloque de módulo que hay que seguir recorriendo.

    Cubre `if`, `try` (con sus `except`, `else` y `finally`), `with`, `for`,
    `while` y `match`. Para cualquier otro nodo devuelve una lista vacía, de
    modo que no se desciende en funciones ni en expresiones.
    """
    if isinstance(node, ast.If):
        return [node.body, node.orelse]
    if isinstance(node, (ast.Try, ast.TryStar)):
        bodies = [node.body, node.orelse, node.finalbody]
        bodies.extend(handler.body for handler in node.handlers)
        return bodies
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
        return [node.body, node.orelse]
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return [node.body]
    if isinstance(node, ast.Match):
        return [case.body for case in node.cases]
    return []


def _collect_module_level(
    body: list[ast.stmt], prefix: str, out: list[_Definition]
) -> None:
    """Añade las definiciones de un cuerpo de nivel de módulo a `out`.

    Los bloques condicionales se recorren como si fueran de nivel superior; las
    funciones no se abren, así que lo definido dentro de ellas no se añade.
    """
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(_Definition(prefix + node.name, "function", node))
        elif isinstance(node, ast.ClassDef):
            name = prefix + node.name
            out.append(_Definition(name, "class", node))
            _collect_class_body(node.body, f"{name}.", out)
        else:
            for child in _child_bodies(node):
                _collect_module_level(child, prefix, out)


def _collect_class_body(
    body: list[ast.stmt], prefix: str, out: list[_Definition]
) -> None:
    """Añade las definiciones del cuerpo directo de una clase a `out`.

    Solo mira los nodos de primer nivel del cuerpo: lo que esté dentro de un
    `if`, `try` o `with` de la clase se ignora porque queda en su fragmento.
    """
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(_Definition(prefix + node.name, "function", node))
        elif isinstance(node, ast.ClassDef):
            name = prefix + node.name
            out.append(_Definition(name, "class", node))
            _collect_class_body(node.body, f"{name}.", out)


def _definition_start(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    lines: list[str],
    string_lines: set[int] | None = None,
) -> int:
    """Devuelve la primera línea del fragmento: decoradores y comentarios pegados.

    Parte del primer decorador si lo hay y sube por el grupo de comentarios
    consecutivos pegado encima. No incluye comentarios separados por una línea
    en blanco ni líneas que no sean comentarios reales: `string_lines` protege
    las que están dentro de una cadena de varias líneas.
    """
    first = node.lineno
    if node.decorator_list:
        first = min(node.lineno, *(item.lineno for item in node.decorator_list))
    return _attached_comment_start(lines, first, string_lines)


def _attached_comment_start(
    lines: list[str],
    first_line: int,
    string_lines: set[int] | None = None,
) -> int:
    """Sube mientras la línea anterior sea solo un comentario pegado.

    Una línea en blanco, una línea con código o una línea de dentro de una
    cadena de varias líneas (`string_lines`) corta el grupo. Recibe y devuelve
    números de línea desde 1; no modifica la lista de líneas.
    """
    protected = string_lines or set()
    start = first_line
    while (
        start > 1
        and (start - 1) not in protected
        and _line_body(lines[start - 2]).strip().startswith("#")
    ):
        start -= 1
    return start


def _make_chunk(
    file_path: str,
    symbol_name: str,
    kind: Literal["function", "class", "module", "window"],
    start_line: int,
    end_line: int,
    lines: list[str],
) -> Chunk:
    """Construye el fragmento con el texto exacto de su rango de líneas.

    No recorta el contenido, no calcula embeddings y no decide el rango: todo
    eso lo recibe ya resuelto.
    """
    return Chunk(
        file_path=file_path,
        symbol_name=symbol_name,
        start_line=start_line,
        end_line=end_line,
        content=_chunk_text(lines, start_line, end_line),
        kind=kind,
    )


def _sort_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """Ordena los fragmentos según RF-17, de forma estable y determinista.

    Primero por línea inicial ascendente, después por línea final descendente
    (el contenedor precede a su contenido) y, si persiste el empate, por nombre
    de símbolo alfabético. No modifica la lista recibida.
    """
    return sorted(
        chunks,
        key=lambda chunk: (chunk.start_line, -chunk.end_line, chunk.symbol_name),
    )


def _module_blocks(lines: list[str], covered: set[int], file_path: str) -> list[Chunk]:
    """Convierte el código de nivel de módulo en fragmentos `module`.

    Recibe las líneas del archivo y el conjunto de líneas ya cubiertas por los
    fragmentos de símbolo (ambos numerados desde 1) y devuelve un fragmento por
    cada racha contigua de líneas no cubiertas, sin las líneas en blanco de sus
    bordes y partida en trozos de hasta `MAX_MODULE_BLOCK_LINES` líneas cuando
    el bloque resulta más largo. Los trozos partidos se numeran `module#N` con
    un contador único que solo avanza al partir; los bloques enteros se llaman
    `module`. No trocea símbolos, no calcula `covered`, no ordena el resultado
    y no modifica ni las líneas ni el conjunto recibidos.
    """
    chunks: list[Chunk] = []
    counter = 0
    first = 1
    while first <= len(lines):
        if first in covered:
            first += 1
            continue
        last = first
        while last < len(lines) and (last + 1) not in covered:
            last += 1
        start, end = _trim_blank_edges(lines, first, last)
        if start <= end:
            if end - start + 1 > MAX_MODULE_BLOCK_LINES:
                for piece_start, piece_end in _split_block(start, end):
                    counter += 1
                    chunks.append(
                        _make_chunk(
                            file_path,
                            f"module#{counter}",
                            "module",
                            piece_start,
                            piece_end,
                            lines,
                        )
                    )
            else:
                chunks.append(
                    _make_chunk(file_path, "module", "module", start, end, lines)
                )
        first = last + 1
    return chunks


def _trim_blank_edges(lines: list[str], start: int, end: int) -> tuple[int, int]:
    """Recorta las líneas en blanco del principio y del final de `[start, end]`.

    Trabaja con números de línea desde 1 y no toca la lista. Si el rango solo
    tiene blancos, devuelve `start > end`, que el llamador interpreta como
    bloque vacío.
    """
    while start <= end and not _line_body(lines[start - 1]).strip():
        start += 1
    while end >= start and not _line_body(lines[end - 1]).strip():
        end -= 1
    return start, end


def _split_block(start: int, end: int) -> list[tuple[int, int]]:
    """Parte `[start, end]` en trozos contiguos de hasta 120 líneas, sin solape."""
    return [
        (piece, min(piece + MAX_MODULE_BLOCK_LINES - 1, end))
        for piece in range(start, end + 1, MAX_MODULE_BLOCK_LINES)
    ]


def _symbol_chunks(
    lines: list[str], tree: ast.Module, file_path: str
) -> tuple[list[Chunk], set[int]]:
    """Construye los fragmentos de símbolo y las líneas que cubren.

    El inicio sale de `_definition_start` (decoradores y comentarios pegados) y
    el final del `end_lineno` del nodo. Las cadenas de varias líneas se
    protegen una sola vez para que una línea `#` de su interior no se tome por
    comentario. Devuelve también la unión de esos rangos, que es lo que
    `_module_blocks` necesita para no repetir ni pisar líneas. No ordena, no
    trocea módulo y no modifica sus entradas.
    """
    chunks: list[Chunk] = []
    covered: set[int] = set()
    string_lines = _string_lines(tree)
    for definition in _iter_definitions(tree):
        start = _definition_start(definition.node, lines, string_lines)
        end = definition.node.end_lineno
        chunks.append(
            _make_chunk(
                file_path, definition.symbol_name, definition.kind, start, end, lines
            )
        )
        covered.update(range(start, end + 1))
    return chunks, covered


def _window_chunks(file_path: str, lines: list[str]) -> list[Chunk]:
    """Parte las líneas en ventanas de `WINDOW_LINES` sin solape ni recortes.

    Es el plan B para contenido no analizable: las nombra `window#1`, `window#2`
    y siguientes desde 1, en orden de aparición. La última ventana puede tener
    menos líneas, incluso una, y su texto se toma exacto, aunque la última línea
    esté vacía. No genera embeddings ni escribe en el almacén.
    """
    return [
        _make_chunk(
            file_path,
            f"window#{number}",
            "window",
            start,
            min(start + WINDOW_LINES - 1, len(lines)),
            lines,
        )
        for number, start in enumerate(range(1, len(lines) + 1, WINDOW_LINES), start=1)
    ]
