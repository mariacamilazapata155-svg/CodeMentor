# Spec 005 - Interfaz web

Estado: implementada


## Contexto y objetivo
Las specs 001 a 004 dejan el sistema usable solo desde código o desde un cliente HTTP: se puede indexar un archivo `.py`, preguntar y recibir una respuesta con citas, pero no hay forma de hacerlo en el navegador.

Esta spec define la interfaz web que se sirve desde la propia aplicación: abrir la página en `/`, subir un archivo `.py` con una ruta opcional, conversar con el asistente y ver las citas de archivo, símbolo y líneas. También fija los estados que la persona ve (carga, éxito, error, resultado sin respuesta y «sin código indexado»), el comportamiento en móvil y las garantías de accesibilidad y seguridad.

La interfaz es solo una capa de presentación: consume las rutas `/upload` y `/chat` ya existentes, sin cambiar su contrato. Aplica solo validaciones locales preventivas y mínimas; el servidor sigue siendo la autoridad sobre todas las reglas. No define el servidor MCP, no persiste el índice y no añade autenticación. El detalle de cómo se sirven la página y sus recursos corresponde al plan.

## Usuarios
- Quien tiene código Python y quiere consultarlo sin usar `curl` ni escribir código.
- Quien ya indexó archivos y quiere preguntar por ellos y comprobar las citas.
- Quien opera CodeMentor, que arranca el servicio y entrega la dirección a otras personas.
- Quien revisa la calidad (QA), que valida los requisitos de interfaz con las herramientas del navegador.

## Historias de usuario
- HU-1. Como persona que entrega código, quiero subir un archivo `.py` desde el navegador y ver cuántos fragmentos se indexaron y cuántos hay en total, para saber que mi archivo ya se puede consultar.
- HU-2. Como persona que consulta código, quiero escribir una pregunta y leer la respuesta con sus citas, para localizar la lógica sin abrir el editor.
- HU-3. Como persona que conversa, quiero hacer preguntas de seguimiento y que el asistente recuerde el intercambio anterior, para no repetir contexto en cada pregunta.
- HU-4. Como persona que usa la interfaz, quiero distinguir con claridad cuándo el sistema está trabajando, cuándo falló, cuándo no hay código indexado y cuándo no encontró fundamento, para saber qué hacer a continuación.
- HU-5. Como persona que revisa una respuesta, quiero ver el archivo, el símbolo y las líneas de cada cita y relacionarlas con las marcas de la respuesta, para verificar la afirmación.
- HU-6. Como persona que usa el móvil, quiero subir archivos y preguntar en una pantalla de 375 px sin desplazamientos laterales ni controles cortados, para usarlo con una mano.
- HU-7. Como persona que navega con teclado o lector de pantalla, quiero etiquetas, foco visible, avisos anunciados y un orden de tabulación lógico, para completar el flujo sin ratón ni vista.
- HU-8. Como persona que entrega código ajeno, quiero que el contenido del código y de las respuestas se muestre como texto y no se ejecute ni se guarde en el navegador, para no exponerme a código malicioso.
- HU-9. Como operador, quiero que la interfaz se sirva con el mismo arranque que la API y sin pasos de compilación, para no añadir infraestructura ni dependencias.

## Definiciones
- **Interfaz**: la página web y su comportamiento en el navegador. No incluye la API ni la lógica de búsqueda o de respuesta.
- **Conversación**: la secuencia de mensajes que se muestran en la página desde que se abre hasta que se recarga o se cierra. Vive solo en la página.
- **Turno**: una pregunta de la persona y el mensaje que el sistema muestra como consecuencia.
- **Pregunta**: el texto que la persona escribe para consultar el código. Es el valor que se envía en `message`.
- **Ruta efectiva**: el valor del campo de ruta si contiene al menos un carácter, sin recortar ni normalizar; en caso contrario, el nombre del archivo elegido. Es la ruta cuya extensión comprueba la interfaz y la que la API usa para indexar.
- **Punto de código Unicode**: un carácter Unicode individual; no se cuenta por bytes ni por unidades UTF-16. Un emoji fuera del plano básico cuenta como uno, aunque ocupe dos unidades UTF-16.
- **Intercambio fundamentado**: una pregunta y una respuesta del asistente con estado 200, `reason` nulo y al menos una cita. Es la única unidad que forma parte del historial.
- **Historial**: los intercambios fundamentados anteriores de la conversación actual, en orden cronológico, que se envían en `history` junto con la pregunta nueva.
- **Respuesta fundamentada**: resultado de `/chat` con estado 200 y `reason` nulo; incluye `reply` y una lista de citas.
- **Resultado sin respuesta**: resultado de `/chat` con estado 200 y `reason` distinto de nulo (`empty_index`, `no_relevant`, `insufficient_context` o `ungrounded_answer`); incluye un `reply` en español y ninguna cita.
- **Aviso**: mensaje informativo de la interfaz que no es ni pregunta ni respuesta (por ejemplo, un error de validación local o un fallo de red).
- **Aviso de subida**: mensaje de éxito, error o fallo de red que se muestra en la zona del formulario de subida, no en la conversación, y que se sustituye con la siguiente subida.
- **Error de la aplicación**: respuesta de `/upload` o `/chat` con estado 400 o superior y un cuerpo con `message` y `reason`. La interfaz muestra `message`, no `reason`.
- **Cita**: referencia a un fragmento real del código, con número, ruta, símbolo y rango de líneas.
- **Marca de cita**: la etiqueta `[Fn]` que aparece dentro de `reply` y cuyo número corresponde a una cita.
- **Estado de carga**: indicación visible de que hay una operación en curso.
- **Texto no confiable**: todo lo que proviene del archivo subido, de la API o del modelo (respuesta, citas, mensajes, ruta y nombre del archivo). Puede contener HTML o scripts y nunca se interpreta.

