# Tareas 003 — Responder con citas

Estado: implementado


Orden de dependencia. Una tarea a la vez: pruebas primero (en rojo), luego código, y parar al terminar. Cada tarea cabe en 20–30 minutos. Ninguna prueba usa red, claves ni llamadas reales al modelo.

## Antes de empezar
- [x] **T0. Resolver las aprobaciones del plan, dejar anotados los supuestos y confirmar la aprobación de spec, plan y tareas.** Resolver las aprobaciones 1 a 4 de `plan.md` (diseño de citas por marcas e interpretación del principio 6, modelos de chat, firma de `answer`, constantes y nombre del modelo) y dejar anotados los supuestos ya confirmados contra el SDK instalado (`anthropic==2.1.0`, la versión de `requirements.txt`): jerarquía de las excepciones y construcción de sus dobles con `httpx2.Request` / `httpx2.Response` (`httpx2` es dependencia transitiva; no se añade a `requirements.txt`), forma de `response.content`, parámetros `timeout` y `max_retries` del cliente y que `MODEL_NAME` existe en el literal de modelos del SDK (su disponibilidad real en la cuenta se comprueba con clave en T10). Actualizar `AGENTS.md` si alguna decisión cambia una regla permanente. No es una tarea de código.
  - Hecho cuando: las aprobaciones están resueltas por escrito, los supuestos 1 a 4 del plan están anotados (sin reabrir la investigación, ya hecha), `spec.md` está en "aprobada" y `plan.md` y `tasks.md` en "aprobado", y `AGENTS.md` no contradice el plan ni la constitución.

## Tareas

- [x] **T1. Definir los modelos de chat con sus pruebas.** RF-19
  - Hecho cuando: `tests/test_models.py` construye `ChatMessage` (un rol inválido se rechaza), `ChatRequest` con `history` por defecto vacío e independiente entre instancias, `Citation` con sus cinco campos, `ChatReason` con los once valores (un valor inventado se rechaza) y `ChatResponse` con `citations` por defecto vacía y `reason` por defecto ausente; los cuatro primeros valores de `ChatReason` coinciden con los de `SearchReason`; `Chunk`, `SearchResult`, `SearchResponse` e `IndexResult` siguen intactos y `pytest -q` pasa.

- [x] **T2. Escribir las pruebas del historial, crear los dobles compartidos y luego implementarlo.** RF-11
  - Antes: crear `tests/conftest.py` con los dobles y, en `bot.py`, las firmas `_prepare_history` y `_merge_same_role` con `raise NotImplementedError("TODO: ...")` y una pista de una línea. Los dobles nacen en esta tarea porque es la primera con pruebas de `bot.py` y la usan todas las siguientes.
  - Hecho cuando: `tests/conftest.py` ofrece un `FakeClient` que registra los argumentos de `messages.create` y devuelve un texto configurable (uno o varios bloques) o lanza el error configurado; constructores de los errores del cliente oficial (`APITimeoutError`, `APIConnectionError`, `RateLimitError`, error 400, 401, 403, 500 y 529) apoyados en `httpx2.Request` / `httpx2.Response` (sin añadir `httpx2` a `requirements.txt`); un fixture que fija o elimina `ANTHROPIC_API_KEY` con `monkeypatch`; y un fixture `autouse` que ejecuta `bot._get_client.cache_clear()` antes y después de cada prueba, para que el cliente cacheado de una prueba (y su clave) no se filtre a la siguiente. Una prueba comprueba que cada constructor produce una instancia de la clase esperada y que los fixtures dejan limpio el estado (variable `ANTHROPIC_API_KEY` y caché del cliente) al terminar. Además, `tests/test_bot_prompt.py` cubre historial vacío; 25 mensajes (quedan los últimos 10); mensajes vacíos o de solo espacios descartados antes de contar; primer mensaje del asistente descartado (y varios seguidos); historial formado solo por mensajes del asistente (queda vacío); mensaje de 5.000 caracteres recortado a 4.000 (y uno de 4.000 intacto); y consecutivos del mismo rol unidos con una línea en blanco. Las pruebas del historial fallan por `NotImplementedError` y después pasan; `pytest -q` pasa.

