# Spec 004 — API HTTP

Estado: implementada


## Contexto y objetivo
Las specs 001 a 003 dejan tres capacidades que solo se pueden usar desde código: indexar un archivo, buscar y responder con citas. Esta spec las expone por HTTP para que la interfaz web (spec 005) y cualquier cliente, como `curl`, puedan subir un archivo de Python, hacer una pregunta y recibir una respuesta con citas.

El objetivo es una capa fina de traducción: recibe peticiones, valida solo lo que es propio de HTTP (formato, tamaño, extensión, codificación), delega en `rag.index_file` y `bot.answer`, y devuelve cuerpos y códigos de estado coherentes, siempre con el mismo formato de error y mensajes en español. También fija lo que ocurre al arrancar (cargar `.env` y calentar el modelo) y protege la memoria y el disco frente a peticiones enormes.

Esta spec no sirve la interfaz web ni los archivos de `static/`, no define el servidor MCP y no añade autenticación.

## Usuarios
- La interfaz web (spec 005), que usará estas rutas desde el navegador.
- Cualquier cliente HTTP (`curl`, scripts, pruebas) de quien opera CodeMentor.
- Quien opera CodeMentor, que arranca el servicio y configura la clave.

## Historias de usuario
- HU-1. Como persona que entrega código, quiero subir un archivo `.py` y saber cuántos fragmentos se indexaron, para empezar a consultarlo.
- HU-2. Como persona que consulta código, quiero hacer una pregunta por HTTP y recibir la respuesta con sus citas, para usarla desde la interfaz.
- HU-3. Como persona que usa la API, quiero que cualquier fallo llegue con un mensaje en español, un motivo y un código HTTP coherente, y siempre con el mismo formato, para mostrarlo sin casos especiales.
- HU-4. Como operador, quiero configurar la clave en un archivo `.env` y que la primera petición no tarde por cargar el modelo, para trabajar con comodidad.
- HU-5. Como operador, quiero que un archivo enorme o una petición mal formada no agoten la memoria ni escriban en disco, para proteger el equipo y los datos.
- HU-6. Como operador, quiero comprobar que el servicio está vivo con una ruta que no exige clave, no carga el modelo, no toca el índice y no se bloquea por los indexados ni las consultas en curso, para distinguir un servicio caído de uno ocupado; el servidor no empieza a atender hasta que termina el calentamiento del arranque.
- HU-7. Como persona que integra la API, quiero una documentación automática en español de las rutas y sus errores, para saber cómo usarla.

## Definiciones
- **Ruta de archivo efectiva**: el valor del campo opcional `path` del formulario de subida, tal como llega, si está presente y no está vacío; si no está o llega vacío, el nombre del archivo subido, tal como llega. Es lo que se entrega a `rag.index_file` como ruta. Un `path` de solo espacios no está vacío: se valida como cualquier otra ruta.
- **Formato de error**: cuerpo JSON `{"message": ..., "reason": ...}` con un texto en español y un código de motivo.
- **Motivo de API**: código propio de esta capa. Son: `invalid_request`, `invalid_path`, `invalid_extension`, `invalid_encoding`, `payload_too_large`, `length_required`, `not_found`, `method_not_allowed` e `internal_error`. Los motivos de las specs 002 y 003 (`empty_content`, `too_large`, `empty_query`, `missing_api_key`, etc.) se reutilizan sin cambiar su significado.
- **Resultado sin respuesta**: respuesta correcta del chat que no contiene una respuesta del modelo: motivos `empty_index`, `no_relevant`, `insufficient_context` y `ungrounded_answer`. Se devuelve con estado 200.
- **Límite de petición**: tamaño máximo del cuerpo de una petición, comprobado con la cabecera `Content-Length` antes de leerlo. En `POST /upload` es 1.052.672 bytes (los 1.048.576 bytes de 1 MiB que admite un archivo más 4.096 bytes de margen para el formato multipart). En `POST /chat` es 262.144 bytes.
- **Archivo temporal efímero**: archivo que el servidor web puede crear al recibir un archivo grande y que elimina al terminar la petición.