## Requisitos funcionales

### Acceso y estado inicial
- RF-1: CUANDO se solicita la raíz `/` con GET, EL SISTEMA responde con estado 200 y la página de la interfaz en español, con el idioma declarado como español, un título visible y todos sus recursos cargados correctamente, incluido el icono de la página; la interfaz se sirve con el mismo comando de arranque que la API y sin compilación, instalación de herramientas de frontend ni paso previo adicional.
- RF-2: CUANDO la página termina de cargar, EL SISTEMA no inicia ninguna petición a `/upload` ni a `/chat`, ni consulta el estado del índice; las únicas peticiones que provoca son las de sus propios recursos. El icono se sirve como recurso propio de la página, y la petición automática que el navegador hace para pedirlo no cuenta como iniciativa de la interfaz, que no la provoca; el icono no produce un 404 propio.
- RF-3: CUANDO se abre la página sin conversación, EL SISTEMA muestra un estado vacío con un texto en español que invita a subir un archivo `.py` y a escribir una pregunta, sin afirmar que el índice esté vacío y sin mostrar citas.
- RF-4: SI el navegador no ejecuta JavaScript, ENTONCES EL SISTEMA muestra un texto en español que indica que la interfaz necesita JavaScript para funcionar; ese texto es visible sin depender de scripts.

### Subida de archivos
- RF-5: EL SISTEMA ofrece un formulario de subida con un campo de archivo obligatorio, un campo de ruta opcional y un botón de envío, cada uno con una etiqueta visible en español redactada por la interfaz; el formulario acepta un único archivo por envío y no permite seleccionar varios. Los textos nativos del control de archivo y los avisos nativos de validación del navegador quedan fuera del control de la interfaz: la obligatoriedad y los avisos propios se gestionan en la página, sin depender de ellos.
- RF-6: SI se intenta subir sin haber elegido un archivo, ENTONCES EL SISTEMA muestra un aviso en español, deja el formulario utilizable y no envía ninguna petición.
- RF-7: SI la ruta efectiva (el campo de ruta si contiene al menos un carácter, sin recortar; en caso contrario, el nombre del archivo elegido) no termina en `.py` sin distinguir mayúsculas y no está formada solo por espacios en blanco, ENTONCES EL SISTEMA muestra un aviso en español que indica que solo se aceptan archivos `.py`, deja el formulario utilizable y no envía ninguna petición. Una ruta efectiva de solo espacios en blanco no se bloquea por extensión: se envía y la API informa `invalid_path`. La interfaz no comprueba el tamaño, la codificación ni el resto de reglas de la ruta: esas reglas las aplica la API y sus mensajes se muestran tal cual.
- RF-8: CUANDO se envía un archivo válido, EL SISTEMA envía `POST /upload` como formulario multipart con el archivo en `file` y, solo si el campo de ruta contiene al menos un carácter, ese texto en `path`, sin recortarlo ni normalizarlo; si el campo está vacío, omite `path`.
- RF-9: MIENTRAS una subida está en curso, EL SISTEMA muestra un estado de carga con texto en español, deshabilita el botón de subida e impide iniciar otra subida; el formulario de pregunta sigue utilizable.
- RF-10: CUANDO `/upload` responde 200, EL SISTEMA muestra en la zona del formulario de subida el mensaje recibido y, además, la ruta efectiva, los fragmentos indexados de ese archivo y el total del índice, vacía los campos de archivo y de ruta, mantiene el resultado visible hasta la siguiente subida, vuelve a habilitar el formulario y no muestra `used_windows` por separado, porque el mensaje de la API ya indica cuándo se troceó por ventanas.
- RF-11: SI `/upload` responde con estado 400 o superior y un cuerpo con `message`, ENTONCES EL SISTEMA muestra ese mensaje tal cual en la zona del formulario de subida (no en la conversación), sustituyendo el aviso anterior, señala el aviso como error de forma perceptible por texto y no solo por color, conserva el archivo y la ruta elegidos, vuelve a habilitar el formulario y no muestra datos de éxito.
- RF-12: SI la subida no obtiene respuesta por un fallo de red, o su respuesta —tanto de éxito como de error— no se puede leer como un cuerpo con `message` y la forma esperada, ENTONCES EL SISTEMA muestra en la zona del formulario de subida un aviso genérico en español que indica que no se pudo completar la subida y que se puede reintentar, sin detalles técnicos, y deja el formulario utilizable.
- RF-13: EL SISTEMA permite subir archivos uno detrás de otro; CUANDO termina una subida, el resultado visible corresponde solo a la última y el total mostrado es el que devuelve la API.

