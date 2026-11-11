"""Pruebas del despacho, la herramienta desconocida y el error no controlado.

Comprueban que `_dispatch` enruta por nombre, trata `arguments=None` como `{}`,
ignora argumentos extra y responde a nombres desconocidos; que `_on_call_tool`
ejecuta el despacho con `asyncio.to_thread`; y que un fallo inesperado se
convierte en un error genérico, se registra solo por tipo y no impide la
siguiente invocación. No descargan el modelo, no usan red y no llaman a
Anthropic.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import json
import logging
import os
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession
from mcp.types import CallToolRequestParams

from app import mcp_server, rag
from app.models import Chunk, IndexResult, SearchReason, SearchResponse
from app.storage import VectorStore


@pytest.fixture(autouse=True)
def clean_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sustituye el índice del proceso por uno vacío en cada prueba."""
    monkeypatch.setattr(rag, "store", VectorStore())


@pytest.fixture(autouse=True)
def clear_model_cache() -> Iterator[None]:
    """Vacía la caché de `_get_model` antes y después de cada prueba."""
    cache_clear = getattr(rag._get_model, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()
    yield
    if callable(cache_clear):
        cache_clear()


def empty_index_response() -> SearchResponse:
    """Respuesta de una búsqueda con el índice vacío."""
    return SearchResponse(
        results=[],
        reason=SearchReason.EMPTY_INDEX,
        message=rag.EMPTY_INDEX_MESSAGE,
    )


def success_result() -> IndexResult:
    """Resultado de un indexado con éxito."""
    return IndexResult(
        file_path="app/x.py",
        chunks_indexed=1,
        total_chunks=1,
        used_windows=False,
        reason=None,
        message=rag._success_message(
            chunks_indexed=1, total_chunks=1, used_windows=False
        ),
    )


# --- Despacho por nombre (RF-24 y RF-27) ------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (mcp_server.SEARCH_TOOL_NAME, mcp_server.MSG_QUERY_REQUIRED),
        (mcp_server.INDEX_TOOL_NAME, mcp_server.MSG_PATH_REQUIRED),
    ],
    ids=["search_code", "index_file"],
)
def test_dispatch_treats_none_arguments_as_empty(name: str, expected: str) -> None:
    """`arguments=None` llega como `{}` y devuelve el error del argumento que falta."""
    result = mcp_server._dispatch(name, None)

    assert result.is_error is True
    assert result.content[0].text == expected


@pytest.mark.parametrize("name", ["no_existe", "", "SEARCH_CODE"])
def test_unknown_tool_returns_the_message_with_the_name(name: str) -> None:
    """Un nombre desconocido devuelve un error con su nombre y los nombres válidos."""
    result = mcp_server._dispatch(name, {"query": "login"})

    assert result.is_error is True
    assert result.content[0].text == mcp_server.MSG_UNKNOWN_TOOL.format(name=name)


def test_extra_arguments_do_not_change_a_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un argumento extra no altera la búsqueda ni su resultado."""
    monkeypatch.setattr(rag, "search", lambda query: empty_index_response())

    plain = mcp_server._dispatch(
        mcp_server.SEARCH_TOOL_NAME, {"query": "login"}
    )
    extra = mcp_server._dispatch(
        mcp_server.SEARCH_TOOL_NAME, {"query": "login", "extra": "ignorado"}
    )

    assert extra.is_error is False
    assert extra.content[0].text == plain.content[0].text


def test_extra_arguments_do_not_change_an_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un argumento extra no altera el indexado ni su resultado."""
    monkeypatch.setattr(rag, "index_file", lambda path, content: success_result())

    plain = mcp_server._dispatch(
        mcp_server.INDEX_TOOL_NAME, {"path": "x.py", "content": "x = 1"}
    )
    extra = mcp_server._dispatch(
        mcp_server.INDEX_TOOL_NAME,
        {"path": "x.py", "content": "x = 1", "extra": "ignorado"},
    )

    assert extra.is_error is False
    assert extra.content[0].text == plain.content[0].text


# --- Ejecución fuera del bucle de eventos (RNF-9) ---------------------------


