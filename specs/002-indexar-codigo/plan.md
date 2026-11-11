# Plan 002 — Indexar código

Estado: implementado

## Alcance y supuestos
- Se implementa la preparación del índice: recibir el contenido de un archivo y su ruta, trocearlo, calcular la representación semántica de cada fragmento y dejarlo disponible para la búsqueda de la spec 001, en la misma operación (RF-1, RF-12).
- No se añade ruta HTTP, ni interfaz web, ni MCP: `main.py`, `bot.py`, `static/` y `mcp_server.py` no se tocan. El consumidor futuro será el endpoint de subida, con su propia spec.
- El contenido llega ya leído como `str`. Esta capacidad no abre archivos, no valida extensiones, no mide tiempos ni rechaza nada por parecer otro lenguaje (fuera de alcance de la spec).
- El índice sigue en memoria y se pierde al reiniciar; RF-12 se cumple dentro de la misma sesión, que es lo que pide.
- No se añaden dependencias: `ast`, `re` y `numpy` ya están en el stack.
- Ninguna función depende de la fecha ni de la hora: no hay nada que inyectar como "hoy".
- Supuestos donde la spec no llega (no la reabren, la interpretan):
  1. Anidamiento de clases de más de dos niveles: la regla de RF-23 se aplica de forma recursiva, de modo que `A.B.C` y `A.B.C.m` se nombran cualificados. La spec solo ejemplifica dos niveles.
  2. Un método se indexa con `kind="function"`: es una función, y el contrato solo admite cuatro literales (RF-5).
  3. `IndexResult` es interno. `UploadResponse` sigue sin implementar porque pertenece a la capa HTTP, que no existe todavía.

## Aprobaciones necesarias (según `AGENTS.md`)
`AGENTS.md` exige preguntar antes de cambiar los esquemas de `models.py` o el formato de los chunks, y antes de añadir dependencias. Esto es lo que cambia:

1. **`models.py`: dos esquemas nuevos.** `IndexReason` (StrEnum) e `IndexResult`. Sin ellos, `index_file` no puede informar de fragmentos, total y aviso de ventanas sin devolver un diccionario suelto (prohibido por `AGENTS.md`).
   - Decisión propuesta: modelos nuevos.
   - Alternativa descartada: reutilizar `UploadResponse`. No tiene total, ni aviso de ventanas, ni motivos de rechazo, y es el contrato de la capa HTTP; rellenarlo desde `rag.py` mezclaría capas.
2. **`rag.index_file` cambia de firma:** pasa de `-> int` a `-> IndexResult`. Cambia el esqueleto de la fase 0 y su pista de `TODO`.
   - Alternativa descartada: devolver `tuple[int, int, bool]`. Tres números posicionales sin nombre son ilegibles y no llevan el mensaje en español ni el motivo del rechazo.
3. **`rag.chunk_python_file` NO cambia de firma.** El aviso de ventanas se deduce de los propios fragmentos (`any(c.kind == "window" ...)`), porque el camino por símbolos nunca produce `window`. Se documenta aquí para que conste que se evaluó y no hace falta aprobación.
   - Alternativa descartada: devolver `tuple[list[Chunk], bool]`. Duplica una información que ya está en los datos y abre la puerta a que se contradigan.
4. **`storage.VectorStore` gana un método:** `replace_path(file_path, chunks, embeddings) -> None`, más la extracción de `_validate_matrix` desde `add`. Vive en `storage` porque es el único dueño del índice: `rag.py` no debe tocar listas privadas.
   - Alternativa descartada: `remove_path` + `add` llamados desde `rag.py`. Entre las dos llamadas la ruta queda vacía y un fallo en la segunda la deja sin fragmentos: rompe RF-22.
5. **Constantes nuevas en `rag.py`:** ventana de 60, bloque de módulo de 120, 1 MiB y 1.000 fragmentos. Son reglas de troceado, y el troceado es responsabilidad de `rag.py`.
   - Alternativa descartada: `models.py` (es contrato, no configuración) o variables de entorno (añaden parseo y validación fuera de alcance).
6. **Nada más:** ni dependencias nuevas, ni cambios en `Chunk`, `SearchResult`, `SearchResponse`, ni en el umbral de la 001.

Estado: las cinco aprobadas por el usuario el 2026-10-29.