### Conversación
- RF-14: EL SISTEMA ofrece un campo de pregunta con etiqueta visible y un botón de envío; la pregunta admite varias líneas y se envía al pulsar Enter, mientras que Shift+Enter inserta un salto de línea dentro de la pregunta.
- RF-15: SI la pregunta está vacía o solo contiene espacios, ENTONCES EL SISTEMA muestra un aviso en español que pide escribir una pregunta y no envía ninguna petición.
- RF-16: SI la pregunta tiene más de 1.000 puntos de código Unicode, ENTONCES EL SISTEMA muestra un aviso en español con ese límite y no envía ninguna petición; una pregunta de exactamente 1.000 puntos de código se envía.
- RF-17: CUANDO se envía una pregunta válida, EL SISTEMA la añade a la conversación como mensaje de la persona, vacía el campo, muestra un estado de carga con texto en español y envía una única petición `POST /chat` con un cuerpo JSON que contiene la pregunta en `message` y el historial en `history`, siempre presente y como `[]` cuando está vacío (nunca se omite); MIENTRAS esa petición no termina, EL SISTEMA no inicia otra y el campo de pregunta sigue editable, aunque el botón de envío queda deshabilitado.
- RF-18: EL SISTEMA construye `history` con los intercambios fundamentados anteriores de la conversación, en orden cronológico, siempre por pares completos (la pregunta y su respuesta juntas) y sin incluir la pregunta actual; incluye como máximo los 10 mensajes más recientes y recorta cada contenido a 4.000 puntos de código Unicode, sin partir un par sustituto. Estos topes y el de 200.000 bytes del cuerpo serializado son una precaución de transporte, no una regla de negocio: el servidor sigue siendo la autoridad sobre el historial, y el margen deja 62.144 bytes bajo el límite de 262.144 de `/chat` para el resto del cuerpo JSON. SI el cuerpo supera 200.000 bytes, ENTONCES EL SISTEMA descarta los intercambios más antiguos, completos, hasta que quepa.
- RF-19: CUANDO `/chat` responde 200 con `reason` nulo, EL SISTEMA muestra `reply` como mensaje del asistente, conservando los saltos de línea y las marcas `[Fn]` tal como llegan, y muestra a continuación la lista de citas ordenada de forma ascendente por `number` como orden de presentación.
- RF-20: CADA cita muestra su número con el formato `[Fn]`, la ruta del archivo, el nombre del símbolo y las líneas en el formato «líneas X–Y», o «línea X» cuando el inicio y el fin coinciden; todos los valores se muestran completos, sin recortar con puntos suspensivos.
- RF-21: CUANDO `reply` contiene marcas `[Fn]`, EL SISTEMA mantiene cada marca en su posición y cada cita con su mismo número; SI llega una marca sin cita o una cita sin marca, ENTONCES EL SISTEMA muestra lo recibido sin inventar, renumerar ni eliminar citas ni marcas.
- RF-22: CUANDO `/chat` responde 200 con `reason` igual a `empty_index`, EL SISTEMA muestra un estado propio identificable por texto como «sin código indexado», con una acción visible en español que lleva al formulario de subida de un archivo `.py`, sin lista de citas y sin añadirlo al historial. CUANDO el motivo es `no_relevant`, `insufficient_context` o `ungrounded_answer`, EL SISTEMA muestra `reply` como aviso del sistema, sin lista de citas, sin añadirlo al historial y con la conversación y el campo de pregunta utilizables.
- RF-23: SI `/chat` responde con estado 400 o superior y un cuerpo con `message`, ENTONCES EL SISTEMA muestra ese mensaje como error, sin citas y sin añadirlo al historial, y vuelve a habilitar el envío.
- RF-24: SI la petición de chat no obtiene respuesta por un fallo de red o el cuerpo no se puede leer como JSON con la forma esperada, ENTONCES EL SISTEMA muestra un aviso genérico en español que indica que no se pudo obtener la respuesta y que se puede reintentar, sin detalles técnicos, sin citas y sin añadirlo al historial.
- RF-25: CUANDO termina una petición de chat, con éxito o con error, EL SISTEMA retira el estado de carga y vuelve a habilitar el botón de envío; el campo de pregunta nunca se deshabilita. No mueve el foco de forma automática ni lo atrapa en ningún elemento.
- RF-26: EL SISTEMA conserva visible durante toda la sesión de la página la conversación completa, en orden, con los mensajes de la persona, los del asistente, los estados de resultado sin respuesta y los errores de chat intercalados; cada mensaje nuevo se añade al final. Los avisos de subida no forman parte de la conversación: viven en la zona del formulario de subida y se sustituyen con la siguiente subida.
- RF-27: EL SISTEMA no resume, reescribe, corrige ni completa las respuestas, las citas ni los mensajes de la API, y muestra su contenido exactamente como lo recibe. Ordenar las citas por `number` para presentarlas, aplicar el formato de líneas de RF-20 o convertirlas en lista son decisiones de presentación que no alteran su contenido, sus números ni el texto de `reply`.

