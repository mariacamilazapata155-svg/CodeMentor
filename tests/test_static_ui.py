"""Pruebas del servicio de la interfaz: `/`, `/static/*` y `/favicon.ico`.

Comprueban que la página, sus recursos y el icono se sirven sin clave ni
modelo, que el 404 estático conserva el formato `{message, reason}` de la
spec 004 y que las rutas de la API y su documentación no cambian (RF-1, RF-2,
RF-32, RNF-1, RNF-9). También incluyen guardas de estructura del HTML (RF-3,
RF-4, RF-5, RF-26, RF-30, RF-31, RNF-3, RNF-5), de la hoja de estilos
(RNF-3, RNF-4, RNF-10) y del script de la interfaz (RF-7, RF-15, RF-16, RF-18,
RF-28, RF-29, RF-30, RF-32, RNF-2), del render seguro de mensajes y citas
(RF-19, RF-20, RF-21, RF-27, RF-28, RF-32) y del flujo de chat (RF-14 a RF-26,
RF-33, RF-34). No ejecutan JavaScript, no abren red y no cargan el modelo: usan
`TestClient(main.app)` sin `with`, así que el `lifespan` no se ejecuta.
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from app import bot, main, rag
from app.models import ApiReason

#: Directorio de los recursos estáticos, resuelto desde este archivo.
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

#: Marcas mínimas de la página en español (RF-1).
HTML_LANG_MARKER = 'lang="es"'
HTML_H1_MARKER = "<h1"

#: Tipos MIME que el navegador acepta para un script (T0 observó `text/javascript`).
JAVASCRIPT_TYPES = frozenset({"text/javascript", "application/javascript"})

#: Claves exactas del cuerpo de error de la spec 004 (RF-14 de la 004).
ERROR_KEYS = {"message", "reason"}


def _client() -> TestClient:
    """Crea un cliente sin `with`: no ejecuta el `lifespan` ni carga el modelo."""
    return TestClient(main.app)


def _media_type(response: Response) -> str:
    """Devuelve el tipo MIME sin parámetros ni espacios."""
    return response.headers["content-type"].split(";", 1)[0].strip().lower()


def _assert_error(
    response: Response,
    status: int,
    reason: ApiReason,
    message: str,
) -> None:
    """Comprueba estado, formato de error y ausencia de la clave `detail`."""
    assert response.status_code == status
    assert _media_type(response) == "application/json"

    body = response.json()

    assert set(body) == ERROR_KEYS
    assert "detail" not in body
    assert body["reason"] == reason.value
    assert body["message"] == message


# --- Página y recursos propios (RF-1, RF-2 y RF-32) -------------------------


def test_root_serves_the_spanish_page() -> None:
    """`GET /` responde 200 con HTML en español, un `h1` y la raíz declarada."""
    response = _client().get("/")

    assert response.status_code == 200
    assert _media_type(response) == "text/html"
    assert HTML_LANG_MARKER in response.text
    assert HTML_H1_MARKER in response.text


def test_static_css_is_served() -> None:
    """`/static/style.css` responde 200 con tipo CSS."""
    response = _client().get("/static/style.css")

    assert response.status_code == 200
    assert _media_type(response) == "text/css"


def test_static_javascript_is_served() -> None:
    """`/static/app.js` responde 200 con un tipo MIME de JavaScript."""
    response = _client().get("/static/app.js")

    assert response.status_code == 200
    assert _media_type(response) in JAVASCRIPT_TYPES


def test_static_favicon_is_served() -> None:
    """`/static/favicon.svg` responde 200 como SVG."""
    response = _client().get("/static/favicon.svg")

    assert response.status_code == 200
    assert _media_type(response) == "image/svg+xml"


def test_favicon_ico_serves_the_same_svg() -> None:
    """`GET /favicon.ico` responde 200 con el mismo SVG que el recurso."""
    response = _client().get("/favicon.ico")

    assert response.status_code == 200
    assert _media_type(response) == "image/svg+xml"
    assert response.content == (STATIC_DIR / "favicon.svg").read_bytes()


# --- Errores y rutas de la API intactas (RF-14 de la 004, RNF-9) -----------


def test_missing_static_resource_keeps_the_004_error_format() -> None:
    """Un estático inexistente da 404 `not_found` con el formato de la 004."""
    _assert_error(
        _client().get("/static/no-existe.css"),
        404,
        ApiReason.NOT_FOUND,
        main.MSG_NOT_FOUND,
    )


def test_unknown_route_still_returns_not_found() -> None:
    """`/no-existe` sigue dando 404 `not_found` con el formato de la 004."""
    _assert_error(
        _client().get("/no-existe"),
        404,
        ApiReason.NOT_FOUND,
        main.MSG_NOT_FOUND,
    )


def test_health_still_returns_ok() -> None:
    """`/health` responde 200 `{"status": "ok"}` pese al montaje estático."""
    response = _client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_on_upload_still_returns_method_not_allowed() -> None:
    """`GET /upload` sigue respondiendo 405 con el formato de la 004."""
    _assert_error(
        _client().get("/upload"),
        405,
        ApiReason.METHOD_NOT_ALLOWED,
        main.MSG_METHOD_NOT_ALLOWED,
    )


def test_chat_with_empty_body_returns_invalid_request() -> None:
    """`POST /chat` con un cuerpo vacío sigue respondiendo 422 `invalid_request`."""
    response = _client().post(
        "/chat",
        content=b"",
        headers={"Content-Type": "application/json"},
    )

    _assert_error(
        response,
        422,
        ApiReason.INVALID_REQUEST,
        main.MSG_INVALID_REQUEST,
    )


def test_openapi_documents_only_the_three_api_routes() -> None:
    """`/openapi.json` mantiene las tres rutas y no documenta las de interfaz."""
    response = _client().get("/openapi.json")

    assert response.status_code == 200
    paths = set(response.json()["paths"])

    assert paths == {"/health", "/upload", "/chat"}
    assert "/" not in paths
    assert "/favicon.ico" not in paths
    assert not any(path.startswith("/static") for path in paths)


# --- `/` sin clave, sin modelo y sin tocar el índice (RF-1) ----------------


@pytest.fixture
def fail_startup(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hace fallar cualquier intento de cargar entorno, modelo o cliente."""

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("GET / no debe cargar el entorno ni el modelo")

    monkeypatch.setattr(main, "_load_env", fail)
    monkeypatch.setattr(rag, "warm_up", fail)
    monkeypatch.setattr(bot, "_get_client", fail)
    yield


def test_root_does_not_need_key_model_or_index(
    fail_startup: None,
    set_api_key: Callable[[str | None], None],
) -> None:
    """`GET /` responde 200 sin clave, sin modelo y sin modificar el índice."""
    set_api_key(None)
    before = rag.store.count

    response = _client().get("/")

    assert response.status_code == 200
    assert rag.store.count == before


# --- Guardas de fuente del icono (RF-1, RF-2 y RF-32) ----------------------


def test_favicon_svg_is_a_square_svg_without_text() -> None:
    """`static/favicon.svg` existe, es cuadrado, es SVG válido y no lleva texto."""
    path = STATIC_DIR / "favicon.svg"

    assert path.is_file()

    root = ET.parse(path).getroot()

    assert root.tag.endswith("svg")

    view_box = root.get("viewBox")
    assert view_box is not None, "el SVG debe declarar viewBox"
    numbers = view_box.replace(",", " ").split()
    assert len(numbers) == 4, f"viewBox inesperado: {view_box!r}"
    assert float(numbers[2]) == float(numbers[3]), "el viewBox no es cuadrado"

    width = root.get("width")
    height = root.get("height")
    if width is not None or height is not None:
        assert width is not None and height is not None
        assert float(width.removesuffix("px")) == float(height.removesuffix("px"))

    assert not any(
        element.tag.endswith("text") or element.tag.endswith("tspan")
        for element in root.iter()
    )


# --- Guardas de estructura del HTML (RF-2, RF-3, RF-4, RF-5, RF-26, RF-30,
#     RF-31, RNF-3 y RNF-5) ------------------------------------------------

