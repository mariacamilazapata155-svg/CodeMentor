# Plan 005 - Interfaz web

Estado: implementada


## Alcance y supuestos
- Se implementa la capa de presentación: la página que se sirve en `/`, sus recursos (`/static/*`), el icono (`/favicon.ico`) y el comportamiento del navegador (`static/app.js`). No cambia ninguna capacidad de las specs 001 a 004.
- No se toca el contrato de `/upload` ni el de `/chat`, ni `models.py`, ni `requirements.txt`, ni `bot.py`, `rag.py`, `storage.py` o `mcp_server.py`. `static/` solo presenta: llama a las dos rutas y muestra lo recibido (RNF-2).
- No se añaden dependencias ni herramientas de frontend: sin Node, sin gestores de paquetes y sin compilación (RNF-1). Se sirve con `uvicorn app.main:app`, el mismo arranque que la API.
- `main.py` gana tres cosas y nada más: la constante `STATIC_DIR`, el montaje de `/static` y dos rutas de fichero (`GET /` y `GET /favicon.ico`). No contiene lógica de presentación, textos de la interfaz ni reglas de validación del navegador.
- No hay fechas ni horas en el dominio: ninguna función usa un parámetro `hoy` ni lee el reloj. Todas las funciones puras reciben todas sus entradas y no leen DOM, reloj, red ni almacenamiento.
- Las rutas nuevas no entran en la documentación automática (`include_in_schema=False`): la spec 004 RF-23 fija que `/docs` describe las tres rutas de la API y la interfaz no forma parte de ese contrato. `tests/test_api_docs.py` debe seguir en verde.

Supuestos que se confirman en T0 contra las versiones fijadas en `requirements.txt` (`starlette==1.9.0`, `fastapi==0.161.0`, `python-multipart==0.0.32`). No se dan por ciertos:
1. `starlette.staticfiles.StaticFiles` y `starlette.responses.FileResponse` están disponibles con las versiones fijadas y no añaden dependencias (RNF-1). Importarlos al cargar `app.main` no rompe la prueba de `tests/test_safety_perf.py` que comprueba que importar la app no carga `sentence_transformers`.
2. Montar `/static` no tapa `/upload`, `/chat` ni `/health`: el montaje solo casa el prefijo `/static`. Un recurso estático inexistente sigue pasando por el manejador de errores de la 004, con el formato `{message, reason}` y sin `detail`. Si el 404 del montaje se saltara el manejador, **no se cambia el contrato**: se sustituye el montaje por una ruta `GET /static/{file_path:path}` que resuelve el archivo dentro de `STATIC_DIR` con `FileResponse` y lanza `HTTPException(404)` para que la traduzca el manejador de la 004.
3. `TestClient(main.app)` usado sin `with` no ejecuta `lifespan` y, por tanto, no carga el modelo. Si lo ejecutara, la prueba de RF-1 sustituye `_load_env` y `rag.warm_up` por dobles, como ya hace la 004.
4. El navegador envía `Content-Length` en `fetch` con un cuerpo JSON (`JSON.stringify`) y con un `FormData`. Es crítico: la 004 responde 411 `length_required` sin esa cabecera (RF-16 de la 004). Se verifica temprano con Chrome DevTools (petición real a `/chat` y a `/upload`); si no se envía, **PARAR y avisar al usuario**, porque cambiar la 004 queda fuera de alcance.
5. `AbortController`, `TextEncoder`, `FormData` y `fetch` están disponibles en los navegadores objetivo (Chrome de escritorio y móvil, Firefox, Edge y Safari de las dos últimas versiones).
6. `FileResponse` con una ruta absoluta funciona con cualquier directorio de trabajo. `STATIC_DIR` se calcula con `Path(__file__).resolve().parent.parent / "static"`, nunca relativo al directorio de trabajo.
7. `static/` existe al importar la app y no se sirve listado de directorios: `StaticFiles(directory=..., html=False)`.
8. Servir el SVG en `/favicon.ico` con `media_type="image/svg+xml"` no produce un 404 ni un error de consola en Chrome; el `<link rel="icon">` apunta al SVG y la ruta `.ico` es solo la petición automática de respaldo.

## Aprobaciones necesarias (según `AGENTS.md`)
`AGENTS.md` exige preguntar antes de añadir dependencias o crear archivos fuera de la estructura. Esto es lo que cambia:
1. **`app/main.py`**: se añaden `STATIC_DIR`, `app.mount("/static", StaticFiles(...), name="static")` y las rutas `GET /` (`index_page`) y `GET /favicon.ico` (`favicon`), las dos con `include_in_schema=False`. No se modifican las rutas existentes ni los manejadores de error.
2. **`static/index.html`**: se sustituye el esqueleto por la estructura semántica completa (cabecera, subida, conversación, `<noscript>`).
3. **`static/style.css`**: se amplía con los estilos del layout, formularios, avisos, mensajes y citas. Se añaden tokens nuevos a `:root` (`--color-border-strong`, `--size-touch`, `--border-width`, `--focus-width`, `--content-max`, `--panel-width` y, si el CSS los usa, `--line-height-base`, `--line-height-tight`, `--font-weight-regular` y `--font-weight-semibold`); los existentes no cambian de valor salvo que T3 lo justifique por contraste.
4. **`static/app.js`**: se implementa el estado, las funciones puras, las llamadas a la API y el render. Sin frameworks, sin `type="module"` (se carga con `defer`).
5. **Archivo nuevo `static/favicon.svg`**: icono servido, necesario para RF-1 y RF-2. No está en la estructura de `AGENTS.md`, así que se aprueba aquí. Alternativa descartada: icono como data URI en el `<head>`, que no es un recurso servido y deja la petición de `/favicon.ico` sin cubrir. Alternativa descartada: icono desde un dominio externo, prohibido por RF-31.
6. **Archivo nuevo `tests/test_static_ui.py`**: servicio de estáticos y guardas de fuente. No prueba comportamiento visual ni ejecuta JavaScript.
7. **Nada más**: sin dependencias nuevas, sin cambios en `models.py`, sin cambios en el contrato de la 004, sin cambios en CORS, sin `Dockerfile` y sin tocar `docs/roadmap.md` en esta fase.

## Contrato consumido (sin cambios)
| Ruta | 200 | Errores |
|---|---|---|
| `POST /upload` | `file_path`, `chunks_indexed`, `total_chunks`, `used_windows`, `message` (`UploadResponse`) | 400, 411, 413, 422, 500 con `{message, reason}` |
| `POST /chat` | `reply`, `citations[]` (`number`, `file_path`, `symbol_name`, `start_line`, `end_line`), `reason` (siempre presente: `null` o motivo) | 400, 411, 413, 422, 500, 502, 503, 504 con `{message, reason}` |