### Seguridad y datos
- RF-28: TODOS los textos no confiables se muestran como texto literal, nunca como marcado HTML; SI contienen etiquetas o scripts, ENTONCES se ven tal cual, no se interpretan y no se ejecutan.
- RF-29: EL SISTEMA no inspecciona, ejecuta ni evalúa el contenido del archivo en el navegador: lo envía sin procesarlo como parte del formulario. La única comprobación local relacionada con el archivo valida la extensión de la ruta efectiva, según RF-7.
- RF-30: EL SISTEMA no guarda datos en el navegador: no usa cookies, almacenamiento local, almacenamiento de sesión, bases de datos del navegador, service workers, Cache API ni ninguna otra forma de almacenamiento o caché propia de la conversación. Todo el estado vive solo en memoria mientras la página está abierta; CUANDO se recarga o se cierra, la conversación y el aviso de la última subida desaparecen.
- RF-31: EL SISTEMA no carga recursos ni envía datos a dominios de terceros; todas las peticiones de la página son al mismo origen que la interfaz.
- RF-32: EL SISTEMA no registra errores propios: no lanza excepciones de JavaScript en los flujos previstos, no imprime mensajes de la aplicación ni el contenido de los archivos, las preguntas, las respuestas o las rutas, y ninguno de sus recursos propios (incluido el icono) responde 404. Los avisos automáticos que el navegador añade a la consola por respuestas 4xx o 5xx, fallos de red o recursos de terceros no cuentan como errores propios y quedan fuera de este requisito.
- RF-33: MIENTRAS hay una subida o una pregunta en curso, EL SISTEMA mantiene la página utilizable: se puede escribir, desplazarse y usar el otro formulario, y la interfaz no se bloquea.

### Tiempo de espera
- RF-34: EL SISTEMA limita a 75 segundos la espera de las peticiones que inicia, incluidas las de subida: el servidor puede tardar hasta 60 segundos en el peor caso del chat (30 segundos por intento × 2 intentos por el reintento automático de la spec 003) y se añaden 15 segundos de margen para la red y el procesamiento. SI se agota ese tiempo, ENTONCES aborta la petición y muestra un aviso en español que indica que no se recibió respuesta a tiempo: en la zona del formulario de subida si era una subida y como error en la conversación si era una pregunta, sin citas y sin añadir nada al historial. El aborto por tiempo de espera no es la cancelación manual que figura fuera de alcance, y no garantiza que el servidor deje de procesar la subida ni cambia el resultado que el servidor registre.