## Contrato de datos (solo lo nuevo)
| Modelo | Campos |
|---|---|
| `IndexReason` | StrEnum: `empty_content`, `too_large`, `too_many_chunks`, `embedding_failed` |
| `IndexResult` | `file_path: str`, `chunks_indexed: int`, `total_chunks: int`, `used_windows: bool`, `reason: IndexReason \| None = None`, `message: str` |

- Éxito ⇔ `reason is None`. No se añade un booleano `indexed` que repita esa información.
- `message` es siempre obligatorio (a diferencia de `SearchResponse`): la spec exige un mensaje en español tanto en el éxito (RF-24) como en los cuatro rechazos (RNF-3).
- `chunks_indexed` es 0 en los rechazos y `total_chunks` es el total del índice en ese momento, contado después del reemplazo cuando lo hubo.
- `used_windows` solo es `True` cuando el troceado cayó al plan B (RF-8).

## Archivos y responsabilidades
- `app/models.py`: añade `IndexReason` e `IndexResult`. No valida reglas de negocio ni construye mensajes.
- `app/storage.py`: `replace_path` (sustitución por ruta) y `_validate_matrix` compartida con `add`. Guarda y busca; no trocea, no genera embeddings y no decide qué es un rechazo.
- `app/rag.py`: troceado (símbolos, bloques de módulo, ventanas), validaciones de contenido, cálculo de representaciones y orquestación de `index_file`. No habla HTTP, no escribe en disco y no ejecuta el código recibido.
- `tests/test_models.py`: se amplía con `IndexResult` e `IndexReason`.
- `tests/test_storage.py`: se amplía con `replace_path`.
- `tests/test_chunking.py`: **nuevo**. Todo el troceado de `chunk_python_file`.
- `tests/test_index.py`: **nuevo**. `index_file`: validaciones, mensajes, reemplazo atómico y recorrido indexar → buscar.
- `tests/test_safety_perf.py`: se amplía con la seguridad y el rendimiento del indexado.
- Sin cambios en `main.py`, `bot.py`, `mcp_server.py`, `static/`, `requirements.txt` ni en la búsqueda de la 001.

## Funciones
`storage.py`
- `VectorStore.replace_path(file_path, chunks, embeddings) -> None`: sustituye todos los fragmentos de esa ruta por los nuevos. Valida primero y escribe al final (ver algoritmo).
- `VectorStore._validate_matrix(chunks, embeddings) -> np.ndarray`: filas que coinciden con los chunks y dimensión compatible con la ya indexada. Extraída de `add`, que la reutiliza sin cambiar su comportamiento.
- `VectorStore.count`, `add`, `search`, `clear`, `_dedupe_key`: sin cambios.

`rag.py` (públicas)
- `chunk_python_file(source: str, file_path: str) -> list[Chunk]`: trocea por símbolos o, si no se puede analizar, por ventanas. Pura y determinista: mismo texto → mismos fragmentos.
- `index_file(file_path: str, source: str) -> IndexResult`: valida, trocea, cuenta, calcula representaciones y reemplaza de forma atómica. Es la única función de la capacidad que escribe en el índice.

`rag.py` (auxiliares, todas deterministas)
- `_split_lines(source: str) -> list[str]`: líneas conservando su separador. Solo `\n`, `\r\n` y `\r` cortan.
- `_line_body(line: str) -> str`: la línea sin su separador final.
- `_chunk_text(lines, start_line, end_line) -> str`: texto exacto del rango (RF-6, RF-27).
- `_parse_module(source: str) -> ast.Module | None`: `ast.parse`; `None` si `SyntaxError` o `ValueError` (indentación, bytes nulos, prosa).
- `_iter_definitions(tree) -> list[_Definition]`: recorre el árbol y devuelve qué fragmentos de símbolo hay y con qué nombre.
- `_string_lines(tree) -> set[int]`: líneas ocupadas por cadenas `str`/`bytes`/`JoinedStr` (f-string) que abarcan más de una línea; su contenido no cuenta como comentario.
- `_definition_start(node, lines, string_lines=None) -> int`: primer decorador y, si existe, grupo de comentarios pegado encima.
- `_attached_comment_start(lines, first_line, string_lines=None) -> int`: sube mientras la línea anterior sea solo un comentario y no esté dentro de una cadena multilínea.
- `_make_chunk(file_path, symbol_name, kind, start_line, end_line, lines) -> Chunk`: construye el fragmento con su texto exacto.
- `_module_blocks(lines, covered, file_path) -> list[Chunk]`: bloques contiguos de módulo, recortados y partidos a 120 líneas.
- `_window_chunks(file_path, lines) -> list[Chunk]`: ventanas de 60 líneas sin solape.
- `_sort_chunks(chunks) -> list[Chunk]`: orden de RF-17.
- `_validate_content(source) -> tuple[IndexReason, str] | None`: vacío y después tamaño.
- `_embed_chunks(chunks) -> np.ndarray`: representaciones normalizadas con `normalize_embeddings=True`.
- `_success_message(...)`, `_rejection_message(reason, *, size=None, produced=None) -> str`: textos en español.
- `_format_number(value: int) -> str`: separador de miles con punto, como en la 001.