La interfaz lee `message` de los errores y `reason` solo para distinguir `empty_index` de los otros tres resultados sin respuesta. `used_windows` no se muestra por separado (RF-10). La clave `reason` del 200 se lee siempre; la 004 la serializa como `null` cuando la respuesta está fundamentada.

## Archivos y responsabilidades
- `app/main.py`: `STATIC_DIR`, montaje de `/static`, `GET /`, `GET /favicon.ico`. Solo sirve ficheros; no redacta textos, no valida el archivo y no conoce el estado de la conversación.
- `static/index.html`: estructura semántica, formularios, etiquetas asociadas, estado vacío y `<noscript>`. Sin estilos en línea y sin manejadores `on*`.
- `static/style.css`: tokens existentes y nuevos, clases BEM, layout de una y dos columnas, foco visible, contraste y ajuste de textos largos. Ningún color, espacio, tamaño ni sombra literal fuera de `:root` (la única excepción es la condición `@media`, que no admite `var()`).
- `static/app.js`: constantes, funciones puras, estado en memoria, llamadas a la API, render seguro con `textContent` y creación de nodos, manejo de estados y accesibilidad. Sin dependencias, sin almacenamiento y sin registro.
- `static/favicon.svg`: icono cuadrado, sin texto, con los colores del proyecto escritos en el propio SVG (no puede leer variables CSS).
- `tests/test_static_ui.py`: servicio de `/`, `/static/*` y `/favicon.ico`, formato de error del 404 estático, rutas de la API intactas, `/` sin clave ni modelo, y guardas de fuente de HTML, CSS y JS. No prueba el comportamiento visual.

## Funciones puras (`static/app.js`)
Todas reciben sus entradas, no leen DOM, reloj, red ni almacenamiento, y no mutan sus argumentos. `Citation` es `{number, file_path, symbol_name, start_line, end_line}`; `Exchange` es `{question, reply, citations}`; `ChatMessage` es `{role, content}`.

| Función | Firma | Qué hace | RF |
|---|---|---|---|
| `effectivePath` | `(pathValue: string, fileName: string) -> string` | Devuelve `pathValue` si tiene al menos un carácter, sin recortar; si no, `fileName`. No normaliza. | RF-7 |
| `isBlank` | `(value: string) -> boolean` | `value.trim().length === 0`. Cuenta como vacío el espacio, el tabulador y el espacio duro. | RF-15 |
| `isPythonPath` | `(path: string) -> boolean` | `true` si la ruta está en blanco (la API decide) o si `path.toLowerCase().endsWith(".py")`. | RF-7 |
| `countCodePoints` | `(text: string) -> number` | `Array.from(text).length`: cuenta puntos de código, no unidades UTF-16. | RF-16 |
| `truncateCodePoints` | `(text: string, max: number) -> string` | Corta a `max` puntos de código sin partir un par sustituto. | RF-18 |
| `formatLineRange` | `(start: number, end: number) -> string` | `"línea X"` si `start === end`; `"líneas X–Y"` en cualquier otro caso (guion medio `U+2013`). | RF-20 |
| `sortCitations` | `(citations: Citation[]) -> Citation[]` | Copia ordenada de forma ascendente y estable por `number`. No cambia números ni datos. | RF-19, RF-27 |
| `buildHistory` | `(exchanges: Exchange[]) -> ChatMessage[]` | Un par `user`/`assistant` por intercambio, en orden, con cada contenido recortado a `MAX_HISTORY_CONTENT_CODE_POINTS`; devuelve los últimos `MAX_HISTORY_MESSAGES` (10, par). | RF-18 |
| `serializedBytes` | `(value: unknown) -> number` | `new TextEncoder().encode(JSON.stringify(value)).length`: los mismos bytes que envía `fetch`. | RF-18 |
| `fitHistoryToBytes` | `(message: string, history: ChatMessage[], limit: number) -> ChatMessage[]` | Copia del historial que, con `message`, serializa como máximo `limit`; descarta intercambios completos desde el más antiguo. | RF-18 |
| `buildChatBody` | `(message: string, history: ChatMessage[]) -> {message, history}` | Cuerpo del chat con `history` siempre presente y `[]` cuando está vacío. | RF-17 |
| `parseErrorMessage` | `(body: unknown) -> string \| null` | Devuelve `body.message` si es un objeto con `message` de texto no vacío; `null` en cualquier otro caso. | RF-11, RF-12, RF-23, RF-24 |
| `isUploadSuccess` | `(body: unknown) -> boolean` | Objeto con `message` y `file_path` de texto y `chunks_indexed` y `total_chunks` numéricos. No exige `used_windows` (no se muestra). | RF-10, RF-12 |
| `isChatSuccess` | `(body: unknown) -> boolean` | Objeto con `reason === null`, `reply` de texto y `citations` como lista de citas válidas (puede estar vacía). | RF-19, RF-24 |
| `isChatResult` | `(body: unknown) -> boolean` | Objeto con `reply` de texto, `reason` nulo o uno de los cuatro resultados sin respuesta y `citations` como lista (vacía permitida). Es la puerta antes de ramificar por `reason`. | RF-22, RF-24 |
| `isCitation` | `(value: unknown) -> boolean` | Objeto con `number`, `start_line` y `end_line` numéricos y `file_path` y `symbol_name` de texto. Auxiliar de las dos anteriores. | RF-20 |

Constantes (`Object.freeze`), con el nombre en inglés y el valor del plan:
`MAX_QUESTION_CODE_POINTS = 1000`, `MAX_HISTORY_MESSAGES = 10`, `MAX_HISTORY_CONTENT_CODE_POINTS = 4000`, `MAX_CHAT_BODY_BYTES = 200000`, `REQUEST_TIMEOUT_MS = 75000`.

`MAX_HISTORY_MESSAGES` tiene que ser par: `buildHistory` corta por mensajes y un número impar partiría un par. Una guarda de fuente comprueba el literal `10`.

Para poder verificar estas reglas a mano sin duplicarlas en la consola, `app.js` expone una superficie congelada `window.CodeMentor` con solo estas funciones y estas constantes, sin estado, sin referencias al DOM y sin datos. Alternativa descartada: no exponer nada y reescribir las funciones en la consola de DevTools, que comprobaría una copia y no el código entregado.

