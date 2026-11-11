"""Pruebas del contrato de datos compartido.

Comprueban que los modelos transportan lo que las specs 001, 002 y 003
necesitan para citar fragmentos, informar de una indexación y devolver una
respuesta con sus citas. No prueban búsqueda, storage, troceado, generación
de embeddings ni la lógica del bot.
"""

import pytest
from pydantic import ValidationError

from app.models import (
    ApiReason,
    ChatMessage,
    ChatReason,
    ChatRequest,
    ChatResponse,
    Chunk,
    Citation,
    ErrorResponse,
    IndexReason,
    IndexResult,
    SearchReason,
    SearchResponse,
    SearchResult,
    UploadResponse,
)


def make_chunk(kind: str = "function") -> Chunk:
    """Crea un chunk de ejemplo con todos los datos de cita."""
    return Chunk(
        file_path="app/rag.py",
        symbol_name="search",
        start_line=10,
        end_line=25,
        content="def search(query: str) -> SearchResponse: ...",
        kind=kind,
    )


def test_chunk_keeps_citation_fields() -> None:
    """Un chunk conserva ruta, símbolo y rango de líneas."""
    chunk = make_chunk()

    assert chunk.file_path == "app/rag.py"
    assert chunk.symbol_name == "search"
    assert chunk.start_line == 10
    assert chunk.end_line == 25
    assert chunk.content.startswith("def search")
    assert chunk.kind == "function"


def test_chunk_accepts_the_four_kinds() -> None:
    """Los cuatro orígenes previstos se aceptan sin cambios."""
    for kind in ("function", "class", "module", "window"):
        assert make_chunk(kind).kind == kind


def test_chunk_rejects_an_unknown_kind() -> None:
    """Un origen inventado se rechaza al construir el chunk."""
    with pytest.raises(ValidationError):
        make_chunk("paragraph")


def test_search_result_pairs_chunk_and_score() -> None:
    """Un resultado incluye el chunk y su puntuación."""
    result = SearchResult(chunk=make_chunk(), score=0.42)

    assert result.chunk.symbol_name == "search"
    assert result.score == 0.42


def test_search_reasons_have_stable_text_values() -> None:
    """Los cuatro motivos tienen valores de texto estables."""
    assert {reason.value for reason in SearchReason} == {
        "empty_index",
        "no_relevant",
        "empty_query",
        "query_too_long",
    }
    assert SearchReason.EMPTY_INDEX == "empty_index"


def test_search_response_with_results_has_no_reason() -> None:
    """Una búsqueda con resultados no necesita motivo ni mensaje."""
    response = SearchResponse(results=[SearchResult(chunk=make_chunk(), score=0.42)])

    assert len(response.results) == 1
    assert response.reason is None
    assert response.message is None


def test_search_response_explains_empty_result() -> None:
    """Una búsqueda sin resultados puede llevar motivo y mensaje en español."""
    response = SearchResponse(
        results=[],
        reason=SearchReason.NO_RELEVANT,
        message="No encontré fragmentos relevantes para esa consulta.",
    )

    assert response.results == []
    assert response.reason is SearchReason.NO_RELEVANT
    assert response.message == "No encontré fragmentos relevantes para esa consulta."


def make_index_result(reason: IndexReason | None = None) -> IndexResult:
    """Crea un resultado de indexación con todos los datos del contrato.

    Con `reason=None` representa un éxito; con un motivo, un rechazo, que
    siempre deja `chunks_indexed` en 0.
    """
    return IndexResult(
        file_path="app/rag.py",
        chunks_indexed=0 if reason is not None else 4,
        total_chunks=12,
        used_windows=False,
        reason=reason,
        message=(
            "Archivo indexado: 4 fragmentos; el índice tiene 12."
            if reason is None
            else "El archivo no se indexó."
        ),
    )


def test_index_reasons_have_stable_text_values() -> None:
    """Los cuatro motivos de rechazo tienen valores de texto estables."""
    assert {reason.value for reason in IndexReason} == {
        "empty_content",
        "too_large",
        "too_many_chunks",
        "embedding_failed",
    }
    assert IndexReason.EMPTY_CONTENT == "empty_content"


