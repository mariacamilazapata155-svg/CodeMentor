"""Pruebas de la interpretación de la respuesta del modelo.

Cubren RF-6, RF-7, RF-8, RF-9 y RF-10: el centinela `NO_ENCONTRADO`, las
marcas válidas e inválidas, el orden y la deduplicación de las citas, la
construcción de citas con los datos de los fragmentos entregados y el descarte
de respuestas sin fundamento. No llaman al modelo ni usan red.
"""

from types import SimpleNamespace

import pytest
from conftest import make_message_response, make_text_block

from app import bot
from app.models import ChatReason, Chunk, Citation, SearchResult

#: Mensajes exactos de los dos motivos que se interpretan en esta tarea.
INSUFFICIENT_CONTEXT_MESSAGE = (
    "No encontré la respuesta en el código indexado. Prueba a reformular la "
    "pregunta o a indexar más archivos."
)
UNGROUNDED_ANSWER_MESSAGE = (
    "No pude respaldar la respuesta con fragmentos concretos del código, así "
    "que prefiero no mostrarla. Prueba a reformular la pregunta."
)


def make_delivered(count: int = 5) -> list[SearchResult]:
    """Crea fragmentos entregados con rutas, símbolos y líneas distintos."""
    return [
        SearchResult(
            chunk=Chunk(
                file_path=f"app/archivo_{number}.py",
                symbol_name=f"simbolo_{number}",
                start_line=number * 10 + 1,
                end_line=number * 10 + 5,
                content=f"def simbolo_{number}():\n    return {number}",
                kind="function",
            ),
            score=0.9 - number / 100,
        )
        for number in range(1, count + 1)
    ]


def expected_citation(number: int, delivered: list[SearchResult]) -> Citation:
    """Cita esperada a partir del fragmento entregado en esa posición."""
    chunk = delivered[number - 1].chunk
    return Citation(
        number=number,
        file_path=chunk.file_path,
        symbol_name=chunk.symbol_name,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
    )


def assert_rf19(response: bot.ChatResponse) -> None:
    """Comprueba el invariante de RF-19 para un resultado del bot."""
    has_citations = bool(response.citations)
    assert (response.reason is None) is has_citations
    if response.reason is not None:
        assert response.citations == []


# --- `_extract_text`: bloques de la respuesta --------------------------------


def test_extract_text_returns_the_text_of_one_block() -> None:
    """Una respuesta con un bloque de texto devuelve exactamente ese texto."""
    response = make_message_response("La función está en rag.py.")

    assert bot._extract_text(response) == "La función está en rag.py."


def test_extract_text_joins_several_text_blocks_without_separator() -> None:
    """Varios bloques de texto se unen sin añadir espacios ni saltos."""
    response = make_message_response("uno", "dos", "tres")

    assert bot._extract_text(response) == "unodostres"


def test_extract_text_ignores_blocks_that_are_not_text() -> None:
    """Un bloque de herramienta no se cuela en el texto de la respuesta."""
    response = SimpleNamespace(
        content=[
            make_text_block("antes "),
            SimpleNamespace(type="tool_use", id="toolu_1", name="buscar", input={}),
            make_text_block("después"),
        ]
    )

    assert bot._extract_text(response) == "antes después"


def test_extract_text_with_no_blocks_returns_empty_string() -> None:
    """Una respuesta sin bloques produce una cadena vacía."""
    assert bot._extract_text(make_message_response()) == ""


# --- RF-6: centinela `NO_ENCONTRADO` -----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "NO_ENCONTRADO",
        "  NO_ENCONTRADO\n",
        "\n\tNO_ENCONTRADO \n",
    ],
)
def test_sentinel_produces_insufficient_context(text: str) -> None:
    """El centinela, con o sin espacios alrededor, no es una respuesta."""
    response = bot._interpret(text, make_delivered())

    assert response.reply == INSUFFICIENT_CONTEXT_MESSAGE
    assert response.reason == ChatReason.INSUFFICIENT_CONTEXT
    assert response.citations == []
    assert_rf19(response)


def test_sentinel_inside_a_longer_text_is_not_the_sentinel() -> None:
    """`NO_ENCONTRADO` dentro de un texto con una marca se interpreta normal."""
    text = "El texto dice NO_ENCONTRADO, pero la función está aquí. [F1]"

    response = bot._interpret(text, make_delivered())

    assert response.reply == text
    assert response.reason is None
    assert [citation.number for citation in response.citations] == [1]
    assert_rf19(response)


