"""Pruebas de la herramienta de búsqueda del servidor MCP.

Usan dobles de `rag.search` para comprobar el formato y la traducción de cada
motivo, y la búsqueda real con un índice vacío o con puntuaciones por debajo
del umbral. No descargan el modelo, no usan red y no llaman a Anthropic.
"""

from typing import Any

import numpy as np
import pytest

from app import mcp_server, rag
from app.models import Chunk, SearchResponse, SearchResult
from app.storage import VectorStore


@pytest.fixture(autouse=True)
def clean_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sustituye el índice del proceso por uno vacío en cada prueba."""
    monkeypatch.setattr(rag, "store", VectorStore())


def make_chunk(
    *,
    index: int = 0,
    file_path: str = "app/x.py",
    symbol_name: str = "login",
    start_line: int = 1,
    content: str = "def login():\n    return True\n",
) -> Chunk:
    """Crea un fragmento con metadatos distintos para cada índice."""
    return Chunk(
        file_path=file_path if index == 0 else f"app/x{index}.py",
        symbol_name=symbol_name if index == 0 else f"{symbol_name}_{index}",
        start_line=start_line + index * 10,
        end_line=start_line + index * 10 + 4,
        content=content if index == 0 else f"def fn_{index}():\n    return {index}\n",
        kind="function",
    )


def make_result(index: int = 0, score: float = 0.87) -> SearchResult:
    """Crea un resultado de búsqueda con un fragmento y una puntuación."""
    return SearchResult(chunk=make_chunk(index=index), score=score)


class RecordingSearch:
    """Doble de `rag.search` que registra la consulta y devuelve una respuesta."""

    def __init__(self, response: SearchResponse) -> None:
        self.response = response
        self.queries: list[str] = []

    def __call__(self, query: str) -> SearchResponse:
        self.queries.append(query)
        return self.response


# --- Formato de los resultados (RF-3 y RF-9) --------------------------------


@pytest.mark.parametrize("count", [1, 3, 5], ids=["uno", "tres", "cinco"])
def test_search_formats_one_block_per_fragment_in_order(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    """Cada fragmento produce su bloque, en el mismo orden y sin añadir nada."""
    results = [make_result(index=index) for index in range(count)]
    fake_search = RecordingSearch(SearchResponse(results=results))
    monkeypatch.setattr(rag, "search", fake_search)

    result = mcp_server._search({"query": "  login  "})

    assert result.is_error is False
    assert fake_search.queries == ["  login  "]
    text = result.content[0].text
    expected = "\n\n".join(
        f"Fragmento {index} de {count}\n"
        f"Ruta: {item.chunk.file_path}\n"
        f"Símbolo: {item.chunk.symbol_name}\n"
        f"Líneas: {item.chunk.start_line}–{item.chunk.end_line}\n"
        f"Relevancia: 0,87\n"
        f"Texto:\n"
        f"{item.chunk.content}"
        for index, item in enumerate(results, 1)
    )
    assert text == expected
    assert text.count("Fragmento ") == count
    assert [text.index(item.chunk.file_path) for item in results] == sorted(
        text.index(item.chunk.file_path) for item in results
    )


# --- Casos límite de búsqueda (mayúsculas, tildes y símbolos) ----------------


class RecordingModel:
    """Doble de embeddings que registra el texto y devuelve un vector fijo."""

    def __init__(self) -> None:
        """Prepara la lista de textos recibidos por el modelo."""
        self.texts: list[str] = []

    def encode(
        self, texts: str | list[str], normalize_embeddings: bool = True
    ) -> np.ndarray:
        """Registra el texto y devuelve `[1, 0]` para cada entrada."""
        if isinstance(texts, str):
            self.texts.append(texts)
            return np.array([1.0, 0.0], dtype=np.float32)
        items = list(texts)
        self.texts.extend(items)
        return np.array([[1.0, 0.0] for _ in items], dtype=np.float32)


@pytest.mark.parametrize(
    "query",
    [
        "LOGIN",
        "Autenticación",
        "  login   auth  ",
        "¿Dónde está el login? ()",
        "login 🤖",
    ],
    ids=["mayusculas", "tildes", "espacios", "puntuacion", "emoji"],
)
def test_special_queries_are_normalized_without_error(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    """Mayúsculas, tildes, espacios y símbolos usan la normalización de la spec 001."""
    rag.store.add([make_chunk()], np.array([[1.0, 0.0]], dtype=np.float32))
    model = RecordingModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)

    result = mcp_server._search({"query": query})

    assert result.is_error is False
    assert result.content[0].text.startswith("Fragmento 1 de 1")
    assert model.texts == [rag._normalize_query(query)]
    normalized = model.texts[0]
    assert normalized == normalized.lower()
    assert "  " not in normalized
    assert not any(char in normalized for char in "áéíóúÁÉÍÓÚ")


# --- Consultas vacías, largas o de tipo incorrecto (RF-4, RF-5, RF-6 y RF-27) --


@pytest.mark.parametrize(
    "query", ["", "   ", "\n\t"], ids=["vacia", "espacios", "saltos"]
)
def test_blank_query_returns_the_rag_error(query: str) -> None:
    """Una consulta vacía o de solo espacios se rechaza con el mensaje de la spec 001."""
    result = mcp_server._search({"query": query})

    assert result.is_error is True
    assert result.content[0].text == rag.EMPTY_QUERY_MESSAGE


def test_query_length_boundaries_and_blank_precedence() -> None:
    """1.000 caracteres pasan; 1.001 fallan; 1.001 espacios ganan como vacío."""
    accepted = mcp_server._search({"query": "a" * 1000})
    too_long = mcp_server._search({"query": "a" * 1001})
    blank_and_long = mcp_server._search({"query": " " * 1001})

    assert accepted.is_error is False
    assert accepted.content[0].text == mcp_server.MSG_EMPTY_INDEX
    assert too_long.is_error is True
    assert too_long.content[0].text == rag.QUERY_TOO_LONG_MESSAGE
    assert blank_and_long.is_error is True
    assert blank_and_long.content[0].text == rag.EMPTY_QUERY_MESSAGE


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({}, mcp_server.MSG_QUERY_REQUIRED),
        ({"query": None}, mcp_server.MSG_QUERY_NOT_TEXT),
        ({"query": 1}, mcp_server.MSG_QUERY_NOT_TEXT),
        ({"query": []}, mcp_server.MSG_QUERY_NOT_TEXT),
        ({"query": {}}, mcp_server.MSG_QUERY_NOT_TEXT),
    ],
    ids=["ausente", "none", "entero", "lista", "diccionario"],
)
def test_missing_or_non_text_query_does_not_call_search(
    monkeypatch: pytest.MonkeyPatch, arguments: dict[str, Any], expected: str
) -> None:
    """Un `query` ausente o de otro tipo no llega a `rag.search`."""
    monkeypatch.setattr(
        rag, "search", lambda query: pytest.fail("no debe llamarse a rag.search")
    )

    result = mcp_server._search(arguments)

    assert result.is_error is True
    assert result.content[0].text == expected


# --- Índice vacío y ausencia de resultados relevantes (RF-7 y RF-8) ----------


def test_empty_index_returns_the_adapted_message_without_error() -> None:
    """Sin código indexado se devuelve el mensaje adaptado, sin marca de error."""
    result = mcp_server._search({"query": "login"})

    assert result.is_error is False
    assert result.content[0].text == mcp_server.MSG_EMPTY_INDEX
    assert result.content[0].text != rag.EMPTY_INDEX_MESSAGE
    assert "index_file" in result.content[0].text
    assert ".py" in result.content[0].text


def test_fragment_below_the_threshold_returns_no_relevant_without_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fragmento con puntuación 0,10 no alcanza el umbral y no es un error."""
    rag.store.add([make_chunk()], np.array([[0.10, 0.0]], dtype=np.float32))
    monkeypatch.setattr(
        rag,
        "_embed_query",
        lambda query: np.array([1.0, 0.0], dtype=np.float32),
    )

    result = mcp_server._search({"query": "autenticación"})

    assert result.is_error is False
    assert result.content[0].text == rag.NO_RELEVANT_MESSAGE


# --- Motivos desconocidos y límites heredados (RF-33) ------------------------


def test_unknown_reason_returns_the_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un motivo no previsto no se trata como éxito."""
    response = SearchResponse.model_construct(
        results=[], reason="motivo_desconocido", message="texto interno"
    )
    monkeypatch.setattr(rag, "search", lambda query: response)

    result = mcp_server._search({"query": "login"})

    assert result.is_error is True
    assert result.content[0].text == mcp_server.MSG_INTERNAL_ERROR


def test_inherited_limits_are_the_spec_001_values() -> None:
    """La capa MCP no cambia los límites de la búsqueda de la spec 001."""
    assert rag.MAX_RESULTS == 5
    assert rag.MIN_SCORE == 0.30
    assert rag.MAX_QUERY_LENGTH == 1_000
