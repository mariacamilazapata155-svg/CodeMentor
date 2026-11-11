# Spec 006 — Servidor MCP

Estado: implementada


## Contexto y objetivo
Las specs 001 y 002 dejan dos capacidades que solo se pueden usar desde código o, desde la spec 004, desde un cliente HTTP: indexar el contenido de un archivo Python con su ruta y buscar los fragmentos relevantes para una pregunta. La spec 005 las pone al alcance de una persona en el navegador, pero un agente que trabaja con código —un asistente de escritorio, el inspector oficial del protocolo o un script— no tiene forma de usarlas.

Esta spec define un servidor que expone esas dos capacidades como herramientas del protocolo MCP (Model Context Protocol). El cliente lanza el servidor, descubre dos herramientas —una de búsqueda y una de indexado— y las invoca; el servidor responde con fragmentos citables o con el resultado del indexado. El objetivo es que un agente pueda fundamentar sus respuestas sobre el código que le interesa sin pasar por HTTP, sin una clave de API y sin un modelo de lenguaje: el servidor solo recupera e indexa.

El servidor es una capa fina: valida solo lo que es suyo —la presencia y el tipo de los argumentos, que la ruta no esté vacía y que termine en `.py` (regla que esta spec define y que coincide con la de la subida HTTP de la spec 004) y las reglas que ya fijan las specs 001 y 002—, delega en esas capacidades y devuelve mensajes claros en español. Los fallos se devuelven como resultados marcados como error, nunca como excepciones sueltas ni cerrando la conexión.

El índice que consulta es el de su propio proceso: empieza vacío y no se comparte con el servidor HTTP ni con ningún otro proceso, así que hay que indexar por MCP lo que se quiera consultar.

Esta spec no expone el chat ni la generación de respuestas (spec 003), no expone HTTP ni la interfaz web (specs 004 y 005), no persiste el índice, no lee archivos del disco y no añade herramientas más allá de las dos que fija el roadmap.

## Usuarios
- Agentes y clientes MCP: un asistente de escritorio, el inspector oficial del protocolo o un script que necesita consultar código.
- Quien opera CodeMentor, que configura el servidor en su cliente y comprueba que funciona.
- Persona que consulta código a través de un agente y recibe citas que puede verificar.
- Quien revisa la calidad (QA), que valida el protocolo con el inspector.

## Historias de usuario
- HU-1. Como agente, quiero buscar en el código indexado con una pregunta y recibir los fragmentos con su ruta, símbolo, líneas y texto, para fundamentar mi respuesta sin abrir los archivos.
- HU-2. Como agente, quiero indexar un archivo entregando su contenido y su ruta, para poder consultarlo después en la misma sesión.
- HU-3. Como agente, quiero saber cuándo una invocación falló y por qué, con un mensaje claro en español, para explicarlo o cambiar de estrategia sin romper la conversación.
- HU-4. Como operador, quiero arrancar el servidor y verlo conectado en el inspector oficial, sin clave ni servicios externos, para comprobar que está bien configurado.
- HU-5. Como persona que entrega código ajeno, quiero que el servidor no ejecute, no importe y no guarde el código, para no exponerme a código malicioso.
- HU-6. Como operador, quiero que el servidor no ensucie la salida del protocolo, para que el cliente no se desconecte ni falle.
- HU-7. Como persona que revisa una respuesta, quiero que las citas del agente salgan de los fragmentos reales, para poder comprobarlas.

