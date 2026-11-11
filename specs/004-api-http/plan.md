# Plan 004 — API HTTP

Estado: implementado


## Alcance y supuestos
- Se implementa la capa HTTP: tres rutas (`GET /health`, `POST /upload`, `POST /chat`), el formato de error único, los límites de petición, el arranque (cargar `.env` y calentar el modelo) y la documentación automática.
- `main.py` solo traduce HTTP (principio 3): valida formato, delega en `rag.index_file` y `bot.answer`, y convierte sus resultados en cuerpos y estados. No trocea, no busca ni arma mensajes para el modelo.
- `main.py` llama a `rag.index_file` sin pasar por `bot.py`: el indexado es una capacidad propia de la spec 002 y la regla de capas de `AGENTS.md` permite `main → rag → storage`; `bot.py` solo orquesta la respuesta (spec 003). Pasar por el bot obligaría a añadir una función de reenvío que no aporta nada.
- No se sirve `static/` ni se añade CORS: lo definirá la spec 005. No hay cambios en `bot.py`, `mcp_server.py` ni `static/`.
- Los comportamientos de las specs 001 a 003 no cambian. Hay dos cambios internos y mínimos en `rag.py` y `storage.py`, justificados abajo.
- Las rutas que indexan o esperan al modelo se declaran con `def`, no con `async def`: FastAPI las ejecuta en un grupo de hilos y el servidor no se bloquea (RNF-2). Eso exige que el índice sea seguro entre hilos (RF-22). `health` se queda `async def`: no hace nada bloqueante.
- Ninguna función depende de la fecha ni de la hora.
- Supuestos que se confirman en T0 contra la documentación de las versiones fijadas en `requirements.txt` (no se dan por ciertos; resultado en `## Resoluciones de T0 (2026-11-02)`):
  1. FastAPI procesa el cuerpo multipart al recibir la petición, antes de resolver dependencias; por eso el límite de tamaño debe vivir en un middleware que mire solo cabeceras.
  2. Starlette guarda en memoria los archivos subidos de hasta 1 MiB (1.048.576 bytes) y usa un archivo temporal por encima, que cierra y elimina al terminar la petición.
  3. `lifespan` se acepta en `FastAPI(...)` y `TestClient` lo ejecuta solo cuando se usa como gestor de contexto (`with TestClient(app) as client`).
  4. Se pueden registrar manejadores para `RequestValidationError`, para `StarletteHTTPException` y para `Exception`; en pruebas, `TestClient(app, raise_server_exceptions=False)` devuelve la respuesta 500 en lugar de relanzar el error.
  5. `python-dotenv` ofrece `load_dotenv(dotenv_path=..., override=False)`.
  6. `request.form()` es lo que FastAPI invoca para leer el formulario (se usa en una prueba para comprobar que no se llega a leer el cuerpo).
  7. Si varios campos `file` llegan en la misma petición, el comportamiento depende de FastAPI y no se garantiza (la spec lo deja fuera de alcance).
  8. Con `path: str | None = Form(None)`, un campo de formulario enviado vacío llega como `None`; el pseudocódigo cubre también que llegara como cadena vacía. Un campo con espacios llega tal cual.

## Aprobaciones necesarias (según `AGENTS.md`)
`AGENTS.md` exige preguntar antes de añadir dependencias, de cambiar esquemas de `models.py` y de tocar el formato de los datos. Esto es lo que cambia:

1. **`models.py`: `UploadResponse` pasa de vacío a definido, y se añaden `ErrorResponse` y `ApiReason`.** Son contrato HTTP.
2. **`main.py` sustituye el esqueleto** (rutas `/upload` y `/chat` que respondían 501) por la implementación real.
3. **`requirements.txt`: se añade `python-dotenv`** (principio 1) para cargar `.env`. La versión no se fija en T0: se anota el pin exacto al instalar en T9, con la última versión estable que resuelva pip, y se deja fija en `requirements.txt`.
   - Alternativa descartada: no cargar `.env` y pedir `export ANTHROPIC_API_KEY=...`. Es lo más simple, pero deja sin uso el `.env.example` y el principio 5, que ya habla de `.env`.
   - Alternativa descartada: leer `.env` con código propio. Un lector casero de `KEY=VALUE` se equivoca con comillas, comentarios y espacios.
4. **`requirements.txt`: se fija `starlette==1.9.0`.** Es la versión con la que se confirman los supuestos 2, 3 y 4 (umbral de 1 MiB, `lifespan` y manejadores de error) y la que decide el comportamiento del multipart. FastAPI la arrastra como dependencia transitiva, y fijarla evita que una resolución distinta cambie el middleware o el archivo temporal sin que nadie lo decida; el principio 4 pide que las pruebas pasen solo con `requirements.txt`, no con lo que resuelva el instalador.
   - **Corregido en T0:** con `starlette==1.9.0` el cliente de pruebas **no** usa `httpx==0.28.1`. `starlette/testclient.py:28-42` importa `httpx2` cuando está disponible, y `httpx2==2.16.0` llega hoy como dependencia transitiva de `anthropic==2.1.0` y `mcp==2.3.0`. Por eso también se fija **`httpx2==2.16.0`** en `requirements.txt`, y se declara en T9 junto a esta versión: así las pruebas usan lo declarado y no lo que resuelva el instalador (principio 4). `httpx==0.28.1` se mantiene porque es transitiva de `anthropic` y la usan otras pruebas, pero no es la que usa `TestClient`.
   - Alternativa descartada: dejar `starlette` y `httpx2` libres. Sus versiones quedarían a merced de FastAPI, de `anthropic`, de `mcp` y de la fecha de instalación.