#: Elementos HTML que no tienen contenido ni etiqueta de cierre.
_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _HtmlNode:
    """Nodo mínimo del árbol HTML: etiqueta, atributos y descendientes."""

    def __init__(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        parent: "_HtmlNode | None",
    ) -> None:
        self.tag = tag
        self.attrs = {
            name.lower(): value if value is not None else "" for name, value in attrs
        }
        self.parent = parent
        self.children: list[_HtmlNode] = []
        self.text_parts: list[str] = []


class _PageParser(HTMLParser):
    """Construye un árbol mínimo del HTML usando solo la biblioteca estándar."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("#document", [], None)
        self._stack = [self.root]

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        node = _HtmlNode(tag, attrs, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in _VOID_ELEMENTS:
            self._stack.append(node)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        node = _HtmlNode(tag, attrs, self._stack[-1])
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].text_parts.append(data)


def _index_source() -> str:
    """Devuelve el HTML de la página tal como se sirve."""
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def _page() -> _HtmlNode:
    """Parsea `static/index.html` en un árbol de nodos."""
    parser = _PageParser()
    parser.feed(_index_source())
    parser.close()
    return parser.root


def _iter_nodes(node: _HtmlNode) -> Iterator[_HtmlNode]:
    """Recorre el nodo y todos sus descendientes en orden de documento."""
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


def _by_tag(page: _HtmlNode, tag: str) -> list[_HtmlNode]:
    """Devuelve todos los nodos con la etiqueta dada."""
    return [node for node in _iter_nodes(page) if node.tag == tag]


def _by_id(page: _HtmlNode, ident: str) -> _HtmlNode | None:
    """Devuelve el primer nodo con el `id` dado, o `None`."""
    return next(
        (node for node in _iter_nodes(page) if node.attrs.get("id") == ident),
        None,
    )


def _text(node: _HtmlNode) -> str:
    """Extrae el texto de un nodo y de sus descendientes."""
    parts = list(node.text_parts)
    parts.extend(_text(child) for child in node.children)
    return "".join(parts)


def _normalized_text(node: _HtmlNode) -> str:
    """Extrae el texto con los espacios colapsados para compararlo."""
    return " ".join(_text(node).split())


def _is_descendant(node: _HtmlNode, ancestor: _HtmlNode) -> bool:
    """Indica si `node` está dentro de `ancestor`."""
    current = node.parent
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


def _assert_visible_label(page: _HtmlNode, control_id: str) -> None:
    """Comprueba que el control tiene una única etiqueta visible asociada."""
    labels = [
        node for node in _by_tag(page, "label") if node.attrs.get("for") == control_id
    ]

    assert len(labels) == 1, f"`{control_id}` debe tener una etiqueta `for`"
    assert _normalized_text(labels[0]), f"la etiqueta de `{control_id}` está vacía"


def _described_by(node: _HtmlNode) -> set[str]:
    """Devuelve los `id` asociados con `aria-describedby`."""
    return set(node.attrs.get("aria-describedby", "").split())


def _assert_submit_button(page: _HtmlNode, form: _HtmlNode) -> None:
    """Comprueba que el formulario tiene un botón de envío con texto."""
    buttons = [
        node
        for node in _iter_nodes(form)
        if node.tag == "button" and node.attrs.get("type") == "submit"
    ]

    assert len(buttons) == 1, "el formulario debe tener un único botón de envío"
    assert _normalized_text(buttons[0]), "el botón de envío debe tener texto"


def test_page_has_language_title_and_single_landmarks() -> None:
    """`lang="es"`, título no vacío, un `h1`, un `header` y un `main` (RF-1)."""
    page = _page()

    html_nodes = _by_tag(page, "html")
    assert len(html_nodes) == 1
    assert html_nodes[0].attrs.get("lang") == "es"

    titles = _by_tag(page, "title")
    assert len(titles) == 1
    assert _normalized_text(titles[0]), "el título no puede estar vacío"

    assert len(_by_tag(page, "h1")) == 1
    assert len(_by_tag(page, "header")) == 1
    assert len(_by_tag(page, "main")) == 1


def test_page_has_one_second_level_heading_per_section() -> None:
    """Hay exactamente dos `h2` y ningún salto a `h3`–`h6` (RNF-3)."""
    page = _page()

    assert len(_by_tag(page, "h2")) == 2
    for tag in ("h3", "h4", "h5", "h6"):
        assert not _by_tag(page, tag), f"no puede haber `{tag}` sin nivel previo"


def test_noscript_explains_that_javascript_is_required() -> None:
    """`<noscript>` lleva el texto literal y una indicación de activarlo (RF-4)."""
    noscript = _by_tag(_page(), "noscript")

    assert len(noscript) == 1
    text = _normalized_text(noscript[0])
    assert "Esta interfaz necesita JavaScript para funcionar." in text
    assert re.search(r"act[ií]valo", text, re.IGNORECASE), (
        "el aviso debe indicar que se active JavaScript"
    )


def test_upload_form_has_labeled_single_file_and_optional_path() -> None:
    """El formulario de subida cumple RF-5, RF-6 y RNF-3."""
    page = _page()
    form = _by_id(page, "upload-form")

    assert form is not None and form.tag == "form"

    file_input = _by_id(page, "upload-file")
    assert file_input is not None
    assert file_input.tag == "input"
    assert file_input.attrs.get("type") == "file"
    assert file_input.attrs.get("name") == "file"
    assert file_input.attrs.get("accept") == ".py"
    assert "multiple" not in file_input.attrs
    _assert_visible_label(page, "upload-file")

    path_input = _by_id(page, "upload-path")
    assert path_input is not None
    assert path_input.tag == "input"
    assert path_input.attrs.get("type") == "text"
    assert path_input.attrs.get("name") == "path"
    _assert_visible_label(page, "upload-path")

    help_node = _by_id(page, "upload-help")
    assert help_node is not None
    assert _normalized_text(help_node)
    for control in (file_input, path_input):
        assert {"upload-help", "upload-status"} <= _described_by(control)

    status = _by_id(page, "upload-status")
    assert status is not None
    assert _is_descendant(status, form)

    assert not any("required" in node.attrs for node in _iter_nodes(form)), (
        "el formulario no debe depender de la validación nativa"
    )

    _assert_submit_button(page, form)


def test_upload_status_is_a_polite_live_region() -> None:
    """`#upload-status` anuncia los avisos de subida (RF-10, RF-26, RNF-3)."""
    status = _by_id(_page(), "upload-status")

    assert status is not None
    assert status.attrs.get("role") == "status"
    assert status.attrs.get("aria-live") == "polite"


def test_chat_form_has_labeled_textarea_and_help() -> None:
    """El formulario de pregunta cumple RF-14 y RNF-3."""
    page = _page()
    form = _by_id(page, "chat-form")

    assert form is not None and form.tag == "form"

    textarea = _by_id(page, "chat-question")
    assert textarea is not None
    assert textarea.tag == "textarea"
    assert textarea.attrs.get("name") == "message"
    _assert_visible_label(page, "chat-question")

    help_node = _by_id(page, "chat-help")
    assert help_node is not None
    assert _normalized_text(help_node)
    assert "chat-help" in _described_by(textarea)

    _assert_submit_button(page, form)


def test_chat_log_is_a_named_log_and_placeholder_invites() -> None:
    """La conversación es un registro con nombre y el vacío invita (RF-3, RF-26)."""
    page = _page()

    log = _by_id(page, "chat-log")
    assert log is not None
    assert log.tag == "ol"
    assert log.attrs.get("role") == "log"
    assert log.attrs.get("aria-label", "").strip()

    placeholder = _by_id(page, "chat-placeholder")
    assert placeholder is not None
    text = _normalized_text(placeholder)
    lowered = text.lower()

    assert ".py" in text
    assert "pregunta" in lowered
    assert "vac" not in lowered, "el vacío no debe afirmar nada del índice"
    assert "índice" not in lowered
    assert "indice" not in lowered


def test_page_links_the_served_svg_icon() -> None:
    """El icono apunta al recurso servido, no a una URL externa (RF-1, RF-2)."""
    icons = [
        node
        for node in _by_tag(_page(), "link")
        if "icon" in node.attrs.get("rel", "").split()
    ]

    assert len(icons) == 1
    assert icons[0].attrs.get("href") == "/static/favicon.svg"
    assert icons[0].attrs.get("type") == "image/svg+xml"


def test_page_has_no_inline_styles_or_event_handlers() -> None:
    """El marcado no usa `style=` ni atributos `on*=` (RNF-10)."""
    for node in _iter_nodes(_page()):
        if node.tag == "#document":
            continue
        assert "style" not in node.attrs, f"`<{node.tag}>` lleva `style=`"
        for name in node.attrs:
            assert not name.startswith("on"), f"`<{node.tag}>` lleva `{name}=`"


def test_page_has_no_external_urls_or_inline_scripts() -> None:
    """Todo es del mismo origen y solo se carga `app.js` (RF-2, RF-31)."""
    source = _index_source()

    assert "http://" not in source
    assert "https://" not in source
    assert "innerHTML" not in source

    for node in _iter_nodes(_page()):
        for name, value in node.attrs.items():
            assert not value.startswith("//"), f"`{name}` apunta a otro dominio"

    scripts = _by_tag(_page(), "script")
    assert len(scripts) == 1
    assert scripts[0].attrs.get("src") == "/static/app.js"
    assert "defer" in scripts[0].attrs


def test_page_does_not_call_api_routes_on_load() -> None:
    """Al cargar no se referencia `/upload`, `/chat` ni `/health` (RF-2)."""
    source = _index_source()

    for route in ("/upload", "/chat", "/health"):
        assert route not in source, f"la página no debe referenciar `{route}`"


# --- Guardas de la hoja de estilos (RNF-3, RNF-4, RNF-10) -------------------

#: Valores de los tokens existentes que T3 no puede cambiar (RNF-10).
_EXISTING_CSS_TOKENS = {
    "--color-bg": "#f7f7f8",
    "--color-surface": "#ffffff",
    "--color-text": "#1f2328",
    "--color-text-muted": "#59636e",
    "--color-border": "#d1d9e0",
    "--color-primary": "#2563eb",
    "--color-primary-hover": "#1d4ed8",
    "--color-success": "#1a7f37",
    "--color-danger": "#cf222e",
    "--space-xs": "0.25rem",
    "--space-sm": "0.5rem",
    "--space-md": "1rem",
    "--space-lg": "1.5rem",
    "--space-xl": "2.5rem",
    "--font-size-sm": "0.875rem",
    "--font-size-base": "1rem",
    "--font-size-lg": "1.25rem",
    "--font-size-xl": "1.75rem",
    "--radius-sm": "0.25rem",
    "--radius-md": "0.5rem",
    "--radius-lg": "1rem",
    "--shadow-md": "0 2px 8px rgb(31 35 40 / 10%)",
}

#: Tokens nuevos que T3 fija con valor literal (RNF-3, RNF-4, RNF-10).
_NEW_CSS_TOKENS = {
    "--color-border-strong": "#6e7781",
    "--size-touch": "2.75rem",
    "--border-width": "1px",
    "--focus-width": "2px",
}

#: Tokens de layout que T3 añade sin fijar su valor exacto.
_LAYOUT_CSS_TOKENS = ("--content-max", "--panel-width")

#: Tokens tipográficos que el CSS usa y, por tanto, debe declarar.
_TEXT_CSS_TOKENS = (
    "--line-height-base",
    "--line-height-tight",
    "--font-weight-regular",
    "--font-weight-semibold",
)

#: Clases BEM que la hoja de estilos debe mantener (RNF-10).
_BEM_CLASSES = (
    ".header__title",
    ".panel__title",
    ".field__label",
    ".message--assistant",
    ".citation__lines",
)

#: Única condición de media con una longitud literal permitida (RNF-10).
_MEDIA_CONDITION = "@media (min-width: 60rem)"

_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_CSS_ROOT_RE = re.compile(r":root\s*\{(?P<body>[^}]*)\}")
_CSS_BLOCK_RE = re.compile(r"(?P<selector>[^{}]+)\{(?P<body>[^{}]*)\}")
_CSS_TOKEN_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
_CSS_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
_CSS_LENGTH_RE = re.compile(
    r"(?<![\w-])(?:\d+(?:\.\d+)?|\.\d+)(?:px|rem|em|pt)\b",
)
_CSS_TEXT_METRIC_RE = re.compile(
    r"(?<![\w-])(font-size|font-weight|line-height)\s*:\s*([^;{}]+);",
)
_CSS_OUTLINE_NONE_RE = re.compile(r"outline\s*:\s*(?:none|0)\b")
_CSS_ORDER_RE = re.compile(r"(?<![\w-])order\s*:")


def _css_source() -> str:
    """Devuelve la hoja de estilos tal como se sirve."""
    return (STATIC_DIR / "style.css").read_text(encoding="utf-8")


def _strip_css_comments(source: str) -> str:
    """Quita los comentarios para que sus textos no cuenten como código."""
    return _CSS_COMMENT_RE.sub("", source)


def _root_tokens() -> dict[str, str]:
    """Devuelve los tokens declarados en el bloque `:root`."""
    match = _CSS_ROOT_RE.search(_strip_css_comments(_css_source()))
    assert match is not None, "style.css debe declarar un bloque `:root`"
    return {
        name: value.strip()
        for name, value in _CSS_TOKEN_RE.findall(match.group("body"))
    }


def _css_without_root() -> str:
    """Devuelve el CSS sin el bloque `:root` ni la condición `@media`."""
    source = _strip_css_comments(_css_source())
    match = _CSS_ROOT_RE.search(source)
    assert match is not None, "style.css debe declarar un bloque `:root`"
    rest = source[: match.start()] + source[match.end() :]
    return rest.replace(_MEDIA_CONDITION, "")


def _css_blocks(source: str) -> list[tuple[str, str]]:
    """Devuelve los pares selector/declaraciones de la hoja de estilos."""
    return [
        (match.group("selector").strip(), match.group("body"))
        for match in _CSS_BLOCK_RE.finditer(_strip_css_comments(source))
    ]


def _media_query_body(condition: str) -> str | None:
    """Devuelve el cuerpo de una condición `@media`, contando llaves anidadas."""
    source = _strip_css_comments(_css_source())
    start = source.find(condition)

    if start == -1:
        return None

    opening = source.find("{", start)

    if opening == -1:
        return None

    depth = 0

    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1

            if depth == 0:
                return source[opening + 1 : index]

    return None


def _css_declaration(body: str, prop: str) -> str | None:
    """Devuelve el valor de una propiedad dentro de un bloque de declaraciones."""
    match = re.search(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;]+);", body)
    return match.group(1).strip() if match else None


def test_css_has_no_imports_or_external_urls() -> None:
    """La hoja no importa ni descarga nada (RNF-1, RNF-10)."""
    source = _strip_css_comments(_css_source())

    assert "@import" not in source
    assert "url(" not in source
    assert "http://" not in source
    assert "https://" not in source


def test_css_root_declares_new_tokens_and_keeps_the_existing_ones() -> None:
    """`:root` conserva los tokens y añade los de T3 (RNF-3, RNF-4)."""
    tokens = _root_tokens()

    for name, value in _EXISTING_CSS_TOKENS.items():
        assert tokens.get(name) == value, f"`{name}` cambió de valor"

    for name, value in _NEW_CSS_TOKENS.items():
        assert tokens.get(name) == value, f"falta o cambió `{name}`"

    for name in (*_LAYOUT_CSS_TOKENS, *_TEXT_CSS_TOKENS):
        assert tokens.get(name), f"falta el token `{name}`"


def test_css_uses_no_literal_colors_or_lengths_outside_root() -> None:
    """Fuera de `:root` solo hay variables, salvo la condición `@media`."""
    rest = _css_without_root()

    colors = _CSS_COLOR_RE.findall(rest)
    lengths = _CSS_LENGTH_RE.findall(rest)

    assert not colors, f"colores literales fuera de `:root`: {colors}"
    assert not lengths, f"longitudes con unidad fuera de `:root`: {lengths}"


def test_css_text_metrics_use_variables() -> None:
    """Tamaños, pesos e interlineados salen de variables (RNF-10)."""
    declarations = _CSS_TEXT_METRIC_RE.findall(_strip_css_comments(_css_source()))

    assert declarations, "el CSS debe declarar métricas de texto"

    for prop, value in declarations:
        assert value.strip().startswith("var("), (
            f"`{prop}: {value.strip()}` debe usar una variable"
        )


def test_css_field_borders_use_the_strong_color() -> None:
    """Los bordes de campo usan `--color-border-strong` (RNF-3, 1.4.11)."""
    borders = [
        declaration.strip()
        for selector, body in _css_blocks(_css_source())
        if ".field__input" in selector
        for declaration in body.split(";")
        if declaration.strip().startswith("border:")
    ]

    assert borders, "`.field__input` debe declarar un borde"
    assert all("var(--color-border-strong)" in border for border in borders), (
        "los bordes de campo deben usar `--color-border-strong`"
    )


def test_css_focus_uses_the_focus_width_and_never_removes_the_outline() -> None:
    """Todos los enfocables muestran un contorno visible (RNF-3, 2.4.7)."""
    source = _strip_css_comments(_css_source())

    assert not _CSS_OUTLINE_NONE_RE.search(source), "no se puede quitar el foco"

    focus_blocks = [
        body for selector, body in _css_blocks(source) if ":focus-visible" in selector
    ]

    assert focus_blocks, "falta una regla `:focus-visible`"
    assert any("outline: var(--focus-width)" in body for body in focus_blocks), (
        "el contorno de foco debe usar `--focus-width`"
    )


def test_css_keeps_the_bem_class_names() -> None:
    """Las clases siguen la nomenclatura BEM del plan (RNF-10)."""
    source = _strip_css_comments(_css_source())

    for class_name in _BEM_CLASSES:
        assert class_name in source, f"falta la clase `{class_name}`"


def test_css_layout_is_one_column_in_document_order() -> None:
    """El layout base es de una columna y respeta el orden del DOM (RNF-4)."""
    main_blocks = [
        body for selector, body in _css_blocks(_css_source()) if selector == ".main"
    ]

    assert main_blocks, "falta el estilo base de `.main`"
    main_body = main_blocks[0]

    assert "display: grid" in main_body or "display: flex" in main_body

    if "display: flex" in main_body:
        assert "flex-direction: column" in main_body

    assert not _CSS_ORDER_RE.search(_strip_css_comments(_css_source())), (
        "el CSS no debe reordenar las secciones respecto al DOM"
    )


# --- Guardas del script de la interfaz (RF-7, RF-15, RF-16, RF-18, RF-28,
#     RF-29, RF-30, RF-32 y RNF-2) ------------------------------------------

#: APIs y patrones prohibidos en el script (RF-28, RF-30, RF-32).
_FORBIDDEN_JS_MARKERS = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "eval(",
    "new Function",
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "document.write",
    "console.",
)

#: Lecturas del contenido del archivo elegido (RF-29).
_FORBIDDEN_FILE_READS = ("FileReader", "file.text(", "file.arrayBuffer(")

#: Constantes de transporte que fija el plan (RF-16, RF-18, RF-34).
_JS_CONSTANTS = {
    "MAX_QUESTION_CODE_POINTS": "1000",
    "MAX_HISTORY_MESSAGES": "10",
    "MAX_HISTORY_CONTENT_CODE_POINTS": "4000",
    "MAX_CHAT_BODY_BYTES": "200000",
    "REQUEST_TIMEOUT_MS": "75000",
}

#: Textos propios del flujo de subida, literales del plan (RNF-5).
_UPLOAD_JS_MESSAGES = {
    "MSG_UPLOAD_NO_FILE": "Elige un archivo .py antes de subir.",
    "MSG_UPLOAD_EXTENSION": (
        "Solo se aceptan archivos de Python (.py). "
        "Revisa el nombre del archivo o la ruta."
    ),
    "MSG_UPLOAD_LOADING": "Indexando el archivo…",
    "MSG_UPLOAD_FAILED": "No se pudo completar la subida. Inténtalo de nuevo.",
    "MSG_TIMEOUT": "No se recibió respuesta a tiempo. Inténtalo de nuevo.",
    "PREFIX_ERROR": "Error: ",
}

#: Etiquetas del resultado de subida (RF-10).
_UPLOAD_SUCCESS_LABELS = (
    "Ruta",
    "Fragmentos indexados",
    "Fragmentos en el índice",
)

#: Funciones puras que la superficie congelada debe exponer (RF-7 a RF-24).
_JS_PURE_FUNCTIONS = (
    "effectivePath",
    "isBlank",
    "isPythonPath",
    "countCodePoints",
    "truncateCodePoints",
    "formatLineRange",
    "sortCitations",
    "buildHistory",
    "serializedBytes",
    "fitHistoryToBytes",
    "buildChatBody",
    "parseErrorMessage",
    "isUploadSuccess",
    "isChatSuccess",
    "isChatResult",
    "isCitation",
)

_JS_COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)
_JS_SURFACE_RE = re.compile(
    r"window\.CodeMentor\s*=\s*Object\.freeze\(\{(?P<body>.*?)\}\);",
    re.DOTALL,
)


def _js_source() -> str:
    """Devuelve el script de la interfaz tal como se sirve."""
    return (STATIC_DIR / "app.js").read_text(encoding="utf-8")


def _js_without_comments() -> str:
    """Quita los comentarios para que sus textos no cuenten como código."""
    return _JS_COMMENT_RE.sub("", _js_source())


def _js_function_body(name: str) -> str:
    """Devuelve el cuerpo de una función declarada, con llaves equilibradas."""
    source = _js_without_comments()
    match = re.search(rf"\bfunction\s+{name}\s*\([^)]*\)\s*\{{", source)

    assert match is not None, f"falta la función `{name}`"

    start = match.end()
    depth = 1

    for index in range(start, len(source)):
        character = source[index]

        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[start:index]

    raise AssertionError(f"la función `{name}` no cierra sus llaves")


def test_app_js_has_no_unsafe_apis() -> None:
    """El script no usa marcado dinámico, almacenamiento ni registro (RF-28, RF-30, RF-32)."""
    source = _js_without_comments()

    for marker in _FORBIDDEN_JS_MARKERS:
        assert marker not in source, f"`app.js` no puede usar `{marker}`"


def test_app_js_does_not_read_the_selected_file() -> None:
    """El script no inspecciona el contenido del archivo elegido (RF-29)."""
    source = _js_without_comments()

    for marker in _FORBIDDEN_FILE_READS:
        assert marker not in source, f"`app.js` no puede usar `{marker}`"


def test_app_js_declares_the_transport_constants() -> None:
    """El script declara las cinco constantes con sus valores (RF-16, RF-18)."""
    source = _js_without_comments()

    for name, value in _JS_CONSTANTS.items():
        pattern = rf"\bconst\s+{name}\s*=\s*{value}\s*;"
        assert re.search(pattern, source), f"falta `const {name} = {value};`"


def test_app_js_exposes_only_the_frozen_pure_surface() -> None:
    """`window.CodeMentor` congela solo las funciones puras y las constantes (RNF-2)."""
    match = _JS_SURFACE_RE.search(_js_without_comments())

    assert match is not None, "falta `window.CodeMentor = Object.freeze({ ... });`"

    keys = {
        item.strip()
        for item in match.group("body").split(",")
        if item.strip()
    }

    assert keys == set(_JS_PURE_FUNCTIONS) | set(_JS_CONSTANTS), (
        "la superficie debe exponer solo las funciones puras y las constantes"
    )


# --- Guardas del flujo de subida (RF-6 a RF-13, RF-29, RF-33, RF-34 y
#     RNF-5) ----------------------------------------------------------------


def test_app_js_declares_the_upload_messages() -> None:
    """Los avisos de subida son los textos literales del plan (RNF-5)."""
    source = _js_without_comments()

    for name, value in _UPLOAD_JS_MESSAGES.items():
        pattern = rf'\bconst\s+{name}\s*=\s*"{re.escape(value)}"\s*;'
        assert re.search(pattern, source), f"falta o cambió `{name}`"


def test_app_js_wires_the_upload_form_on_start() -> None:
    """`init()` enlaza el envío del formulario y no hace peticiones (RF-2)."""
    body = _js_function_body("init")

    assert re.search(r'addEventListener\("submit",\s*handleUpload\)', body), (
        "`init()` debe enlazar `handleUpload` con el formulario de subida"
    )
    assert "fetch(" not in body, "`init()` no puede iniciar peticiones"


def test_app_js_validates_file_and_extension_before_uploading() -> None:
    """Sin archivo o con extensión no válida no se envía nada (RF-6, RF-7)."""
    body = _js_function_body("handleUpload")

    no_file = body.index("MSG_UPLOAD_NO_FILE")
    extension = body.index("MSG_UPLOAD_EXTENSION")
    send = body.index('request("/upload"')

    assert no_file < extension < send, (
        "las validaciones locales deben ejecutarse antes de la petición"
    )
    assert "effectivePath(" in body, "la extensión se comprueba sobre la ruta efectiva"
    assert "isPythonPath(" in body


def test_app_js_sends_multipart_with_an_optional_path() -> None:
    """`FormData` lleva `file` y `path` solo si el campo tiene texto (RF-8)."""
    body = _js_function_body("handleUpload")

    assert "new FormData()" in body
    assert re.search(r'body\.append\("file",\s*file\)', body)
    assert re.search(
        r'if\s*\(elements\.uploadPath\.value\.length\s*>\s*0\)\s*'
        r'\{\s*body\.append\("path",\s*elements\.uploadPath\.value\)',
        body,
    ), "`path` solo debe añadirse si el campo tiene al menos un carácter"
    assert "Content-Type" not in body, "el navegador fija el `boundary` y la longitud"


def test_app_js_guards_against_double_upload_and_rehabilitates() -> None:
    """Un doble envío no duplica la petición y el botón se recupera (RF-9)."""
    body = _js_function_body("handleUpload")

    assert re.search(r'if\s*\(state\.uploading\)', body)
    assert body.index("state.uploading = true") < body.index('request("/upload"')

    finally_block = body[body.index("} finally {") :]
    assert "state.uploading = false" in finally_block
    assert "elements.uploadButton.disabled = false" in finally_block


def test_app_js_request_has_a_timeout_and_distinguishes_failures() -> None:
    """Cada petición se aborta a los 75 s y distingue red de tiempo (RF-34)."""
    body = _js_function_body("request")

    assert "new AbortController()" in body
    assert "setTimeout(" in body and "REQUEST_TIMEOUT_MS" in body
    assert "clearTimeout(" in body
    assert "signal: controller.signal" in body
    assert 'error.name === "AbortError"' in body
    assert "return { timeout: true };" in body
    assert "return { failed: true };" in body


def test_app_js_reads_json_without_throwing() -> None:
    """Un cuerpo vacío, HTML o JSON roto no lanza (RF-12, RF-32)."""
    body = _js_function_body("readJson")

    assert "JSON.parse(await response.text())" in body
    assert "catch" in body


def test_app_js_renders_route_and_counters_only_after_success() -> None:
    """El éxito muestra mensaje, ruta y contadores y vacía los campos (RF-10)."""
    source = _js_without_comments()

    for label in _UPLOAD_SUCCESS_LABELS:
        assert f'"{label}"' in source, f"falta la etiqueta `{label}`"
    assert "used_windows" not in source, "`used_windows` no se muestra por separado"

    body = _js_function_body("handleUpload")
    success = body.index("renderUploadSuccess(data)")

    assert body.index('elements.uploadFile.value = ""') > success, (
        "los campos solo se vacían después del éxito"
    )
    assert body.index('elements.uploadPath.value = ""') > success
    assert body.index('showUploadError(MSG_UPLOAD_EXTENSION)') < success


def test_app_js_keeps_both_forms_usable_during_upload() -> None:
    """Durante la subida solo se deshabilita el botón de subida (RF-33)."""
    body = _js_function_body("handleUpload")

    assert not re.search(r"upload(File|Path)\.disabled", body)
    assert "/chat" not in body, "el flujo de subida no toca la conversación"


# --- Guardas del render seguro de mensajes y citas (RF-19, RF-20, RF-21,
#     RF-27, RF-28 y RF-32) ------------------------------------------------


def test_app_js_renders_messages_as_list_items_with_text_content() -> None:
    """Cada mensaje es un `<li>` con rol y texto literal (RF-27, RF-28)."""
    body = _js_function_body("appendMessage")
    source = _js_without_comments()

    assert 'document.createElement("li")' in body
    assert "elements.chatLog.append(" in body
    assert "message message--" in body
    assert 'document.createElement("p")' in body
    assert "message__text" in body
    assert "textContent = text" in body
    assert "innerHTML" not in body
    assert '"Tú"' in source and '"Asistente"' in source


def test_app_js_presents_sorted_citations_inside_the_answer() -> None:
    """La respuesta se pinta literal y sus citas van dentro del `<li>` (RF-19, RF-21)."""
    body = _js_function_body("appendAnswer")

    assert 'appendMessage("assistant", reply)' in body
    assert "citations.length > 0" in body
    assert "sortCitations(citations)" in body
    assert "item.append(appendCitationList(" in body
    assert "elements.chatLog.append(" not in body, (
        "las citas no pueden ser hermanas del mensaje"
    )
    assert "replace(" not in body, "las marcas `[Fn]` no se reescriben"
    assert "state.exchanges" not in body, "el render no altera el historial"


def test_app_js_renders_each_citation_complete_and_in_order() -> None:
    """Cada cita lleva número, ruta, símbolo y líneas completos (RF-20, RF-27)."""
    body = _js_function_body("appendCitationList")

    assert 'document.createElement("ol")' in body
    assert 'list.className = "citations"' in body
    assert 'list.setAttribute("aria-label", "Citas de la respuesta")' in body

    for field in ("citation.number", "citation.file_path", "citation.symbol_name"):
        assert field in body, f"falta mostrar `{field}`"

    assert "formatLineRange(citation.start_line, citation.end_line)" in body

    for class_name in (
        "citation__number",
        "citation__path",
        "citation__symbol",
        "citation__lines",
    ):
        assert class_name in body, f"falta la clase `{class_name}`"

    assert "truncateCodePoints" not in body, "los valores se muestran completos"
    assert "elements.chatLog.append(" not in body, (
        "el `<ol>` de citas se anida en el `<li>` del mensaje"
    )


def test_app_js_keeps_every_chat_log_child_a_list_item() -> None:
    """Todos los hijos directos de `#chat-log` son `<li>` (RF-19, RF-26, RF-32)."""
    for name in (
        "appendMessage",
        "appendStatus",
        "appendNotice",
        "appendError",
        "appendEmptyIndex",
    ):
        body = _js_function_body(name)

        assert 'document.createElement("li")' in body, f"`{name}` debe crear un `<li>`"
        assert "elements.chatLog.append(" in body, (
            f"`{name}` debe añadir su `<li>` al registro"
        )

    citations = _js_function_body("appendCitationList")
    assert "elements.chatLog.append(" not in citations


def test_app_js_renders_empty_index_and_notices_with_their_actions() -> None:
    """`empty_index` y los avisos se pintan como estados propios (RF-22, RF-27)."""
    empty = _js_function_body("appendEmptyIndex")

    assert "Sin código indexado" in empty
    assert "Subir un archivo .py" in empty
    assert 'href = "#subida"' in empty
    assert "uploadSection.focus()" in empty
    assert "appendCitationList" not in empty
    assert "state.exchanges" not in empty

    notice = _js_function_body("appendNotice")

    assert '"Aviso"' in notice
    assert "textContent = reply" in notice
    assert "appendCitationList" not in notice

    error = _js_function_body("appendError")

    assert "PREFIX_ERROR" in error
    assert "message message--error" in error


def test_app_js_render_helpers_do_not_mutate_state_or_call_the_api() -> None:
    """El render puro no toca el historial, la red ni el reloj (RNF-2)."""
    for name in (
        "appendMessage",
        "appendAnswer",
        "appendCitationList",
        "appendStatus",
        "appendNotice",
        "appendError",
        "appendEmptyIndex",
    ):
        body = _js_function_body(name)

        assert "state.exchanges" not in body, f"`{name}` no puede mutar el historial"
        assert "fetch(" not in body, f"`{name}` no puede iniciar peticiones"
        assert "Date" not in body and "setTimeout(" not in body


def test_css_preserves_newlines_and_wraps_long_citation_values() -> None:
    """El texto conserva saltos y las citas largas se ajustan (RF-20, RF-27)."""
    blocks = _css_blocks(_css_source())

    text_blocks = [body for selector, body in blocks if ".message__text" in selector]
    assert text_blocks, "falta el estilo de `.message__text`"

    for body in text_blocks:
        assert "white-space: pre-wrap" in body, "se deben conservar los saltos de línea"
        assert "overflow-wrap: anywhere" in body

    for name in (".citation__path", ".citation__symbol", ".citation__lines"):
        bodies = [body for selector, body in blocks if name in selector]

        assert bodies, f"falta el estilo de `{name}`"
        assert all("overflow-wrap: anywhere" in body for body in bodies), (
            f"`{name}` debe ajustarse en varias líneas"
        )


# --- Guardas del flujo de chat (RF-14 a RF-26, RF-33 y RF-34) --------------

#: Textos propios del flujo de chat, literales del plan (RNF-5).
_CHAT_JS_MESSAGES = {
    "MSG_QUESTION_EMPTY": "Escribe una pregunta antes de enviar.",
    "MSG_QUESTION_TOO_LONG": "La pregunta no puede tener más de 1.000 caracteres.",
    "MSG_CHAT_LOADING": "Buscando en el código…",
    "MSG_CHAT_FAILED": "No se pudo obtener la respuesta. Inténtalo de nuevo.",
}


def test_app_js_declares_the_chat_messages() -> None:
    """Los textos del chat son los literales del plan (RNF-5)."""
    source = _js_without_comments()

    for name, value in _CHAT_JS_MESSAGES.items():
        pattern = rf'\bconst\s+{name}\s*=\s*"{re.escape(value)}"\s*;'
        assert re.search(pattern, source), f"falta o cambió `{name}`"


def test_app_js_keeps_the_chat_state_in_memory_only() -> None:
    """El estado guarda los intercambios y la marca de envío (RF-17, RF-18, RF-30)."""
    source = _js_without_comments()
    match = re.search(r"const\s+state\s*=\s*\{(?P<body>[^}]*)\}", source)

    assert match is not None, "falta el objeto `state`"

    declared = match.group("body")

    assert re.search(r"exchanges:\s*\[\]", declared), "falta `exchanges: []`"
    assert re.search(r"sending:\s*false", declared), "falta `sending: false`"
    assert re.search(r"uploading:\s*false", declared), "falta `uploading: false`"

    for marker in ("localStorage", "sessionStorage", "indexedDB"):
        assert marker not in source, f"el estado no puede persistirse (`{marker}`)"


def test_app_js_sends_with_enter_but_never_with_shift_or_ime() -> None:
    """Enter envía, Shift+Enter salta y una composición no envía (RF-14)."""
    body = _js_function_body("onQuestionKeyDown")

    assert 'event.key === "Enter"' in body
    assert "!event.shiftKey" in body
    assert "event.isComposing" in body
    assert "event.keyCode === 229" in body
    assert "event.preventDefault()" in body
    assert "handleSend(event)" in body

    assert body.index("event.isComposing") < body.index("event.preventDefault()"), (
        "no se puede enviar mientras el método de entrada compone"
    )
    assert body.index("event.preventDefault()") < body.index("handleSend(event)")


def test_app_js_wires_the_chat_form_and_its_keys_on_start() -> None:
    """`init()` enlaza el envío y las teclas del chat sin hacer peticiones (RF-2, RF-14)."""
    body = _js_function_body("init")

    assert re.search(r'addEventListener\("submit",\s*handleSend\)', body), (
        "`init()` debe enlazar `handleSend` con el formulario de pregunta"
    )
    assert re.search(r'addEventListener\("keydown",\s*onQuestionKeyDown\)', body), (
        "`init()` debe interceptar el Enter de la pregunta"
    )

    for ident in (
        "chat-form",
        "chat-question",
        "chat-submit",
        "chat-log",
        "chat-placeholder",
    ):
        assert ident in body, f"`init()` debe resolver `{ident}`"

    assert "fetch(" not in body, "`init()` no puede iniciar peticiones"


def test_app_js_validates_blank_and_long_questions_before_sending() -> None:
    """Una pregunta vacía o de más de 1.000 puntos no se envía (RF-15, RF-16)."""
    body = _js_function_body("handleSend")

    empty = body.index("MSG_QUESTION_EMPTY")
    too_long = body.index("MSG_QUESTION_TOO_LONG")
    send = body.index('request("/chat"')

    assert empty < too_long < send, (
        "las validaciones locales deben ejecutarse antes de la petición"
    )
    assert "isBlank(question)" in body
    assert re.search(
        r"countCodePoints\(question\)\s*>\s*MAX_QUESTION_CODE_POINTS",
        body,
    ), "el límite se cuenta por puntos de código Unicode"


def test_app_js_shows_the_question_before_waiting_and_keeps_the_field_editable() -> None:
    """La pregunta se pinta, el campo se vacía y sigue editable (RF-17, RF-25, RF-33)."""
    body = _js_function_body("handleSend")

    assert "hidePlaceholder()" in body

    shown = body.index('appendMessage("user", question)')
    cleared = body.index('elements.chatQuestion.value = ""')
    sent = body.index('request("/chat"')

    assert shown < cleared < sent, (
        "la pregunta se pinta y el campo se vacía antes de esperar la respuesta"
    )

    assert re.search(r"if\s*\(state\.sending\)", body), "falta la guarda de doble envío"
    assert body.index("state.sending = true") < sent
    assert "elements.chatButton.disabled = true" in body
    assert not re.search(r"chatQuestion\.disabled", body), (
        "el campo de pregunta nunca se deshabilita"
    )

    finally_block = body[body.index("} finally {") :]

    assert "loading.remove()" in finally_block, "la carga se retira al terminar"
    assert "state.sending = false" in finally_block
    assert "elements.chatButton.disabled = false" in finally_block


def test_app_js_builds_the_history_payload_for_every_question() -> None:
    """El cuerpo lleva `message` e `history` siempre presente (RF-17, RF-18)."""
    body = _js_function_body("handleSend")

    assert re.search(
        r"fitHistoryToBytes\(\s*question,\s*buildHistory\(state\.exchanges\),\s*"
        r"MAX_CHAT_BODY_BYTES,?\s*\)",
        body,
    ), "el historial se ajusta a los 200.000 bytes antes de enviarse"
    assert "buildChatBody(question, history)" in body
    assert 'headers: { "Content-Type": "application/json" }' in body
    assert "JSON.stringify(payload)" in body
    assert body.index("MSG_QUESTION_TOO_LONG") < body.index("buildHistory("), (
        "el historial se construye solo con preguntas válidas"
    )


def test_app_js_branches_the_chat_result_by_reason() -> None:
    """La respuesta se ramifica por `reason` y solo lo fundamentado va al historial (RF-19, RF-22)."""
    body = _js_function_body("handleSend")

    assert "isChatResult(data)" in body

    success = body.index("appendAnswer(data.reply, data.citations)")
    empty = body.index("appendEmptyIndex(data.reply)")
    notice = body.index("appendNotice(data.reply)")

    assert success < empty < notice
    assert body.index('data.reason === "empty_index"') < empty
    assert body.index("data.reason === null") < success

    guard = body.index("data.citations.length > 0")
    push = body.index("state.exchanges.push(")

    assert success < guard < push, (
        "solo los intercambios con citas entran al historial"
    )
    assert "appendCitationList" not in body, (
        "el render de citas vive en `appendAnswer`"
    )


def test_app_js_reports_chat_errors_without_touching_the_history() -> None:
    """Un error de chat muestra su mensaje y no contamina el historial (RF-23, RF-24, RF-34)."""
    body = _js_function_body("handleSend")

    assert "MSG_TIMEOUT" in body
    assert "MSG_CHAT_FAILED" in body
    assert "await readJson(result.response)" in body
    assert "result.response.ok" in body
    assert "parseErrorMessage(data) || MSG_CHAT_FAILED" in body
    assert "catch" in body, "un fallo inesperado no puede escapar (RF-32)"

    errors_block = body[
        body.index("if (!result.response.ok)") : body.index("if (!isChatResult(data))")
    ]

    assert "state.exchanges" not in errors_block, (
        "los errores no se añaden al historial"
    )


def test_app_js_hides_the_placeholder_at_the_first_message() -> None:
    """El estado vacío desaparece al primer mensaje y no vuelve (RF-3, RF-26)."""
    body = _js_function_body("hidePlaceholder")

    assert "elements.chatPlaceholder" in body
    assert "hidden = true" in body


def test_app_js_does_not_move_the_focus_or_reset_the_conversation() -> None:
    """El chat no mueve el foco ni reescribe el registro (RF-25, RF-26)."""
    body = _js_function_body("handleSend")

    assert ".focus(" not in body, "el flujo de chat no mueve el foco"
    assert "replaceChildren(" not in body, "la conversación solo crece al final"
    assert "elements.chatLog" not in body, "el flujo delega el render en los helpers"


# --- Guardas de accesibilidad y anuncios (RF-25, RNF-3 y RNF-7) ------------


def test_chat_log_is_an_explicit_polite_live_region() -> None:
    """La conversación anuncia solo lo que se añade (RNF-3, 4.1.3)."""
    log = _by_id(_page(), "chat-log")

    assert log is not None
    assert log.attrs.get("role") == "log"
    assert log.attrs.get("aria-live") == "polite"
    assert log.attrs.get("aria-relevant") == "additions"
    assert log.attrs.get("aria-label", "").strip()


def test_upload_status_is_an_atomic_live_region() -> None:
    """La zona de subida anuncia el aviso completo (RNF-3, 4.1.3)."""
    status = _by_id(_page(), "upload-status")

    assert status is not None
    assert status.attrs.get("role") == "status"
    assert status.attrs.get("aria-live") == "polite"
    assert status.attrs.get("aria-atomic") == "true"


def test_upload_errors_are_associated_with_the_fields_and_have_own_text() -> None:
    """Los errores de subida se asocian a los campos y llevan texto (RNF-3, 3.3.1)."""
    page = _page()
    status = _by_id(page, "upload-status")
    form = _by_id(page, "upload-form")

    assert status is not None and form is not None
    assert _is_descendant(status, form)

    for control_id in ("upload-file", "upload-path"):
        control = _by_id(page, control_id)
        assert control is not None
        assert {"upload-help", "upload-status"} <= _described_by(control)

    source = _js_without_comments()

    assert 'setUploadNotice("error", PREFIX_ERROR + message)' in source
    assert re.search(r'const\s+PREFIX_ERROR\s*=\s*"Error: "\s*;', source)


def test_every_form_control_has_an_accessible_name() -> None:
    """Los cinco controles exponen un nombre accesible (RNF-3, 4.1.2)."""
    page = _page()

    for control_id in ("upload-file", "upload-path", "chat-question"):
        _assert_visible_label(page, control_id)

    for form_id in ("upload-form", "chat-form"):
        form = _by_id(page, form_id)
        assert form is not None
        _assert_submit_button(page, form)


def test_tab_order_follows_the_document_order() -> None:
    """El orden de tabulación coincide con el visual (RNF-3, 2.4.3)."""
    page = _page()
    focusable = [
        node
        for node in _iter_nodes(page)
        if node.tag in {"input", "textarea", "button"}
        and node.attrs.get("type") != "hidden"
        and "disabled" not in node.attrs
    ]

    assert [node.attrs.get("id") for node in focusable] == [
        "upload-file",
        "upload-path",
        "upload-submit",
        "chat-question",
        "chat-submit",
    ]


def test_page_has_no_focus_traps_or_positive_tabindex() -> None:
    """Solo la sección de subida es enfocable por programa (RF-25, 2.1.2)."""
    page = _page()
    with_tabindex = [
        node for node in _iter_nodes(page) if "tabindex" in node.attrs
    ]

    assert len(with_tabindex) == 1
    assert with_tabindex[0].attrs.get("id") == "subida"
    assert with_tabindex[0].attrs.get("tabindex") == "-1"

    for node in _iter_nodes(page):
        if node.attrs.get("aria-hidden") == "true":
            assert node.tag not in {"input", "textarea", "button", "a"}, (
                f"`<{node.tag}>` enfocable no puede estar oculto a la vez"
            )


def test_only_the_empty_index_action_moves_the_focus() -> None:
    """El único movimiento de foco lo provoca `empty_index` (RF-25)."""
    source = _js_without_comments()

    assert len(re.findall(r"\.focus\(\)", source)) == 1, (
        "solo la acción de `empty_index` mueve el foco"
    )
    assert "elements.uploadSection.focus()" in _js_function_body("appendEmptyIndex")
    assert ".focus(" not in _js_function_body("handleSend")
    assert ".focus(" not in _js_function_body("handleUpload")


def test_upload_loading_is_announced_before_waiting_and_only_disables_its_button() -> (
    None
):
    """La carga de subida se anuncia antes de la petición (RNF-3, RNF-7)."""
    body = _js_function_body("handleUpload")
    loading = body.index("showUploadLoading()")
    request = body.index('request("/upload"')
    finally_block = body[body.index("} finally {") :]

    assert loading < request
    assert "elements.uploadButton.disabled = false" in finally_block
    assert "uploadFile.disabled" not in body
    assert "uploadPath.disabled" not in body


def test_chat_loading_is_announced_before_waiting_and_keeps_the_field_editable() -> (
    None
):
    """La carga del chat se anuncia y no deshabilita la pregunta (RNF-3, RNF-7)."""
    body = _js_function_body("handleSend")
    loading = body.index("appendStatus(MSG_CHAT_LOADING)")
    request = body.index('request("/chat"')
    finally_block = body[body.index("} finally {") :]

    assert loading < request
    assert "loading.remove()" in finally_block
    assert "elements.chatQuestion.disabled" not in body


def test_css_shows_a_visible_outline_for_programmatic_focus() -> None:
    """El panel enfocado por la acción de `empty_index` muestra el foco (RNF-3, 2.4.7)."""
    blocks = _css_blocks(_css_source())

    programmatic = [
        body
        for selector, body in blocks
        if ".panel" in selector and ":focus" in selector
    ]

    assert programmatic, "falta el contorno de foco del panel enfocado por programa"
    assert any(
        "outline: var(--focus-width) solid var(--color-primary)" in body
        for body in programmatic
    )
    assert any(":focus-visible" in selector for selector, _ in blocks)


# --- Guardas del acabado responsive (RF-20, RNF-3, RNF-4 y RNF-10) ----------


def test_css_two_column_layout_starts_at_sixty_rems() -> None:
    """Desde 60rem la subida va a la izquierda y el chat a la derecha (RNF-4)."""
    media = _media_query_body(_MEDIA_CONDITION)

    assert media is not None, f"falta la condición `{_MEDIA_CONDITION}`"

    main = dict(_css_blocks(media)).get(".main")

    assert main is not None, "la condición de media debe redefinir `.main`"

    columns = _css_declaration(main, "grid-template-columns")

    assert columns is not None, "`.main` debe declarar `grid-template-columns`"
    assert columns.split()[0] == "var(--panel-width)", (
        "la subida, primera en el DOM, debe ocupar la primera columna"
    )
    assert "minmax(0, 1fr)" in columns, (
        "la conversación debe ocupar el resto sin ensanchar la página"
    )


def test_css_grid_items_can_shrink_below_their_content() -> None:
    """Los elementos de rejilla no ensanchan la página (RNF-4, 1.4.10)."""
    blocks = dict(_css_blocks(_css_source()))

    for selector in (".panel", ".field__input"):
        assert _css_declaration(blocks.get(selector, ""), "min-width") == "0", (
            f"`{selector}` debe declarar `min-width: 0`"
        )

    media = _media_query_body(_MEDIA_CONDITION)

    assert media is not None, f"falta la condición `{_MEDIA_CONDITION}`"
    assert "minmax(0, 1fr)" in media, "la columna del chat debe poder encogerse"


def test_css_never_hides_horizontal_overflow() -> None:
    """El desbordamiento se corrige en el layout, no se oculta (RNF-4, 1.4.10)."""
    source = _strip_css_comments(_css_source())

    assert not re.search(r"(?<![\w-])overflow-x\s*:", source), (
        "no se puede ocultar el desplazamiento horizontal"
    )
    assert not re.search(r"(?<![\w-])overflow\s*:\s*(?:hidden|scroll)\b", source), (
        "no se puede ocultar el desbordamiento"
    )


def test_css_touch_targets_use_the_touch_token() -> None:
    """Botones, campo de archivo y pregunta miden al menos 44 px (RNF-4)."""
    blocks = _css_blocks(_css_source())

    for selector in (".button", ".field__input--area"):
        bodies = [body for name, body in blocks if name == selector]

        assert bodies, f"falta el estilo de `{selector}`"
        assert all(
            _css_declaration(body, "min-height") == "var(--size-touch)"
            for body in bodies
        ), f"`{selector}` debe medir al menos `var(--size-touch)`"

    file_targets = [
        body for name, body in blocks if 'input[type="file"]' in name
    ]

    assert file_targets, "falta el estilo del campo de archivo"
    assert all(
        _css_declaration(body, "min-height") == "var(--size-touch)"
        for body in file_targets
    ), "el campo de archivo y su botón deben medir al menos `var(--size-touch)`"


def test_css_wraps_long_values_without_truncating_them() -> None:
    """Rutas, símbolos y textos largos se ajustan, no se recortan (RF-20, RNF-4)."""
    source = _strip_css_comments(_css_source())

    assert "text-overflow" not in source, "no se puede recortar el texto"
    assert "white-space: nowrap" not in source, "no se puede impedir el ajuste"

    blocks = _css_blocks(source)

    for selector in (
        ".message__text",
        ".citation__path",
        ".citation__symbol",
        ".citation__lines",
    ):
        bodies = [body for name, body in blocks if selector in name]

        assert bodies, f"falta el estilo de `{selector}`"
        assert all("overflow-wrap: anywhere" in body for body in bodies), (
            f"`{selector}` debe ajustarse en varias líneas"
        )


# --- Verificación integral de T10 (RF-1 a RF-34 y RNF-1 a RNF-10) ----------

#: Rutas propias que la página necesita para funcionar (RF-1, RF-2, RF-32).
_OWN_RESOURCE_PATHS = (
    "/",
    "/static/style.css",
    "/static/app.js",
    "/static/favicon.svg",
    "/favicon.ico",
)

#: URL externa en cualquier recurso propio (RF-31).
_EXTERNAL_URL_RE = re.compile(r"https?://[^\s\"'<>]+")

#: Única URL externa permitida: el espacio de nombres del SVG (RF-31).
_SVG_NAMESPACE = "http://www.w3.org/2000/svg"

#: APIs de persistencia que la interfaz no puede usar (RF-30, RNF-6).
_PERSISTENCE_MARKERS = (
    "document.cookie",
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "caches.",
    "serviceWorker",
    "navigator.storage",
)

#: `tasks.md`, para comprobar el registro de verificación de T10.
_TASKS_PATH = (
    Path(__file__).resolve().parents[1] / "specs" / "005-interfaz-web" / "tasks.md"
)

#: Requisitos que el registro de T10 debe cubrir uno a uno.
_REQUIRED_REQUIREMENTS = tuple(f"RF-{number}" for number in range(1, 35)) + tuple(
    f"RNF-{number}" for number in range(1, 11)
)

#: Áreas de casos límite que el registro de T10 debe recorrer.
_T10_EDGE_CASE_AREAS = (
    "Carga inicial",
    "Subida",
    "Conversación",
    "Render",
    "Sesión",
    "Accesibilidad",
    "Responsive",
    "Navegadores",
)

_T10_HEADING_RE = re.compile(r"^- \[[ x]\] \*\*T10\.", re.MULTILINE)
_NEXT_TASK_HEADING_RE = re.compile(r"^- \[[ x]\] \*\*T\d+", re.MULTILINE)


def test_all_own_resources_answer_without_not_found() -> None:
    """La página, sus recursos y su icono responden 200 (RF-1, RF-2, RF-32)."""
    client = _client()

    for path in _OWN_RESOURCE_PATHS:
        response = client.get(path)
        assert response.status_code == 200, (
            f"`{path}` respondió {response.status_code}, no 200"
        )


def test_page_references_only_served_own_resources() -> None:
    """Todo `href`/`src` propio de la página se sirve (RF-1, RF-2, RF-32)."""
    references = {
        node.attrs[name]
        for node in _iter_nodes(_page())
        for name in ("href", "src")
        if name in node.attrs and node.attrs[name].startswith("/")
    }

    assert references == {
        "/static/favicon.svg",
        "/static/style.css",
        "/static/app.js",
    }, f"recursos referenciados inesperados: {sorted(references)}"

    client = _client()

    for reference in references:
        response = client.get(reference)
        assert response.status_code == 200, (
            f"`{reference}` respondió {response.status_code}, no 200"
        )


def test_static_sources_reference_only_the_own_origin() -> None:
    """Ningún recurso propio descarga de terceros (RF-31)."""
    for name in ("index.html", "style.css", "app.js"):
        source = (STATIC_DIR / name).read_text(encoding="utf-8")

        assert not _EXTERNAL_URL_RE.search(source), f"`{name}` usa una URL externa"
        assert not re.search(r"""["'(]//[^/]""", source), (
            f"`{name}` usa un dominio externo"
        )

    svg = (STATIC_DIR / "favicon.svg").read_text(encoding="utf-8")

    assert _EXTERNAL_URL_RE.findall(svg) == [_SVG_NAMESPACE], (
        "el SVG solo puede declarar su espacio de nombres"
    )