def test_sentinel_inside_a_longer_text_without_markers_is_ungrounded() -> None:
    """Un texto largo con el centinela pero sin marcas no es el centinela."""
    text = "El texto dice NO_ENCONTRADO, pero no aporta ninguna marca."

    response = bot._interpret(text, make_delivered())

    assert response.reply == UNGROUNDED_ANSWER_MESSAGE
    assert response.reason == ChatReason.UNGROUNDED_ANSWER
    assert response.citations == []
    assert text not in response.reply
    assert_rf19(response)


# --- RF-7, RF-8 y RF-10: marcas y citas -------------------------------------


def test_two_valid_markers_produce_two_citations_in_text_order() -> None:
    """`[F2]` y `[F4]` con cinco fragmentos dan las citas 2 y 4."""
    text = "La función dos está en [F2] y la cuatro en [F4]."

    response = bot._interpret(text, make_delivered())

    assert response.reply == text
    assert response.reason is None
    assert [citation.number for citation in response.citations] == [2, 4]
    assert response.citations == [
        expected_citation(2, make_delivered()),
        expected_citation(4, make_delivered()),
    ]
    assert_rf19(response)


def test_repeated_valid_marker_produces_only_one_citation() -> None:
    """`[F1]` repetido no duplica la cita."""
    text = "Primero [F1], otra vez [F1] y al final [F1]."

    response = bot._interpret(text, make_delivered())

    assert [citation.number for citation in response.citations] == [1]
    assert len(response.citations) == 1
    assert_rf19(response)


def test_citations_follow_the_first_appearance_order() -> None:
    """`[F3]` antes que `[F1]` produce las citas en orden 3, 1."""
    text = "La tercera [F3] aparece antes que la primera [F1]."

    response = bot._interpret(text, make_delivered())

    assert [citation.number for citation in response.citations] == [3, 1]
    assert_rf19(response)


def test_extract_markers_removes_invalid_markers_and_deduplicates() -> None:
    """Solo las marcas válidas quedan en el texto y los números no se repiten."""
    numbers, cleaned = bot._extract_markers(
        "[F2] [F9] [F4] [F2] [F0] [F01] [f2] [F1234]",
        make_delivered(5),
    )

    assert numbers == [2, 4]
    assert cleaned == "[F2]  [F4] [F2] [F0] [F01] [f2] [F1234]"


def test_out_of_range_marker_is_removed_and_does_not_cite() -> None:
    """`[F9]` con tres fragmentos se elimina y no genera cita."""
    text = "Válido [F1] e inválido [F9]."

    response = bot._interpret(text, make_delivered(3))

    assert response.reply == "Válido [F1] e inválido ."
    assert [citation.number for citation in response.citations] == [1]
    assert_rf19(response)


def test_only_an_out_of_range_marker_is_ungrounded() -> None:
    """Si `[F9]` era la única marca, se aplica RF-9 y no se muestra el texto."""
    text = "Solo [F9] y nada más."

    response = bot._interpret(text, make_delivered(3))

    assert response.reply == UNGROUNDED_ANSWER_MESSAGE
    assert response.reason == ChatReason.UNGROUNDED_ANSWER
    assert response.citations == []
    assert text not in response.reply
    assert_rf19(response)


def test_a_marker_inside_code_written_by_the_model_counts_as_a_marker() -> None:
    """`items[F2]` cuenta como marca: limitación conocida del formato."""
    text = "El código usa items[F2] para acceder al segundo elemento."
    delivered = make_delivered()

    response = bot._interpret(text, delivered)

    assert response.reply == text
    assert [citation.number for citation in response.citations] == [2]
    assert response.citations == [expected_citation(2, delivered)]
    assert_rf19(response)


def test_non_marker_texts_are_kept_and_do_not_cite() -> None:
    """`[F0]`, `[F01]`, `[f2]` y `[F1234]` se conservan y no generan citas."""
    text = "Válido [F1]; no son marcas [F0], [F01], [f2] ni [F1234]."

    response = bot._interpret(text, make_delivered())

    assert response.reply == text
    assert [citation.number for citation in response.citations] == [1]
    assert_rf19(response)