## Algoritmo
### Arranque de la página
```text
init():
    referencias = { uploadForm, uploadFile, uploadPath, uploadButton, uploadStatus,
                    chatForm, chatQuestion, chatButton, chatLog, chatPlaceholder, uploadSection }
    uploadForm.addEventListener("submit", handleUpload)
    chatForm.addEventListener("submit", handleSend)          # botón y Enter a la vez
    chatQuestion.addEventListener("keydown", onQuestionKeyDown)
    state = { exchanges: [], uploading: false, sending: false }
    # NO se llama a fetch, ni a /upload, ni a /chat, ni a /health (RF-2)
```
El script se carga con `defer`, así que el DOM ya existe y no hace falta `DOMContentLoaded`. `init` solo enlaza eventos: no provoca peticiones y no afirma nada sobre el índice.

La sección de subida ya es enfocable con `tabindex="-1"` y no necesita ningún listener de `focus`: el enlace de `empty_index` llama directamente a `uploadSection.focus()`. Ese es el único movimiento de foco de la interfaz y ocurre solo por una acción de la persona (RF-25).

```text
onQuestionKeyDown(event):
    si event.key === "Enter" y not event.shiftKey:
        si event.isComposing o event.keyCode === 229: devolver        # IME (RF-14)
        event.preventDefault()
        handleSend(event)
```
El `submit` del formulario cubre el clic y el Enter; el `keydown` solo intercepta el Enter sin Shift para que Shift+Enter inserte el salto de línea nativo del `textarea`. La comprobación de composición evita enviar mientras el método de entrada está componiendo.

### Petición con tiempo de espera
```text
async request(url, options):
    controller = new AbortController()
    timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    intentar:
        response = await fetch(url, { ...options, signal: controller.signal })
        devolver { response }
    atrapar error:
        si error.name === "AbortError": devolver { timeout: true }
        devolver { failed: true }
    finalmente:
        clearTimeout(timer)
```
Cada petición lleva su propio `AbortController`; un `timeout` se distingue de un fallo de red para elegir el aviso (RF-34). No se registra el error ni su texto.

```text
async readJson(response):
    intentar: devolver JSON.parse(await response.text())
    atrapar: devolver null            # cuerpo vacío, HTML de error o JSON roto
```
Se lee `text()` y se parsea a mano: `response.json()` lanza en un cuerpo ilegible y la interfaz no debe lanzar excepciones (RF-32).

### Flujo de subida
```text
async handleUpload(event):
    event.preventDefault()
    si state.uploading: devolver                       # doble clic (RF-9)
    file = uploadFile.files[0]
    si no file: showUploadError(MSG_UPLOAD_NO_FILE); devolver          # RF-6
    path = effectivePath(uploadPath.value, file.name)
    si not isPythonPath(path): showUploadError(MSG_UPLOAD_EXTENSION); devolver   # RF-7
    body = new FormData()
    body.append("file", file)
    si uploadPath.value.length > 0: body.append("path", uploadPath.value)        # RF-8
    state.uploading = true
    uploadButton.disabled = true
    showUploadNotice("loading", MSG_UPLOAD_LOADING)
    intentar:
        resultado = await request("/upload", { method: "POST", body })
        si resultado.timeout: showUploadError(MSG_TIMEOUT); devolver            # RF-34
        si resultado.failed: showUploadError(MSG_UPLOAD_FAILED); devolver       # RF-12
        datos = await readJson(resultado.response)
        si not resultado.response.ok:
            showUploadError(parseErrorMessage(datos) o MSG_UPLOAD_FAILED)       # RF-11, RF-12
            devolver
        si not isUploadSuccess(datos):
            showUploadError(MSG_UPLOAD_FAILED); devolver                        # RF-12
        renderUploadSuccess(datos)
        uploadFile.value = ""
        uploadPath.value = ""
    finalmente:
        state.uploading = false
        uploadButton.disabled = false
```
- El `FormData` se envía sin fijar `Content-Type`: el navegador pone el `boundary` y el `Content-Length`.
- `path` solo se añade si el campo tiene al menos un carácter; se envía sin recortar (RF-8).
- Los campos de archivo y ruta solo se vacían en el éxito (RF-10); en un error se conservan (RF-11).
- `renderUploadSuccess` sustituye el aviso anterior y escribe: `datos.message` como texto del aviso, y una lista de definiciones con `Ruta` = `datos.file_path`, `Fragmentos indexados` = `datos.chunks_indexed` y `Fragmentos en el índice` = `datos.total_chunks`. No muestra `used_windows`.
- Un aviso de error lleva el prefijo `Error: ` en el texto, para que se distinga sin depender del color (RF-11).

### Flujo de chat
```text
async handleSend(event):
    event.preventDefault()
    si state.sending: devolver                          # RF-17
    question = chatQuestion.value
    si isBlank(question): showChatError(MSG_QUESTION_EMPTY); devolver          # RF-15
    si countCodePoints(question) > MAX_QUESTION_CODE_POINTS:
        showChatError(MSG_QUESTION_TOO_LONG); devolver                         # RF-16
    hidePlaceholder()
    appendMessage("user", question)                     # RF-17, RF-26
    chatQuestion.value = ""
    history = fitHistoryToBytes(question, buildHistory(state.exchanges), MAX_CHAT_BODY_BYTES)
    payload = buildChatBody(question, history)          # history siempre presente
    state.sending = true
    chatButton.disabled = true
    loading = appendStatus(MSG_CHAT_LOADING)            # región activa
    intentar:
        resultado = await request("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        })
        si resultado.timeout: appendError(MSG_TIMEOUT); devolver               # RF-34
        si resultado.failed: appendError(MSG_CHAT_FAILED); devolver            # RF-24
        datos = await readJson(resultado.response)
        si not resultado.response.ok:
            appendError(parseErrorMessage(datos) o MSG_CHAT_FAILED)            # RF-23, RF-24
            devolver
        si not isChatResult(datos): appendError(MSG_CHAT_FAILED); devolver     # RF-24
        si datos.reason === null:
            appendAnswer(datos.reply, datos.citations)                          # RF-19, RF-21
            si datos.citations.length > 0:
                state.exchanges.push({ question, reply: datos.reply, citations: datos.citations })
            devolver
        si datos.reason === "empty_index": appendEmptyIndex(datos.reply)        # RF-22
        si no: appendNotice(datos.reply)                                       # RF-22
    finalmente:
        quitar(loading)
        state.sending = false
        chatButton.disabled = false
```
- `chatQuestion` nunca se deshabilita (RF-17, RF-25, RNF-7): solo el botón.
- La pregunta se pinta antes de esperar la respuesta y el campo se vacía al enviarla; si la petición falla, la pregunta sigue visible como mensaje de la persona y el aviso se añade debajo (RF-26).
- Una respuesta 200 con `reason` nulo y **sin** citas se pinta como mensaje del asistente, sin lista de citas y **sin** entrar en el historial: no es un intercambio fundamentado.
- `empty_index` no entra en el historial; los otros tres motivos tampoco.
- Un error de chat se pinta como error en la conversación, con `textContent` y prefijo `Error: `.
- No se mueve el foco al terminar ni se atrapa en ningún elemento (RF-25).

