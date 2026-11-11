"""Pruebas de las piezas del troceado de código.

Cubren `_split_lines`, `_line_body`, `_chunk_text` y `_format_number`: solo
`\\n`, `\\r\\n` y `\\r` cuentan como salto de línea, el texto de un rango es la
subcadena exacta sin el separador de la última línea, y los bordes no se
recortan (RF-6, RF-27, RNF-6, RNF-7).

Cubren también el troceado por símbolos de T4: `_parse_module`,
`_iter_definitions`, `_definition_start`, `_attached_comment_start`,
`_make_chunk` y `_sort_chunks` (RF-2, RF-3, RF-5, RF-17, RF-23, RF-27).

Y, al final, los bloques de módulo de T5: `_module_blocks` (RF-4, RF-20, RF-23,
RF-26), incluido que el recorte de blancos va antes del conteo de 120 líneas y
que el contador de `module#N` solo avanza al partir bloques.

Cierra el ensamblado de T6: `chunk_python_file` completo, con el plan B de
ventanas de 60 líneas (RF-8, RF-9), la cobertura de toda línea con código sobre
los fixtures y sobre `app/rag.py` y `app/storage.py` (RF-7) y el orden final
(RF-17).

No descargan el modelo, no usan red y no llaman a Anthropic.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import rag
from app.models import Chunk


def line_spans(source: str) -> list[tuple[int, int, int]]:
    """Calcula (inicio, fin sin separador, fin con separador) de cada línea.

    Se recorre el texto carácter a carácter para que la prueba no se valide a
    sí misma reutilizando `rag._split_lines`. A propósito no se usa
    `str.splitlines()`: además de `\\n`, `\\r\\n` y `\\r`, corta en `\\f`, `\\v`
    y otros caracteres de control, y RF-6 exige justo que esos caracteres se
    queden dentro de la línea.
    """
    spans: list[tuple[int, int, int]] = []
    start = 0
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\r":
            end = index + 2 if source[index : index + 2] == "\r\n" else index + 1
            spans.append((start, index, end))
            start = end
            index = end
        elif char == "\n":
            spans.append((start, index, index + 1))
            start = index + 1
            index += 1
        else:
            index += 1
    if start < len(source):
        spans.append((start, len(source), len(source)))
    return spans


def expected_text(source: str, start_line: int, end_line: int) -> str:
    """Subcadena real del rango, sin el separador que cierra la última línea."""
    spans = line_spans(source)
    return source[spans[start_line - 1][0] : spans[end_line - 1][1]]


def test_split_lines_keeps_a_file_without_newlines_as_one_line() -> None:
    """Un texto sin separadores es una sola línea, sin añadir nada."""
    assert rag._split_lines("a = 1") == ["a = 1"]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("a\nb", ["a\n", "b"]),
        ("a\r\nb", ["a\r\n", "b"]),
        ("a\rb", ["a\r", "b"]),
        ("a\nb\r\nc\rd", ["a\n", "b\r\n", "c\r", "d"]),
    ],
)
def test_split_lines_supports_the_three_line_endings(
    source: str, expected: list[str]
) -> None:
    """`\\n`, `\\r\\n` y `\\r` abren línea nueva y el separador se conserva."""
    assert rag._split_lines(source) == expected


@pytest.mark.parametrize("source", ["a\n", "a\r\n", "a\r"])
def test_split_lines_does_not_add_an_empty_line_at_the_end(source: str) -> None:
    """Un archivo que termina en salto de línea no produce una línea vacía de más."""
    assert rag._split_lines(source) == [source]


def test_split_lines_keeps_an_empty_last_line_after_two_newlines() -> None:
    """Con dos saltos seguidos sí existe una última línea vacía, con su separador."""
    assert rag._split_lines("a\n\n") == ["a\n", "\n"]


def test_split_lines_does_not_split_on_form_feed() -> None:
    """Un `\\f` dentro de una línea es contenido y no abre una línea nueva."""
    source = "antes\fdentro\nsiguiente\n"

    assert rag._split_lines(source) == ["antes\fdentro\n", "siguiente\n"]
    # `splitlines()` sí cortaría en `\f`: por eso no se usa como referencia.
    assert len(source.splitlines()) == 3


def test_split_lines_returns_no_lines_for_empty_source() -> None:
    """Un texto vacío no tiene ninguna línea."""
    assert rag._split_lines("") == []


def test_split_lines_preserves_edges_and_round_trips() -> None:
    """Los espacios, tabulaciones y líneas de los bordes se conservan al unir."""
    source = "  x  \n\ty\t\n\n  z"

    lines = rag._split_lines(source)

    assert lines == ["  x  \n", "\ty\t\n", "\n", "  z"]
    assert "".join(lines) == source


@pytest.mark.parametrize(
    ("line", "expected"),
    [("a\n", "a"), ("a\r\n", "a"), ("a\r", "a"), ("\r\n", ""), ("\n", "")],
)
def test_line_body_removes_one_trailing_separator(line: str, expected: str) -> None:
    """Quita el separador final, incluido `\\r\\n` como una sola unidad."""
    assert rag._line_body(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [("a", "a"), ("", ""), ("a\f", "a\f"), ("a\v", "a\v")],
)
def test_line_body_keeps_lines_without_a_separator(line: str, expected: str) -> None:
    """Si no hay separador final, la línea se devuelve intacta."""
    assert rag._line_body(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [("a\n\n", "a\n"), ("a\r\r", "a\r"), ("a\r\n\n", "a\r\n"), ("a\n\r", "a\n")],
)
def test_line_body_removes_only_one_separator(line: str, expected: str) -> None:
    """Solo se quita el último separador, no todos los del final."""
    assert rag._line_body(line) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [("  a  \n", "  a  "), ("\t\n", "\t"), ("  \r\n", "  ")],
)
def test_line_body_does_not_trim_spaces(line: str, expected: str) -> None:
    """Los espacios y tabulaciones de la línea se conservan."""
    assert rag._line_body(line) == expected


@pytest.mark.parametrize(
    "source",
    ["uno\ndos\ntres\n", "uno\r\ndos\r\ntres\r\n", "uno\rdos\rtres\r"],
)
def test_chunk_text_with_lf_crlf_and_cr(source: str) -> None:
    """El texto del rango coincide en los tres finales de línea."""
    lines = rag._split_lines(source)

    assert len(lines) == 3
    assert rag._chunk_text(lines, 2, 3) == expected_text(source, 2, 3)
    assert rag._chunk_text(lines, 2, 3).startswith("dos")


@pytest.mark.parametrize(
    "source",
    [
        "uno\ndos\ntres\n",
        "uno\r\ndos\r\ntres\r\n",
        "uno\rdos\rtres\r",
        "  uno  \n\tdos\t\ntres\n",
    ],
)
@pytest.mark.parametrize(
    ("start_line", "end_line"),
    [(1, 1), (1, 3), (2, 2), (2, 3), (3, 3), (1, 2)],
)
def test_chunk_text_is_the_real_substring(
    source: str, start_line: int, end_line: int
) -> None:
    """Cada rango devuelve exactamente la subcadena real del archivo."""
    lines = rag._split_lines(source)

    assert rag._chunk_text(lines, start_line, end_line) == expected_text(
        source, start_line, end_line
    )


def test_chunk_text_leaves_out_the_separator_of_the_last_line() -> None:
    """Aunque el archivo termine en salto de línea, el texto no lo incluye."""
    source = "a\nb\n"

    assert rag._chunk_text(rag._split_lines(source), 1, 2) == "a\nb"


def test_chunk_text_includes_the_previous_separator_when_the_last_line_is_empty() -> (
    None
):
    """Si la última línea está vacía, el texto conserva el separador anterior."""
    source = "a\nb\n\nc"
    lines = rag._split_lines(source)

    assert lines[2] == "\n"
    assert rag._chunk_text(lines, 2, 3) == "b\n"
    assert rag._chunk_text(lines, 2, 3).endswith("\n")
    assert rag._chunk_text(lines, 1, 3) == "a\nb\n"
    assert rag._chunk_text(lines, 3, 4) == "\nc"
    assert rag._chunk_text(lines, 2, 3) == expected_text(source, 2, 3)


def test_chunk_text_does_not_split_on_form_feed() -> None:
    """Un `\\f` dentro de una línea forma parte del texto del fragmento."""
    source = "antes\fdentro\nsiguiente\n"
    lines = rag._split_lines(source)

    assert rag._chunk_text(lines, 1, 1) == "antes\fdentro"
    assert rag._chunk_text(lines, 1, 2) == "antes\fdentro\nsiguiente"
    assert rag._chunk_text(lines, 1, 2) == expected_text(source, 1, 2)


def test_chunk_text_does_not_trim_the_edges() -> None:
    """La indentación inicial y los espacios finales se conservan intactos."""
    source = "  def f():  \n\treturn 1  \n"
    lines = rag._split_lines(source)

    text = rag._chunk_text(lines, 1, 2)

    assert text == "  def f():  \n\treturn 1  "
    assert text.startswith("  ")
    assert text.endswith("  ")
    assert text == expected_text(source, 1, 2)


def test_chunk_text_with_a_single_line() -> None:
    """Un rango de una sola línea devuelve esa línea sin su separador."""
    source = "uno\ndos\ntres"

    assert rag._chunk_text(rag._split_lines(source), 2, 2) == "dos"


def test_chunk_text_of_the_whole_file() -> None:
    """El rango completo del archivo es todo el texto sin el último separador."""
    source = "uno\n\ndos\n"

    assert rag._chunk_text(rag._split_lines(source), 1, 3) == "uno\n\ndos"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0"),
        (7, "7"),
        (999, "999"),
        (1_000, "1.000"),
        (1_048_576, "1.048.576"),
        (1_000_000_000, "1.000.000.000"),
    ],
)
def test_format_number_uses_a_dot_for_thousands(value: int, expected: str) -> None:
    """Las cifras se agrupan de tres en tres con punto, como en la spec 001."""
    assert rag._format_number(value) == expected


def test_format_number_matches_the_message_of_the_001() -> None:
    """El límite de la consulta se formatea igual que en su mensaje ya existente."""
    formatted = rag._format_number(rag.MAX_QUERY_LENGTH)

    assert formatted == "1.000"
    assert formatted in rag.QUERY_TOO_LONG_MESSAGE


# --- Troceado por símbolos (T4) -------------------------------------------


def definitions_of(source: str) -> list[rag._Definition]:
    """Analiza el texto y devuelve las definiciones que generan fragmento."""
    tree = rag._parse_module(source)
    assert tree is not None
    return rag._iter_definitions(tree)


def symbol_chunk(source: str, symbol_name: str) -> Chunk:
    """Construye el fragmento de un símbolo igual que lo hará el troceado."""
    lines = rag._split_lines(source)
    tree = rag._parse_module(source)
    assert tree is not None
    definition = next(
        item for item in rag._iter_definitions(tree) if item.symbol_name == symbol_name
    )
    start = rag._definition_start(definition.node, lines, rag._string_lines(tree))
    return rag._make_chunk(
        "ejemplo.py",
        definition.symbol_name,
        definition.kind,
        start,
        definition.node.end_lineno,
        lines,
    )


def test_parse_module_returns_the_tree_of_valid_python() -> None:
    """Un texto válido se analiza y conserva las definiciones de nivel superior."""
    tree = rag._parse_module("def f():\n    pass\n")

    assert isinstance(tree, ast.Module)
    assert [node.name for node in tree.body] == ["f"]


@pytest.mark.parametrize(
    "source",
    [
        "esto no es Python",
        "function f(){}",
        "def f(:\n    pass\n",
        "    def f():\n        pass\n",
        "x = 1\x00\n",
    ],
)
def test_parse_module_returns_none_when_the_source_is_not_python(source: str) -> None:
    """Prosa, JS, sintaxis o indentación rotas y bytes nulos no son analizables."""
    assert rag._parse_module(source) is None


def test_iter_definitions_returns_nothing_for_a_module_without_definitions() -> None:
    """Asignaciones y cadenas de documentación no generan fragmento de símbolo."""
    assert definitions_of('"""Docstring."""\n\nx = 1\n') == []


SYMBOLS_SOURCE = """\
def plain():
    return 1


