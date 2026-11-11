"use strict";

// Núcleo de la interfaz: constantes, funciones puras y flujos de subida y de
// pregunta. El estado vive solo en memoria mientras la página está abierta: no
// se usa almacenamiento ni se registra nada (RF-2, RF-30, RF-32).

// Límites de transporte de la pregunta y del historial (RF-16, RF-18, RF-34).
const MAX_QUESTION_CODE_POINTS = 1000;
const MAX_HISTORY_MESSAGES = 10;
const MAX_HISTORY_CONTENT_CODE_POINTS = 4000;
const MAX_CHAT_BODY_BYTES = 200000;
const REQUEST_TIMEOUT_MS = 75000;

// Textos propios de la subida (RNF-5).
const MSG_UPLOAD_NO_FILE = "Elige un archivo .py antes de subir.";
const MSG_UPLOAD_EXTENSION = "Solo se aceptan archivos de Python (.py). Revisa el nombre del archivo o la ruta.";
const MSG_UPLOAD_LOADING = "Indexando el archivo…";
const MSG_UPLOAD_FAILED = "No se pudo completar la subida. Inténtalo de nuevo.";
const MSG_TIMEOUT = "No se recibió respuesta a tiempo. Inténtalo de nuevo.";
const PREFIX_ERROR = "Error: ";

// Textos propios del chat (RNF-5).
const MSG_QUESTION_EMPTY = "Escribe una pregunta antes de enviar.";
const MSG_QUESTION_TOO_LONG = "La pregunta no puede tener más de 1.000 caracteres.";
const MSG_CHAT_LOADING = "Buscando en el código…";
const MSG_CHAT_FAILED = "No se pudo obtener la respuesta. Inténtalo de nuevo.";

//: Etiqueta visible del rol de cada mensaje de la conversación (RNF-5).
const ROLE_LABELS = Object.freeze({
    user: "Tú",
    assistant: "Asistente",
});

/**
 * Devuelve la ruta efectiva: el campo de ruta si tiene al menos un carácter,
 * sin recortar ni normalizar; en caso contrario, el nombre del archivo (RF-7).
 *
 * @param {string} pathValue Texto del campo de ruta.
 * @param {string} fileName Nombre del archivo elegido.
 * @returns {string} Ruta efectiva.
 */
function effectivePath(pathValue, fileName) {
    return pathValue.length > 0 ? pathValue : fileName;
}

/**
 * Indica si un texto está vacío o formado solo por espacios (RF-15).
 *
 * @param {string} value Texto que se comprueba.
 * @returns {boolean} `true` si no queda ningún carácter visible.
 */
function isBlank(value) {
    return value.trim().length === 0;
}

/**
 * Indica si la ruta efectiva puede enviarse: una ruta en blanco se deja a la
 * API y el resto debe terminar en `.py` sin distinguir mayúsculas (RF-7).
 *
 * @param {string} path Ruta efectiva.
 * @returns {boolean} `true` si la interfaz no debe bloquearla.
 */
function isPythonPath(path) {
    if (isBlank(path)) {
        return true;
    }

    return path.toLowerCase().endsWith(".py");
}

/**
 * Cuenta puntos de código Unicode, no unidades UTF-16 (RF-16, RF-18).
 *
 * @param {string} text Texto que se cuenta.
 * @returns {number} Número de puntos de código.
 */
function countCodePoints(text) {
    return Array.from(text).length;
}

/**
 * Recorta a un máximo de puntos de código sin partir un par sustituto
 * (RF-18).
 *
 * @param {string} text Texto que se recorta.
 * @param {number} max Número máximo de puntos de código.
 * @returns {string} Texto original si cabe o su prefijo completo.
 */
function truncateCodePoints(text, max) {
    const points = Array.from(text);

    if (points.length <= max) {
        return text;
    }

    return points.slice(0, max).join("");
}

/**
 * Da formato al rango de líneas de una cita (RF-20).
 *
 * @param {number} start Primera línea.
 * @param {number} end Última línea.
 * @returns {string} «línea X» o «líneas X–Y».
 */
