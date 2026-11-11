"""Repositorio de vectores en memoria.

Guarda los chunks indexados junto a sus embeddings y resuelve búsquedas
por similitud. No hace chunking, no genera embeddings, no habla HTTP y no
llama al modelo.

Al ser un singleton en memoria, el índice se pierde al reiniciar el
servidor: es el comportamiento esperado en esta versión.

Las operaciones públicas se ejecutan bajo un bloqueo reentrante porque la API
HTTP atiende peticiones en varios hilos a la vez.
"""

import threading

import numpy as np

from app.models import Chunk, SearchResult


class VectorStore:
    """Almacén en memoria de chunks y sus embeddings.

    No sabe de dónde vienen los datos ni qué significan: solo guarda y busca.
    """

    def __init__(self) -> None:
        """Inicializa el almacén vacío y su bloqueo.

        Aún no guarda nada: solo deja preparadas las estructuras en memoria.
        El bloqueo es un `RLock` porque los métodos públicos pueden llamarse
        entre sí sin quedarse esperándose a sí mismos, y porque protege la
        reasignación de `_chunks` y `_embeddings` que hace `replace_path`: una
        búsqueda concurrente ve el estado anterior completo o el nuevo completo,
        nunca una mezcla.
        """
        self._chunks: list[Chunk] = []
        self._embeddings: np.ndarray | None = None
        self._lock = threading.RLock()

    @property
    def count(self) -> int:
        """Número de chunks guardados en el almacén."""
        with self._lock:
            return len(self._chunks)

    def add(self, chunks: list[Chunk], embeddings: np.ndarray) -> None:
        """Añade chunks y sus embeddings al almacén.

        No genera los embeddings ni valida su contenido: los recibe ya calculados.
        Rechaza matrices cuyas filas no coincidan con los chunks o cuya dimensión
        no encaje con la ya indexada, para no mezclar datos incompatibles.
        """
        with self._lock:
            matrix = self._validate_matrix(chunks, embeddings)

            self._chunks.extend(chunks)
            if self._embeddings is None:
                self._embeddings = matrix
            else:
                self._embeddings = np.vstack([self._embeddings, matrix])

    def replace_path(
        self, file_path: str, chunks: list[Chunk], embeddings: np.ndarray
    ) -> None:
        """Sustituye todos los fragmentos de una ruta por los nuevos.

        No genera embeddings ni decide si un archivo es indexable: recibe los
        datos ya calculados. Valida antes de escribir y solo reasigna al final,
        para que un fallo deje el índice exactamente como estaba. Las rutas que
        no se reemplazan conservan su orden y los fragmentos nuevos van al final.
        """
        with self._lock:
            matrix = self._validate_matrix(chunks, embeddings)
            keep = [
                index
                for index, chunk in enumerate(self._chunks)
                if chunk.file_path != file_path
            ]
            new_chunks = [self._chunks[index] for index in keep] + chunks
            if self._embeddings is None or not keep:
                new_matrix = matrix
            else:
                new_matrix = np.vstack([self._embeddings[keep], matrix])

            self._chunks = new_chunks
            self._embeddings = new_matrix

    def _validate_matrix(
        self, chunks: list[Chunk], embeddings: np.ndarray
    ) -> np.ndarray:
        """Comprueba que la matriz encaje con los chunks y con el índice actual.

        Devuelve la matriz en `float32` y lanza `ValueError` si no es de dos
        dimensiones, si sus filas no coinciden con los chunks o si su dimensión
        no encaja con la ya indexada. No escribe nada en el almacén.
        """
        matrix = np.asarray(embeddings, dtype=np.float32)
        if matrix.ndim != 2:
            raise ValueError("Los embeddings deben ser una matriz de dos dimensiones.")
        if matrix.shape[0] != len(chunks):
            raise ValueError(
                f"Hay {len(chunks)} chunks pero {matrix.shape[0]} embeddings: "
                "deben coincidir fila a fila."
            )
        if (
            self._embeddings is not None
            and matrix.shape[1] != self._embeddings.shape[1]
        ):
            raise ValueError(
                f"Los embeddings tienen {matrix.shape[1]} dimensiones y el índice "
                f"ya guarda {self._embeddings.shape[1]}."
            )
        return matrix

    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> list[SearchResult]:
        """Devuelve los `top_k` chunks más parecidos al embedding de la pregunta.

        No genera el embedding de la consulta ni llama al modelo: solo compara
        vectores ya normalizados con producto punto.
        """
        with self._lock:
            if not self._chunks or self._embeddings is None or top_k <= 0:
                return []

            vector = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
            if vector.shape[0] != self._embeddings.shape[1]:
                raise ValueError(
                    f"El vector de la consulta tiene {vector.shape[0]} dimensiones y "
                    f"el índice guarda {self._embeddings.shape[1]}."
                )

            scores = self._embeddings @ vector
            order = np.argsort(-scores, kind="stable")

            results: list[SearchResult] = []
            seen: set[tuple[str, int, int]] = set()
            for index in order:
                result = SearchResult(
                    chunk=self._chunks[int(index)],
                    score=float(scores[int(index)]),
                )
                key = self._dedupe_key(result)
                if key in seen:
                    continue
                seen.add(key)
                results.append(result)
                if len(results) >= top_k:
                    break

            return results

    def clear(self) -> None:
        """Vacía el almacén para volver a indexar desde cero."""
        with self._lock:
            self._chunks = []
            self._embeddings = None

    @staticmethod
    def _dedupe_key(result: SearchResult) -> tuple[str, int, int]:
        """Identifica un fragmento por ruta y rango de líneas."""
        chunk = result.chunk
        return (chunk.file_path, chunk.start_line, chunk.end_line)


store = VectorStore()
