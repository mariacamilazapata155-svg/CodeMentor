"""Pruebas de seguridad y rendimiento de la búsqueda, del indexado y del bot.

El primer bloque (spec 001) comprueba que la búsqueda trata el código indexado
como texto, no abre conexiones ni escribe archivos, y que recorre 10.000
fragmentos en menos de dos segundos.

El segundo bloque (spec 002) caracteriza el indexado ya implementado: con
contenido malicioso, `chunk_python_file` e `index_file` no llaman a `exec` ni a
`eval`, no importan los módulos del contenido, no abren sockets y no dejan
archivos en disco (RNF-1, RNF-2); además, 1.000 líneas con 100 funciones se
trocean en menos de un segundo sin cargar el modelo (RNF-4).

El tercer bloque (spec 003) caracteriza la respuesta ya implementada: al modelo
solo llegan el mensaje de sistema, el historial enviado, la pregunta y los
fragmentos recuperados (RNF-1); un archivo malicioso se indexa y se responde
sin ejecutarlo (RNF-2); y construir el mensaje y procesar la respuesta con
cinco fragmentos de 6.000 caracteres tarda menos de un segundo (RNF-6).

Ninguna prueba descarga el modelo, usa red ni usa claves: los embeddings se
sustituyen por un doble que no importa `sentence_transformers` y el cliente del
modelo por un `FakeClient`.
"""

import builtins
import codecs
import json
import logging
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from conftest import FakeClient, make_message_response
from fastapi.testclient import TestClient
from httpx2 import Response

from app import bot, main, rag
from app.models import (
    ApiReason,
    ChatMessage,
    ChatResponse,
    Chunk,
    IndexReason,
    SearchResult,
)
from app.storage import VectorStore


@pytest.fixture(autouse=True)
def clean_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sustituye el singleton en memoria por uno vacío en cada prueba."""
    monkeypatch.setattr(rag, "store", VectorStore())


@pytest.fixture(autouse=True)
def clean_dependency_overrides() -> Iterator[None]:
    """Vacía las dependencias sustituidas antes y después de cada prueba."""
    main.app.dependency_overrides.clear()
    yield
    main.app.dependency_overrides.clear()


@pytest.fixture
def query_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fija el vector de la consulta para no cargar el modelo real."""
    monkeypatch.setattr(
        rag,
        "_embed_query",
        lambda query: np.array([1.0, 0.0], dtype=np.float32),
    )


def make_chunk(index: int, content: str = "def search(): ...") -> Chunk:
    """Crea un chunk con rango de líneas distinto para cada índice."""
    return Chunk(
        file_path="app/malicioso.py",
        symbol_name=f"fn_{index}",
        start_line=index * 10 + 1,
        end_line=index * 10 + 5,
        content=content,
        kind="function",
    )


def fail(*args: object, **kwargs: object) -> None:
    """Falla si la búsqueda intenta ejecutar código o abrir un socket."""
    raise AssertionError("la búsqueda no debe ejecutar código ni abrir sockets")


def test_search_never_executes_indexed_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, query_vector: None
) -> None:
    """Un chunk con código malicioso se trata como texto, nunca se ejecuta."""
    monkeypatch.chdir(tmp_path)
    rag.store.add(
        [make_chunk(0, content='import os; os.system("touch PWNED")')],
        np.array([[1.0, 0.0]], dtype=np.float32),
    )

    with monkeypatch.context() as patched:
        patched.setattr(builtins, "exec", fail)
        patched.setattr(builtins, "eval", fail)
        response = rag.search("os.system")

    assert response.results
    assert not (tmp_path / "PWNED").exists()


def test_search_opens_no_sockets_and_writes_no_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, query_vector: None
) -> None:
    """Buscar no requiere red ni deja archivos en disco."""
    monkeypatch.chdir(tmp_path)
    rag.store.add([make_chunk(0)], np.array([[1.0, 0.0]], dtype=np.float32))

    with monkeypatch.context() as patched:
        patched.setattr(socket, "socket", fail)
        response = rag.search("autenticación")

    assert response.results
    assert list(tmp_path.iterdir()) == []


def test_search_over_ten_thousand_fragments_is_fast() -> None:
    """La búsqueda sobre 10.000 vectores de 384 dimensiones tarda menos de dos segundos."""
    rng = np.random.default_rng(0)
    embeddings = rng.standard_normal((10_000, 384), dtype=np.float32)
    chunks = [make_chunk(index) for index in range(10_000)]
    store = VectorStore()
    store.add(chunks, embeddings)
    query = rng.standard_normal(384, dtype=np.float32)

    start = time.perf_counter()
    results = store.search(query, top_k=5)
    elapsed = time.perf_counter() - start

    assert len(results) == 5
    assert elapsed < 2.0


def test_importing_rag_does_not_import_the_embedding_model() -> None:
    """`import app.rag` no arrastra `sentence_transformers` ni descarga el modelo."""
    code = "import sys, app.rag; print('sentence_transformers' in sys.modules)"
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=project_root,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "False"


# --- Indexado: el contenido nunca se ejecuta (RNF-1) ------------------------