function formatLineRange(start, end) {
    if (start === end) {
        return `línea ${start}`;
    }

    return `líneas ${start}–${end}`;
}

/**
 * Copia las citas ordenadas de forma ascendente y estable por número, sin
 * cambiar números ni datos (RF-19, RF-27).
 *
 * @param {Array<object>} citations Citas recibidas.
 * @returns {Array<object>} Copia ordenada.
 */
function sortCitations(citations) {
    return citations.slice().sort((first, second) => first.number - second.number);
}

/**
 * Construye el historial por pares completos, recorta cada contenido y deja
 * solo los mensajes más recientes (RF-18).
 *
 * @param {Array<object>} exchanges Intercambios fundamentados.
 * @returns {Array<{role: string, content: string}>} Mensajes del historial.
 */
function buildHistory(exchanges) {
    const messages = [];

    for (const exchange of exchanges) {
        messages.push({
            role: "user",
            content: truncateCodePoints(
                exchange.question,
                MAX_HISTORY_CONTENT_CODE_POINTS,
            ),
        });
        messages.push({
            role: "assistant",
            content: truncateCodePoints(
                exchange.reply,
                MAX_HISTORY_CONTENT_CODE_POINTS,
            ),
        });
    }

    return messages.slice(-MAX_HISTORY_MESSAGES);
}

/**
 * Calcula los bytes que ocupará un valor al serializarlo como JSON (RF-18).
 *
 * @param {unknown} value Valor que se serializa.
 * @returns {number} Número de bytes UTF-8.
 */
function serializedBytes(value) {
    return new TextEncoder().encode(JSON.stringify(value)).length;
}

/**
 * Descarta intercambios completos desde el más antiguo hasta que el cuerpo
 * serializado no supere el límite (RF-18).
 *
 * @param {string} message Pregunta actual.
 * @param {Array<{role: string, content: string}>} history Historial previo.
 * @param {number} limit Límite en bytes.
 * @returns {Array<{role: string, content: string}>} Copia ajustada.
 */
function fitHistoryToBytes(message, history, limit) {
    let fitted = history.slice();

    while (
        fitted.length > 0 &&
        serializedBytes(buildChatBody(message, fitted)) > limit
    ) {
        fitted = fitted.slice(2);
    }

    return fitted;
}

/**
 * Construye el cuerpo de `/chat` con `history` siempre presente (RF-17).
 *
 * @param {string} message Pregunta actual.
 * @param {Array<{role: string, content: string}>} history Historial.
 * @returns {{message: string, history: Array<object>}} Cuerpo de la petición.
 */
function buildChatBody(message, history) {
    return { message, history };
}

/**
 * Extrae el mensaje de un cuerpo de error de la API (RF-11, RF-12, RF-23,
 * RF-24).
 *
 * @param {unknown} body Cuerpo recibido.
 * @returns {string | null} Mensaje no vacío o `null`.
 */
function parseErrorMessage(body) {
    if (body === null || typeof body !== "object" || Array.isArray(body)) {
        return null;
    }

    const message = body.message;

    if (typeof message !== "string" || message.trim().length === 0) {
        return null;
    }

    return message;
}

/**
 * Comprueba la forma de una cita (RF-20).
 *
 * @param {unknown} value Valor que se comprueba.
 * @returns {boolean} `true` si tiene número, ruta, símbolo y líneas.
 */
function isCitation(value) {
    return (
        value !== null &&
        typeof value === "object" &&
        Number.isFinite(value.number) &&
        typeof value.file_path === "string" &&
        typeof value.symbol_name === "string" &&
        Number.isFinite(value.start_line) &&
        Number.isFinite(value.end_line)
    );
}

/**
 * Comprueba la forma del éxito de `/upload` (RF-10, RF-12). No exige
 * `used_windows` porque no se muestra.
 *
 * @param {unknown} body Cuerpo recibido.
 * @returns {boolean} `true` si trae mensaje, ruta y contadores numéricos.
 */
function isUploadSuccess(body) {
    return (
        body !== null &&
        typeof body === "object" &&
        typeof body.message === "string" &&
        typeof body.file_path === "string" &&
        Number.isFinite(body.chunks_indexed) &&
        Number.isFinite(body.total_chunks)
    );
}