### Historial
```text
buildHistory(exchanges):
    mensajes = []
    por cada intercambio en exchanges:
        mensajes.push({ role: "user", content: truncateCodePoints(intercambio.question, MAX_HISTORY_CONTENT_CODE_POINTS) })
        mensajes.push({ role: "assistant", content: truncateCodePoints(intercambio.reply, MAX_HISTORY_CONTENT_CODE_POINTS) })
    devolver mensajes.slice(-MAX_HISTORY_MESSAGES)      # 10: cinco pares completos

fitHistoryToBytes(message, history, limit):
    ajustado = history.slice()
    mientras ajustado.length > 0 y serializedBytes(buildChatBody(message, ajustado)) > limit:
        ajustado = ajustado.slice(2)                    # fuera el intercambio más antiguo, completo
    devolver ajustado
```
Los topes son de transporte, no de negocio: el servidor sigue siendo la autoridad. El margen de 200.000 bytes deja 62.144 bytes libres bajo el límite de 262.144 de `/chat` para el JSON, las comas, las claves y la pregunta. La pregunta local nunca supera 1.000 puntos de código, así que con el historial vacío el cuerpo siempre cabe.

### Render
`#chat-log` es un `<ol>`: sus hijos directos son siempre `<li>`, nunca otro `<ol>`. Los mensajes, los estados de carga, los avisos, los errores y el estado `empty_index` son `<li>` hermanos; las citas van dentro del `<li>` del mensaje del asistente, en un `<ol class="citations">` anidado.
```text
appendMessage(role, text) -> HTMLLIElement:
    li = document.createElement("li")
    li.className = "message message--" + role
    etiqueta = document.createElement("span")
    etiqueta.className = "message__role"
    etiqueta.textContent = TEXTO_DE_ROL[role]          # "Tú" / "Asistente"
    cuerpo = document.createElement("p")
    cuerpo.className = "message__text"
    cuerpo.textContent = text                          # RF-27, RF-28: nunca innerHTML
    li.append(etiqueta, cuerpo)
    chatLog.append(li)
    devolver li

appendAnswer(reply, citations):
    item = appendMessage("assistant", reply)           # saltos de línea por CSS `white-space: pre-wrap`
    si citations.length > 0:
        item.append(appendCitationList(sortCitations(citations)))   # el <ol> vive dentro del <li>

appendCitationList(citations) -> HTMLOListElement:
    ol.className = "citations"; ol.setAttribute("aria-label", "Citas de la respuesta")
    por cada c en citations:
        li.className = "citation"
        span "citation__number": "[F" + c.number + "]"
        span "citation__path":   c.file_path
        span "citation__symbol": c.symbol_name
        span "citation__lines":  formatLineRange(c.start_line, c.end_line)
        todos con textContent y sin recortar
    devolver ol                                       # se anida en el <li> del mensaje
```
- Las marcas `[Fn]` del `reply` se dejan tal cual: no se convierten en enlaces ni se renumeran. Así una marca sin cita o una cita sin marca se ven como llegaron (RF-21) y no hay que interpretar el texto del modelo (RF-27).
- Las citas se ordenan solo para presentarlas; `state.exchanges` guarda las citas como llegaron (RF-19, RF-27).
- Los valores largos se ajustan en varias líneas por CSS (`overflow-wrap: anywhere`), no se recortan (RF-20).

### Estado sin índice y resultados sin respuesta
```text
appendEmptyIndex(reply):
    li.className = "message message--state"
    strong.textContent = "Sin código indexado"
    p.textContent = reply
    a.href = "#subida"; a.textContent = "Subir un archivo .py"
    a.addEventListener("click", () => uploadSection.focus())   # foco solo por acción de la persona
    sin lista de citas y sin tocar state.exchanges             # RF-22

appendNotice(reply):
    li.className = "message message--notice"
    etiqueta.textContent = "Aviso"; p.textContent = reply
    sin citas y sin tocar state.exchanges                      # RF-22
```
La acción de `empty_index` es un enlace real al formulario de subida, con la sección `tabindex="-1"` para que el foco llegue al pulsarla con teclado. Es la única vez que la interfaz mueve el foco, y solo tras una acción de la persona (RF-25).

### Mensajes propios (literales)
| Constante / uso | Texto |
|---|---|
| `MSG_UPLOAD_NO_FILE` | `Elige un archivo .py antes de subir.` |
| `MSG_UPLOAD_EXTENSION` | `Solo se aceptan archivos de Python (.py). Revisa el nombre del archivo o la ruta.` |
| `MSG_UPLOAD_LOADING` | `Indexando el archivo…` |
| `MSG_UPLOAD_FAILED` | `No se pudo completar la subida. Inténtalo de nuevo.` |
| `MSG_QUESTION_EMPTY` | `Escribe una pregunta antes de enviar.` |
| `MSG_QUESTION_TOO_LONG` | `La pregunta no puede tener más de 1.000 caracteres.` |
| `MSG_CHAT_LOADING` | `Buscando en el código…` |
| `MSG_CHAT_FAILED` | `No se pudo obtener la respuesta. Inténtalo de nuevo.` |
| `MSG_TIMEOUT` | `No se recibió respuesta a tiempo. Inténtalo de nuevo.` |
| `PREFIX_ERROR` | `Error: ` |
| Rol de persona / asistente / aviso | `Tú` / `Asistente` / `Aviso` |
| Título del estado sin índice / acción | `Sin código indexado` / `Subir un archivo .py` |
| Etiquetas de éxito | `Ruta` / `Fragmentos indexados` / `Fragmentos en el índice` |