async def fetch():
    return 2


class User:
    def login(self):
        return True

    async def logout(self):
        return False


class Outer:
    class Inner:
        def metodo(self):
            return 3
"""


def test_iter_definitions_finds_functions_async_classes_and_methods() -> None:
    """Cubre función, `async def`, clase, método, clase anidada y su método."""
    definitions = definitions_of(SYMBOLS_SOURCE)

    assert [(item.symbol_name, item.kind) for item in definitions] == [
        ("plain", "function"),
        ("fetch", "function"),
        ("User", "class"),
        ("User.login", "function"),
        ("User.logout", "function"),
        ("Outer", "class"),
        ("Outer.Inner", "class"),
        ("Outer.Inner.metodo", "function"),
    ]


CONDITIONAL_SOURCE = """\
if True:
    def under_if():
        return 1

    if True:
        def under_nested_if():
            return 2


try:
    def under_try():
        return 3
except ValueError:
    def under_except():
        return 4
else:
    def under_else():
        return 5
finally:
    def under_finally():
        return 6


with open("archivo.txt") as handle:
    class UnderWith:
        def metodo(self):
            return 7


for item in range(3):
    def under_for():
        return 8


while False:
    def under_while():
        return 9


match 1:
    case 1:
        def under_case():
            return 10
"""


def test_iter_definitions_includes_module_level_blocks() -> None:
    """`if`, `try`, `with`, `for`, `while` y `match` de módulo son nivel superior."""
    definitions = definitions_of(CONDITIONAL_SOURCE)
    by_name = {item.symbol_name: item.kind for item in definitions}
    expected = {
        "under_if",
        "under_nested_if",
        "under_try",
        "under_except",
        "under_else",
        "under_finally",
        "UnderWith",
        "UnderWith.metodo",
        "under_for",
        "under_while",
        "under_case",
    }

    assert set(by_name) == expected
    assert len(definitions) == len(expected)
    assert by_name["UnderWith"] == "class"
    assert by_name["UnderWith.metodo"] == "function"


NESTED_IN_FUNCTIONS_SOURCE = """\
def outer():
    def inner():
        return 1

    class Local:
        def metodo(self):
            return 2

    return inner