def test_on_call_tool_uses_asyncio_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """El manejador ejecuta `_dispatch` con `asyncio.to_thread` y sus argumentos."""
    calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    async def fake_to_thread(
        func: object, *args: object, **kwargs: object
    ) -> object:
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(mcp_server.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(rag, "search", lambda query: empty_index_response())
    params = CallToolRequestParams(
        name=mcp_server.SEARCH_TOOL_NAME, arguments={"query": "login"}
    )

    result = asyncio.run(mcp_server._on_call_tool(None, params))  # type: ignore[arg-type]

    assert result.is_error is False
    assert calls == [
        (mcp_server._dispatch, (mcp_server.SEARCH_TOOL_NAME, {"query": "login"}), {})
    ]


def test_on_call_tool_forwards_none_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    """`arguments=None` se pasa tal cual al despacho, que lo trata como vacío."""
    calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    async def fake_to_thread(
        func: object, *args: object, **kwargs: object
    ) -> object:
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)  # type: ignore[operator]

    monkeypatch.setattr(mcp_server.asyncio, "to_thread", fake_to_thread)
    params = CallToolRequestParams(name=mcp_server.SEARCH_TOOL_NAME, arguments=None)

    result = asyncio.run(mcp_server._on_call_tool(None, params))  # type: ignore[arg-type]

    assert result.is_error is True
    assert result.content[0].text == mcp_server.MSG_QUERY_REQUIRED
    assert calls == [(mcp_server._dispatch, (mcp_server.SEARCH_TOOL_NAME, None), {})]


# --- Error no controlado (RF-25, RF-26 y RNF-9) -----------------------------


