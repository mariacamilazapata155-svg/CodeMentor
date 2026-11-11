# Spec 003 — Responder con citas

Estado: implementada


Depende de: spec 001 (búsqueda de fragmentos) y spec 002 (indexado). Ambas ya definen el índice y su contrato; esta spec no los modifica.

## Contexto y objetivo
Las specs 001 y 002 permiten construir un índice de fragmentos de código y recuperar los más relevantes para una pregunta. Falta el último paso: convertir esos fragmentos en una respuesta que una persona pueda leer y comprobar.

El objetivo es que, dada una pregunta en español (y, opcionalmente, lo conversado antes), el sistema responda **solo** con el código recuperado, en español, y devuelva junto a la respuesta las citas (archivo, símbolo y líneas) de los fragmentos en los que se apoya, para abrirlos y verificarlos. Cuando el código no alcanza, no hay nada indexado, falta la clave del modelo o el modelo falla, el sistema lo dice en español y no inventa nada.

Esta spec solo define la capacidad de responder. No redefine la búsqueda, el umbral ni el indexado, y no define rutas HTTP, interfaz web ni herramientas MCP.

## Usuarios
- Persona que consulta código, con conocimientos básicos de Python, que ya tiene código indexado.
- La capa HTTP (spec 004) y la interfaz web (spec 005), que mostrarán la respuesta y las citas sin conocer cómo se obtuvieron.
- Quien opera CodeMentor, que configura la clave de acceso al modelo.

## Historias de usuario
- HU-1. Como persona que consulta código, quiero hacer una pregunta en español y recibir una respuesta basada en mi código, para entenderlo sin leer todos los archivos.
- HU-2. Como persona que consulta código, quiero que cada respuesta indique de qué fragmentos sale (archivo, símbolo y líneas) y qué parte de la respuesta respalda cada uno, para abrirlos y comprobarla.
- HU-3. Como persona que consulta código, quiero que, si el código indexado no alcanza para responder, el sistema lo diga en lugar de inventar una respuesta.
- HU-4. Como persona que consulta código, quiero saber por qué no recibí respuesta (pregunta vacía o demasiado larga, nada indexado, nada relevante, falta de clave, fallo del modelo), para saber qué corregir.
- HU-5. Como persona que consulta código, quiero poder hacer preguntas de seguimiento dentro de una conversación, para no repetir el contexto cada vez.
- HU-6. Como operador, quiero que la aplicación arranque y que las pruebas pasen sin clave y sin llamar al modelo, para trabajar y verificar sin coste ni red.
- HU-7. Como capa HTTP o interfaz, quiero recibir siempre un resultado con la misma forma y con un texto en español listo para mostrar, para no ramificar por tipos de error.

## Definiciones
- **Pregunta**: texto libre que se recibe; es la misma "consulta" de la spec 001 y se valida allí.
- **Historial**: lista ordenada de mensajes anteriores de la conversación, cada uno con rol (`user` o `assistant`) y contenido. Lo aporta quien llama; el sistema no lo guarda.
- **Fragmento entregado**: fragmento recuperado por la búsqueda que se envía al modelo como contexto. Se numera desde 1 en orden de relevancia.
- **Marca**: referencia a un fragmento entregado con la forma exacta `[F` + número + `]`, donde el número es un entero de 1 a 999 sin ceros a la izquierda (por ejemplo `[F2]`). Cualquier otro texto, como `[F0]`, `[F01]` o `[f2]`, no es una marca.
- **Marca válida**: marca cuyo número corresponde a un fragmento entregado.
- **Cita**: referencia verificable formada por el número de la marca, la ruta del archivo, el nombre del símbolo, la línea inicial y la línea final. Sus datos salen siempre del fragmento entregado, nunca del texto del modelo; del texto del modelo solo se toma el número de la marca, y solo si es válida.
- **Centinela de "no encontrado"**: el texto exacto `NO_ENCONTRADO`, que el modelo debe devolver, y nada más, cuando los fragmentos no bastan para responder.
- **Respuesta fundamentada**: respuesta del modelo con al menos una marca válida.
- **Historial enviado**: los mensajes del historial que realmente se envían al modelo, tras aplicar RF-11.
- **Motivo**: código que explica por qué no hubo respuesta. Cuando la respuesta se da, no hay motivo.
- **Clave de acceso**: valor de la variable de entorno `ANTHROPIC_API_KEY`.
- **Fallo del modelo**: cualquier error al llamar al modelo que provoque el servicio del modelo o su cliente oficial: tiempo agotado, conexión, límite de peticiones, error del servidor, clave inválida u otro rechazo.