# Módulos estándar entre los que la prueba elige el primero que no esté ya
# cargado. Así la comprobación de `sys.modules` no es vacía cuando otro test o
# un plugin ha importado alguno de ellos.
PAYLOAD_MODULE_CANDIDATES = ("colorsys", "wave", "filecmp", "graphlib")


def unloaded_module() -> str:
    """Devuelve un módulo estándar que todavía no esté en `sys.modules`."""
    for name in PAYLOAD_MODULE_CANDIDATES:
        if name not in sys.modules:
            return name
    raise AssertionError("no queda ningún módulo de sondeo sin importar")


def import_payload(module: str) -> str:
    """Contenido malicioso con `import` de un módulo y `os.system`."""
    return (
        f"import {module}\n"
        "import os\n"
        "\n"
        'os.system("touch PWNED")\n'
        "\n"
        "\n"
        "def payload():\n"
        '    return open("PWNED", "w").write("pwned")\n'
    )


def dunder_import_payload(module: str) -> str:
    """Contenido malicioso con `__import__` y `os.system`."""
    return (
        f'__import__("{module}")\n'
        '__import__("os").system("touch PWNED")\n'
        "\n"
        "\n"
        "def payload():\n"
        '    return open("PWNED", "w").write("pwned")\n'
    )


MALICIOUS_PAYLOAD_BUILDERS = [
    pytest.param(import_payload, id="import"),
    pytest.param(dunder_import_payload, id="dunder_import"),
]


class ExecutionGuard:
    """Sustitutos de `exec` y `eval` que registran el uso y cortan la ejecución.

    Si el indexado intentara ejecutar el contenido, la prueba fallaría en ese
    mismo punto y nunca llegaría a crear `PWNED`; por eso se sustituyen solo
    dentro de un `monkeypatch.context()` acotado a la llamada, para no romper
    al propio pytest.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def exec_(self, *args: object, **kwargs: object) -> None:
        """Falla si alguien intenta ejecutar código durante el indexado."""
        self.calls.append("exec")
        raise AssertionError("el indexado no debe llamar a exec")

    def eval_(self, *args: object, **kwargs: object) -> None:
        """Falla si alguien intenta evaluar código durante el indexado."""
        self.calls.append("eval")
        raise AssertionError("el indexado no debe llamar a eval")


class FixedModel:
    """Doble del modelo de embeddings que no descarga nada ni usa red."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def encode(self, texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        """Registra los textos y devuelve una fila constante por fragmento."""
        self.texts.extend(texts)
        return np.ones((len(texts), 2), dtype=np.float32)


@pytest.mark.parametrize("builder", MALICIOUS_PAYLOAD_BUILDERS)
def test_chunking_never_executes_malicious_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    builder: Callable[[str], str],
) -> None:
    """`chunk_python_file` lee el contenido malicioso como texto, no lo ejecuta.

    La comprobación es real, no solo "no falla": `exec` y `eval` están
    sustituidos por funciones que lanzan `AssertionError`, se vigila que el
    módulo del contenido no entre en `sys.modules` y se verifica que el archivo
    `PWNED` que crearía el código no existe. Si el troceado ejecutara una sola
    línea, la prueba fallaría.
    """
    module = unloaded_module()
    source = builder(module)
    monkeypatch.chdir(tmp_path)
    assert module not in sys.modules
    before_modules = set(sys.modules)
    guard = ExecutionGuard()

    with monkeypatch.context() as patched:
        patched.setattr(builtins, "exec", guard.exec_)
        patched.setattr(builtins, "eval", guard.eval_)
        chunks = rag.chunk_python_file(source, "app/malicioso.py")

    assert chunks
    assert guard.calls == []
    assert not (tmp_path / "PWNED").exists()
    assert module not in set(sys.modules) - before_modules


@pytest.mark.parametrize("builder", MALICIOUS_PAYLOAD_BUILDERS)
def test_indexing_never_executes_malicious_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    builder: Callable[[str], str],
) -> None:
    """El contenido malicioso se indexa como texto y no se ejecuta al hacerlo.

    Es el caso negativo útil: el archivo es Python válido, así que `index_file`
    lo acepta (`reason is None` y fragmentos > 0), pero ni `exec`/`eval` ni la
    importación de sus módulos llegan a ocurrir.
    """
    module = unloaded_module()
    source = builder(module)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rag, "_get_model", lambda: FixedModel())
    assert module not in sys.modules
    before_modules = set(sys.modules)
    guard = ExecutionGuard()

    with monkeypatch.context() as patched:
        patched.setattr(builtins, "exec", guard.exec_)
        patched.setattr(builtins, "eval", guard.eval_)
        result = rag.index_file("app/malicioso.py", source)

    assert result.reason is None
    assert result.chunks_indexed > 0
    assert result.total_chunks == rag.store.count > 0
    assert guard.calls == []
    assert not (tmp_path / "PWNED").exists()
    assert module not in set(sys.modules) - before_modules


# --- Indexado: sin red y sin archivos (RNF-2) -------------------------------


def test_indexing_opens_no_sockets_and_writes_no_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Indexar no necesita red ni escribe: `tmp_path` queda exactamente igual."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rag, "_get_model", lambda: FixedModel())
    source = import_payload(unloaded_module())
    before = set(tmp_path.iterdir())

    with monkeypatch.context() as patched:
        patched.setattr(socket, "socket", fail)
        patched.setattr(socket, "create_connection", fail)
        result = rag.index_file("app/malicioso.py", source)

    assert result.reason is None
    assert result.chunks_indexed > 0
    assert set(tmp_path.iterdir()) == before


# --- Indexado: rendimiento del troceado (RNF-4) -----------------------------


def build_thousand_line_source() -> str:
    """Genera 1.000 líneas con 100 funciones realistas de 10 líneas cada una.

    Cada bloque son nueve líneas de código (definición, docstring, condicional,
    bucle y cálculos) más una línea en blanco de separación, de modo que el
    archivo tiene exactamente 1.000 líneas y 900 líneas con código.
    """
    blocks: list[str] = []
    for index in range(100):
        body = [
            f"def function_{index}(value):",
            '    """Devuelve un valor transformado paso a paso."""',
            "    result = value + 1",
            "    if result > 10:",
            "        result = result % 10",
            "    for step in range(3):",
            "        result += step",
            "    result = abs(result)",
            "    return result",
            "",
        ]
        blocks.append("\n".join(body) + "\n")
    return "".join(blocks)


def test_chunking_one_thousand_lines_takes_less_than_a_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RNF-4: 1.000 líneas con 100 funciones se trocean en menos de 1 segundo.

    El umbral es el de la spec y no se sube: si una máquina de CI más lenta
    fallara, el fallo señalaría una regresión real del troceado. La prueba no
    carga el modelo (se sustituye por una función que falla) porque el troceado
    no calcula representaciones.
    """
    source = build_thousand_line_source()
    monkeypatch.setattr(rag, "_get_model", fail)

    start = time.perf_counter()
    chunks = rag.chunk_python_file(source, "app/rendimiento.py")
    elapsed = time.perf_counter() - start

    assert len(source.splitlines()) == 1_000
    functions = [chunk for chunk in chunks if chunk.kind == "function"]
    assert len(functions) == 100
    assert len(chunks) == 100
    assert functions[0].symbol_name == "function_0"
    assert (functions[0].start_line, functions[0].end_line) == (1, 9)

    lines = source.splitlines()
    code_lines = {
        number
        for number, line in enumerate(lines, start=1)
        if line.strip() and not line.strip().startswith("#")
    }
    covered = {
        number
        for chunk in chunks
        for number in range(chunk.start_line, chunk.end_line + 1)
    }
    assert len(code_lines) == 900
    assert code_lines <= covered
    assert elapsed < 1.0


