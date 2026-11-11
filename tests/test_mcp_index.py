"""Pruebas de la herramienta de indexado del servidor MCP.

Usan un `rag.index_file` falso para comprobar la validación de argumentos, el
formato del éxito y la traducción de cada rechazo; después usan `index_file`
real con un índice nuevo y dobles de embeddings para fijar los límites de la
spec 002. No descargan el modelo, no usan red, no leen del disco y no llaman a
Anthropic.
"""

from __future__ import annotations

import builtins
import threading
from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest

from app import mcp_server, rag
from app.models import Chunk, IndexReason, IndexResult, SearchReason
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


class RecordingIndex:
    """Doble de `rag.index_file` que registra los argumentos y devuelve un resultado."""

    def __init__(self, result: IndexResult) -> None:
        """Guarda el resultado que devolverá y la lista de llamadas recibidas."""
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def __call__(self, file_path: str, source: str) -> IndexResult:
        """Registra la ruta y el contenido exactos y devuelve el resultado fijado."""
        self.calls.append((file_path, source))
        return self.result


class FakeModel:
    """Doble del modelo de embeddings que devuelve filas distintas y no normalizadas."""

    def __init__(self, dimensions: int = 3) -> None:
        """Fija la dimensión de las filas y la lista de textos recibidos."""
        self.dimensions = dimensions
        self.texts: list[str] = []

    def encode(
        self, texts: list[str], normalize_embeddings: bool = True
    ) -> np.ndarray:
        """Registra cada texto y devuelve una fila distinta por texto."""
        rows: list[list[float]] = []
        for index, text in enumerate(texts):
            self.texts.append(text)
            rows.append([float(index + 1)] + [1.0] * (self.dimensions - 1))
        return np.array(rows, dtype=np.float32)


def success_result(
    *,
    file_path: str = "app/x.py",
    chunks_indexed: int = 3,
    total_chunks: int = 7,
    used_windows: bool = False,
) -> IndexResult:
    """Construye un `IndexResult` de éxito con el mensaje real de la spec 002."""
    return IndexResult(
        file_path=file_path,
        chunks_indexed=chunks_indexed,
        total_chunks=total_chunks,
        used_windows=used_windows,
        reason=None,
        message=rag._success_message(
            chunks_indexed=chunks_indexed,
            total_chunks=total_chunks,
            used_windows=used_windows,
        ),
    )


def functions_source(prefix: str, count: int) -> str:
    """Construye un archivo con `count` funciones de dos líneas cada una."""
    return "".join(
        f"def {prefix}{index}():\n    return {index}\n" for index in range(count)
    )


def fail_embedding(chunks: list[Any]) -> np.ndarray:
    """Doble que falla si un rechazo llega a calcular representaciones."""
    raise AssertionError("un rechazo no debe calcular embeddings")


# --- Formato del éxito (RF-10) ----------------------------------------------


@pytest.mark.parametrize(
    "used_windows", [False, True], ids=["sin_ventanas", "con_ventanas"]
)
def test_success_formats_the_message_and_the_four_fields(
    monkeypatch: pytest.MonkeyPatch, used_windows: bool
) -> None:
    """El mensaje va primero y después ruta, fragmentos, total y troceado."""
    result = success_result(
        chunks_indexed=1_234, total_chunks=2_000, used_windows=used_windows
    )
    fake = RecordingIndex(result)
    monkeypatch.setattr(rag, "index_file", fake)

    output = mcp_server._index({"path": "app/x.py", "content": "x = 1"})

    expected = (
        f"{result.message}\n\n"
        "Ruta: app/x.py\n"
        "Fragmentos indexados: 1.234\n"
        "Total del índice: 2.000\n"
        f"Troceado por ventanas: {'sí' if used_windows else 'no'}"
    )
    assert output.is_error is False
    assert output.content[0].text == expected
    assert output.content[0].text.splitlines()[0] == result.message
    assert "Fragmento " not in output.content[0].text
    assert "Texto:" not in output.content[0].text
    assert fake.calls == [("app/x.py", "x = 1")]


# --- Ruta y contenido exactos, sin leer del disco (RF-11) -------------------

EXACT_PATHS = [
    pytest.param("../app/../../etc/x.py", id="recorrido"),
    pytest.param("/var/tmp/app/x.py", id="absoluta"),
    pytest.param("C:\\Users\\camil\\app\\x.py", id="windows"),
    pytest.param("<b>app/x.py", id="html"),
    pytest.param('app/"x".py', id="comillas"),
    pytest.param("app/\nx.py", id="salto_de_linea"),
    pytest.param("APP/X.PY", id="mayusculas"),
]