## Definiciones
- **Servidor MCP**: proceso que se comunica con un cliente por la entrada y la salida estándar y publica herramientas que el cliente puede invocar.
- **Cliente MCP**: programa que lanza el servidor, descubre sus herramientas y las invoca.
- **Herramienta**: operación publicada con un nombre, una descripción y un esquema de argumentos, que devuelve un resultado.
- **Invocación**: una llamada del cliente a una herramienta con sus argumentos.
- **Herramienta de búsqueda** (`search_code`): la que recibe `query`, un texto obligatorio, y devuelve fragmentos.
- **Herramienta de indexado** (`index_file`): la que recibe `path` y `content`, ambos textos obligatorios, y deja el contenido disponible para la búsqueda.
- **Contrato de argumentos**: `search_code` recibe `query`; `index_file` recibe `path` y `content`. Todos son texto y obligatorios; ninguna herramienta acepta argumentos opcionales ni de otro tipo.
- **Contenido del archivo**: el texto que el cliente entrega en `content`. Es la única entrada de código del servidor; decodificar el archivo original es responsabilidad del cliente.
- **Ruta del archivo**: el texto que el cliente entrega en `path`, con el que se identifica un archivo en el índice y en las citas. Es una etiqueta: no se resuelve y no se usa para acceder al disco. Su existencia en el sistema de archivos no se comprueba; solo se valida su forma: que no esté vacía ni contenga solo espacios y que termine en `.py` (RF-12 y RF-13).
- **Índice del servidor MCP**: el conjunto de fragmentos que vive en la memoria del proceso del servidor MCP. Es independiente del índice de cualquier otro proceso y se pierde al terminar el proceso; por eso, para consultar un archivo por MCP hay que haberlo indexado por MCP en ese proceso, aunque ya se haya subido por HTTP.
- **Consulta**: la de la spec 001.
- **Fragmento**: el de la spec 001.
- **Resultado con error**: resultado de una invocación que no completa su operación; lleva un mensaje en español y está marcado como error.
- **Resultado sin error**: resultado de una invocación que completa su operación, aunque no devuelva fragmentos.
- **Mensaje reutilizado**: el que produce la capacidad de las specs 001 o 002 para el mismo caso y se devuelve sin cambiar ni una palabra.
- **Mensaje adaptado**: el que se reescribe porque el de la capacidad se refiere a subir un archivo o a la interfaz web. El texto exacto de los mensajes adaptados y de los propios de esta capa se fija en el plan.

## Requisitos funcionales

### Publicación de herramientas
- RF-1: CUANDO un cliente MCP se conecta y solicita la lista de herramientas, EL SISTEMA publica exactamente dos, la de búsqueda (`search_code`) y la de indexado (`index_file`), cada una con una descripción en español de qué hace y cuándo usarla y con el esquema de sus argumentos. El contrato público es: `search_code` recibe `query`, un texto obligatorio; `index_file` recibe `path` y `content`, ambos textos obligatorios. Ningún argumento es opcional. No publica ninguna otra herramienta, recurso ni plantilla.
- RF-2: EL SISTEMA arranca y publica sus herramientas sin clave de API, sin conexión de red y sin que exista código indexado; la primera operación que necesite el modelo de representaciones puede requerir su descarga o carga (RNF-4).

### Búsqueda
- RF-3: CUANDO se invoca la herramienta de búsqueda con `query` válido y el índice tiene fragmentos, EL SISTEMA aplica el comportamiento de la spec 001 sobre el índice de su proceso y devuelve, en texto legible en español con un bloque por fragmento, hasta cinco fragmentos ordenados de mayor a menor relevancia; cada bloque muestra la ruta, el símbolo, la línea inicial, la línea final, la relevancia y el texto del fragmento. La relevancia se muestra con un criterio estable y verificable (el mismo formato para el mismo valor, dentro de la escala de 0 a 1 de la spec 001); el formato exacto se fija en el plan.
- RF-4: SI la consulta está vacía o solo contiene espacios, ENTONCES EL SISTEMA no busca y devuelve un resultado con error con el mensaje de consulta obligatoria de la spec 001, reutilizado literalmente; una prueba comprueba que el texto es idéntico al que produce esa capacidad.
- RF-5: SI la consulta, tal como se recibe y no vacía, supera los 1.000 caracteres, ENTONCES EL SISTEMA no busca y devuelve un resultado con error con el mensaje de límite de la spec 001, reutilizado literalmente; una prueba comprueba que el texto es idéntico al que produce esa capacidad. La comprobación de vacío se hace antes que la de longitud.
- RF-6: SI falta el argumento `query` o no es texto, ENTONCES EL SISTEMA no busca y devuelve un resultado con error con un mensaje en español que indica que falta la consulta y que debe ser texto; el texto exacto se fija en el plan.
- RF-7: SI el índice no tiene fragmentos, ENTONCES EL SISTEMA no busca y devuelve un resultado sin error, con cero fragmentos y el mensaje de «no hay código indexado» adaptado del de la spec 001, porque el original invita a subir un archivo por la interfaz web; el texto exacto se fija en el plan y una prueba comprueba ese texto. El resultado no lleva marca de error.
- RF-8: SI el índice tiene fragmentos pero ninguno alcanza el umbral, ENTONCES EL SISTEMA devuelve un resultado sin error, con cero fragmentos y el mensaje de «no encontré fragmentos relevantes» de la spec 001, reutilizado literalmente; una prueba comprueba que el texto es idéntico al de esa capacidad.
- RF-9: EL SISTEMA devuelve los fragmentos tal como los produce la búsqueda: no los resume, no los completa, no los reordena ni añade fragmentos que la búsqueda no haya devuelto.

