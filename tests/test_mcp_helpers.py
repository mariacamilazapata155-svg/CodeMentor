"""Pruebas de las funciones puras y los mensajes de `app.mcp_server`.

Comprueban la validación de argumentos, el formato de los fragmentos y del
éxito del indexado, la construcción de resultados y los textos exactos del
plan. No abren conexiones MCP, no indexan y no usan el modelo de embeddings.
"""

from collections.abc import Callable

import pytest
from mcp.types import CallToolResult, TextContent

from app import main, mcp_server
from app.models import Chunk, IndexResult, SearchResult

#: Copia literal de la tabla de mensajes propios del plan (RNF-3).
OWN_MESSAGES = {
    "MSG_QUERY_REQUIRED": (
        "Falta la consulta: el argumento «query» es obligatorio y debe ser un "
        "texto."
    ),
    "MSG_QUERY_NOT_TEXT": "El argumento «query» debe ser un texto.",
    "MSG_PATH_REQUIRED": (
        "Falta la ruta del archivo: el argumento «path» es obligatorio y no "
        "puede estar vacío."
    ),
    "MSG_PATH_NOT_TEXT": "El argumento «path» debe ser un texto.",
    "MSG_EXTENSION": "Solo se aceptan archivos de Python (.py).",
    "MSG_CONTENT_REQUIRED": (
        "Falta el contenido del archivo: el argumento «content» es obligatorio "
        "y debe ser un texto."
    ),
    "MSG_CONTENT_NOT_TEXT": "El argumento «content» debe ser un texto.",
    "MSG_EMPTY_INDEX": (
        "Todavía no hay código indexado. Indexa un archivo .py con la "
        "herramienta index_file para poder buscar en él."
    ),
    "MSG_UNKNOWN_TOOL": (
        "La herramienta «{name}» no existe. Usa search_code para buscar o "
        "index_file para indexar un archivo .py."
    ),
    "MSG_INTERNAL_ERROR": (
        "Ocurrió un error interno al ejecutar la herramienta. Inténtalo de "
        "nuevo."
    ),
}


def make_chunk(
    *,
    file_path: str = "app/x.py",
    symbol_name: str = "login",
    start_line: int = 3,
    end_line: int = 9,
    content: str = "def login():\n    return True\n",
) -> Chunk:
    """Crea un fragmento citable con los datos indicados."""
    return Chunk(
        file_path=file_path,
        symbol_name=symbol_name,
        start_line=start_line,
        end_line=end_line,
        content=content,
        kind="function",
    )


def make_search_result(score: float = 0.87, **kwargs: object) -> SearchResult:
    """Crea un resultado de búsqueda con un fragmento y una puntuación."""
    return SearchResult(chunk=make_chunk(**kwargs), score=score)


# --- _parse_query (RF-6 y RF-27) ---------------------------------------------


def test_parse_query_requires_the_query_argument() -> None:
    """Sin `query` se devuelve el mensaje de argumento obligatorio."""
    assert mcp_server._parse_query({}) == (None, mcp_server.MSG_QUERY_REQUIRED)


@pytest.mark.parametrize("query", [None, 1, [], {}], ids=["none", "int", "list", "dict"])
def test_parse_query_rejects_values_that_are_not_text(query: object) -> None:
    """Un `query` que no es texto se rechaza con su mensaje específico."""
    assert mcp_server._parse_query({"query": query}) == (
        None,
        mcp_server.MSG_QUERY_NOT_TEXT,
    )


@pytest.mark.parametrize(
    "query",
    ["login", "  ¿Dónde está login?  ", "a" * 1000],
    ids=["simple", "con-espacios", "mil-caracteres"],
)
def test_parse_query_returns_the_text_unchanged(query: str) -> None:
    """La consulta válida se devuelve tal cual, sin recortar ni validar límites."""
    assert mcp_server._parse_query({"query": query}) == (query, None)