`_Definition` es un `NamedTuple` privado de `rag.py` (`symbol_name`, `kind`, `node`): es un detalle interno del troceado, no un contrato entre capas, así que no va a `models.py`.

## Algoritmo

### Troceado por símbolos
```text
chunk_python_file(source, file_path):
    lines = _split_lines(source)
    tree = _parse_module(source)
    si tree es None: devolver _window_chunks(file_path, lines)      # RF-8

    string_lines = _string_lines(tree)          # una sola vez por archivo
    definitions = _iter_definitions(tree)
    chunks = []; covered = conjunto vacío
    para d en definitions:
        start = _definition_start(d.node, lines, string_lines)   # decoradores + comentarios pegados
        end = d.node.end_lineno                       # última instrucción del símbolo
        chunks.append(_make_chunk(file_path, d.symbol_name, d.kind, start, end, lines))
        covered |= {start .. end}
    chunks += _module_blocks(lines, covered, file_path)
    devolver _sort_chunks(chunks)
```

```text
_iter_definitions(tree):
    # nivel de módulo: las definiciones dentro de if/try/with/for/while/match
    # cuentan como de nivel superior (RF-2)
    _collect_module_level(tree.body, prefix="")

_collect_module_level(body, prefix):
    para node en body:
        FunctionDef | AsyncFunctionDef -> (prefix + node.name, "function", node)
        ClassDef -> (prefix + node.name, "class", node)
                    _collect_class_body(node.body, prefix + node.name + ".")
        If | Try | TryStar | With | AsyncWith | For | AsyncFor | While | Match
            -> para cada campo de cuerpo del nodo: _collect_module_level(campo, prefix)
        (cualquier otro nodo: nada)
    # nunca se desciende dentro de una función: sus anidadas no generan fragmento

_collect_class_body(body, prefix):
    para node en body:
        FunctionDef | AsyncFunctionDef -> (prefix + node.name, "function", node)
        ClassDef -> (prefix + node.name, "class", node)
                    _collect_class_body(node.body, prefix + node.name + ".")
        # If, Try, With... dentro de la clase: se ignoran; quedan dentro de la clase
```

```text
_definition_start(node, lines, string_lines=None):
    first = node.lineno
    si node tiene decorator_list: first = min(first, min(d.lineno para d en decorator_list))
    devolver _attached_comment_start(lines, first, string_lines)

_attached_comment_start(lines, first, string_lines=None):
    protected = string_lines o conjunto vacío
    start = first
    mientras start > 1 y (start - 1) no en protected
          y _line_body(lines[start-2]).strip().startswith("#"):
        start -= 1
    devolver start          # una línea en blanco corta el grupo: se queda en módulo
```
Una línea que empieza por `#` dentro de una cadena triple no es un comentario: como `protected` la contiene, el grupo se corta ahí y no se solapan dos símbolos (RF-2, RF-3).

### Bloques de módulo
```text
_module_blocks(lines, covered, file_path):
    chunks = []; counter = 0; i = 1
    mientras i <= len(lines):
        si i en covered: i += 1; continuar
        j = i
        mientras j < len(lines) y (j + 1) no en covered: j += 1
        start, end = recortar líneas en blanco al principio y al final de [i, j]
        si start <= end:
            si end - start + 1 > MAX_MODULE_BLOCK_LINES:
                para cada trozo [s, e] de hasta 120 líneas en [start, end]:
                    counter += 1
                    chunks.append(_make_chunk(..., f"module#{counter}", "module", s, e, lines))
            si no:
                chunks.append(_make_chunk(..., "module", "module", start, end, lines))
        i = j + 1
    devolver chunks
```
`covered` es la unión de los rangos de todos los símbolos, ya con decoradores y comentarios pegados incluidos. Por eso un comentario pegado nunca aparece en un bloque de módulo y uno separado por una línea en blanco sí (RF-4).