# --- Responder: solo se envía lo permitido (spec 003, RNF-1) -----------------

#: Clave falsa: nunca debe llegar al modelo ni a ningún valor serializado.
RN_F1_SECRET_KEY = "clave-secreta-rnf1"
ALPHA_PATH = "app/alpha.py"
ALPHA_SOURCE = (
    "def alpha_uno():\n"
    '    """Devuelve el texto único alpha-uno."""\n'
    '    return "alpha-uno"\n'
)
BETA_PATH = "app/beta.py"
BETA_SOURCE = (
    "def beta_dos():\n"
    '    """Devuelve el texto único beta-dos."""\n'
    '    return "beta-dos"\n'
)
ALPHA_QUESTION = "¿Qué devuelve alpha_uno?"


def patch_two_file_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hace que cada archivo tenga su propio vector y la consulta el de alpha.

    Los fragmentos de `app/alpha.py` comparten la dirección de la consulta
    (puntuación 1) y los de `app/beta.py` son ortogonales (puntuación 0, por
    debajo del umbral 0,30). Así solo se recupera el archivo preguntado sin
    cargar el modelo real.
    """
    alpha_vector = np.array([1.0, 0.0], dtype=np.float32)
    beta_vector = np.array([0.0, 1.0], dtype=np.float32)

    def embed_chunks(chunks: list[Chunk]) -> np.ndarray:
        rows = [
            alpha_vector if "alpha_uno" in chunk.content else beta_vector
            for chunk in chunks
        ]
        return np.array(rows, dtype=np.float32)

    monkeypatch.setattr(rag, "_embed_chunks", embed_chunks)
    monkeypatch.setattr(rag, "_embed_query", lambda _query: alpha_vector.copy())


def patch_constant_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hace que todos los fragmentos y la consulta tengan el mismo vector."""
    vector = np.array([1.0, 0.0], dtype=np.float32)

    def embed_chunks(chunks: list[Chunk]) -> np.ndarray:
        return np.tile(vector, (len(chunks), 1)).astype(np.float32)

    monkeypatch.setattr(rag, "_embed_chunks", embed_chunks)
    monkeypatch.setattr(rag, "_embed_query", lambda _query: vector.copy())