class Container:
    def outer_method(self):
        class LocalInsideMethod:
            def metodo(self):
                return 3

        return LocalInsideMethod
"""


def test_iter_definitions_does_not_descend_into_functions() -> None:
    """Funciones y clases dentro de una función quedan en su fragmento."""
    names = [item.symbol_name for item in definitions_of(NESTED_IN_FUNCTIONS_SOURCE)]

    assert names == ["outer", "Container", "Container.outer_method"]


CLASS_CONDITIONAL_SOURCE = """\
class WithConditional:
    def directo(self):
        return 1

    if True:
        def en_if(self):
            return 2

        class EnIf:
            def metodo(self):
                return 3

    try:
        def en_try(self):
            return 4
    except ValueError:
        def en_except(self):
            return 5

    with open("archivo.txt") as handle:
        def en_with(self):
            return 6
"""


def test_iter_definitions_ignores_members_inside_a_class_conditional_block() -> None:
    """Solo lo definido directamente en el cuerpo de la clase genera fragmento."""
    definitions = definitions_of(CLASS_CONDITIONAL_SOURCE)

    assert [item.symbol_name for item in definitions] == [
        "WithConditional",
        "WithConditional.directo",
    ]


def test_class_chunk_contains_the_members_it_ignores() -> None:
    """El rango de la clase incluye los métodos y clases de sus bloques internos."""
    lines = rag._split_lines(CLASS_CONDITIONAL_SOURCE)
    chunk = symbol_chunk(CLASS_CONDITIONAL_SOURCE, "WithConditional")

    assert chunk.end_line == len(lines)
    assert "def en_if" in chunk.content
    assert "class EnIf" in chunk.content
    assert "def en_try" in chunk.content
    assert "def en_with" in chunk.content


CONTAINER_SOURCE = """\
class User:
    def first(self):
        return 1

    def second(self):
        return 2
"""


def test_class_range_contains_its_methods_without_overlapping_them() -> None:
    """La clase contiene a sus métodos y los métodos no se solapan entre sí."""
    chunks = [
        symbol_chunk(CONTAINER_SOURCE, item.symbol_name)
        for item in definitions_of(CONTAINER_SOURCE)
    ]
    by_symbol = {chunk.symbol_name: chunk for chunk in chunks}

    user = by_symbol["User"]
    first = by_symbol["User.first"]
    second = by_symbol["User.second"]

    assert user.start_line <= first.start_line
    assert user.start_line <= second.start_line
    assert user.end_line >= first.end_line
    assert user.end_line >= second.end_line
    assert first.end_line < second.start_line


def test_definition_start_includes_the_attached_comment_group() -> None:
    """Un grupo de comentarios pegado encima entra completo en el fragmento."""
    source = "# uno\n# dos\ndef f():\n    pass\n"

    assert symbol_chunk(source, "f").start_line == 1


def test_definition_start_includes_a_simple_decorator() -> None:
    """El fragmento empieza en el decorador, no en el `def`."""
    source = "@decorador\ndef f():\n    pass\n"

    assert symbol_chunk(source, "f").start_line == 1


def test_definition_start_includes_a_multiline_decorator() -> None:
    """Un decorador de varias líneas entra completo, con sus argumentos."""
    source = '@decorador(\n    "argumento",\n)\ndef f():\n    pass\n'

    chunk = symbol_chunk(source, "f")

    assert chunk.start_line == 1
    assert chunk.content.startswith('@decorador(\n    "argumento",\n)')


@pytest.mark.parametrize(
    ("definition", "symbol_name"),
    [
        ("def f():\n    pass\n", "f"),
        ("async def f():\n    pass\n", "f"),
        ("class C:\n    pass\n", "C"),
    ],
)
def test_definition_start_includes_a_comment_above_a_decorator(
    definition: str, symbol_name: str
) -> None:
    """El comentario pegado antes del decorador también entra en el rango."""
    source = f"# comentario\n@decorador\n{definition}"

    assert symbol_chunk(source, symbol_name).start_line == 1


def test_definition_start_stops_at_a_blank_line() -> None:
    """Una línea en blanco corta el grupo: el comentario se queda en módulo."""
    source = "# suelto\n\ndef f():\n    pass\n"

    assert symbol_chunk(source, "f").start_line == 3


def test_function_range_ends_at_its_last_statement() -> None:
    """Las líneas en blanco y el comentario posterior no entran en el fragmento."""
    source = "def f():\n    valor = 1\n    return valor\n\n\n# suelto\n"

    chunk = symbol_chunk(source, "f")

    assert chunk.start_line == 1
    assert chunk.end_line == 3
    assert chunk.content == "def f():\n    valor = 1\n    return valor"


def test_class_range_ends_at_the_last_line_of_its_body() -> None:
    """El rango de una clase no incluye blancos ni comentarios posteriores."""
    source = (
        "class C:\n"
        "    valor = 1\n"
        "\n"
        "    def metodo(self):\n"
        "        return self.valor\n"
        "\n"
        "\n"
        "# suelto\n"
    )

    chunk = symbol_chunk(source, "C")

    assert chunk.start_line == 1
    assert chunk.end_line == 5
    assert chunk.content.endswith("return self.valor")


def test_class_range_does_not_include_a_comment_after_its_body() -> None:
    """Un comentario detrás de la última instrucción ya no es parte del símbolo."""
    source = "class C:\n    valor = 1\n    # nota final\n"

    chunk = symbol_chunk(source, "C")

    assert chunk.end_line == 2
    assert "# nota final" not in chunk.content


@pytest.mark.parametrize(
    ("symbol_name", "kind", "expected"),
    [
        ("f", "function", "def f():\n    return 1"),
        ("C", "class", "class C:\n    pass"),
    ],
)
def test_make_chunk_builds_every_field_with_the_exact_text(
    symbol_name: str, kind: str, expected: str
) -> None:
    """El fragmento trae ruta, símbolo, líneas, texto y tipo, sin recortes."""
    source = expected + "\n"
    lines = rag._split_lines(source)

    chunk = rag._make_chunk("carpeta/modulo.py", symbol_name, kind, 1, 2, lines)

    assert chunk == Chunk(
        file_path="carpeta/modulo.py",
        symbol_name=symbol_name,
        start_line=1,
        end_line=2,
        content=expected,
        kind=kind,
    )
    assert chunk.content == expected_text(source, 1, 2)


def make_plain_chunk(symbol_name: str, start_line: int, end_line: int) -> Chunk:
    """Fragmento mínimo para probar solo el criterio de orden."""
    return Chunk(
        file_path="orden.py",
        symbol_name=symbol_name,
        start_line=start_line,
        end_line=end_line,
        content="",
        kind="function",
    )


def test_sort_chunks_orders_by_start_end_descending_and_symbol() -> None:
    """Aplica los tres criterios: inicio, fin descendente y nombre alfabético."""
    chunks = [
        make_plain_chunk("z_inner", 1, 5),
        make_plain_chunk("later", 4, 6),
        make_plain_chunk("outer", 1, 10),
        make_plain_chunk("a_inner", 1, 5),
    ]

    ordered = rag._sort_chunks(chunks)

    assert [chunk.symbol_name for chunk in ordered] == [
        "outer",
        "a_inner",
        "z_inner",
        "later",
    ]
    assert [chunk.start_line for chunk in ordered] == [1, 1, 1, 4]
    assert [chunk.end_line for chunk in ordered] == [10, 5, 5, 6]


def test_sort_chunks_returns_a_new_list() -> None:
    """Ordena en una lista nueva y no modifica la recibida."""
    chunks = [make_plain_chunk("b", 2, 2), make_plain_chunk("a", 1, 1)]

    ordered = rag._sort_chunks(chunks)

    assert [chunk.symbol_name for chunk in chunks] == ["b", "a"]
    assert [chunk.symbol_name for chunk in ordered] == ["a", "b"]


def test_sort_chunks_is_stable_for_identical_keys() -> None:
    """Con la misma clave conserva el orden de entrada, así que es determinista."""
    first = make_plain_chunk("same", 1, 1)
    second = make_plain_chunk("same", 1, 1)

    assert rag._sort_chunks([first, second]) == [first, second]
    assert rag._sort_chunks([second, first]) == [second, first]


def test_a_string_line_is_not_an_attached_comment() -> None:
    """Una línea `#` dentro de una cadena triple no alarga el símbolo siguiente.

    Antes del arreglo, `_attached_comment_start` solo miraba el texto y tomaba
    la última línea de la cadena de `a` por un comentario pegado: `b` empezaba
    en la línea 3 y los dos fragmentos se solapaban sin contención (RF-2, RF-3).
    """
    source = 'def a():\n    x = """texto\n# c"""\ndef b(): pass\n'

    chunks = rag.chunk_python_file(source, "cadenas.py")
    by_symbol = {chunk.symbol_name: chunk for chunk in chunks}

    assert (by_symbol["a"].start_line, by_symbol["a"].end_line) == (1, 3)
    assert by_symbol["b"].start_line == 4
    assert (by_symbol["b"].start_line, by_symbol["b"].end_line) == (4, 4)
    assert_symbols_are_nested_or_disjoint(chunks)
    assert_module_chunks_avoid_symbols(chunks)