- [x] **T3. Escribir las pruebas del contexto y la delimitación, y luego implementarlos.** RF-4, RF-12, RF-21
  - Antes: crear `_truncate_content`, `_pick_boundary`, `_format_fragment` y `_build_context` con `NotImplementedError`.
  - Hecho cuando: las pruebas cubren fragmento de 6.000 caracteres entero y de 6.001 truncado con aviso (el aviso se construye con `MAX_FRAGMENT_CHARS`, no con un literal); cinco fragmentos de 6.000 (se entregan tres y se detiene en el primero que no cabe, sin probar los siguientes); primer fragmento de 25.000 truncado y entregado; fragmentos omitidos sin número; numeración desde 1 en el orden de la búsqueda; cada bloque con ruta, símbolo, líneas y texto; un fragmento con `[F1]`, `FIN FRAGMENTO F1`, una fila de 3 `=` y otra de 40 `=` (la fila de delimitación es más larga que cualquiera del contenido y hay un inicio y un fin por fragmento); y una ruta con `=`.

- [x] **T4. Escribir las pruebas del mensaje de sistema y del mensaje final, y luego implementarlos.** RF-4, RF-5, RF-20
  - Antes: crear la constante `SYSTEM_PROMPT` con un `TODO` y la firma `_build_messages` con `NotImplementedError`.
  - Hecho cuando: las pruebas comprueban que `SYSTEM_PROMPT` contiene `NO_ENCONTRADO`, la forma de la marca, la palabra "datos" y "español"; que `_build_messages` devuelve historial enviado más un mensaje final de usuario con el contexto y la pregunta, con roles alternados (incluido el caso de un historial que termina en mensaje del usuario, que se une con el final); y que dos llamadas con las mismas entradas dan exactamente el mismo resultado.

- [x] **T5. Escribir las pruebas de interpretación de la respuesta y luego implementarla.** RF-6, RF-7, RF-8, RF-9, RF-10
  - Antes: crear `_extract_text`, `_extract_markers`, `_build_citations`, `_interpret` y `_failure` con `NotImplementedError`, y las constantes de mensajes de `insufficient_context` y `ungrounded_answer`.
  - Hecho cuando: las pruebas cubren `NO_ENCONTRADO` (también con espacios y saltos de línea alrededor; dentro de un texto largo no es centinela); `[F2]` y `[F4]` dan dos citas; `[F1]` repetido da una; `[F3]` antes que `[F1]` da orden 3, 1; `[F9]` con 3 entregados se elimina del texto y no genera cita; `[F0]`, `[F01]`, `[f2]` y `[F1234]` se conservan como texto; sin marcas válidas, respuesta vacía y solo marcas inválidas dan `ungrounded_answer` sin el texto del modelo; varios bloques de texto se unen sin separador; un modelo falso que inventa rutas, símbolos y líneas en su texto produce citas con los datos del fragmento entregado; y una cadena de 5.000 dígitos dentro de `[F...]` no lanza `ValueError`.

- [x] **T6. Escribir las pruebas de la clave y del cliente diferido, y luego implementarlos.** RF-13, RNF-3, RNF-7
  - Antes: crear `_api_key_present` y `_get_client` con `NotImplementedError`, y el mensaje de `missing_api_key`.
  - Hecho cuando: las pruebas cubren variable ausente, vacía y de solo espacios (no hay clave) y una clave válida (hay clave); que importar o recargar `bot` sin clave y sin red no falla ni crea el cliente; que `_get_client` crea el cliente con `timeout=30.0` y `max_retries=1` sustituyendo `anthropic.Anthropic` por un doble, y lo reutiliza en la segunda llamada; y que el mensaje de falta de clave está en español y nombra `ANTHROPIC_API_KEY`.

- [x] **T7. Escribir las pruebas de los fallos del modelo y luego implementarlos.** RF-14, RF-15, RF-16, RF-17, RF-18, RNF-4, RNF-5
  - Antes: crear `_ModelError` y `_call_model` con `NotImplementedError`, y los mensajes de `api_timeout`, `api_unavailable`, `invalid_api_key` y `api_error`.
  - Hecho cuando: `APITimeoutError` da `api_timeout`; `APIConnectionError`, `RateLimitError`, error 500 y 529 dan `api_unavailable`; `AuthenticationError` y `PermissionDeniedError` dan `invalid_api_key`; error 400 y un `AnthropicError` genérico dan `api_error`; un `ValueError` del cliente falso se propaga sin traducir; ningún mensaje contiene la clave, el texto de la excepción ni nombres de clases del SDK y todos están en español; con `caplog`, cada fallo registra solo el nombre de la clase del error y nunca la clave, la pregunta ni código, y con `capsys` no se imprime nada por pantalla.

