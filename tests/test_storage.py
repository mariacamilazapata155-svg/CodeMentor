"""Pruebas del repositorio de vectores en memoria.

Comprueban solo lo que `storage.py` promete: guardar chunks con sus embeddings,
contar, ordenar por similitud, deduplicar, recortar a `top_k` y vaciarse.
Tampoco prueban umbrales, normalización de consultas ni generación de
embeddings. Al final se comprueba que cada operación pública adquiere y libera
el bloqueo interno, que es lo que permite atender peticiones simultáneas.
"""

from types import TracebackType
from typing import Self

import numpy as np
import pytest

from app.models import Chunk, SearchResult
from app.storage import VectorStore


def make_chunk(
    file_path: str = "app/rag.py",
    symbol_name: str = "search",
    start_line: int | None = None,
    end_line: int | None = None,
) -> Chunk:
    """Crea un chunk identificable por ruta, símbolo y rango de líneas.

    Si no se indica el rango, se deriva del nombre del símbolo para que dos
    símbolos distintos no compartan la misma clave de deduplicación.
    """
    base = sum(ord(char) for char in symbol_name)
    start = base if start_line is None else start_line
    end = start + 4 if end_line is None else end_line
    return Chunk(
        file_path=file_path,
        symbol_name=symbol_name,
        start_line=start,
        end_line=end,
        content=f"def {symbol_name}(): ...",
        kind="function",
    )


def matrix(*rows: tuple[float, ...]) -> np.ndarray:
    """Construye una matriz de embeddings falsos en `float32`."""
    return np.array(rows, dtype=np.float32)


def chunks_of(file_path: str, names: tuple[str, ...]) -> list[Chunk]:
    """Crea un fragmento por nombre, con rangos distintos, dentro de una ruta."""
    return [
        make_chunk(
            file_path=file_path,
            symbol_name=name,
            start_line=index * 10 + 1,
            end_line=index * 10 + 5,
        )
        for index, name in enumerate(names)
    ]


def tied_matrix(rows: int, dimensions: int = 2) -> np.ndarray:
    """Matriz de vectores idénticos: todas las puntuaciones empatan.

    Así `search` devuelve los fragmentos en orden de inserción y sirve para
    observar el índice sin tocar sus atributos privados.
    """
    return np.full((rows, dimensions), 0.5, dtype=np.float32)


def snapshot(store: VectorStore) -> list[SearchResult]:
    """Retrata fragmentos y puntuaciones en orden de inserción."""
    return store.search(tied_matrix(1), top_k=100)


def test_add_keeps_chunks_and_count_grows() -> None:
    """Añadir chunks incrementa el contador y no pierde los anteriores."""
    store = VectorStore()
    assert store.count == 0

    store.add(
        [make_chunk(symbol_name="a"), make_chunk(symbol_name="b")],
        matrix((1, 0), (0, 1)),
    )
    assert store.count == 2

    store.add([make_chunk(symbol_name="c")], matrix((0.5, 0.5)))
    assert store.count == 3


def test_add_rejects_embeddings_that_do_not_match_chunks() -> None:
    """Si hay menos filas que chunks, el almacén lo rechaza en vez de mezclar datos."""
    store = VectorStore()

    with pytest.raises(ValueError):
        store.add(
            [make_chunk(symbol_name="a"), make_chunk(symbol_name="b")], matrix((1, 0))
        )


def test_add_rejects_a_different_number_of_dimensions() -> None:
    """No se pueden mezclar embeddings de distinta dimensión en el mismo índice."""
    store = VectorStore()
    store.add([make_chunk(symbol_name="a")], matrix((1, 0)))

    with pytest.raises(ValueError):
        store.add([make_chunk(symbol_name="b")], matrix((1, 0, 0)))


def test_add_rejects_embeddings_that_are_not_a_matrix() -> None:
    """Un vector suelto no es una matriz válida: `add` lo rechaza sin tocar el índice."""
    store = VectorStore()
    store.add([make_chunk(symbol_name="a")], matrix((1, 0)))

    with pytest.raises(ValueError):
        store.add([make_chunk(symbol_name="b")], np.array([1.0, 0.0], dtype=np.float32))

    assert store.count == 1


def test_search_orders_by_descending_score() -> None:
    """El fragmento más parecido a la consulta sale primero."""
    store = VectorStore()
    store.add(
        [
            make_chunk(symbol_name="a"),
            make_chunk(symbol_name="b"),
            make_chunk(symbol_name="c"),
        ],
        matrix((1, 0), (0, 1), (0.5, 0.5)),
    )

    results = store.search(matrix((1, 0)), top_k=3)

    assert [result.chunk.symbol_name for result in results] == ["a", "c", "b"]
    assert results[0].score == pytest.approx(1.0)
    assert results[1].score == pytest.approx(0.5)