### Indexado
- RF-10: CUANDO se invoca la herramienta de indexado con `path` y `content` válidos, EL SISTEMA aplica el comportamiento de la spec 002 sobre el índice de su proceso y devuelve un resultado sin error con el mensaje de éxito de esa capacidad, reutilizado literalmente (una prueba comprueba la igualdad), la ruta, el número de fragmentos indexados de ese archivo (`chunks_indexed`), no la lista de fragmentos, el total del índice tras el reemplazo y si se troceó por ventanas.
- RF-11: EL SISTEMA indexa exactamente el contenido y la ruta recibidos, sin recortarlos, normalizarlos ni resolverlos, y no lee ningún archivo del sistema de archivos ni comprueba que la ruta exista.
- RF-12: SI falta la ruta, está vacía o solo contiene espacios, ENTONCES EL SISTEMA no indexa y devuelve un resultado con error con un mensaje en español que indica que la ruta es obligatoria; el texto exacto se fija en el plan. Esta es la primera comprobación del indexado, que sigue este orden: ruta presente y no vacía (esta regla), extensión `.py` (RF-13), contenido presente y de tipo texto (RF-14), contenido vacío (RF-15), tamaño (RF-16), tope de fragmentos (RF-17) y representaciones (RF-18).
- RF-13: SI la ruta no termina en `.py` (sin distinguir mayúsculas), ENTONCES EL SISTEMA no indexa y devuelve un resultado con error con un mensaje en español que indica que solo se indexan archivos `.py`; el texto exacto se fija en el plan. Se comprueba después de la ruta no vacía (RF-12) y antes del contenido.
- RF-14: SI falta el contenido o no es texto, ENTONCES EL SISTEMA no indexa y devuelve un resultado con error con un mensaje en español que indica que falta el contenido y que debe ser texto; el texto exacto se fija en el plan. Se comprueba después de la extensión (RF-13) y antes de las comprobaciones de la spec 002.
- RF-15: SI el contenido está vacío o solo contiene espacios, ENTONCES EL SISTEMA no indexa y devuelve un resultado con error con el mensaje de contenido vacío de la spec 002, reutilizado literalmente; una prueba comprueba la igualdad con el de esa capacidad. Se comprueba antes que el tamaño.
- RF-16: SI el contenido ocupa más de 1.048.576 bytes en UTF-8, ENTONCES EL SISTEMA no indexa y devuelve un resultado con error con el mensaje de tamaño de la spec 002, reutilizado literalmente, que incluye el límite y el tamaño recibido; una prueba comprueba la igualdad con el que produce esa capacidad para el mismo contenido. Se comprueba después del vacío y antes del tope.
- RF-17: SI el troceado produciría más de 1.000 fragmentos, ENTONCES EL SISTEMA no indexa y devuelve un resultado con error con el mensaje de tope de fragmentos de la spec 002, reutilizado literalmente, que incluye el tope y la cantidad que habría producido; una prueba comprueba la igualdad con el que produce esa capacidad para el mismo contenido. Se comprueba después del tamaño y antes de calcular ninguna representación.
- RF-18: SI no se puede calcular la representación semántica de algún fragmento, ENTONCES EL SISTEMA no indexa y devuelve un resultado con error con el mensaje de archivo no indexable de la spec 002, reutilizado literalmente; una prueba comprueba la igualdad con el de esa capacidad. Es la última comprobación del indexado.
- RF-19: SI se rechaza un indexado por cualquiera de los motivos anteriores, ENTONCES EL SISTEMA deja el índice exactamente como estaba, incluida la versión anterior de la ruta si ya estaba indexada.
- RF-20: CUANDO se indexa una ruta que ya estaba en el índice, EL SISTEMA sustituye todos sus fragmentos por los nuevos, de modo que una búsqueda posterior devuelve solo la versión nueva y nunca una mezcla.
- RF-21: CUANDO termina un indexado con éxito, EL SISTEMA deja los fragmentos disponibles para la herramienta de búsqueda en la misma sesión, sin reiniciar el proceso ni volver a cargar nada.