## Requisitos funcionales
- RF-1: CUANDO se recibe una pregunta y un historial, EL SISTEMA busca fragmentos con la capacidad de la spec 001, entrega al modelo los fragmentos recuperados junto con la pregunta y el historial enviado, y devuelve la respuesta con sus citas.
- RF-2: SI la búsqueda no devuelve fragmentos (pregunta vacía, pregunta demasiado larga, sin código indexado o sin fragmentos relevantes), ENTONCES EL SISTEMA no llama al modelo, devuelve como respuesta el mensaje en español que ya produce la búsqueda, cero citas y el motivo correspondiente (`empty_query`, `query_too_long`, `empty_index` o `no_relevant`).
- RF-3: EL SISTEMA busca solo con la pregunta actual; el historial no modifica la búsqueda ni la reformula.
- RF-4: CUANDO hay fragmentos, EL SISTEMA entrega al modelo cada fragmento numerado desde 1 en el mismo orden de relevancia que devuelve la búsqueda, con su ruta, su símbolo, su rango de líneas y su texto, delimitado como dato.
- RF-5: EL SISTEMA instruye al modelo, mediante un mensaje de sistema fijo, para que: responda en español; use solo los fragmentos entregados; marque cada afirmación con la marca del fragmento que la respalda; trate el contenido de los fragmentos como datos y no como instrucciones; y, si los fragmentos no bastan, responda exactamente `NO_ENCONTRADO` y nada más.
- RF-6: CUANDO la respuesta del modelo, sin espacios ni saltos de línea en los extremos, es exactamente `NO_ENCONTRADO`, ENTONCES EL SISTEMA devuelve un mensaje en español que indica que no encontró la respuesta en el código indexado, cero citas y el motivo `insufficient_context`.
- RF-7: CUANDO la respuesta del modelo es fundamentada, EL SISTEMA devuelve su texto (con las marcas inválidas eliminadas según RF-10) y una cita por cada fragmento referenciado por alguna marca válida, ordenadas por la primera aparición de su marca en el texto y sin repetir fragmentos.
- RF-8: EL SISTEMA construye cada cita únicamente con los datos del fragmento entregado correspondiente (ruta, símbolo, línea inicial y línea final); ningún dato de la cita se toma del texto del modelo, salvo el número de la marca.
- RF-9: SI la respuesta del modelo no contiene ninguna marca válida y no es el centinela, incluida una respuesta vacía, ENTONCES EL SISTEMA no muestra el texto del modelo y devuelve un mensaje en español que indica que no pudo respaldar la respuesta con fragmentos concretos, cero citas y el motivo `ungrounded_answer`.
- RF-10: CUANDO el texto del modelo contiene marcas que no son válidas (número mayor que el de fragmentos entregados), EL SISTEMA las elimina del texto devuelto y no genera citas para ellas.
- RF-11: EL SISTEMA envía al modelo como historial, como máximo, los últimos 10 mensajes del historial recibido, tras descartar los mensajes vacíos o de solo espacios; recorta cada mensaje a sus primeros 4.000 caracteres; descarta los mensajes iniciales del asistente para que el primero sea del usuario; y une en un solo mensaje, separados por una línea en blanco, los mensajes consecutivos del mismo rol. Si no queda ningún mensaje, envía solo la pregunta.
- RF-12: EL SISTEMA limita el contexto enviado: cada fragmento entregado se trunca a sus primeros 6.000 caracteres con un aviso en el propio texto enviado; la suma de los textos de los fragmentos entregados no supera 20.000 caracteres; los fragmentos que no caben y los posteriores se omiten, no se numeran y no se pueden citar; el primer fragmento siempre se entrega. La cita de un fragmento truncado conserva su rango de líneas real.
- RF-13: SI hay fragmentos y no hay clave de acceso (variable ausente, vacía o de solo espacios), ENTONCES EL SISTEMA no llama al modelo ni abre ninguna conexión, y devuelve un mensaje en español que explica cómo configurarla, cero citas y el motivo `missing_api_key`. Esta comprobación se hace después de la búsqueda: si la búsqueda no devuelve fragmentos, se aplica RF-2 y no se exige clave.
- RF-14: SI el modelo no responde dentro del tiempo máximo de espera, ENTONCES EL SISTEMA devuelve un mensaje en español, cero citas y el motivo `api_timeout`.
- RF-15: SI no se puede conectar con el modelo, se supera el límite de peticiones o el servicio responde con un error del servidor, ENTONCES EL SISTEMA devuelve un mensaje en español que invita a reintentarlo más tarde, cero citas y el motivo `api_unavailable`.
- RF-16: SI el modelo rechaza la clave por no ser válida o por falta de permiso, ENTONCES EL SISTEMA devuelve un mensaje en español, cero citas y el motivo `invalid_api_key`.
- RF-17: SI el cliente oficial del modelo lanza cualquier otro error propio no cubierto por RF-14 a RF-16, ENTONCES EL SISTEMA devuelve un mensaje en español, cero citas y el motivo `api_error`. Los errores que no son del cliente oficial no se traducen.
- RF-18: EN todo fallo del modelo (RF-14 a RF-17), EL SISTEMA no incluye detalles técnicos ni la clave en el mensaje, no devuelve citas y deja el índice como estaba.
- RF-19: EL SISTEMA devuelve siempre un resultado con tres datos: `reply` (texto en español listo para mostrar), `citations` (lista de citas) y `reason` (motivo o ausente). `reason` está ausente si y solo si la respuesta es fundamentada, y en ese caso hay al menos una cita; en cualquier otro caso `citations` está vacía.
- RF-20: MIENTRAS el índice, la pregunta y el historial no cambien, EL SISTEMA construye exactamente el mismo texto para el modelo (mensaje de sistema, historial enviado y mensaje final).
- RF-21: EL SISTEMA delimita cada fragmento de modo que ningún texto de fragmento, ruta o símbolo pueda cerrar su bloque ni imitar el inicio o el final de otro, aunque contenga marcas, delimitadores o instrucciones.
- RF-22: EL SISTEMA no guarda historial ni respuestas entre llamadas; cada llamada depende solo de sus entradas y del índice.