## Requisitos no funcionales
- RNF-1: La interfaz usa solo las capacidades del navegador, sin frameworks, bibliotecas de interfaz, gestores de paquetes de frontend, compilación ni dependencias nuevas (constitución, principio 1). Se sirve con el mismo arranque que la API.
- RNF-2: La interfaz solo presenta (constitución, principio 3): no trocea, no calcula representaciones, no busca, no redacta ni decide motivos; se limita a llamar a `/upload` y `/chat` y a mostrar lo recibido. Sus validaciones locales (RF-6, RF-7, RF-15 y RF-16) son preventivas y mínimas, y el servidor sigue siendo la autoridad sobre todas las reglas. El formato de presentación (orden ascendente de citas, «líneas X–Y») no altera el contenido, los números ni los textos que devuelve la API; los topes del historial son una precaución de transporte, según RF-18.
- RNF-3: La interfaz cumple estos criterios de accesibilidad, verificables con la herramienta de accesibilidad, la inspección del DOM, el zoom y el redimensionado, y la navegación por teclado:
  - 1.4.3 Contraste (mínimo): el texto normal alcanza 4,5:1 y el texto grande (18 pt o 14 pt en negrita) alcanza 3:1, medido con el comprobador de contraste de DevTools.
  - 1.4.4 Cambio de tamaño del texto: al ampliar el texto al 200 % no se pierde contenido ni funcionalidad.
  - 1.4.10 Reflujo: a 320 px de ancho (equivalente a 400 % sobre 1280 px) no aparece desplazamiento horizontal y todo el contenido sigue disponible en una columna.
  - 1.4.11 Contraste de elementos no textuales: bordes de campos, indicadores de foco y controles alcanzan 3:1 frente a su entorno.
  - 2.4.3 Orden del foco: el orden de tabulación sigue el orden visual y lógico.
  - 2.4.7 Foco visible: todo elemento enfocable muestra un contorno de al menos 2 px y contraste de 3:1.
  - 3.3.1 Identificación de errores: cada error se identifica con texto en español y se asocia al control o a la zona que lo provoca.
  - 3.3.2 Etiquetas o instrucciones: todo control tiene una etiqueta visible y asociada.
  - 4.1.2 Nombre, función y valor: cada control expone nombre accesible, rol y estado en el árbol de accesibilidad.
  - 4.1.3 Mensajes de estado: los estados de carga, éxito, error y resultado sin respuesta se anuncian mediante una región activa.
  Además, el flujo completo se completa con teclado (2.1.1) y no hay trampas de foco (2.1.2); la página tiene un solo encabezado principal y ningún salto de nivel en la jerarquía de encabezados (de h1 se pasa a h2, nunca a h3), con regiones de cabecera y contenido principal.
- RNF-4: La interfaz se adapta a 375×667 y a 1280×800 sin desplazamiento horizontal de la página y sin contenido cortado, superpuesto ni fuera de la pantalla; a 375 px el contenido se organiza en una sola columna, los textos largos se ajustan con saltos de línea y los controles táctiles miden al menos 44×44 px CSS, un requisito adicional del proyecto y no un criterio de WCAG AA.
- RNF-5: Todos los textos propios de la interfaz (títulos, etiquetas, ayudas, botones, avisos y mensajes propios) están en español (constitución, principio 7), con lenguaje claro para alguien que empieza, y no incluyen detalles técnicos internos, JSON sin tratar, trazas ni el código del motivo. Los textos nativos del navegador (por ejemplo, el botón del selector de archivo o sus avisos de validación) dependen de su idioma y quedan fuera del control de la interfaz: no se consideran textos propios ni se usan como mensajes de la aplicación. La comprensibilidad de los textos propios se revisa a mano al cerrar la spec.
- RNF-6: La interfaz no persiste ni registra datos de la persona (constitución, principio 5): no guarda contenido, preguntas, respuestas ni rutas en el navegador ni en registros propios, y no envía nada fuera del origen. La única información que conserva es la conversación en memoria mientras la página está abierta.
- RNF-7: El estado de carga aparece en la misma interacción que inicia la petición, antes de recibir la respuesta, y no bloquea la página: el campo de pregunta nunca se deshabilita y la interfaz sigue respondiendo a la escritura y al desplazamiento mientras espera; solo el botón de envío correspondiente queda deshabilitado.
- RNF-8: La validación obligatoria se hace en Chrome de escritorio y con emulación de 375 px, que son el mínimo exigible. Las dos últimas versiones de Firefox, Edge y Safari y los dispositivos reales son una comprobación manual no bloqueante; el plan decide si se documenta su resultado.
- RNF-9: La interfaz se sirve desde el mismo origen que la API y no requiere cambios en el contrato de `/upload` ni de `/chat`, ni en CORS, ni en el comportamiento del servidor descrito en la spec 004.
- RNF-10: La presentación usa el sistema de diseño ya existente: solo variables CSS para color, espacio, tipografía, radios y sombras (nada de colores, espaciados, tamaños ni sombras literales fuera de las variables), clases con nomenclatura BEM y ningún estilo en línea. La verificación se hace por inspección del CSS y del marcado generado.