def test_internal_error_is_sanitized_logged_and_the_next_call_works(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Un fallo inesperado no escapa, no filtra datos y no mata la siguiente llamada."""
    caplog.set_level(logging.ERROR, logger=mcp_server.__name__)

    def boom(query: str) -> SearchResponse:
        raise RuntimeError("secreto")

    monkeypatch.setattr(rag, "search", boom)
    search_params = CallToolRequestParams(
        name=mcp_server.SEARCH_TOOL_NAME, arguments={"query": "login"}
    )

    result = asyncio.run(
        mcp_server._on_call_tool(None, search_params)  # type: ignore[arg-type]
    )

    assert result.is_error is True
    assert result.content[0].text == mcp_server.MSG_INTERNAL_ERROR
    for secret in ("secreto", "login"):
        assert secret not in result.content[0].text
        assert secret not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "ValueError" not in caplog.text

    caplog.clear()

    def fail_index(path: str, content: str) -> IndexResult:
        raise ValueError(f"ruta {path} con contenido {content}")

    monkeypatch.setattr(rag, "index_file", fail_index)
    index_params = CallToolRequestParams(
        name=mcp_server.INDEX_TOOL_NAME,
        arguments={"path": "app/privado.py", "content": "TOKEN_SECRETO = 1"},
    )

    index_result = asyncio.run(
        mcp_server._on_call_tool(None, index_params)  # type: ignore[arg-type]
    )

    assert index_result.is_error is True
    assert index_result.content[0].text == mcp_server.MSG_INTERNAL_ERROR
    for secret in ("app/privado.py", "TOKEN_SECRETO", "ruta", "contenido"):
        assert secret not in index_result.content[0].text
        assert secret not in caplog.text
    assert "ValueError" in caplog.text
    assert "RuntimeError" not in caplog.text

    monkeypatch.setattr(rag, "search", lambda query: empty_index_response())
    later = asyncio.run(
        mcp_server._on_call_tool(None, search_params)  # type: ignore[arg-type]
    )

    assert later.is_error is False
    assert later.content[0].text == mcp_server.MSG_EMPTY_INDEX


# --- Cableado del manejador en el servidor (RF-26) --------------------------


def test_server_registers_call_tool_and_answers_unknown_tools() -> None:
    """`create_server()` conecta `on_call_tool` y responde a un nombre desconocido."""

    async def run() -> object:
        server = mcp_server.create_server()
        async with (
            InMemoryTransport(server) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            return await session.call_tool("no_existe", {})

    result = asyncio.run(run())

    assert result.is_error is True  # type: ignore[attr-defined]
    assert result.content[0].text == mcp_server.MSG_UNKNOWN_TOOL.format(  # type: ignore[attr-defined]
        name="no_existe"
    )


def test_server_call_tool_routes_to_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una invocación por protocolo llega a `_search` a través de `_on_call_tool`."""
    monkeypatch.setattr(rag, "search", lambda query: empty_index_response())

    async def run() -> object:
        server = mcp_server.create_server()
        async with (
            InMemoryTransport(server) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            return await session.call_tool(
                mcp_server.SEARCH_TOOL_NAME, {"query": "login"}
            )

    result = asyncio.run(run())

    assert result.is_error is False  # type: ignore[attr-defined]
    assert result.content[0].text == mcp_server.MSG_EMPTY_INDEX  # type: ignore[attr-defined]


# --- Integración con el índice real (RF-19 a RF-23 y RNF-8) -----------------

KEYWORDS = ("login", "logout", "saludo", "version", "pago", "auth")
KEYWORD_DIMENSIONS = len(KEYWORDS)


class KeywordModel:
    """Doble determinista que vectoriza por palabras clave y registra los textos."""

    def __init__(self) -> None:
        """Prepara la lista de textos recibidos y el bloqueo que la protege."""
        self.texts: list[str] = []
        self._lock = threading.Lock()

    def encode(
        self, texts: str | list[str], normalize_embeddings: bool = True
    ) -> np.ndarray:
        """Registra los textos y devuelve una fila con el recuento de cada palabra."""
        single = isinstance(texts, str)
        items = [texts] if single else list(texts)
        with self._lock:
            self.texts.extend(items)
        rows: list[list[float]] = []
        for text in items:
            lowered = text.lower()
            rows.append([float(lowered.count(word)) for word in KEYWORDS])
        matrix = np.array(rows, dtype=np.float32)
        return matrix[0] if single else matrix


class BarrierKeywordModel(KeywordModel):
    """`KeywordModel` que espera a que las dos versiones troceen antes de embeber."""

    def __init__(self, parties: int = 2) -> None:
        """Prepara el modelo y la barrera que sincroniza los indexados."""
        super().__init__()
        self._barrier = threading.Barrier(parties)

    def encode(
        self, texts: str | list[str], normalize_embeddings: bool = True
    ) -> np.ndarray:
        """Sincroniza solo los embeddings de fragmentos, no los de consulta."""
        if not isinstance(texts, str):
            self._barrier.wait(timeout=30)
        return super().encode(texts, normalize_embeddings)


def store_snapshot() -> list[Chunk]:
    """Devuelve todos los fragmentos en orden de inserción, sin tocar atributos privados."""
    query = np.zeros(KEYWORD_DIMENSIONS, dtype=np.float32)
    return [result.chunk for result in rag.store.search(query, top_k=10_000)]


def test_index_and_search_in_the_same_protocol_session_finds_the_new_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Indexar y buscar por la misma sesión MCP encuentra lo recién indexado."""
    monkeypatch.setattr(rag, "_get_model", lambda: KeywordModel())

    async def run() -> tuple[object, object]:
        server = mcp_server.create_server()
        async with (
            InMemoryTransport(server) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            indexed = await session.call_tool(
                mcp_server.INDEX_TOOL_NAME,
                {
                    "path": "app/saludo.py",
                    "content": 'def saludo():\n    return "saludo"\n',
                },
            )
            found = await session.call_tool(
                mcp_server.SEARCH_TOOL_NAME, {"query": "saludo"}
            )
            return indexed, found

    indexed, found = asyncio.run(run())

    assert indexed.is_error is False  # type: ignore[attr-defined]
    assert "Ruta: app/saludo.py" in indexed.content[0].text  # type: ignore[attr-defined]
    assert found.is_error is False  # type: ignore[attr-defined]
    assert "Ruta: app/saludo.py" in found.content[0].text  # type: ignore[attr-defined]
    assert "Símbolo: saludo" in found.content[0].text  # type: ignore[attr-defined]


def test_concurrent_dispatch_indexing_and_searching_keeps_each_path_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 rutas indexadas y buscadas a la vez: sin excepciones y sin mezclas."""
    model = KeywordModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    paths = [f"app/simultanea_{index}.py" for index in range(20)]
    sources = {
        path: (
            f"def ruta_{index}_uno():\n"
            f'    return "version_{index}_uno"\n'
            "\n"
            f"def ruta_{index}_dos():\n"
            f'    return "version_{index}_dos"\n'
        )
        for index, path in enumerate(paths)
    }
    upload_threads = len(paths)
    search_threads = 4
    parties = upload_threads + search_threads
    barrier = threading.Barrier(parties)

    def upload(path: str) -> None:
        """Espera la salida común e indexa una ruta distinta por el despacho."""
        barrier.wait(timeout=30)
        result = mcp_server._dispatch(
            mcp_server.INDEX_TOOL_NAME, {"path": path, "content": sources[path]}
        )
        assert result.is_error is False
        assert "Fragmentos indexados: 2" in result.content[0].text

    def search_many() -> None:
        """Busca mientras se indexa, sin exigir un estado concreto del índice."""
        barrier.wait(timeout=30)
        for _ in range(25):
            result = mcp_server._dispatch(
                mcp_server.SEARCH_TOOL_NAME, {"query": "version"}
            )
            assert result.is_error is False

    with ThreadPoolExecutor(max_workers=parties) as executor:
        futures = [executor.submit(upload, path) for path in paths]
        futures.extend(executor.submit(search_many) for _ in range(search_threads))
        for future in futures:
            future.result()

    stored = store_snapshot()
    by_path: dict[str, list[Chunk]] = {}
    for chunk in stored:
        by_path.setdefault(chunk.file_path, []).append(chunk)

    assert set(by_path) == set(paths)
    assert rag.store.count == len(paths) * 2
    for index, path in enumerate(paths):
        chunks = by_path[path]
        assert len(chunks) == 2
        assert all(f"version_{index}_" in chunk.content for chunk in chunks)
        assert {chunk.symbol_name for chunk in chunks} == {
            f"ruta_{index}_uno",
            f"ruta_{index}_dos",
        }


def test_concurrent_reindexing_of_the_same_path_never_mixes_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dos versiones de la misma ruta por MCP: la búsqueda nunca mezcla.

    La garantía de reemplazo atómico vive en `rag.index_file` y está cubierta
    por `tests/test_safety_perf.py::test_concurrent_uploads_of_the_same_path_never_mix_versions`;
    aquí se comprueba a través del despacho MCP mientras se busca.
    """
    model = BarrierKeywordModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    path = "app/contendida.py"
    source_a = 'def version_a():\n    return "version_a"\n'
    source_b = (
        'def version_b():\n    return "version_b"\n'
        "\n"
        'def version_b_dos():\n    return "version_b"\n'
    )
    barrier = threading.Barrier(3)
    mixed: list[str] = []
    errors: list[BaseException] = []

    def upload(source: str) -> None:
        """Espera la salida común y reindexa la ruta compartida por MCP."""
        barrier.wait(timeout=30)
        result = mcp_server._dispatch(
            mcp_server.INDEX_TOOL_NAME, {"path": path, "content": source}
        )
        assert result.is_error is False

    def search_while_reindexing() -> None:
        """Busca por MCP y vigila que la ruta no tenga dos versiones a la vez."""
        barrier.wait(timeout=30)
        for _ in range(100):
            try:
                result = mcp_server._dispatch(
                    mcp_server.SEARCH_TOOL_NAME, {"query": "version"}
                )
                text = result.content[0].text
                if "version_a" in text and "version_b" in text:
                    mixed.append(text)
                contents = [
                    chunk.content
                    for chunk in store_snapshot()
                    if chunk.file_path == path
                ]
            except BaseException as exc:  # noqa: BLE001 - se reporta como fallo
                errors.append(exc)
                return
            if contents and not (
                all("version_a" in content for content in contents)
                or all("version_b" in content for content in contents)
            ):
                mixed.append("\n".join(contents))

    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(upload, source_a)
        second = executor.submit(upload, source_b)
        search = executor.submit(search_while_reindexing)
        first.result()
        second.result()
        search.result()

    assert errors == []
    assert mixed == []

    stored = [chunk for chunk in store_snapshot() if chunk.file_path == path]
    assert stored
    assert all("version_a" in chunk.content for chunk in stored) or all(
        "version_b" in chunk.content for chunk in stored
    )


# --- Flujo completo por protocolo (T7, RF-1, RF-3, RF-10, RF-21 y RF-23) ----


def test_full_protocol_flow_indexes_searches_and_recovers_from_an_empty_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una sola sesión indexa, busca dos veces, falla con consulta vacía y sigue viva."""
    model = KeywordModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    content = 'def saludo():\n    return "saludo"\n'

    async def run() -> tuple[object, object, object, object, object, object]:
        server = mcp_server.create_server()
        async with (
            InMemoryTransport(server) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            indexed = await session.call_tool(
                mcp_server.INDEX_TOOL_NAME,
                {"path": "app/saludo.py", "content": content},
            )
            first = await session.call_tool(
                mcp_server.SEARCH_TOOL_NAME, {"query": "saludo"}
            )
            second = await session.call_tool(
                mcp_server.SEARCH_TOOL_NAME, {"query": "saludo"}
            )
            empty = await session.call_tool(
                mcp_server.SEARCH_TOOL_NAME, {"query": ""}
            )
            tools_after = await session.list_tools()
            return tools, indexed, first, second, empty, tools_after

    tools, indexed, first, second, empty, tools_after = asyncio.run(run())

    assert [tool.name for tool in tools.tools] == [  # type: ignore[attr-defined]
        mcp_server.SEARCH_TOOL_NAME,
        mcp_server.INDEX_TOOL_NAME,
    ]

    assert indexed.is_error is False  # type: ignore[attr-defined]
    index_text = indexed.content[0].text  # type: ignore[attr-defined]
    success_message = rag._success_message(
        chunks_indexed=1, total_chunks=1, used_windows=False
    )
    assert index_text.splitlines()[0] == success_message
    assert "Ruta: app/saludo.py" in index_text
    assert "Fragmentos indexados: 1" in index_text
    assert "Total del índice: 1" in index_text
    assert "Troceado por ventanas: no" in index_text
    assert rag.store.count == 1

    assert first.is_error is False  # type: ignore[attr-defined]
    first_text = first.content[0].text  # type: ignore[attr-defined]
    assert "Fragmento 1 de 1" in first_text
    assert "Ruta: app/saludo.py" in first_text
    assert "Símbolo: saludo" in first_text
    assert "Líneas: 1–2" in first_text
    assert 'def saludo():\n    return "saludo"' in first_text

    assert second.is_error is False  # type: ignore[attr-defined]
    second_text = second.content[0].text  # type: ignore[attr-defined]
    assert "Ruta: app/saludo.py" in second_text
    assert "Símbolo: saludo" in second_text
    assert rag.store.count == 1

    assert empty.is_error is True  # type: ignore[attr-defined]
    assert empty.content[0].text == rag.EMPTY_QUERY_MESSAGE  # type: ignore[attr-defined]

    assert [tool.name for tool in tools_after.tools] == [  # type: ignore[attr-defined]
        mcp_server.SEARCH_TOOL_NAME,
        mcp_server.INDEX_TOOL_NAME,
    ]


# --- Arranque por stdio y seguridad (T8, RF-29 a RF-32 y RNF-1 a RNF-10) ----

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Módulos que esta capa no debe importar: solo traduce, no implementa RAG ni HTTP.
FORBIDDEN_MODULES = (
    "ast",
    "numpy",
    "sentence_transformers",
    "tempfile",
    "app.storage",
    "app.bot",
    "app.main",
    "fastapi",
    "uvicorn",
    "anthropic",
    "httpx",
    "requests",
    "urllib",
    "socket",
)

#: Nombres de `rag.py` que no deben reimplementarse en esta capa.
FORBIDDEN_DEFINITIONS = {
    "chunk_python_file",
    "index_file",
    "search",
    "_get_model",
    "warm_up",
}

#: Prefijos que delatan troceado o embeddings propios.
FORBIDDEN_DEFINITION_PREFIXES = ("chunk", "_chunk", "embed", "_embed")

#: Dependencias exactas que el proyecto ya fija antes de esta spec.
EXPECTED_REQUIREMENTS = (
    "fastapi==0.161.0",
    "starlette==1.9.0",
    "uvicorn==0.54.0",
    "pydantic==2.14.1",
    "python-dotenv==1.2.4",
    "sentence-transformers==6.2.0",
    "numpy==2.5.4",
    "anthropic==2.1.0",
    "mcp==2.3.0",
    "python-multipart==0.0.32",
    "pytest==9.1.1",
    "httpx==0.28.1",
    "httpx2==2.16.0",
    "ruff==0.17.2",
)


def module_tree() -> ast.Module:
    """Devuelve el AST del módulo `app/mcp_server.py`."""
    source = (PROJECT_ROOT / "app" / "mcp_server.py").read_text(encoding="utf-8")
    return ast.parse(source)


def imported_modules(tree: ast.Module) -> set[str]:
    """Devuelve los módulos importados, incluidos los nombres de `from ... import`."""
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(
                f"{node.module}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            )
    return imported


def test_configure_logging_installs_a_single_stderr_handler(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Configura un solo `StreamHandler(sys.stderr)`, sin duplicar ni tocar stdout."""
    monkeypatch.setattr(mcp_server.logger, "handlers", [])
    monkeypatch.setattr(mcp_server.logger, "propagate", True)
    monkeypatch.setattr(mcp_server.logger, "level", logging.WARNING)

    mcp_server._configure_logging()
    first = list(mcp_server.logger.handlers)
    mcp_server._configure_logging()
    second = list(mcp_server.logger.handlers)

    assert len(first) == 1
    assert isinstance(first[0], logging.StreamHandler)
    assert first[0].stream is sys.stderr
    assert second == first
    assert mcp_server.logger.propagate is False

    mcp_server.logger.warning("aviso solo por stderr")
    captured = capsys.readouterr()

    assert captured.out == ""
    assert "aviso solo por stderr" in captured.err


def test_module_has_no_print_or_stdout_write_calls() -> None:
    """El AST no contiene `print(...)` ni `sys.stdout.write(...)` (RNF-1)."""
    offenders: list[str] = []
    for node in ast.walk(module_tree()):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id == "print":
            offenders.append("print")
        if (
            isinstance(function, ast.Attribute)
            and function.attr == "write"
            and isinstance(function.value, ast.Attribute)
            and function.value.attr == "stdout"
        ):
            offenders.append("stdout.write")

    assert offenders == []


def test_module_does_not_write_files_or_use_tempfile() -> None:
    """El AST no llama a `write_text` ni a `write_bytes` (RF-31)."""
    offenders = [
        node.func.attr
        for node in ast.walk(module_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"write_text", "write_bytes"}
    ]

    assert offenders == []


def test_module_does_not_import_forbidden_layers_or_libraries() -> None:
    """No importa RAG, HTTP, modelos ni sockets: solo traduce por stdio (RNF-5)."""
    imported = imported_modules(module_tree())
    offenders = sorted(
        name
        for name in imported
        if any(
            name == forbidden or name.startswith(f"{forbidden}.")
            for forbidden in FORBIDDEN_MODULES
        )
    )

    assert offenders == []


def test_module_does_not_reimplement_chunking_embeddings_or_search() -> None:
    """No define troceado, embeddings ni búsqueda propias; reutiliza `rag` (RNF-5)."""
    definitions = {
        node.name
        for node in ast.walk(module_tree())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    offenders = sorted(
        name
        for name in definitions
        if name in FORBIDDEN_DEFINITIONS
        or name.startswith(FORBIDDEN_DEFINITION_PREFIXES)
    )

    assert offenders == []
    assert mcp_server.rag is rag


def clean_environment(**overrides: str) -> dict[str, str]:
    """Devuelve el entorno sin clave de API y con las variables indicadas."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() != "ANTHROPIC_API_KEY"
    }
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.update(overrides)
    return environment


def start_stdout_reader(
    process: subprocess.Popen[str],
) -> tuple[queue.Queue[str | None], threading.Thread]:
    """Lee stdout en un hilo y encola cada línea; al llegar al final encola `None`."""
    lines: queue.Queue[str | None] = queue.Queue()

    def read() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    return lines, thread


def collect_stdio_messages(
    lines: queue.Queue[str | None], expected_ids: set[int], timeout: float
) -> list[dict[str, object]]:
    """Recoge mensajes JSON-RPC hasta ver todos los identificadores esperados."""
    messages: list[dict[str, object]] = []
    seen: set[int] = set()
    deadline = time.monotonic() + timeout
    while not expected_ids <= seen:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            break
        if line is None:
            break
        if not line.strip():
            continue
        message = json.loads(line)
        assert message["jsonrpc"] == "2.0"
        messages.append(message)
        if "id" in message:
            seen.add(message["id"])
    return messages


def drain_stdio_messages(
    lines: queue.Queue[str | None],
) -> list[dict[str, object]]:
    """Recoge los mensajes que queden en la cola tras terminar el proceso."""
    messages: list[dict[str, object]] = []
    while True:
        try:
            line = lines.get_nowait()
        except queue.Empty:
            break
        if line is None:
            break
        if not line.strip():
            continue
        message = json.loads(line)
        assert message["jsonrpc"] == "2.0"
        messages.append(message)
    return messages


def test_stdio_subprocess_emits_only_jsonrpc_on_stdout(tmp_path: Path) -> None:
    """`python -m app.mcp_server` habla solo JSON-RPC por stdout (RF-29 y RNF-1)."""
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "import numpy as np\n"
        "from app import rag\n"
        "\n"
        "class _FakeModel:\n"
        "    def encode(self, texts, normalize_embeddings=True):\n"
        "        single = isinstance(texts, str)\n"
        "        items = [texts] if single else list(texts)\n"
        "        rows = np.array([[1.0, 0.0] for _ in items], dtype=np.float32)\n"
        "        return rows[0] if single else rows\n"
        "\n"
        "rag._get_model = lambda: _FakeModel()\n",
        encoding="utf-8",
    )
    environment = clean_environment()
    environment["PYTHONPATH"] = os.pathsep.join((str(tmp_path), str(PROJECT_ROOT)))

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "prueba", "version": "0.0.0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": mcp_server.INDEX_TOOL_NAME,
                "arguments": {
                    "path": "app/login.py",
                    "content": 'def login():\n    return "login"\n',
                },
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": mcp_server.SEARCH_TOOL_NAME,
                "arguments": {"query": "login"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": mcp_server.SEARCH_TOOL_NAME,
                "arguments": {"query": ""},
            },
        },
    ]
    payload = "".join(
        json.dumps(request, ensure_ascii=False) + "\n" for request in requests
    )

    process = subprocess.Popen(
        [sys.executable, "-m", "app.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=PROJECT_ROOT,
        env=environment,
    )
    lines, stdout_thread = start_stdout_reader(process)
    stderr_chunks: list[str] = []

    def drain_stderr() -> None:
        assert process.stderr is not None
        stderr_chunks.append(process.stderr.read())

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()
    messages: list[dict[str, object]] = []
    try:
        assert process.stdin is not None
        process.stdin.write(payload)
        process.stdin.flush()
        messages = collect_stdio_messages(lines, {1, 2, 3, 4, 5}, timeout=60)
        process.stdin.close()
        process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        pytest.fail(f"el servidor no terminó:\n{''.join(stderr_chunks)}")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=30)
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

    messages.extend(drain_stdio_messages(lines))
    stderr = "".join(stderr_chunks)
    assert process.returncode == 0, stderr

    by_id = {
        message["id"]: message for message in messages if "id" in message
    }
    assert set(by_id) == {1, 2, 3, 4, 5}

    initialized = by_id[1]["result"]
    assert initialized["serverInfo"]["name"] == "codementor"  # type: ignore[index]

    tools = by_id[2]["result"]["tools"]  # type: ignore[index]
    assert [tool["name"] for tool in tools] == [
        mcp_server.SEARCH_TOOL_NAME,
        mcp_server.INDEX_TOOL_NAME,
    ]

    indexed = by_id[3]["result"]
    assert indexed["isError"] is False  # type: ignore[index]
    indexed_text = indexed["content"][0]["text"]  # type: ignore[index]
    assert "Ruta: app/login.py" in indexed_text
    assert "Fragmentos indexados: 1" in indexed_text

    found = by_id[4]["result"]
    assert found["isError"] is False  # type: ignore[index]
    found_text = found["content"][0]["text"]  # type: ignore[index]
    assert "Ruta: app/login.py" in found_text
    assert "Símbolo: login" in found_text

    empty = by_id[5]["result"]
    assert empty["isError"] is True  # type: ignore[index]
    assert empty["content"][0]["text"] == rag.EMPTY_QUERY_MESSAGE  # type: ignore[index]


def test_import_without_key_or_env_does_not_load_the_model(tmp_path: Path) -> None:
    """Sin clave ni `.env`, importar y listar funciona sin cargar el modelo (RNF-4)."""
    code = (
        "import asyncio, sys\n"
        "import app.mcp_server as m\n"
        "from mcp.client._memory import InMemoryTransport\n"
        "from mcp.client.session import ClientSession\n"
        "\n"
        "async def main():\n"
        "    async with InMemoryTransport(m.create_server()) as (read, write):\n"
        "        async with ClientSession(read, write) as session:\n"
        "            await session.initialize()\n"
        "            result = await session.list_tools()\n"
        "            return [tool.name for tool in result.tools]\n"
        "\n"
        "names = asyncio.run(main())\n"
        "print('sentence_transformers' in sys.modules, names)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=tmp_path,
        env=clean_environment(),
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False ['search_code', 'index_file']"


def test_indexing_and_searching_need_no_open_or_sockets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Indexar y buscar con dobles no abre archivos ni sockets (RF-31 y RF-32)."""
    monkeypatch.setattr(rag, "_get_model", lambda: KeywordModel())

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("no debe abrir archivos ni sockets")

    with monkeypatch.context() as patched:
        patched.setattr(builtins, "open", fail)
        patched.setattr(socket, "socket", fail)
        patched.setattr(socket, "create_connection", fail)
        indexed = mcp_server._dispatch(
            mcp_server.INDEX_TOOL_NAME,
            {
                "path": "app/saludo.py",
                "content": 'def saludo():\n    return "saludo"\n',
            },
        )
        found = mcp_server._dispatch(
            mcp_server.SEARCH_TOOL_NAME, {"query": "saludo"}
        )

    assert indexed.is_error is False
    assert found.is_error is False
    assert "Ruta: app/saludo.py" in found.content[0].text
    assert "Símbolo: saludo" in found.content[0].text


def test_malicious_content_is_indexed_as_text_and_never_executed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """El contenido que borra o crea archivos y sale no se ejecuta (RF-30)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rag, "_get_model", lambda: KeywordModel())
    source = (
        "import os\n"
        "\n"
        "os.remove('pwned.txt')\n"
        "open('pwned.txt', 'w')\n"
        "raise SystemExit(1)\n"
        "\n"
        "def login():\n"
        "    return 'login'\n"
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("el contenido no debe ejecutarse")

    with monkeypatch.context() as patched:
        patched.setattr(builtins, "exec", fail)
        patched.setattr(builtins, "eval", fail)
        result = mcp_server._dispatch(
            mcp_server.INDEX_TOOL_NAME,
            {"path": "app/malicioso.py", "content": source},
        )

    assert result.is_error is False
    assert not (tmp_path / "pwned.txt").exists()
    assert rag.store.count > 0


def test_indexing_and_searching_leave_no_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ni el directorio de trabajo ni el temporal reciben archivos (RF-31)."""
    work = tmp_path / "trabajo"
    spool = tmp_path / "temporal"
    work.mkdir()
    spool.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(tempfile, "tempdir", str(spool))
    monkeypatch.setattr(rag, "_get_model", lambda: KeywordModel())

    indexed = mcp_server._dispatch(
        mcp_server.INDEX_TOOL_NAME,
        {
            "path": "app/saludo.py",
            "content": 'def saludo():\n    return "saludo"\n',
        },
    )
    found = mcp_server._dispatch(
        mcp_server.SEARCH_TOOL_NAME, {"query": "saludo"}
    )

    assert indexed.is_error is False
    assert found.is_error is False
    assert set(work.iterdir()) == set()
    assert set(spool.iterdir()) == set()


def test_requirements_keep_mcp_pinned_and_add_no_new_dependencies() -> None:
    """`mcp==2.3.0` sigue fijado y la lista de dependencias no cambia (RNF-10)."""
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    lines = tuple(
        line.strip() for line in requirements.splitlines() if line.strip()
    )

    assert "mcp==2.3.0" in lines
    assert lines == EXPECTED_REQUIREMENTS