## Requisitos no funcionales
- RNF-1: Al modelo solo se envían el mensaje de sistema fijo, el historial enviado, la pregunta y los fragmentos entregados con su ruta, símbolo y líneas (constitución, principio 5). No se envía ningún otro fragmento indexado, ni datos del equipo, del entorno o de la clave.
- RNF-2: El código recuperado se trata solo como texto: no se ejecuta, importa ni evalúa (constitución, principio 5).
- RNF-3: Importar el módulo del bot y arrancar la aplicación no requiere clave ni abre conexiones: el cliente del modelo se crea de forma diferida, solo cuando hay fragmentos y clave (constitución, principio 4).
- RNF-4: Todos los mensajes al usuario están en español, son comprensibles para alguien que empieza, no contienen detalles técnicos internos ni la clave, y el de falta de clave nombra la variable `ANTHROPIC_API_KEY` y cómo configurarla (constitución, principio 7).
- RNF-5: Los detalles técnicos de un fallo del modelo se registran con el sistema de registros del lenguaje (nunca con `print`) e incluyen solo el tipo de error; no incluyen la clave, la pregunta, el historial ni el código.
- RNF-6: Construir el mensaje para el modelo y procesar su respuesta, sin contar la búsqueda ni la llamada al modelo, tarda menos de 1 segundo con 5 fragmentos de 6.000 caracteres y un historial de 10 mensajes.
- RNF-7: La espera por cada intento de llamada al modelo es de 30 segundos como máximo, con un máximo de un reintento automático del cliente oficial.