## Casos límite
- Abrir `/`: la página carga y solo se piden sus recursos propios, incluido el icono; no hay peticiones a `/upload` ni a `/chat`.
- Abrir `/` sin clave configurada: la página carga igualmente; solo fallaría una pregunta que necesite el modelo, y entonces se muestra el mensaje 503 de la API.
- Abrir la página con el índice vacío: no se afirma nada sobre el índice; la primera pregunta devuelve 200 con `empty_index`, se muestra el estado propio «sin código indexado» con la acción de subir un `.py` y no hay citas.
- Servicio detenido o sin red al enviar: aviso genérico en español, sin citas y con el formulario utilizable.
- Subida sin archivo: aviso local y ninguna petición.
- Archivo `code.txt` sin ruta: la ruta efectiva es `code.txt`, se bloquea en cliente con el aviso de extensión y no se envía.
- Archivo `.txt` con `path="app/code.py"`: la ruta efectiva es `app/code.py`, se envía y la API lo acepta.
- Archivo `.py` con `path="app/code.txt"`: la ruta efectiva es `app/code.txt`, se bloquea en cliente con el aviso de extensión y no se envía.
- Archivo `.PY` con ruta vacía: la ruta efectiva es el nombre, se acepta en cliente, se envía y la API lo acepta.
- Archivo sin extensión: se bloquea en cliente porque su ruta efectiva no termina en `.py`.
- Archivo de nombre exactamente `.py`: se envía y la API decide.
- Archivo de más de 1 MiB: no se bloquea en el cliente; la API responde 413 y se muestra su mensaje.
- Archivo de 1.048.577 bytes con BOM inicial: la API lo acepta; la interfaz no lo rechaza por tamaño.
- Archivo que no es UTF-8: la API responde 400 `invalid_encoding` y se muestra su mensaje.
- Archivo vacío o de solo espacios: la API responde 400 `empty_content` y se muestra su mensaje.
- Archivo con demasiados fragmentos: la API responde 413 `too_many_chunks` y se muestra su mensaje.
- Fallo al preparar las representaciones: la API responde 500 `embedding_failed` y se muestra su mensaje.
- Error interno al subir: la API responde 500 `internal_error` con su mensaje genérico y se muestra ese texto, sin datos de éxito.
- Archivo que no es Python válido pero termina en `.py`: se envía; la API lo indexa por ventanas y su mensaje lo indica.
- Ruta opcional vacía: se omite el campo y se indexa con el nombre del archivo.
- Ruta de solo espacios en blanco: se envía tal cual y se muestra el mensaje 400 `invalid_path` de la API (RF-7 no la bloquea por extensión).
- Ruta de más de 255 caracteres que termina en `.py`: se envía y la API responde 400 `invalid_path`.
- Ruta con etiquetas HTML o comillas: se envía como texto; si aparece en una cita, se ve literal y no se interpreta.
- Nombre de archivo con etiquetas HTML: la interfaz no lo interpreta, lo valida por su extensión y lo muestra literal donde aparezca; si el sistema de archivos impide crear ese nombre, la misma comprobación se hace con el campo de ruta.
- Dos subidas seguidas del mismo archivo con rutas distintas: cada una sustituye el aviso de subida anterior y el total mostrado es el de la API.
- Subida en curso y pregunta simultánea: ambas se pueden iniciar y cada una muestra su propio estado de carga.
- Doble clic en el botón de subida o de envío: solo se envía una petición.
- Pregunta vacía, de solo espacios o de 1.001 puntos de código: aviso local y ninguna petición; de 1.000 puntos de código: se envía.
- Pregunta con caracteres fuera del plano básico (por ejemplo, emojis): el límite se cuenta por puntos de código Unicode, no por bytes ni por unidades UTF-16.
- Pregunta con varias líneas: se envía con los saltos de línea tal como se escribieron.
- Enter mientras se compone texto con un método de entrada (IME): no envía la pregunta; solo envía al confirmar la composición.
- Respuesta fundamentada con una sola cita: se muestra `[F1]` y una única entrada de cita.
- Cita con el mismo inicio y fin de línea: se muestra «línea X».
- Cita con ruta o símbolo muy largos: se ajusta en varias líneas y se ve completa a 375 px.
- Citas que llegan con números fuera de orden (3, 1, 2): se presentan ordenadas 1, 2, 3, sin cambiar sus números, sus datos ni el texto de `reply`.
- Respuesta con `reason` nulo pero sin citas: se muestra el texto, no se inventan citas y no se añade al historial (no es un intercambio fundamentado).
- Marca `[Fn]` sin cita o cita sin marca: se muestran los datos recibidos sin corregirlos.
- `no_relevant`, `insufficient_context` o `ungrounded_answer`: aviso sin citas, sin añadirse al historial.
- Error 400, 413, 422, 502, 503 o 504 del chat: se muestra el `message` de la API, sin citas y sin historial.
- Respuesta 200 de chat o de subida con un cuerpo que no se puede leer: aviso genérico, sin citas y sin datos de éxito.
- Texto de respuesta o de cita con `<script>alert(1)</script>` o `<img onerror=...>`: se ve literal, no se ejecuta y no aparece ningún diálogo.
- Recargar la página: se pierde la conversación y el último aviso de subida; el índice sigue en el servidor.
- Conversación de más de 10 mensajes: se envían solo los 10 más recientes, por pares completos, y la conversación visible no se recorta.
- Respuesta del asistente de exactamente 4.000 puntos de código: se envía completa en el historial; de 4.001: se recorta a 4.000 sin partir un par sustituto, y en la página se sigue viendo completa.
- Cuerpo de chat serializado de exactamente 200.000 bytes: se envía; de 200.001: se descartan intercambios antiguos completos hasta que quepa.
- Petición de subida o de chat sin respuesta durante 75 segundos: se aborta y se muestra el aviso «no se recibió respuesta a tiempo»; en el chat, además, sin citas y sin historial.
- Navegador sin JavaScript: se muestra el texto que lo indica.
- Navegador con la consola abierta durante todo el flujo: no hay errores propios ni contenido impreso; los avisos automáticos por respuestas 4xx o 5xx, fallos de red o recursos de terceros no cuentan.

