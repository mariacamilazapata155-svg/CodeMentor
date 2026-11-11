# Tareas 002 — Indexar código

Estado: implementado

Orden de dependencia. Una tarea a la vez: pruebas primero (en rojo), luego código, y parar al terminar. Cada tarea cabe en 20–30 minutos.

## Antes de empezar
- [x] **T0. Resolver las aprobaciones del plan y aprobar plan y tareas.** Resolver las aprobaciones 1, 2, 4 y 5 de `plan.md` (esquemas `IndexReason`/`IndexResult`, firma de `index_file`, `replace_path` en `storage`, constantes en `rag.py`) y actualizar `AGENTS.md` si alguna cambia una regla permanente. No es una tarea de código. Aprobadas las cinco decisiones del plan el 2026-10-29.
  - Hecho cuando: las aprobaciones están resueltas por escrito, este archivo y `plan.md` pasan de "borrador" a "aprobado" y `AGENTS.md` no contradice el plan.

## Tareas

- [x] **T1. Definir `IndexReason` e `IndexResult` con sus pruebas.** RF-5, RF-10, RF-24, RNF-3
  - Hecho cuando: `tests/test_models.py` construye un `IndexResult` de éxito (`reason is None`, `message` obligatorio) y uno de rechazo para cada uno de los cuatro motivos; un `reason` inventado se rechaza; `Chunk`, `SearchResult` y `SearchResponse` siguen intactos y `pytest -q` pasa.

- [x] **T2. Escribir las pruebas de `VectorStore.replace_path` y luego implementarlo.** RF-18, RF-22, RF-25
  - Antes: crear `replace_path(file_path, chunks, embeddings)` con `NotImplementedError` y extraer `_validate_matrix` de `add` sin cambiar el comportamiento de `add`.
  - Hecho cuando: `tests/test_storage.py` cubre reemplazar 3 fragmentos por 7 y por 3, reemplazar una ruta inexistente sin tocar las demás, mantener el orden de las otras rutas, rechazar filas o dimensiones incompatibles **sin modificar el índice** (se comprueba `count` y el contenido antes y después), y `pytest -q` pasa con las pruebas de la 001 verdes.

- [x] **T3. Escribir las pruebas de líneas y texto exacto, y luego los auxiliares.** RF-6, RF-27, RNF-6, RNF-7
  - Antes: crear `_split_lines`, `_line_body`, `_chunk_text` y `_format_number` con `NotImplementedError`.
  - Hecho cuando: `tests/test_chunking.py` comprueba `\n`, `\r\n`, `\r`, `\f` dentro de una línea (no abre línea nueva), archivo que termina en salto de línea, última línea vacía (el texto conserva el separador anterior), texto idéntico a la subcadena real, y que no se recortan espacios ni líneas de los bordes; las pruebas fallan por `NotImplementedError` y después pasan.

- [x] **T4. Escribir las pruebas del troceado por símbolos y luego implementarlo.** RF-2, RF-3, RF-5, RF-17, RF-23, RF-27
  - Antes: crear `_parse_module`, `_iter_definitions`, `_definition_start`, `_attached_comment_start`, `_make_chunk` y `_sort_chunks` con `NotImplementedError`.
  - Hecho cuando: las pruebas cubren función, `async def`, clase, método (`User.login`), clase anidada (`Outer.Inner`) y sus métodos, `def` y `class` dentro de `if`/`try`/`with` de módulo, que no se generan fragmentos para funciones dentro de funciones ni para clases dentro de funciones, ni para métodos o clases dentro de un bloque condicional de una clase; el rango de la clase contiene a sus métodos sin solapes; comentario pegado y decorador (también de varias líneas) entran en el rango; comentario tras una línea en blanco no; el rango acaba en la última instrucción (función) y en la última línea del cuerpo (clase); y el orden es línea inicial, después fin descendente, después símbolo.

- [x] **T5. Escribir las pruebas de los bloques de módulo y luego implementarlos.** RF-4, RF-20, RF-23, RF-26
  - Antes: crear `_module_blocks` con `NotImplementedError`.
  - Hecho cuando: las pruebas cubren imports y constantes como `module`, bloque de arranque condicional cortado por la función que contiene, docstring de módulo, archivo solo de comentarios, `import` suelto de una línea sin fusionar, recorte de blancos en los bordes, bloque de 120 líneas (`module`) y de 121 (`module#1` + `module#2`), numeración que continúa en `module#3` al partir un segundo bloque, y dos bloques sin partir que se llaman ambos `module`.

- [x] **T6. Ensamblar `chunk_python_file`: ventanas, fallback y cobertura.** RF-1, RF-7, RF-8, RF-9
  - Hecho cuando: las pruebas cubren prosa, JS y Python roto indexados como `window#1..` sin abortar; 60 líneas → una ventana, 61 → dos con la segunda de 1 línea; ventana con última línea vacía; y, para todos los fixtures y para `app/rag.py` y `app/storage.py` leídos como texto, toda línea con código (no vacía y no solo comentario) pertenece a algún fragmento.

