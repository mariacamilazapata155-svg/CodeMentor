"""Pruebas de la ruta `POST /upload`.

Cubren el éxito, la ruta efectiva, la extensión, la codificación, los motivos
del indexado, el orden de comprobaciones y la integridad del índice (RF-2 a
RF-9 y RF-13). La mayoría usa un `index_file` falso sustituido por
`app.dependency_overrides`; las de integridad usan el `rag.index_file` real con
un doble del modelo de embeddings, sin red ni claves.
"""

import codecs
from collections.abc import Callable, Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from app import main, rag
from app.models import ApiReason, Chunk, IndexReason, IndexResult
from app.storage import VectorStore

#: Claves exactas de un éxito de subida (contrato de `UploadResponse`).
UPLOAD_KEYS = {"file_path", "chunks_indexed", "total_chunks", "used_windows", "message"}

#: Claves exactas del cuerpo de error (RF-14).
ERROR_KEYS = {"message", "reason"}

#: Contenido mínimo de un archivo Python de prueba.
SOURCE = "x = 1\n"

#: Dimensión de los vectores falsos de embeddings.
EMBEDDING_DIMENSIONS = 3

#: Contenido válido para poblar el índice antes de comprobar un rechazo.
AUTH_SOURCE = "def login():\n    return True\n\ndef logout():\n    return False\n"

#: Dos archivos con el mismo nombre y contenido distinto para sus rutas.
ALPHA_SOURCE = "def alpha():\n    return 1\n"
BETA_SOURCE = "def beta():\n    return 2\n"


def make_path(length: int) -> str:
    """Crea una ruta que termina en `.py` con la longitud exacta pedida."""
    return "a" * (length - len(".py")) + ".py"


def post_empty_filename(client: TestClient) -> Response:
    """Envía un multipart con `filename=""` y contenido válido.

    `httpx2` omite el parámetro `filename` cuando vale vacío, así que la
    petición se construye a mano para poder probar la ruta efectiva vacía.
    """
    boundary = "----codementor"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename=""\r\n'
        "Content-Type: text/x-python\r\n\r\n"
        f"{SOURCE}\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    return client.post(
        "/upload",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


class FakeIndexFile:
    """Doble de `rag.index_file` que registra las llamadas y devuelve un éxito.

    Registra `(ruta_efectiva, texto)` tal cual los recibe, sin recortar ni
    normalizar, para poder comprobar qué entrega la capa HTTP a la capacidad.
    """

    def __init__(self, result: IndexResult | None = None) -> None:
        self.result = result if result is not None else make_success_result()
        self.calls: list[tuple[str, str]] = []

    def __call__(self, file_path: str, source: str) -> IndexResult:
        """Anota la llamada y devuelve el resultado configurado."""
        self.calls.append((file_path, source))
        return self.result


def make_success_result(file_path: str = "utils.py") -> IndexResult:
    """Crea un `IndexResult` de éxito con valores distinguibles."""
    return IndexResult(
        file_path=file_path,
        chunks_indexed=2,
        total_chunks=5,
        used_windows=False,
        message="Se indexaron 2 fragmentos.",
    )


class FakeEmbeddingModel:
    """Doble del modelo de embeddings que devuelve filas normalizadas.

    Cada fila tiene un uno en una posición distinta, de modo que la matriz es
    válida y determinista sin descargar el modelo real. Con `fail=True` lanza
    `RuntimeError`, que es el fallo que `rag.index_file` traduce a
    `embedding_failed`.
    """

    def __init__(self, *, fail: bool = False) -> None:
        """Configura si el doble debe fallar al calcular representaciones."""
        self.fail = fail
        self.texts: list[str] = []

    def encode(self, texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        """Registra los textos y devuelve una fila normalizada por texto."""
        if self.fail:
            raise RuntimeError("fallo simulado del modelo de embeddings")

        self.texts.extend(texts)
        rows = np.zeros((len(texts), EMBEDDING_DIMENSIONS), dtype=np.float32)
        for index in range(len(texts)):
            rows[index, index % EMBEDDING_DIMENSIONS] = 1.0
        return rows


def snapshot() -> list[Chunk]:
    """Devuelve los fragmentos del índice en orden de inserción.

    Se consulta con el vector cero: todas las puntuaciones empatan y el orden
    estable de `search` coincide con el orden en que se indexaron.
    """
    query = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)
    return [result.chunk for result in rag.store.search(query, top_k=10_000)]


