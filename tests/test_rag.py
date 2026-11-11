"""Pruebas de la búsqueda semántica de la spec 001.

Cubren validación y normalización de la consulta, la búsqueda completa con
dobles de embeddings y store, y los cuatro motivos de resultado vacío.
No descargan el modelo real, no usan red y no llaman a Anthropic.
"""

import inspect
import os

import numpy as np
import pytest

from app import rag
from app.models import Chunk, SearchReason, SearchResponse
from app.storage import VectorStore


@pytest.fixture(autouse=True)
def clean_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sustituye el singleton en memoria por uno vacío en cada prueba."""
    monkeypatch.setattr(rag, "store", VectorStore())


def make_chunk(
    symbol_name: str = "search",
    file_path: str = "app/rag.py",
    start_line: int = 1,
    end_line: int | None = None,
) -> Chunk:
    """Crea un chunk con metadatos de cita distintos para cada símbolo."""
    return Chunk(
        file_path=file_path,
        symbol_name=symbol_name,
        start_line=start_line,
        end_line=start_line + 4 if end_line is None else end_line,
        content=f"def {symbol_name}(): ...",
        kind="function",
    )


def index_scores(scores: list[float]) -> None:
    """Indexa un chunk por puntuación; con el vector de consulta [1, 0], el score es la fila."""
    chunks = [
        make_chunk(symbol_name=f"fn_{index}", start_line=index * 10 + 1)
        for index in range(len(scores))
    ]
    embeddings = np.array([[score, 0.0] for score in scores], dtype=np.float32)
    rag.store.add(chunks, embeddings)


@pytest.fixture
def query_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fija el vector de la consulta para que las puntuaciones sean predecibles."""
    monkeypatch.setattr(
        rag,
        "_embed_query",
        lambda query: np.array([1.0, 0.0], dtype=np.float32),
    )


class KeywordModel:
    """Doble del modelo de embeddings: asigna un vector fijo según palabras clave."""

    def __init__(
        self, keywords: tuple[str, ...] = ("login", "autenticacion", "valida")
    ) -> None:
        self.keywords = keywords
        self.texts: list[str] = []

    def encode(self, text: str, normalize_embeddings: bool = True) -> np.ndarray:
        """Registra el texto recibido y devuelve un vector unitario."""
        self.texts.append(text)
        if any(keyword in text for keyword in self.keywords):
            return np.array([1.0, 0.0], dtype=np.float32)
        return np.array([0.0, 1.0], dtype=np.float32)


@pytest.mark.parametrize("query", ["", "   ", "\n\t", "  \n  "])
def test_validate_query_rejects_empty_or_blank_queries(query: str) -> None:
    """Una consulta vacía o de solo espacios se rechaza como obligatoria."""
    outcome = rag._validate_query(query)

    assert outcome is not None
    reason, message = outcome
    assert reason is SearchReason.EMPTY_QUERY
    assert message


def test_validate_query_checks_empty_before_length() -> None:
    """1.500 espacios son una consulta vacía, no una consulta demasiado larga."""
    outcome = rag._validate_query(" " * 1500)

    assert outcome is not None
    reason, _ = outcome
    assert reason is SearchReason.EMPTY_QUERY


def test_validate_query_accepts_exactly_the_limit() -> None:
    """1.000 caracteres se aceptan."""
    assert rag._validate_query("a" * 1000) is None


def test_validate_query_rejects_one_character_over_the_limit() -> None:
    """1.001 caracteres se rechazan con el motivo de longitud."""
    outcome = rag._validate_query("a" * 1001)

    assert outcome is not None
    reason, message = outcome
    assert reason is SearchReason.QUERY_TOO_LONG
    assert "1.000" in message


def test_validate_query_accepts_a_normal_question() -> None:
    """Una pregunta normal no tiene ningún motivo de rechazo."""
    assert rag._validate_query("¿Dónde se validan los tokens?") is None