@pytest.mark.parametrize(
    "source",
    [
        'TEXTO = """inicio\n# linea dentro de la cadena"""\ndef f():\n    pass\n',
        'TEXTO = f"""inicio\n# {valor} dentro"""\ndef f():\n    pass\n',
    ],
    ids=["string", "f_string"],
)
def test_a_multiline_string_keeps_its_last_line_in_module(source: str) -> None:
    """La cadena triple de módulo no alarga `f` ni le quita una línea a `module`."""
    chunks = rag.chunk_python_file(source, "cadena.py")

    assert module_spans(chunks) == [
        ("module", 1, 2),
        ("f", 3, 4),
    ]
    assert chunks[0].content == source.split("\ndef f")[0]


# --- Bloques de módulo (T5) -----------------------------------------------


def covered_lines(source: str) -> set[int]:
    """Líneas que ocuparían los fragmentos de símbolo, como las calculará T6.

    Usa el `start` de `_definition_start` (decoradores y comentarios pegados) y
    el `end_lineno` del nodo, que es justo lo que `_module_blocks` recibirá ya
    calculado.
    """
    lines = rag._split_lines(source)
    tree = rag._parse_module(source)
    assert tree is not None
    string_lines = rag._string_lines(tree)
    covered: set[int] = set()
    for definition in rag._iter_definitions(tree):
        start = rag._definition_start(definition.node, lines, string_lines)
        covered.update(range(start, definition.node.end_lineno + 1))
    return covered


def module_blocks_of(source: str, file_path: str = "ejemplo.py") -> list[Chunk]:
    """Trocea el módulo de un archivo válido, con su cobertura de símbolos."""
    return rag._module_blocks(
        rag._split_lines(source), covered_lines(source), file_path
    )


def assignments(count: int, prefix: str = "VALOR") -> str:
    """Genera `count` líneas de asignaciones de nivel de módulo."""
    return "".join(f"{prefix}_{index} = {index}\n" for index in range(1, count + 1))


def module_spans(chunks: list[Chunk]) -> list[tuple[str, int, int]]:
    """Resumen legible del nombre y el rango de cada fragmento."""
    return [(chunk.symbol_name, chunk.start_line, chunk.end_line) for chunk in chunks]


def assert_module_chunks_are_exact(source: str, chunks: list[Chunk]) -> None:
    """Comprueba texto exacto, tipo `module` y bordes sin líneas en blanco."""
    lines = rag._split_lines(source)
    for chunk in chunks:
        assert chunk.kind == "module"
        assert chunk.start_line <= chunk.end_line
        assert rag._line_body(lines[chunk.start_line - 1]).strip()
        assert rag._line_body(lines[chunk.end_line - 1]).strip()
        assert chunk.content == expected_text(source, chunk.start_line, chunk.end_line)


def test_module_blocks_indexes_imports_and_constants_as_module() -> None:
    """Las líneas que no son de un símbolo forman un fragmento `module`."""
    source = "import os\n\nCONSTANTE = 1\n"

    chunks = module_blocks_of(source)

    assert len(chunks) == 1
    assert chunks[0].symbol_name == "module"
    assert chunks[0].kind == "module"
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 3)
    assert chunks[0].content == "import os\n\nCONSTANTE = 1"


def test_module_blocks_keeps_an_interior_blank_line_in_the_block() -> None:
    """Una línea en blanco entre dos imports no corta la racha (RF-4).

    Solo se recortan los blancos de los bordes: el blanco interior forma parte
    del bloque contiguo, igual que cualquier otra línea no cubierta.
    """
    source = "import os\n\nimport sys\n"

    chunks = module_blocks_of(source)

    assert module_spans(chunks) == [("module", 1, 3)]
    assert chunks[0].content == "import os\n\nimport sys"