def test_parse_query_ignores_undeclared_arguments() -> None:
    """Un argumento extra no cambia el resultado."""
    assert mcp_server._parse_query({"query": "login", "extra": 1}) == (
        "login",
        None,
    )


# --- _parse_index_arguments (RF-12, RF-13, RF-14 y RF-27) --------------------


@pytest.mark.parametrize(
    "arguments",
    [{}, {"content": "x"}],
    ids=["sin-argumentos", "solo-contenido"],
)
def test_parse_index_requires_the_path_argument(arguments: dict[str, object]) -> None:
    """La ruta se comprueba antes que el contenido."""
    assert mcp_server._parse_index_arguments(arguments) == (
        None,
        mcp_server.MSG_PATH_REQUIRED,
    )


@pytest.mark.parametrize("path", [None, 1, [], {}], ids=["none", "int", "list", "dict"])
def test_parse_index_rejects_a_path_that_is_not_text(path: object) -> None:
    """Una ruta que no es texto se rechaza con su mensaje específico."""
    assert mcp_server._parse_index_arguments({"path": path, "content": "x"}) == (
        None,
        mcp_server.MSG_PATH_NOT_TEXT,
    )


@pytest.mark.parametrize("path", ["", "   ", "\n\t"], ids=["vacia", "espacios", "saltos"])
def test_parse_index_rejects_a_blank_path(path: str) -> None:
    """Una ruta vacía o de solo espacios se rechaza como obligatoria."""
    assert mcp_server._parse_index_arguments({"path": path, "content": "x"}) == (
        None,
        mcp_server.MSG_PATH_REQUIRED,
    )


@pytest.mark.parametrize(
    "path",
    ["a.txt", "a.js", "a.py.txt", "py", "a.pyi", "a.py "],
    ids=["txt", "js", "py-txt", "sin-punto", "pyi", "espacio-final"],
)
def test_parse_index_rejects_paths_without_py_extension(path: str) -> None:
    """Solo se aceptan rutas que terminen en `.py`, sin distinguir mayúsculas."""
    assert mcp_server._parse_index_arguments({"path": path, "content": "x"}) == (
        None,
        mcp_server.MSG_EXTENSION,
    )


@pytest.mark.parametrize(
    "path",
    [
        ".py",
        "a.py",
        "a.PY",
        "app/Main.Py",
        " a.py",
        "../../etc/passwd.py",
        "C:\\Windows\\System32\\evil.py",
        "<b>a</b>.py",
        '"a".py',
        "a\nb.py",
    ],
    ids=[
        "solo-extension",
        "minusculas",
        "mayusculas",
        "mixta",
        "espacio-inicial",
        "recorrido",
        "windows",
        "html",
        "comillas",
        "salto",
    ],
)
def test_parse_index_accepts_py_paths_and_preserves_them(path: str) -> None:
    """La ruta se acepta y se devuelve exactamente como llegó."""
    content = "  def x():\n\treturn 1\n"

    assert mcp_server._parse_index_arguments({"path": path, "content": content}) == (
        (path, content),
        None,
    )


def test_parse_index_requires_the_content_argument() -> None:
    """Con una ruta válida, la falta de contenido tiene su propio mensaje."""
    assert mcp_server._parse_index_arguments({"path": "a.py"}) == (
        None,
        mcp_server.MSG_CONTENT_REQUIRED,
    )


@pytest.mark.parametrize(
    "content", [None, 1, [], {}], ids=["none", "int", "list", "dict"]
)
def test_parse_index_rejects_content_that_is_not_text(content: object) -> None:
    """Un contenido que no es texto se rechaza con su mensaje específico."""
    assert mcp_server._parse_index_arguments(
        {"path": "a.py", "content": content}
    ) == (None, mcp_server.MSG_CONTENT_NOT_TEXT)