5. **`rag.py` gana una función pública `warm_up()`** que solo llama a `_get_model()`. No cambia nada más. Sin ella, `main.py` tendría que llamar a una función privada.
6. **`storage.py` gana un `threading.RLock` interno** que protege sus métodos públicos. No cambia firmas ni comportamiento. Es necesario porque, al ejecutarse las rutas en hilos, `replace_path` (que reasigna dos atributos) podría verse a medias desde una búsqueda (RF-22).
   - Alternativa descartada: un bloqueo en `main.py` alrededor de todo. Haría que una subida esperara a un chat de hasta 30 segundos.
   - Alternativa descartada: rutas `async def` llamando directamente al código bloqueante. Evita las carreras porque todo ocurre en un solo hilo, pero congela el servidor, `/health` incluido, durante cada indexado o consulta al modelo.
7. **Excepción acotada al principio 5** (RF-18): el archivo temporal efímero de Starlette en un rango estrecho de tamaños. La constitución permite guardar en disco "si una spec aprobada lo define"; esta spec lo define y lo acota.
   - Alternativa descartada: recibir el contenido como JSON (`{"path", "content"}`). Evita el archivo temporal por completo, pero rompe `curl -F`, `UploadFile` y el patrón habitual de subida.
8. **Reglas de la subida:** solo `.py`, UTF-8 estricto (con BOM tolerado) y campo `path` opcional, donde `path` vacío equivale a ausente.
9. **Archivos de pruebas nuevos** dentro de `tests/`: `test_api_helpers.py`, `test_api_upload.py`, `test_api_chat.py`, `test_api_runtime.py`.
10. **Nada más:** ni cambios en `Chunk`, `SearchResponse`, `IndexResult`, `ChatResponse` ni en las constantes de las specs anteriores.

## Resoluciones de T0 (2026-11-02)
T0 cerrado. Comprobado contra el entorno instalado: `fastapi==0.161.0`, `starlette==1.9.0`, `httpx2==2.16.0`, `httpx==0.28.1`; `python-dotenv` no estaba instalado.

- **Aprobaciones 1 a 10:** concedidas tal cual, sin cambios de alcance. `AGENTS.md` no se toca: ninguna decisión cambia una regla permanente (la estructura de módulos, el orden de capas `main → bot → rag → storage` y las reglas de dependencias siguen igual).
- **Supuesto 1, confirmado.** `fastapi/routing.py:450-456` ejecuta `body = await request.form()` (línea 455) antes de resolver dependencias, así que el límite de tamaño debe vivir en un middleware que solo mire cabeceras.
- **Supuesto 2, confirmado con matiz.** `starlette/formparsers.py:151,234`: `spool_max_size` es 1 MiB y cada archivo va a un `SpooledTemporaryFile`; el `max_part_size` de 1 MiB (líneas 153,188-189) solo se aplica a los campos sin archivo, no a los archivos. Cierre y borrado: FastAPI registra `body.close` (`fastapi/routing.py:456`) y `starlette/datastructures.py:487-512` cierra cada `UploadFile`, cuyo `SpooledTemporaryFile.close` borra el temporal.
- **Supuesto 3, confirmado.** `fastapi/applications.py:987` pasa `lifespan=lifespan`; `starlette/testclient.py:557-572` ejecuta el `lifespan` solo dentro de `with TestClient(app)`.
- **Supuesto 4, confirmado.** `fastapi/applications.py:1002` registra el manejador de `RequestValidationError` y `:1047` el `ServerErrorMiddleware` para `Exception`; `starlette/testclient.py:418-422` devuelve 500 con `raise_server_exceptions=False` cuando no hay respuesta iniciada, y el cuerpo ya enviado cuando el manejador respondió.
- **Supuesto 5, pendiente de confirmar.** `python-dotenv` no está instalado y T0 no tenía red: `load_dotenv(dotenv_path=..., override=False)` se confirma al instalarla en T9. Si la firma no coincidiera, el único cambio afecta a `_load_env`.
- **Supuesto 6, confirmado.** `fastapi/routing.py:455`: `request.form()` es lo que invoca FastAPI; la prueba puede sustituirlo para comprobar que no se lee el cuerpo.
- **Supuesto 7, sin verificación y sin necesidad.** Varios campos `file` en una misma petición quedan fuera de alcance (spec).
- **Supuesto 8, confirmado.** `fastapi/dependencies/utils.py:828-842`: un `""` en `FormData` se convierte en `Undefined` y se aplica el default (`None`); el `if path` del pseudocódigo cubre además que llegara como cadena vacía.
- **Corrección 1, aplicada en la aprobación 4:** con `starlette==1.9.0`, `TestClient` no usa `httpx==0.28.1`. `starlette/testclient.py:28-42` importa `httpx2` si existe, y `httpx2==2.16.0` está instalado como transitiva de `anthropic==2.1.0` y `mcp==2.3.0`. Se declara `httpx2==2.16.0` en `requirements.txt` en T9, para que las pruebas pasen solo con lo declarado (principio 4).
- **Corrección 2, aplicada en "Manejadores de error":** `MultiPartException` no es una `StarletteHTTPException`; es una `Exception` normal (`starlette/formparsers.py:56`) que FastAPI convierte en `HTTPException(400)` (`fastapi/routing.py:495-499`). El resultado observable no cambia: 400 `invalid_request`.
- **`python-dotenv`:** no se fija versión en T0. Decisión: pin exacto al instalar en T9, con la última versión estable que resuelva pip, dejándola fija en `requirements.txt`. `httpx2==2.16.0` se declara en T9 junto a `python-dotenv` y `starlette==1.9.0`.
- **Resultado:** spec, plan y tareas pasan a aprobado. Sin cambios de alcance ni de requisitos; respecto al borrador solo cambian las dos correcciones y las versiones fijadas.