def test_module_blocks_does_not_merge_a_lone_import_with_the_next_block() -> None:
    """Un `import` suelto de una línea es su propio fragmento (RF-26)."""
    source = "import os\n\ndef f():\n    return 1\n\nimport sys\n"

    chunks = module_blocks_of(source)

    assert module_spans(chunks) == [
        ("module", 1, 1),
        ("module", 6, 6),
    ]
    assert [chunk.content for chunk in chunks] == ["import os", "import sys"]


CONDITIONAL_STARTUP_SOURCE = (
    "import sys\n"  # 1
    "\n"  # 2
    'if __name__ == "__main__":\n'  # 3
    '    print("arrancando")\n'  # 4
    "\n"  # 5
    "def main():\n"  # 6
    "    return 0\n"  # 7
    "\n"  # 8
    'if __name__ == "__main__":\n'  # 9
    "    main()\n"  # 10
)


def test_module_blocks_cuts_the_startup_block_around_the_function() -> None:
    """La función de dentro parte el bloque de arranque en dos `module`."""
    chunks = module_blocks_of(CONDITIONAL_STARTUP_SOURCE)

    assert module_spans(chunks) == [
        ("module", 1, 4),
        ("module", 9, 10),
    ]
    assert chunks[0].content == (
        'import sys\n\nif __name__ == "__main__":\n    print("arrancando")'
    )
    assert chunks[1].content == 'if __name__ == "__main__":\n    main()'
    assert "def main" not in "".join(chunk.content for chunk in chunks)


def test_module_blocks_counts_a_module_docstring_as_module() -> None:
    """Un archivo con solo la cadena de documentación produce un `module`."""
    source = '"""Utilidades del proyecto."""\n'

    chunks = module_blocks_of(source)

    assert module_spans(chunks) == [("module", 1, 1)]
    assert chunks[0].content == '"""Utilidades del proyecto."""'


def test_module_blocks_indexes_a_file_with_only_comments() -> None:
    """Un archivo solo de comentarios produce un `module` con esas líneas."""
    source = "# primero\n# segundo\n"

    chunks = module_blocks_of(source)

    assert module_spans(chunks) == [("module", 1, 2)]
    assert chunks[0].content == "# primero\n# segundo"


def test_module_blocks_indexes_a_file_with_a_single_assignment() -> None:
    """Una sola asignación es un fragmento de módulo de una línea."""
    source = "TOTAL = 0\n"

    chunks = module_blocks_of(source)

    assert len(chunks) == 1
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 1)
    assert chunks[0].content == "TOTAL = 0"


def test_module_blocks_trims_blank_lines_at_the_edges() -> None:
    """Los blancos del principio y del final no forman parte del fragmento."""
    source = "\n\nCONSTANTE = 1\n\n\n"

    chunks = module_blocks_of(source)

    assert [(chunk.start_line, chunk.end_line) for chunk in chunks] == [(3, 3)]
    assert chunks[0].content == "CONSTANTE = 1"


def test_module_blocks_keeps_comments_at_the_edges_when_not_covered() -> None:
    """Un comentario sin blanco de por medio no es una línea en blanco: entra."""
    source = "# cabecera\nimport os\n\nTOTAL = 1\n# nota final\n\n"

    chunks = module_blocks_of(source)

    assert [(chunk.start_line, chunk.end_line) for chunk in chunks] == [(1, 5)]
    assert chunks[0].content.startswith("# cabecera")
    assert chunks[0].content.endswith("# nota final")


def test_module_blocks_skips_a_block_made_only_of_blank_lines() -> None:
    """Una racha de blancos entre dos símbolos no produce fragmento."""
    source = "def f():\n    pass\n\n\ndef g():\n    pass\n"

    chunks = module_blocks_of(source)

    assert chunks == []


def test_module_blocks_with_an_empty_covered_set_indexes_every_line() -> None:
    """Sin cobertura, todo el archivo es un único bloque de módulo."""
    source = "x = 1\ny = 2\n"
    lines = rag._split_lines(source)

    chunks = rag._module_blocks(lines, set(), "ejemplo.py")

    assert [(chunk.start_line, chunk.end_line) for chunk in chunks] == [(1, 2)]
    assert chunks[0].content == "x = 1\ny = 2"


def test_module_blocks_returns_nothing_when_everything_is_covered() -> None:
    """Si todas las líneas son de símbolos, no hay bloque de módulo."""
    source = "x = 1\ny = 2\n"

    chunks = rag._module_blocks(rag._split_lines(source), {1, 2}, "ejemplo.py")

    assert chunks == []


def test_module_blocks_returns_nothing_for_an_empty_file() -> None:
    """Un archivo sin líneas no produce fragmentos."""
    assert rag._module_blocks([], set(), "vacio.py") == []


def test_module_blocks_with_120_lines_produces_one_module() -> None:
    """Un bloque de exactamente 120 líneas no se parte (RF-20)."""
    source = assignments(120)

    chunks = module_blocks_of(source)

    assert module_spans(chunks) == [("module", 1, 120)]
    assert chunks[0].content == source.rstrip("\n")


def test_module_blocks_splits_a_121_line_block_in_two() -> None:
    """De 121 líneas salen `module#1` de 120 y `module#2` de 1, sin solape."""
    source = assignments(121)

    chunks = module_blocks_of(source)

    assert module_spans(chunks) == [
        ("module#1", 1, 120),
        ("module#2", 121, 121),
    ]
    assert chunks[0].end_line + 1 == chunks[1].start_line
    assert chunks[1].content == "VALOR_121 = 121"
    assert_module_chunks_are_exact(source, chunks)


@pytest.mark.parametrize("count", [119, 120])
def test_module_blocks_trims_before_counting_the_120_lines(count: int) -> None:
    """Un bloque con blancos en los bordes se recorta antes de decidir si se parte.

    Sin recortar primero, un bloque de 119 o 120 líneas de código rodeado de
    blancos parecería de 121 o 122 y se partiría sin necesidad.
    """
    source = "\n" + assignments(count) + "\n"

    chunks = module_blocks_of(source)

    assert module_spans(chunks) == [("module", 2, count + 1)]
    assert chunks[0].content == assignments(count).rstrip("\n")


def test_module_blocks_continues_the_numbering_in_a_second_split_block() -> None:
    """El contador de `module#N` es único por archivo y no se reinicia."""
    source = (
        assignments(121, "PRIMERO")
        + "def f():\n    return 1\n"
        + assignments(121, "SEGUNDO")
    )

    chunks = module_blocks_of(source)

    assert module_spans(chunks) == [
        ("module#1", 1, 120),
        ("module#2", 121, 121),
        ("module#3", 124, 243),
        ("module#4", 244, 244),
    ]
    assert_module_chunks_are_exact(source, chunks)