def test_index_result_success_has_no_reason() -> None:
    """Un éxito trae fragmentos, total del índice, aviso de ventanas y mensaje."""
    result = make_index_result()

    assert result.file_path == "app/rag.py"
    assert result.chunks_indexed == 4
    assert result.total_chunks == 12
    assert result.used_windows is False
    assert result.reason is None
    assert result.message == "Archivo indexado: 4 fragmentos; el índice tiene 12."


def test_index_result_reason_defaults_to_none() -> None:
    """Un éxito puede omitir el motivo: su ausencia es lo que lo define."""
    result = IndexResult(
        file_path="app/rag.py",
        chunks_indexed=4,
        total_chunks=12,
        used_windows=False,
        message="Archivo indexado.",
    )

    assert result.reason is None


def test_index_result_success_can_warn_about_windows() -> None:
    """Un éxito troceado por ventanas marca `used_windows` y sigue sin motivo."""
    result = IndexResult(
        file_path="prose.txt",
        chunks_indexed=2,
        total_chunks=14,
        used_windows=True,
        message="Archivo indexado de forma aproximada por ventanas.",
    )

    assert result.used_windows is True
    assert result.reason is None


@pytest.mark.parametrize("reason", list(IndexReason))
def test_index_result_rejection_keeps_reason_and_message(reason: IndexReason) -> None:
    """Cada motivo de rechazo se conserva junto a un mensaje y sin fragmentos."""
    result = make_index_result(reason)

    assert result.reason is reason
    assert result.chunks_indexed == 0
    assert result.total_chunks == 12
    assert result.message == "El archivo no se indexó."


def test_index_result_requires_message() -> None:
    """El mensaje es obligatorio tanto en el éxito como en el rechazo."""
    with pytest.raises(ValidationError):
        IndexResult(
            file_path="app/rag.py",
            chunks_indexed=4,
            total_chunks=12,
            used_windows=False,
        )


def test_index_result_rejects_an_unknown_reason() -> None:
    """Un motivo inventado se rechaza al construir el resultado."""
    with pytest.raises(ValidationError):
        IndexResult(
            file_path="app/rag.py",
            chunks_indexed=0,
            total_chunks=12,
            used_windows=False,
            reason="too_big",
            message="El archivo no se indexó.",
        )


def make_chat_message(
    role: str = "user",
    content: str = "¿Dónde se buscan los fragmentos?",
) -> ChatMessage:
    """Crea un mensaje de conversación de ejemplo."""
    return ChatMessage(role=role, content=content)


def make_citation(number: int = 1) -> Citation:
    """Crea una cita de ejemplo con los datos de un fragmento real."""
    return Citation(
        number=number,
        file_path="app/rag.py",
        symbol_name="search",
        start_line=10,
        end_line=25,
    )


def test_chat_message_keeps_role_and_content() -> None:
    """Un mensaje conserva su rol y su texto."""
    message = make_chat_message("assistant", "Los fragmentos se buscan en rag.py.")

    assert message.role == "assistant"
    assert message.content == "Los fragmentos se buscan en rag.py."


def test_chat_message_accepts_both_roles() -> None:
    """Los dos roles de la conversación se aceptan tal cual."""
    for role in ("user", "assistant"):
        assert make_chat_message(role).role == role


def test_chat_message_rejects_an_unknown_role() -> None:
    """Un rol inventado se rechaza al construir el mensaje."""
    with pytest.raises(ValidationError):
        make_chat_message("system")


def test_chat_request_history_defaults_to_an_empty_list() -> None:
    """Una petición sin historial empieza con la lista vacía."""
    request = ChatRequest(message="¿Dónde se calculan los embeddings?")

    assert request.message == "¿Dónde se calculan los embeddings?"
    assert request.history == []


def test_chat_request_history_is_independent_between_instances() -> None:
    """Añadir historial a una petición no afecta a otra."""
    first = ChatRequest(message="Primera pregunta")
    second = ChatRequest(message="Segunda pregunta")

    first.history.append(make_chat_message())

    assert len(first.history) == 1
    assert second.history == []