### Índice
- RF-22: EL SISTEMA usa un único índice en memoria, propio de su proceso y compartido por las dos herramientas; empieza vacío al arrancar, no se comparte con ningún otro proceso ni servicio y se pierde al terminar el proceso.
- RF-23: MIENTRAS el proceso sigue vivo, EL SISTEMA conserva el índice entre invocaciones, de modo que un indexado previo es visible para todas las búsquedas posteriores.

### Errores
- RF-24: SI una invocación no completa su operación, ENTONCES EL SISTEMA devuelve un resultado marcado como error con un mensaje en español comprensible, sin trazas, sin nombres internos y sin detalles técnicos.
- RF-25: SI ocurre un error no controlado durante una invocación, ENTONCES EL SISTEMA devuelve un resultado marcado como error con un mensaje genérico en español, mantiene el proceso vivo y sigue atendiendo invocaciones posteriores.
- RF-26: EL SISTEMA nunca propaga una excepción suelta al cliente, nunca cierra la conexión por el fallo de una herramienta y nunca deja una invocación sin respuesta.
- RF-27: SI un argumento falta o tiene un tipo distinto del declarado, ENTONCES EL SISTEMA no ejecuta la operación y devuelve un resultado marcado como error con un mensaje en español que indica qué argumento falta o es incorrecto; el texto exacto se fija en el plan.

### Límites de la exposición
- RF-28: EL SISTEMA no expone ninguna herramienta que responda preguntas con un modelo de lenguaje, redacte respuestas, genere citas narrativas o gestione conversaciones.
- RF-29: EL SISTEMA no escucha en ningún puerto ni expone un servidor HTTP: no expone ni atiende HTTP ni sirve la interfaz web, y toda la comunicación con el cliente ocurre por la entrada y la salida estándar del proceso que lo lanza. Si el modelo de representaciones debe descargarse o cargarse, esa operación no forma parte del protocolo y no envía el contenido, la ruta ni la consulta.
- RF-30: EL SISTEMA no ejecuta, importa ni evalúa el contenido indexado, aunque parezca inofensivo; solo lo trata como texto.
- RF-31: EL SISTEMA no escribe en disco el contenido, los fragmentos ni el índice, y no crea archivos temporales para los datos de la aplicación (contenido, fragmentos o índice). Esta garantía no cubre la caché de bytecode que Python pueda generar al importar sus propios módulos (`__pycache__`).
- RF-32: EL SISTEMA no envía a servicios externos el contenido, la ruta ni las consultas; el cálculo de las representaciones es local y la posible descarga o carga del modelo no envía esos datos.
- RF-33: EL SISTEMA no aplica límites de tamaño, de número de resultados ni de número de fragmentos distintos de los de las specs 001 y 002: reutiliza el umbral de 0,30, el máximo de cinco resultados, el límite de 1.000 caracteres de consulta, el de 1.048.576 bytes por archivo y el tope de 1.000 fragmentos.