def test_static_sources_do_not_use_browser_storage_or_cookies() -> None:
    """La interfaz no persiste datos ni usa cookies (RF-30, RNF-6)."""
    for name in ("index.html", "style.css", "app.js"):
        source = (STATIC_DIR / name).read_text(encoding="utf-8")

        for marker in _PERSISTENCE_MARKERS:
            assert marker not in source, f"`{name}` no puede usar `{marker}`"


def test_static_directory_listing_is_disabled() -> None:
    """`/static/` no lista el directorio y conserva el error de la 004 (RF-32)."""
    _assert_error(
        _client().get("/static/"),
        404,
        ApiReason.NOT_FOUND,
        main.MSG_NOT_FOUND,
    )


def test_app_js_calls_only_the_two_api_routes() -> None:
    """La interfaz solo llama a `/upload` y `/chat` (RNF-2, RF-31)."""
    source = _js_without_comments()

    assert set(re.findall(r'request\("([^"]+)"', source)) == {"/upload", "/chat"}
    assert source.count("fetch(") == 1, "todas las peticiones pasan por `request`"


def _t10_section() -> str:
    """Devuelve el bloque de la tarea T10 dentro de `tasks.md`."""
    source = _TASKS_PATH.read_text(encoding="utf-8")
    match = _T10_HEADING_RE.search(source)

    assert match is not None, "`tasks.md` no contiene la tarea T10"

    following = _NEXT_TASK_HEADING_RE.search(source, match.end())
    end = following.start() if following else len(source)

    return source[match.end() : end]


def test_t10_verification_record_is_complete_and_checked() -> None:
    """T10 está marcada y su registro cubre requisitos y casos límite."""
    source = _TASKS_PATH.read_text(encoding="utf-8")
    section = _t10_section()

    assert re.search(r"^- \[x\] \*\*T10\.", source, re.MULTILINE), (
        "T10 debe estar marcada como hecha"
    )
    assert "**Registro de verificación" in section, (
        "falta el registro de verificación de T10"
    )

    missing = [
        requirement
        for requirement in _REQUIRED_REQUIREMENTS
        if not re.search(rf"\b{re.escape(requirement)}\b", section)
    ]

    assert not missing, f"faltan requisitos en el registro de T10: {missing}"

    for area in _T10_EDGE_CASE_AREAS:
        assert area in section, f"falta el área de casos límite `{area}`"