def seed_index(monkeypatch: pytest.MonkeyPatch) -> list[Chunk]:
    """Indexa un archivo válido con embeddings falsos y devuelve su instantánea."""
    monkeypatch.setattr(rag, "_get_model", lambda: FakeEmbeddingModel())
    result = rag.index_file("app/auth.py", AUTH_SOURCE)
    assert result.reason is None
    return snapshot()


@pytest.fixture(autouse=True)
def clean_overrides() -> Iterator[None]:
    """Vacía las dependencias sustituidas antes y después de cada prueba."""
    main.app.dependency_overrides.clear()
    yield
    main.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clean_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sustituye el singleton en memoria por uno vacío en cada prueba.

    `rag.index_file` lee `rag.store` en cada llamada, así que el índice real de
    las pruebas de integridad nunca comparte estado con otras pruebas.
    """
    monkeypatch.setattr(rag, "store", VectorStore())


@pytest.fixture
def client() -> TestClient:
    """Cliente que devuelve las respuestas de error en lugar de relanzarlas."""
    return TestClient(main.app, raise_server_exceptions=False)


def use_index_file(fake: FakeIndexFile) -> None:
    """Sustituye la capacidad de indexado por el doble indicado."""
    main.app.dependency_overrides[main.get_index_file] = lambda: fake


def assert_error(response: Response, reason: ApiReason, message: str) -> None:
    """Comprueba el estado 400 y el formato de error con su mensaje."""
    assert response.status_code == 400

    body = response.json()

    assert set(body) == ERROR_KEYS
    assert body == {"message": message, "reason": reason.value}


# --- Éxito y ruta efectiva (RF-2, RF-3 y RF-4) ------------------------------


def test_upload_success_without_path_uses_filename(client: TestClient) -> None:
    """Sin `path`, la ruta efectiva es el nombre del archivo y se responde 200."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("utils.py", SOURCE.encode(), "text/x-python")},
    )

    assert response.status_code == 200

    body = response.json()

    assert set(body) == UPLOAD_KEYS
    assert body == {
        "file_path": "utils.py",
        "chunks_indexed": 2,
        "total_chunks": 5,
        "used_windows": False,
        "message": "Se indexaron 2 fragmentos.",
    }
    assert fake.calls == [("utils.py", SOURCE)]


def test_empty_path_uses_filename_without_trimming(client: TestClient) -> None:
    """`path=""` equivale a ausente: la ruta efectiva es el nombre del archivo."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("utils.py", SOURCE.encode(), "text/x-python")},
        data={"path": ""},
    )

    assert response.status_code == 200
    assert fake.calls == [("utils.py", SOURCE)]


def test_blank_path_is_rejected_without_indexing(client: TestClient) -> None:
    """Un `path` de solo espacios no está vacío y da 400 `invalid_path`."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("utils.py", SOURCE.encode(), "text/x-python")},
        data={"path": "   "},
    )

    assert_error(response, ApiReason.INVALID_PATH, main.MSG_INVALID_PATH)
    assert fake.calls == []


@pytest.mark.parametrize(
    "path",
    ["src/a.py", "src\\a.py", "  a.py", "a b.py"],
    ids=["barra", "barra-invertida", "espacios-iniciales", "espacio-medio"],
)
def test_path_is_delivered_exactly_as_sent(client: TestClient, path: str) -> None:
    """La ruta llega al indexado sin recortar ni normalizar y vuelve tal cual."""
    fake = FakeIndexFile(make_success_result(file_path="devuelto.py"))
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("otro.py", SOURCE.encode(), "text/x-python")},
        data={"path": path},
    )

    assert response.status_code == 200
    assert fake.calls == [(path, SOURCE)]
    assert response.json()["file_path"] == "devuelto.py"


