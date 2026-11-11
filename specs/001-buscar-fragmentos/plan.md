# Plan 001 — Buscar fragmentos

Estado: implementado

## Alcance y supuestos
- Se implementa solo la capacidad de búsqueda: consulta en lenguaje natural → hasta 5 fragmentos relevantes.
- El índice ya existe (lo construirá otra spec). Aquí solo se lee.
- No se añade ruta HTTP ni interfaz web: el consumidor será `bot.py` en la spec de chat. Exponer la búsqueda por HTTP o MCP queda fuera.
- No se añaden dependencias. Todo el cálculo es local.
- Regla de proyecto que condiciona el diseño: las pruebas corren sin red, sin claves y sin descargar el modelo (`AGENTS.md`).

## Aprobaciones necesarias (según `AGENTS.md`)
1. **Cambio de firma:** `rag.search` pasa de devolver una lista a devolver `SearchResponse`. Cambia el esqueleto creado en la fase 0.
2. **Carga diferida del modelo** con `lru_cache` en vez de carga a nivel de módulo. `AGENTS.md` hoy dice "a nivel de módulo"; si se aprueba, esa línea se actualiza a "una sola vez por proceso, de forma diferida".
3. **Cambio de contrato de datos:** `kind` pasa de `str` a un `Literal` (ver abajo). Afecta a las pruebas de T1.

## Contrato de datos (`models.py`)
Campos que esta spec necesita; los modelos de chat siguen sin definir.

| Modelo | Campos |
|---|---|
| `Chunk` | `file_path: str`, `symbol_name: str`, `start_line: int`, `end_line: int`, `content: str`, `kind: Literal["function", "class", "module", "window"]` |
| `SearchResult` | `chunk: Chunk`, `score: float` |
| `SearchReason` | `empty_index`, `no_relevant`, `empty_query`, `query_too_long` (enum de texto) |
| `SearchResponse` | `results: list[SearchResult]`, `reason: SearchReason \| None`, `message: str \| None` |

- `reason` permite que el consumidor decida sin comparar textos; `message` lleva el texto en español listo para mostrar.
- `kind` no lo usa la búsqueda. Se deja como `Literal` para que la spec de indexado lo rellene: función, clase, código de módulo y ventana de líneas (plan B cuando `ast` falla).

## Archivos y responsabilidades
- `app/models.py`: contrato anterior. No valida reglas de negocio.
- `app/storage.py`: guarda chunks y embeddings ya calculados; búsqueda vectorial, orden, deduplicación y recorte a `top_k`. No aplica umbral (es criterio de RAG) ni genera embeddings.
- `app/rag.py`: valida y normaliza la consulta, genera su embedding, consulta el store, aplica el umbral y arma `SearchResponse`. No escribe en disco ni ejecuta código.
- `tests/test_models.py`, `tests/test_storage.py`, `tests/test_rag.py`, `tests/test_safety_perf.py`: pruebas nuevas.
- Sin cambios en `main.py`, `bot.py`, `mcp_server.py`, `static/` ni `requirements.txt`.

## Funciones
`storage.py`
- `VectorStore.count -> int` (propiedad): número de chunks.
- `VectorStore.add(chunks, embeddings) -> None`: añade y concatena; valida que las filas coincidan con los chunks.
- `VectorStore.search(query_embedding, top_k=5) -> list[SearchResult]`: producto punto, orden descendente estable, sin duplicados, máximo `top_k`.
- `VectorStore.clear() -> None`: vuelve al estado vacío.
- `_dedupe_key(result) -> tuple[str, int, int]`: identifica un fragmento por ruta y rango.

`rag.py`
- `search(query: str) -> SearchResponse`: única función pública de la capacidad.
- `_validate_query(query) -> tuple[SearchReason, str] | None`: primero vacío o solo espacios, después más de 1.000 caracteres (sobre el texto recibido).
- `_normalize_query(query) -> str`: minúsculas, sin tildes (`unicodedata.normalize("NFKD", ...)` y descartar marcas combinadas) y espacios consecutivos reducidos a uno.
- `_get_model()`: carga diferida y única del modelo de embeddings (`lru_cache`), para no importarlo al arrancar.
- `_embed_query(query) -> np.ndarray`: normaliza el texto, calcula el vector y lo normaliza a longitud 1.
- `_is_relevant(score) -> bool`: `round(score, 6) >= MIN_SCORE`.
Ninguna función depende de la fecha ni de la hora; no hace falta inyectar `hoy`.

