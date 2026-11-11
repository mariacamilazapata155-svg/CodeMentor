"""Pruebas de las validaciones de contenido y de los mensajes de indexación.

Cubren `_validate_content` (vacío antes que tamaño y el límite medido en bytes
UTF-8, no en caracteres), el criterio único del tope de fragmentos
(`_too_many_chunks`) y los cinco mensajes en español de `_success_message` y
`_rejection_message` (RF-10, RF-13, RF-14, RF-21, RF-24, RNF-3).

Viven en `tests/test_index.py` porque son las precondiciones y el informe de
`index_file`. No son troceado (`test_chunking.py`) ni contrato de datos
(`test_models.py`).

El segundo bloque cubre el flujo completo de T8: `_embed_chunks` normaliza cada
fila y envía el texto exacto, `index_file` conserva las otras rutas, reindexa sin
mezclar versiones y deja intacto el índice en cualquier rechazo, y el recorrido
indexar → buscar devuelve las citas de la spec 001 (RF-1, RF-11, RF-12, RF-15,
RF-16, RF-17, RF-18, RF-19, RF-22, RF-25, RNF-5).

No descargan el modelo, no usan red, no usan claves y no llaman a Anthropic: los
embeddings se calculan con un doble que registra los textos recibidos.
"""

from __future__ import annotations

import numpy as np
import pytest

from app import rag
from app.models import Chunk, IndexReason, IndexResult, SearchResponse
from app.storage import VectorStore


def rejection_cases() -> list[tuple[IndexReason, dict[str, int], str]]:
    """Casos de rechazo con los datos que exige cada mensaje y una cifra suya."""
    return [
        (IndexReason.EMPTY_CONTENT, {}, "vacío"),
        (IndexReason.TOO_LARGE, {"size": 1_048_577}, "1.048.576"),
        (IndexReason.TOO_MANY_CHUNKS, {"produced": 1_001}, "1.000"),
        (IndexReason.EMBEDDING_FAILED, {}, "archivo no indexable"),
    ]


def test_limits_match_the_spec() -> None:
    """El tamaño y el tope son los que fija la spec, no otros valores."""
    assert rag.MAX_FILE_BYTES == 1_048_576
    assert rag.MAX_CHUNKS_PER_FILE == 1_000


# --- `_validate_content` (RF-13, RF-14) ------------------------------------


@pytest.mark.parametrize("source", ["", "   ", "\n\n", "\t \n \n", "\r\n\t\r\n"])
def test_validate_content_rejects_empty_or_blank_content(source: str) -> None:
    """Un texto vacío o de solo blancos se rechaza como contenido vacío."""
    result = rag._validate_content(source)

    assert result is not None
    reason, message = result
    assert reason is IndexReason.EMPTY_CONTENT
    assert message == rag._rejection_message(IndexReason.EMPTY_CONTENT)


def test_validate_content_checks_emptiness_before_the_size() -> None:
    """1.100.000 espacios ocupan más de 1 MiB y aun así se rechazan por vacío."""
    source = " " * 1_100_000

    assert len(source.encode("utf-8")) > rag.MAX_FILE_BYTES
    result = rag._validate_content(source)

    assert result is not None
    reason, message = result
    assert reason is IndexReason.EMPTY_CONTENT
    assert message == rag._rejection_message(IndexReason.EMPTY_CONTENT)


def test_validate_content_accepts_exactly_one_mib() -> None:
    """1.048.576 bytes UTF-8 es el límite permitido y se acepta (RF-14)."""
    source = "a" * rag.MAX_FILE_BYTES

    assert len(source.encode("utf-8")) == 1_048_576
    assert rag._validate_content(source) is None


def test_validate_content_rejects_one_byte_over_one_mib() -> None:
    """1.048.577 bytes se rechazan e informan del límite y del tamaño recibido."""
    source = "a" * (rag.MAX_FILE_BYTES + 1)

    result = rag._validate_content(source)

    assert result is not None
    reason, message = result
    assert reason is IndexReason.TOO_LARGE
    assert message == rag._rejection_message(IndexReason.TOO_LARGE, size=1_048_577)
    assert "1.048.576" in message
    assert "1.048.577" in message