## Requisitos no funcionales
- RNF-1: El servidor nunca escribe en la salida estándar nada que no forme parte del protocolo: ni mensajes de la aplicación, ni trazas, ni registros por defecto. Todo registro va a la salida de error. Se verifica arrancando el servidor y comprobando que la salida estándar solo contiene mensajes del protocolo durante la conexión, la lista de herramientas, una búsqueda, un indexado y un error.
- RNF-2: Los registros que escribe la aplicación no contienen el contenido, la ruta, la consulta ni los fragmentos; ante un fallo registran solo el tipo del error (constitución, principio 5).
- RNF-3: Todos los mensajes que produce la aplicación al cliente están en español, son comprensibles para alguien que empieza y no contienen detalles técnicos internos (constitución, principio 7); no se refiere a los mensajes que generan el SDK o el protocolo MCP por su cuenta. La comprensibilidad se revisa a mano al cerrar la spec.
- RNF-4: Importar el servidor no descarga el modelo, no requiere red, no requiere clave y no carga el índice; la carga del modelo es diferida y ocurre como máximo una vez por proceso, en la primera operación que la necesite (constitución, principio 4).
- RNF-5: La exposición solo traduce (constitución, principio 3): no trocea, no calcula representaciones, no busca ni redacta; reutiliza las capacidades de las specs 001 y 002 sin cambiar su contrato, su umbral ni su número de resultados. Una prueba comprueba que no reimplementa el troceado ni la búsqueda.
- RNF-6: Las pruebas automatizadas pasan sin red, sin claves y sin descargar el modelo, con dobles de las representaciones y de las capacidades (constitución, principio 4).
- RNF-7: Las descripciones de las herramientas y de sus argumentos están en español e indican para qué sirve cada herramienta, qué recibe y qué devuelve, de modo que un agente sepa cuándo invocarlas.
- RNF-8: El índice se mantiene coherente mientras se atienden invocaciones: una búsqueda durante un indexado no falla y nunca devuelve una ruta con fragmentos de dos versiones mezcladas (spec 002).
- RNF-9: Un error de una herramienta no termina el proceso ni deja el índice corrupto; la siguiente invocación funciona con normalidad.
- RNF-10: El servidor se arranca con las dependencias que ya fija el proyecto, sin dependencias nuevas (constitución, principio 1).

## Casos límite
- Lista de herramientas: exactamente dos, con descripción y esquema; no aparece ninguna otra capacidad.
- `search_code` sin el argumento `query`: error que indica que falta; no se busca.
- Consulta vacía (`""`) o de solo espacios: error con el mensaje de consulta obligatoria; no se busca.
- Consulta de exactamente 1.000 caracteres: se busca. De 1.001: error con el límite.
- Consulta de solo espacios y 1.001 caracteres: se informa consulta obligatoria, porque el vacío se comprueba antes.
- Consulta con mayúsculas, tildes o espacios repetidos: mismos resultados que su forma simple (spec 001).
- Consulta con `¿?()`, emojis o caracteres especiales: no produce error.
- Índice vacío: cero fragmentos y mensaje adaptado de «no hay código indexado», sin marca de error.
- Índice con fragmentos y ninguno relevante: cero fragmentos y mensaje de «no encontré fragmentos relevantes», sin marca de error.
- Búsqueda con varios fragmentos: cada uno aparece en su propio bloque, con ruta, símbolo, líneas, relevancia y texto, en texto legible en español.
- `index_file` con `path` y `content` válidos: indexa y devuelve el mensaje con el número de fragmentos indexados de ese archivo (`chunks_indexed`) y el total, no la lista de fragmentos.
- Ruta vacía o de solo espacios: error que indica que la ruta es obligatoria; no se indexa.
- Ruta sin `.py`: error que indica que solo se indexan archivos `.py`; no se indexa.
- Ruta vacía y contenido vacío a la vez: gana el error de ruta obligatoria, porque la ruta se comprueba primero.
- Ruta que no termina en `.py` y contenido vacío: gana el error de extensión, porque la extensión se comprueba antes que el contenido.
- Contenido ausente y ruta que no termina en `.py`: gana el error de extensión, porque la ruta se valida antes que el contenido.
- Ruta válida y contenido ausente: gana el error de contenido obligatorio, antes que las comprobaciones de la spec 002.
- Contenido vacío o de solo espacios: error con el mensaje de la spec 002; el índice queda intacto.
- Contenido de exactamente 1.048.576 bytes: se indexa. De 1.048.577: error con el límite y el tamaño.
- Contenido que produciría exactamente 1.000 fragmentos: se indexa. 1.001: error con el tope y la cantidad, sin calcular representaciones.
- Fallo al calcular alguna representación: error con el mensaje de la spec 002; el índice queda intacto.
- Archivo que no es Python válido: se indexa por ventanas y el mensaje lo indica (spec 002).
- Archivo con código malicioso (borrar archivos, abrir conexiones): se indexa como texto y no se ejecuta.
- Ruta con forma de recorrido, absoluta o de Windows que termina en `.py` (por ejemplo, `../../etc/passwd.py`, `/etc/passwd.py` o `C:\Windows\System32\evil.py`): se guarda y se devuelve tal cual como etiqueta; es el caso de aceptación.
- Las mismas rutas sin `.py` (por ejemplo, `../../etc/passwd`): se rechazan por extensión antes de guardarlas.
- Garantía de no lectura: indexar una ruta con forma de recorrido o absoluta no abre, lee ni escribe el archivo al que apunta; se comprueba en los criterios de finalización.
- Ruta válida cuyo archivo no existe en el disco: se indexa igualmente, porque la existencia no se comprueba.
- Ruta con etiquetas HTML, comillas o saltos de línea que termina en `.py` (por ejemplo, `<b>a</b>.py`, `"a".py` o `a\nb.py`): se guarda y se devuelve tal cual, sin interpretarla.
- Ruta con esos mismos caracteres que no termina en `.py` (por ejemplo, `<b>a.py</b>`, `"a.py"` o `a\nb.txt`): se rechaza por extensión (RF-13) antes de guardarla.
- Indexar dos veces la misma ruta con contenido distinto: quedan solo los fragmentos nuevos.
- Reindexar una ruta con contenido rechazado: la versión anterior sigue disponible para la búsqueda.
- Indexar y buscar en la misma sesión: la búsqueda encuentra lo recién indexado sin reiniciar.
- Reiniciar el proceso: el índice queda vacío y la primera búsqueda informa de que no hay código indexado.
- Búsqueda mientras se indexa: no falla y la ruta nunca muestra fragmentos de dos versiones mezcladas.
- Argumento con un tipo distinto del declarado (por ejemplo, un `query` que no es texto): error que indica el argumento incorrecto; no se ejecuta.
- Argumento no declarado: se ignora y la operación continúa con los argumentos declarados.
- Error no controlado dentro de una herramienta: mensaje genérico marcado como error; el proceso sigue vivo y la siguiente invocación funciona.
- Servidor arrancado sin red, sin clave y sin código indexado: publica las dos herramientas.
- La salida estándar durante todo el flujo solo contiene mensajes del protocolo; los registros aparecen en la salida de error (comprobación manual con el inspector).