def test_validation_messages_are_distinct_and_clear() -> None:
    """Los dos mensajes de validación son distintos y explican el problema."""
    empty_outcome = rag._validate_query("")
    long_outcome = rag._validate_query("a" * 1001)
    assert empty_outcome is not None
    assert long_outcome is not None

    _, empty_message = empty_outcome
    _, long_message = long_outcome

    assert empty_message != long_message
    assert "obligatoria" in empty_message
    assert "1.000" in long_message


def test_normalize_query_lowercases_and_strips_accents() -> None:
    """Mayúsculas, tildes y espacios repetidos se reducen a una forma simple."""
    assert (
        rag._normalize_query("  Autenticación   DE Usuarios ")
        == "autenticacion de usuarios"
    )


def test_normalize_query_handles_all_spanish_accents() -> None:
    """Todas las vocales acentuadas y la eñe pierden su diacrítico."""
    assert rag._normalize_query("ÁÉÍÓÚÜÑ áéíóúüñ") == "aeiouun aeiouun"


def test_normalize_query_tolerates_punctuation() -> None:
    """Los signos de puntuación no rompen la normalización."""
    normalized = rag._normalize_query("¿Dónde se valida el token?? (JWT)")

    assert normalized == "¿donde se valida el token?? (jwt)"


def test_normalize_query_is_idempotent() -> None:
    """Normalizar dos veces da el mismo texto que normalizar una vez."""
    once = rag._normalize_query("  Consulta   Con   Tildes ")
    assert rag._normalize_query(once) == once


def test_search_returns_at_most_five_results_in_descending_order(
    query_vector: None,
) -> None:
    """Con siete fragmentos relevantes, se devuelven cinco del más al menos parecido."""
    index_scores([0.95, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4])

    response = rag.search("¿Dónde está la autenticación?")

    assert isinstance(response, SearchResponse)
    assert response.reason is None
    assert response.message is None
    assert [result.score for result in response.results] == pytest.approx(
        [0.95, 0.9, 0.8, 0.7, 0.6]
    )


def test_search_discards_fragments_below_the_threshold(query_vector: None) -> None:
    """0,29 queda fuera y 0,31 entra con el umbral por defecto de 0,30."""
    index_scores([0.29, 0.31])

    response = rag.search("autenticación")

    assert [result.score for result in response.results] == pytest.approx([0.31])


@pytest.mark.parametrize(
    ("score", "relevant"),
    [
        (0.29, False),
        (0.30, True),
        (float(np.float32(0.29999998)), True),
        (0.299999, False),
    ],
)
def test_is_relevant_compares_the_rounded_score(score: float, relevant: bool) -> None:
    """El umbral se compara con la puntuación redondeada a seis decimales."""
    assert rag._is_relevant(score) is relevant


def test_search_without_indexed_code_explains_it(query_vector: None) -> None:
    """Sin índice, la respuesta indica que no hay código indexado."""
    response = rag.search("¿Dónde está la autenticación?")

    assert response.results == []
    assert response.reason is SearchReason.EMPTY_INDEX
    assert response.message == rag.EMPTY_INDEX_MESSAGE