def test_validate_content_measures_utf8_bytes_not_characters() -> None:
    """600.000 caracteres de dos bytes superan 1 MiB aunque no sean tantos."""
    source = "ñ" * 600_000

    assert len(source) < rag.MAX_FILE_BYTES
    assert len(source.encode("utf-8")) > rag.MAX_FILE_BYTES

    result = rag._validate_content(source)

    assert result is not None
    reason, message = result
    assert reason is IndexReason.TOO_LARGE
    assert "1.200.000" in message


def test_validate_content_accepts_blank_line_around_code() -> None:
    """Un contenido con código y blancos en los bordes es válido."""
    assert rag._validate_content("\n\nx = 1\n\n") is None


# --- Tope de fragmentos (RF-21) --------------------------------------------


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, False), (1, False), (999, False), (1_000, False), (1_001, True)],
)
def test_too_many_chunks_uses_the_limit_of_one_thousand(
    count: int, expected: bool
) -> None:
    """1.000 fragmentos caben; 1.001 ya superan el tope."""
    assert rag._too_many_chunks(count) is expected


def test_cap_rejection_message_contains_the_limit_and_the_produced_count() -> None:
    """El rechazo por tope dice el tope y la cantidad que habría producido."""
    message = rag._rejection_message(IndexReason.TOO_MANY_CHUNKS, produced=1_001)

    assert "1.000" in message
    assert "1.001" in message