## Requisitos funcionales
- RF-1: `GET /health` responde con estado 200 y el cuerpo `{"status": "ok"}`, sin cargar el modelo, sin exigir clave, sin tocar el índice y sin esperar a los indexados ni a las consultas en curso. MIENTRAS dura el calentamiento del arranque, EL SISTEMA no atiende ninguna petición, `/health` incluida.
- RF-2: CUANDO se envía `POST /upload` con un formulario multipart que contiene el campo `file` y, opcionalmente, el campo `path`, EL SISTEMA valida la petición, decodifica el archivo, lo indexa con la capacidad de la spec 002 y responde con estado 200 y un cuerpo con la ruta de archivo efectiva, el número de fragmentos del archivo, el total del índice, si se troceó por ventanas y el mensaje en español de la spec 002.
- RF-3: EL SISTEMA entrega a la capacidad de indexado exactamente la ruta de archivo efectiva, sin recortarla, normalizarla ni resolverla.
- RF-4: SI la ruta de archivo efectiva está vacía, es solo espacios, supera los 255 caracteres o contiene algún carácter de control (incluidos saltos de línea, tabuladores, el carácter nulo y los separadores de línea o párrafo de Unicode), ENTONCES EL SISTEMA responde 400 con el motivo `invalid_path` y no indexa nada. Un campo `path` enviado vacío no llega a esta comprobación: se sustituye por el nombre del archivo según la definición de ruta de archivo efectiva.
- RF-5: SI la ruta de archivo efectiva no termina en `.py` (sin distinguir mayúsculas), ENTONCES EL SISTEMA responde 400 con el motivo `invalid_extension` y no indexa nada. Esta comprobación se hace después de RF-4.
- RF-6: EL SISTEMA decodifica el archivo como UTF-8, tolerando y descartando una marca de orden de bytes (BOM) inicial; SI no se puede decodificar, ENTONCES responde 400 con el motivo `invalid_encoding` y no indexa nada.
- RF-7: CUANDO la capacidad de indexado rechaza el archivo, EL SISTEMA responde con el formato de error, el mensaje y el motivo de esa capacidad, y este estado: `empty_content` → 400; `too_large` → 413; `too_many_chunks` → 413; `embedding_failed` → 500.
- RF-8: EN todo rechazo, sea de esta capa o de la spec 002, EL SISTEMA deja el índice exactamente como estaba.
- RF-9: EL SISTEMA comprueba una subida en este orden: límite de petición (RF-16 y RF-17), campos obligatorios y formato (422), ruta (RF-4), extensión (RF-5), codificación (RF-6) y, por último, las comprobaciones de la spec 002 (vacío, tamaño, tope de fragmentos y representaciones). Un cuerpo multipart mal formado se rechaza antes de este orden, con 400 (RF-14).
- RF-10: CUANDO se envía `POST /chat` con un cuerpo JSON con `message` y, opcionalmente, `history`, EL SISTEMA obtiene la respuesta de la capacidad de la spec 003 y la devuelve con estado 200 y el contenido completo de la respuesta (`reply`, `citations` y `reason`), tanto si no hay motivo como si el motivo es de un resultado sin respuesta. La clave `reason` siempre está presente en el cuerpo: vale `null` cuando no hay motivo y el código del motivo en cualquier otro caso; no se omite.
- RF-11: CUANDO la capacidad de respuesta devuelve un motivo de fallo, EL SISTEMA responde con el formato de error, usando su `reply` como mensaje y su motivo, y este estado: `empty_query` → 422; `query_too_long` → 422; `missing_api_key` → 503; `invalid_api_key` → 503; `api_unavailable` → 503; `api_timeout` → 504; `api_error` → 502.
- RF-12: SI `history` no se envía, EL SISTEMA lo trata como un historial vacío.
- RF-13: SI el cuerpo de `POST /chat` no es JSON válido, no es un objeto, falta `message`, `message` o `history` tienen un tipo incorrecto, o algún mensaje del historial tiene un rol distinto de `user` y `assistant`, ENTONCES EL SISTEMA responde 422 con el motivo `invalid_request`, sin llamar a la capacidad de respuesta. La misma regla se aplica a `POST /upload` cuando falta el campo `file`.
- RF-14: TODA respuesta con estado 400 o superior que produce la aplicación tiene el formato de error, incluidas las que genera el propio framework dentro de ella: validación (422), cuerpo multipart mal formado (400, motivo `invalid_request`), ruta inexistente (404, motivo `not_found`), método no permitido (405, motivo `method_not_allowed`) y errores internos.
- RF-15: SI ocurre un error no controlado, ENTONCES EL SISTEMA responde 500 con el motivo `internal_error` y un mensaje genérico en español, sin detalles técnicos, y registra solo el tipo del error.
- RF-16: SI `POST /upload` o `POST /chat` llegan sin cabecera `Content-Length`, ENTONCES EL SISTEMA responde 411 con el motivo `length_required`; SI su valor no es un entero no negativo, responde 400 con el motivo `invalid_request`. En ambos casos no lee el cuerpo. Esta comprobación solo se aplica a esas dos rutas: ninguna otra ruta ni método la exige.
- RF-17: SI el `Content-Length` de `POST /upload` o `POST /chat` supera el límite de petición de esa ruta, ENTONCES EL SISTEMA responde 413 con el motivo `payload_too_large` sin leer el cuerpo. Un valor exactamente igual al límite se acepta. El límite solo se aplica a `POST /upload` y `POST /chat`; `GET /upload`, `GET /chat` y las rutas inexistentes siguen su curso normal (405 y 404).
- RF-18: EL SISTEMA no escribe en disco el contenido subido. Única excepción, declarada por esta spec según el principio 5 de la constitución: el servidor web puede crear un archivo temporal efímero cuando un archivo supera 1.048.576 bytes dentro del margen de 4.096 bytes del límite de petición; ese archivo se elimina al terminar la petición, su contenido no se conserva y la petición se resuelve según RF-7.
- RF-19: AL arrancar, EL SISTEMA carga las variables del archivo `.env` del directorio de trabajo, sin sustituir las variables que ya estén definidas en el entorno, y después calienta el modelo de representaciones para que la primera petición no pague su carga.
- RF-20: SI el calentamiento del modelo falla, ENTONCES EL SISTEMA arranca igualmente, registra solo el tipo del error, y la primera petición que necesite el modelo lo intenta de nuevo.
- RF-21: SI no existe archivo `.env`, ENTONCES EL SISTEMA arranca sin error.
- RF-22: MIENTRAS se atienden varias peticiones a la vez (subidas, búsquedas y respuestas), EL SISTEMA mantiene el índice coherente: para cada ruta contiene los fragmentos completos de una sola versión, nunca una mezcla, y ninguna búsqueda falla por un estado intermedio.
- RF-23: EL SISTEMA publica una documentación automática de la API (`/docs` y `/openapi.json`) que describe las tres rutas, sus cuerpos y sus códigos de estado de error, con títulos y descripciones en español, incluida una descripción en español de cada respuesta de error declarada.

