# Tareas 001 — Buscar fragmentos

Estado: implementado

Orden de dependencia. Una tarea a la vez: pruebas primero, luego código, y parar al terminar.

## Antes de empezar
- [x] **T0. Aprobar spec, plan y tareas.** Resolver las tres aprobaciones del plan (firma de `search`, carga diferida, `kind` como `Literal`) y, si se aprueba la carga diferida, actualizar la línea correspondiente de `AGENTS.md`.
  - Hecho cuando: los tres archivos pasan de "borrador" a "aprobado" y `AGENTS.md` no contradice el plan.

## Tareas

- [x] **T1. Definir el contrato de datos y sus pruebas.** Contrato de RF-3, RF-4, RF-5, RF-6, RF-7
  - Hecho cuando: `tests/test_models.py` construye `Chunk`, `SearchResult`, `SearchReason` y `SearchResponse`; `pytest -q` pasa y los modelos de chat siguen sin campos.

- [x] **T1b. Ajustar T1 al contrato revisado.**
  - Hecho cuando: `Chunk.kind` es un `Literal` de cuatro valores, las pruebas de `test_models.py` rechazan un valor inválido y `pytest -q` pasa.

- [x] **T2. Escribir las pruebas de `VectorStore` (en rojo).** RF-1, RF-8, RF-9, RF-10 y casos límite
  - Antes: crear las firmas (`count`, `add`, `search`, `clear`, `_dedupe_key`) con `raise NotImplementedError("TODO: ...")` y una pista de una línea.
  - Hecho cuando: `tests/test_storage.py` cubre añadir, contar, orden descendente, `top_k`, empates estables, duplicados, store vacío, dimensiones incompatibles, `clear`, un solo fragmento, menos de cinco fragmentos y mismo símbolo en archivos distintos; las pruebas fallan por `NotImplementedError`, no por `AttributeError` ni errores de sintaxis.

- [x] **T3. Implementar `VectorStore`.** RF-1, RF-8, RF-9, RF-10
  - Hecho cuando: `pytest -q tests/test_storage.py` pasa y `store` se puede vaciar con `clear()`.

- [x] **T4. Escribir las pruebas de validación y normalización de consulta (en rojo).** RF-5, RF-6, RF-12, RF-13, RNF-3
  - Antes: crear las firmas `_validate_query` y `_normalize_query` con `NotImplementedError`.
  - Hecho cuando: las pruebas cubren vacío, solo espacios, 1.500 espacios (`empty_query` antes que `query_too_long`), 1.000 y 1.001 caracteres, que `"  Autenticación   DE Usuarios "` da `"autenticacion de usuarios"`, que los signos como `¿?()` no producen error, y los cuatro mensajes en español; fallan por `NotImplementedError`.

- [x] **T5. Implementar constantes, mensajes, `_validate_query` y `_normalize_query`.** RF-5, RF-6, RF-12, RF-13, RNF-3
  - Hecho cuando: las pruebas de T4 pasan sin cargar el modelo de embeddings.

- [x] **T6. Escribir las pruebas de `rag.search` (en rojo).** RF-1, RF-2, RF-3, RF-4, RF-7, RF-10, RF-11, RF-12, RNF-3
  - Antes: dejar las firmas `search`, `_get_model`, `_embed_query` y `_is_relevant` con `NotImplementedError`.
  - Hecho cuando: con embeddings y store dobles se prueban los 5 resultados, el umbral 0,30 (0,29 fuera, 0,30 dentro, `0.29999998` en `float32` dentro, `0.299999` fuera), índice vacío, sin relevantes, metadatos completos, dos búsquedas iguales con el mismo orden, un doble de embeddings que recupera sinónimos (RF-11) y un doble que registra el texto recibido y ve el mismo texto para "Autenticación" y "autenticacion" (RF-12); fallan por `NotImplementedError`. La prueba opcional con el modelo real queda marcada y omitida salvo que exista `CODEMENTOR_REAL_MODEL`.

- [x] **T7. Implementar `rag.search`, el modelo diferido, el embedding de la consulta y `_is_relevant`.** RF-1, RF-2, RF-3, RF-4, RF-7, RF-10, RF-11, RF-12
  - Hecho cuando: las pruebas de T6 pasan y `import app.rag` no importa `sentence_transformers` ni descarga nada.

- [x] **T8. Añadir pruebas de seguridad y rendimiento (caracterización).** RNF-1, RNF-2, RNF-4
  - Estas pruebas se escriben después del código porque comprueban propiedades de lo ya implementado; pasan desde el principio y, si fallan, se corrige el código.
  - Hecho cuando: `tests/test_safety_perf.py` verifica que con un chunk malicioso (`import os; os.system("touch PWNED")`) no se llama a `exec` ni a `eval`, que no se abren sockets, que no aparecen archivos nuevos, y que `store.search` con 10.000 vectores `float32` de 384 dimensiones tarda menos de 2 s.

- [x] **T9. Verificación final y memoria.** RNF-1, RNF-2, RNF-3, RNF-4
  - Hecho cuando: `ruff check .` y `pytest -q` pasan sin red ni claves; cada RF, RNF y caso límite tiene su prueba; los tres archivos de la spec pasan a "implementada"; `MEMORY.md` refleja la spec implementada, incluidas la carga diferida y la normalización de consultas.

## Fuera de estas tareas
- Endpoint HTTP o UI de búsqueda.
- Carga, troceado e indexación de archivos.
- Chat con Claude y MCP.
- Calentamiento del modelo al arrancar (spec de la API).