## Contrato de datos
| Modelo | Campos |
|---|---|
| `UploadResponse` | `file_path: str`, `chunks_indexed: int`, `total_chunks: int`, `used_windows: bool`, `message: str` |
| `ErrorResponse` | `message: str`, `reason: str` |
| `ApiReason` | StrEnum: `invalid_request`, `invalid_path`, `invalid_extension`, `invalid_encoding`, `payload_too_large`, `length_required`, `not_found`, `method_not_allowed`, `internal_error` |

- `UploadResponse` solo existe en el éxito, así que no lleva `reason`: los rechazos usan `ErrorResponse`.
- `ErrorResponse.reason` es `str` porque agrupa motivos de tres enums (`ApiReason`, `IndexReason` y `ChatReason`).
- `ChatRequest` y `ChatResponse` ya existen (spec 003) y se usan sin cambios como cuerpo de entrada y de salida de `/chat`.

## Archivos y responsabilidades
- `app/models.py`: `UploadResponse`, `ErrorResponse` y `ApiReason`. No valida reglas de negocio.
- `app/main.py`: aplicación FastAPI, middleware de tamaño, manejadores de error, dependencias, rutas, arranque. No tiene lógica de RAG, de prompt ni de reglas de indexado.
- `app/rag.py`: solo se añade `warm_up()`.
- `app/storage.py`: solo se añade el bloqueo interno.
- `tests/test_api_helpers.py`: funciones puras de `main.py` (ruta, decodificación, estados, mensajes) y el middleware llamado directamente.
- `tests/test_api_upload.py`: la ruta `/upload`.
- `tests/test_api_chat.py`: la ruta `/chat`.
- `tests/test_api_runtime.py`: arranque, errores del framework, documentación y rutas.
- `tests/test_storage.py`: se amplía con el bloqueo. `tests/test_rag.py`: se amplía con `warm_up`.
- `tests/test_safety_perf.py`: se amplía con registros y simultaneidad.
- Sin cambios en `bot.py`, `mcp_server.py`, `static/`.

## Funciones
`rag.py`
- `warm_up() -> None`: carga el modelo si aún no está cargado (`_get_model()`), sin calcular nada más. Idempotente.

`storage.py`
- `VectorStore.__init__`: crea `self._lock = threading.RLock()`.
- Cada método público (`add`, `replace_path`, `search`, `clear`) y la propiedad `count` ejecutan su cuerpo dentro de `with self._lock:` (`count` dentro de su `getter`). No se bloquea la construcción de embeddings, que ocurre fuera del almacén.

`main.py`
- `app`: `FastAPI(title=..., description=..., lifespan=_lifespan)` con textos en español.
- `_lifespan(app)`: gestor asíncrono; en el arranque llama a `_load_env()` y `_warm_up()`, y cede el control.
- `_load_env(path: Path = Path(".env")) -> None`: si el archivo existe, `load_dotenv(dotenv_path=path, override=False)`; si no, no hace nada.
- `_warm_up() -> None`: llama a `rag.warm_up()`; si lanza una excepción, registra solo `type(exc).__name__` y sigue.
- `_error(status, reason, message) -> JSONResponse`: construye el formato de error.
- `_validate_path(path: str) -> ApiReason | None`: reglas de RF-4 y RF-5.
- `_decode_source(raw: bytes) -> str | None`: `raw.decode("utf-8-sig")`; `None` si falla.
- `_status_for_index(reason) -> int` y `_status_for_chat(reason) -> int`: tablas de estados.
- `_limit_for(method, path) -> int | None`: límite de petición de `POST /upload` y `POST /chat`; `None` para cualquier otro par de método y ruta.
- `_check_body_size(request, call_next)`: middleware de RF-16 y RF-17.
- `_on_validation_error`, `_on_http_exception`, `_on_unhandled`: manejadores de error.
- `get_index_file()` y `get_answer()`: proveedores de dependencias que devuelven `rag.index_file` y `bot.answer`. Se resuelven en cada petición, de modo que las pruebas pueden usar `app.dependency_overrides` o `monkeypatch`.
- `health()`, `upload(file, path, index_file)`, `chat(request, answer)`: rutas. `health` sigue `async def`; `upload` y `chat` son `def` (RNF-2).

## Algoritmo
### Middleware de tamaño
```text
_limit_for(method, path):
    si (method, path) == ("POST", "/upload"): devolver UPLOAD_BODY_LIMIT
    si (method, path) == ("POST", "/chat"):   devolver CHAT_BODY_LIMIT
    devolver None                                  # GET /upload, GET /chat, /health, inexistentes

_check_body_size(request, call_next):
    limit = _limit_for(request.method, request.url.path)
    si limit es None: devolver await call_next(request)          # no toca otras rutas

    raw = request.headers.get("content-length")
    si raw es None: devolver _error(411, length_required, MSG_LENGTH_REQUIRED)         # RF-16
    si not (raw.isascii() y raw.isdigit()): devolver _error(400, invalid_request, MSG_INVALID_REQUEST)
    si len(raw) > 15 o int(raw) > limit:                                               # RF-17
        devolver _error(413, payload_too_large, mensaje de la ruta)
    devolver await call_next(request)
```
`len(raw) > 15` se comprueba antes de `int(raw)`: en Python 3.11 o superior, convertir una cadena de más de 4.300 dígitos lanza `ValueError`, y 15 dígitos ya superan cualquier límite razonable. El middleware solo mira cabeceras y nunca lee el cuerpo.