### Ventanas (plan B)
```text
_window_chunks(file_path, lines):
    para n, start en enumerate(range(1, len(lines) + 1, WINDOW_LINES), start=1):
        end = min(start + WINDOW_LINES - 1, len(lines))
        chunks.append(_make_chunk(file_path, f"window#{n}", "window", start, end, lines))
    devolver chunks
```

### Rangos y textos exactos
```text
_split_lines(source):
    lines = []; start = 0
    para cada coincidencia de r"\r\n|\r|\n" en source:
        lines.append(source[start:fin_de_la_coincidencia]); start = fin_de_la_coincidencia
    si start < len(source): lines.append(source[start:])
    devolver lines        # la última línea solo existe si le quedan caracteres

_line_body(line): devolver line sin un separador final ("\r\n", "\r" o "\n")

_chunk_text(lines, start, end):
    devolver "".join(lines[start-1:end-1]) + _line_body(lines[end-1])
```
`_chunk_text` equivale a la subcadena exacta desde el inicio de `start` hasta el final de `end` sin el separador que cierra `end`. Si la última línea está vacía, `_line_body` devuelve `""` y el texto conserva el separador anterior y termina en salto de línea (RF-6).

### Validaciones, en este orden
```text
_validate_content(source):
    si not source.strip():                       # RF-13, antes que todo
        devolver (EMPTY_CONTENT, _rejection_message(EMPTY_CONTENT))
    size = len(source.encode("utf-8"))
    si size > MAX_FILE_BYTES:                    # RF-14, después de vacío
        devolver (TOO_LARGE, _rejection_message(TOO_LARGE, size=size))
    devolver None
```

### Representaciones y reemplazo atómico
```text
_embed_chunks(chunks):
    texts = [c.content para c in chunks]         # texto exacto, sin recortar (RNF-7)
    vectors = _get_model().encode(texts, normalize_embeddings=True)
    matrix = np.asarray(vectors, dtype=np.float32).reshape(len(chunks), -1)
    para cada fila: si su norma > 0: fila = fila / norma   # |norma - 1| <= 1e-5 también con dobles
    devolver matrix
```

```text
index_file(file_path, source):
    invalid = _validate_content(source)
    si invalid: devolver _rejected(file_path, *invalid)          # índice intacto

    chunks = chunk_python_file(source, file_path)                # sin tocar el índice
    si len(chunks) > MAX_CHUNKS_PER_FILE:                        # RF-21, antes de embeber
        devolver _rejected(file_path, TOO_MANY_CHUNKS, produced=len(chunks))

    intentar:
        matrix = _embed_chunks(chunks)                           # todo en memoria
        store.replace_path(file_path, chunks, matrix)            # único punto que escribe
    except Exception:                                            # RF-19
        devolver _rejected(file_path, EMBEDDING_FAILED)

    devolver IndexResult(file_path, len(chunks), store.count,
                         any(c.kind == "window" for c in chunks),
                         None, _success_message(...))
```

```text
VectorStore.replace_path(file_path, chunks, embeddings):
    matrix = _validate_matrix(chunks, embeddings)                # puede lanzar; aún no se escribió nada
    keep = [i para i, c en enumerate(self._chunks) si c.file_path != file_path]
    new_chunks = [self._chunks[i] para i en keep] + chunks
    new_matrix = matrix si self._embeddings is None o no quedan filas
                 si no np.vstack([self._embeddings[keep], matrix])
    # a partir de aquí no hay ninguna operación que pueda fallar
    self._chunks = new_chunks
    self._embeddings = new_matrix
```
La atomicidad es de fallo, no de concurrencia: se calcula todo en variables locales y solo al final se reasignan los dos atributos. Cualquier excepción anterior deja el índice exactamente como estaba (RF-19, RF-22, RF-25).