def test_search_limits_results_to_top_k() -> None:
    """Se devuelven como mucho `top_k` fragmentos."""
    store = VectorStore()
    store.add(
        [make_chunk(symbol_name=name) for name in ("a", "b", "c")],
        matrix((1, 0), (0.8, 0.2), (0.5, 0.5)),
    )

    results = store.search(matrix((1, 0)), top_k=2)

    assert [result.chunk.symbol_name for result in results] == ["a", "b"]


def test_search_keeps_insertion_order_when_scores_tie() -> None:
    """Con la misma puntuación, el orden es estable y determinista."""
    store = VectorStore()
    store.add(
        [make_chunk(symbol_name="first"), make_chunk(symbol_name="second")],
        matrix((0.5, 0.5), (0.5, 0.5)),
    )

    results = store.search(matrix((1, 0)), top_k=2)

    assert [result.chunk.symbol_name for result in results] == ["first", "second"]


def test_search_returns_a_duplicated_fragment_only_once() -> None:
    """Misma ruta y mismo rango de líneas cuenta como un único fragmento."""
    duplicate = make_chunk(symbol_name="search")
    store = VectorStore()
    store.add(
        [
            duplicate,
            make_chunk(symbol_name="other", start_line=10, end_line=12),
            duplicate,
        ],
        matrix((1, 0), (0, 1), (1, 0)),
    )

    results = store.search(matrix((1, 0)), top_k=3)

    assert [result.chunk.symbol_name for result in results] == ["search", "other"]


def test_search_returns_the_other_file_with_the_same_symbol() -> None:
    """El mismo símbolo en archivos distintos son fragmentos distintos."""
    store = VectorStore()
    store.add(
        [
            make_chunk(file_path="app/rag.py", symbol_name="search"),
            make_chunk(file_path="app/bot.py", symbol_name="search"),
        ],
        matrix((1, 0), (0.9, 0.1)),
    )

    results = store.search(matrix((1, 0)), top_k=5)

    assert [result.chunk.file_path for result in results] == [
        "app/rag.py",
        "app/bot.py",
    ]


def test_search_returns_everything_when_fewer_than_five_pass() -> None:
    """Con menos de cinco fragmentos, se devuelven los que hay."""
    store = VectorStore()
    store.add(
        [make_chunk(symbol_name=name) for name in ("a", "b", "c")],
        matrix((1, 0), (0.8, 0.2), (0.6, 0.4)),
    )

    results = store.search(matrix((1, 0)), top_k=5)

    assert len(results) == 3


def test_search_with_a_single_fragment() -> None:
    """Un único fragmento indexado se devuelve solo."""
    store = VectorStore()
    store.add([make_chunk(symbol_name="only")], matrix((1, 0)))

    results = store.search(matrix((1, 0)), top_k=5)

    assert [result.chunk.symbol_name for result in results] == ["only"]


def test_search_on_an_empty_store_returns_nothing() -> None:
    """Sin chunks no hay nada que comparar y no se lanza ninguna excepción."""
    store = VectorStore()

    assert store.search(matrix((1, 0)), top_k=5) == []


def test_search_with_non_positive_top_k_returns_nothing() -> None:
    """Pedir cero o menos resultados devuelve una lista vacía."""
    store = VectorStore()
    store.add([make_chunk(symbol_name="a")], matrix((1, 0)))

    assert store.search(matrix((1, 0)), top_k=0) == []
    assert store.search(matrix((1, 0)), top_k=-3) == []


def test_search_rejects_a_query_with_another_dimension() -> None:
    """Una consulta de dimensión distinta se rechaza en vez de dar puntuaciones falsas."""
    store = VectorStore()
    store.add([make_chunk(symbol_name="a")], matrix((1, 0)))

    with pytest.raises(ValueError):
        store.search(matrix((1, 0, 0)), top_k=5)


def test_clear_empties_the_store() -> None:
    """Tras `clear` no quedan chunks ni resultados."""
    store = VectorStore()
    store.add([make_chunk(symbol_name="a")], matrix((1, 0)))

    store.clear()

    assert store.count == 0
    assert store.search(matrix((1, 0)), top_k=5) == []


def test_dedupe_key_uses_path_and_line_range() -> None:
    """La clave de deduplicación es ruta, línea inicial y línea final."""
    chunk = make_chunk(file_path="app/bot.py", start_line=7, end_line=19)

    assert VectorStore._dedupe_key(SearchResult(chunk=chunk, score=0.5)) == (
        "app/bot.py",
        7,
        19,
    )


