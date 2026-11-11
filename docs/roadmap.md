# ROADMAP — Specs de CodeMentor

Orden de autoridad: constitución > `spec.md` > `plan.md` y `tasks.md` > código. `AGENTS.md` no puede contradecir la constitución, que vive en `docs/constitution.md`.

Cada spec vive en `specs/<carpeta>/` con `spec.md`, `plan.md` y `tasks.md`. Por el principio 7, las carpetas y los documentos de spec van en español y los identificadores de código (como `search_code` e `index_file`) en inglés.

**Regla de avance:** no se empieza una spec hasta que la anterior esté aprobada, implementada, con `ruff check .` y `pytest -q` en verde, sin incumplir la constitución y reflejada en `MEMORY.md`.

## Resumen

| Orden | Carpeta | Para qué sirve | Depende de | Estado |
|---|---|---|---|---|
| 001 | `001-buscar-fragmentos` | Recuperar fragmentos relevantes | 000 | Implementada |
| 002 | `002-indexar-codigo` | Subir `.py`, trocear con `ast` y construir el índice | 001 | Implementada |
| 003 | `003-responder-con-citas` | Bot que responde con Claude y cita archivo, símbolo y líneas | 001, 002 | Implementada |
| 004 | `004-api-http` | Exponer subida y chat por HTTP | 002, 003 | Implementada |
| 005 | `005-interfaz-web` | Chat y subida en el navegador | 004 | Implementada |
| 006 | `006-servidor-mcp` | Exponer búsqueda e indexado como herramientas MCP | 001, 002 | Implementada |
| 007 | `007-publicacion-portafolio` | README, CI y demo | 001 a 006 | Implementada |
| Extra | `008a` a `008d` | Mejoras opcionales | según cada una | Opcional |

```text
000 → 001 → 002 → 003 → 004 → 005
              └──────────────→ 006
                                 ↓
                         007 (cuando todo esté listo)
```

La 006 solo necesita 001 y 002, así que puede hacerse antes o después de la API. Se deja después para que primero tengas una versión usable de principio a fin.


## 001 — Buscar fragmentos

- **Estado:** Implementada (spec, plan y tareas ya redactados y alineados con la constitución).
- **Entrega:** `rag.search(query) -> SearchResponse` y `VectorStore`.
- **Principios que más pesan:** 3, 4, 5 y 6.

## 002 — Indexar código

- **Objetivo:** convertir archivos `.py` en fragmentos indexados, listos para la búsqueda.
- **Define:**
  - Fragmentos por función, clase y método (símbolo tipo `Clase.metodo`), más un fragmento para el código suelto del módulo (imports y constantes).
  - Plan B por ventanas de líneas cuando `ast.parse` lanza `SyntaxError` (`kind="window"`).
  - Límite de tamaño por archivo, decodificación UTF-8 con archivos mal codificados y archivos vacíos.
  - Qué pasa al subir dos veces el mismo archivo: reemplazar o ignorar.
- **Principios que más pesan:**
  - 5: nunca ejecutar, importar ni evaluar el archivo; el índice vive en memoria y no se guarda en disco.
  - 4: pruebas con un doble de embeddings y archivos de ejemplo pequeños.
  - 3: el chunking vive en `rag.py`, no en `main.py`.
- **Trampas conocidas:**
  - Las líneas de un símbolo con decoradores empiezan en el primer decorador, no en el `def`.
  - Las funciones `async` y las anidadas también cuentan.
- **Prueba manual:** aquí haces la primera con el modelo real.

## 003 — Responder con citas

- **Estado:** Implementada y validada (APROBADO el 2026-11-02).
- **Entrega:** `bot.answer(question, history) -> ChatResponse` con citas por marcas `[Fn]`.
- **Objetivo:** el bot toma la pregunta, usa `rag.search` y pide a Claude una respuesta basada solo en esos fragmentos.
- **Define:**
  - Los modelos de chat (`ChatMessage`, `ChatRequest`, `ChatResponse`), que hasta ahora estaban vacíos.
  - Si la búsqueda devuelve `reason`, no se llama al modelo y se devuelve el mensaje en español.
  - Límite del historial enviado y fallos de la API (sin clave, error, tiempo agotado).
- **Principios que más pesan:**
  - 6: las citas (archivo, símbolo, líneas) se construyen desde los resultados de la búsqueda, nunca desde el texto del modelo; el system prompt obliga a decir "no lo encontré" si el contexto no alcanza.
  - 5: a Claude solo se envían la pregunta, el historial y los fragmentos recuperados.
  - 4: cliente de Anthropic simulado con mocks; ninguna llamada real.
- **Trampa conocida:** el cliente de Anthropic se crea de forma diferida, para que la app arranque y las pruebas corran sin clave.

## 004 — API HTTP