# --- Límite y caracteres de la ruta (RF-4) -----------------------------------


def test_path_of_255_characters_is_accepted(client: TestClient) -> None:
    """255 caracteres es el máximo permitido: se indexa con la ruta tal cual."""
    fake = FakeIndexFile()
    use_index_file(fake)
    path = make_path(main.MAX_PATH_CHARS)

    response = client.post(
        "/upload",
        files={"file": ("otro.py", SOURCE.encode(), "text/x-python")},
        data={"path": path},
    )

    assert len(path) == 255
    assert response.status_code == 200
    assert fake.calls == [(path, SOURCE)]


def test_path_of_256_characters_is_rejected(client: TestClient) -> None:
    """Un carácter más de lo permitido da 400 `invalid_path` sin indexar."""
    fake = FakeIndexFile()
    use_index_file(fake)
    path = make_path(main.MAX_PATH_CHARS + 1)

    response = client.post(
        "/upload",
        files={"file": ("otro.py", SOURCE.encode(), "text/x-python")},
        data={"path": path},
    )

    assert len(path) == 256
    assert_error(response, ApiReason.INVALID_PATH, main.MSG_INVALID_PATH)
    assert fake.calls == []


def test_empty_filename_without_path_is_rejected(client: TestClient) -> None:
    """Sin `path` y con nombre de archivo vacío, la ruta efectiva está vacía."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = post_empty_filename(client)

    assert_error(response, ApiReason.INVALID_PATH, main.MSG_INVALID_PATH)
    assert fake.calls == []


@pytest.mark.parametrize(
    "character",
    ["\n", "\t", "\x00", "\u2028"],
    ids=["salto", "tabulador", "nulo", "u2028"],
)
def test_control_characters_in_path_are_rejected(
    client: TestClient, character: str
) -> None:
    """Un carácter de control en la ruta da 400 `invalid_path` sin indexar."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("otro.py", SOURCE.encode(), "text/x-python")},
        data={"path": f"a{character}.py"},
    )

    assert_error(response, ApiReason.INVALID_PATH, main.MSG_INVALID_PATH)
    assert fake.calls == []


# --- Extensión (RF-5) --------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["a.txt", "a.js", "a.py.txt", "py", "a.pyi", "a.py "],
    ids=["txt", "js", "doble", "sin-punto", "pyi", "espacio-final"],
)
def test_invalid_extensions_are_rejected(client: TestClient, path: str) -> None:
    """Solo se acepta una ruta que termine exactamente en `.py`."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("otro.py", SOURCE.encode(), "text/x-python")},
        data={"path": path},
    )

    assert_error(response, ApiReason.INVALID_EXTENSION, main.MSG_INVALID_EXTENSION)
    assert fake.calls == []


@pytest.mark.parametrize(
    "path",
    ["a.PY", "app/Main.PY", ".py"],
    ids=["mayusculas", "carpeta-mayusculas", "solo-extension"],
)
def test_valid_python_extensions_are_accepted(client: TestClient, path: str) -> None:
    """La extensión no distingue mayúsculas y `.py` sola también vale."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("otro.py", SOURCE.encode(), "text/x-python")},
        data={"path": path},
    )

    assert response.status_code == 200
    assert fake.calls == [(path, SOURCE)]