## Requisitos no funcionales
- RNF-1: La capa HTTP solo traduce (constitución, principio 3): no trocea, no calcula representaciones, no busca ni arma mensajes para el modelo. Obtiene la capacidad de indexado y la de respuesta mediante dependencias que las pruebas pueden sustituir. Una prueba comprueba que no importa ni usa el troceado de la spec 002 ni la construcción de mensajes de la 003.
- RNF-2: Las rutas que indexan o esperan al modelo se ejecutan fuera del hilo principal del servidor, de modo que `/health` y las demás peticiones no quedan bloqueadas mientras tanto, una vez terminado el calentamiento del arranque (RF-1).
- RNF-3: Los registros de la aplicación no contienen el contenido de los archivos subidos, la ruta de archivo, las preguntas, el historial ni la clave; ante un fallo registran solo el tipo del error (constitución, principio 5). No cubre los registros propios del servidor web, que no están bajo control de esta capa.
- RNF-4: Todos los mensajes al usuario están en español, no contienen detalles técnicos internos ni la clave (constitución, principio 7). Los mensajes propios de esta capa se fijan literalmente en el plan y una prueba compara su texto exacto; que sean comprensibles para alguien que empieza se revisa a mano al cerrar la spec.
- RNF-5: Importar la aplicación no requiere clave, red ni descargar el modelo (constitución, principio 4); el calentamiento solo ocurre al arrancar el servicio, no al importar el módulo. Una vez arrancado, `/health` no depende de la clave, del modelo ni del índice, y el calentamiento no se repite mientras haya funcionado (si falló, RF-20).
- RNF-6: Esta capa no guarda en ningún sitio el contenido subido, las preguntas ni las respuestas; lo único que persiste, en memoria, es el índice de las specs 001 y 002.