def test_parse_index_checks_extension_before_content() -> None:
    """La extensión se comprueba antes que el contenido."""
    assert mcp_server._parse_index_arguments({"path": "a.txt"}) == (
        None,
        mcp_server.MSG_EXTENSION,
    )
    assert mcp_server._parse_index_arguments(
        {"path": "a.txt", "content": None}
    ) == (None, mcp_server.MSG_EXTENSION)


def test_parse_index_checks_path_type_before_blankness() -> None:
    """El tipo de la ruta se comprueba antes que su contenido vacío."""
    assert mcp_server._parse_index_arguments({"path": None, "content": ""}) == (
        None,
        mcp_server.MSG_PATH_NOT_TEXT,
    )


def test_parse_index_returns_arguments_unchanged_and_ignores_extras() -> None:
    """Ni la ruta ni el contenido se recortan; los extras se ignoran."""
    path = "  app/x.py"
    content = "  def x():\n\treturn 1\n"

    assert mcp_server._parse_index_arguments(
        {"path": path, "content": content, "extra": True}
    ) == ((path, content), None)


# --- Formato de números y relevancia (RF-3) ----------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (1000, "1.000"), (1_048_576, "1.048.576")],
    ids=["cero", "mil", "un-mib"],
)
def test_format_number_uses_thousands_separator(value: int, expected: str) -> None:
    """Los enteros se muestran con punto de miles."""
    assert mcp_server._format_number(value) == expected


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, "0,00"),
        (0.3, "0,30"),
        (0.87, "0,87"),
        (1.0, "1,00"),
        (-0.2, "0,00"),
        (1.2, "1,00"),
    ],
    ids=["cero", "treinta", "ochenta-y-siete", "uno", "negativo", "mayor-que-uno"],
)
def test_format_relevance_clamps_and_uses_two_decimals(
    score: float, expected: str
) -> None:
    """La relevancia se acota a [0, 1] y usa coma decimal."""
    assert mcp_server._format_relevance(score) == expected


# --- Formato de fragmentos (RF-3 y RF-9) -------------------------------------


def test_format_result_builds_the_exact_block() -> None:
    """El bloque tiene las seis líneas del plan y conserva el texto tal cual."""
    result = make_search_result(
        score=0.87,
        file_path="app/x.py",
        symbol_name="login",
        start_line=3,
        end_line=9,
        content="def login():\n    return True\n",
    )

    expected = (
        "Fragmento 1 de 1\n"
        "Ruta: app/x.py\n"
        "Símbolo: login\n"
        "Líneas: 3–9\n"
        "Relevancia: 0,87\n"
        "Texto:\n"
        "def login():\n"
        "    return True\n"
    )

    assert mcp_server._format_result(1, 1, result) == expected


def test_format_result_uses_an_en_dash_between_lines() -> None:
    """Entre las dos líneas se usa un guion de raya, no un guion normal."""
    result = make_search_result(start_line=12, end_line=34)

    block = mcp_server._format_result(2, 5, result)

    assert "Líneas: 12–34" in block
    assert "Líneas: 12-34" not in block
    assert block.startswith("Fragmento 2 de 5\n")


def test_format_search_results_joins_blocks_in_order() -> None:
    """Los bloques se unen con una línea en blanco y conservan el orden."""
    results = [
        make_search_result(
            score=1.0,
            file_path="app/a.py",
            symbol_name="a",
            start_line=1,
            end_line=2,
            content="a\n",
        ),
        make_search_result(
            score=0.5,
            file_path="app/b.py",
            symbol_name="b",
            start_line=3,
            end_line=4,
            content="b\n",
        ),
        make_search_result(
            score=0.0,
            file_path="app/c.py",
            symbol_name="c",
            start_line=5,
            end_line=6,
            content="c\n",
        ),
    ]

    expected = "\n\n".join(
        mcp_server._format_result(index, len(results), result)
        for index, result in enumerate(results, 1)
    )

    assert mcp_server._format_search_results(results) == expected
    assert mcp_server._format_search_results(results).startswith(
        "Fragmento 1 de 3\nRuta: app/a.py"
    )
    assert mcp_server._format_search_results(results).endswith(
        "Fragmento 3 de 3\nRuta: app/c.py"
        "\nSímbolo: c"
        "\nLíneas: 5–6"
        "\nRelevancia: 0,00"
        "\nTexto:\nc\n"
    )