def serialize(value: object) -> str:
    """Serializa los argumentos de la llamada para inspeccionarlos como texto."""
    return json.dumps(value, ensure_ascii=False, default=str)


def test_rnf1_only_allowed_content_reaches_the_model(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
) -> None:
    """RNF-1: al modelo solo llegan sistema, historial, pregunta y recuperados.

    Se indexan dos archivos con textos únicos y se pregunta por uno: lo que
    recibe el cliente falso tiene exactamente las claves de la llamada, el
    mensaje de sistema fijo, el historial enviado y el fragmento recuperado.
    El texto del archivo no recuperado y la clave no aparecen en ningún valor.
    """
    patch_two_file_embeddings(monkeypatch)
    assert rag.index_file(ALPHA_PATH, ALPHA_SOURCE).reason is None
    assert rag.index_file(BETA_PATH, BETA_SOURCE).reason is None

    found = rag.search(ALPHA_QUESTION)
    assert [result.chunk.symbol_name for result in found.results] == ["alpha_uno"]

    set_api_key(RN_F1_SECRET_KEY)
    client = FakeClient(
        response=make_message_response("La función alpha_uno está en alpha.py [F1].")
    )
    monkeypatch.setattr(bot, "_get_client", lambda: client)
    history = [
        ChatMessage(role="user", content="historial-rnf1-uno"),
        ChatMessage(role="assistant", content="historial-rnf1-dos"),
    ]

    response = bot.answer(ALPHA_QUESTION, history)

    assert response.reason is None
    assert len(client.calls) == 1
    call = client.last_call
    assert set(call) == {"model", "max_tokens", "system", "messages"}
    assert call["system"] == bot.SYSTEM_PROMPT

    messages_payload = serialize(call["messages"])
    whole_payload = serialize(call)
    assert RN_F1_SECRET_KEY not in whole_payload
    assert "beta-dos" not in call["system"]
    assert "beta-dos" not in messages_payload
    assert "beta_dos" not in messages_payload
    assert BETA_PATH not in messages_payload
    assert ALPHA_QUESTION in messages_payload
    assert "historial-rnf1-uno" in messages_payload
    assert "historial-rnf1-dos" in messages_payload
    assert "alpha_uno" in messages_payload
    assert "alpha-uno" in messages_payload
    assert messages_payload.count("INICIO FRAGMENTO F") == len(found.results)


# --- Responder: código malicioso tratado como texto (spec 003, RNF-2) -------

MALICIOUS_MODULE = "malicioso_rnf2"
MALICIOUS_PATH = f"app/{MALICIOUS_MODULE}.py"
MALICIOUS_SOURCE = (
    f"import {MALICIOUS_MODULE}\n"
    "\n"
    "\n"
    f"def {MALICIOUS_MODULE}():\n"
    '    import os; os.system("touch PWNED")\n'
    f'    return "{MALICIOUS_MODULE}"\n'
)


def test_rnf2_answer_never_executes_the_indexed_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    set_api_key: Callable[[str | None], None],
) -> None:
    """RNF-2: responder no ejecuta, importa ni evalúa el código indexado.

    El archivo es Python válido y se indexa y se recupera, pero durante
    `answer` `exec` y `eval` están sustituidos por funciones que fallan, no se
    crea `PWNED` y el módulo del contenido no entra en `sys.modules`.
    """
    monkeypatch.chdir(tmp_path)
    patch_constant_embeddings(monkeypatch)
    assert rag.index_file(MALICIOUS_PATH, MALICIOUS_SOURCE).reason is None
    set_api_key("clave-secreta-rnf2")
    client = FakeClient(
        response=make_message_response("El código se trata como texto [F1].")
    )
    monkeypatch.setattr(bot, "_get_client", lambda: client)
    guard = ExecutionGuard()
    assert MALICIOUS_MODULE not in sys.modules
    assert f"app.{MALICIOUS_MODULE}" not in sys.modules
    before_modules = set(sys.modules)

    with monkeypatch.context() as patched:
        patched.setattr(builtins, "exec", guard.exec_)
        patched.setattr(builtins, "eval", guard.eval_)
        response = bot.answer("¿Dónde está el código malicioso?", [])

    assert client.calls
    assert response.reason is None
    assert guard.calls == []
    assert not (tmp_path / "PWNED").exists()
    assert MALICIOUS_MODULE not in sys.modules
    assert f"app.{MALICIOUS_MODULE}" not in sys.modules
    new_modules = set(sys.modules) - before_modules
    assert not any(MALICIOUS_MODULE in name for name in new_modules)


# --- Responder: rendimiento (spec 003, RNF-6) -------------------------------


def make_performance_result(index: int) -> SearchResult:
    """Crea un fragmento distinto de exactamente `MAX_FRAGMENT_CHARS` caracteres."""
    prefix = f"# fragmento de rendimiento {index}\n"
    content = prefix + "x" * (bot.MAX_FRAGMENT_CHARS - len(prefix))
    assert len(content) == bot.MAX_FRAGMENT_CHARS
    return SearchResult(
        chunk=Chunk(
            file_path=f"app/rendimiento_{index}.py",
            symbol_name=f"rendimiento_{index}",
            start_line=index * 10 + 1,
            end_line=index * 10 + 5,
            content=content,
            kind="function",
        ),
        score=1.0 - index * 0.01,
    )