def test_replace_path_swaps_three_chunks_for_seven() -> None:
    """Reindexar una ruta deja sus fragmentos nuevos y ninguno de los antiguos."""
    store = VectorStore()
    store.add(chunks_of("app/rag.py", ("old_a", "old_b", "old_c")), tied_matrix(3))
    store.add(chunks_of("app/bot.py", ("bot",)), tied_matrix(1))

    store.replace_path(
        "app/rag.py",
        chunks_of("app/rag.py", tuple(f"new_{n}" for n in range(7))),
        tied_matrix(7),
    )

    indexed = snapshot(store)
    assert store.count == 8
    assert [
        result.chunk.symbol_name
        for result in indexed
        if result.chunk.file_path == "app/rag.py"
    ] == [f"new_{n}" for n in range(7)]
    assert [
        result.chunk.symbol_name
        for result in indexed
        if result.chunk.file_path == "app/bot.py"
    ] == ["bot"]


def test_replace_path_swaps_seven_chunks_for_three() -> None:
    """Al contrario, una ruta que tenía siete fragmentos puede quedarse con tres."""
    store = VectorStore()
    store.add(
        chunks_of("app/rag.py", tuple(f"old_{n}" for n in range(7))), tied_matrix(7)
    )
    store.add(chunks_of("app/bot.py", ("bot",)), tied_matrix(1))

    store.replace_path(
        "app/rag.py",
        chunks_of("app/rag.py", ("new_a", "new_b", "new_c")),
        tied_matrix(3),
    )

    assert store.count == 4
    assert [
        result.chunk.symbol_name
        for result in snapshot(store)
        if result.chunk.file_path == "app/rag.py"
    ] == ["new_a", "new_b", "new_c"]


def test_replace_path_indexes_a_path_that_was_not_in_the_index() -> None:
    """Reemplazar una ruta nueva añade sus fragmentos sin tocar las demás rutas."""
    store = VectorStore()
    store.add(chunks_of("app/rag.py", ("a", "b")), tied_matrix(2))
    store.add(chunks_of("app/bot.py", ("c",)), tied_matrix(1))

    store.replace_path(
        "app/new.py", chunks_of("app/new.py", ("n1", "n2")), tied_matrix(2)
    )

    assert store.count == 5
    assert [
        (result.chunk.file_path, result.chunk.symbol_name) for result in snapshot(store)
    ] == [
        ("app/rag.py", "a"),
        ("app/rag.py", "b"),
        ("app/bot.py", "c"),
        ("app/new.py", "n1"),
        ("app/new.py", "n2"),
    ]


def test_replace_path_keeps_the_other_paths_order_and_appends_the_new_chunks() -> None:
    """Las rutas no reemplazadas conservan su orden; los fragmentos nuevos van al final."""
    store = VectorStore()
    store.add(chunks_of("app/rag.py", ("r1", "r2")), tied_matrix(2))
    store.add(chunks_of("app/bot.py", ("b1",)), tied_matrix(1))
    store.add(chunks_of("app/main.py", ("m1",)), tied_matrix(1))

    store.replace_path(
        "app/bot.py", chunks_of("app/bot.py", ("b2", "b3")), tied_matrix(2)
    )

    assert [
        (result.chunk.file_path, result.chunk.symbol_name) for result in snapshot(store)
    ] == [
        ("app/rag.py", "r1"),
        ("app/rag.py", "r2"),
        ("app/main.py", "m1"),
        ("app/bot.py", "b2"),
        ("app/bot.py", "b3"),
    ]


def test_replace_path_replaces_the_only_indexed_path() -> None:
    """Si no queda ninguna otra ruta, la matriz nueva sustituye a la anterior."""
    store = VectorStore()
    store.add(chunks_of("app/rag.py", ("old_a", "old_b")), tied_matrix(2))

    store.replace_path(
        "app/rag.py", chunks_of("app/rag.py", ("n1", "n2", "n3")), tied_matrix(3)
    )

    indexed = snapshot(store)
    assert store.count == 3
    assert [result.chunk.symbol_name for result in indexed] == ["n1", "n2", "n3"]
    assert [result.score for result in indexed] == pytest.approx([0.5, 0.5, 0.5])


def test_replace_path_on_an_empty_store_indexes_the_new_chunks() -> None:
    """En un almacén vacío, reemplazar equivale a indexar la primera ruta."""
    store = VectorStore()

    store.replace_path(
        "app/rag.py", chunks_of("app/rag.py", ("a", "b")), tied_matrix(2)
    )

    assert store.count == 2
    assert [result.chunk.symbol_name for result in snapshot(store)] == ["a", "b"]