def test_cap_rejection_does_not_need_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decidir y explicar el tope no calcula ninguna representación semántica.

    T8 comprobará que `index_file` llama a esta comprobación antes de embeber;
    aquí se fija que ni el criterio ni el mensaje dependen de los embeddings.
    """

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("un rechazo por tope no debe calcular embeddings")

    monkeypatch.setattr(rag, "_embed_chunks", fail, raising=False)

    assert rag._too_many_chunks(1_001) is True
    assert "1.001" in rag._rejection_message(
        IndexReason.TOO_MANY_CHUNKS, produced=1_001
    )


# --- Mensajes de rechazo (RNF-3) -------------------------------------------


@pytest.mark.parametrize(
    ("reason", "kwargs", "required_figure"),
    rejection_cases(),
    ids=[reason.value for reason, _, _ in rejection_cases()],
)
def test_rejection_messages_are_in_spanish_and_carry_their_figures(
    reason: IndexReason, kwargs: dict[str, int], required_figure: str
) -> None:
    """Cada rechazo explica en español el motivo y la cifra que exige RNF-3."""
    message = rag._rejection_message(reason, **kwargs)

    assert required_figure in message
    assert "no se ha" in message.lower()
    assert message.endswith(".")


@pytest.mark.parametrize(
    ("reason", "kwargs", "required_figure"),
    rejection_cases(),
    ids=[reason.value for reason, _, _ in rejection_cases()],
)
def test_rejection_messages_avoid_machine_jargon(
    reason: IndexReason, kwargs: dict[str, int], required_figure: str
) -> None:
    """No se muestran códigos internos ni palabras propias de un error técnico."""
    message = rag._rejection_message(reason, **kwargs)
    lowered = message.lower()

    for jargon in ("error", "exception", "traceback", "embedding", "none"):
        assert jargon not in lowered
    assert "_" not in message


def test_empty_content_message_says_the_file_is_empty() -> None:
    """El rechazo por vacío indica que el archivo no tiene contenido."""
    message = rag._rejection_message(IndexReason.EMPTY_CONTENT)

    assert "vacío" in message
    assert message == rag.EMPTY_CONTENT_MESSAGE


def test_too_large_message_says_the_limit_in_bytes_and_the_received_size() -> None:
    """El rechazo por tamaño incluye 1.048.576 y el tamaño recibido en bytes."""
    message = rag._rejection_message(IndexReason.TOO_LARGE, size=1_200_000)

    assert "1.048.576" in message
    assert "1.200.000" in message
    assert "1 MiB" in message


def test_embedding_failure_message_uses_the_wording_of_the_spec() -> None:
    """RNF-3 exige la expresión "archivo no indexable" en este rechazo."""
    message = rag._rejection_message(IndexReason.EMBEDDING_FAILED)

    assert "archivo no indexable" in message
    assert message == rag.EMBEDDING_FAILED_MESSAGE


@pytest.mark.parametrize("reason", [IndexReason.TOO_LARGE, IndexReason.TOO_MANY_CHUNKS])
def test_rejection_message_requires_the_number_of_the_case(
    reason: IndexReason,
) -> None:
    """Sin el tamaño o la cantidad, construir el mensaje es un fallo de código."""
    with pytest.raises(ValueError):
        rag._rejection_message(reason)


# --- Mensaje de éxito (RF-10, RF-24) ---------------------------------------


def test_success_message_includes_file_chunks_and_index_total() -> None:
    """El mensaje informa de ese archivo y del total del índice, en ese orden."""
    message = rag._success_message(
        chunks_indexed=4, total_chunks=12, used_windows=False
    )

    assert "4 fragmentos" in message
    assert "12 fragmentos" in message
    assert message.index("4 fragmentos") < message.index("12 fragmentos")


def test_success_message_adds_the_window_note_only_when_used() -> None:
    """El aviso de troceado aproximado solo aparece con `used_windows=True`."""
    plain = rag._success_message(chunks_indexed=3, total_chunks=9, used_windows=False)
    windows = rag._success_message(chunks_indexed=3, total_chunks=9, used_windows=True)

    assert "ventana" not in plain.lower()
    assert windows.startswith(plain)
    assert "ventana" in windows.lower()
    assert "aproximado" in windows.lower()


def test_success_message_formats_thousands_with_a_dot() -> None:
    """Los números grandes se agrupan de tres en tres con punto."""
    message = rag._success_message(
        chunks_indexed=1_000, total_chunks=2_000, used_windows=False
    )

    assert "1.000 fragmentos" in message
    assert "2.000 fragmentos" in message


def test_success_message_uses_the_singular_for_one_fragment() -> None:
    """Un solo fragmento se dice en singular, sin sonar a traducción automática."""
    message = rag._success_message(chunks_indexed=1, total_chunks=1, used_windows=False)

    assert "1 fragmento" in message
    assert "1 fragmentos" not in message


def test_success_message_has_no_machine_jargon() -> None:
    """El éxito también se cuenta en español, sin códigos ni términos técnicos."""
    message = rag._success_message(chunks_indexed=4, total_chunks=12, used_windows=True)

    assert "_" not in message
    assert "error" not in message.lower()
    assert "embedding" not in message.lower()


# --- Doble de embeddings y utilidades del flujo completo (T8) ---------------


class RecordingModel:
    """Doble del modelo de embeddings que registra los textos que recibe.

    Devuelve filas deliberadamente **sin normalizar** (`[i+1, 1, 1]`), para que
    la prueba distinga la renormalización de `_embed_chunks` de lo que hiciera el
    modelo. Puede fallar en la fila `fail_at` y guardar en `seen` solo los
    primeros `keep_chars` caracteres de cada texto, como haría un modelo real que
    trunca (RNF-7), sin alterar el texto que se guarda en el índice.
    """

    def __init__(
        self,
        *,
        dimensions: int = 3,
        fail_at: int | None = None,
        keep_chars: int | None = None,
    ) -> None:
        """Configura dimensión, fila que falla y truncado del doble."""
        self.dimensions = dimensions
        self.fail_at = fail_at
        self.keep_chars = keep_chars
        self.texts: list[str] = []
        self.seen: list[str] = []

    def encode(self, texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        """Registra los textos y devuelve una fila distinta, no normalizada, por texto."""
        rows: list[list[float]] = []
        for index, text in enumerate(texts):
            if self.fail_at is not None and index == self.fail_at:
                raise RuntimeError("fallo simulado del modelo de embeddings")
            self.texts.append(text)
            self.seen.append(
                text if self.keep_chars is None else text[: self.keep_chars]
            )
            rows.append([float(index + 1)] + [1.0] * (self.dimensions - 1))
        return np.array(rows, dtype=np.float32)


@pytest.fixture(autouse=True)
def clean_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sustituye el singleton en memoria por uno vacío en cada prueba."""
    monkeypatch.setattr(rag, "store", VectorStore())