/**
 * Comprueba la forma de una respuesta fundamentada de `/chat` (RF-19, RF-24).
 *
 * @param {unknown} body Cuerpo recibido.
 * @returns {boolean} `true` si `reason` es nulo y las citas son válidas.
 */
function isChatSuccess(body) {
    return (
        body !== null &&
        typeof body === "object" &&
        body.reason === null &&
        typeof body.reply === "string" &&
        Array.isArray(body.citations) &&
        body.citations.every(isCitation)
    );
}

/**
 * Comprueba la forma de un resultado de `/chat` antes de ramificar por
 * `reason` (RF-22, RF-24).
 *
 * @param {unknown} body Cuerpo recibido.
 * @returns {boolean} `true` si trae `reply`, un `reason` conocido y citas.
 */
function isChatResult(body) {
    if (body === null || typeof body !== "object") {
        return false;
    }

    if (typeof body.reply !== "string" || !Array.isArray(body.citations)) {
        return false;
    }

    const reason = body.reason;

    return (
        reason === null ||
        reason === "empty_index" ||
        reason === "no_relevant" ||
        reason === "insufficient_context" ||
        reason === "ungrounded_answer"
    );
}

// Superficie congelada para verificar las reglas a mano en DevTools sin
// duplicarlas: solo funciones puras y constantes, sin estado ni DOM.
window.CodeMentor = Object.freeze({
    effectivePath,
    isBlank,
    isPythonPath,
    countCodePoints,
    truncateCodePoints,
    formatLineRange,
    sortCitations,
    buildHistory,
    serializedBytes,
    fitHistoryToBytes,
    buildChatBody,
    parseErrorMessage,
    isUploadSuccess,
    isChatSuccess,
    isChatResult,
    isCitation,
    MAX_QUESTION_CODE_POINTS,
    MAX_HISTORY_MESSAGES,
    MAX_HISTORY_CONTENT_CODE_POINTS,
    MAX_CHAT_BODY_BYTES,
    REQUEST_TIMEOUT_MS,
});

// --- Flujo de subida -------------------------------------------------------

//: Estado de la sesión; vive solo en memoria (RF-30).
const state = {
    exchanges: [],
    uploading: false,
    sending: false,
};

//: Referencias del DOM que `init` resuelve una sola vez.
const elements = {};

/**
 * Envía una petición con un límite de 75 s y distingue el tiempo agotado de un
 * fallo de red (RF-34).
 *
 * @param {string} url Ruta del mismo origen.
 * @param {object} options Opciones de `fetch`.
 * @returns {Promise<object>} La respuesta, `timeout` o `failed`.
 */
async function request(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal,
        });

        return { response };
    } catch (error) {
        if (error !== null && typeof error === "object" && error.name === "AbortError") {
            return { timeout: true };
        }

        return { failed: true };
    } finally {
        clearTimeout(timer);
    }
}

/**
 * Lee un cuerpo JSON sin lanzar: un cuerpo vacío, HTML o roto devuelve `null`
 * (RF-12, RF-32).
 *
 * @param {Response} response Respuesta recibida.
 * @returns {Promise<unknown>} Cuerpo parseado o `null`.
 */
async function readJson(response) {
    try {
        return JSON.parse(await response.text());
    } catch (error) {
        return null;
    }
}

/**
 * Sustituye el contenido del aviso de subida por un tipo y un texto (RF-10,
 * RF-11, RF-13).
 *
 * @param {string} kind Sufijo BEM del aviso (`error` o `success`).
 * @param {string} message Texto visible.
 */
function setUploadNotice(kind, message) {
    elements.uploadStatus.replaceChildren();
    elements.uploadStatus.className = kind
        ? `notice notice--${kind}`
        : "notice";

    const text = document.createElement("p");
    text.className = "notice__text";
    text.textContent = message;
    elements.uploadStatus.append(text);
}

/**
 * Muestra un aviso de error de subida con el prefijo textual del plan (RF-11).
 *
 * @param {string} message Mensaje de la API o propio.
 */