## Casos límite
- Archivo de exactamente 1.048.576 bytes de contenido UTF-8 sin BOM: se acepta y se indexa. De 1.048.577 bytes: la spec 002 lo rechaza (413 `too_large`) si llega dentro del límite de petición. El límite se mide sobre el texto ya decodificado y sin el BOM (spec 002), no sobre los bytes crudos: un archivo de 1.048.577 bytes crudos con un BOM inicial de 3 bytes se acepta, porque su texto son 1.048.574 bytes.
- Cuerpo de subida de exactamente 1.052.672 bytes: se acepta para su proceso. De 1.052.673: 413 `payload_too_large` sin leer el cuerpo.
- Cuerpo de chat de exactamente 262.144 bytes: se acepta. De 262.145: 413 `payload_too_large`.
- Petición sin `Content-Length` (por ejemplo, con transferencia por fragmentos): 411 `length_required` en `POST /upload` y `POST /chat`.
- `Content-Length` con un valor no numérico, negativo, decimal o con caracteres no ASCII: 400 `invalid_request`.
- `Content-Length` con más de 15 dígitos: se trata como demasiado grande (413), sin convertirlo a número.
- Ruta de exactamente 255 caracteres: se acepta. De 256: 400 `invalid_path`.
- Ruta con salto de línea, tabulador, carácter nulo o `U+2028`: 400 `invalid_path`.
- Campo `path` presente pero vacío con un archivo de nombre válido: se trata como ausente, la ruta efectiva es el nombre del archivo y se responde 200. `path` de solo espacios: 400 `invalid_path`.
- Campo `path` ausente y archivo llamado `utils.py`: la ruta efectiva es `utils.py`. Con `path` igual a `app/utils.py`: la ruta efectiva es `app/utils.py`.
- Dos archivos `utils.py` con `path` distinto (`a/utils.py`, `b/utils.py`): se indexan por separado; con el mismo `path`: el segundo sustituye al primero (spec 002).
- Ruta `app/Main.PY`: se acepta. `a.txt`, `a.js`, `a.py.txt`, `py` y `a.pyi`: 400 `invalid_extension`. Una ruta llamada exactamente `.py`: se acepta. `"  a.py"` y `"a b.py"` se aceptan y se entregan sin recortar; `"a.py "` no termina en `.py` y da 400 `invalid_extension`.
- Ruta inválida y extensión inválida a la vez (`a\n.txt`): se informa `invalid_path`, por el orden de RF-4 y RF-5.
- Archivo con BOM inicial: se indexa sin el BOM. Archivo con bytes que no son UTF-8 (por ejemplo, Latin-1 con tildes): 400 `invalid_encoding`.
- Archivo vacío o de solo espacios: 400 `empty_content` (spec 002). Archivo con `\r\n` o `\r`: se indexa con la numeración de la spec 002 (cubierto por sus pruebas).
- Archivo que no es Python válido pero termina en `.py`: se acepta y se indexa por ventanas (spec 002; cubierto por sus pruebas).
- Subida sin el campo `file`, o con un `Content-Type` que no es multipart: formulario vacío, 422 `invalid_request`. `Content-Type: multipart/form-data` sin `boundary`: el servidor web rechaza el cuerpo, 400 `invalid_request`.
- `POST /chat` con `history` ausente: se trata como vacío. Con `history` igual a `null`, con un rol `system` o con `content` que no es texto: 422 `invalid_request`.
- `POST /chat` con `message` vacío o de solo espacios: 422 con el motivo `empty_query` (lo decide la búsqueda, no la validación del cuerpo).
- `POST /chat` con `message` de 1.001 caracteres: 422 con el motivo `query_too_long`.
- Resultados sin respuesta (`empty_index`, `no_relevant`, `insufficient_context`, `ungrounded_answer`): estado 200 con `citations` vacías y `reason` con el motivo, nunca `null`.
- Falta de clave con fragmentos relevantes: 503 `missing_api_key`; sin fragmentos relevantes, el motivo y el estado son los de la búsqueda aunque falte la clave (cubierto por la spec 003).
- Tiempo agotado del modelo: 504 `api_timeout`.
- Error no controlado dentro de una ruta: 500 `internal_error`, y el texto del error no aparece en la respuesta ni en los registros de la aplicación.
- `GET /upload` o `GET /chat` sin `Content-Length`: 405 `method_not_allowed`, no 411. Ruta inexistente: 404 `not_found`.
- Dos subidas simultáneas de rutas distintas: ambas quedan indexadas. Dos subidas simultáneas de la misma ruta con versiones distintas, mientras otro hilo busca: la ruta queda con los fragmentos de una sola versión completa, nunca una mezcla, y ninguna búsqueda falla. Una búsqueda durante una subida: devuelve resultados sin error.
- Arranque sin `.env`, sin clave y sin red (con el modelo ya en caché): arranca (cubierto por la spec 003 y por la prueba de importación de RF-19).
- Arranque con el calentamiento fallando: arranca.
- `.env` con una variable que ya existe en el entorno: gana el entorno.
- Servicio arrancado con recarga automática: el índice se vacía en cada recarga (es esperado, spec 002). Se comprueba a mano y se documenta en el README (spec 007); no forma parte de `pytest`.