- [x] **T8. Escribir las pruebas de `answer` y luego implementarlo.** RF-1, RF-2, RF-3, RF-13, RF-18, RF-19, RF-22
  - Antes: crear `answer` con `NotImplementedError`.
  - Hecho cuando: con un cliente falso, un doble de embeddings y el índice llenado con `rag.index_file`, `answer` devuelve respuesta, cita y `reason=None` en el caso feliz; con cada uno de los cuatro motivos de la búsqueda no se llama al cliente y `reply` es el mensaje de la búsqueda; sin clave y con índice vacío, pregunta vacía o sin relevantes, el motivo es el de la búsqueda; con fragmentos y sin clave, `missing_api_key` sin llamar a `_get_client`; la búsqueda recibe solo la pregunta aunque el historial cambie; una pregunta que contiene una marca como `[F1]` no genera citas por sí misma (solo se analizan las marcas de la respuesta del modelo); una pregunta en otro idioma se procesa igual (el mensaje de sistema pide responder en español); en todos los casos éxito ⇔ `reason is None` ⇔ al menos una cita, y en cualquier otro caso `citations == []`; un fallo del modelo deja el índice igual; dos llamadas independientes no comparten estado; y el recorrido completo (indexar una función con `index_file`, preguntar, el modelo falso cita `[F1]`) devuelve una cita con la ruta, el símbolo y las líneas del fragmento indexado.

- [x] **T9. Añadir las pruebas de seguridad y rendimiento (caracterización).** RNF-1, RNF-2, RNF-6
  - Se escriben después del código porque comprueban propiedades de lo ya implementado; pasan desde el principio y, si fallan, se corrige el código.
  - Hecho cuando: `tests/test_safety_perf.py` verifica que, indexados dos archivos y preguntando por uno, lo recibido por el cliente falso contiene solo el mensaje de sistema, el historial enviado, la pregunta y los fragmentos recuperados, sin el texto del fragmento no recuperado ni la clave; que con contenido malicioso (`import os; os.system("touch PWNED")`) `answer` no llama a `exec` ni a `eval`, no aparece `PWNED` y el módulo no aparece en `sys.modules`; y que construir el mensaje para el modelo (`_build_messages` con 5 fragmentos de 6.000 caracteres y 10 mensajes de historial) y procesar la respuesta (`_interpret` sobre la respuesta a esos mismos 5 fragmentos, también de 6.000 caracteres) tardan menos de 1 s en total.

- [x] **T10. Verificación final, comprobación con clave real y memoria.** RNF-1 a RNF-7
  - Hecho cuando: `ruff check .` y `pytest -q` pasan sin red, sin claves y sin llamadas reales; cada RF, RNF y caso límite de la spec tiene su prueba (tabla del plan revisada punto por punto); se revisa el código contra los principios 3, 4, 5, 6 y 7 de la constitución; `plan.md` y `tasks.md` pasan a "implementado"; y `MEMORY.md` recoge que la spec 003 está implementada, con las decisiones de marcas `[Fn]`, `ungrounded_answer` y centinela, el cliente diferido y la búsqueda solo con la pregunta actual.
  - Prueba manual (donde se comprueba la disponibilidad real de `MODEL_NAME`), fuera de `pytest -q` y del CI: con una clave real en el entorno, indexar un archivo pequeño y hacer una pregunta con respuesta y otra sin ella, para anotar en `MEMORY.md` si el modelo respeta las marcas y el centinela. Se omite por defecto (constitución, principio 4).

## Fuera de estas tareas
- Rutas HTTP, validación de peticiones, códigos de estado y carga de `.env` (spec 004).
- Interfaz web, vista de citas y respuesta progresiva (spec 005).
- Servidor MCP (spec 006).
- Reformular la pregunta con el historial antes de buscar.
- Guardar historial o respuestas, contar tokens o costes, elegir el modelo por petición y caché de respuestas.
- Citar líneas concretas dentro de un fragmento.
- Evaluar la calidad de las respuestas con el modelo real (spec 008d).