## Interfaz
### Estructura de la página
```text
<body>
  <header class="header">
    <h1 class="header__title">CodeMentor</h1>
    <p class="header__subtitle">Pregunta por tu código y obtén respuestas con citas.</p>
  </header>
  <main class="main">
    <noscript>
      <p class="notice notice--error">Esta interfaz necesita JavaScript para funcionar.
      Actívalo en el navegador y vuelve a cargar la página.</p>
    </noscript>
    <section class="panel panel--upload" id="subida" tabindex="-1" aria-labelledby="subida-title">
      <h2 class="panel__title" id="subida-title">Subir código</h2>
      <form class="form" id="upload-form" novalidate>
        <label class="field__label" for="upload-file">Archivo de Python (.py)</label>
        <input class="field__input" id="upload-file" name="file" type="file" accept=".py"
               aria-describedby="upload-help upload-status" />
        <label class="field__label" for="upload-path">Ruta en el proyecto (opcional)</label>
        <input class="field__input" id="upload-path" name="path" type="text" autocomplete="off"
               aria-describedby="upload-help upload-status" />
        <p class="field__help" id="upload-help">Si dejas la ruta vacía, se usa el nombre del archivo.</p>
        <button class="button button--primary" id="upload-submit" type="submit">Indexar archivo</button>
        <div class="notice" id="upload-status" role="status" aria-live="polite"></div>
      </form>
    </section>
    <section class="panel panel--chat" aria-labelledby="chat-title">
      <h2 class="panel__title" id="chat-title">Conversación</h2>
      <p class="chat__empty" id="chat-placeholder">Sube un archivo .py y escribe una pregunta para consultar tu código.</p>
      <ol class="chat__log" id="chat-log" role="log" aria-label="Conversación"></ol>
      <form class="form" id="chat-form" novalidate>
        <label class="field__label" for="chat-question">Tu pregunta</label>
        <textarea class="field__input field__input--area" id="chat-question" name="message" rows="3"
                  aria-describedby="chat-help"></textarea>
        <p class="field__help" id="chat-help">Pulsa Enter para enviar. Usa Shift+Enter para añadir una línea.</p>
        <button class="button button--primary" id="chat-submit" type="submit">Preguntar</button>
      </form>
    </section>
  </main>
</body>
```
- Un solo `<h1>`, dos `<h2>` y ningún salto de nivel (RNF-3).
- `<html lang="es">`, `<meta charset="utf-8">`, `<meta name="viewport" content="width=device-width, initial-scale=1">` y `<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">`.
- El `input type="file"` no lleva `multiple` (RF-5) y el `form` no lleva `required`: la obligatoriedad se gestiona en la página (RF-5).
- El estado vacío es texto estático de HTML; se oculta con `hidden` al primer mensaje y no se vuelve a mostrar (RF-3, RF-26).
- Los avisos de subida viven en `#upload-status`, dentro de la sección de subida, y se sustituyen en cada subida (RF-10, RF-11, RF-26). Los de chat, en `#chat-log`.
- Dentro de `#chat-log` todos los hijos directos son `<li>`: mensajes, estados de carga, avisos, errores y `empty_index`. Las citas no son hermanas del mensaje: van en un `<ol class="citations">` dentro del `<li>` del mensaje del asistente.
- `role="log"` en la conversación y `role="status"` en el aviso de subida son las regiones activas de 4.1.3. Un mensaje nuevo se anuncia al añadirse; el estado de carga del chat también, porque es un elemento más del registro.

### Estados y dónde se ven
| Estado | Dónde | Cómo se reconoce |
|---|---|---|
| Sin conversación | `#chat-placeholder` | Texto de invitación, sin citas y sin afirmar nada del índice (RF-3) |
| Subida en curso | `#upload-status` | `Indexando el archivo…`, botón de subida deshabilitado |
| Subida correcta | `#upload-status` | Mensaje de la API + ruta + dos contadores; sustituye al anterior |
| Error de subida | `#upload-status` | Prefijo `Error: ` y el `message` de la API, o el genérico |
| Pregunta en curso | `#chat-log` | `Buscando en el código…`, botón deshabilitado, campo editable |
| Respuesta fundamentada | `#chat-log` | Mensaje del asistente con sus citas ordenadas |
| Resultado sin respuesta | `#chat-log` | `Aviso` + `reply`, sin citas |
| Sin código indexado | `#chat-log` | `Sin código indexado`, `reply` y la acción de subir |
| Error de chat | `#chat-log` | `Error: ` + `message` de la API o el genérico |
| Sin JavaScript | `noscript` | Texto visible sin scripts |

### Accesibilidad
- Etiqueta visible y `for`/`id` en los cuatro controles (3.3.2). Los textos de ayuda y el aviso de subida se asocian con `aria-describedby` (3.3.1).
- Foco visible en todos los enfocables: `outline: var(--focus-width) solid var(--color-primary)` con `outline-offset`, sin `outline: none` (2.4.7).
- Orden de tabulación igual al visual: archivo, ruta, botón de subida, pregunta, botón de preguntar. Es el mismo orden del DOM y del layout (2.4.3).
- Sin movimiento automático del foco ni trampas (RF-25, 2.1.2). La acción de `empty_index` mueve el foco solo al pulsarla.
- Los mensajes de error se identifican con texto; el color es un refuerzo, nunca el único indicador (3.3.1, RF-11).
- Las citas no son interactivas ni enfocables: se leen en orden dentro del mensaje.

### Responsive y diseño
- Una columna por defecto. A partir de `@media (min-width: 60rem)` el layout es de dos columnas: subida a la izquierda (`--panel-width`) y conversación a la derecha; el orden visual coincide con el del DOM.
- Sin `overflow-x` en `body`; `min-width: 0` en los elementos de rejilla para que el texto no ensanche la página; `overflow-wrap: anywhere` en rutas, símbolos y textos de respuesta.
- A 375 px los controles táctiles miden al menos `var(--size-touch)` (44 px): botones con `min-height`, campo de archivo con `min-height` y `::file-selector-button` con `min-height` y `padding`. El texto del `textarea` usa `var(--font-size-base)` (16 px) para que el navegador móvil no haga zoom.
- Solo variables CSS para color, espacio, tipografía, radios, sombras y longitudes; clases BEM (`.panel__title`, `.message--assistant`, `.citation__lines`); ningún `style="..."` ni manejador `on*="..."` (RNF-10). La regla exacta, comprobable por inspección y por guarda: ningún color hexadecimal, `rgb()`, `rgba()`, `hsl()` ni `hsla()` fuera de `:root`; ninguna longitud con `px`, `rem`, `em` o `pt` fuera de `:root` y de la condición `@media`; se permiten los valores estructurales `0`, `100%`, `auto`, `1fr`, `min-content`, `max-content`, `fit-content`, `none`, `inherit`, `initial`, `unset`, `revert`, `transparent` y `currentColor`; los tamaños, pesos e interlineados de texto salen siempre de variables. La condición `@media (min-width: 60rem)` es la única longitud literal fuera de `:root` y se documenta como excepción estructural, porque CSS no admite `var()` en una condición de media.
- `--color-border` (`#d1d9e0`) no alcanza 3:1 sobre blanco: los bordes de campo y los separadores que cuentan para 1.4.11 usan `--color-border-strong`. `--color-text-muted` (`#59636e`) sí supera 4,5:1 sobre `--color-bg` (`#f7f7f8`).
- Sin animaciones ni transiciones, así que no hace falta `prefers-reduced-motion`.