## Fuera de alcance
- Responder preguntas con un modelo de lenguaje, el chat y las citas narrativas (spec 003).
- HTTP, rutas HTTP, puertos, autenticación, TLS y CORS; la interfaz web (specs 004 y 005).
- Leer archivos del disco, recorrer directorios, importar repositorios o detectar cambios en los archivos (008c).
- Persistencia del índice entre reinicios o compartirlo con otro proceso (008a).
- Listar, borrar o limpiar el índice desde una herramienta, reindexar todo el índice o reindexar desde el disco sin entregar el contenido, y filtrar o paginar resultados. Reindexar una ruta entregando de nuevo su contenido sí está en alcance (RF-20).
- Indexar JavaScript u otros lenguajes (008b).
- Recursos, plantillas, notificaciones, suscripciones y cualquier capacidad MCP que no sean las dos herramientas.
- Transportes distintos de la entrada y la salida estándar.
- Cambiar el comportamiento, el contrato, el umbral o los límites de las specs 001 a 005.
- Instalar el servidor en un cliente concreto, publicar el proyecto y el README (spec 007).

## Criterios de finalización
- Cada requisito funcional y no funcional tiene una comprobación que lo verifica; las pruebas automatizadas pasan sin red, sin claves, sin descargar el modelo y sin llamadas reales a un modelo de lenguaje, y `ruff check .` no reporta errores. Son comprobaciones manuales declaradas: la salida estándar limpia (RNF-1), la comprensibilidad de los mensajes (RNF-3) y la prueba con el inspector oficial del protocolo.
- Está verificado con una prueba de protocolo que el servidor completa la conexión inicial y que la lista de herramientas contiene exactamente las dos, con descripción en español y esquema de argumentos; el esquema declara `query` en `search_code` y `path` y `content` en `index_file`, todos obligatorios y de tipo texto.
- Está verificado el flujo completo: se indexa un archivo con la herramienta de indexado y una búsqueda posterior devuelve un fragmento con la ruta, el símbolo y las líneas correctas, en texto legible en español con un bloque por fragmento.
- Está verificado que el índice empieza vacío, que un indexado es visible para las búsquedas posteriores y que se pierde al reiniciar el proceso.
- Está verificado que todos los fallos (consulta vacía o larga, argumento ausente o de tipo incorrecto, ruta vacía, ruta sin `.py`, contenido ausente, vacío, demasiado grande, con demasiados fragmentos o con fallo de representaciones, y error no controlado) se devuelven como resultados marcados como error, con mensaje en español, sin cerrar la conexión y sin terminar el proceso.
- Está verificado el orden de validación del indexado (ruta no vacía, extensión `.py`, contenido presente y de tipo texto, vacío, tamaño, tope de fragmentos y representaciones) y que, en las combinaciones, gana la comprobación anterior.
- Está verificado que los mensajes reutilizados coinciden literalmente con los que producen las capacidades de las specs 001 y 002, y que los adaptados y los propios de esta capa coinciden con el texto fijado en el plan.
- Está verificado que «no hay código indexado» y «no encontré fragmentos relevantes» se devuelven sin marca de error, con el texto fijado en el plan para el primero y con el mensaje literal de la spec 001 para el segundo.
- Está verificado que cada rechazo del indexado deja el índice como estaba y que la versión anterior de una ruta sigue siendo buscable.
- Está verificado que el servidor no lee ni escribe archivos: se indexa una ruta válida que apunta a un archivo del sistema (por ejemplo, `../../etc/passwd.py`) y no se lee nada, y se comprueba que no aparecen archivos nuevos ni temporales creados por el servidor; la verificación ignora `__pycache__` o se ejecuta con `PYTHONDONTWRITEBYTECODE=1`.
- Está verificado que el contenido no se ejecuta ni se importa, con un archivo malicioso como entrada.
- Está verificado que la salida estándar solo contiene mensajes del protocolo y que los registros van a la salida de error, durante la conexión, una búsqueda, un indexado y un error (comprobación manual con el inspector oficial).
- Está verificado que los registros no contienen contenido, rutas, consultas ni fragmentos.
- Está verificado que el servidor arranca sin clave, sin red y sin código indexado, y que importarlo no descarga el modelo.
- Está verificado que no se publica ninguna herramienta de chat ni de generación de respuestas.
- La prueba manual con el inspector oficial del protocolo confirma que las dos herramientas aparecen, se invocan y responden. Usa el modelo de representaciones ya descargado y en caché, y no requiere clave de API. Si no hay modelo descargado o red disponibles, la parte que dependa de él se documenta como pendiente, igual que en las specs 004 y 005, y se completa después con el modelo real y en el entorno real.
- La spec pasa de borrador a aprobada antes de implementar la primera tarea.