def snapshot(dimensions: int = 3) -> list[Chunk]:
    """Devuelve los fragmentos del índice en orden de inserción.

    Se consulta con el vector cero: todas las puntuaciones empatan y el orden
    estable de `search` coincide con el orden en que se indexaron.
    """
    query = np.zeros(dimensions, dtype=np.float32)
    results = rag.store.search(query, top_k=10_000)
    return [result.chunk for result in results]


def functions_source(prefix: str, count: int) -> str:
    """Construye un archivo con `count` funciones de dos líneas cada una."""
    return "".join(
        f"def {prefix}{index}():\n    return {index}\n" for index in range(count)
    )


def fail_embedding(chunks: list[Chunk]) -> np.ndarray:
    """Doble que falla si un rechazo llega a calcular embeddings."""
    raise AssertionError("un rechazo no debe calcular embeddings")


AUTH_SOURCE = """import os


def login(user):
    return check(user)


def logout(user):
    return None
"""


def rejection_inputs() -> list[tuple[str, str, IndexReason]]:
    """Contenidos que deben rechazarse con cada motivo, sin tocar el índice."""
    return [
        ("vacio", "", IndexReason.EMPTY_CONTENT),
        ("demasiado_grande", "a" * (rag.MAX_FILE_BYTES + 1), IndexReason.TOO_LARGE),
        (
            "demasiados_fragmentos",
            functions_source("f", rag.MAX_CHUNKS_PER_FILE + 1),
            IndexReason.TOO_MANY_CHUNKS,
        ),
    ]


# --- `_embed_chunks` (RF-11, RNF-7) ----------------------------------------


def test_embed_chunks_normalizes_every_row_and_sends_exact_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada fila queda con norma 1 y el modelo recibe los `content` exactos."""
    chunks = rag.chunk_python_file(AUTH_SOURCE, "app/auth.py")
    model = RecordingModel(dimensions=3)
    monkeypatch.setattr(rag, "_get_model", lambda: model)

    matrix = rag._embed_chunks(chunks)

    assert matrix.shape == (len(chunks), 3)
    assert matrix.dtype == np.float32
    norms = np.linalg.norm(matrix, axis=1)
    assert all(abs(float(norm) - 1.0) <= 1e-5 for norm in norms)
    assert model.texts == [chunk.content for chunk in chunks]


def test_embed_chunks_does_not_trim_what_the_model_receives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El doble trunca su copia, pero `_embed_chunks` le entrega el texto entero."""
    source = "def login(user):\n    return user\n"
    chunks = rag.chunk_python_file(source, "app/auth.py")
    model = RecordingModel(keep_chars=5)
    monkeypatch.setattr(rag, "_get_model", lambda: model)

    matrix = rag._embed_chunks(chunks)

    assert model.texts == [chunk.content for chunk in chunks]
    assert model.texts[0] == "def login(user):\n    return user"
    assert model.seen[0] == "def l"
    assert matrix.shape[0] == len(chunks)


# --- Éxito de `index_file` (RF-1, RF-11, RF-12, RF-24) ----------------------