## Fuera de alcance
- Servir la interfaz mediante un servidor o un proceso distinto del de la API, o con un paso de compilación.
- Persistencia del índice, de la conversación o de archivos subidos; guardar el historial en el navegador.
- Autenticación, cuentas, límites de uso por persona, HTTPS y CORS.
- Subir varios archivos en una petición, arrastrar y soltar, listar, borrar o reindexar archivos, y cualquier selector de archivos ya indexados.
- Respuestas progresivas (streaming), WebSockets, cancelar una petición en curso y reintento automático.
- Mostrar el contenido de los fragmentos, resaltar la sintaxis, renderizar Markdown, enlaces o HTML de la respuesta.
- Editar, regenerar o valorar respuestas, copiar citas y navegar al archivo o a la línea.
- Tema oscuro, selector de idioma, internacionalización, atajos de teclado adicionales y animaciones.
- Servidor MCP (spec 006), publicación, README, capturas, CI y despliegue (spec 007).
- Cambiar el comportamiento de la búsqueda, el indexado o la respuesta, o el contrato de las rutas de la spec 004.

## Criterios de finalización
- Cada requisito funcional y no funcional tiene una comprobación registrada. Lo que se pueda automatizar sin dependencias nuevas (validación de la extensión por ruta efectiva, pregunta vacía y límite de 1.000 puntos de código, construcción del historial con sus topes, y orden y formato de citas si el plan aísla esas reglas como funciones puras) se cubre con pruebas automatizadas; lo que depende del navegador (red, consola, viewport, teclado, contraste, almacenamiento y accesibilidad) se verifica a mano con el MCP de Chrome DevTools. Cada caso límite tiene su comprobación registrada, sea automatizada o manual.
- Se verifica el flujo completo con el servicio arrancado y una clave válida: abrir `/`, subir un archivo `.py` del proyecto que contenga la función que calcula las representaciones, preguntar «¿Dónde se calculan los embeddings?» y comprobar que la respuesta muestra `[Fn]` y una cita con la ruta, el símbolo y las líneas correctas. Si no hay clave disponible, se deja constancia expresa de la parte pendiente, como en la spec 004.
- Se verifica la prueba negativa: preguntar por algo que no está en el código devuelve un resultado sin respuesta, sin citas y con un aviso claro.
- Se verifica el estado sin índice tras reiniciar el servicio: la pregunta devuelve `empty_index`, la interfaz muestra el estado propio «sin código indexado» con la acción de subir y no muestra citas.
- Se verifica que una ruta con etiquetas HTML (y un nombre de archivo con etiquetas, si el sistema de archivos lo permite) se muestra literal en las citas, sin ejecutar scripts y sin diálogos.
- Se verifica que no hay peticiones a dominios de terceros, que ningún recurso propio da 404 y que no hay errores propios en la consola durante los flujos de subida, pregunta, resultado sin respuesta y error; los avisos automáticos del navegador por respuestas HTTP, red o recursos de terceros quedan excluidos.
- Se verifica a 375×667 y a 320 px de ancho que no hay desplazamiento horizontal (`scrollWidth` igual a `clientWidth`), que no hay contenido cortado ni superpuesto y que los controles táctiles alcanzan 44×44 px a 375 px.
- Se completa el flujo entero solo con teclado: elegir archivo, escribir la ruta, subir, escribir la pregunta y enviarla, con el foco siempre visible y sin trampas. Las citas no son interactivas ni enfocables: se leen con el lector de pantalla o se llega a ellas desplazándose.
- Se comprueban los criterios de RNF-3 con la herramienta de accesibilidad, el comprobador de contraste de DevTools, el zoom y el redimensionado, y la navegación por teclado: contraste, texto al 200 % (1.4.4), reflujo, contraste de elementos no textuales (1.4.11), orden del foco (2.4.3), foco visible, etiquetas, nombres accesibles, identificación de errores (3.3.1) y anuncios de estado.
- Se comprueba que no se guarda nada en el navegador: sin cookies, almacenamiento local, de sesión, IndexedDB, service workers ni Cache API, y que al recargar desaparecen la conversación y el aviso de subida.
- Se comprueba que recargar la página, apagar el servidor y volver a encenderlo no rompe la interfaz y que los mensajes de error son comprensibles; la revisión de comprensión se hace a mano.
- `ruff check .` no reporta errores y `pytest -q` sigue en verde, sin dependencias nuevas y sin cambios en el contrato de `/upload` o `/chat`.
- La spec pasa de borrador a aprobada antes de implementar la primera tarea.