## Casos límite
- Pregunta de exactamente 1.000 caracteres: se acepta. De 1.001: `query_too_long`, sin llamar al modelo.
- Pregunta vacía y sin clave: `empty_query`, no `missing_api_key`.
- Índice vacío y sin clave: `empty_index`.
- Sin fragmentos relevantes y sin clave: `no_relevant`.
- Hay fragmentos y la clave está vacía o es solo espacios: `missing_api_key`, sin crear el cliente.
- Un único fragmento relevante: se entrega numerado `F1`.
- Cinco fragmentos relevantes y el modelo usa `[F2]` y `[F4]`: dos citas, con números 2 y 4.
- El modelo usa `[F1]` varias veces: una sola cita.
- El modelo usa `[F3]` antes que `[F1]`: las citas salen en el orden 3, 1.
- Marca `[F9]` con solo 3 fragmentos entregados: se elimina del texto y no genera cita; si era la única marca, se aplica RF-9.
- Textos `[F0]`, `[F01]`, `[f2]` o `[F1234]`: no son marcas; se dejan como texto y no generan citas.
- Marca dentro de código que escribe el modelo, como `x[F2]`: cuenta como marca; es una limitación conocida del formato.
- Respuesta `NO_ENCONTRADO` rodeada de espacios o saltos de línea: se reconoce como centinela. `NO_ENCONTRADO` dentro de un texto más largo: no es centinela; se aplican las reglas de las marcas.
- Respuesta del modelo vacía o formada por varios bloques de texto: la vacía cae en RF-9; los bloques se unen en un solo texto sin separador.
- Respuesta cortada por el límite de longitud: se procesa igual; si contiene marcas válidas, se devuelve.
- El modelo menciona en su texto una ruta que no existe: el texto se devuelve, pero la lista de citas solo contiene fragmentos entregados.
- Historial vacío: solo se envía la pregunta con su contexto.
- Historial de 25 mensajes: se envían como máximo los últimos 10.
- Historial cuyo primer mensaje enviado sería del asistente: ese mensaje se descarta.
- Historial con mensajes vacíos o de solo espacios: se descartan antes de contar los 10.
- Historial cuyo último mensaje es del usuario: se une con el mensaje final, separados por una línea en blanco.
- Mensaje del historial de más de 4.000 caracteres: se envían sus primeros 4.000.
- Historial formado solo por mensajes del asistente: queda vacío y se envía solo la pregunta.
- Fragmento de exactamente 6.000 caracteres: se entrega entero. De 6.001: se trunca y se avisa.
- Cinco fragmentos cuyos textos suman más de 20.000 caracteres: los últimos que no caben se omiten; solo se numeran y se pueden citar los entregados.
- Primer fragmento de más de 20.000 caracteres: se entrega truncado a 6.000.
- Fragmento cuyo texto contiene `[F1]`, líneas de signos `=` o la frase "FIN FRAGMENTO": no altera la delimitación de ningún fragmento.
- Fragmento cuyo texto contiene instrucciones dirigidas al modelo (por ejemplo, "ignora lo anterior"): se entrega como dato, con el mensaje de sistema que lo declara así.
- Pregunta que contiene una marca como `[F1]`: no tiene efecto, porque solo se analizan las marcas de la respuesta del modelo.
- Pregunta en otro idioma: se procesa igual; el mensaje de sistema pide responder en español.
- Misma pregunta dos veces con el mismo índice e historial: se envía exactamente el mismo texto al modelo.
- Archivo malicioso indexado, con código que borra archivos o abre conexiones: sus fragmentos se tratan como texto y nada se ejecuta.
- Tiempo agotado, límite de peticiones (429), error del servidor (500 o 529), clave rechazada (401 o 403) o petición rechazada (400): cada uno produce su motivo y ninguno deja citas.
- Error que no es del cliente oficial del modelo (un fallo de programación): no se traduce a un motivo; se propaga.