def test_format_search_results_without_results_is_empty() -> None:
    """Sin fragmentos no se inventa ningún texto."""
    assert mcp_server._format_search_results([]) == ""


# --- Formato del éxito del indexado (RF-10) ----------------------------------


def test_format_index_success_builds_the_exact_text() -> None:
    """El éxito lleva el mensaje literal y los cuatro datos con punto de miles."""
    result = IndexResult(
        file_path="app/x.py",
        chunks_indexed=1000,
        total_chunks=1_048_576,
        used_windows=False,
        message="Archivo indexado: 2 de este archivo; el índice tiene 5 en total.",
    )

    expected = (
        "Archivo indexado: 2 de este archivo; el índice tiene 5 en total.\n"
        "\n"
        "Ruta: app/x.py\n"
        "Fragmentos indexados: 1.000\n"
        "Total del índice: 1.048.576\n"
        "Troceado por ventanas: no"
    )

    assert mcp_server._format_index_success(result) == expected


def test_format_index_success_marks_windows_chunking_with_si() -> None:
    """El troceado por ventanas se muestra como `sí` cuando ocurrió."""
    result = IndexResult(
        file_path="app/x.py",
        chunks_indexed=1,
        total_chunks=1,
        used_windows=True,
        message="Archivo indexado: 1 de este archivo; el índice tiene 1 en total.",
    )

    text = mcp_server._format_index_success(result)

    assert text.startswith(result.message + "\n\n")
    assert text.endswith("Troceado por ventanas: sí")


# --- Resultados de herramienta (RF-24 y RF-26) -------------------------------


@pytest.mark.parametrize(
    ("builder", "is_error"),
    [(mcp_server._ok, False), (mcp_server._error, True)],
    ids=["ok", "error"],
)
def test_ok_and_error_build_text_results(
    builder: Callable[[str], CallToolResult], is_error: bool
) -> None:
    """Ambos constructores devuelven un único `TextContent` con la marca correcta."""
    result = builder("texto de prueba")

    assert result.is_error is is_error
    assert len(result.content) == 1
    content = result.content[0]
    assert isinstance(content, TextContent)
    assert content.type == "text"
    assert content.text == "texto de prueba"


# --- Mensajes propios (RNF-3) ------------------------------------------------


@pytest.mark.parametrize(
    ("name", "text"), OWN_MESSAGES.items(), ids=OWN_MESSAGES.keys()
)
def test_own_messages_match_the_plan_exactly(name: str, text: str) -> None:
    """Cada mensaje propio coincide con el texto literal del plan."""
    assert getattr(mcp_server, name) == text


@pytest.mark.parametrize("name", OWN_MESSAGES)
def test_own_messages_end_with_a_period(name: str) -> None:
    """Todos los mensajes son frases completas."""
    assert getattr(mcp_server, name).endswith(".")


@pytest.mark.parametrize("name", OWN_MESSAGES)
@pytest.mark.parametrize(
    "forbidden", ["Traceback", "Exception", "Error executing tool", "api_key"]
)
def test_own_messages_have_no_technical_details(name: str, forbidden: str) -> None:
    """Los mensajes no filtran detalles técnicos ni nombres internos."""
    assert forbidden not in getattr(mcp_server, name)


def test_extension_message_matches_the_http_layer() -> None:
    """La regla `.py` se redacta igual que en la subida HTTP."""
    assert mcp_server.MSG_EXTENSION == main.MSG_INVALID_EXTENSION