function showUploadError(message) {
    setUploadNotice("error", PREFIX_ERROR + message);
}

/**
 * Muestra el estado de carga de la subida (RF-9).
 */
function showUploadLoading() {
    setUploadNotice("", MSG_UPLOAD_LOADING);
}

/**
 * Añade una pareja de etiqueta y valor a la lista del resultado (RF-10).
 *
 * @param {HTMLDListElement} list Lista de definiciones.
 * @param {string} label Etiqueta visible.
 * @param {string | number} value Valor completo.
 */
function appendUploadDetail(list, label, value) {
    const term = document.createElement("dt");
    term.className = "notice__term";
    term.textContent = label;

    const description = document.createElement("dd");
    description.className = "notice__value";
    description.textContent = String(value);

    list.append(term, description);
}

/**
 * Sustituye el aviso por el resultado de una subida correcta: mensaje de la
 * API, ruta efectiva y contadores (RF-10, RF-13).
 *
 * @param {object} data Cuerpo validado de `/upload`.
 */
function renderUploadSuccess(data) {
    setUploadNotice("success", data.message);

    const list = document.createElement("dl");
    list.className = "notice__details";
    appendUploadDetail(list, "Ruta", data.file_path);
    appendUploadDetail(list, "Fragmentos indexados", data.chunks_indexed);
    appendUploadDetail(list, "Fragmentos en el índice", data.total_chunks);
    elements.uploadStatus.append(list);
}

/**
 * Gestiona el envío del formulario de subida: validación local mínima,
 * `FormData` y render del resultado (RF-6 a RF-13, RF-33, RF-34).
 *
 * @param {SubmitEvent} event Envío del formulario.
 */
async function handleUpload(event) {
    event.preventDefault();

    if (state.uploading) {
        return;
    }

    const file = elements.uploadFile.files[0];

    if (!file) {
        showUploadError(MSG_UPLOAD_NO_FILE);
        return;
    }

    const path = effectivePath(elements.uploadPath.value, file.name);

    if (!isPythonPath(path)) {
        showUploadError(MSG_UPLOAD_EXTENSION);
        return;
    }

    const body = new FormData();
    body.append("file", file);

    if (elements.uploadPath.value.length > 0) {
        body.append("path", elements.uploadPath.value);
    }

    state.uploading = true;
    elements.uploadButton.disabled = true;
    showUploadLoading();

    try {
        const result = await request("/upload", { method: "POST", body });

        if (result.timeout) {
            showUploadError(MSG_TIMEOUT);
            return;
        }

        if (result.failed) {
            showUploadError(MSG_UPLOAD_FAILED);
            return;
        }

        const data = await readJson(result.response);

        if (!result.response.ok) {
            showUploadError(parseErrorMessage(data) || MSG_UPLOAD_FAILED);
            return;
        }

        if (!isUploadSuccess(data)) {
            showUploadError(MSG_UPLOAD_FAILED);
            return;
        }

        renderUploadSuccess(data);
        elements.uploadFile.value = "";
        elements.uploadPath.value = "";
    } catch (error) {
        showUploadError(MSG_UPLOAD_FAILED);
    } finally {
        state.uploading = false;
        elements.uploadButton.disabled = false;
    }
}

// --- Render de la conversación --------------------------------------------

/**
 * Añade un mensaje como `<li>` hijo directo de `#chat-log` y devuelve el nodo
 * para poder anidar contenido (RF-26, RF-27, RF-28).
 *
 * @param {"user" | "assistant"} role Rol de quien habla.
 * @param {string} text Texto literal, sin interpretar.
 * @returns {HTMLLIElement} El mensaje creado.
 */
function appendMessage(role, text) {
    const li = document.createElement("li");
    li.className = `message message--${role}`;

    const label = document.createElement("span");
    label.className = "message__role";
    label.textContent = ROLE_LABELS[role];

    const body = document.createElement("p");
    body.className = "message__text";
    body.textContent = text;

    li.append(label, body);
    elements.chatLog.append(li);

    return li;
}