`_limit_for` devuelve `None` para todo lo que no sea exactamente `POST /upload` o `POST /chat`. Así `GET /upload` o `GET /chat` sin `Content-Length` no caen en 411: llegan al enrutado y responden 405 (RF-16, RF-17). La comparación es por método y ruta exactos, no por prefijo: una ruta inexistente como `/uploads` tampoco exige la cabecera y acaba en 404.

### Subida
```text
upload(file, path, index_file):
    efectiva = path if path else (file.filename o "")            # RF-2, RF-3, RF-4
    motivo = _validate_path(efectiva)                           # RF-4, RF-5
    si motivo: devolver _error(400, motivo, mensaje de motivo)

    source = _decode_source(file.file.read())                   # ya acotado por el middleware
    si source es None: devolver _error(400, invalid_encoding, MSG_INVALID_ENCODING)    # RF-6

    result = index_file(efectiva, source)                       # spec 002
    si result.reason es None:
        devolver UploadResponse(file_path=result.file_path, chunks_indexed=..., total_chunks=...,
                                used_windows=..., message=result.message)              # RF-2
    devolver _error(_status_for_index(result.reason), result.reason.value, result.message)   # RF-7
```
`path` se declara `str | None = Form(None)`. FastAPI convierte un campo enviado vacío (`path=""`) en `None`, así que la ruta efectiva pasa a ser el nombre del archivo y la respuesta es 200 (RF-4 y la definición de ruta efectiva); un `path` de solo espacios no está vacío, llega como `"   "` y se rechaza con `invalid_path`. El `if path` cubre además el caso de que el framework lo entregue como cadena vacía. No se recorta el valor en ningún punto (RF-3): `"  a.py"` se entrega tal cual y `"a.py "` falla por extensión.

```text
_validate_path(path):
    si path.strip() == "": devolver invalid_path
    si len(path) > 255: devolver invalid_path
    si algún carácter tiene categoría Unicode "Cc", "Zl" o "Zp": devolver invalid_path
    si not path.lower().endswith(".py"): devolver invalid_extension
    devolver None
```
La categoría `Cc` cubre saltos de línea, tabuladores, el carácter nulo, `DEL` y los controles C1; `Zl` y `Zp` cubren `U+2028` y `U+2029`. No se aceptan porque la ruta acaba dentro del mensaje que se envía al modelo (spec 003) y no debe poder simular líneas.

### Chat
```text
chat(req, answer):
    result = answer(req.message, req.history)                   # spec 003; nunca se reimplementa
    status = _status_for_chat(result.reason)
    si status == 200: devolver result                           # RF-10
    devolver _error(status, result.reason.value, result.reply)  # RF-11
```
El 200 usa `ChatResponse` como `response_model`, sin `response_model_exclude_none`: FastAPI serializa `"reason": null` cuando la respuesta es fundamentada. La clave no se omite; la interfaz puede leerla siempre. Esto fija la representación HTTP de la spec 003 (RF-19), que a nivel de la capacidad habla de `reason` ausente, y no cambia esa spec.

### Tablas de estados
```text
_INDEX_STATUS = { empty_content: 400, too_large: 413, too_many_chunks: 413, embedding_failed: 500 }
_CHAT_STATUS  = { empty_query: 422, query_too_long: 422, missing_api_key: 503, invalid_api_key: 503,
                  api_unavailable: 503, api_timeout: 504, api_error: 502 }
_CHAT_OK_REASONS = { empty_index, no_relevant, insufficient_context, ungrounded_answer }

_status_for_chat(reason):
    si reason es None o reason en _CHAT_OK_REASONS: devolver 200
    devolver _CHAT_STATUS[reason]
```
Una prueba recorre todos los valores de `ChatReason` e `IndexReason` y comprueba que cada uno está en alguna tabla. Si se añade un motivo nuevo sin asignarle estado, la prueba falla en lugar de devolver 200 por omisión.

### Manejadores de error
```text
_on_validation_error(request, exc): devolver _error(422, invalid_request, MSG_INVALID_REQUEST)
_on_http_exception(request, exc):
    404 → _error(404, not_found, MSG_NOT_FOUND)
    405 → _error(405, method_not_allowed, MSG_METHOD_NOT_ALLOWED)
    otro → _error(exc.status_code, invalid_request, MSG_INVALID_REQUEST)
_on_unhandled(request, exc):
    logger.error("error interno: %s", type(exc).__name__)
    devolver _error(500, internal_error, MSG_INTERNAL_ERROR)
```
Nunca se incluye `str(exc)` ni `exc.errors()` en la respuesta ni en los registros: pueden contener fragmentos de la petición.

Un `Content-Type` que no es multipart deja el formulario vacío y dispara `RequestValidationError` → 422 `invalid_request`. Un `multipart/form-data` sin `boundary` lanza `MultiPartException`: no es una `StarletteHTTPException`, es una `Exception` normal (`starlette/formparsers.py:56`) que FastAPI convierte en `HTTPException(400)` (`fastapi/routing.py:495-499`); acaba en `_on_http_exception` → 400 `invalid_request`. Son dos casos distintos y la spec los distingue a propósito. (Corregido en T0: el resultado observable es el mismo que decía el borrador, 400 `invalid_request`; solo cambia la explicación del mecanismo.)

