"""Pruebas de la ruta `POST /chat`.

Cubren el éxito, los resultados sin respuesta, cada motivo de fallo con su
estado, la validación del cuerpo, los límites de longitud y de tamaño y que la
ruta entrega a la capacidad de la spec 003 exactamente lo recibido (RF-10 a
RF-14). Salvo las dos pruebas de longitud, que usan `bot.answer` real con un
índice vacío, todas sustituyen `bot.answer` por un doble con
`app.dependency_overrides`: no hay red, claves ni modelo de embeddings.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from app import main, rag
from app.models import (
    ApiReason,
    ChatMessage,
    ChatReason,
    ChatResponse,
    Citation,
)
from app.storage import VectorStore

#: Claves exactas de un éxito del chat (contrato de `ChatResponse`).
CHAT_KEYS = {"reply", "citations", "reason"}

#: Claves exactas del cuerpo de error (RF-14).
ERROR_KEYS = {"message", "reason"}

#: Pregunta de prueba enviada por el historial de los casos.
QUESTION = "¿Dónde se calculan los embeddings?"

#: Resultados sin respuesta: llegan con 200 y `reason`, nunca como error.
OK_REASONS = [
    ChatReason.EMPTY_INDEX,
    ChatReason.NO_RELEVANT,
    ChatReason.INSUFFICIENT_CONTEXT,
    ChatReason.UNGROUNDED_ANSWER,
]

#: Cada motivo de fallo con su estado HTTP (RF-11).
FAILURE_STATUSES = [
    (ChatReason.EMPTY_QUERY, 422),
    (ChatReason.QUERY_TOO_LONG, 422),
    (ChatReason.MISSING_API_KEY, 503),
    (ChatReason.INVALID_API_KEY, 503),
    (ChatReason.API_UNAVAILABLE, 503),
    (ChatReason.API_TIMEOUT, 504),
    (ChatReason.API_ERROR, 502),
]

#: Cuerpos que deben rechazarse antes de llegar a la capacidad (RF-13).
INVALID_BODIES: list[tuple[str, bytes]] = [
    ("json-mal-formado", b"{no es json"),
    ("arreglo-en-lugar-de-objeto", b'["hola"]'),
    ("sin-message", b"{}"),
    ("message-numerico", b'{"message": 123}'),
    ("history-null", b'{"message": "hola", "history": null}'),
    (
        "rol-system",
        b'{"message": "hola", "history": [{"role": "system", "content": "x"}]}',
    ),
    (
        "content-numerico",
        b'{"message": "hola", "history": [{"role": "user", "content": 1}]}',
    ),
]


def make_citation() -> Citation:
    """Crea la cita que devuelve el doble en un éxito."""
    return Citation(
        number=1,
        file_path="app/rag.py",
        symbol_name="_embed_query",
        start_line=232,
        end_line=236,
    )


def make_success() -> ChatResponse:
    """Crea una respuesta fundamentada con una cita distinguible."""
    return ChatResponse(
        reply="Se calculan en `rag._embed_query`. [F1]",
        citations=[make_citation()],
    )


def make_failure(reason: ChatReason) -> ChatResponse:
    """Crea la respuesta del bot para un motivo de fallo.

    El `reply` es propio de la prueba para comprobar que la capa HTTP lo
    devuelve tal cual como `message`, sin reescribirlo.
    """
    return ChatResponse(
        reply=f"mensaje del bot para {reason.value}",
        citations=[],
        reason=reason,
    )


def chat_body_of_size(size: int) -> bytes:
    """Construye un cuerpo JSON válido con el tamaño exacto pedido, en bytes."""
    prefix = b'{"message": "'
    suffix = b'"}'
    body = prefix + b"a" * (size - len(prefix) - len(suffix)) + suffix
    assert len(body) == size
    return body


class FakeAnswer:
    """Doble de `bot.answer` que registra las llamadas y devuelve un resultado.

    Guarda `(mensaje, historial)` tal cual los recibe, sin recortar ni
    normalizar, para comprobar qué entrega la capa HTTP a la capacidad.
    """

    def __init__(self, result: ChatResponse | None = None) -> None:
        self.result = result if result is not None else make_success()
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    def __call__(self, message: str, history: list[ChatMessage]) -> ChatResponse:
        """Anota la llamada y devuelve el resultado configurado."""
        self.calls.append((message, history))
        return self.result


@pytest.fixture(autouse=True)
def clean_overrides() -> Iterator[None]:
    """Vacía las dependencias sustituidas antes y después de cada prueba."""
    main.app.dependency_overrides.clear()
    yield
    main.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clean_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sustituye el singleton en memoria por uno vacío en cada prueba.

    Las pruebas de longitud usan `bot.answer` real: con el índice vacío la
    búsqueda termina en `empty_index` sin cargar el modelo de embeddings.
    """
    monkeypatch.setattr(rag, "store", VectorStore())