# --- RF-9: respuestas sin marcas válidas ------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Una respuesta sin ninguna marca.",
        "",
        "   \n\t",
        "Solo marcas inválidas [F0], [F01], [f2] y [F1234].",
    ],
)
def test_answer_without_valid_markers_is_ungrounded(text: str) -> None:
    """Sin marcas válidas se descarta el texto y se devuelve `ungrounded_answer`."""
    response = bot._interpret(text, make_delivered())

    assert response.reply == UNGROUNDED_ANSWER_MESSAGE
    assert response.reason == ChatReason.UNGROUNDED_ANSWER
    assert response.citations == []
    if text:
        assert text not in response.reply
    assert_rf19(response)


# --- RF-8: los datos de la cita salen del fragmento -------------------------


def test_invented_paths_in_the_model_text_do_not_reach_the_citations() -> None:
    """Aunque el modelo invente ruta, símbolo y líneas, la cita usa el fragmento."""
    text = "Según app/inventado.py, la función fake, líneas 99-120, esto es así. [F1]"
    delivered = make_delivered()

    response = bot._interpret(text, delivered)

    assert response.reply == text
    assert response.citations == [expected_citation(1, delivered)]
    assert response.citations[0].file_path == "app/archivo_1.py"
    assert response.citations[0].symbol_name == "simbolo_1"
    assert (response.citations[0].start_line, response.citations[0].end_line) == (
        11,
        15,
    )
    assert_rf19(response)


def test_build_citations_uses_all_five_fields_of_the_delivered_fragment() -> None:
    """Cada cita lleva el número, la ruta, el símbolo y el rango del fragmento."""
    delivered = make_delivered()

    citations = bot._build_citations([2, 4], delivered)

    assert citations == [
        Citation(
            number=2,
            file_path="app/archivo_2.py",
            symbol_name="simbolo_2",
            start_line=21,
            end_line=25,
        ),
        Citation(
            number=4,
            file_path="app/archivo_4.py",
            symbol_name="simbolo_4",
            start_line=41,
            end_line=45,
        ),
    ]


def test_a_huge_number_inside_a_marker_does_not_raise_value_error() -> None:
    """Una marca con 5.000 dígitos no se convierte ni lanza `ValueError`."""
    huge_marker = "[F" + "9" * 5_000 + "]"
    text = f"{huge_marker} y una marca válida [F2]."
    delivered = make_delivered()

    numbers, cleaned = bot._extract_markers(text, delivered)
    response = bot._interpret(text, delivered)

    assert numbers == [2]
    assert cleaned == text
    assert huge_marker in response.reply
    assert [citation.number for citation in response.citations] == [2]
    assert_rf19(response)


def test_a_response_cut_off_by_the_length_limit_with_a_marker_is_returned() -> None:
    """Una respuesta que termina a medias pero conserva una marca se devuelve."""
    text = "La función login está en auth.py [F1], y además se usa para"

    response = bot._interpret(text, make_delivered())

    assert response.reply == text
    assert response.reason is None
    assert [citation.number for citation in response.citations] == [1]
    assert_rf19(response)


# --- `_failure`: mensajes de los motivos ------------------------------------


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        (ChatReason.INSUFFICIENT_CONTEXT, INSUFFICIENT_CONTEXT_MESSAGE),
        (ChatReason.UNGROUNDED_ANSWER, UNGROUNDED_ANSWER_MESSAGE),
    ],
)
def test_failure_returns_the_spanish_message_without_citations(
    reason: ChatReason, message: str
) -> None:
    """Cada motivo propio del bot tiene su mensaje en español y cero citas."""
    response = bot._failure(reason)

    assert response.reply == message
    assert response.reason == reason
    assert response.citations == []
    assert_rf19(response)


# --- RF-19: invariante en todos los caminos de `_interpret` -----------------


@pytest.mark.parametrize(
    "text",
    [
        "Respuesta fundamentada [F1].",
        "NO_ENCONTRADO",
        "  NO_ENCONTRADO\n",
        "Respuesta sin marcas.",
        "",
        "Solo una marca fuera de rango [F9].",
        "Solo textos que no son marcas [F0], [F01], [f2] y [F1234].",
    ],
)
def test_rf19_holds_for_every_interpretation_path(text: str) -> None:
    """Éxito, centinela y respuestas sin fundamento respetan RF-19."""
    response = bot._interpret(text, make_delivered(3))

    assert_rf19(response)