### Arranque
```text
_lifespan(app):
    _load_env()
    _warm_up()
    yield

_load_env(path):
    si path.exists(): load_dotenv(dotenv_path=path, override=False)    # el entorno gana (RF-19, RF-21)

_warm_up():
    intentar: rag.warm_up()
    except Exception como exc: logger.warning("no se pudo calentar el modelo: %s", type(exc).__name__)   # RF-20
```
La ruta de `.env` es explícita y relativa al directorio de trabajo, no la que `load_dotenv()` buscaría por su cuenta: así las pruebas controlan qué archivo se lee y nunca cargan por accidente el `.env` real de quien desarrolla. El calentamiento se hace dentro de `lifespan`, antes de ceder el control: uvicorn no atiende ninguna petición, `/health` incluida, hasta que termina (RF-1).

### Bloqueo del almacén
```text
VectorStore.<método público>(...):
    con self._lock:
        cuerpo del método (sin cambios)
```
`replace_path` construye sus listas y matrices en variables locales y reasigna al final, todo dentro del bloqueo; una búsqueda concurrente ve el estado anterior completo o el nuevo completo. Se usa `RLock` por si un método público llama a otro.

## Configuración
Constantes en `main.py`:
| Constante | Valor | Para qué |
|---|---|---|
| `MULTIPART_MARGIN_BYTES` | `4_096` | Margen sobre el archivo para el formato multipart (RF-17) |
| `UPLOAD_BODY_LIMIT` | `rag.MAX_FILE_BYTES + MULTIPART_MARGIN_BYTES` (1.052.672) | Límite de petición de `/upload` |
| `CHAT_BODY_LIMIT` | `262_144` | Límite de petición de `/chat` |
| `MAX_PATH_CHARS` | `255` | Longitud máxima de la ruta (RF-4) |
| `DOTENV_PATH` | `Path(".env")` | Archivo de entorno |

Mensajes propios de esta capa (en español):
| Motivo | Mensaje |
|---|---|
| `invalid_request` | "La petición no es válida. Revisa los datos enviados." |
| `invalid_path` | "La ruta del archivo no es válida: no puede estar vacía, superar 255 caracteres ni contener saltos de línea u otros caracteres de control." |
| `invalid_extension` | "Solo se aceptan archivos de Python (.py)." |
| `invalid_encoding` | "No se pudo leer el archivo como texto UTF-8. Guárdalo con codificación UTF-8 y vuelve a subirlo." |
| `payload_too_large` (`/upload`) | "La petición es demasiado grande: el límite son 1.052.672 bytes (1 MiB de archivo más el margen del formulario de subida)." |
| `payload_too_large` (`/chat`) | "El mensaje y el historial son demasiado grandes." |
| `length_required` | "La petición debe indicar su tamaño (cabecera Content-Length)." |
| `not_found` | "No existe esa ruta." |
| `method_not_allowed` | "Ese método no está permitido en esta ruta." |
| `internal_error` | "Ocurrió un error interno. Inténtalo de nuevo; si sigue fallando, revisa los registros." |

Los mensajes de `empty_content`, `too_large`, `too_many_chunks`, `embedding_failed` (spec 002) y los de la spec 003 se devuelven tal cual; esta capa no los duplica. En particular, el límite de 1.048.576 bytes del archivo lo decide y lo mide la spec 002 sobre el texto ya decodificado y sin BOM; `main.py` no vuelve a contar bytes crudos.

## Interfaz
| Ruta | Entrada | Respuesta 200 | Errores |
|---|---|---|---|
| `GET /health` | — | `{"status": "ok"}` | 405 |
| `POST /upload` | multipart: `file` (obligatorio), `path` (opcional) | `UploadResponse` | 400, 411, 413, 422, 500 |
| `POST /chat` | JSON `ChatRequest` | `ChatResponse` | 400, 411, 413, 422, 500, 502, 503, 504 |

Todos los errores usan `ErrorResponse`. Los errores de cada ruta se declaran en `responses=` para que aparezcan en `/docs`, y cada uno lleva su `description` en español además del `model`: sin la descripción, la documentación muestra el código sin explicar qué significa.