## Configuración
Constantes en `rag.py`, junto a las de la 001:
| Constante | Valor | Para qué |
|---|---|---|
| `MAX_FILE_BYTES` | `1_048_576` | Límite de tamaño en bytes UTF-8 (RF-14) |
| `MAX_CHUNKS_PER_FILE` | `1_000` | Tope de fragmentos por archivo (RF-21) |
| `WINDOW_LINES` | `60` | Tamaño de ventana del plan B (RF-8) |
| `MAX_MODULE_BLOCK_LINES` | `120` | Tamaño máximo de un trozo de bloque de módulo (RF-20) |

Mensajes en español como constantes del mismo módulo; los que llevan cifras se formatean en `_rejection_message` y `_success_message`.

## Interfaz interna
- `rag.chunk_python_file(source: str, file_path: str) -> list[Chunk]`: pura, sin efectos. La usará el endpoint de subida si necesita previsualizar.
- `rag.index_file(file_path: str, source: str) -> IndexResult`: efecto único, escribir en `store`.
- `storage.VectorStore.replace_path(file_path, chunks, embeddings) -> None`.
- La búsqueda de la 001 no cambia: `search(query) -> SearchResponse` sigue leyendo el mismo `store`.

## Decisiones y alternativas descartadas
| Decisión | Por qué | Alternativa descartada |
|---|---|---|
| `index_file` devuelve `IndexResult` | RF-24 exige tres datos y RNF-3 un mensaje; un modelo los nombra y se valida | `int` o `tuple[int, int, bool]`: pierden el motivo del rechazo y el mensaje |
| `chunk_python_file` mantiene su firma | El aviso de ventanas se deduce de `kind == "window"`, que solo produce el plan B | Devolver `(chunks, used_windows)`: duplica el dato y puede contradecirlo |
| Decoradores con `node.decorator_list` y comentarios escaneando líneas hacia arriba | `ast` da la línea de cada decorador; los comentarios no están en el árbol, así que se leen del texto | Buscar `@` con una expresión regular: confunde `@` dentro de cadenas y decoradores de varias líneas |
| Cadenas multilínea protegidas con `_string_lines(tree)`, calculado una vez por archivo | `ast` ya conoce los rangos de las cadenas; con `\r` aislado, `tokenize` no respeta la numeración de líneas de RF-6/RF-8, mientras que `ast.parse` acepta `\r` y da `lineno`/`end_lineno` correctos | `tokenize` para distinguir comentarios reales: se desalinea de `_split_lines` con finales `\r`. Expresión regular de cadenas triples: no cubre `f-string`, `bytes` ni anidamiento |
| Bloques de módulo como complemento de las líneas cubiertas | Garantiza RF-7 por construcción: lo que no es símbolo es módulo, sin huecos | `tokenize` o partir por `ast` de sentencias: más frágil y no cubre comentarios ni blancos |
| La cobertura se verifica en pruebas, no con un `assert` en producción | Un `assert` en el camino caliente cuesta y no aporta al usuario; la prueba lo comprueba sobre fixtures y sobre código real del proyecto | Comprobar la cobertura en cada indexación: coste lineal extra y fallo en producción por un caso no previsto |
| Solo `ast.parse`, nunca `compile`/`exec`/`import` del contenido | `ast.parse` construye el árbol sin ejecutar; es lo único que hace falta (RNF-1) | `exec(source, {})` para validar: ejecutaría código ajeno |
| `replace_path` valida, construye en locales y reasigna al final | Da atomicidad de fallo sin transacciones ni copias del índice entero | `remove_path` + `add`: deja la ruta vacía entre llamadas. Copiar el índice completo: O(n) por subida |
| El tope de 1.000 se cuenta antes de calcular representaciones | Trocear es barato; embeber es lo caro y puede tardar segundos. Rechazar antes evita trabajo inútil (RF-21) | Embeber y luego contar: gasta el modelo para un archivo que se va a rechazar |
| Texto exacto con `_split_lines` (solo `\n`, `\r\n`, `\r`) y `_chunk_text` | Respeta RF-6: la subcadena exacta sin el separador final, y conserva el separador cuando la última línea está vacía | `str.splitlines()`: también corta en `\f`, `\v` y `\x1c`, y rompería la numeración de líneas. Guardar offsets: equivalente pero más código |
| `module#N` con un contador único por archivo que solo avanza al partir bloques | RF-20 y RF-23 piden numeración correlativa global, sin reiniciar entre bloques | Un contador por bloque: repetiría `module#1` en el segundo bloque partido. Numerar también los bloques sin partir: rompe el caso "dos bloques sin partir se llaman `module`" |
| `window#N` con `enumerate` sobre el rango de líneas | Numeración desde 1 en orden de aparición, sin estado | Contar fragmentos ya creados: se rompe si algún día convive con símbolos |
| Renormalizar cada fila tras `normalize_embeddings=True` | Garantiza `|norma − 1| ≤ 1e-5` (RF-11) incluso con un doble que devuelva vectores sin normalizar | Confiar solo en el flag del modelo: no es verificable sin descargarlo |
| El texto del fragmento no se recorta antes de embeber | RNF-7: el modelo puede truncar por su cuenta, pero lo guardado y citado es el texto completo | Truncar a N caracteres: la cita dejaría de cuadrar con el archivo |
| `used_windows` se deduce de los fragmentos | Una sola fuente de verdad: el `kind` ya dice cómo se obtuvo | Un booleano paralelo a la lista: dos datos que pueden discrepar |
| `kind="function"` para métodos | El contrato solo admite cuatro literales y un método es una función | Un quinto literal `method`: cambio de contrato no pedido por la spec |
| Clases anidadas resueltas de forma recursiva | RF-23 describe la regla por "clase contenedora"; aplicarla recursiva es la única lectura coherente | Limitar a dos niveles: dejaría `A.B.C` sin nombre válido |