def test_invalid_path_wins_over_invalid_extension(client: TestClient) -> None:
    """RF-4 se comprueba antes que RF-5: `a\\n.txt` es ruta inválida."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("otro.py", SOURCE.encode(), "text/x-python")},
        data={"path": "a\n.txt"},
    )

    assert_error(response, ApiReason.INVALID_PATH, main.MSG_INVALID_PATH)
    assert fake.calls == []


# --- Codificación (RF-6) -----------------------------------------------------


def test_utf8_bom_is_removed_before_indexing(client: TestClient) -> None:
    """El falso recibe el texto sin el BOM inicial y se responde 200."""
    fake = FakeIndexFile()
    use_index_file(fake)
    raw = codecs.BOM_UTF8 + SOURCE.encode()

    response = client.post(
        "/upload",
        files={"file": ("utils.py", raw, "text/x-python")},
    )

    assert response.status_code == 200
    assert fake.calls == [("utils.py", SOURCE)]
    assert not fake.calls[0][1].startswith("\ufeff")


@pytest.mark.parametrize(
    "raw",
    [b"\xff\xfe\x00", "año = 1\n".encode("latin-1")],
    ids=["bytes-invalidos", "latin-1"],
)
def test_non_utf8_file_is_rejected(client: TestClient, raw: bytes) -> None:
    """Lo que no es UTF-8 da 400 `invalid_encoding` sin indexar."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("utils.py", raw, "text/x-python")},
    )

    assert_error(response, ApiReason.INVALID_ENCODING, main.MSG_INVALID_ENCODING)
    assert fake.calls == []


# --- Motivos del indexado (RF-7) ---------------------------------------------

#: Estado que fija RF-7 para cada motivo del indexado.
INDEX_STATUS_CASES = [
    (IndexReason.EMPTY_CONTENT, 400),
    (IndexReason.TOO_LARGE, 413),
    (IndexReason.TOO_MANY_CHUNKS, 413),
    (IndexReason.EMBEDDING_FAILED, 500),
]


def make_rejection_result(reason: IndexReason) -> IndexResult:
    """Crea el `IndexResult` de rechazo que devolvería la spec 002.

    El mensaje sale de `rag._rejection_message`, la misma función que usa la
    capacidad de indexado, para comprobar que la capa HTTP no lo reescribe.
    """
    extras: dict[str, int] = {}
    if reason is IndexReason.TOO_LARGE:
        extras["size"] = rag.MAX_FILE_BYTES + 1
    elif reason is IndexReason.TOO_MANY_CHUNKS:
        extras["produced"] = rag.MAX_CHUNKS_PER_FILE + 1

    return IndexResult(
        file_path="utils.py",
        chunks_indexed=0,
        total_chunks=0,
        used_windows=False,
        reason=reason,
        message=rag._rejection_message(reason, **extras),
    )


@pytest.mark.parametrize(
    ("reason", "status"),
    INDEX_STATUS_CASES,
    ids=[reason.value for reason, _ in INDEX_STATUS_CASES],
)
def test_index_rejection_uses_its_status_and_capability_message(
    client: TestClient, reason: IndexReason, status: int
) -> None:
    """Cada motivo del indexado conserva su estado y su mensaje tal cual."""
    expected = make_rejection_result(reason)
    fake = FakeIndexFile(expected)
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("utils.py", SOURCE.encode(), "text/x-python")},
    )

    assert response.status_code == status

    body = response.json()

    assert set(body) == ERROR_KEYS
    assert body == {"message": expected.message, "reason": reason.value}
    assert fake.calls == [("utils.py", SOURCE)]


# --- Orden de comprobaciones (RF-9) -----------------------------------------


def test_excessive_content_length_wins_over_invalid_path(client: TestClient) -> None:
    """El middleware rechaza por tamaño antes de mirar la ruta (RF-9)."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("utils.py", SOURCE.encode(), "text/x-python")},
        data={"path": "a\n.txt"},
        headers={"Content-Length": str(main.UPLOAD_BODY_LIMIT + 1)},
    )

    assert response.status_code == 413
    assert response.json() == {
        "message": main.MSG_UPLOAD_TOO_LARGE,
        "reason": ApiReason.PAYLOAD_TOO_LARGE.value,
    }
    assert fake.calls == []


def test_invalid_path_wins_over_invalid_encoding(client: TestClient) -> None:
    """La ruta se comprueba antes de decodificar el archivo (RF-9)."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("utils.py", b"\xff\xfe\x00", "text/x-python")},
        data={"path": "a\n.py"},
    )

    assert_error(response, ApiReason.INVALID_PATH, main.MSG_INVALID_PATH)
    assert fake.calls == []