/**
 * Añade un estado de carga como `<li>` y devuelve el nodo para retirarlo al
 * terminar la petición (RF-25).
 *
 * @param {string} text Texto visible del estado.
 * @returns {HTMLLIElement} El estado creado.
 */
function appendStatus(text) {
    const li = document.createElement("li");
    li.className = "message message--status";

    const body = document.createElement("p");
    body.className = "message__text";
    body.textContent = text;

    li.append(body);
    elements.chatLog.append(li);

    return li;
}

/**
 * Añade un aviso del sistema como `<li>`, sin citas (RF-22, RF-26).
 *
 * @param {string} reply Texto literal recibido de la API.
 * @returns {HTMLLIElement} El aviso creado.
 */
function appendNotice(reply) {
    const li = document.createElement("li");
    li.className = "message message--notice";

    const label = document.createElement("span");
    label.className = "message__role";
    label.textContent = "Aviso";

    const body = document.createElement("p");
    body.className = "message__text";
    body.textContent = reply;

    li.append(label, body);
    elements.chatLog.append(li);

    return li;
}

/**
 * Añade un error de chat como `<li>`, con prefijo textual y sin citas
 * (RF-23, RF-24, RF-32).
 *
 * @param {string} message Mensaje de la API o propio.
 * @returns {HTMLLIElement} El error creado.
 */
function appendError(message) {
    const li = document.createElement("li");
    li.className = "message message--error";

    const label = document.createElement("span");
    label.className = "message__role";
    label.textContent = "Error";

    const body = document.createElement("p");
    body.className = "message__text";
    body.textContent = PREFIX_ERROR + message;

    li.append(label, body);
    elements.chatLog.append(li);

    return li;
}

/**
 * Añade el estado propio de índice vacío con una acción al formulario de
 * subida, sin citas (RF-22).
 *
 * @param {string} reply Texto literal recibido de la API.
 * @returns {HTMLLIElement} El estado creado.
 */
function appendEmptyIndex(reply) {
    const li = document.createElement("li");
    li.className = "message message--state";

    const title = document.createElement("strong");
    title.className = "message__title";
    title.textContent = "Sin código indexado";

    const body = document.createElement("p");
    body.className = "message__text";
    body.textContent = reply;

    const action = document.createElement("a");
    action.className = "message__action";
    action.href = "#subida";
    action.textContent = "Subir un archivo .py";
    action.addEventListener("click", () => elements.uploadSection.focus());

    li.append(title, body, action);
    elements.chatLog.append(li);

    return li;
}

/**
 * Crea la lista de citas con todos los valores completos; se anida dentro del
 * `<li>` del mensaje del asistente (RF-19, RF-20, RF-27).
 *
 * @param {Array<object>} citations Citas ya ordenadas para presentarlas.
 * @returns {HTMLOListElement} Lista de citas.
 */
function appendCitationList(citations) {
    const list = document.createElement("ol");
    list.className = "citations";
    list.setAttribute("aria-label", "Citas de la respuesta");

    for (const citation of citations) {
        const item = document.createElement("li");
        item.className = "citation";

        const number = document.createElement("span");
        number.className = "citation__number";
        number.textContent = `[F${citation.number}]`;

        const path = document.createElement("span");
        path.className = "citation__path";
        path.textContent = citation.file_path;

        const symbol = document.createElement("span");
        symbol.className = "citation__symbol";
        symbol.textContent = citation.symbol_name;

        const lines = document.createElement("span");
        lines.className = "citation__lines";
        lines.textContent = formatLineRange(citation.start_line, citation.end_line);

        item.append(number, path, symbol, lines);
        list.append(item);
    }

    return list;
}

/**
 * Pinta una respuesta fundamentada: el `reply` literal y, si hay, la lista de
 * citas ordenada dentro del mismo `<li>` (RF-19, RF-21, RF-27).
 *
 * @param {string} reply Texto literal del asistente.
 * @param {Array<object>} citations Citas recibidas.
 * @returns {HTMLLIElement} El mensaje del asistente.
 */
function appendAnswer(reply, citations) {
    const item = appendMessage("assistant", reply);

    if (citations.length > 0) {
        item.append(appendCitationList(sortCitations(citations)));
    }

    return item;
}