def test_module_blocks_names_both_unsplit_blocks_module() -> None:
    """Dos bloques sin partir se llaman igual y se distinguen por sus líneas."""
    chunks = module_blocks_of(CONDITIONAL_STARTUP_SOURCE)

    assert [chunk.symbol_name for chunk in chunks] == ["module", "module"]
    assert chunks[0].start_line != chunks[1].start_line


REALISTIC_SOURCE = (
    '"""Utilidades del proyecto."""\n'  # 1
    "\n"  # 2
    "import os\n"  # 3
    "import sys\n"  # 4
    "\n"  # 5
    'VERSION = "1.0"\n'  # 6
    "DEBUG = False\n"  # 7
    "\n"  # 8
    "\n"  # 9
    "# Ajustes de la aplicación\n"  # 10
    "def load_config():\n"  # 11
    "    return os.environ.copy()\n"  # 12
    "\n"  # 13
    "\n"  # 14
    "class Config:\n"  # 15
    '    ruta = "."\n'  # 16
    "\n"  # 17
    "    def load(self):\n"  # 18
    "        return self.ruta\n"  # 19
    "\n"  # 20
    "\n"  # 21
    'if __name__ == "__main__":\n'  # 22
    "    Config().load()\n"  # 23
)


def test_module_blocks_of_a_realistic_module_match_the_expected_blocks() -> None:
    """Docstring, imports y arranque son módulo; los símbolos no se pisan."""
    chunks = module_blocks_of(REALISTIC_SOURCE)
    covered = covered_lines(REALISTIC_SOURCE)

    assert module_spans(chunks) == [
        ("module", 1, 7),
        ("module", 22, 23),
    ]
    for chunk in chunks:
        assert not covered & set(range(chunk.start_line, chunk.end_line + 1))
    assert chunks[0].content == (
        '"""Utilidades del proyecto."""\n\nimport os\nimport sys\n'
        '\nVERSION = "1.0"\nDEBUG = False'
    )
    assert "# Ajustes de la aplicación" not in chunks[0].content
    assert "def load_config" not in chunks[0].content
    assert "class Config" not in chunks[0].content
    assert_module_chunks_are_exact(REALISTIC_SOURCE, chunks)


@pytest.mark.parametrize(
    "source",
    [
        REALISTIC_SOURCE,
        CONDITIONAL_STARTUP_SOURCE,
        "import os\n\ndef f():\n    return 1\n\nimport sys\n",
        '"""Solo documentación."""\n',
        "# solo comentarios\n# y más\n",
        "\n\nCONSTANTE = 1\n\n\n",
    ],
)
def test_module_blocks_text_is_exact_and_starts_and_ends_with_content(
    source: str,
) -> None:
    """Cada `module` cita el texto exacto y no empieza ni acaba en blanco."""
    chunks = module_blocks_of(source)

    assert chunks
    assert_module_chunks_are_exact(source, chunks)


def test_module_blocks_keeps_the_file_path_as_received() -> None:
    """La ruta se copia tal cual, con sus barras invertidas (RNF-6)."""
    chunks = module_blocks_of("x = 1\n", file_path="carpeta\\modulo.py")

    assert [chunk.file_path for chunk in chunks] == ["carpeta\\modulo.py"]


def test_module_blocks_does_not_modify_its_inputs_and_is_deterministic() -> None:
    """Ni las líneas ni `covered` cambian, y dos llamadas dan lo mismo."""
    source = assignments(121, "PRIMERO") + "def f():\n    return 1\n" + "x = 1\n"
    lines = rag._split_lines(source)
    covered = covered_lines(source)
    lines_copy = list(lines)
    covered_copy = set(covered)

    first = rag._module_blocks(lines, covered, "ejemplo.py")
    second = rag._module_blocks(lines, covered, "ejemplo.py")

    assert first == second
    assert lines == lines_copy
    assert covered == covered_copy


# --- Ensamblado de `chunk_python_file` (T6) -------------------------------


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def prose_lines(count: int) -> str:
    """Genera `count` líneas de prosa con espacios, que no son Python válido."""
    return "".join(f"texto libre {index}\n" for index in range(1, count + 1))


def code_lines(source: str) -> set[int]:
    """Líneas con código desde 1: no vacías y que no son solo un comentario.

    Se apoya en `line_spans`, que recorre el texto carácter a carácter, para no
    validar el troceado con `rag._split_lines`. La regla es textual: una línea
    de una cadena triple que empiece por `#` se cuenta aquí como comentario y
    no se exige que esté cubierta. Es una limitación del oráculo que solo puede
    dejar de comprobar una línea, nunca inventar un fallo.
    """
    result: set[int] = set()
    for number, (start, body_end, _) in enumerate(line_spans(source), start=1):
        body = source[start:body_end].strip()
        if body and not body.startswith("#"):
            result.add(number)
    return result


def assert_every_code_line_is_covered(source: str, chunks: list[Chunk]) -> int:
    """Comprueba RF-7 y devuelve cuántas líneas con código se han revisado."""
    covered = {
        line for chunk in chunks for line in range(chunk.start_line, chunk.end_line + 1)
    }
    expected = code_lines(source)
    missing = expected - covered
    assert not missing, f"hay líneas con código sin cubrir: {sorted(missing)}"
    return len(expected)


def spans_intersect(first: Chunk, second: Chunk) -> bool:
    """Indica si dos rangos comparten al menos una línea."""
    return first.start_line <= second.end_line and second.start_line <= first.end_line


def span_contains(outer: Chunk, inner: Chunk) -> bool:
    """Indica si el rango de `outer` incluye entero el de `inner`."""
    return outer.start_line <= inner.start_line and inner.end_line <= outer.end_line


def assert_symbols_are_nested_or_disjoint(chunks: list[Chunk]) -> None:
    """Fuera de la contención de una clase en sus miembros, no hay solapes."""
    symbols = [chunk for chunk in chunks if chunk.kind in {"function", "class"}]
    for index, first in enumerate(symbols):
        for second in symbols[index + 1 :]:
            if not spans_intersect(first, second):
                continue
            assert span_contains(first, second) or span_contains(second, first), (
                f"{first.symbol_name} y {second.symbol_name} se solapan sin contener"
            )
            container, inner = (
                (first, second) if span_contains(first, second) else (second, first)
            )
            assert container.kind == "class", (
                f"{container.symbol_name} contiene a {inner.symbol_name} sin ser clase"
            )


def assert_module_chunks_avoid_symbols(chunks: list[Chunk]) -> None:
    """Ningún fragmento `module` comparte líneas con un fragmento de símbolo."""
    symbols = [chunk for chunk in chunks if chunk.kind != "module"]
    modules = [chunk for chunk in chunks if chunk.kind == "module"]
    for module in modules:
        for symbol in symbols:
            assert not spans_intersect(module, symbol), (
                f"el bloque {module.start_line}-{module.end_line} pisa a "
                f"{symbol.symbol_name}"
            )