def test_chat_request_keeps_the_given_history() -> None:
    """El historial recibido se conserva con su orden y sus roles."""
    request = ChatRequest(
        message="¿Y las citas?",
        history=[
            make_chat_message("user", "¿Dónde se buscan los fragmentos?"),
            make_chat_message("assistant", "En rag.py."),
        ],
    )

    assert [message.role for message in request.history] == ["user", "assistant"]


def test_citation_keeps_the_five_fields() -> None:
    """Una cita lleva número, ruta, símbolo y rango de líneas."""
    citation = make_citation(2)

    assert citation.number == 2
    assert citation.file_path == "app/rag.py"
    assert citation.symbol_name == "search"
    assert citation.start_line == 10
    assert citation.end_line == 25


def test_citation_has_only_the_five_contract_fields() -> None:
    """La cita no lleva texto ni puntuación: solo lo necesario para abrirla."""
    assert set(make_citation().model_dump()) == {
        "number",
        "file_path",
        "symbol_name",
        "start_line",
        "end_line",
    }


def test_chat_reasons_have_stable_text_values() -> None:
    """Los once motivos tienen valores de texto estables, en el orden del contrato."""
    assert [reason.value for reason in ChatReason] == [
        "empty_query",
        "query_too_long",
        "empty_index",
        "no_relevant",
        "missing_api_key",
        "invalid_api_key",
        "api_timeout",
        "api_unavailable",
        "api_error",
        "insufficient_context",
        "ungrounded_answer",
    ]


def test_chat_reasons_start_with_the_search_reasons() -> None:
    """Los cuatro primeros motivos son los de la búsqueda, para convertir sin tabla."""
    first_four = list(ChatReason)[:4]

    assert {reason.value for reason in first_four} == {
        reason.value for reason in SearchReason
    }
    for reason in SearchReason:
        assert ChatReason(reason.value).value == reason.value


def test_chat_reason_rejects_an_unknown_value() -> None:
    """Un motivo inventado no se puede convertir ni usar en una respuesta."""
    with pytest.raises(ValueError):
        ChatReason("invented_reason")

    with pytest.raises(ValidationError):
        ChatResponse(
            reply="No lo encontré en el código indexado.", reason="invented_reason"
        )


def test_chat_response_defaults_have_no_citations_and_no_reason() -> None:
    """Un resultado por defecto no trae citas ni motivo."""
    response = ChatResponse(reply="No lo encontré en el código indexado.")

    assert response.citations == []
    assert response.reason is None


def test_chat_response_citations_are_independent_between_instances() -> None:
    """Añadir citas a una respuesta no afecta a otra."""
    first = ChatResponse(reply="Primera respuesta")
    second = ChatResponse(reply="Segunda respuesta")

    first.citations.append(make_citation())

    assert len(first.citations) == 1
    assert second.citations == []


def test_chat_response_success_has_a_citation_and_no_reason() -> None:
    """Una respuesta fundamentada lleva texto, al menos una cita y ningún motivo."""
    response = ChatResponse(
        reply="Los fragmentos se buscan en rag.py. [F1]",
        citations=[make_citation()],
    )

    assert response.reply.endswith("[F1]")
    assert [citation.number for citation in response.citations] == [1]
    assert response.reason is None


@pytest.mark.parametrize("reason", list(ChatReason))
def test_chat_response_failure_keeps_reason_and_no_citations(
    reason: ChatReason,
) -> None:
    """Cada motivo viaja con un mensaje y sin citas, sin lógica en el modelo."""
    response = ChatResponse(reply="No pude responder.", reason=reason)

    assert response.reason is reason
    assert response.citations == []


def test_chat_response_success_and_failure_are_told_apart_by_reason() -> None:
    """RF-19: el éxito no tiene motivo; el fallo lo lleva y no trae citas.

    El modelo solo transporta los tres datos: no deduce ni impone la
    invariante, que decide el bot al construir la respuesta.
    """
    success = ChatResponse(reply="Respuesta. [F1]", citations=[make_citation()])
    failure = ChatResponse(reply="No pude responder.", reason=ChatReason.API_ERROR)

    assert success.reason is None
    assert len(success.citations) >= 1
    assert failure.reason is not None
    assert failure.citations == []