## Fuera de alcance
- Rutas HTTP, validación de formato de las peticiones, códigos de estado y carga de `.env`: corresponden a la spec 004.
- Interfaz web, vista de las citas y respuesta progresiva (streaming): specs posteriores.
- Exponer la respuesta o la búsqueda por MCP.
- Reformular la pregunta usando el historial antes de buscar: en esta versión las preguntas de seguimiento se envían al modelo con el historial, pero la búsqueda usa solo la pregunta actual.
- Guardar el historial o las respuestas, o contar tokens y costes.
- Elegir el modelo por petición, reintentos propios más allá del cliente oficial y caché de respuestas.
- Citar líneas concretas dentro de un fragmento: la cita es el rango completo del fragmento.
- Verificar que cada afirmación del texto del modelo sea cierta: esta spec garantiza que las citas existen y coinciden con los fragmentos entregados, no que el modelo las use con acierto.
- Evaluar la calidad de las respuestas con el modelo real (spec 008d).

## Criterios de finalización
- Cada requisito funcional y no funcional tiene una prueba automatizada que pasa sin red, sin claves y sin llamadas reales al modelo (constitución, principio 4), y `ruff check .` no reporta errores.
- Todos los casos límite anteriores están cubiertos por pruebas.
- Está verificado que ningún dato de una cita proviene del texto del modelo: con un modelo simulado que inventa rutas, símbolos y líneas en su texto, las citas siguen coincidiendo con los fragmentos entregados.
- Está verificado que la respuesta sin marcas válidas no muestra el texto del modelo y que el centinela produce `insufficient_context`.
- Está verificado qué se envía al modelo: solo el mensaje de sistema, el historial enviado, la pregunta y los fragmentos entregados; un fragmento indexado que no fue recuperado nunca aparece.
- Está verificado el orden de las comprobaciones: la búsqueda va antes que la comprobación de la clave, y sin fragmentos no se pide clave ni se llama al modelo.
- Está verificado que el cliente del modelo no se crea al importar el módulo ni cuando no hay fragmentos o clave.
- Está verificado que cada fallo del modelo produce su motivo, sin citas, sin detalles técnicos y sin tocar el índice, y que un error ajeno al cliente oficial se propaga.
- Está verificado que el texto enviado al modelo es idéntico para las mismas entradas y que un fragmento hostil no altera la delimitación.
- Está verificado el recorrido completo: indexar un archivo (spec 002), preguntar por algo que contiene, y obtener una respuesta con una cita cuyo archivo, símbolo y líneas coinciden con el fragmento.
- Está verificado que los registros de un fallo no contienen la clave, la pregunta ni el código.
- La spec pasa de borrador a aprobada antes de planificar la implementación.

## Dudas abiertas
Ninguna sobre el comportamiento. Estas decisiones de diseño se confirman al aprobar la spec:
- **Cómo se eligen las citas.** El modelo marca con `[Fn]` los fragmentos que usa y solo se aceptan marcas que correspondan a fragmentos entregados. Se interpreta el principio 6 ("las citas salen de los resultados de la búsqueda, nunca del texto del modelo") como: los datos de la cita salen de la búsqueda y del texto solo se toma un número validado. Alternativa más estricta: citar siempre todos los fragmentos entregados, sin leer marcas; es más simple, pero cita fragmentos que quizá no se usaron.
- **Respuesta sin marcas válidas.** Se descarta el texto del modelo y se devuelve `ungrounded_answer`, en vez de mostrarlo sin citas.
- **Centinela.** `NO_ENCONTRADO` para el caso "no alcanza", en lugar de inferirlo del texto.
- **Búsqueda solo con la pregunta actual.** Las preguntas de seguimiento con referencias ("¿y esa función?") pueden recuperar peor; la reformulación con historial queda para una spec posterior.

**Aclaración de redacción aprobada (sin cambio de comportamiento).** En RF-12, "los fragmentos que no caben y los posteriores se omiten" explicita lo ya decidido al aprobar la spec: al no caber un fragmento se omiten también los siguientes, para que la numeración sea contigua y se respete el orden de relevancia. El comportamiento no cambia.