def test_invalid_extension_wins_over_empty_content(client: TestClient) -> None:
    """La extensión se comprueba antes que el contenido vacío de la spec 002."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        files={"file": ("utils.py", b"", "text/x-python")},
        data={"path": "a.txt"},
    )

    assert_error(response, ApiReason.INVALID_EXTENSION, main.MSG_INVALID_EXTENSION)
    assert fake.calls == []


# --- Petición inválida (RF-13) ----------------------------------------------


def test_missing_file_field_is_invalid_request(client: TestClient) -> None:
    """Sin el campo `file` se responde 422 `invalid_request` sin indexar."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post("/upload", data={"path": "utils.py"})

    assert response.status_code == 422
    assert response.json() == {
        "message": main.MSG_INVALID_REQUEST,
        "reason": ApiReason.INVALID_REQUEST.value,
    }
    assert fake.calls == []


def test_non_multipart_content_type_is_invalid_request(client: TestClient) -> None:
    """Un `Content-Type` que no es multipart deja el formulario vacío y da 422."""
    fake = FakeIndexFile()
    use_index_file(fake)

    response = client.post(
        "/upload",
        content=b'{"path": "utils.py"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "message": main.MSG_INVALID_REQUEST,
        "reason": ApiReason.INVALID_REQUEST.value,
    }
    assert fake.calls == []


# --- Integridad del índice con el indexado real (RF-8) ----------------------

RejectionRequest = Callable[[TestClient, pytest.MonkeyPatch], Response]


def reject_by_invalid_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Response:
    """Envía una ruta inválida con un archivo y un contenido válidos."""
    return client.post(
        "/upload",
        files={"file": ("utils.py", SOURCE.encode(), "text/x-python")},
        data={"path": "a\n.py"},
    )