@pytest.fixture
def client() -> TestClient:
    """Cliente que devuelve las respuestas de error en lugar de relanzarlas."""
    return TestClient(main.app, raise_server_exceptions=False)


def use_answer(fake: FakeAnswer) -> None:
    """Sustituye la capacidad de respuesta por el doble indicado."""
    main.app.dependency_overrides[main.get_answer] = lambda: fake


def assert_error(response: Response, status: int, reason: str, message: str) -> None:
    """Comprueba el estado y el formato único de error, sin clave `detail`."""
    assert response.status_code == status

    body = response.json()

    assert set(body) == ERROR_KEYS
    assert body == {"message": message, "reason": reason}


# --- Éxito y resultados sin respuesta (RF-10) -------------------------------


def test_chat_success_returns_reply_citations_and_reason_null(
    client: TestClient,
) -> None:
    """Un éxito devuelve 200 con `reply`, `citations` y `reason: null`."""
    fake = FakeAnswer()
    use_answer(fake)

    response = client.post("/chat", json={"message": QUESTION})

    assert response.status_code == 200

    body = response.json()

    assert set(body) == CHAT_KEYS
    assert "reason" in body
    assert body["reason"] is None
    assert body["reply"] == make_success().reply
    assert body["citations"] == [make_citation().model_dump()]
    assert len(fake.calls) == 1


@pytest.mark.parametrize("reason", OK_REASONS)
def test_chat_ok_reason_returns_200_with_reason_and_empty_citations(
    client: TestClient, reason: ChatReason
) -> None:
    """Un resultado sin respuesta es 200 con su motivo y sin citas."""
    result = ChatResponse(
        reply=f"sin respuesta: {reason.value}", citations=[], reason=reason
    )
    fake = FakeAnswer(result)
    use_answer(fake)

    response = client.post("/chat", json={"message": QUESTION})

    assert response.status_code == 200

    body = response.json()

    assert set(body) == CHAT_KEYS
    assert body["reason"] == reason.value
    assert body["reply"] == result.reply
    assert body["citations"] == []


# --- Fallos del chat (RF-11) ------------------------------------------------


@pytest.mark.parametrize(("reason", "status"), FAILURE_STATUSES)
def test_chat_failure_reason_returns_error_with_its_status(
    client: TestClient, reason: ChatReason, status: int
) -> None:
    """Cada motivo de fallo usa su estado y su `reply` como `message`."""
    result = make_failure(reason)
    fake = FakeAnswer(result)
    use_answer(fake)

    response = client.post("/chat", json={"message": QUESTION})

    assert_error(response, status, reason.value, result.reply)
    assert "detail" not in response.json()
    assert len(fake.calls) == 1


# --- Cuerpo entregado a la capacidad (RF-12) --------------------------------