## Dudas abiertas
Ninguna. Esta spec fija la decisión, los nombres de los argumentos (`query`, `path` y `content`) y el orden de validación del indexado; los textos literales de los mensajes adaptados y de los propios de esta capa se fijan en el plan, como indican los requisitos correspondientes. No hay puntos pendientes de aclaración.

**Decisiones confirmadas al aprobar la spec**
- **Contenido entregado por el cliente, no leído del disco.** La herramienta de indexado recibe `path` y `content` como texto; el servidor no abre ni comprueba archivos y la existencia de la ruta no se comprueba. Por qué: es lo que ya hacen la capacidad de indexado de la spec 002 y la subida HTTP de la spec 004, respeta el principio 5 y evita que un agente remoto pueda leer archivos arbitrarios del equipo donde corre el servidor. Alternativa descartada: leer la ruta del disco, que permitiría indexar un proyecto sin copiar el texto, pero convertiría la herramienta en un lector de archivos arbitrario y contradiría la spec 002.
- **Índice propio del proceso.** El servidor MCP usa un índice en memoria propio, que empieza vacío, no se comparte con el servidor HTTP ni con otro proceso y se pierde al terminar. Por qué: son procesos distintos y el índice no se persiste (spec 002); compartirlo exigiría persistencia (008a) o un canal entre procesos, ambos fuera de alcance. Consecuencia documentada: hay que indexar por MCP lo que se quiera consultar, aunque ya se haya subido por HTTP.
- **Respuesta en texto legible y errores marcados.** La búsqueda devuelve texto en español con un bloque por fragmento (ruta, símbolo, líneas, relevancia y texto), y los fallos se devuelven con la marca de error del protocolo; «sin resultados» no lleva error e «invocación fallida» sí. Por qué: el cliente entrega el resultado al modelo tal cual y un texto claro se interpreta mejor, y la marca permite distinguir las dos situaciones, igual que la spec 004 distingue 200 de 4xx/5xx. Alternativa descartada: devolver solo JSON estructurado, que facilita el parseo automático pero empeora la lectura del modelo y no es lo que pide el roadmap («mensajes claros»).
- **Exactamente dos herramientas.** Se publican `search_code` e `index_file`; nada de listar, borrar, limpiar ni responder preguntas. Por qué: el roadmap fija esas dos y las specs 001 y 002 no ofrecen listar ni borrar; añadirlas ampliaría el alcance sin una necesidad demostrada. Alternativa descartada: publicar también una herramienta de respuesta, que duplicaría la spec 003 y exigiría una clave de Anthropic que hoy no hace falta.
- **Sin límites nuevos.** Se reutilizan los de las specs 001 y 002: 1.000 caracteres de consulta, 1.048.576 bytes por archivo, 1.000 fragmentos, cinco resultados y umbral 0,30. Por qué: duplicar límites en otra capa crea dos fuentes de verdad y podría rechazar algo que la capacidad acepta; el límite de 1 MiB ya acota el tamaño del argumento. Alternativa descartada: un límite de transporte más bajo (por ejemplo, 256 KiB) para no exceder los mensajes de algunos clientes, que rechazaría archivos que la spec 002 acepta y habría que declarar como excepción.
- **Solo rutas `.py`.** La herramienta de indexado rechaza una ruta que no termine en `.py` (sin distinguir mayúsculas), como la subida HTTP de la spec 004. Por qué: el producto indexa archivos `.py` y una ruta con otra extensión produciría fragmentos por ventanas que aparentan ser código Python, además de mantener la coherencia con lo que la persona puede subir por la web. Alternativa descartada: no validar la extensión, más permisiva, pero mezcla en el índice contenido que el producto no promete.
- **Contrato de argumentos fijo.** `search_code` recibe `query`; `index_file` recibe `path` y `content`; todos son texto y obligatorios, y ninguna herramienta acepta argumentos opcionales. Por qué: un contrato explícito permite que el cliente y el agente sepan qué enviar y hace verificable el rechazo de un argumento ausente o de otro tipo. Alternativa descartada: argumentos opcionales con valores por defecto, que ocultarían errores del cliente y harían ambiguo qué se indexa.
- **Mensajes reutilizados y adaptados.** Se reutiliza literalmente el mensaje de la capacidad cuando encaja (consulta vacía o larga, sin resultados relevantes, contenido vacío, tamaño, tope, fallo de representaciones y éxito del indexado) y se adapta solo cuando el original habla de subir un archivo o de la interfaz web (el de «no hay código indexado»). Los textos exactos de los adaptados y de los propios de esta capa se fijan en el plan. Por qué: una sola redacción por caso evita que dos capas cuenten lo mismo de forma distinta y permite comprobar la igualdad con una prueba. Alternativa descartada: redactar todos los mensajes de nuevo en el servidor, que duplicaría textos y rompería la coherencia con la API y la interfaz.
- **Orden de validación del indexado.** Ruta presente y no vacía, extensión `.py`, contenido presente y de tipo texto y, después, las comprobaciones de la spec 002 (vacío, tamaño, tope de fragmentos y representaciones). Por qué: la ruta y el contenido son argumentos de esta capa y deben rechazarse antes de llamar a la capacidad; el resto se delega en el orden ya fijado por la spec 002. Alternativa descartada: validar el contenido antes que la ruta, que daría un mensaje menos útil cuando faltan ambos.
- **Formato de la relevancia.** La spec solo exige que se muestre con un criterio estable y verificable; el formato exacto (decimales y separador) se fija en el plan. Por qué: el formato es una decisión de presentación que no cambia el contrato de búsqueda y conviene fijarla junto al resto de la respuesta. Alternativa descartada: imponer aquí los decimales, que mezclaría presentación con requisitos y duplicaría una decisión que corresponde al plan.