## Decisiones y alternativas descartadas
| Decisión | Por qué | Alternativa descartada |
|---|---|---|
| Resultados sin respuesta del chat con estado 200 | La API funcionó; "no hay nada indexado" o "no alcanza" es un resultado, y la interfaz solo necesita leer `reason` | Devolver 404 o 204: obliga a la interfaz a tratar como error algo normal |
| Formato de error único `{message, reason}` | La interfaz muestra `message` siempre y ramifica por `reason` si quiere | Dejar el formato por defecto del framework (`{"detail": ...}`): inglés, forma distinta por origen |
| Motivos del chat convertidos en errores con su `reply` como `message` | Un solo punto donde mostrar el texto en español | Devolver `ChatResponse` con estado de error: la interfaz leería `reply` o `message` según el estado |
| Mapa de estados con prueba exhaustiva | Añadir un motivo exige decidir su estado | `dict.get(reason, 200)`: un motivo nuevo pasaría a 200 sin que nadie lo decida |
| Solo `.py` | Es lo que CodeMentor entiende; la spec 002 solo trocea Python por símbolos | Aceptar `.txt` o `.md`: se indexarían por ventanas y confundiría la cita |
| UTF-8 estricto con BOM tolerado | La cita debe ser el texto exacto del archivo; sustituir bytes lo cambiaría | `errors="replace"`: indexa texto distinto del archivo sin avisar |
| Campo `path` opcional | Distingue `a/utils.py` de `b/utils.py`, que con solo el nombre se sustituirían entre sí | Usar siempre el nombre: colisiones silenciosas; hacer `path` obligatorio: complica `curl` |
| Rechazar caracteres de control en la ruta | La ruta se inserta en el mensaje al modelo (spec 003); un salto de línea podría simular campos | Aceptarla tal cual: el `path` es un vector de inyección |
| `path` vacío equivale a ausente | Es lo que envía un formulario HTML con el campo opcional en blanco (spec 005); si diera 400, la interfaz fallaría al subir sin ruta | Tratarlo como ruta vacía y responder 400 `invalid_path`: obliga a la interfaz a omitir el campo |
| `reason: null` explícito en el 200 de `/chat` | La interfaz lee siempre la misma clave; `response_model` ya lo serializa así y no hace falta `response_model_exclude_none` | Omitir la clave con `exclude_none`: el contrato cambia según el caso |
| Límite de archivo medido sobre el texto decodificado | La spec 002 ya mide `len(source.encode("utf-8"))` después de quitar el BOM; `main.py` no duplica la regla ni lee bytes antes de decodificar | Contar bytes crudos en la capa HTTP: duplica la regla y discrepa con la 002 en archivos con BOM |
| Middleware solo para `POST /upload` y `POST /chat` | Solo esas rutas leen cuerpo; así `GET /upload` sin `Content-Length` llega al 405 y no al 411 | Aplicarlo a toda ruta existente: convierte un 405 correcto en 411 |
| Comprobar el tamaño con `Content-Length` en un middleware | El cuerpo multipart se procesa antes que las dependencias; solo un middleware puede rechazar sin leerlo | Contar bytes leyendo el cuerpo: ya habrá pasado por memoria o disco |
| Exigir `Content-Length` (411) | Sin esa cabecera no se puede acotar antes de leer; los navegadores, `curl -F` y `fetch` la envían | Aceptar transferencia por fragmentos: reabre el hueco de memoria y disco |
| Límite de `/upload` = archivo + 4.096 | El multipart añade cabeceras y fronteras; con el margen, un archivo exacto de 1 MiB cabe | Sin margen: un archivo del límite exacto se rechazaría por el formato |
| `def` en las rutas | Se ejecutan en hilos; `/health` no se bloquea durante un indexado | `async def` con código bloqueante: congela el servidor |
| Bloqueo interno en `VectorStore` | Hace atómica la lectura y la escritura del índice sin bloquear fuera del almacén | Bloqueo en `main.py`: serializa subidas con chats de hasta 30 s |
| Proveedores `Depends` | Principio 3 y pruebas sin modelo: `app.dependency_overrides` sustituye el indexado y la respuesta | Importar y llamar directamente: obliga a `monkeypatch` en cada prueba |
| `load_dotenv` con ruta explícita y `override=False` | Las pruebas controlan el archivo; las variables reales del entorno mandan | `load_dotenv()` sin argumentos: busca el `.env` real del proyecto, también en pruebas |
| El calentamiento falla sin impedir el arranque | El servicio termina de arrancar y desde entonces sirve `/health`; un fallo de red no debe tumbarlo y la primera petición reintenta | Abortar el arranque: peor experiencia sin ganancia |
| `rag.warm_up()` público | `main.py` no debe llamar a funciones privadas de otra capa | Llamar `rag._get_model()`: rompe la encapsulación |
| Registrar solo el tipo de error | RNF-3: el texto del error puede contener datos de la petición | Registrar la traza completa: riesgo de filtrar contenido |

## Estrategia de tests (`pytest`)
Todas las pruebas usan `TestClient(app, raise_server_exceptions=False)`, `app.dependency_overrides` y dobles; ninguna usa red, claves ni el modelo real. Los dobles de la spec 003 (`FakeClient`, fixtures de clave) se reutilizan en el flujo completo. Las pruebas que necesitan el arranque usan `with TestClient(app) as client` y sustituyen `_load_env` y `rag.warm_up`. Las subidas se envían con `files={"file": (nombre, bytes, tipo)}` y `data={"path": ...}`.