def test_chat_without_history_passes_empty_list(client: TestClient) -> None:
    """Sin `history`, la capacidad recibe una lista vacía."""
    fake = FakeAnswer()
    use_answer(fake)

    response = client.post("/chat", json={"message": QUESTION})

    assert response.status_code == 200
    assert fake.calls == [(QUESTION, [])]


def test_chat_passes_message_and_history_unchanged(client: TestClient) -> None:
    """La capacidad recibe el mensaje y el historial exactos, sin transformar."""
    history = [
        {"role": "user", "content": "  ¿Qué es CodeMentor?  "},
        {"role": "assistant", "content": "Un asistente RAG.\n"},
    ]
    fake = FakeAnswer()
    use_answer(fake)

    response = client.post("/chat", json={"message": QUESTION, "history": history})

    assert response.status_code == 200
    assert fake.calls == [
        (
            QUESTION,
            [
                ChatMessage(role="user", content="  ¿Qué es CodeMentor?  "),
                ChatMessage(role="assistant", content="Un asistente RAG.\n"),
            ],
        )
    ]


# --- Validación del cuerpo (RF-13) ------------------------------------------


@pytest.mark.parametrize(
    "body", [pytest.param(body, id=name) for name, body in INVALID_BODIES]
)
def test_chat_invalid_request_returns_422_without_calling_answer(
    client: TestClient, body: bytes
) -> None:
    """Un cuerpo inválido da 422 `invalid_request` sin llamar a la capacidad."""
    fake = FakeAnswer()
    use_answer(fake)

    response = client.post(
        "/chat",
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert_error(
        response,
        422,
        ApiReason.INVALID_REQUEST.value,
        main.MSG_INVALID_REQUEST,
    )
    assert fake.calls == []


# --- Límites de longitud y de tamaño (RF-13 y RF-17) ------------------------


def test_chat_message_of_1000_chars_passes(client: TestClient) -> None:
    """Un mensaje de 1.000 caracteres supera la validación de la búsqueda."""
    response = client.post("/chat", json={"message": "a" * 1000})

    assert response.status_code == 200
    assert response.json()["reason"] == ChatReason.EMPTY_INDEX.value


def test_chat_message_of_1001_chars_is_query_too_long(client: TestClient) -> None:
    """Un mensaje de 1.001 caracteres da 422 `query_too_long`."""
    response = client.post("/chat", json={"message": "a" * 1001})

    assert_error(
        response,
        422,
        ChatReason.QUERY_TOO_LONG.value,
        rag.QUERY_TOO_LONG_MESSAGE,
    )


def test_chat_blank_message_is_empty_query(client: TestClient) -> None:
    """Un mensaje de solo espacios da 422 `empty_query`, no un error de validación.

    Lo decide la búsqueda de la spec 003, no la validación del cuerpo: la ruta
    entrega el texto tal cual y traduce el motivo a su estado.
    """
    response = client.post("/chat", json={"message": "   "})

    assert_error(
        response,
        422,
        ChatReason.EMPTY_QUERY.value,
        rag.EMPTY_QUERY_MESSAGE,
    )


def test_chat_body_at_limit_passes(client: TestClient) -> None:
    """Un cuerpo de 262.144 bytes pasa el middleware y llega a la ruta."""
    fake = FakeAnswer()
    use_answer(fake)

    response = client.post(
        "/chat",
        content=chat_body_of_size(main.CHAT_BODY_LIMIT),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert len(fake.calls) == 1


def test_chat_body_over_limit_is_413(client: TestClient) -> None:
    """Un cuerpo de 262.145 bytes da 413 sin llamar a la capacidad."""
    fake = FakeAnswer()
    use_answer(fake)

    response = client.post(
        "/chat",
        content=chat_body_of_size(main.CHAT_BODY_LIMIT + 1),
        headers={"Content-Type": "application/json"},
    )

    assert_error(
        response,
        413,
        ApiReason.PAYLOAD_TOO_LARGE.value,
        main.MSG_CHAT_TOO_LARGE,
    )
    assert fake.calls == []