def test_index_file_indexes_every_chunk_and_reports_the_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El éxito informa de los fragmentos del archivo y del total del índice."""
    model = RecordingModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)

    result = rag.index_file("app/auth.py", AUTH_SOURCE)

    chunks = rag.chunk_python_file(AUTH_SOURCE, "app/auth.py")
    assert isinstance(result, IndexResult)
    assert result.reason is None
    assert result.file_path == "app/auth.py"
    assert result.chunks_indexed == len(chunks)
    assert result.total_chunks == rag.store.count == len(chunks)
    assert result.used_windows is False
    assert "indexado" in result.message.lower()
    assert f"{len(chunks)} fragmentos" in result.message
    assert "ventana" not in result.message.lower()
    assert snapshot() == chunks
    assert model.texts == [chunk.content for chunk in chunks]


def test_a_2000_line_function_is_stored_and_cited_in_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fragmento de 2.000 líneas se guarda entero aunque el modelo lo trunque."""
    source = "def huge():\n" + "    x = 1\n" * 1999
    model = RecordingModel(keep_chars=100)
    monkeypatch.setattr(rag, "_get_model", lambda: model)

    result = rag.index_file("app/huge.py", source)

    assert result.chunks_indexed == 1
    stored = snapshot()
    assert [chunk.symbol_name for chunk in stored] == ["huge"]
    assert stored[0].content == source[:-1]
    assert len(stored[0].content) > 100
    assert model.seen == [source[:-1][:100]]

    monkeypatch.setattr(
        rag,
        "_embed_query",
        lambda query: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )
    response = rag.search("¿Dónde está el código largo?")

    assert response.results[0].chunk == stored[0]
    assert response.results[0].chunk.content == source[:-1]


def test_success_reports_when_the_file_was_chunked_by_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un contenido no analizable se indexa por ventanas y el mensaje lo avisa."""
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel())

    result = rag.index_file("app/notas.txt", "Esto no es Python\n" * 3)

    assert result.reason is None
    assert result.used_windows is True
    assert "ventana" in result.message.lower()
    assert all(chunk.kind == "window" for chunk in snapshot())


# --- Varias rutas y reindexado (RF-15, RF-16, RF-17, RF-18) -----------------


def test_indexing_a_second_path_keeps_the_first_and_does_not_empty_the_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Indexar otra ruta añade sus fragmentos sin tocar los anteriores."""
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel())

    first = rag.index_file("app/auth.py", AUTH_SOURCE)
    second = rag.index_file("app/billing.py", functions_source("pay", 2))

    auth_chunks = rag.chunk_python_file(AUTH_SOURCE, "app/auth.py")
    billing_chunks = rag.chunk_python_file(functions_source("pay", 2), "app/billing.py")
    assert first.total_chunks == len(auth_chunks)
    assert (
        second.total_chunks == rag.store.count == len(auth_chunks) + len(billing_chunks)
    )
    assert snapshot() == auth_chunks + billing_chunks
    assert {chunk.file_path for chunk in snapshot()} == {
        "app/auth.py",
        "app/billing.py",
    }


def test_the_same_symbol_in_two_paths_stays_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El mismo símbolo en dos archivos son dos fragmentos, cada uno con su ruta."""
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel())
    source = "def login():\n    return True\n"

    rag.index_file("app/a.py", source)
    result = rag.index_file("app/b.py", source)

    assert result.total_chunks == 2
    assert [(chunk.file_path, chunk.symbol_name) for chunk in snapshot()] == [
        ("app/a.py", "login"),
        ("app/b.py", "login"),
    ]


def test_reindexing_the_same_file_keeps_the_same_chunks_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Indexar dos veces no duplica, no reordena y deja el mismo `count`."""
    model = RecordingModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)

    first = rag.index_file("app/auth.py", AUTH_SOURCE)
    before = snapshot()
    second = rag.index_file("app/auth.py", AUTH_SOURCE)

    assert snapshot() == before
    assert second.chunks_indexed == first.chunks_indexed
    assert second.total_chunks == first.total_chunks == rag.store.count
    assert len(model.texts) == 2 * len(before)