## Decisiones y alternativas descartadas
| Decisión | Por qué | Alternativa descartada |
|---|---|---|
| Servir `/` con `FileResponse` y `/static` con un montaje `StaticFiles(html=False)` | Es el mecanismo de Starlette, no añade dependencias y respeta el orden de las rutas; `html=False` evita el listado de directorios | Montar `static/` en `/`: taparía `/upload`, `/chat` y `/health` |
| `GET /favicon.ico` devuelve el mismo SVG | Cubre la petición automática del navegador y cumple que ningún recurso propio da 404 (RF-2, RF-32) | Dejar solo el `<link rel="icon">`: Chrome puede pedir `/favicon.ico` igualmente y daría 404 |
| `favicon.svg` como archivo aparte | Es el único formato de icono que se puede escribir a mano sin binarios y sin dependencias; el SVG es texto | Icono como data URI: no es un recurso servido (RF-2) |
| Rutas estáticas fuera de `/docs` (`include_in_schema=False`) | La 004 RF-23 fija la documentación de las tres rutas de la API; añadir rutas de presentación cambia ese contrato | Documentarlas: obliga a tocar la 004 y confunde API con interfaz |
| Un solo `app.js` con un IIFE y `defer` | Sin módulos, sin bundler y sin peticiones extra; el orden de carga es explícito | Varios archivos o `type="module"`: más peticiones y ningún beneficio con este tamaño |
| `textContent` y nodos creados a mano | Es la única forma de que el contenido no confiable no se interprete (RF-28); sin dependencias de saneado | `innerHTML` con escape manual: un fallo de escape abre XSS; una biblioteca de saneado rompe el principio 1 |
| Sin persistencia ni caché propia | RF-30 y principio 5; recargar borra conversación y aviso de subida | `localStorage`/`sessionStorage`: guardaría preguntas y respuestas de código en el equipo |
| Validación local mínima (archivo, extensión de la ruta efectiva, pregunta vacía o larga) | RF-7 pide no rechazar en cliente lo que la API aceptaría (tamaño, codificación, ruta de solo espacios) | Validar tamaño y codificación en el cliente: duplica reglas y discrepa con la 002 |
| Historial solo con intercambios fundamentados | Evita meter errores y avisos en el contexto del modelo (RF-18) | Enviar todo lo mostrado: contamina el prompt |
| Citas ordenadas de forma ascendente al presentarlas | Hace seguibles las marcas `[Fn]`; no altera números ni datos (RF-19, RF-27) | Respetar el orden de llegada: las marcas quedan desordenadas |
| `empty_index` con estado propio y acción | Es el único resultado que se arregla subiendo un archivo (RF-22) | Tratarlo como aviso genérico: no indica qué hacer |
| Avisos de subida en su zona y errores de chat en la conversación | Cada herramienta tiene su estado; se sustituyen sin ensuciar la conversación (RF-26) | Llevar todo a la conversación: mezcla dos flujos |
| Tiempo de espera de 75 s con `AbortController` | Cubre los 60 s del peor caso del chat (30 s × 2 intentos) más 15 s de red (RF-34) | Sin límite: la interfaz queda esperando indefinidamente |
| Límite de 200.000 bytes con descarte de intercambios completos | Deja 62.144 bytes de margen bajo el límite de 262.144 de `/chat` sin partir pares (RF-18) | Enviar sin margen: un 413 en conversaciones largas |
| Enter envía y Shift+Enter salta, con guarda de IME | Es lo que pide RF-14 y evita enviar a medias con un método de entrada | Enter solo en el botón: más lento en escritorio; enviar durante la composición: preguntas truncadas |
| Superficie congelada `window.CodeMentor` con las funciones puras | Permite comprobar las reglas en la consola de DevTools sin duplicarlas ni añadir Node (principios 1 y 4) | Reimplementarlas en la consola: se comprueba una copia, no el código |
| `try/catch/finally` en los dos flujos | Garantiza que el botón se rehabilita y que ningún error propio llega a la consola (RF-25, RF-32) | Dejar propagar el error: excepción en consola y botón bloqueado |
| `used_windows` no se muestra aparte | El `message` de la API ya lo dice (RF-10) | Añadir una etiqueta propia: duplica la misma información |

## Estrategia de tests
### Qué se automatiza (`pytest -q` y `ruff check .`)
Todo vive en `tests/test_static_ui.py` y no abre red, no usa clave y no carga el modelo. Usa `TestClient(main.app)` **sin** `with` (sin `lifespan`) y, cuando necesita el arranque, sustituye `_load_env` y `rag.warm_up` como ya hace la 004.