def test_replace_path_rejects_a_row_count_mismatch_without_touching_the_index() -> None:
    """Si las filas no coinciden, se rechaza y el índice queda exactamente igual."""
    store = VectorStore()
    store.add(chunks_of("app/rag.py", ("old_a", "old_b")), tied_matrix(2))
    store.add(chunks_of("app/bot.py", ("bot",)), tied_matrix(1))
    before = snapshot(store)

    with pytest.raises(ValueError):
        store.replace_path(
            "app/rag.py", chunks_of("app/rag.py", ("n1", "n2", "n3")), tied_matrix(2)
        )

    assert store.count == 3
    assert snapshot(store) == before


def test_replace_path_rejects_a_dimension_mismatch_without_touching_the_index() -> None:
    """Una dimensión distinta se rechaza antes de escribir: no mezcla ni pierde datos."""
    store = VectorStore()
    store.add(chunks_of("app/rag.py", ("old_a", "old_b")), tied_matrix(2))
    store.add(chunks_of("app/bot.py", ("bot",)), tied_matrix(1))
    before = snapshot(store)

    with pytest.raises(ValueError):
        store.replace_path(
            "app/rag.py", chunks_of("app/rag.py", ("n1", "n2")), tied_matrix(2, 3)
        )

    assert store.count == 3
    assert snapshot(store) == before


class CountingLock:
    """Doble de `RLock` que cuenta cuántas veces se adquiere y se libera.

    Hace visible el bloqueo interno sin depender de sus detalles: si una
    operación no lo usa, los contadores se quedan a cero.
    """

    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> Self:
        self.entered += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.exited += 1
        return False


def with_counting_lock(
    store: VectorStore, monkeypatch: pytest.MonkeyPatch
) -> CountingLock:
    """Cambia el bloqueo de un almacén nuevo por el doble que cuenta accesos.

    Solo se instala sobre instancias locales, nunca sobre el singleton
    `app.storage.store`, y con `raising=False` para que la prueba falle por el
    recuento y no porque el atributo aún no exista.
    """
    lock = CountingLock()
    monkeypatch.setattr(store, "_lock", lock, raising=False)
    return lock


def assert_lock_used_once(lock: CountingLock) -> None:
    """Comprueba que la operación adquirió el bloqueo y lo liberó una sola vez."""
    assert (lock.entered, lock.exited) == (1, 1)


def test_count_acquires_and_releases_the_lock_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leer `count` también entra en la sección crítica: ve una lista completa."""
    store = VectorStore()
    lock = with_counting_lock(store, monkeypatch)

    assert store.count == 0

    assert_lock_used_once(lock)


def test_add_acquires_and_releases_the_lock_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Añadir escribe dos estructuras y lo hace bajo el bloqueo."""
    store = VectorStore()
    lock = with_counting_lock(store, monkeypatch)

    store.add([make_chunk(symbol_name="a")], matrix((1, 0)))

    assert_lock_used_once(lock)


def test_replace_path_acquires_and_releases_the_lock_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reemplazar reasigna dos atributos: la sección crítica los cubre juntos."""
    store = VectorStore()
    lock = with_counting_lock(store, monkeypatch)

    store.replace_path(
        "app/rag.py", chunks_of("app/rag.py", ("a", "b")), tied_matrix(2)
    )

    assert_lock_used_once(lock)


def test_search_acquires_and_releases_the_lock_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Buscar lee chunks y embeddings del mismo estado, bajo el bloqueo."""
    store = VectorStore()
    store.add([make_chunk(symbol_name="a")], matrix((1, 0)))
    lock = with_counting_lock(store, monkeypatch)

    store.search(matrix((1, 0)), top_k=5)

    assert_lock_used_once(lock)


def test_clear_acquires_and_releases_the_lock_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vaciar reasigna los dos atributos dentro del bloqueo."""
    store = VectorStore()
    store.add([make_chunk(symbol_name="a")], matrix((1, 0)))
    lock = with_counting_lock(store, monkeypatch)

    store.clear()

    assert_lock_used_once(lock)
    assert store.count == 0


def test_add_releases_the_lock_when_the_matrix_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la validación falla, el bloqueo se libera igualmente."""
    store = VectorStore()
    lock = with_counting_lock(store, monkeypatch)

    with pytest.raises(ValueError):
        store.add(
            [make_chunk(symbol_name="a"), make_chunk(symbol_name="b")], matrix((1, 0))
        )

    assert_lock_used_once(lock)


def test_search_releases_the_lock_when_the_query_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una consulta de dimensión incorrecta también sale de la sección crítica."""
    store = VectorStore()
    store.add([make_chunk(symbol_name="a")], matrix((1, 0)))
    lock = with_counting_lock(store, monkeypatch)

    with pytest.raises(ValueError):
        store.search(matrix((1, 0, 0)), top_k=5)

    assert_lock_used_once(lock)