def test_rnf6_building_messages_and_interpreting_take_less_than_a_second() -> None:
    """RNF-6: armar el mensaje y procesar la respuesta tarda menos de 1 segundo.

    Se usan cinco fragmentos de 6.000 caracteres y diez mensajes de historial.
    `_build_context` aplica el tope de 20.000 caracteres de RF-12 (solo caben
    tres), pero `_interpret` recibe los cinco fragmentos para medir la carga de
    trabajo que describe RNF-6. No se mide la búsqueda ni la llamada al modelo.
    """
    results = [make_performance_result(index) for index in range(5)]
    history = [
        ChatMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"mensaje de historial {index}",
        )
        for index in range(bot.MAX_HISTORY_MESSAGES)
    ]
    context, _delivered = bot._build_context(results)
    question = "¿Qué hacen las cinco funciones?"
    answer_text = " ".join(
        f"La función {index} hace algo [F{index + 1}]." for index in range(5)
    )

    start = time.perf_counter()
    messages = bot._build_messages(history, context, question)
    response = bot._interpret(answer_text, results)
    elapsed = time.perf_counter() - start

    assert len(messages) == bot.MAX_HISTORY_MESSAGES + 1
    assert response.reason is None
    assert len(response.citations) == len(results)
    assert elapsed < 1.0


# --- API HTTP: flujo completo, límite de archivo y temporal (spec 004) ------


API_PATH = "app/saludo.py"
API_SOURCE = 'def saludo():\n    return "hola"\n'
API_QUESTION = "¿Qué hace la función saludo?"


def api_client() -> TestClient:
    """Cliente de la app real que devuelve los errores en vez de relanzarlos."""
    return TestClient(main.app, raise_server_exceptions=False)


def test_full_flow_upload_then_chat_cites_the_indexed_fragment(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key: Callable[[str | None], None],
    query_vector: None,
) -> None:
    """Subir y preguntar devuelve una cita con ruta, símbolo y líneas reales.

    Usa el índice real, un doble del modelo de embeddings y el `FakeClient` de
    la spec 003: la cita sale del fragmento indexado, no del texto del modelo.
    """
    monkeypatch.setattr(rag, "_get_model", lambda: FixedModel())
    set_api_key("clave-de-prueba-del-flujo")
    fake = FakeClient(
        response=make_message_response(
            "La función saludo está en `app/saludo.py` [F1]."
        )
    )
    monkeypatch.setattr(bot, "_get_client", lambda: fake)
    client = api_client()

    upload = client.post(
        "/upload",
        files={"file": ("saludo.py", API_SOURCE.encode(), "text/x-python")},
        data={"path": API_PATH},
    )

    assert upload.status_code == 200
    assert upload.json()["file_path"] == API_PATH

    response = client.post("/chat", json={"message": API_QUESTION})

    assert response.status_code == 200
    body = response.json()
    assert body["reason"] is None
    assert body["reply"] == "La función saludo está en `app/saludo.py` [F1]."
    assert body["citations"] == [
        {
            "number": 1,
            "file_path": API_PATH,
            "symbol_name": "saludo",
            "start_line": 1,
            "end_line": 2,
        }
    ]
    assert len(fake.calls) == 1