| RF / RNF / caso | Prueba |
|---|---|
| RF-1 | `GET /health`: 200 y `{"status": "ok"}`; con `rag.warm_up` y el cliente del modelo sustituidos por funciones que fallan, no se llaman; sin clave funciona igual; no toca el índice. No se prueba durante el calentamiento: la spec declara que el servidor no atiende hasta que termina |
| RF-2 | Con un `index_file` falso que devuelve un `IndexResult` de éxito: 200, cuerpo con los cinco campos y el falso llamado con `("a.py", "x = 1\n")`; sin `path` en el formulario, la ruta efectiva es el nombre del archivo |
| RF-3 | Con `path="src/a.py"` y archivo `b.py`: el falso recibe `"src/a.py"`; con `path="src\a.py"`, `"  a.py"` y `"a b.py"` se entrega exactamente el mismo texto, sin recortar; con `"a.py "` se rechaza por extensión (RF-5) |
| RF-4 | Rutas de 255 (ok) y 256 caracteres; de solo espacios; con `\n`, `\t`, `\x00` y `\u2028`: 400 `invalid_path` y el falso no se llama; sin `path` y con nombre de archivo vacío: 400 `invalid_path`; `path=""` con archivo `utils.py`: 200 y el falso recibe `"utils.py"` |
| RF-5 | `a.txt`, `a.js`, `a.py.txt`, `py`, `a.pyi`: 400 `invalid_extension`; `a.PY`, `app/Main.PY` y `.py` se aceptan; `"a.py "` no termina en `.py` y da 400 `invalid_extension` |
| RF-4 y RF-5 (orden) | `a\n.txt` informa `invalid_path` |
| RF-6 | `b"\xff\xfe\x00"` y Latin-1 con tildes: 400 `invalid_encoding`; con BOM: el falso recibe el texto sin BOM |
| RF-7 | Para cada `IndexReason`, un falso que lo devuelve: estado, `reason` y `message` esperados, con el formato de error |
| RF-8 | Con el índice real y dobles de embeddings: tras cada rechazo (ruta, extensión, codificación, 411, 413, y cada motivo de la spec 002) el `count` y el contenido del almacén son los de antes |
| RF-9 | Peticiones con varios fallos a la vez: gana el primero del orden; con un `Content-Length` excesivo y un `path` inválido, 413; con un `path` inválido y un archivo no UTF-8, `invalid_path` |
| RF-10 | Éxito: 200, `body["reply"]` y `body["citations"]` iguales a los del falso y `body["reason"] is None`, con la clave `"reason"` presente en el JSON. Para cada uno de los cuatro resultados sin respuesta: 200 con `citations` vacías y `body["reason"]` igual al motivo |
| RF-11 | Para cada motivo de fallo (`empty_query` 422, `query_too_long` 422, `missing_api_key` 503, `invalid_api_key` 503, `api_unavailable` 503, `api_timeout` 504, `api_error` 502): estado, `reason` y `message` iguales al `reply` |
| RF-11 (exhaustiva) | Recorre todos los valores de `ChatReason` e `IndexReason`: cada uno está en una tabla de estados |
| RF-12 | `{"message": "hola"}` sin `history`: el falso recibe `[]` |
| RF-13 | JSON mal formado, un arreglo en lugar de objeto, sin `message`, `message` numérico, `history: null`, rol `system`, `content` numérico, y `/upload` sin `file` o con `Content-Type` no multipart: 422 `invalid_request`, sin llamar a los falsos |
| RF-14 | 404, 405, 422, 500 y `multipart/form-data` sin `boundary` (400): todos con las claves `message` y `reason` y sin `detail` |
| RF-15 | Un `answer` falso que lanza `RuntimeError("secreto")`: 500 `internal_error`; el cuerpo y `caplog` no contienen "secreto" pero sí `RuntimeError` |
| RF-16 | Se llama a `_check_body_size` con una petición construida a mano: en `POST /upload` y `POST /chat`, sin `Content-Length` → 411; con `abc`, `-1`, `1.5`, `²` y cadena vacía → 400; en `GET /upload` y `GET /chat` sin `Content-Length` → pasa a `call_next` y acaba en 405, no en 411 |
| RF-17 | Con `Content-Length` igual al límite pasa a `call_next`; con límite + 1, no, y devuelve 413 sin llamar a `call_next`; con 5.000 dígitos, 413 sin `ValueError`; prueba de extremo a extremo: un cuerpo de 1,2 MiB a `/upload` da 413 con `starlette.requests.Request.form` sustituido por una función que falla (no se llegó a leer); en `GET /upload` el límite no se aplica |
| RF-17 (límites) | Se comprueba el límite de `/upload` (1.052.672) y el de `/chat` (262.144) con valores justo en el borde |
| RF-18 | Prueba de extremo a extremo: un archivo de 1.048.577 bytes sin BOM que cabe en el límite de petición llega al `index_file` real con doble de embeddings y da 413 `too_large`; con `tempfile.tempdir` redirigido a un directorio temporal de la prueba (`monkeypatch.setattr`), ese directorio y el de trabajo quedan sin archivos tras la petición |
| RF-19 | Con `with TestClient(app)`, `_load_env` y `rag.warm_up` se llaman y en ese orden; `_load_env` con un `.env` temporal define la variable, registrándola antes con `monkeypatch.setenv`/`delenv` (o guardando y restaurando) porque `load_dotenv` escribe en `os.environ` directamente; con la variable ya definida en el entorno, no se sustituye; sin `with`, el arranque no se ejecuta |
| RF-20 | Con `rag.warm_up` que lanza `RuntimeError`: el cliente arranca, `/health` da 200, `caplog` contiene `RuntimeError` y la siguiente petición que usa el modelo lo vuelve a intentar; no se afirma nada sobre el periodo en que el servidor aún no atiende |
| RF-21 | `_load_env` con una ruta inexistente: no lanza error |
| RF-22 | Hilos que suben 20 rutas distintas con `rag.index_file` y dobles mientras otros hilos buscan: sin excepciones, `count` final igual a la suma de fragmentos y cada ruta con fragmentos de una sola versión; dos subidas simultáneas de la misma ruta con versiones distintas mientras otro hilo busca: al final esa ruta tiene fragmentos de una sola versión completa, sin mezcla, y ninguna búsqueda falla; el bloqueo se comprueba con un doble de `RLock` que cuenta adquisiciones en cada método público y en la propiedad `count` de `VectorStore` |
| RF-23 | `GET /openapi.json` contiene las tres rutas, los estados de error declarados de cada una con su `description` en español, y títulos y descripciones en español |
| RNF-1 | Los endpoints reciben `index_file` y `answer` por `Depends`; con `dependency_overrides` no se importa ni se usa el modelo real; `main.py` no importa ni usa `rag.chunk_python_file` ni `bot._build_messages` |
| RNF-2 | `inspect.iscoroutinefunction` es falso para `upload` y `chat` y verdadero para `health`; con una subida lenta, `/health` responde mientras sigue en curso (una vez terminado el calentamiento) |
| RNF-3 | Con `caplog`, subidas y preguntas que provocan cada tipo de error no dejan en los registros de la aplicación el contenido del archivo, la ruta, la pregunta, el historial ni la clave. No cubre la salida del servidor web (ver riesgos) |
| RNF-4 | Cada mensaje propio de la tabla se compara con su texto exacto; todos están en español y ninguno contiene la clave ni el texto de una excepción. La comprensibilidad se revisa a mano al cerrar la spec |
| RNF-5 | En un subproceso (`sys.executable -c`), sin clave y sin `.env`: `import app.main` no importa `sentence_transformers` ni abre conexiones; con `rag.warm_up` sustituido (o el modelo en caché), `/health` responde sin cargar el modelo |
| RNF-6 | Tras subir y preguntar, no hay archivos nuevos en el directorio de trabajo; el contenido y la pregunta no aparecen en `caplog` |
| Casos límite de ruta y `path` | Dos `utils.py` con `path` distinto quedan indexados por separado; con el mismo `path`, se sustituyen; `path=""` con archivo válido usa el nombre del archivo |
| Casos límite de chat | `message` de 1.000 caracteres pasa; de 1.001: 422 `query_too_long`; vacío: 422 `empty_query`; sin fragmentos relevantes y sin clave gana el motivo de la búsqueda (cubierto por la spec 003) |
| Casos límite del cuerpo | Chat de 262.144 bytes pasa; 262.145: 413; subida de 1.052.672 pasa; 1.052.673: 413 |
| Casos límite de tamaño de archivo | 1.048.576 bytes de texto: se acepta; 1.048.577 sin BOM: 413 `too_large`; 1.048.577 bytes crudos con BOM de 3 bytes: se acepta, porque el texto decodificado son 1.048.574 bytes (spec 002) |
| Casos límite cubiertos por 002 | `\r\n` y `\r`, archivo no Python indexado por ventanas y contenido vacío: sus pruebas ya existen en `tests/test_chunking.py` y `tests/test_index.py`; la API solo comprueba que el motivo y el mensaje llegan tal cual |
| Recarga automática | No va en `pytest`: se comprueba a mano que el índice se vacía y se documenta en el README (spec 007) |
| Flujo completo | Se sube un archivo con una función con el índice real y doble de embeddings, se pregunta con el `FakeClient` de la spec 003 citando `[F1]`, y la respuesta 200 trae una cita con la ruta, el símbolo y las líneas del fragmento |