## Fuera de alcance
- Servir la interfaz web y los archivos de `static/` (spec 005).
- Servidor MCP (spec 006).
- Autenticación, límites de uso por cliente, CORS y HTTPS.
- Subir varios archivos en una misma petición (la interfaz los enviará uno a uno), borrar o listar archivos indexados, y cualquier otra ruta.
- Respuestas progresivas (streaming) y WebSockets.
- Subir archivos que no sean `.py` o que no estén en UTF-8.
- Persistencia del índice, despliegue y empaquetado (spec 007).
- Cambiar el comportamiento de la búsqueda, el indexado o la respuesta.

## Criterios de finalización
- Cada requisito funcional y no funcional tiene una prueba automatizada que pasa sin red, sin claves, sin descargar el modelo y sin llamadas reales al modelo de lenguaje (constitución, principio 4), y `ruff check .` no reporta errores. Quedan como comprobación manual declarada la comprensibilidad de los mensajes, el bloqueo durante el calentamiento y la recarga automática.
- Todos los casos límite anteriores están cubiertos por pruebas, salvo los que remiten a las specs 002 o 003 (cubiertos por sus pruebas) y la recarga automática, que es una comprobación manual documentada.
- Está verificado que cada motivo del indexado y de la respuesta tiene un estado asignado, y que añadir un motivo nuevo sin asignarle estado hace fallar una prueba.
- Está verificado que toda respuesta de error, incluidas las que genera el framework (404, 405, 422 y 500), tiene el formato de error y está en español.
- Está verificado que un `path` vacío se trata como ausente y que `path` de solo espacios se rechaza, y que la ruta efectiva se entrega sin recortar.
- Está verificado que la respuesta 200 de `/chat` incluye siempre `reason`, con `null` cuando la respuesta es fundamentada.
- Está verificado que cada respuesta de error declarada en la documentación automática lleva una descripción en español.
- Está verificado que las peticiones que superan el límite se rechazan sin leer el cuerpo, que las que no llevan `Content-Length` válido se rechazan en `POST /upload` y `POST /chat`, y que `GET /upload` y `GET /chat` sin esa cabecera llegan a 405.
- Está verificado el orden de comprobaciones de `/upload` y que ningún rechazo cambia el índice.
- Está verificado que una subida y una pregunta consecutivas funcionan de principio a fin: se sube un archivo, se pregunta por algo que contiene y la respuesta trae una cita con la ruta, el símbolo y las líneas correctas.
- Está verificado que el calentamiento y la carga de `.env` ocurren al arrancar, que un fallo del calentamiento no impide arrancar y que el entorno prevalece sobre `.env`; que el servidor no atiende peticiones hasta que el calentamiento termina se comprueba a mano al arrancar el servicio y se documenta.
- Está verificado que los registros de la aplicación no contienen contenido, rutas, preguntas, historial ni la clave, ni siquiera ante un error interno.
- Está verificado que el índice se mantiene coherente con operaciones simultáneas, incluida la misma ruta con dos versiones distintas mientras otro hilo busca.
- Está verificado que las rutas que indexan o responden no bloquean el servidor y que importar la aplicación no carga el modelo.
- La spec pasa de borrador a aprobada antes de implementar la primera tarea.