def test_search_does_not_embed_when_the_index_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin índice no se gasta tiempo en calcular el vector de la consulta."""
    monkeypatch.setattr(
        rag, "_embed_query", lambda query: pytest.fail("no debe embeberse")
    )

    response = rag.search("autenticación")

    assert response.reason is SearchReason.EMPTY_INDEX


def test_search_without_relevant_fragments_explains_it(query_vector: None) -> None:
    """Con índice pero sin puntuaciones suficientes, se avisa de que no hay relevantes."""
    index_scores([0.1, 0.2])

    response = rag.search("autenticación")

    assert response.results == []
    assert response.reason is SearchReason.NO_RELEVANT
    assert response.message == rag.NO_RELEVANT_MESSAGE


@pytest.mark.parametrize("query", ["", "   ", "\n\t", "  \n  "])
def test_search_rejects_blank_queries(
    monkeypatch: pytest.MonkeyPatch, query: str
) -> None:
    """Una consulta vacía se rechaza antes de tocar el índice o el modelo."""
    monkeypatch.setattr(
        rag, "_embed_query", lambda text: pytest.fail("no debe embeberse")
    )

    response = rag.search(query)

    assert response.results == []
    assert response.reason is SearchReason.EMPTY_QUERY
    assert response.message == rag.EMPTY_QUERY_MESSAGE


def test_search_rejects_queries_over_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una consulta de 1.001 caracteres se rechaza sin calcular su vector."""
    monkeypatch.setattr(
        rag, "_embed_query", lambda text: pytest.fail("no debe embeberse")
    )

    response = rag.search("a" * 1001)

    assert response.results == []
    assert response.reason is SearchReason.QUERY_TOO_LONG
    assert response.message == rag.QUERY_TOO_LONG_MESSAGE


def test_search_accepts_a_query_of_exactly_the_limit(query_vector: None) -> None:
    """1.000 caracteres se aceptan y llegan a la búsqueda."""
    index_scores([0.9])

    response = rag.search("a" * 1000)

    assert response.reason is None
    assert len(response.results) == 1


def test_results_include_every_citation_field(query_vector: None) -> None:
    """Cada resultado trae ruta, símbolo, líneas, texto y puntuación."""
    chunk = make_chunk(symbol_name="login", file_path="app/auth.py", start_line=12)
    rag.store.add([chunk], np.array([[0.9, 0.0]], dtype=np.float32))

    result = rag.search("login").results[0]

    assert result.chunk.file_path == "app/auth.py"
    assert result.chunk.symbol_name == "login"
    assert result.chunk.start_line == 12
    assert result.chunk.end_line == 16
    assert result.chunk.content == "def login(): ..."
    assert result.score == pytest.approx(0.9)


def test_the_same_query_returns_the_same_order(query_vector: None) -> None:
    """Dos búsquedas iguales sobre el mismo índice dan el mismo resultado."""
    index_scores([0.9, 0.9, 0.8])

    first = rag.search("autenticación")
    second = rag.search("autenticación")

    assert [result.chunk.symbol_name for result in first.results] == [
        result.chunk.symbol_name for result in second.results
    ]


def test_search_recovers_by_meaning_without_shared_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fragmento sobre login se recupera preguntando por validar al usuario."""
    monkeypatch.setattr(rag, "_get_model", lambda: KeywordModel())
    rag.store.add(
        [
            make_chunk(symbol_name="login"),
            make_chunk(symbol_name="suma", start_line=10),
        ],
        np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
    )

    response = rag.search("¿Cómo se valida el usuario?")

    assert [result.chunk.symbol_name for result in response.results] == ["login"]


def test_equivalent_queries_reach_the_model_with_the_same_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mayúsculas y tildes se normalizan antes de calcular el embedding."""
    model = KeywordModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    rag.store.add(
        [make_chunk(symbol_name="login")], np.array([[1.0, 0.0]], dtype=np.float32)
    )

    rag.search("Autenticación")
    rag.search("autenticacion")

    assert model.texts == ["autenticacion", "autenticacion"]


def test_search_tolerates_punctuation(query_vector: None) -> None:
    """Los signos de puntuación no producen errores."""
    index_scores([0.9])

    response = rag.search("¿Dónde se valida el token?? (JWT)")

    assert response.reason is None


def test_search_returns_a_single_relevant_fragment(query_vector: None) -> None:
    """Solo un fragmento supera el umbral: se devuelve uno."""
    index_scores([0.9, 0.1])

    assert len(rag.search("autenticación").results) == 1


def test_search_returns_three_when_only_three_pass(query_vector: None) -> None:
    """Con tres fragmentos relevantes se devuelven tres, no cinco."""
    index_scores([0.9, 0.8, 0.7, 0.1, 0.2])

    assert len(rag.search("autenticación").results) == 3