## Riesgos
- Los supuestos 1 a 8 dependen de las versiones de FastAPI, Starlette, `httpx2` y `python-dotenv`; `starlette` se fija en 1.9.0 y `httpx2` en 2.16.0 (aprobación 4) y se confirmaron en T0 salvo el 5, que se cierra al instalar `python-dotenv` en T9 (ver `## Resoluciones de T0 (2026-11-02)`). Si el 5 falla, solo se ajusta `_load_env`.
- Con recarga automática (`uvicorn --reload`), cada recarga vacía el índice y repite el calentamiento; es esperado, pero molesta al desarrollar. Se comprueba a mano y se documentará en el README (spec 007); no hay prueba automatizada.
- El calentamiento se ejecuta dentro de `lifespan`, y uvicorn no acepta conexiones hasta que `lifespan` termina. Por eso `/health` no exige clave, no carga el modelo, no toca el índice y no se bloquea por indexados ni consultas en curso, pero tampoco responde durante el arranque: la primera vez puede tardar y, si hay que descargar el modelo, varios minutos. Un fallo del calentamiento no impide arrancar; se reintenta en la primera petición que necesite el modelo.
- RNF-3 cubre los registros de la aplicación. `add_exception_handler(Exception)` hace que Starlette responda 500 y vuelva a lanzar el error, y uvicorn imprime entonces la traza completa en su propia salida. Esta capa no puede impedir esos registros del servidor; se asume y se documenta en el README (spec 007). Tampoco hay que confundirlo con el `caplog` de las pruebas.
- Exigir `Content-Length` deja fuera a clientes que envían por fragmentos; son raros, y a cambio se evita el hueco de memoria y disco.
- El archivo temporal efímero de RF-18 depende de cómo Starlette decida cuándo pasar a disco; la prueba de extremo a extremo vigila que no queden restos, pero no impide su existencia durante la petición.
- Si dos subidas de la misma ruta coinciden, gana la última en llegar al bloqueo; es coherente con la spec 002 y la prueba de RF-22 comprueba que la ruta nunca queda mezclada, pero la persona no sabrá cuál quedó. La interfaz subirá archivos uno a uno.
- El bloqueo interno hace que una búsqueda espere a que termine un reemplazo; el reemplazo es rápido (solo reasigna), pero con índices muy grandes una búsqueda larga retrasa una subida.
- `BaseHTTPMiddleware`, que usa `@app.middleware("http")`, tiene limitaciones conocidas con respuestas en flujo; aquí solo se mira una cabecera y no hay streaming, así que no afecta. Si se añade streaming (spec posterior) habrá que pasar a un middleware ASGI puro.
- Un `Content-Length` falso es imposible entre servidor y aplicación con HTTP/1.1 (el servidor corta la lectura al llegar a lo declarado), pero detrás de ciertos proxies el comportamiento puede variar; el despliegue (spec 007) deberá revisarlo.

## Criterios para pasar a implementación
- Spec, plan y tareas aprobados.
- Las aprobaciones 1 a 10 resueltas por escrito; `AGENTS.md` actualizado si alguna cambia una regla permanente.
- Los supuestos 1 a 8 confirmados contra la documentación de las versiones fijadas (T0); el 5 se cierra al instalar `python-dotenv` en T9.