def test_reindexing_replaces_three_chunks_with_seven_and_back_to_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una re-subida deja solo los fragmentos nuevos de esa ruta (RF-18)."""
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel())

    rag.index_file("app/rag.py", functions_source("old", 3))
    seven = rag.index_file("app/rag.py", functions_source("new", 7))

    assert seven.chunks_indexed == 7
    assert seven.total_chunks == rag.store.count == 7
    assert [chunk.symbol_name for chunk in snapshot()] == [
        f"new{index}" for index in range(7)
    ]

    three = rag.index_file("app/rag.py", functions_source("last", 3))

    assert three.chunks_indexed == 3
    assert three.total_chunks == rag.store.count == 3
    assert [chunk.symbol_name for chunk in snapshot()] == [
        f"last{index}" for index in range(3)
    ]


# --- Fallo de embeddings y atomicidad (RF-19, RF-22, RF-25) -----------------


def test_a_mid_reindex_embedding_failure_keeps_the_previous_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si falla la segunda fila, el índice conserva y encuentra la versión anterior."""
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel())
    first = rag.index_file("app/rag.py", functions_source("old", 3))
    before = snapshot()

    failing = RecordingModel(fail_at=1)
    monkeypatch.setattr(rag, "_get_model", lambda: failing)
    monkeypatch.setattr(
        rag,
        "_embed_query",
        lambda query: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )

    result = rag.index_file("app/rag.py", functions_source("new", 5))

    assert result.reason is IndexReason.EMBEDDING_FAILED
    assert result.chunks_indexed == 0
    assert result.total_chunks == first.total_chunks == rag.store.count
    assert result.message == rag.EMBEDDING_FAILED_MESSAGE
    assert "archivo no indexable" in result.message
    assert snapshot() == before

    response = rag.search("¿Dónde está el código viejo?")
    found = [result.chunk.symbol_name for result in response.results]
    assert sorted(found) == sorted(chunk.symbol_name for chunk in before)


def test_an_embedding_failure_on_a_new_path_adds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fallo al embeber una ruta nueva no deja fragmentos a medias."""
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel(fail_at=0))

    result = rag.index_file("app/auth.py", AUTH_SOURCE)

    assert result.reason is IndexReason.EMBEDDING_FAILED
    assert result.chunks_indexed == 0
    assert result.total_chunks == rag.store.count == 0


@pytest.mark.parametrize(
    ("case", "source", "reason"),
    rejection_inputs(),
    ids=[case for case, _, _ in rejection_inputs()],
)
def test_a_rejected_reindex_keeps_the_previous_version(
    monkeypatch: pytest.MonkeyPatch, case: str, source: str, reason: IndexReason
) -> None:
    """Vacío, tamaño o tope dejan la versión anterior intacta y no embeben."""
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel())
    rag.index_file("app/rag.py", functions_source("old", 3))
    before = snapshot()
    monkeypatch.setattr(rag, "_embed_chunks", fail_embedding)

    result = rag.index_file("app/rag.py", source)

    assert result.reason is reason
    assert result.chunks_indexed == 0
    assert result.total_chunks == len(before)
    assert snapshot() == before


@pytest.mark.parametrize(
    ("case", "source", "reason"),
    rejection_inputs(),
    ids=[case for case, _, _ in rejection_inputs()],
)
def test_a_rejected_new_path_adds_nothing(
    monkeypatch: pytest.MonkeyPatch, case: str, source: str, reason: IndexReason
) -> None:
    """En una ruta nueva, un rechazo no añade nada al índice."""
    monkeypatch.setattr(rag, "_embed_chunks", fail_embedding)

    result = rag.index_file("app/nuevo.py", source)

    assert result.reason is reason
    assert result.chunks_indexed == 0
    assert result.total_chunks == rag.store.count == 0
    assert snapshot() == []


def test_the_chunk_cap_rejects_before_calculating_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1.001 fragmentos se rechazan antes de llamar al modelo de embeddings."""
    monkeypatch.setattr(rag, "_embed_chunks", fail_embedding)
    source = functions_source("f", rag.MAX_CHUNKS_PER_FILE + 1)

    result = rag.index_file("app/huge.py", source)

    assert result.reason is IndexReason.TOO_MANY_CHUNKS
    assert "1.000" in result.message
    assert "1.001" in result.message
    assert rag.store.count == 0