## Estrategia de tests (`pytest`)
Todas las pruebas usan dobles de embeddings y `monkeypatch.setattr(rag, "store", VectorStore())`, como en la 001. Ninguna descarga el modelo, usa red ni claves. Los archivos de ejemplo son cadenas dentro de la prueba, nunca archivos reales salvo la lectura de `app/rag.py` y `app/storage.py` para el caso de código real.

| RF / RNF / caso | Prueba |
|---|---|
| RF-1, RF-12 | `index_file` sobre un archivo de ejemplo y después `rag.search`: el fragmento esperado aparece con su ruta, símbolo y líneas |
| RF-2 | Archivo con función, `async def`, clase, método, clase anidada, función dentro de función, clase dentro de función y `def` dentro de un `if` de módulo: se comprueban los símbolos exactos |
| RF-2 (contención) | El rango de la clase contiene el de cada método y los métodos no se solapan entre sí |
| RF-3 | Función con comentario pegado, con decorador y con decorador de varias líneas: el inicio es la primera línea correspondiente |
| RF-3 (negativo) | Comentario separado por una línea en blanco: se queda en el bloque de módulo |
| RF-4 | Imports, constante y bloque de arranque condicional: fragmentos `module` con rangos continuos y sin blancos en los bordes |
| RF-4 (docstring) | Archivo con solo un docstring de módulo: produce un fragmento `module` |
| RF-5 | Todo fragmento trae los seis campos y `kind` en los cuatro literales; `test_models.py` rechaza un `kind` inválido |
| RF-6, RNF-6 | `_chunk_text` comparado con la subcadena real en archivos con `\n`, `\r\n`, `\r`, `\f` dentro de una línea y ruta con barras invertidas sin normalizar |
| RF-6 (línea vacía final) | Ventana cuya última línea está vacía: el texto termina en salto de línea y el rango no se ajusta |
| RF-7 | Para cada fixture, todas las líneas con código están en algún fragmento; también sobre `app/rag.py` y `app/storage.py` |
| RF-8 | Prosa, `function f(){}` de JS y Python con `SyntaxError`: `kind="window"`, nombres `window#1..`, aviso en el mensaje |
| RF-9 | No analizable de 60 líneas: una ventana; de 61: dos, la segunda de 1 línea |
| RF-10, RF-24, RNF-3 | El mensaje de éxito contiene el número de fragmentos, el total del índice y, solo cuando toca, el aviso de ventanas |
| RF-11 | Doble de embeddings que registra el texto recibido y devuelve vectores sin normalizar: cada fila cumple `abs(norm - 1) <= 1e-5` y el texto recibido es el `content` exacto |
| RF-13 | `""`, `"   "`, `"\n\n"`: `reason=empty_content`; y 1.100.000 espacios se rechazan como vacío, no como grandes |
| RF-14 | 1.048.576 bytes se aceptan; 1.048.577 se rechazan; 600.000 caracteres que ocupan más de 1 MiB se rechazan; el mensaje incluye `1.048.576` y el tamaño recibido |
| RF-15, RF-16 | Indexar dos rutas: se conservan las dos; mismo `symbol_name` en rutas distintas: dos fragmentos |
| RF-17 | Indexar dos veces el mismo archivo: mismos fragmentos, mismo orden y mismo `count`; y orden por línea inicial, después fin descendente y después símbolo |
| RF-18, RF-25 | Ruta con 3 fragmentos reindexada con 7: quedan 7; con 3: quedan 3; los cuatro rechazos dejan la versión anterior intacta y no añaden nada en una ruta nueva |
| RF-19, RF-22 | Doble de embeddings que falla en el segundo fragmento de una re-subida: `reason=embedding_failed`, el índice conserva los fragmentos anteriores, `search` los sigue encontrando y el mensaje está en español |
| RF-20 | Bloque de 120 líneas: un `module`; de 121: `module#1` y `module#2`; dos bloques partidos: la numeración continúa en `module#3` |
| RF-21 | Archivo que produce 1.000 fragmentos se indexa; 1.001 se rechaza con el tope y la cantidad en el mensaje, y el doble de embeddings no se llega a llamar |
| RF-23 | Nombres `login`, `User`, `User.login`, `Outer.Inner`, `Outer.Inner.metodo`, `module`, `module#N`, `window#N`; los métodos de una clase dentro de una función no aparecen |
| RF-26 | Un `import` suelto: fragmento de una línea llamado `module`, no fusionado con el bloque siguiente |
| RF-27 | Función con líneas en blanco y comentarios después: el rango acaba en la última instrucción; clase: acaba en la última línea de su cuerpo |
| RNF-1 | Contenido malicioso (`import os; os.system("touch PWNED")`): durante `chunk_python_file` e `index_file`, `exec` y `eval` se sustituyen por funciones que fallan, el módulo no aparece en `sys.modules` y `PWNED` no existe |
| RNF-2 | Durante `index_file`, `socket.socket` falla y `monkeypatch.chdir(tmp_path)` queda sin archivos nuevos |
| RNF-4 | 1.000 líneas con unas 100 funciones de 10 líneas: `chunk_python_file` tarda menos de 1 s (sin modelo) |
| RNF-5 | El fragmento devuelto por `search` tras indexar conserva el contrato de la 001: `SearchResponse` con hasta 5 resultados y umbral intacto |
| RNF-7 | Texto de un fragmento de 2.000 líneas: se guarda entero aunque el doble de embeddings trunque lo que recibe |
| Casos límite de una línea | Archivo de una sola asignación, clase sin métodos, única función sin módulo, archivo solo de comentarios, dos bloques `module` sin partir |