## Dudas abiertas
Ninguna sobre el comportamiento. Estas decisiones de diseño se confirman al aprobar la spec:
- **Estados HTTP.** Los resultados sin respuesta del chat (`empty_index`, `no_relevant`, `insufficient_context`, `ungrounded_answer`) devuelven 200; los fallos de entrada, 422; los fallos del modelo, 502, 503 o 504; y todo error comparte el formato `{message, reason}`.
- **Solo `.py` y UTF-8 estricto.** Un archivo que no es UTF-8 se rechaza en lugar de decodificarlo con sustituciones, porque cambiaría el texto que luego se cita.
- **Campo `path` opcional.** Permite distinguir archivos con el mismo nombre en carpetas distintas; sin él, se usa el nombre del archivo. Un `path` vacío se trata como ausente porque es lo que envía un formulario HTML con el campo opcional en blanco (spec 005); un `path` de solo espacios sigue siendo inválido.
- **`reason` en la respuesta HTTP de `/chat`.** La spec 003 (RF-19) describe `reason` como ausente cuando la respuesta es fundamentada, a nivel de la capacidad. Esta spec fija la serialización HTTP: el cuerpo incluye siempre la clave y vale `null` en ese caso, sin `response_model_exclude_none`. La 003 no cambia.
- **Límite de tamaño medido sobre el texto decodificado.** El BOM se descarta antes de indexar (RF-6) y la spec 002 ya mide el tamaño sobre el texto en UTF-8. Medirlo sobre bytes crudos en `main.py` duplicaría esa regla y podría discrepar; además, contar antes de decodificar exigiría leer el cuerpo fuera de la capacidad de indexado. Consecuencia asumida: un archivo con BOM puede tener hasta 3 bytes crudos más y seguir aceptándose.
- **Excepción acotada al principio 5** (RF-18): un archivo temporal efímero en un rango muy estrecho de tamaños. La alternativa, recibir el contenido como JSON, evita el archivo temporal pero rompe el formato habitual de subida (`curl -F`, `UploadFile`).
- **Dependencia nueva `python-dotenv`** para cargar `.env` (principio 1). La alternativa es que quien opera exporte la variable a mano y no cargar `.env`.
- **Bloqueo interno en el almacén** (spec 002, `storage.py`) para atender peticiones simultáneas, sin cambiar su comportamiento ni sus firmas.