def test_the_same_symbol_in_two_files_appears_twice(query_vector: None) -> None:
    """Cada archivo conserva su propia cita aunque el símbolo se repita."""
    rag.store.add(
        [
            make_chunk(symbol_name="search", file_path="app/rag.py", start_line=1),
            make_chunk(symbol_name="search", file_path="app/bot.py", start_line=1),
        ],
        np.array([[0.9, 0.0], [0.8, 0.0]], dtype=np.float32),
    )

    results = rag.search("buscar").results

    assert [result.chunk.file_path for result in results] == [
        "app/rag.py",
        "app/bot.py",
    ]


def test_the_four_empty_messages_are_distinct(query_vector: None) -> None:
    """Los cuatro motivos de lista vacía se explican con mensajes diferentes."""
    empty_index = rag.search("autenticación").message
    blank = rag.search("   ").message
    too_long = rag.search("a" * 1001).message
    index_scores([0.1])
    no_relevant = rag.search("autenticación").message

    messages = {empty_index, blank, too_long, no_relevant}

    assert len(messages) == 4
    assert all(message and message.endswith(".") for message in messages)


@pytest.mark.skipif(
    not os.getenv("CODEMENTOR_REAL_MODEL"),
    reason="Requiere descargar el modelo real; activar con CODEMENTOR_REAL_MODEL=1.",
)
def test_real_model_recovers_a_fragment_with_other_words() -> None:
    """Prueba opcional con el modelo real: recupera por significado, no por palabras."""
    rag._get_model.cache_clear()
    model = rag._get_model()
    chunks = [
        make_chunk(symbol_name="login", file_path="app/auth.py", start_line=1),
        make_chunk(symbol_name="suma", file_path="app/math.py", start_line=10),
    ]
    embeddings = model.encode(
        [
            "def login(user, password):\n    return check_password(user, password)",
            "def suma(a, b):\n    return a + b",
        ],
        normalize_embeddings=True,
    )
    rag.store.add(chunks, np.asarray(embeddings, dtype=np.float32))

    response = rag.search("¿Dónde se valida el usuario?")

    assert response.results
    assert response.results[0].chunk.symbol_name == "login"


class NoEmbeddingModel:
    """Doble del modelo que falla si alguien intenta calcular embeddings."""

    def encode(self, *args: object, **kwargs: object) -> None:
        """Cualquier llamada es un fallo: `warm_up` no debe embeber nada."""
        pytest.fail("warm_up no debe calcular embeddings")


class CountingModelGetter:
    """Doble de `_get_model` que cuenta cuántas veces se pide el modelo."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> NoEmbeddingModel:
        """Registra la llamada y devuelve un modelo que no se debe usar."""
        self.calls += 1
        return NoEmbeddingModel()


def test_warm_up_loads_the_model_once_without_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`warm_up` pide el modelo una sola vez y no calcula embeddings."""
    getter = CountingModelGetter()
    monkeypatch.setattr(rag, "_get_model", getter)

    rag.warm_up()

    assert getter.calls == 1


def test_each_warm_up_call_asks_for_the_model_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dos llamadas piden el modelo dos veces: la idempotencia es del `lru_cache`."""
    getter = CountingModelGetter()
    monkeypatch.setattr(rag, "_get_model", getter)

    rag.warm_up()
    rag.warm_up()

    assert getter.calls == 2


def test_warm_up_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """El calentamiento no devuelve nada: solo carga el modelo."""
    monkeypatch.setattr(rag, "_get_model", CountingModelGetter())

    assert rag.warm_up() is None


def test_warm_up_is_public_and_annotated() -> None:
    """El calentamiento es público (`warm_up`, no `_warm_up`) y no devuelve nada."""
    assert callable(rag.warm_up)
    assert not hasattr(rag, "_warm_up")
    signature = inspect.signature(rag.warm_up)
    assert not signature.parameters
    assert signature.return_annotation in (None, "None")