EXACT_CONTENT = "  \n\tdef login():\n    return True\n\n  "


@pytest.mark.parametrize("path", EXACT_PATHS)
def test_path_and_content_are_delivered_exactly(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """La ruta y el contenido llegan sin recortar, normalizar ni resolver."""
    fake = RecordingIndex(success_result(file_path=path))
    monkeypatch.setattr(rag, "index_file", fake)

    output = mcp_server._index({"path": path, "content": EXACT_CONTENT})

    assert output.is_error is False
    assert fake.calls == [(path, EXACT_CONTENT)]


def test_index_never_opens_a_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_index` no lee del sistema de archivos: solo pasa el texto recibido."""
    fake = RecordingIndex(success_result())
    monkeypatch.setattr(rag, "index_file", fake)

    def fail_open(*args: object, **kwargs: object) -> None:
        raise AssertionError("no debe abrirse ningún archivo")

    monkeypatch.setattr(builtins, "open", fail_open)

    output = mcp_server._index({"path": "C:\\tmp\\x.py", "content": "x = 1"})

    assert output.is_error is False
    assert fake.calls == [("C:\\tmp\\x.py", "x = 1")]


# --- Ruta obligatoria y extensión (RF-12 y RF-13) ---------------------------


@pytest.mark.parametrize(
    "arguments",
    [{}, {"path": ""}, {"path": "   "}, {"path": "\n\t"}],
    ids=["ausente", "vacia", "espacios", "saltos"],
)
def test_missing_or_blank_path_returns_the_required_message(
    monkeypatch: pytest.MonkeyPatch, arguments: dict[str, Any]
) -> None:
    """Sin ruta o con una ruta en blanco no se indexa nada."""
    fake = RecordingIndex(success_result())
    monkeypatch.setattr(rag, "index_file", fake)

    output = mcp_server._index(arguments)

    assert output.is_error is True
    assert output.content[0].text == mcp_server.MSG_PATH_REQUIRED
    assert fake.calls == []


@pytest.mark.parametrize(
    "path",
    ["x.txt", "x", "x.py.txt", "x.py ", "x.py\n", "x.pyc", "x.PY.txt"],
    ids=["txt", "sin_extension", "doble", "espacio_final", "salto_final", "pyc", "txt_mayus"],
)
def test_invalid_extensions_return_the_extension_message(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Una ruta que no termina en `.py` se rechaza por extensión."""
    fake = RecordingIndex(success_result())
    monkeypatch.setattr(rag, "index_file", fake)

    output = mcp_server._index({"path": path, "content": "x = 1"})

    assert output.is_error is True
    assert output.content[0].text == mcp_server.MSG_EXTENSION
    assert fake.calls == []


def test_extension_message_is_the_http_layer_message() -> None:
    """El mensaje de extensión reutiliza el literal de la capa HTTP (RF-13)."""
    from app import main

    assert mcp_server.MSG_EXTENSION == main.MSG_INVALID_EXTENSION


@pytest.mark.parametrize("path", ["x.py", "X.PY", "dir/x.Py"])
def test_valid_extensions_are_accepted(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """`.py` se acepta sin distinguir mayúsculas y se entrega tal cual."""
    fake = RecordingIndex(success_result(file_path=path))
    monkeypatch.setattr(rag, "index_file", fake)

    output = mcp_server._index({"path": path, "content": "x = 1"})

    assert output.is_error is False
    assert fake.calls == [(path, "x = 1")]


@pytest.mark.parametrize(
    "arguments",
    [
        {"path": "x.txt"},
        {"path": "x.txt", "content": None},
        {"path": "a.txt", "content": ""},
    ],
    ids=["ausente", "none", "vacio"],
)
def test_extension_is_checked_before_content(arguments: dict[str, Any]) -> None:
    """Con extensión inválida y contenido ausente o vacío gana la extensión."""
    output = mcp_server._index(arguments)

    assert output.is_error is True
    assert output.content[0].text == mcp_server.MSG_EXTENSION


@pytest.mark.parametrize(
    "path", [None, 1, [], {}, True], ids=["none", "entero", "lista", "dict", "booleano"]
)
def test_non_text_path_returns_the_path_type_message(path: object) -> None:
    """Un `path` que no es texto se rechaza sin intentar indexar."""
    output = mcp_server._index({"path": path, "content": "x = 1"})

    assert output.is_error is True
    assert output.content[0].text == mcp_server.MSG_PATH_NOT_TEXT


# --- Contenido obligatorio y de tipo texto (RF-14) --------------------------


def test_missing_content_returns_the_required_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `content` no se indexa y se indica que es obligatorio."""
    fake = RecordingIndex(success_result())
    monkeypatch.setattr(rag, "index_file", fake)

    output = mcp_server._index({"path": "x.py"})

    assert output.is_error is True
    assert output.content[0].text == mcp_server.MSG_CONTENT_REQUIRED
    assert fake.calls == []


@pytest.mark.parametrize(
    "content", [None, 1, [], {}, True], ids=["none", "entero", "lista", "dict", "booleano"]
)
def test_non_text_content_returns_the_content_type_message(
    monkeypatch: pytest.MonkeyPatch, content: object
) -> None:
    """Un `content` que no es texto se rechaza sin llamar a `rag.index_file`."""
    fake = RecordingIndex(success_result())
    monkeypatch.setattr(rag, "index_file", fake)

    output = mcp_server._index({"path": "x.py", "content": content})

    assert output.is_error is True
    assert output.content[0].text == mcp_server.MSG_CONTENT_NOT_TEXT
    assert fake.calls == []


def test_extra_arguments_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un argumento que no es `path` ni `content` no cambia el resultado."""
    fake = RecordingIndex(success_result())
    monkeypatch.setattr(rag, "index_file", fake)

    output = mcp_server._index(
        {"path": "x.py", "content": "x = 1", "extra": "ignorado"}
    )

    assert output.is_error is False
    assert fake.calls == [("x.py", "x = 1")]


# --- Traducción de los rechazos de la spec 002 (RF-15 a RF-18) --------------


@pytest.mark.parametrize(
    "reason", list(IndexReason), ids=[reason.value for reason in IndexReason]
)
def test_each_index_reason_is_returned_as_error_with_its_message(
    monkeypatch: pytest.MonkeyPatch, reason: IndexReason
) -> None:
    """Cualquier motivo de rechazo se convierte en error con su mensaje literal."""
    message = f"Mensaje de rechazo para {reason.value}."
    result = IndexResult(
        file_path="x.py",
        chunks_indexed=0,
        total_chunks=5,
        used_windows=False,
        reason=reason,
        message=message,
    )
    fake = RecordingIndex(result)
    monkeypatch.setattr(rag, "index_file", fake)

    output = mcp_server._index({"path": "x.py", "content": "x = 1"})

    assert output.is_error is True
    assert output.content[0].text == message


# --- Límites heredados de la spec 002 (RF-33) -------------------------------


def test_inherited_limits_are_the_spec_002_values() -> None:
    """La capa MCP no cambia el tamaño máximo ni el tope de fragmentos."""
    assert rag.MAX_FILE_BYTES == 1_048_576
    assert rag.MAX_CHUNKS_PER_FILE == 1_000
    assert not hasattr(mcp_server, "MAX_FILE_BYTES")
    assert not hasattr(mcp_server, "MAX_CHUNKS_PER_FILE")


# --- `rag.index_file` real con dobles de embeddings (RF-15 a RF-18) ---------


@pytest.mark.parametrize("content", ["", "   ", "\n\t"], ids=["vacio", "espacios", "saltos"])
def test_empty_content_uses_the_spec_002_message(
    monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    """El contenido vacío o de solo blancos se rechaza con el mensaje de la spec 002."""
    monkeypatch.setattr(rag, "_embed_chunks", fail_embedding)

    output = mcp_server._index({"path": "app/x.py", "content": content})

    assert output.is_error is True
    assert output.content[0].text == rag.EMPTY_CONTENT_MESSAGE
    assert rag.store.count == 0


def test_many_spaces_are_rejected_as_empty_before_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.100.000 espacios se rechazan por vacío, no por tamaño (RF-16)."""
    monkeypatch.setattr(rag, "_embed_chunks", fail_embedding)

    output = mcp_server._index({"path": "app/x.py", "content": " " * 1_100_000})

    assert output.is_error is True
    assert output.content[0].text == rag.EMPTY_CONTENT_MESSAGE
    assert rag.store.count == 0


def test_one_mib_is_accepted_and_indexed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.048.576 bytes UTF-8 es el límite permitido y se indexa."""
    model = FakeModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    content = "a" * rag.MAX_FILE_BYTES

    output = mcp_server._index({"path": "app/x.py", "content": content})

    assert len(content.encode("utf-8")) == 1_048_576
    assert output.is_error is False
    assert output.content[0].text.splitlines()[0] == rag._success_message(
        chunks_indexed=1, total_chunks=1, used_windows=False
    )
    assert rag.store.count == 1


def test_one_byte_over_one_mib_uses_the_spec_002_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.048.577 bytes se rechazan con el mensaje de tamaño, sin embeber."""
    monkeypatch.setattr(rag, "_embed_chunks", fail_embedding)
    content = "a" * (rag.MAX_FILE_BYTES + 1)

    output = mcp_server._index({"path": "app/x.py", "content": content})

    assert output.is_error is True
    assert output.content[0].text == rag._rejection_message(
        IndexReason.TOO_LARGE, size=1_048_577
    )
    assert rag.store.count == 0


def test_one_thousand_functions_are_indexed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.000 fragmentos caben y se indexan en el índice del proceso."""
    monkeypatch.setattr(rag, "_get_model", lambda: FakeModel())
    content = functions_source("f", rag.MAX_CHUNKS_PER_FILE)

    output = mcp_server._index({"path": "app/x.py", "content": content})

    assert output.is_error is False
    assert "Fragmentos indexados: 1.000" in output.content[0].text
    assert "Total del índice: 1.000" in output.content[0].text
    assert rag.store.count == 1_000


def test_one_thousand_and_one_functions_fail_without_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.001 fragmentos se rechazan por el tope antes de calcular representaciones."""
    monkeypatch.setattr(rag, "_embed_chunks", fail_embedding)
    content = functions_source("f", rag.MAX_CHUNKS_PER_FILE + 1)

    output = mcp_server._index({"path": "app/x.py", "content": content})

    assert output.is_error is True
    assert output.content[0].text == rag._rejection_message(
        IndexReason.TOO_MANY_CHUNKS, produced=1_001
    )
    assert rag.store.count == 0


def test_embedding_failure_uses_the_spec_002_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si el modelo no se puede cargar, se devuelve el mensaje de archivo no indexable."""

    def fail_model() -> None:
        raise RuntimeError("fallo simulado al cargar el modelo")

    monkeypatch.setattr(rag, "_get_model", fail_model)

    output = mcp_server._index({"path": "app/x.py", "content": "def login():\n    return True\n"})

    assert output.is_error is True
    assert output.content[0].text == rag.EMBEDDING_FAILED_MESSAGE
    assert rag.store.count == 0


# --- Integración con el índice real (RF-19 a RF-23) -------------------------

KEYWORDS = ("login", "logout", "saludo", "version", "pago", "auth")
KEYWORD_DIMENSIONS = len(KEYWORDS)

PREVIOUS_PATH = "app/versionada.py"
PREVIOUS_SOURCE = 'def login():\n    return "login"\n'


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


def store_snapshot() -> list[Chunk]:
    """Devuelve todos los fragmentos en orden de inserción, sin tocar atributos privados."""
    query = np.zeros(KEYWORD_DIMENSIONS, dtype=np.float32)
    return [result.chunk for result in rag.store.search(query, top_k=10_000)]


def rejection_case_arguments(case: str) -> dict[str, str]:
    """Construye los argumentos de cada rechazo de la lista de T6."""
    if case == "ruta":
        return {"path": "   ", "content": PREVIOUS_SOURCE}
    if case == "extension":
        return {"path": "app/x.txt", "content": PREVIOUS_SOURCE}
    if case == "contenido_ausente":
        return {"path": PREVIOUS_PATH}
    if case == "vacio":
        return {"path": PREVIOUS_PATH, "content": "   "}
    if case == "tamano":
        return {"path": PREVIOUS_PATH, "content": "a" * (rag.MAX_FILE_BYTES + 1)}
    if case == "tope":
        return {
            "path": PREVIOUS_PATH,
            "content": functions_source("f", rag.MAX_CHUNKS_PER_FILE + 1),
        }
    if case == "representaciones":
        return {"path": PREVIOUS_PATH, "content": PREVIOUS_SOURCE}
    raise AssertionError(f"caso de rechazo desconocido: {case}")


REJECTION_EXPECTATIONS = [
    ("ruta", mcp_server.MSG_PATH_REQUIRED),
    ("extension", mcp_server.MSG_EXTENSION),
    ("contenido_ausente", mcp_server.MSG_CONTENT_REQUIRED),
    ("vacio", rag.EMPTY_CONTENT_MESSAGE),
    (
        "tamano",
        rag._rejection_message(
            IndexReason.TOO_LARGE, size=rag.MAX_FILE_BYTES + 1
        ),
    ),
    (
        "tope",
        rag._rejection_message(
            IndexReason.TOO_MANY_CHUNKS, produced=rag.MAX_CHUNKS_PER_FILE + 1
        ),
    ),
    ("representaciones", rag.EMBEDDING_FAILED_MESSAGE),
]


def test_a_new_index_is_empty_and_mcp_server_uses_the_same_store() -> None:
    """El índice recién creado está vacío y ambas capas apuntan al mismo objeto."""
    assert rag.store.count == 0
    assert mcp_server.rag is rag
    assert mcp_server.rag.store is rag.store


def test_indexing_then_searching_finds_the_new_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con el índice real, lo indexado por MCP se encuentra con `rag.search`."""
    monkeypatch.setattr(rag, "_get_model", lambda: KeywordModel())

    indexed = mcp_server._index(
        {"path": "app/saludo.py", "content": 'def saludo():\n    return "saludo"\n'}
    )
    found = rag.search("saludo")

    assert indexed.is_error is False
    assert found.reason is None
    assert [item.chunk.file_path for item in found.results] == ["app/saludo.py"]
    assert [item.chunk.symbol_name for item in found.results] == ["saludo"]


def test_invalid_python_is_indexed_by_windows_and_the_message_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un archivo que no es Python válido se indexa por ventanas y se avisa."""
    monkeypatch.setattr(rag, "_get_model", lambda: KeywordModel())
    content = "def roto(:\n    return 'login'\n"

    output = mcp_server._index({"path": "app/roto.py", "content": content})

    assert output.is_error is False
    assert output.content[0].text.splitlines()[0] == rag._success_message(
        chunks_indexed=1, total_chunks=1, used_windows=True
    )
    assert "Troceado por ventanas: sí" in output.content[0].text
    assert [chunk.kind for chunk in store_snapshot()] == ["window"]
    assert rag.store.count == 1


def test_reindexing_replaces_the_previous_version_without_mixing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La misma ruta con contenido nuevo deja solo la versión nueva."""
    monkeypatch.setattr(rag, "_get_model", lambda: KeywordModel())

    first = mcp_server._index(
        {"path": PREVIOUS_PATH, "content": 'def old_login():\n    return "login"\n'}
    )
    second = mcp_server._index(
        {"path": PREVIOUS_PATH, "content": 'def new_logout():\n    return "logout"\n'}
    )

    stored = store_snapshot()
    assert first.is_error is False
    assert second.is_error is False
    assert rag.store.count == 1
    assert [(chunk.file_path, chunk.symbol_name) for chunk in stored] == [
        (PREVIOUS_PATH, "new_logout")
    ]
    assert "old_login" not in {chunk.symbol_name for chunk in stored}

    old = rag.search("login")
    new = rag.search("logout")
    assert old.reason is SearchReason.NO_RELEVANT
    assert [item.chunk.symbol_name for item in new.results] == ["new_logout"]


@pytest.mark.parametrize(
    ("case", "expected"),
    REJECTION_EXPECTATIONS,
    ids=[case for case, _ in REJECTION_EXPECTATIONS],
)
def test_each_rejection_keeps_the_previous_version_intact(
    monkeypatch: pytest.MonkeyPatch, case: str, expected: str
) -> None:
    """Ningún rechazo cambia el índice y la versión anterior sigue buscable."""
    model = KeywordModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    first = mcp_server._index({"path": PREVIOUS_PATH, "content": PREVIOUS_SOURCE})
    assert first.is_error is False
    before_count = rag.store.count
    before = store_snapshot()
    original_embed_chunks = rag._embed_chunks

    if case in {"vacio", "tamano", "tope"}:
        monkeypatch.setattr(rag, "_embed_chunks", fail_embedding)
    if case == "representaciones":

        def fail_model() -> None:
            raise RuntimeError("fallo simulado al cargar el modelo")

        monkeypatch.setattr(rag, "_get_model", fail_model)

    result = mcp_server._index(rejection_case_arguments(case))

    assert result.is_error is True
    assert result.content[0].text == expected
    assert rag.store.count == before_count
    assert store_snapshot() == before

    monkeypatch.setattr(rag, "_embed_chunks", original_embed_chunks)
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    found = rag.search("login")
    assert found.reason is None
    assert [item.chunk.file_path for item in found.results] == [PREVIOUS_PATH]


def test_simulated_restart_with_a_new_store_leaves_the_index_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un `VectorStore()` nuevo equivale a reiniciar: no queda nada indexado."""
    monkeypatch.setattr(rag, "_get_model", lambda: KeywordModel())
    indexed = mcp_server._index({"path": PREVIOUS_PATH, "content": PREVIOUS_SOURCE})
    assert indexed.is_error is False
    assert rag.store.count > 0

    monkeypatch.setattr(rag, "store", VectorStore())

    assert rag.store.count == 0
    result = mcp_server._dispatch(mcp_server.SEARCH_TOOL_NAME, {"query": "login"})
    assert result.is_error is False
    assert result.content[0].text == mcp_server.MSG_EMPTY_INDEX