def reject_by_invalid_extension(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Response:
    """Envía una extensión inválida con un contenido válido."""
    return client.post(
        "/upload",
        files={"file": ("utils.py", SOURCE.encode(), "text/x-python")},
        data={"path": "a.txt"},
    )


def reject_by_invalid_encoding(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Response:
    """Envía bytes que no son UTF-8 con una ruta válida."""
    return client.post(
        "/upload",
        files={"file": ("utils.py", b"\xff\xfe\x00", "text/x-python")},
    )


def reject_by_empty_content(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Response:
    """Envía un archivo vacío que la spec 002 rechaza."""
    return client.post(
        "/upload",
        files={"file": ("nuevo.py", b"  \n", "text/x-python")},
        data={"path": "app/nuevo.py"},
    )


def reject_by_too_large(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Response:
    """Envía un archivo de un byte más que el límite de la spec 002."""
    return client.post(
        "/upload",
        files={
            "file": (
                "nuevo.py",
                b"a" * (rag.MAX_FILE_BYTES + 1),
                "text/x-python",
            )
        },
        data={"path": "app/nuevo.py"},
    )


def too_many_functions_source() -> str:
    """Crea un archivo con un fragmento más que el tope por archivo."""
    return "".join(
        f"def f{index}():\n    return {index}\n"
        for index in range(rag.MAX_CHUNKS_PER_FILE + 1)
    )


def reject_by_too_many_chunks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Response:
    """Envía un archivo que produciría más fragmentos que el tope."""
    return client.post(
        "/upload",
        files={
            "file": (
                "nuevo.py",
                too_many_functions_source().encode(),
                "text/x-python",
            )
        },
        data={"path": "app/nuevo.py"},
    )


def reject_by_embedding_failure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Response:
    """Hace fallar al doble de embeddings con un contenido válido."""
    monkeypatch.setattr(rag, "_get_model", lambda: FakeEmbeddingModel(fail=True))
    return client.post(
        "/upload",
        files={"file": ("nuevo.py", SOURCE.encode(), "text/x-python")},
        data={"path": "app/nuevo.py"},
    )


def reject_by_body_too_large(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Response:
    """Declara un `Content-Length` mayor que el límite de la ruta."""
    return client.post(
        "/upload",
        files={"file": ("utils.py", SOURCE.encode(), "text/x-python")},
        data={"path": "utils.py"},
        headers={"Content-Length": str(main.UPLOAD_BODY_LIMIT + 1)},
    )


def reject_by_missing_length(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Response:
    """Envía el cuerpo por fragmentos, sin cabecera `Content-Length`."""
    return client.post(
        "/upload",
        content=iter([b"--x--\r\n"]),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )


REJECTION_BUILDERS: dict[str, tuple[RejectionRequest, int, ApiReason | IndexReason]] = {
    "ruta": (reject_by_invalid_path, 400, ApiReason.INVALID_PATH),
    "extension": (reject_by_invalid_extension, 400, ApiReason.INVALID_EXTENSION),
    "codificacion": (reject_by_invalid_encoding, 400, ApiReason.INVALID_ENCODING),
    "vacio": (reject_by_empty_content, 400, IndexReason.EMPTY_CONTENT),
    "tamano": (reject_by_too_large, 413, IndexReason.TOO_LARGE),
    "tope": (reject_by_too_many_chunks, 413, IndexReason.TOO_MANY_CHUNKS),
    "embeddings": (reject_by_embedding_failure, 500, IndexReason.EMBEDDING_FAILED),
    "cuerpo": (reject_by_body_too_large, 413, ApiReason.PAYLOAD_TOO_LARGE),
    "longitud": (reject_by_missing_length, 411, ApiReason.LENGTH_REQUIRED),
}


@pytest.mark.parametrize(
    ("case", "scenario"),
    REJECTION_BUILDERS.items(),
    ids=list(REJECTION_BUILDERS),
)
def test_each_rejection_keeps_the_store_exactly_as_it_was(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    scenario: tuple[RejectionRequest, int, ApiReason | IndexReason],
) -> None:
    """Ningún rechazo cambia el `count` ni el contenido del índice (RF-8)."""
    builder, status, reason = scenario
    before = seed_index(monkeypatch)

    response = builder(client, monkeypatch)

    assert response.status_code == status
    assert response.json()["reason"] == reason.value
    assert rag.store.count == len(before)
    assert snapshot() == before


# --- Dos archivos con el mismo nombre (RF-3, RF-8) --------------------------


def test_two_files_with_the_same_name_index_separately_by_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dos `utils.py` con `path` distinto conviven con sus propios fragmentos."""
    monkeypatch.setattr(rag, "_get_model", lambda: FakeEmbeddingModel())

    first = client.post(
        "/upload",
        files={"file": ("utils.py", ALPHA_SOURCE.encode(), "text/x-python")},
        data={"path": "a/utils.py"},
    )
    second = client.post(
        "/upload",
        files={"file": ("utils.py", BETA_SOURCE.encode(), "text/x-python")},
        data={"path": "b/utils.py"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["file_path"] == "a/utils.py"
    assert second.json()["file_path"] == "b/utils.py"
    assert second.json()["total_chunks"] == 2

    stored = snapshot()

    assert {chunk.file_path for chunk in stored} == {"a/utils.py", "b/utils.py"}
    assert [
        (chunk.file_path, chunk.symbol_name, chunk.content) for chunk in stored
    ] == [
        ("a/utils.py", "alpha", ALPHA_SOURCE[:-1]),
        ("b/utils.py", "beta", BETA_SOURCE[:-1]),
    ]