NON_PYTHON_SOURCES = {
    "prosa": "esto no es Python\n",
    "javascript": "function f(){}\n",
    "sintaxis_rota": "def f(:\n    pass\n",
    "indentacion_invalida": "    def f():\n        pass\n",
    "bytes_nulos": "x = 1\x00\n",
    "prosa_sin_salto_final": "Esto tampoco es Python",
}


@pytest.mark.parametrize(
    "source", list(NON_PYTHON_SOURCES.values()), ids=list(NON_PYTHON_SOURCES)
)
def test_chunk_python_file_indexes_non_python_content_as_windows(
    source: str,
) -> None:
    """Prosa, JS, sintaxis rota, indentación inválida y bytes nulos no abortan."""
    file_path = "carpeta\\modulo.js"

    chunks = rag.chunk_python_file(source, file_path)

    assert [chunk.symbol_name for chunk in chunks] == ["window#1"]
    assert [chunk.kind for chunk in chunks] == ["window"]
    assert all(chunk.file_path == file_path for chunk in chunks)
    lines_count = len(line_spans(source))
    assert (chunks[0].start_line, chunks[0].end_line) == (1, lines_count)
    assert chunks[0].content == expected_text(source, 1, lines_count)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, [("window#1", 1, 1)]),
        (59, [("window#1", 1, 59)]),
        (60, [("window#1", 1, 60)]),
        (61, [("window#1", 1, 60), ("window#2", 61, 61)]),
        (120, [("window#1", 1, 60), ("window#2", 61, 120)]),
        (
            121,
            [
                ("window#1", 1, 60),
                ("window#2", 61, 120),
                ("window#3", 121, 121),
            ],
        ),
    ],
)
def test_chunk_python_file_cuts_windows_without_overlap(
    count: int, expected: list[tuple[str, int, int]]
) -> None:
    """Ventanas de 60 líneas: la última puede tener menos, incluso una sola."""
    source = prose_lines(count)

    chunks = rag.chunk_python_file(source, "largo.txt")

    assert module_spans(chunks) == expected
    assert {chunk.kind for chunk in chunks} == {"window"}
    for chunk in chunks:
        assert chunk.content == expected_text(source, chunk.start_line, chunk.end_line)


def test_chunk_python_file_keeps_a_blank_last_window_line() -> None:
    """Si la línea 60 está vacía, la ventana termina en salto de línea (RF-6, RF-9)."""
    source = prose_lines(59) + "\n" + "cierre\n"

    chunks = rag.chunk_python_file(source, "vacio_al_final.txt")

    assert module_spans(chunks) == [
        ("window#1", 1, 60),
        ("window#2", 61, 61),
    ]
    assert chunks[0].content.endswith("\n")
    assert chunks[0].content == expected_text(source, 1, 60)
    assert chunks[1].content == "cierre"


@pytest.mark.parametrize("source", ["", "   ", "\n\n", " \t\n \n", "\r\n\r\n"])
def test_chunk_python_file_returns_nothing_for_empty_or_blank_content(
    source: str,
) -> None:
    """Un archivo vacío o solo de blancos no produce fragmentos.

    No es un fallo del troceado: RF-13 es un rechazo de `index_file`, que se
    comprueba antes de trocear. Aquí solo se documenta que no hay fragmentos.
    """
    assert rag.chunk_python_file(source, "vacio.py") == []


def test_chunk_python_file_with_a_single_assignment() -> None:
    """Un archivo de una sola asignación produce un `module` de una línea."""
    chunks = rag.chunk_python_file("TOTAL = 0\n", "config.py")

    assert module_spans(chunks) == [("module", 1, 1)]
    assert chunks[0].kind == "module"
    assert chunks[0].content == "TOTAL = 0"


def test_chunk_python_file_with_a_single_line_without_newline() -> None:
    """Un archivo de una línea sin salto final también se cita entero."""
    chunks = rag.chunk_python_file("TOTAL = 0", "config.py")

    assert module_spans(chunks) == [("module", 1, 1)]
    assert chunks[0].content == "TOTAL = 0"


def test_chunk_python_file_does_not_produce_windows_for_valid_python() -> None:
    """El plan B solo se usa cuando el contenido no se puede analizar."""
    chunks = rag.chunk_python_file(REALISTIC_SOURCE, "ejemplo.py")

    assert {chunk.kind for chunk in chunks} == {"function", "class", "module"}


def test_chunk_python_file_keeps_the_attached_comment_out_of_module() -> None:
    """Un comentario pegado a una función pertenece a la función, no a `module`."""
    chunks = rag.chunk_python_file(REALISTIC_SOURCE, "ejemplo.py")
    modules = [chunk for chunk in chunks if chunk.kind == "module"]
    load_config = next(chunk for chunk in chunks if chunk.symbol_name == "load_config")

    assert load_config.start_line == 10
    assert load_config.content.startswith("# Ajustes de la aplicación")
    assert all("# Ajustes de la aplicación" not in chunk.content for chunk in modules)


def test_chunk_python_file_orders_the_assembled_chunks_by_rf_17() -> None:
    """El ensamblado final aplica línea inicial, fin descendente y símbolo."""
    source = (
        '"""Doc."""\n'  # 1
        "import os\n"  # 2
        "\n"  # 3
        "\n"  # 4
        "class User:\n"  # 5
        "    def login(self):\n"  # 6
        "        return True\n"  # 7
        "\n"  # 8
        "    def logout(self):\n"  # 9
        "        return False\n"  # 10
        "\n"  # 11
        "\n"  # 12
        "def help():\n"  # 13
        "    return 0\n"  # 14
        "\n"  # 15
        "TOTAL = 1\n"  # 16
    )

    chunks = rag.chunk_python_file(source, "orden.py")

    assert module_spans(chunks) == [
        ("module", 1, 2),
        ("User", 5, 10),
        ("User.login", 6, 7),
        ("User.logout", 9, 10),
        ("help", 13, 14),
        ("module", 16, 16),
    ]
    assert chunks == rag._sort_chunks(chunks)
    assert sorted(chunks, key=lambda c: (c.start_line, -c.end_line, c.symbol_name)) == (
        chunks
    )


def test_chunk_python_file_does_not_overlap_symbols_with_module() -> None:
    """Los símbolos se contienen entre sí como mucho, y `module` no los pisa."""
    chunks = rag.chunk_python_file(SYMBOLS_SOURCE + "\nTOTAL = 1\n", "simbolos.py")

    assert_module_chunks_avoid_symbols(chunks)
    assert_symbols_are_nested_or_disjoint(chunks)