## Algoritmo
```text
search(query):
    error = _validate_query(query)
    si error: devolver SearchResponse([], reason=error.reason, message=error.message)

    si store.count == 0: devolver SearchResponse([], empty_index, mensaje)

    vector = _embed_query(query)          # incluye _normalize_query
    candidatos = store.search(vector, top_k=MAX_RESULTS)
    resultados = [r para r en candidatos si _is_relevant(r.score)]

    si resultados está vacío: devolver SearchResponse([], no_relevant, mensaje)
    devolver SearchResponse(resultados, reason=None, message=None)
```

```text
_validate_query(query):
    si query.strip() == "": devolver (empty_query, mensaje)
    si len(query) > MAX_QUERY_LENGTH: devolver (query_too_long, mensaje)
    devolver None
```

```text
VectorStore.search(vector, top_k):
    si no hay chunks o top_k <= 0: devolver []

    validar que la dimensión de vector coincide con la de los embeddings
    scores = embeddings @ vector
    orden = argsort(-scores, kind="stable")

    vistos = conjunto vacío; salida = []
    para i en orden:
        clave = (chunk.file_path, chunk.start_line, chunk.end_line)
        si clave en vistos: continuar
        vistos.add(clave)
        salida.append(SearchResult(chunk, float(scores[i])))
        si len(salida) == top_k: cortar

    devolver salida
```

## Configuración
Constantes en `rag.py`, ajustables por quien opera el sistema editando el valor:
- `MAX_RESULTS = 5`
- `MIN_SCORE = 0.30`
- `MAX_QUERY_LENGTH = 1000`
Los mensajes en español son constantes del mismo módulo.

## Interfaz
- Interna: `rag.search(query: str) -> SearchResponse`.
- No se expone endpoint en esta spec; el chat la consumirá sin conocer embeddings ni umbral.

## Decisiones y alternativas descartadas
| Decisión | Por qué | Alternativa descartada |
|---|---|---|
| Carga diferida del modelo con `lru_cache` | Permite importar `rag` y correr pruebas sin descargar el modelo. Sigue cargándose una sola vez por proceso. | Cargarlo a nivel de módulo: rompe las pruebas sin red y retrasa el arranque. Requiere tu aprobación porque `AGENTS.md` dice "a nivel de módulo". |
| Normalizar la consulta antes de calcular el embedding (RF-12) | El modelo no garantiza que "Autenticación" y "autenticacion" den el mismo vector; normalizar sí lo garantiza y es fácil de probar. | Confiar en el modelo: no es comprobable sin descargarlo. Borrar el caso límite: empeora la experiencia con teclados sin tildes. |
| Umbral como constante de módulo | Simple para aprender y suficiente para "solo quien opera lo cambia". | Variable de entorno: más configurable, pero añade parseo y validación fuera del alcance. |
| Deduplicar dentro de `VectorStore.search` | Evita que un duplicado consuma uno de los 5 puestos y garantiza que el recorte final sea correcto. | Deduplicar en `rag.search`: si el store ya recortó a 5, se perderían fragmentos válidos. |
| `SearchResponse` con `reason` y `message` | El chat puede ramificar por código y la UI mostrar el texto en español sin duplicarlo. | Devolver solo una lista: no distingue "índice vacío" de "sin resultados" (RF-3 y RF-4). |
| Sin endpoint HTTP | La spec define una capacidad, no una interfaz; `main.py` solo traduce HTTP. | Añadir `/search`: amplía el alcance y mezcla capas. |
| `round(score, 6) >= MIN_SCORE` | Los embeddings salen en `float32`, con ruido cercano a `1e-7`; una tolerancia de `1e-9` no lo cubre y un 0,30 exacto podría descartarse. | Comparación estricta o tolerancia `1e-9`: fallan de forma intermitente. |
| Validar vacío sobre `strip()` antes que la longitud, y longitud sobre el texto recibido | Orden único y predecible: 1.500 espacios es "vacía"; 1.000 se acepta y 1.001 se rechaza. | Recortar la consulta en silencio: oculta un error al usuario y contradice RF-6. |
| `kind` como `Literal` | Evita valores inventados y deja listo el contrato para la spec de indexado. | `str` libre: errores de escritura silenciosos. |