def test_index_file_accepts_exactly_the_chunk_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un archivo que produce justo 1.000 fragmentos se indexa entero (RF-21)."""
    model = RecordingModel()
    monkeypatch.setattr(rag, "_get_model", lambda: model)
    source = functions_source("f", rag.MAX_CHUNKS_PER_FILE)

    result = rag.index_file("app/limite.py", source)

    assert result.reason is None
    assert result.chunks_indexed == rag.MAX_CHUNKS_PER_FILE
    assert result.total_chunks == rag.store.count == rag.MAX_CHUNKS_PER_FILE
    assert len(model.texts) == rag.MAX_CHUNKS_PER_FILE


def test_the_size_check_runs_before_the_chunk_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un archivo grande y con más de 1.000 fragmentos se rechaza por tamaño.

    Es el caso de orden que faltaba (RF-14 antes que RF-21): el contenido supera
    a la vez 1 MiB y el tope de 1.000 fragmentos. Se rellena cada función con un
    comentario largo para pasar de 1 MiB sin construir cadenas absurdas; el
    troceado daría 1.001 fragmentos, pero `index_file` no llega a trocear porque
    la validación de tamaño corta antes y `_embed_chunks` no se llama.
    """
    padding = "# " + "x" * 1_040
    source = "".join(
        f"{padding}\ndef f{index}():\n    return {index}\n"
        for index in range(rag.MAX_CHUNKS_PER_FILE + 1)
    )
    size = len(source.encode("utf-8"))
    monkeypatch.setattr(rag, "_embed_chunks", fail_embedding)

    assert size > rag.MAX_FILE_BYTES
    assert len(rag.chunk_python_file(source, "app/grande.py")) > (
        rag.MAX_CHUNKS_PER_FILE
    )

    result = rag.index_file("app/grande.py", source)

    assert result.reason is IndexReason.TOO_LARGE
    assert result.message == rag._rejection_message(IndexReason.TOO_LARGE, size=size)
    assert "1.048.576" in result.message
    assert result.chunks_indexed == 0
    assert rag.store.count == 0


# --- Recorrido completo indexar → buscar (RF-1, RF-12, RNF-5) ---------------


def test_index_then_search_returns_the_cited_fragment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tras indexar, la búsqueda devuelve ruta, símbolo, líneas y texto correctos."""
    source = "def login(user):\n    return user == 'admin'\n"
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel())
    rag.index_file("app/auth.py", source)
    monkeypatch.setattr(
        rag,
        "_embed_query",
        lambda query: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )

    response = rag.search("¿Dónde se valida el usuario?")

    assert isinstance(response, SearchResponse)
    assert response.reason is None
    chunk = response.results[0].chunk
    assert chunk.file_path == "app/auth.py"
    assert chunk.symbol_name == "login"
    assert chunk.start_line == 1
    assert chunk.end_line == 2
    assert chunk.content == source[:-1]


def test_a_module_only_file_is_indexed_and_found_by_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un archivo solo de configuración produce un `module` buscable (RF-1, RF-12)."""
    source = 'import os\n\nDEBUG = False\nVERSION = "1.0"\n'
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel())

    result = rag.index_file("app/config.py", source)

    assert result.reason is None
    assert result.chunks_indexed == 1
    monkeypatch.setattr(
        rag,
        "_embed_query",
        lambda query: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )

    response = rag.search("¿Dónde se configura la versión?")

    chunk = response.results[0].chunk
    assert chunk.kind == "module"
    assert chunk.symbol_name == "module"
    assert chunk.file_path == "app/config.py"
    assert (chunk.start_line, chunk.end_line) == (1, 4)
    assert "VERSION" in chunk.content


def test_search_after_indexing_keeps_the_contract_of_spec_001(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La búsqueda de la 001 consume el índice sin cambiar umbral ni máximo."""
    monkeypatch.setattr(rag, "_get_model", lambda: RecordingModel())
    rag.index_file("app/many.py", functions_source("f", 7))
    monkeypatch.setattr(
        rag,
        "_embed_query",
        lambda query: np.array([1.0, 0.0, 0.0], dtype=np.float32),
    )

    response = rag.search("funciones")

    assert rag.MAX_RESULTS == 5
    assert rag.MIN_SCORE == pytest.approx(0.30)
    assert len(response.results) == rag.MAX_RESULTS
    assert all(result.score >= rag.MIN_SCORE for result in response.results)