- [x] **T7. Escribir las pruebas de validaciones y mensajes, y luego implementarlos.** RF-10, RF-13, RF-14, RF-21, RF-24, RNF-3
  - Antes: crear `_validate_content`, `_success_message` y `_rejection_message` con `NotImplementedError`.
  - Hecho cuando: se comprueba el orden vacío → tamaño → tope (1.100.000 espacios es vacío; 1.048.577 bytes es tamaño), que 1.048.576 se acepta y 1.048.577 se rechaza, que 600.000 caracteres de más de 1 MiB se rechazan por bytes, que 1.000 fragmentos se aceptan y 1.001 se rechazan con el tope y la cantidad, que un rechazo por tope no llama al doble de embeddings, y que los cinco mensajes están en español y contienen las cifras exigidas.

- [x] **T8. Escribir las pruebas de `index_file` y luego implementarlo.** RF-1, RF-11, RF-12, RF-15, RF-16, RF-17, RF-18, RF-19, RF-22, RF-25, RNF-5
  - Antes: crear `index_file` y `_embed_chunks` con `NotImplementedError`.
  - Hecho cuando: con un doble de embeddings que registra textos, cada fila cumple `abs(norm - 1) <= 1e-5` y el texto recibido es el `content` exacto (también en un fragmento de 2.000 líneas que el doble trunca); indexar dos rutas las conserva y no vacía el índice; reindexar da los mismos fragmentos, orden y `count`; de 3 a 7 fragmentos quedan 7; un fallo del doble a mitad de una re-subida deja la ruta con la versión anterior, `search` la sigue encontrando y el mensaje es `embedding_failed`; y tras indexar, `rag.search` devuelve el fragmento con ruta, símbolo y líneas correctos.

- [x] **T9. Añadir pruebas de seguridad y rendimiento del indexado.** RNF-1, RNF-2, RNF-4
  - Se escriben después del código porque caracterizan lo ya implementado; si fallan, se corrige el código.
  - Hecho cuando: `tests/test_safety_perf.py` verifica que con contenido malicioso (`import os; os.system("touch PWNED")`, `open(...)`) `chunk_python_file` e `index_file` no llaman a `exec` ni a `eval`, que el módulo no aparece en `sys.modules`, que `socket.socket` no se usa, que no aparecen archivos nuevos en `tmp_path` y que 1.000 líneas con unas 100 funciones de 10 líneas se trocean en menos de 1 s sin modelo.

- [x] **T10. Verificación final y memoria.** RNF-1 a RNF-7
  - Hecho cuando: `ruff check .` y `pytest -q` pasan sin red, sin claves y sin descargar el modelo; cada RF, RNF y caso límite de la spec tiene su prueba (tabla del plan revisada punto por punto); `plan.md` y `tasks.md` pasan a "implementado"; `MEMORY.md` recoge que la spec 002 está implementada, con las decisiones de atomicidad, numeración de `module#N` y derivación de `used_windows`.
  - Verificado el 2026-10-30: `ruff check .` y `ruff format --check .` limpios y `pytest -q` con 328 pruebas verdes y 1 omitida explícita (`CODEMENTOR_REAL_MODEL`) en 1,34 s, con `HF_HUB_OFFLINE=1` y sin claves ni red. Se añadieron 7 pruebas de casos límite en la primera pasada (única función y `async def`, clase sin métodos, finales `\r\n` y `\r`, comentario separado por línea en blanco y 1.000 fragmentos aceptados por `index_file`) y 3 en la revisión final (línea muy larga sin recortar, función anidada dentro del fragmento de su contenedora y archivo solo de configuración localizable con `search`).

## Correcciones tras la validación (2026-10-30)
- **RF-2/RF-3/RF-4, comentario falso dentro de una cadena:** `_definition_start` recibe ahora `string_lines` con las líneas de cadenas multilínea del AST (`_string_lines`, incluye `str`/`bytes` y `JoinedStr`), de modo que una línea `#` de dentro de una cadena triple ya no se toma por comentario pegado. Se eligió el AST y no `tokenize` porque `tokenize` no numera bien los `\r` aislados. Regresión en `tests/test_chunking.py` (solape `a`/`b` y `module` + `f` con cadena triple y `f-string`).
- **Criterio de finalización de `spec.md:139`:** `test_chunk_python_file_covers_the_project_code` comprueba además que `chunk.content` es la subcadena exacta de su rango en `app/rag.py` y `app/storage.py`.
- **Criterio de finalización de `spec.md:153`:** `test_the_size_check_runs_before_the_chunk_cap` cubre un contenido de más de 1 MiB que daría 1.001 fragmentos: gana `TOO_LARGE`, el mensaje es el de tamaño y `_embed_chunks` no se llama.
- Resultado: `pytest -q` con 331 pruebas verdes y 1 omitida, `ruff check .` y `ruff format --check .` limpios.
- Cierre: la validación del reviewer terminó en **APROBADO** el 2026-10-30, tras esta vuelta de correcciones.

## Fuera de estas tareas
- Endpoint HTTP de subida, validación de extensión y lectura desde disco (spec de la API).
- Indexar JavaScript u otro lenguaje con troceado por símbolos: solo por ventanas.
- Persistencia del índice en SQLite o en disco.
- Chat con Claude (`bot.py`) y exposición por MCP.
- Interfaz web de subida y cualquier cambio en `static/`.
- Borrar una ruta del índice por petición, detectar cambios en disco y deduplicar por contenido.
- Cambiar el modelo de embeddings, el umbral o el número de resultados de la 001.