def make_upload_response() -> UploadResponse:
    """Crea la confirmación de una subida con sus cinco campos."""
    return UploadResponse(
        file_path="app/rag.py",
        chunks_indexed=4,
        total_chunks=12,
        used_windows=False,
        message="Archivo indexado: 4 fragmentos; el índice tiene 12.",
    )


def test_upload_response_keeps_the_five_fields() -> None:
    """La confirmación conserva ruta, fragmentos, total, ventanas y mensaje."""
    response = make_upload_response()

    assert response.file_path == "app/rag.py"
    assert response.chunks_indexed == 4
    assert response.total_chunks == 12
    assert response.used_windows is False
    assert response.message == "Archivo indexado: 4 fragmentos; el índice tiene 12."


def test_upload_response_has_only_the_five_contract_fields() -> None:
    """La confirmación no lleva motivo: los rechazos usan `ErrorResponse`."""
    assert set(make_upload_response().model_dump()) == {
        "file_path",
        "chunks_indexed",
        "total_chunks",
        "used_windows",
        "message",
    }


def test_upload_response_requires_the_five_fields() -> None:
    """Si falta un campo obligatorio, la confirmación no se construye."""
    with pytest.raises(ValidationError):
        UploadResponse(
            file_path="app/rag.py",
            chunks_indexed=4,
            total_chunks=12,
            used_windows=False,
        )


def test_error_response_keeps_message_and_reason() -> None:
    """El error conserva el mensaje en español y el motivo que lo identifica."""
    error = ErrorResponse(message="No existe esa ruta.", reason=ApiReason.NOT_FOUND)

    assert error.message == "No existe esa ruta."
    assert error.reason == "not_found"


def test_error_response_has_only_the_two_contract_fields() -> None:
    """El formato de error no añade campos: solo `message` y `reason`."""
    error = ErrorResponse(message="No existe esa ruta.", reason=ApiReason.NOT_FOUND)

    assert set(error.model_dump()) == {"message", "reason"}


@pytest.mark.parametrize(
    "reason",
    [*ApiReason, *IndexReason, *ChatReason],
    ids=lambda reason: reason.value,
)
def test_error_response_accepts_reasons_from_the_three_capabilities(
    reason: ApiReason | IndexReason | ChatReason,
) -> None:
    """`reason` reúne motivos de la capa HTTP, del indexado y del chat."""
    error = ErrorResponse(message="No se pudo completar la operación.", reason=reason)

    assert error.reason == reason.value


def test_api_reasons_have_stable_text_values() -> None:
    """Los nueve motivos tienen valores estables, en el orden del contrato."""
    assert [reason.value for reason in ApiReason] == [
        "invalid_request",
        "invalid_path",
        "invalid_extension",
        "invalid_encoding",
        "payload_too_large",
        "length_required",
        "not_found",
        "method_not_allowed",
        "internal_error",
    ]


def test_api_reason_rejects_an_unknown_value() -> None:
    """Un motivo inventado no se puede convertir."""
    with pytest.raises(ValueError):
        ApiReason("invented_reason")


def test_previous_specs_models_keep_their_fields_and_defaults() -> None:
    """La spec 004 no altera los modelos de las specs 001 a 003."""
    assert set(ChatRequest.model_fields) == {"message", "history"}
    assert ChatRequest.model_fields["message"].is_required()
    assert ChatRequest.model_fields["history"].default == []

    assert set(ChatResponse.model_fields) == {"reply", "citations", "reason"}
    assert ChatResponse.model_fields["reply"].is_required()
    assert ChatResponse.model_fields["citations"].default == []
    assert ChatResponse.model_fields["reason"].default is None

    assert set(IndexResult.model_fields) == {
        "file_path",
        "chunks_indexed",
        "total_chunks",
        "used_windows",
        "reason",
        "message",
    }
    assert IndexResult.model_fields["file_path"].is_required()
    assert IndexResult.model_fields["reason"].default is None
    assert IndexResult.model_fields["message"].is_required()