// --- Flujo de chat ---------------------------------------------------------

/**
 * Oculta el estado vacío al primer mensaje; no vuelve a mostrarse (RF-3,
 * RF-26).
 */
function hidePlaceholder() {
    elements.chatPlaceholder.hidden = true;
}

/**
 * Muestra un aviso local del chat en la conversación, con el prefijo textual
 * de error (RF-15, RF-16, RF-23).
 *
 * @param {string} message Texto propio o de la API.
 */
function showChatError(message) {
    appendError(message);
}

/**
 * Envía con Enter sin Shift; durante la composición de un método de entrada no
 * envía nada (RF-14).
 *
 * @param {KeyboardEvent} event Tecla pulsada en el campo de pregunta.
 */
function onQuestionKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        if (event.isComposing || event.keyCode === 229) {
            return;
        }

        event.preventDefault();
        handleSend(event);
    }
}

/**
 * Gestiona el envío de la pregunta: validación local mínima, historial,
 * petición y ramas del resultado (RF-14 a RF-26, RF-33, RF-34).
 *
 * @param {SubmitEvent} event Envío del formulario de pregunta.
 */
async function handleSend(event) {
    event.preventDefault();

    if (state.sending) {
        return;
    }

    const question = elements.chatQuestion.value;

    if (isBlank(question)) {
        showChatError(MSG_QUESTION_EMPTY);
        return;
    }

    if (countCodePoints(question) > MAX_QUESTION_CODE_POINTS) {
        showChatError(MSG_QUESTION_TOO_LONG);
        return;
    }

    hidePlaceholder();
    appendMessage("user", question);
    elements.chatQuestion.value = "";

    const history = fitHistoryToBytes(
        question,
        buildHistory(state.exchanges),
        MAX_CHAT_BODY_BYTES,
    );
    const payload = buildChatBody(question, history);

    state.sending = true;
    elements.chatButton.disabled = true;
    const loading = appendStatus(MSG_CHAT_LOADING);

    try {
        const result = await request("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        if (result.timeout) {
            appendError(MSG_TIMEOUT);
            return;
        }

        if (result.failed) {
            appendError(MSG_CHAT_FAILED);
            return;
        }

        const data = await readJson(result.response);

        if (!result.response.ok) {
            appendError(parseErrorMessage(data) || MSG_CHAT_FAILED);
            return;
        }

        if (!isChatResult(data)) {
            appendError(MSG_CHAT_FAILED);
            return;
        }

        if (data.reason === null) {
            appendAnswer(data.reply, data.citations);

            if (data.citations.length > 0) {
                state.exchanges.push({
                    question,
                    reply: data.reply,
                    citations: data.citations,
                });
            }

            return;
        }

        if (data.reason === "empty_index") {
            appendEmptyIndex(data.reply);
            return;
        }

        appendNotice(data.reply);
    } catch (error) {
        appendError(MSG_CHAT_FAILED);
    } finally {
        loading.remove();
        state.sending = false;
        elements.chatButton.disabled = false;
    }
}

/**
 * Punto de entrada del script: resuelve las referencias del DOM y enlaza los
 * eventos. Al cargar no se inicia ninguna petición (RF-2).
 */
function init() {
    elements.uploadForm = document.getElementById("upload-form");
    elements.uploadFile = document.getElementById("upload-file");
    elements.uploadPath = document.getElementById("upload-path");
    elements.uploadButton = document.getElementById("upload-submit");
    elements.uploadStatus = document.getElementById("upload-status");
    elements.chatForm = document.getElementById("chat-form");
    elements.chatQuestion = document.getElementById("chat-question");
    elements.chatButton = document.getElementById("chat-submit");
    elements.chatLog = document.getElementById("chat-log");
    elements.chatPlaceholder = document.getElementById("chat-placeholder");
    elements.uploadSection = document.getElementById("subida");

    elements.uploadForm.addEventListener("submit", handleUpload);
    elements.chatForm.addEventListener("submit", handleSend);
    elements.chatQuestion.addEventListener("keydown", onQuestionKeyDown);
}

init();