## Dudas abiertas
Ninguna que bloquee la redacción. Estas decisiones de diseño se confirman al aprobar la spec:
- **Sin persistencia en el navegador** (RF-30): recargar pierde la conversación y el último aviso de subida. La alternativa, guardar la conversación en el almacenamiento local, conservaría preguntas y respuestas de código en el equipo y choca con el principio 5.
- **Validación local mínima sobre la ruta efectiva** (RF-7): solo se comprueban el archivo presente, la extensión de la ruta efectiva y la pregunta vacía o demasiado larga. El tamaño, la codificación y el resto de reglas de la ruta se dejan a la API para no rechazar en cliente un archivo que la API aceptaría (por ejemplo, uno de 1.048.577 bytes con BOM).
- **Historial solo con intercambios fundamentados** (RF-18): las preguntas con resultado sin respuesta, los errores y los avisos locales no se envían como contexto. La alternativa, enviar todo lo mostrado, metería mensajes de error en el contexto del modelo.
- **Un archivo por envío y sin arrastrar y soltar**: el resultado visible es solo el de la última subida y no hay lista de archivos porque la API no la ofrece.
- **Respuestas como texto plano** (RF-19, RF-27): se conservan los saltos de línea y las marcas, sin Markdown ni resaltado. La alternativa, interpretar el texto como Markdown o HTML, abriría la puerta a inyección y exigiría una dependencia.
- **Orden ascendente de citas** (RF-19, RF-27): es un orden de presentación y no cambia sus números, sus datos ni el texto de `reply`. La alternativa, respetar el orden de llegada, dificultaría seguir las marcas en una respuesta.
- **Margen de 200.000 bytes para el cuerpo del chat** (RF-18): los topes de 10 mensajes y 4.000 puntos de código no garantizan por sí solos caber en los 262.144 bytes de `/chat`, así que se reservan 62.144 bytes para el resto del cuerpo JSON. La alternativa, enviar sin margen, expondría a un 413 en conversaciones largas.
- **Campo de pregunta siempre editable** (RF-17, RF-25, RNF-7): solo se deshabilita el botón de envío mientras hay una petición en vuelo. La alternativa, deshabilitar el campo, impedía escribir la siguiente pregunta y contradecía RF-33.
- **Avisos de subida en la zona del formulario** (RF-10, RF-11, RF-26): no se mezclan con la conversación y se sustituyen en cada subida; los errores de chat sí se intercalan en la conversación. La alternativa, llevar todo a la conversación, confundiría estados de herramientas distintas.
- **`empty_index` con estado propio** (RF-22): se distingue por texto como «sin código indexado» y ofrece subir un archivo. La alternativa, tratarlo como un aviso genérico, no indicaba la acción necesaria.
- **`used_windows` sin indicador aparte** (RF-10): el mensaje de la API ya avisa cuando el archivo se troceó por ventanas. La alternativa, añadir una etiqueta propia, duplicaría la misma información.
- **Tiempo de espera del cliente de 75 segundos** (RF-34): el peor caso del chat son 60 segundos (30 s por intento × 2 intentos por el reintento automático de la spec 003) y se añaden 15 s de margen para la red y el procesamiento. Al agotarse se muestra «no se recibió respuesta a tiempo», sin citas y sin historial; el aborto no es una cancelación manual ni garantiza que el servidor deje de procesar la subida.
- **Las citas son informativas y no interactivas**: se numeran igual que las marcas, pero no abren el archivo ni resaltan el fragmento, porque la interfaz no recibe el contenido ni puede navegar a la línea.
- **La interfaz se sirve desde el mismo origen y con el mismo arranque** (RF-1, RNF-9): cómo se publican la página y sus recursos se decide en el plan; esta spec solo fija que no hay build ni proceso aparte.
- **El estado vacío no afirma que el índice esté vacío** (RF-3): la interfaz no tiene forma de consultarlo y solo invita a subir y preguntar.