| Comprobación | Cómo |
|---|---|
| RF-1 (servicio) | `GET /` → 200, `text/html`, cuerpo con `lang="es"`, `<h1>`, `/static/style.css`, `/static/app.js` y `favicon.svg`; `GET /static/style.css` → 200 `text/css`; `/static/app.js` → 200 con tipo JavaScript; `/static/favicon.svg` → 200 `image/svg+xml`; `/favicon.ico` → 200 y el mismo cuerpo |
| RF-1 (sin clave ni modelo) | `GET /` con `set_api_key(None)`, `rag.warm_up` y `bot._get_client` sustituidos por funciones que fallan, `TestClient(main.app)` sin `with`: 200 y `store.count` sin cambios |
| RF-14 de la 004 intacto | `/static/no-existe.css` → 404 con claves `{message, reason}`, sin `detail`, `reason == "not_found"` y el mensaje de la 004; `/no-existe` sigue igual |
| Rutas de la API intactas | `/health` → 200 `{"status": "ok"}`; `GET /upload` → 405; `POST /chat` con cuerpo vacío → 422 `invalid_request`; ninguna ruta cambia de comportamiento |
| Documentación de la 004 | `/openapi.json` contiene `/health`, `/upload` y `/chat`, y **no** contiene `/`, `/favicon.ico` ni `/static` |
| RF-5, RF-14 (marcado) | `index.html` tiene un solo `<h1>`, `<header>` y `<main>`, `<html lang="es">`, un `<h2>` por sección, `noscript`, `input type="file"` sin `multiple`, `<textarea>`, y cada control tiene `<label for>` que apunta a su `id` |
| RNF-10 (marcado) | `index.html` no contiene `style=` ni atributos `on*=`; `style.css` no contiene `@import` ni `url(`; fuera del bloque `:root` no aparece ningún hexadecimal, `rgb(`, `rgba(`, `hsl(` ni `hsla(`, ni ninguna longitud con `px`, `rem`, `em` o `pt` fuera de la condición `@media`; se permiten `0`, `100%`, `auto`, `1fr`, `min-content`, `max-content`, `fit-content`, `none`, `inherit`, `initial`, `unset`, `revert`, `transparent` y `currentColor`; los tamaños, pesos e interlineados de texto usan variables |
| RF-31 | `index.html`, `style.css` y `app.js` no contienen `http://`, `https://` ni `//` de dominio externo; el `xmlns` del SVG es la única excepción y no se descarga |
| RF-28, RF-29, RF-30, RF-32 | `app.js` no contiene `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `eval(`, `new Function`, `localStorage`, `sessionStorage`, `indexedDB`, `document.write` ni `console.`; no lee el contenido del archivo (`FileReader`, `file.text()`, `file.arrayBuffer()`) |
| RF-18 (constantes) | `app.js` declara `MAX_QUESTION_CODE_POINTS = 1000`, `MAX_HISTORY_MESSAGES = 10`, `MAX_HISTORY_CONTENT_CODE_POINTS = 4000`, `MAX_CHAT_BODY_BYTES = 200000` y `REQUEST_TIMEOUT_MS = 75000` |

Las guardas se añaden en la tarea que crea el archivo correspondiente y tienen que quedar en verde al terminarla. Las guardas de estructura que dependen del HTML nuevo se escriben en T2; las de CSS, en T3; las de JS, en T4.

**Las funciones puras no se ejecutan en `pytest`.** Ejecutarlas exigiría un motor de JavaScript, es decir, Node o una dependencia nueva, y los principios 1 y 4 de la constitución exigen que `pytest -q` pase solo con `requirements.txt`. Por eso se aíslan como funciones sin efectos y se verifican a mano con la tabla de casos de T4 en la consola de Chrome DevTools, sobre `window.CodeMentor`. Es una comprobación registrada, no una prueba automática; el plan lo declara para que el criterio de finalización de la spec se lea con esa precisión.

### Qué se verifica a mano (Chrome DevTools)
Con el servicio arrancado, una clave válida y el MCP `chrome-devtools`: consola, pestaña Network, panel Application, panel de accesibilidad, emulación de dispositivo, zoom y navegación por teclado. La tabla completa de RF, RNF y casos límite está en T10.

| Área | Qué se comprueba |
|---|---|
| Carga | Solo se piden `/`, `/static/style.css`, `/static/app.js` y el icono; ninguna petición a `/upload`, `/chat` o `/health`; ningún 404 propio (RF-2, RF-32) |
| Subida | Sin archivo, `code.txt`, `.txt` con `path="app/code.py"`, `.py` con `path="app/code.txt"`, `.PY`, `.py` exacto, archivo de más de 1 MiB, no UTF-8, vacío, demasiados fragmentos, fallo de embeddings, error interno y ruta de solo espacios; en Network, `Content-Length` presente y `path` solo cuando el campo tiene texto (RF-6 a RF-13, RF-29) |
| Chat | Enter, Shift+Enter, IME, vacía, solo espacios, 1.000 y 1.001 puntos de código, varias líneas, doble Enter, `history` en cada petición, `empty_index`, los otros tres motivos, 400/413/422/502/503/504, cuerpo ilegible, red caída y tiempo agotado (RF-14 a RF-25, RF-34) |
| Render | Saltos de línea y marcas conservados, citas ordenadas, «línea X» y «líneas X–Y», rutas y símbolos largos completos, `<script>alert(1)</script>` y `<img onerror=...>` literales y sin diálogo (RF-19 a RF-21, RF-27, RF-28) |
| Sesión | La conversación crece al final, el aviso de subida se sustituye, recargar borra ambos y el panel Application no muestra cookies, almacenamiento, IndexedDB, service workers ni caché (RF-26, RF-30) |
| Accesibilidad | Nombres y roles en el árbol de accesibilidad, regiones activas, orden de tabulación, foco visible, sin trampas, zoom al 200 %, contraste con el comprobador de DevTools (RNF-3, RNF-7) |
| Responsive | 375×667, 320 px y 1280×800 sin desplazamiento horizontal, sin cortes y con controles de 44×44 px a 375 (RNF-4) |
| Idiomas y textos | Todos los textos propios en español, sin jerga, sin JSON ni motivos técnicos; los nativos del navegador quedan fuera (RNF-5) |
| Otros navegadores | Firefox, Edge y Safari de las dos últimas versiones: comprobación no bloqueante que se anota en T10 (RNF-8) |

## Cobertura de requisitos
| Requisito | Dónde se resuelve | Tarea |
|---|---|---|
| RF-1 | `STATIC_DIR`, `GET /`, montaje `/static`, `GET /favicon.ico`; HTML con `lang="es"` y `<h1>` | T1, T2 |
| RF-2 | `GET /` y `GET /favicon.ico`; `init()` sin `fetch`; `<link rel="icon">` | T1, T2, T10 |
| RF-3 | `#chat-placeholder` con texto de invitación | T2 |
| RF-4 | `<noscript>` con el texto propio | T2 |
| RF-5 | Formulario de subida con etiquetas, `accept=".py"` y sin `multiple` | T2 |
| RF-6 | `handleUpload`: comprobación de archivo y `MSG_UPLOAD_NO_FILE` | T5 |
| RF-7 | `effectivePath`, `isPythonPath` y `MSG_UPLOAD_EXTENSION` | T4, T5 |
| RF-8 | `FormData` con `file` y `path` solo si el campo tiene texto | T5 |
| RF-9 | `state.uploading`, botón deshabilitado y guarda de doble clic | T5 |
| RF-10 | `renderUploadSuccess`: mensaje, ruta y contadores; vaciado de campos | T5 |
| RF-11 | `parseErrorMessage`, prefijo `Error: ` y campos conservados | T5 |
| RF-12 | `isUploadSuccess`, `readJson` y `MSG_UPLOAD_FAILED` | T5 |
| RF-13 | El aviso de subida se sustituye en cada envío; el total es el de la API | T5, T10 |
| RF-14 | `<textarea>`, `submit` y `onQuestionKeyDown` con Enter/Shift+Enter/IME | T2, T7 |
| RF-15 | `isBlank` y `MSG_QUESTION_EMPTY` | T4, T7 |
| RF-16 | `countCodePoints` y `MSG_QUESTION_TOO_LONG` | T4, T7 |
| RF-17 | `buildChatBody` con `history` siempre; `state.sending`; campo siempre editable | T7 |
| RF-18 | `buildHistory`, `truncateCodePoints`, `serializedBytes` y `fitHistoryToBytes` | T4, T7 |
| RF-19 | `appendAnswer` con `sortCitations` y `respuesta.reply` literal | T6 |
| RF-20 | `formatLineRange` y `appendCitationList` con valores completos | T4, T6 |
| RF-21 | Marcas `[Fn]` sin transformar y citas sin renumerar | T6 |
| RF-22 | `appendEmptyIndex` y `appendNotice`; ramas de `reason` en el flujo | T6, T7 |
| RF-23 | Rama de error del chat con `parseErrorMessage` | T7 |
| RF-24 | `isChatResult`, `readJson` y `MSG_CHAT_FAILED` | T4, T7 |
| RF-25 | `finally` que retira la carga y rehabilita; sin mover el foco | T7, T8 |
| RF-26 | Registro append-only, estado vacío oculto y avisos de subida aparte | T2, T5, T7 |
| RF-27 | `textContent` en todos los textos; citas ordenadas solo al presentar | T6 |
| RF-28 | `textContent` y creación de nodos; guardas de fuente | T6 |
| RF-29 | No se lee el archivo en el navegador; solo se añade al `FormData` | T5 |
| RF-30 | Sin cookies, almacenamiento, service workers ni caché propia; estado en memoria | T2, T10 |
| RF-31 | Todo al mismo origen; guardas de URLs externas | T2, T10 |
| RF-32 | `try/catch/finally`, sin `console.`, icono servido y guards de fuente | T1, T6, T10 |
| RF-33 | Sin bloqueos: solo se deshabilita el botón correspondiente; campo siempre editable | T5, T7 |
| RF-34 | `request()` con `AbortController`, 75 s y `MSG_TIMEOUT` en la zona correcta | T5, T7 |
| RNF-1 | Sin dependencias, sin Node, mismo arranque; guardas de fuente | T1 |
| RNF-2 | `app.js` solo llama a `/upload` y `/chat` y presenta lo recibido | T4, T5, T6, T7 |
| RNF-3 | Etiquetas, foco, regiones activas, contraste, reflujo y zoom | T3, T8, T9, T10 |
| RNF-4 | Layout de una y dos columnas, `--size-touch` y textos ajustados | T3, T9, T10 |
| RNF-5 | Tabla de mensajes literales y revisión manual de comprensión | T2, T5, T6, T10 |
| RNF-6 | Sin datos en el navegador ni en registros; comprobación en Application | T2, T10 |
| RNF-7 | Estado de carga en la misma interacción; campo nunca deshabilitado | T5, T7, T8 |
| RNF-8 | Chrome de escritorio y 375 px como mínimo; otros navegadores no bloqueantes | T10 |
| RNF-9 | Sin cambios en el contrato, CORS ni comportamiento de la 004 | T1 |
| RNF-10 | Solo variables CSS, clases BEM y ningún estilo en línea | T3, T9 |

## Riesgos
- **`Content-Length` en `fetch`**: si algún navegador objetivo no la envía con `FormData` o con un cuerpo JSON, la 004 responde 411 y no se puede arreglar sin cambiar su contrato (fuera de alcance). Se verifica en T0 con DevTools; si falla, se para y se avisa.
- **404 de estáticos**: el 404 de `StaticFiles` podría no pasar por el manejador de la 004. El plan tiene un recambio (ruta propia con `FileResponse` y `HTTPException(404)`) que no cambia el contrato; la decisión se toma en T0 y se prueba en T1.
- **Solapamiento del montaje `/static`**: si el montaje se registra antes que las rutas, solo intercepta su prefijo, pero conviene probar `/upload`, `/chat`, `/health` y una ruta inexistente que empiece por `/static` para descartar sorpresas de enrutado.
- **`TestClient` y `lifespan`**: si una versión de Starlette ejecutara el `lifespan` sin `with`, la prueba de `/` cargaría el modelo. Se sustituyen `_load_env` y `rag.warm_up`; si aun así se ejecuta, la prueba se ajusta, nunca el código de producción.
- **Contraste de `--color-border`**: `#d1d9e0` no llega a 3:1 sobre blanco (1.4.11). Se añade `--color-border-strong`; hay que medirlo con el comprobador de DevTools y, si tampoco llega, oscurecerlo. `--color-text-muted` debe seguir por encima de 4,5:1.
- **44×44 px del control de archivo nativo**: el alto del `input type="file"` y de su `::file-selector-button` depende del navegador. Se fuerza con `min-height` y `padding`; si Chrome no llega a 44 px, se mide la caja real y se documenta en T9, sin cambiar la spec.
- **Texto de la respuesta pintado con `textContent`**: cualquier intento de resaltar marcas convertiría el texto en marcado y abriría XSS. Se deja literal y las guardas impiden `innerHTML`.
- **Condición `@media` literal**: CSS no admite `var()` en la condición, así que `min-width: 60rem` es la única longitud literal fuera de `:root`; se documenta como excepción estructural para que la revisión de RNF-10 no la tome por un incumplimiento. La guarda de CSS distingue colores (prohibidos fuera de `:root`), longitudes (prohibidas fuera de `:root` y de la condición `@media`) y valores estructurales permitidos (`0`, `100%`, `auto`, `1fr`, `min-content`, `max-content`, `fit-content`, `none`, `inherit`, `initial`, `unset`, `revert`, `transparent`, `currentColor`).
- **Guarda de RNF-10 demasiado estricta**: una guarda por expresiones regulares puede marcar `translateY(0)` o `flex: 1 1 auto`; la lista de valores permitidos del plan evita falsos positivos y la revisión manual de T9 decide los casos dudosos.
- **Superficie `window.CodeMentor`**: expone funciones puras, sin estado ni datos. Si en una spec futura se aprueba un ejecutor de pruebas de JavaScript, puede retirarse; hoy es la vía para verificar las reglas sin duplicarlas.
- **`try/catch` global en los flujos**: cumple RF-32, pero puede ocultar un fallo de programación detrás del aviso genérico. Se compensa con la verificación manual de T10 y con las guardas de fuente.
- **Prueba del tiempo de espera**: esperar 75 s reales hace la verificación lenta. Se provoca con limitación de red en DevTools sobre una subida grande; si no se consigue, se anota como pendiente y no se simula con código de producción.
- **Servir SVG en `/favicon.ico`**: algunos navegadores podrían ignorar el tipo por la extensión. El `<link rel="icon">` apunta al SVG, así que el icono se ve igual; la ruta `.ico` solo evita el 404.

## Criterios para pasar a implementación
- Spec, plan y tareas aprobados (`spec.md` en `aprobada`; `plan.md` y `tasks.md` en `aprobada`).
- Las aprobaciones 1 a 7 resueltas por escrito y `AGENTS.md` sin contradicciones (no cambia ninguna regla permanente).
- Los supuestos 1 a 8 confirmados en T0, en especial el `Content-Length` en `fetch` y el formato de error del 404 estático.
- `tests/test_static_ui.py` acordado como el único archivo de pruebas nuevo y las guardas de fuente aceptadas como la parte automatizable.



