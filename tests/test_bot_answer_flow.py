"""Pruebas del flujo completo de `bot.answer` con el índice real.

Cubren RF-1, RF-2, RF-3, RF-13, RF-18, RF-19 y RF-22: el recorrido indexar →
preguntar → citar, el orden búsqueda → clave, los cuatro motivos de la
búsqueda, la independencia entre llamadas, el invariante de RF-19 y que un
fallo del modelo no toca el índice.

No usan red, claves reales ni el modelo de embeddings: `_embed_chunks` y
`_embed_query` se sustituyen por dobles y el cliente por un `FakeClient`. El
índice se llena con `rag.index_file`, como en las pruebas de las specs 001 y
002.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from conftest import FakeClient, build_timeout_error, make_message_response

from app import bot, rag
from app.models import (
    ChatMessage,
    ChatReason,
    ChatResponse,
    Chunk,
    Citation,
    SearchResponse,
    SearchResult,
)
from app.storage import VectorStore

LOGIN_PATH = "app/auth.py"
LOGIN_SOURCE = "def login(user):\n    return check(user)\n"
LOGIN_QUESTION = "¿Dónde se valida el usuario?"

#: Clave falsa: nunca debe usarse de verdad ni filtrarse a las respuestas.
SECRET_KEY = "clave-secreta-de-prueba"


@pytest.fixture(autouse=True)
def clean_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sustituye el singleton en memoria por uno vacío en cada prueba."""
    monkeypatch.setattr(rag, "store", VectorStore())


def _unit(*components: float) -> np.ndarray:
    """Devuelve un vector normalizado en `float32`."""
    vector = np.array(components, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def _patch_embeddings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    chunk: tuple[float, ...] = (1.0, 0.0, 0.0),
    query: tuple[float, ...] = (1.0, 0.0, 0.0),
) -> None:
    """Sustituye el modelo de embeddings por vectores fijos y normalizados.

    Con el vector por defecto, cada fragmento y la consulta apuntan en la misma
    dirección: la puntuación es 1 y la búsqueda los considera relevantes. Con
    una consulta ortogonal la puntuación es 0 y se fuerza `no_relevant`.
    """
    chunk_vector = _unit(*chunk)
    query_vector = _unit(*query)

    def embed_chunks(chunks: list[Chunk]) -> np.ndarray:
        return np.tile(chunk_vector, (len(chunks), 1)).astype(np.float32)

    monkeypatch.setattr(rag, "_embed_chunks", embed_chunks)
    monkeypatch.setattr(rag, "_embed_query", lambda _query: query_vector.copy())


def _expected_chunk() -> Chunk:
    """Fragmento que produce el archivo de prueba, sin tocar el índice."""
    return rag.chunk_python_file(LOGIN_SOURCE, LOGIN_PATH)[0]


def _expected_citation(number: int = 1) -> Citation:
    """Cita esperada a partir del fragmento del archivo de prueba."""
    chunk = _expected_chunk()
    return Citation(
        number=number,
        file_path=chunk.file_path,
        symbol_name=chunk.symbol_name,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
    )


def _index_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """Indexa el archivo de prueba con el doble de embeddings."""
    _patch_embeddings(monkeypatch)
    result = rag.index_file(LOGIN_PATH, LOGIN_SOURCE)
    assert result.reason is None
    assert result.chunks_indexed == 1


def _use_client(
    monkeypatch: pytest.MonkeyPatch,
    text: str = "La función está en auth.py [F1].",
    error: BaseException | None = None,
) -> FakeClient:
    """Sustituye `bot._get_client` por un `FakeClient` configurable."""
    client = FakeClient(response=make_message_response(text), error=error)
    monkeypatch.setattr(bot, "_get_client", lambda: client)
    return client