- **Estado:** Implementada (2026-11-04); la prueba manual con clave real queda pendiente.
- **Objetivo:** que el sistema se pueda usar por HTTP.
- **Define:** `POST /upload`, `POST /chat` y `GET /health`; códigos de error (400 extensión inválida, 413 archivo demasiado grande, 422 validación, 503 falta de clave); formato único de respuestas de error; calentamiento del modelo al arrancar (`lifespan`).
- **Principios que más pesan:**
  - 3: `main.py` solo traduce HTTP; las rutas deben poder probarse sustituyendo dependencias por dobles (`dependency_overrides`).
  - 4: pruebas con `TestClient` y `httpx`.
  - 5: por defecto, Starlette guarda en un archivo temporal los archivos subidos que superan 1 MB, lo que choca con este principio. La spec debe fijar un tamaño máximo que lo evite (rechazo con 413) o declarar y justificar la excepción.

## 005 — Interfaz web

- **Estado:** Implementada (2026-11-09); la prueba manual con clave real queda pendiente.
- **Objetivo:** subir archivos y chatear desde el navegador, viendo las citas.
- **Define:** estados de carga, error y "sin código indexado"; citas visibles con archivo, símbolo y líneas; diseño adaptado al móvil con las variables CSS existentes.
- **Principios que más pesan:** 1 (sin frameworks), 3 (`static/` solo presenta) y 7 (textos de la interfaz en español).
- **Trampa conocida:** el código indexado puede contener HTML; mostrar siempre con `textContent`, nunca con `innerHTML` (riesgo XSS).
- **Pruebas:** manuales con el MCP `chrome-devtools`: servidor levantado, subir un archivo, preguntar y revisar la consola del navegador.

## 006 — Servidor MCP

- **Estado:** Implementada (2026-11-09); prueba manual con el inspector oficial completada (`tools/list`, `search_code` con índice vacío e `index_file` con el modelo en caché). La búsqueda con índice no vacío en una sola sesión la cubre la prueba de flujo.
- **Objetivo:** que otro agente pueda usar tu buscador de código como herramienta.
- **Define:** herramientas `search_code` e `index_file`, que reutilizan `rag.search` e `index_file`; errores devueltos como mensajes claros, no como excepciones sueltas.
- **Principios que más pesan:** 3 (`mcp_server.py` consume `rag.py` sin pasar por HTTP) y 4 (pruebas con dobles).
- **Trampas conocidas:**
  - Con stdio, **nunca** `print` en stdout (corrompe el protocolo); los logs van a stderr.
- **Prueba manual:** `npx @modelcontextprotocol/inspector python -m app.mcp_server`.

## 007 — Publicación y portafolio

- **Estado:** Implementada (2026-11-10).
- **Objetivo:** que cualquiera entienda y pruebe el proyecto en cinco minutos.
- **Define:** README con diagrama de arquitectura, decisiones y cómo correrlo; capturas o un GIF de demo; CI con GitHub Actions que ejecute `ruff check .` y `pytest -q`; `.env.example` y notas de seguridad.
- **Principios que más pesan:** 4 (el CI debe pasar solo con `requirements.txt`, sin claves ni descargas) y 5 (`.env` fuera del repo), .gitignore con todos los archivos que se deben omitir y no subir al repositorio.
- **Opcional:** `Dockerfile` (requiere aprobar según `AGENTS.md`).

## Extras opcionales (008a a 008d)

- **008a-persistencia-sqlite:** guardar fragmentos y embeddings para que sobrevivan al reinicio. Cambia solo `storage.py`; es el mejor ejemplo para defender la arquitectura en capas. Por el principio 5, esta es "la spec aprobada" que debe definir qué se guarda en disco, dónde, cómo se borra y que el archivo de base de datos queda fuera del repo.
- **008b-soporte-javascript:** trocear `.js`. Puede necesitar una dependencia nueva; por el principio 1, debe justificarse y aprobarse antes.
- **008c-importar-repo-github:** traer un repositorio público. Define límites de tamaño y de tasa de la API de GitHub. Por el principio 5, el código descargado nunca se ejecuta y se procesa en memoria, sin guardarlo en disco.
- **008d-evaluar-calidad-rag:** conjunto de preguntas con respuesta esperada y una métrica simple (por ejemplo, si el fragmento correcto está entre los 5 primeros). Aporta datos reales y sirve para recalibrar el umbral de 0,30. Por el principio 4, usa el modelo real solo bajo demanda y nunca en el `pytest -q` por defecto.

## Cómo trabajar cada spec

1. Revisar la idea contra la constitución y anotar qué principios pesan.
2. Redactar `spec.md` y revisarla antes de aprobar.
3. Redactar `plan.md` y `tasks.md`; aprobar los tres.
4. Ejecutar las tareas de una en una, con pruebas primero.
5. Verificar (`ruff`, `pytest`, prueba manual si aplica) y revisar el código contra los principios señalados.
6. Actualizar `MEMORY.md` y marcar la spec como implementada aquí.