def test_file_one_byte_over_the_limit_gives_too_large_inside_the_request_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.048.577 bytes sin BOM: pasa el middleware y lo rechaza el indexado.

    El motivo es `too_large` (spec 002), no `payload_too_large`: eso demuestra
    que la petición cabe en el límite de 1.052.672 bytes y que la medida se
    hace sobre el texto decodificado, no sobre el cuerpo multipart.
    """
    monkeypatch.setattr(rag, "_get_model", lambda: FixedModel())
    raw = b"a" * (rag.MAX_FILE_BYTES + 1)

    response = api_client().post(
        "/upload",
        files={"file": ("limite.py", raw, "text/x-python")},
    )

    assert response.status_code == 413
    body = response.json()
    assert body["reason"] == IndexReason.TOO_LARGE.value
    assert body["message"] == rag._rejection_message(
        IndexReason.TOO_LARGE, size=rag.MAX_FILE_BYTES + 1
    )
    assert rag.store.count == 0


def test_file_one_byte_over_the_raw_limit_with_bom_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.048.577 bytes crudos con BOM de 3 se aceptan: su texto son 1.048.574."""
    raw = codecs.BOM_UTF8 + b"a" * (rag.MAX_FILE_BYTES - len(codecs.BOM_UTF8) + 1)
    assert len(raw) == rag.MAX_FILE_BYTES + 1
    assert len(raw.decode("utf-8-sig").encode("utf-8")) == rag.MAX_FILE_BYTES - 2
    monkeypatch.setattr(rag, "_get_model", lambda: FixedModel())

    response = api_client().post(
        "/upload",
        files={"file": ("bom.py", raw, "text/x-python")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["file_path"] == "bom.py"
    assert body["chunks_indexed"] == 1
    assert body["total_chunks"] == 1
    assert rag.store.count == 1


def test_upload_leaves_no_files_in_the_temporary_or_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Starlette pasa a disco un archivo de más de 1 MiB y lo borra al terminar.

    `tempfile.tempdir` apunta a un directorio de la prueba para poder mirar
    exactamente dónde habría quedado el temporal. Tras la petición, ni ese
    directorio ni el de trabajo contienen archivos (RF-18).
    """
    spool = tmp_path / "temporal"
    work = tmp_path / "trabajo"
    spool.mkdir()
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setattr(tempfile, "tempdir", str(spool))
    monkeypatch.setattr(rag, "_get_model", lambda: FixedModel())
    raw = codecs.BOM_UTF8 + b"a" * (rag.MAX_FILE_BYTES - 2)
    before = set(work.iterdir())

    response = api_client().post(
        "/upload",
        files={"file": ("bom.py", raw, "text/x-python")},
    )

    assert response.status_code == 200
    assert set(work.iterdir()) == before
    assert before == set()
    assert list(spool.iterdir()) == []


# --- API HTTP: índice coherente con operaciones simultáneas (RF-22) ---------

#: Dimensión de los vectores falsos de las pruebas de simultaneidad.
CONCURRENT_DIMENSIONS = 2

#: Ruta que compiten las dos versiones de la prueba de mezcla.
CONTESTED_PATH = "app/versionada.py"

#: Versión A: dos funciones con la marca `version_a`.
VERSION_A_SOURCE = (
    "def version_a_uno():\n"
    '    return "version_a_uno"\n'
    "\n"
    "def version_a_dos():\n"
    '    return "version_a_dos"\n'
)

#: Versión B: tres funciones con la marca `version_b` (distinto número de chunks).
VERSION_B_SOURCE = (
    "def version_b_uno():\n"
    '    return "version_b_uno"\n'
    "\n"
    "def version_b_dos():\n"
    '    return "version_b_dos"\n'
    "\n"
    "def version_b_tres():\n"
    '    return "version_b_tres"\n'
)


def store_snapshot() -> list[Chunk]:
    """Devuelve todos los fragmentos del índice en orden de inserción.

    Consulta con un vector cero: todas las puntuaciones empatan y el orden
    estable de `search` coincide con el de inserción. Así se observa el índice
    completo sin tocar sus atributos privados.
    """
    query = np.zeros(CONCURRENT_DIMENSIONS, dtype=np.float32)
    return [result.chunk for result in rag.store.search(query, top_k=10_000)]


def concurrent_source(index: int) -> str:
    """Archivo con dos funciones y una marca única por ruta."""
    return (
        f"def ruta_{index}_uno():\n"
        f'    return "version_{index}_uno"\n'
        "\n"
        f"def ruta_{index}_dos():\n"
        f'    return "version_{index}_dos"\n'
    )


def test_concurrent_uploads_of_distinct_paths_keep_each_path_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 rutas subidas a la vez mientras se busca: índice completo y sin mezcla.

    Cada subida usa `rag.index_file` real con un doble de embeddings y las
    búsquedas usan `rag.search`. La barrera de inicio solo aumenta el
    solapamiento: las comprobaciones no dependen de qué hilo gane ni del orden
    en que terminen. Al final están las 20 rutas, cada una con sus dos
    fragmentos y el contenido de su única versión.
    """
    model = FixedModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    monkeypatch.setattr(
        rag, "_embed_query", lambda _query: np.array([1.0, 0.0], dtype=np.float32)
    )
    paths = [f"app/simultanea_{index}.py" for index in range(20)]
    sources = {path: concurrent_source(index) for index, path in enumerate(paths)}
    upload_threads = len(paths)
    search_threads = 4
    parties = upload_threads + search_threads
    barrier = threading.Barrier(parties)

    def upload(path: str) -> None:
        """Espera la salida común y sube una ruta distinta."""
        barrier.wait(timeout=30)
        result = rag.index_file(path, sources[path])
        assert result.reason is None
        assert result.chunks_indexed == 2

    def search_many() -> None:
        """Busca mientras se sube, sin exigir un estado concreto del índice."""
        barrier.wait(timeout=30)
        for _ in range(25):
            response = rag.search("¿dónde está la función?")
            assert (response.reason is None) == bool(response.results)

    with ThreadPoolExecutor(max_workers=parties) as executor:
        futures = [executor.submit(upload, path) for path in paths]
        futures.extend(executor.submit(search_many) for _ in range(search_threads))
        for future in futures:
            future.result()

    stored = store_snapshot()
    by_path: dict[str, list[Chunk]] = {}
    for chunk in stored:
        by_path.setdefault(chunk.file_path, []).append(chunk)

    assert set(by_path) == set(paths)
    assert rag.store.count == len(paths) * 2
    for index, path in enumerate(paths):
        chunks = by_path[path]
        assert len(chunks) == 2
        assert all(f"version_{index}_" in chunk.content for chunk in chunks)
        assert {chunk.symbol_name for chunk in chunks} == {
            f"ruta_{index}_uno",
            f"ruta_{index}_dos",
        }


class BarrierEmbeddingModel:
    """Doble de embeddings que sincroniza dos subidas antes de devolver vectores.

    Fuerza que las dos subidas de la misma ruta terminen de trocear a la vez y
    lleguen juntas al reemplazo, para ejercer la carrera sin depender de la
    velocidad de cada hilo.
    """

    def __init__(self, parties: int) -> None:
        self._barrier = threading.Barrier(parties)

    def encode(self, texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        """Espera a la otra subida y devuelve una fila constante por fragmento."""
        self._barrier.wait(timeout=30)
        return np.ones((len(texts), 2), dtype=np.float32)


def test_concurrent_uploads_of_the_same_path_never_mix_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dos versiones de la misma ruta a la vez: gana una completa, nunca mezcla.

    Las dos subidas esperan en un doble de embeddings hasta que ambas han
    troceado, y un tercer hilo busca durante los reemplazos. Cada instantánea
    intermedia de la ruta contiene fragmentos de una sola versión, y al final
    quedan los dos fragmentos de A o los tres de B, nunca una combinación.
    """
    model = BarrierEmbeddingModel(2)
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    monkeypatch.setattr(
        rag, "_embed_query", lambda _query: np.array([1.0, 0.0], dtype=np.float32)
    )
    barrier = threading.Barrier(3)
    mixed: list[list[str]] = []
    search_errors: list[BaseException] = []

    def upload(source: str):
        """Espera la salida común y sube una de las dos versiones."""
        barrier.wait(timeout=30)
        return rag.index_file(CONTESTED_PATH, source)

    def search_while_uploading() -> None:
        """Busca y retrata la ruta mientras las subidas se reemplazan."""
        barrier.wait(timeout=30)
        for _ in range(200):
            try:
                rag.search("¿qué versión está indexada?")
                contents = [
                    chunk.content
                    for chunk in store_snapshot()
                    if chunk.file_path == CONTESTED_PATH
                ]
            except BaseException as exc:  # noqa: BLE001 - se reporta como fallo
                search_errors.append(exc)
                return
            if contents and not (
                all("version_a" in content for content in contents)
                or all("version_b" in content for content in contents)
            ):
                mixed.append(contents)

    with ThreadPoolExecutor(max_workers=3) as executor:
        upload_a = executor.submit(upload, VERSION_A_SOURCE)
        upload_b = executor.submit(upload, VERSION_B_SOURCE)
        search = executor.submit(search_while_uploading)
        result_a = upload_a.result()
        result_b = upload_b.result()
        search.result()

    assert result_a.reason is None
    assert result_b.reason is None
    assert search_errors == []
    assert mixed == []

    stored = [chunk for chunk in store_snapshot() if chunk.file_path == CONTESTED_PATH]
    contents = [chunk.content for chunk in stored]
    if contents and all("version_a" in content for content in contents):
        assert len(stored) == 2
    else:
        assert contents
        assert all("version_b" in content for content in contents)
        assert len(stored) == 3


# --- API HTTP: registros sin datos sensibles (RNF-3) ------------------------

#: Clave falsa: nunca debe aparecer en los registros de la aplicación.
SENSITIVE_KEY = "CLAVE_SECRETA_RNF3"

#: Contenido con una tilde que no se puede decodificar como UTF-8 desde Latin-1.
SENSITIVE_CONTENT = "secreto_contenido = 'año'"

#: Ruta con un salto de línea: es inválida y lleva una marca reconocible.
SENSITIVE_PATH = "secreto_ruta\noculta.py"

#: Ruta con extensión inválida y una marca reconocible.
SENSITIVE_EXTENSION = "secreto_extension.txt"

#: Pregunta e historial con marcas únicas de la prueba.
SENSITIVE_QUESTION = "PREGUNTA_SECRETA_RNF3"
SENSITIVE_HISTORY = "HISTORIAL_SECRETO_RNF3"

#: Textos que ningún registro de la aplicación debe contener (RNF-3).
SENSITIVE_MARKERS = (
    "secreto",
    "secreto_ruta",
    "secreto_extension",
    "secreto_contenido",
    SENSITIVE_QUESTION,
    SENSITIVE_HISTORY,
    SENSITIVE_KEY,
)


def trigger_invalid_path(client: TestClient) -> Response:
    """Sube un archivo con una ruta que contiene un salto de línea."""
    return client.post(
        "/upload",
        files={"file": ("codigo.py", SENSITIVE_CONTENT.encode(), "text/x-python")},
        data={"path": SENSITIVE_PATH},
    )


def trigger_invalid_extension(client: TestClient) -> Response:
    """Sube un archivo con una extensión que no es `.py`."""
    return client.post(
        "/upload",
        files={"file": ("codigo.py", SENSITIVE_CONTENT.encode(), "text/x-python")},
        data={"path": SENSITIVE_EXTENSION},
    )


def trigger_invalid_encoding(client: TestClient) -> Response:
    """Sube un archivo con bytes Latin-1 que no son UTF-8 válido."""
    raw = f"{SENSITIVE_CONTENT}\n".encode("latin-1")
    return client.post(
        "/upload",
        files={"file": ("codigo.py", raw, "text/x-python")},
    )


def trigger_invalid_chat_body(client: TestClient) -> Response:
    """Envía un cuerpo de chat con un historial de tipo incorrecto."""
    return client.post(
        "/chat",
        json={
            "message": SENSITIVE_QUESTION,
            "history": {"contenido": SENSITIVE_HISTORY},
        },
    )


def trigger_unhandled_error(client: TestClient) -> Response:
    """Hace que la capacidad de respuesta lance un `RuntimeError`."""

    def explota(message: str, history: list[ChatMessage]) -> ChatResponse:
        raise RuntimeError("secreto")

    main.app.dependency_overrides[main.get_answer] = lambda: explota
    return client.post(
        "/chat",
        json={
            "message": SENSITIVE_QUESTION,
            "history": [{"role": "user", "content": SENSITIVE_HISTORY}],
        },
    )


#: Un caso por origen de error: ruta, extensión, codificación, cuerpo y 500.
ERROR_LOG_SCENARIOS = [
    pytest.param(
        trigger_invalid_path,
        400,
        ApiReason.INVALID_PATH.value,
        False,
        id="ruta",
    ),
    pytest.param(
        trigger_invalid_extension,
        400,
        ApiReason.INVALID_EXTENSION.value,
        False,
        id="extension",
    ),
    pytest.param(
        trigger_invalid_encoding,
        400,
        ApiReason.INVALID_ENCODING.value,
        False,
        id="codificacion",
    ),
    pytest.param(
        trigger_invalid_chat_body,
        422,
        ApiReason.INVALID_REQUEST.value,
        False,
        id="cuerpo-chat",
    ),
    pytest.param(
        trigger_unhandled_error,
        500,
        ApiReason.INTERNAL_ERROR.value,
        True,
        id="error-interno",
    ),
]


@pytest.mark.parametrize(
    ("trigger", "status", "reason", "logs_the_type"),
    ERROR_LOG_SCENARIOS,
)
def test_error_responses_never_log_sensitive_data(
    caplog: pytest.LogCaptureFixture,
    set_api_key: Callable[[str | None], None],
    trigger: Callable[[TestClient], Response],
    status: int,
    reason: str,
    logs_the_type: bool,
) -> None:
    """Ningún error deja contenido, rutas, preguntas, historial ni clave (RNF-3).

    Solo se afirma sobre los registros de la aplicación que recoge `caplog`, no
    sobre la salida propia de uvicorn. En el error interno, además, se comprueba
    que sí queda el tipo de la excepción y no su texto.
    """
    caplog.set_level(logging.DEBUG)
    set_api_key(SENSITIVE_KEY)
    caplog.clear()

    response = trigger(api_client())

    assert response.status_code == status
    assert response.json()["reason"] == reason
    for marker in SENSITIVE_MARKERS:
        assert marker not in caplog.text
    if logs_the_type:
        assert "RuntimeError" in caplog.text


# --- API HTTP: nada persistido tras subir y preguntar (RNF-6) --------------

#: Ruta, contenido y pregunta únicos de la prueba de persistencia.
RNF6_PATH = "app/rnf6.py"
RNF6_CONTENT = 'def rnf6_funcion():\n    return "contenido_rnf6_unico"\n'
RNF6_QUESTION = "PREGUNTA_RNF6_UNICA"
RNF6_HISTORY = "historial_rnf6_unico"


def test_upload_and_chat_leave_no_files_and_no_user_data_in_logs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    set_api_key: Callable[[str | None], None],
    query_vector: None,
) -> None:
    """Tras subir y preguntar no hay archivos nuevos ni datos en los registros.

    Se usa el flujo real con doble de embeddings y `FakeClient` en un
    directorio temporal para comparar su contenido antes y después. RNF-6: la
    capa no guarda el contenido ni la pregunta en ningún sitio.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rag, "_get_model", lambda: FixedModel())
    set_api_key("clave-rnf6")
    fake = FakeClient(response=make_message_response("La función existe [F1]."))
    monkeypatch.setattr(bot, "_get_client", lambda: fake)
    caplog.set_level(logging.DEBUG)
    before = set(tmp_path.iterdir())
    client = api_client()

    upload = client.post(
        "/upload",
        files={"file": ("rnf6.py", RNF6_CONTENT.encode(), "text/x-python")},
        data={"path": RNF6_PATH},
    )
    chat = client.post(
        "/chat",
        json={
            "message": RNF6_QUESTION,
            "history": [{"role": "user", "content": RNF6_HISTORY}],
        },
    )

    assert upload.status_code == 200
    assert chat.status_code == 200
    assert chat.json()["reason"] is None
    assert set(tmp_path.iterdir()) == before
    assert "contenido_rnf6_unico" not in caplog.text
    assert RNF6_QUESTION not in caplog.text
    assert RNF6_HISTORY not in caplog.text