def test_chunk_python_file_is_deterministic_and_keeps_the_path() -> None:
    """Dos llamadas dan los mismos fragmentos y la ruta se copia tal cual."""
    file_path = "carpeta\\subcarpeta/modulo.py"

    first = rag.chunk_python_file(REALISTIC_SOURCE, file_path)
    second = rag.chunk_python_file(REALISTIC_SOURCE, file_path)

    assert first == second
    assert all(chunk.file_path == file_path for chunk in first)


COVERAGE_FIXTURES = {
    "symbols": SYMBOLS_SOURCE,
    "conditional": CONDITIONAL_SOURCE,
    "nested_in_functions": NESTED_IN_FUNCTIONS_SOURCE,
    "class_conditional": CLASS_CONDITIONAL_SOURCE,
    "container": CONTAINER_SOURCE,
    "conditional_startup": CONDITIONAL_STARTUP_SOURCE,
    "realistic": REALISTIC_SOURCE,
    "decoradores": (
        "# uno\n# dos\n@decorador(\n    'argumento',\n)\ndef f():\n    pass\n\n\nx = 1\n"
    ),
    "cadena_triple": 'TEXTO = """inicio\n# linea dentro de la cadena"""\ndef f():\n    pass\n',
    "solo_docstring": '"""Solo documentación."""\n',
    "solo_comentarios": "# solo comentarios\n# y más\n",
    "import_suelto": "import os\n\ndef f():\n    return 1\n\nimport sys\n",
    "blancos_en_bordes": "\n\nCONSTANTE = 1\n\n\n",
    "bloques_partidos": (
        assignments(121, "PRIMERO")
        + "def f():\n    return 1\n"
        + assignments(121, "SEGUNDO")
    ),
    "prosa": "esto no es Python\n",
    "javascript": "function f(){}\n",
    "roto": "def f(:\n    pass\n",
    "indentado": "    def f():\n        pass\n",
    "una_linea": "TOTAL = 0",
    "crlf": "import os\r\n\r\nx = 1\r\n",
    "formfeed": "antes\fdentro\nx = 1\n",
}


@pytest.mark.parametrize(
    "source", list(COVERAGE_FIXTURES.values()), ids=list(COVERAGE_FIXTURES)
)
def test_chunk_python_file_covers_every_code_line_of_the_fixtures(
    source: str,
) -> None:
    """Toda línea con código del fixture pertenece a algún fragmento (RF-7)."""
    chunks = rag.chunk_python_file(source, "fixture.py")

    assert chunks
    assert_every_code_line_is_covered(source, chunks)
    for chunk in chunks:
        assert chunk.content == expected_text(source, chunk.start_line, chunk.end_line)


@pytest.mark.parametrize("name", ["rag.py", "storage.py"])
def test_chunk_python_file_covers_the_project_code(name: str) -> None:
    """RF-7 también sobre código real del proyecto, leído como texto."""
    source = (PROJECT_ROOT / "app" / name).read_text(encoding="utf-8")

    chunks = rag.chunk_python_file(source, f"app/{name}")

    checked = assert_every_code_line_is_covered(source, chunks)
    assert checked > 50
    assert all(chunk.kind != "window" for chunk in chunks)
    assert_module_chunks_avoid_symbols(chunks)
    assert_symbols_are_nested_or_disjoint(chunks)
    for chunk in chunks:
        assert chunk.content == expected_text(source, chunk.start_line, chunk.end_line)


# --- Casos límite que cierra T10 ------------------------------------------


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("def only():\n    return 1\n", "function"),
        ("async def only():\n    return 1\n", "function"),
    ],
    ids=["function", "async_function"],
)
def test_chunk_python_file_with_only_one_function_produces_a_single_chunk(
    source: str, kind: str
) -> None:
    """Una única función sin código de módulo produce un solo fragmento (RF-2).

    Cubre también que una función asíncrona se indexa con `kind="function"`.
    """
    chunks = rag.chunk_python_file(source, "unica.py")

    assert module_spans(chunks) == [("only", 1, 2)]
    assert chunks[0].kind == kind


def test_chunk_python_file_with_a_class_without_methods() -> None:
    """Una clase sin métodos produce un solo fragmento y ningún método (RF-2)."""
    source = "class Empty:\n    value = 1\n"

    chunks = rag.chunk_python_file(source, "vacia.py")

    assert module_spans(chunks) == [("Empty", 1, 2)]
    assert chunks[0].kind == "class"


@pytest.mark.parametrize(
    ("newline", "path"),
    [("\r\n", "windows.py"), ("\r", "mac.py")],
    ids=["crlf", "cr"],
)
def test_chunk_python_file_numbers_lines_with_windows_and_mac_endings(
    newline: str, path: str
) -> None:
    """Con `\\r\\n` y `\\r` la numeración sigue coincidiendo con el archivo (RF-6)."""
    source = f"import os{newline}{newline}def f():{newline}    return 1{newline}"

    chunks = rag.chunk_python_file(source, path)

    assert module_spans(chunks) == [
        ("module", 1, 1),
        ("f", 3, 4),
    ]
    for chunk in chunks:
        assert chunk.content == expected_text(source, chunk.start_line, chunk.end_line)


def test_chunk_python_file_keeps_a_detached_comment_in_the_module_block() -> None:
    """Un comentario separado por una línea en blanco no entra en la función (RF-3)."""
    source = "# suelto\n\ndef f():\n    pass\n"

    chunks = rag.chunk_python_file(source, "comentario.py")

    assert module_spans(chunks) == [
        ("module", 1, 1),
        ("f", 3, 4),
    ]
    assert chunks[0].content == "# suelto"
    assert "# suelto" not in chunks[1].content


def test_chunk_python_file_keeps_a_very_long_line_whole() -> None:
    """Una línea muy larga no se recorta ni se parte por caracteres (RF-6).

    El texto citado debe seguir cuadrando con lo que se ve al abrir el archivo:
    el fragmento conserva la línea entera, aunque supere con creces el ancho de
    una pantalla.
    """
    expression = "valor = " + " + ".join(["1"] * 500)
    source = f"def f():\n    {expression}\n"

    chunks = rag.chunk_python_file(source, "larga.py")

    assert len(expression) > 1_000
    assert module_spans(chunks) == [("f", 1, 2)]
    assert chunks[0].content == expected_text(source, 1, 2)
    assert chunks[0].content.count("\n") == 1
    assert expression in chunks[0].content
    assert len(chunks[0].content) == len(source) - 1


def test_a_nested_function_stays_inside_its_container_fragment() -> None:
    """La función anidada no genera fragmento, pero su texto no se pierde (RF-2)."""
    source = "def outer():\n    def inner():\n        return 1\n    return inner\n"

    chunks = rag.chunk_python_file(source, "anidada.py")

    assert module_spans(chunks) == [("outer", 1, 4)]
    assert "def inner():" in chunks[0].content
    assert "return inner" in chunks[0].content
    assert chunks[0].content == expected_text(source, 1, 4)