## Estrategia de tests (`pytest`)
Todas las pruebas usan vectores falsos o dobles; ninguna descarga el modelo, usa red ni claves. Un fixture limpia el singleton `store` antes de cada prueba.
| RF / RNF / caso | Prueba |
|---|---|
| RF-1 | Store con 7 chunks y `top_k=5`: devuelve 5 ordenados. |
| RF-2 | Scores 0,29 y 0,31: solo pasa el segundo. |
| RF-3 | Store vacío: lista vacía y `reason=empty_index`. |
| RF-4 | Chunks indexados con scores bajo el umbral: `no_relevant`. |
| RF-5 | `""`, `"   "` y `"\n\t"`: `empty_query`. |
| RF-5 y RF-6 (orden) | 1.500 espacios: `empty_query`, no `query_too_long`. |
| RF-6 | 1.000 caracteres aceptada; 1.001 rechazada con `query_too_long`. |
| RF-7 | Cada resultado trae ruta, símbolo, líneas, texto y score. |
| RF-8 | Chunk duplicado en el store: aparece una vez. |
| RF-9 | Scores empatados: orden de inserción estable. |
| RF-10 | Dos búsquedas iguales: mismo resultado y orden. |
| RF-11 | Doble de embeddings que asigna el mismo vector a sinónimos: recupera el fragmento por significado. Opcional: prueba con el modelo real, omitida salvo que exista la variable de entorno `CODEMENTOR_REAL_MODEL`, nunca en CI. |
| RF-12 | `_normalize_query("  Autenticación   DE Usuarios ")` da `"autenticacion de usuarios"`. Un doble de embeddings que registra el texto recibido ve el mismo texto para "Autenticación" y "autenticacion". |
| RF-13 | Consultas como `"¿Dónde se valida el token?? (JWT)"` no lanzan excepción. |
| Umbral con `float32` | Un score `0.29999998` en `float32` cuenta como relevante; `0.299999` no. |
| Caso límite: un solo fragmento | Solo un chunk supera el umbral: un único resultado. |
| Caso límite: menos de cinco | Tres chunks superan el umbral: se devuelven tres. |
| Caso límite: mismo símbolo en archivos distintos | Dos chunks con el mismo `symbol_name` y distinta ruta: ambos aparecen, cada uno con su ruta. |
| RNF-1 | Un chunk con contenido como `import os; os.system("touch PWNED")`. Durante la llamada a `search`, `exec` y `eval` se sustituyen con `monkeypatch` por funciones que fallan; se comprueba que no se llaman y que `PWNED` no existe. |
| RNF-2 | Durante `search`, `socket.socket` se sustituye por una función que falla y el directorio de trabajo (`monkeypatch.chdir(tmp_path)`) queda sin archivos nuevos. |
| RNF-3 | Se comparan los cuatro mensajes en español. |
| RNF-4 | 10.000 vectores aleatorios `float32` de 384 dimensiones en el store; `store.search` tarda menos de 2 s. No incluye modelo ni embedding de consulta. |

## Riesgos
- Las pruebas con dobles no miden la calidad real del modelo multilingüe; RF-11 se valida a nivel de contrato. La prueba opcional con el modelo real queda fuera de CI.
- El umbral 0,30 depende del modelo; si se cambia el modelo de embeddings, hay que recalibrarlo (la spec lo prohíbe sin aprobación).
- La primera búsqueda tras arrancar paga la carga del modelo. Se resuelve con calentamiento al arrancar en la spec de la API.
- El singleton en memoria obliga a limpiar entre pruebas; se resuelve con fixture.
- Sustituir `exec` y `eval` con `monkeypatch` puede afectar a otras herramientas si se hace fuera de la llamada a `search`; se limita a ese bloque.

## Criterios para pasar a implementación
- Spec, plan y tareas aprobados por ti.
- Las tres aprobaciones de la sección "Aprobaciones necesarias" resueltas, y `AGENTS.md` actualizado si se aprueba la carga diferida.