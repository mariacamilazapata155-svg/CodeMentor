"""Servidor MCP (stdio) que expone `search_code` e `index_file`.

Responsabilidad:
- Exponer una tool de búsqueda semántica sobre el código ya indexado.
- Exponer una tool para indexar el contenido de un archivo `.py` por su ruta.
- Consumir `rag.search` y `rag.index_file` directamente, sin pasar por HTTP ni
    por `bot.py`.

Límites:
- No implementa chunking, embeddings ni el bucle RAG del bot.
- NUNCA escribe en stdout (ni `print` ni logs por defecto): el protocolo stdio
    se corrompe. Cualquier log debe ir a stderr.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from app import rag
from app.models import IndexResult, SearchReason, SearchResult

logger = logging.getLogger(__name__)

SEARCH_TOOL_NAME = "search_code"
INDEX_TOOL_NAME = "index_file"

SEARCH_DESCRIPTION = (
    "Busca en el código Python ya indexado en este servidor los fragmentos más "
    "parecidos a una consulta. Devuelve hasta cinco fragmentos, cada uno con su "
    "ruta, símbolo, líneas, relevancia y texto, para que puedas citarlos. Úsala "
    "cuando necesites localizar dónde está algo en el código indexado; no "
    "responde preguntas ni genera explicaciones."
)

INDEX_DESCRIPTION = (
    "Indexa el contenido de un archivo Python en el índice de este servidor para "
    "poder buscarlo después con search_code. Recibe la ruta con la que se citará "
    "el archivo y su contenido completo como texto; no lee el archivo del disco y "
    "no lo ejecuta. Si la ruta ya estaba indexada, sustituye sus fragmentos. "
    "Úsala antes de search_code."
)

SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "Pregunta o palabras clave sobre el código que quieres localizar. "
                "No puede estar vacía ni superar los 1.000 caracteres."
            ),
        }
    },
    "required": ["query"],
}

INDEX_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Ruta con la que se identificará el archivo en el índice y en las "
                "citas. Debe terminar en .py; no se comprueba que exista en el disco."
            ),
        },
        "content": {
            "type": "string",
            "description": (
                "Contenido completo del archivo Python como texto. No puede estar "
                "vacío ni superar 1.048.576 bytes en UTF-8."
            ),
        },
    },
    "required": ["path", "content"],
}

SEARCH_TOOL = Tool(
    name=SEARCH_TOOL_NAME,
    description=SEARCH_DESCRIPTION,
    input_schema=SEARCH_INPUT_SCHEMA,
)

INDEX_TOOL = Tool(
    name=INDEX_TOOL_NAME,
    description=INDEX_DESCRIPTION,
    input_schema=INDEX_INPUT_SCHEMA,
)

MSG_QUERY_REQUIRED = (
    "Falta la consulta: el argumento «query» es obligatorio y debe ser un texto."
)
MSG_QUERY_NOT_TEXT = "El argumento «query» debe ser un texto."
MSG_PATH_REQUIRED = (
    "Falta la ruta del archivo: el argumento «path» es obligatorio y no puede "
    "estar vacío."
)
MSG_PATH_NOT_TEXT = "El argumento «path» debe ser un texto."
MSG_EXTENSION = "Solo se aceptan archivos de Python (.py)."
MSG_CONTENT_REQUIRED = (
    "Falta el contenido del archivo: el argumento «content» es obligatorio y "
    "debe ser un texto."
)
MSG_CONTENT_NOT_TEXT = "El argumento «content» debe ser un texto."
MSG_EMPTY_INDEX = (
    "Todavía no hay código indexado. Indexa un archivo .py con la herramienta "
    "index_file para poder buscar en él."
)
MSG_UNKNOWN_TOOL = (
    "La herramienta «{name}» no existe. Usa search_code para buscar o index_file "
    "para indexar un archivo .py."
)
MSG_INTERNAL_ERROR = (
    "Ocurrió un error interno al ejecutar la herramienta. Inténtalo de nuevo."
)


def create_server() -> Server[Any]:
    """Crea el servidor MCP con las dos herramientas y sin arrancarlo."""
    return Server(
        "codementor",
        title="CodeMentor",
        instructions=(
            "Indexa archivos .py con index_file y busca en ellos con search_code. "
            "El índice vive en este proceso y empieza vacío."
        ),
        on_list_tools=_on_list_tools,
        on_call_tool=_on_call_tool,
    )


async def _on_list_tools(
    ctx: ServerRequestContext[Any],
    params: PaginatedRequestParams | None,
) -> ListToolsResult:
    """Devuelve la lista de herramientas publicadas, en orden estable."""
    return ListToolsResult(tools=[SEARCH_TOOL, INDEX_TOOL])


async def _on_call_tool(
    ctx: ServerRequestContext[Any],
    params: CallToolRequestParams,
) -> CallToolResult:
    """Ejecuta el despacho fuera del bucle y convierte los fallos en un error."""
    try:
        return await asyncio.to_thread(_dispatch, params.name, params.arguments)
    except Exception as exc:  # noqa: BLE001 - RF-25: cualquier fallo se convierte en error
        logger.error("error interno en una herramienta: %s", type(exc).__name__)
        return _error(MSG_INTERNAL_ERROR)


def _dispatch(name: str, arguments: dict[str, Any] | None) -> CallToolResult:
    """Enruta la invocación por nombre de herramienta."""
    args = arguments or {}
    if name == SEARCH_TOOL_NAME:
        return _search(args)
    if name == INDEX_TOOL_NAME:
        return _index(args)
    return _error(MSG_UNKNOWN_TOOL.format(name=name))


def _search(arguments: dict[str, Any]) -> CallToolResult:
    """Valida la consulta, delega en `rag.search` y traduce su resultado."""
    query, error = _parse_query(arguments)
    if error is not None:
        return _error(error)

    response = rag.search(query)
    if response.reason == SearchReason.EMPTY_QUERY:
        return _error(response.message or MSG_INTERNAL_ERROR)
    if response.reason == SearchReason.QUERY_TOO_LONG:
        return _error(response.message or MSG_INTERNAL_ERROR)
    if response.reason == SearchReason.EMPTY_INDEX:
        return _ok(MSG_EMPTY_INDEX)
    if response.reason == SearchReason.NO_RELEVANT:
        return _ok(response.message or MSG_INTERNAL_ERROR)
    if response.reason is not None:
        return _error(MSG_INTERNAL_ERROR)
    return _ok(_format_search_results(response.results))


def _index(arguments: dict[str, Any]) -> CallToolResult:
    """Valida los argumentos, delega en `rag.index_file` y traduce su resultado."""
    parsed, error = _parse_index_arguments(arguments)
    if error is not None:
        return _error(error)

    path, content = parsed
    result = rag.index_file(path, content)
    if result.reason is not None:
        return _error(result.message)
    return _ok(_format_index_success(result))


def _parse_query(arguments: dict[str, Any]) -> tuple[str | None, str | None]:
    """Valida el argumento `query` y lo devuelve sin recortar.

    Devuelve `(query, None)` si es texto, o `(None, mensaje)` si falta o no es
    texto. No comprueba vacío ni longitud: eso es responsabilidad de `rag.search`.
    """
    if "query" not in arguments:
        return None, MSG_QUERY_REQUIRED
    query = arguments["query"]
    if not isinstance(query, str):
        return None, MSG_QUERY_NOT_TEXT
    return query, None


def _parse_index_arguments(
    arguments: dict[str, Any],
) -> tuple[tuple[str, str] | None, str | None]:
    """Valida `path` y `content` en el orden fijado por el plan.

    Devuelve `((path, content), None)` si ambos son válidos, o
    `(None, mensaje)` en el primer rechazo. No recorta ni normaliza nada.
    """
    if "path" not in arguments:
        return None, MSG_PATH_REQUIRED
    path = arguments["path"]
    if not isinstance(path, str):
        return None, MSG_PATH_NOT_TEXT
    if path.strip() == "":
        return None, MSG_PATH_REQUIRED
    if not path.lower().endswith(".py"):
        return None, MSG_EXTENSION
    if "content" not in arguments:
        return None, MSG_CONTENT_REQUIRED
    content = arguments["content"]
    if not isinstance(content, str):
        return None, MSG_CONTENT_NOT_TEXT
    return (path, content), None


def _format_number(value: int) -> str:
    """Formatea un entero con punto de miles (`1.000`)."""
    return f"{value:,}".replace(",", ".")


def _format_relevance(score: float) -> str:
    """Acota la relevancia a `[0, 1]` y la formatea con dos decimales y coma."""
    clamped = min(max(score, 0.0), 1.0)
    return f"{clamped:.2f}".replace(".", ",")


def _format_result(index: int, total: int, result: SearchResult) -> str:
    """Construye el bloque legible de un fragmento, sin añadir ni quitar texto."""
    chunk = result.chunk
    return (
        f"Fragmento {index} de {total}\n"
        f"Ruta: {chunk.file_path}\n"
        f"Símbolo: {chunk.symbol_name}\n"
        f"Líneas: {chunk.start_line}–{chunk.end_line}\n"
        f"Relevancia: {_format_relevance(result.score)}\n"
        f"Texto:\n"
        f"{chunk.content}"
    )


def _format_search_results(results: list[SearchResult]) -> str:
    """Une los bloques de todos los fragmentos con una línea en blanco."""
    return "\n\n".join(
        _format_result(index, len(results), result)
        for index, result in enumerate(results, 1)
    )


def _format_index_success(result: IndexResult) -> str:
    """Formatea el éxito del indexado con el mensaje y los cuatro datos."""
    windows = "sí" if result.used_windows else "no"
    return (
        f"{result.message}\n\n"
        f"Ruta: {result.file_path}\n"
        f"Fragmentos indexados: {_format_number(result.chunks_indexed)}\n"
        f"Total del índice: {_format_number(result.total_chunks)}\n"
        f"Troceado por ventanas: {windows}"
    )


def _ok(text: str) -> CallToolResult:
    """Construye un resultado de herramienta sin marca de error."""
    return CallToolResult(
        content=[TextContent(type="text", text=text)], is_error=False
    )


def _error(text: str) -> CallToolResult:
    """Construye un resultado de herramienta marcado como error."""
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)


def _configure_logging() -> None:
    """Instala un registro por stderr en el logger del módulo, una sola vez."""
    if logger.handlers:
        logger.propagate = False
        return
    logger.addHandler(logging.StreamHandler(sys.stderr))
    logger.propagate = False


async def _serve() -> None:
    """Sirve el servidor MCP por stdio hasta que el cliente cierra la entrada."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Punto de entrada de `python -m app.mcp_server`."""
    _configure_logging()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