def _forbid_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hace fallar la prueba si `answer` intenta crear el cliente."""

    def fail() -> None:
        raise AssertionError("no se debe crear el cliente del modelo")

    monkeypatch.setattr(bot, "_get_client", fail)


def _assert_rf19(response: ChatResponse) -> None:
    """Comprueba que éxito ⇔ motivo ausente ⇔ al menos una cita (RF-19)."""
    has_citations = bool(response.citations)
    assert (response.reason is None) is has_citations
    if response.reason is not None:
        assert response.citations == []


def _snapshot(dimensions: int = 3) -> list[tuple[str, str, int, int, str]]:
    """Devuelve el contenido del índice en orden, sin depender de la puntuación."""
    query = np.zeros(dimensions, dtype=np.float32)
    results = rag.store.search(query, top_k=1_000)
    return [
        (
            result.chunk.file_path,
            result.chunk.symbol_name,
            result.chunk.start_line,
            result.chunk.end_line,
            result.chunk.content,
        )
        for result in results
    ]


def _prepare_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deja el índice vacío: lo necesitan los casos de consulta o índice vacío."""


def _prepare_no_relevant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Indexa un fragmento y usa una consulta ortogonal, bajo el umbral."""
    _patch_embeddings(monkeypatch, query=(0.0, 1.0, 0.0))
    result = rag.index_file(LOGIN_PATH, LOGIN_SOURCE)
    assert result.reason is None


SEARCH_FAILURE_CASES = [
    pytest.param(
        _prepare_nothing,
        "   ",
        ChatReason.EMPTY_QUERY,
        rag.EMPTY_QUERY_MESSAGE,
        id="empty_query",
    ),
    pytest.param(
        _prepare_nothing,
        "a" * (rag.MAX_QUERY_LENGTH + 1),
        ChatReason.QUERY_TOO_LONG,
        rag.QUERY_TOO_LONG_MESSAGE,
        id="query_too_long",
    ),
    pytest.param(
        _prepare_nothing,
        LOGIN_QUESTION,
        ChatReason.EMPTY_INDEX,
        rag.EMPTY_INDEX_MESSAGE,
        id="empty_index",
    ),
    pytest.param(
        _prepare_no_relevant,
        LOGIN_QUESTION,
        ChatReason.NO_RELEVANT,
        rag.NO_RELEVANT_MESSAGE,
        id="no_relevant",
    ),
]


# --- Caso feliz (RF-1, RF-19) ----------------------------------------------


def test_happy_path_returns_reply_citation_and_no_reason(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """Con índice y clave, `answer` devuelve texto, una cita y `reason=None`."""
    _index_login(monkeypatch)
    set_api_key(SECRET_KEY)
    client = _use_client(monkeypatch, "La función login está en auth.py [F1].")

    response = bot.answer(LOGIN_QUESTION, [])

    assert response.reply == "La función login está en auth.py [F1]."
    assert response.reason is None
    assert response.citations == [_expected_citation()]
    assert len(client.calls) == 1
    _assert_rf19(response)


# --- Los cuatro motivos de la búsqueda (RF-2) -------------------------------


@pytest.mark.parametrize(
    ("prepare", "question", "reason", "message"),
    SEARCH_FAILURE_CASES,
)
def test_each_search_reason_returns_its_message_without_calling_the_model(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
    prepare: Callable[[pytest.MonkeyPatch], None],
    question: str,
    reason: ChatReason,
    message: str,
) -> None:
    """Cada motivo de la búsqueda usa su mensaje y no llega a llamar al modelo."""
    set_api_key(SECRET_KEY)
    prepare(monkeypatch)
    client = _use_client(monkeypatch)

    response = bot.answer(question, [])

    assert client.calls == []
    assert response.reply == message
    assert response.reason == reason
    assert response.citations == []
    _assert_rf19(response)


# --- Orden búsqueda → clave (RF-13) -----------------------------------------


@pytest.mark.parametrize(
    ("prepare", "question", "reason", "message"),
    SEARCH_FAILURE_CASES,
)
def test_search_reason_wins_over_the_missing_key(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
    prepare: Callable[[pytest.MonkeyPatch], None],
    question: str,
    reason: ChatReason,
    message: str,
) -> None:
    """Sin clave, un fallo de la búsqueda conserva el motivo de la búsqueda."""
    set_api_key(None)
    prepare(monkeypatch)
    _forbid_client(monkeypatch)

    response = bot.answer(question, [])

    assert response.reason == reason
    assert response.reply == message
    assert response.citations == []
    _assert_rf19(response)


@pytest.mark.parametrize("key", [None, "", "   ", "\n\t "])
def test_fragments_without_key_fail_before_creating_the_client(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
    key: str | None,
) -> None:
    """Con fragmentos y sin clave: `missing_api_key` y el cliente no se crea.

    La variable ausente, vacía y de solo espacios cuentan como falta de clave.
    """
    _index_login(monkeypatch)
    set_api_key(key)
    _forbid_client(monkeypatch)

    response = bot.answer(LOGIN_QUESTION, [])

    assert response.reason == ChatReason.MISSING_API_KEY
    assert response.reply == bot._FAILURE_MESSAGES[ChatReason.MISSING_API_KEY]
    assert response.citations == []
    _assert_rf19(response)


# --- Solo la pregunta actual a la búsqueda (RF-3) ---------------------------


def test_search_receives_only_the_question_even_when_history_changes(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """Dos historiales distintos con la misma pregunta reciben la misma búsqueda."""
    set_api_key(SECRET_KEY)
    _use_client(monkeypatch)
    delivered = [SearchResult(chunk=_expected_chunk(), score=0.9)]
    queries: list[str] = []

    def fake_search(query: str) -> SearchResponse:
        queries.append(query)
        return SearchResponse(results=delivered)

    monkeypatch.setattr(rag, "search", fake_search)

    first = bot.answer(LOGIN_QUESTION, [ChatMessage(role="user", content="antes")])
    second = bot.answer(
        LOGIN_QUESTION, [ChatMessage(role="user", content="otra conversación")]
    )

    assert queries == [LOGIN_QUESTION, LOGIN_QUESTION]
    assert first.reason is None
    assert second.reason is None
    _assert_rf19(first)
    _assert_rf19(second)


# --- Marcas en la pregunta y en la respuesta (RF-7, RF-8) -------------------


def test_a_marker_in_the_question_does_not_create_citations(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """La marca de la pregunta no cuenta: sin marcas del modelo es `ungrounded`."""
    _index_login(monkeypatch)
    set_api_key(SECRET_KEY)
    client = _use_client(monkeypatch, "La función está en auth.py.")
    question = "¿Qué hace [F1]?"

    response = bot.answer(question, [])

    assert client.calls
    assert question in client.last_call["messages"][-1]["content"]
    assert response.reason == ChatReason.UNGROUNDED_ANSWER
    assert response.citations == []
    _assert_rf19(response)


def test_a_model_marker_cites_the_delivered_fragment_not_the_question(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """La cita sale del fragmento entregado aunque la pregunta lleve `[F1]`."""
    _index_login(monkeypatch)
    set_api_key(SECRET_KEY)
    _use_client(monkeypatch, "La función está en auth.py [F1].")

    response = bot.answer("¿Qué hace [F1]?", [])

    assert response.reason is None
    assert response.citations == [_expected_citation()]
    assert response.reply == "La función está en auth.py [F1]."
    _assert_rf19(response)


# --- Pregunta en otro idioma (RF-5) -----------------------------------------


def test_a_question_in_another_language_is_processed_the_same_way(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """Una pregunta en inglés se responde igual y el sistema pide español."""
    _index_login(monkeypatch)
    set_api_key(SECRET_KEY)
    client = _use_client(monkeypatch, "The login function is here [F1].")

    response = bot.answer("Where is the login function?", [])

    assert response.reason is None
    assert response.citations == [_expected_citation()]
    assert client.last_call["system"] == bot.SYSTEM_PROMPT
    assert "español" in client.last_call["system"]
    assert "Where is the login function?" in client.last_call["messages"][-1]["content"]
    _assert_rf19(response)


# --- Fallo del modelo e independencia (RF-18, RF-22) ------------------------


def test_a_model_failure_leaves_the_index_untouched(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """Un `api_timeout` no cambia el recuento ni el contenido del índice."""
    _index_login(monkeypatch)
    set_api_key(SECRET_KEY)
    before_count = rag.store.count
    before = _snapshot()
    _use_client(monkeypatch, error=build_timeout_error())

    response = bot.answer(LOGIN_QUESTION, [])

    assert response.reason == ChatReason.API_TIMEOUT
    assert response.citations == []
    assert rag.store.count == before_count
    assert _snapshot() == before
    _assert_rf19(response)


def test_two_calls_do_not_share_question_or_history(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """La segunda llamada no incluye la pregunta ni el historial de la primera."""
    _index_login(monkeypatch)
    set_api_key(SECRET_KEY)
    client = _use_client(monkeypatch, "Está en auth.py [F1].")
    first_question = "pregunta-alfa"
    second_question = "pregunta-beta"
    history = [
        ChatMessage(role="user", content="historial-secreto-uno"),
        ChatMessage(role="assistant", content="respuesta-previa-uno"),
    ]

    first = bot.answer(first_question, history)
    second = bot.answer(second_question, [])

    assert first.reason is None
    assert second.reason is None
    assert len(client.calls) == 2
    first_payload = str(client.calls[0]["messages"])
    second_payload = str(client.calls[1]["messages"])
    assert "historial-secreto-uno" in first_payload
    for stale in (first_question, "historial-secreto-uno", "respuesta-previa-uno"):
        assert stale not in second_payload
    assert second_question in second_payload
    _assert_rf19(first)
    _assert_rf19(second)


# --- Determinismo (RF-20) ----------------------------------------------------


def test_two_identical_calls_send_exactly_the_same_text_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """RF-20: misma pregunta, índice e historial producen idéntica llamada."""
    _index_login(monkeypatch)
    set_api_key(SECRET_KEY)
    client = _use_client(monkeypatch, "Está en auth.py [F1].")
    history = [
        ChatMessage(role="user", content="hola"),
        ChatMessage(role="assistant", content="¿en qué te ayudo?"),
    ]

    first = bot.answer(LOGIN_QUESTION, history)
    second = bot.answer(LOGIN_QUESTION, history)

    assert len(client.calls) == 2
    assert client.calls[0]["system"] == client.calls[1]["system"]
    assert client.calls[0]["messages"] == client.calls[1]["messages"]
    assert first == second
    _assert_rf19(first)


# --- Recorrido completo (RF-1, RF-8) ----------------------------------------


def test_full_journey_index_file_then_answer_cites_the_indexed_function(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """Indexar, preguntar y citar devuelve ruta, símbolo y líneas reales."""
    _patch_embeddings(monkeypatch)
    result = rag.index_file(LOGIN_PATH, LOGIN_SOURCE)
    expected = _expected_chunk()
    set_api_key(SECRET_KEY)
    _use_client(monkeypatch, "La validación está en login [F1].")

    response = bot.answer(LOGIN_QUESTION, [])

    assert result.reason is None
    assert response.reason is None
    assert response.reply == "La validación está en login [F1]."
    assert len(response.citations) == 1
    citation = response.citations[0]
    assert citation.number == 1
    assert citation.file_path == LOGIN_PATH
    assert citation.symbol_name == expected.symbol_name == "login"
    assert (
        (citation.start_line, citation.end_line)
        == (
            expected.start_line,
            expected.end_line,
        )
        == (1, 2)
    )
    assert rag.store.count == 1
    _assert_rf19(response)


def test_the_client_receives_the_fixed_system_prompt_and_the_final_messages(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """El mensaje de sistema va aparte y el historial más la pregunta en `messages`."""
    _index_login(monkeypatch)
    set_api_key(SECRET_KEY)
    client = _use_client(monkeypatch)
    history = [
        ChatMessage(role="user", content="hola"),
        ChatMessage(role="assistant", content="¿en qué te ayudo?"),
    ]

    response = bot.answer(LOGIN_QUESTION, history)

    call = client.last_call
    assert call["system"] == bot.SYSTEM_PROMPT
    assert call["model"] == bot.MODEL_NAME
    assert call["max_tokens"] == bot.MAX_TOKENS
    messages = call["messages"]
    assert messages[0] == {"role": "user", "content": "hola"}
    assert messages[1] == {"role": "assistant", "content": "¿en qué te ayudo?"}
    assert messages[2]["role"] == "user"
    final = messages[2]["content"]
    assert LOGIN_QUESTION in final
    assert "INICIO FRAGMENTO F1" in final
    assert "FIN FRAGMENTO F1" in final
    expected = _expected_chunk()
    assert f"Archivo: {expected.file_path}" in final
    assert f"Símbolo: {expected.symbol_name}" in final
    assert f"Líneas: {expected.start_line}-{expected.end_line}" in final
    assert expected.content.strip() in final
    _assert_rf19(response)