## Riesgos
- La regla de "comentario pegado" se decide mirando el texto, no el árbol: una línea que empiece por `#` dentro de una cadena multilínea podría atribuirse mal. **Cubierto**: `_string_lines(tree)` protege las líneas de `str`/`bytes`/`JoinedStr` de varias líneas, con prueba de regresión (`test_a_string_line_is_not_an_attached_comment`, solapes entre símbolos y `f-string`).
- `node.end_lineno` depende de la versión de Python; en 3.12 es estable, pero si se sube de versión conviene revisar RF-27.
- `replace_path` no es atómico frente a lecturas concurrentes: reasigna dos atributos. La spec no pide concurrencia y el store ya no era seguro con hilos; si se añade, la solución es un único atributo inmutable o un `Lock`.
- `except Exception` en `index_file` es deliberadamente amplio: cualquier fallo al embeber o al reemplazar debe acabar en el mismo rechazo en español. Nunca captura `BaseException`, para no tragarse `KeyboardInterrupt`.
- Un archivo con un bloque de módulo de 120 líneas exactas depende de recortar antes de contar: si se cuenta antes de recortar, se parte un bloque que no debía partirse.
- Las pruebas con dobles no miden la calidad del modelo ni el truncado real; RNF-7 se valida a nivel de contrato.
- El troceado de un archivo de 1 MiB con muchas definiciones no está acotado por RNF-4 (que habla de 1.000 líneas); se vigila con el tope de 1.000 fragmentos.

## Criterios para pasar a implementación
- Spec, plan y tareas aprobados.
- Las aprobaciones 1, 2, 4 y 5 resueltas; `AGENTS.md` actualizado si alguna cambia una regla permanente.
