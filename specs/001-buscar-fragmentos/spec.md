# Spec 001 — Buscar fragmentos

Estado: implementada

## Contexto y objetivo
CodeMentor responde preguntas sobre código Python citando archivo, símbolo y líneas. Esta spec define la capacidad de recuperación: dada una consulta en lenguaje natural, devolver los fragmentos de código más relevantes para que otra capacidad redacte la respuesta. El objetivo es que quien consulta localice una funcionalidad sin leer todos los archivos y pueda verificar cada cita.
Esta spec presupone que el código ya fue cargado y troceado en un índice. Esa preparación se define en una spec aparte.

## Usuarios
- Persona que consulta código, con conocimientos básicos de Python, que ya dispone de código indexado.
- La capacidad de chat, que consumirá los fragmentos como contexto para redactar respuestas citadas.

## Historias de usuario
- HU-1. Como persona que consulta código, quiero buscar con una pregunta en español para encontrar dónde está una funcionalidad sin revisar archivo por archivo.
- HU-2. Como persona que consulta código, quiero recibir archivo, símbolo y líneas de cada fragmento para abrirlo y comprobar la respuesta.
- HU-3. Como persona que consulta código, quiero distinguir "no hay código indexado" de "no encontré nada relevante" para saber si el problema es la consulta o la falta de datos.
- HU-4. Como capacidad de chat, quiero recibir fragmentos ordenados por relevancia y con su puntuación para construir un contexto fiable.

## Definiciones
- **Fragmento**: porción de código Python indexada, identificada por su ruta de archivo, nombre de símbolo y rango de líneas.
- **Consulta**: texto libre en lenguaje natural, normalmente en español.
- **Consulta normalizada**: la consulta en minúsculas, sin tildes ni otros signos diacríticos y con los espacios consecutivos reducidos a uno. Es el texto con el que se calcula la relevancia.
- **Relevancia**: grado de similitud semántica entre la consulta normalizada y un fragmento, en una escala de 0 a 1.
- **Umbral mínimo**: 0,30 por defecto. Un fragmento es relevante cuando su puntuación, redondeada a 6 decimales, es mayor o igual que el umbral. El redondeo evita que el ruido de los números decimales descarte una puntuación de 0,30 exacta. Solo quien opera CodeMentor puede cambiar el umbral.

## Requisitos funcionales
- RF-1: CUANDO se recibe una consulta válida y existen fragmentos indexados, EL SISTEMA devuelve como máximo cinco fragmentos ordenados de mayor a menor relevancia.
- RF-2: EL SISTEMA descarta todo fragmento cuya relevancia sea menor que el umbral mínimo configurado, 0,30 por defecto.
- RF-3: SI no hay fragmentos indexados, ENTONCES EL SISTEMA no realiza la búsqueda, devuelve cero fragmentos e indica que no hay código indexado.
- RF-4: SI hay fragmentos indexados pero ninguno alcanza el umbral, ENTONCES EL SISTEMA devuelve cero fragmentos e indica que no encontró fragmentos relevantes.
- RF-5: SI la consulta está vacía o solo contiene espacios, ENTONCES EL SISTEMA no realiza la búsqueda, devuelve cero fragmentos e indica que la consulta es obligatoria. Esta comprobación se hace antes que la de longitud.
- RF-6: SI la consulta, tal como se recibe y no vacía, supera los 1.000 caracteres, ENTONCES EL SISTEMA no realiza la búsqueda, devuelve cero fragmentos e indica el límite permitido.
- RF-7: EL SISTEMA incluye en cada resultado la ruta del archivo, el símbolo, la línea inicial, la línea final, el texto del fragmento y su puntuación de relevancia.
- RF-8: EL SISTEMA no devuelve dos veces el mismo fragmento, entendido como misma ruta y mismo rango de líneas.
- RF-9: CUANDO dos fragmentos obtienen la misma puntuación, EL SISTEMA los ordena de forma estable y determinista.
- RF-10: MIENTRAS el conjunto de fragmentos indexados no cambie, EL SISTEMA devuelve los mismos resultados en el mismo orden para la misma consulta.
- RF-11: CUANDO la consulta usa palabras distintas a las del código pero con el mismo significado, EL SISTEMA recupera el fragmento correspondiente si alcanza el umbral.
- RF-12: CUANDO dos consultas difieren solo en mayúsculas, tildes o espacios repetidos, EL SISTEMA devuelve los mismos resultados para ambas.
- RF-13: SI la consulta contiene signos de puntuación o caracteres especiales, ENTONCES EL SISTEMA la procesa sin producir un error.

## Requisitos no funcionales
- RNF-1: La búsqueda no ejecuta, importa ni evalúa el código indexado; solo lo trata como texto.
- RNF-2: La búsqueda no escribe el código indexado en disco ni lo envía a servicios externos.
- RNF-3: Los mensajes de "sin código indexado", "sin fragmentos relevantes", "consulta obligatoria" y "consulta demasiado larga" se muestran en español y son comprensibles para alguien que empieza.
- RNF-4: La búsqueda sobre el índice (sin contar la carga del modelo de embeddings ni el cálculo del vector de la consulta) tarda menos de 2 segundos con 10.000 fragmentos de 384 dimensiones.

## Casos límite
- Una consulta de exactamente 1.000 caracteres se acepta; una de 1.001 se rechaza. La longitud se mide sobre el texto recibido, antes de normalizarlo.
- Una consulta de solo espacios se rechaza como vacía aunque supere los 1.000 caracteres.
- Una puntuación de exactamente 0,30 cuenta como relevante, también cuando llega como 0,29999998 por precisión decimal.
- Menos de cinco fragmentos superan el umbral: se devuelven solo los que lo superan.
- Un único fragmento supera el umbral: se devuelve un solo resultado.
- La consulta no comparte ninguna palabra literal con el código: se recupera por significado si supera el umbral.
- El mismo nombre de símbolo aparece en archivos distintos: cada resultado identifica su ruta.
- El mismo fragmento fue indexado dos veces: se devuelve una sola vez.
- La consulta incluye acentos, mayúsculas o espacios repetidos: se interpreta igual que su forma simple.
- La consulta incluye signos como `¿?()` o caracteres especiales: no produce error.

## Fuera de alcance
- Cargar archivos, trocearlos y construir el índice: tendrá su propia spec.
- Redactar respuestas con un modelo de lenguaje o generar citas narrativas.
- Exponer la búsqueda como herramienta MCP.
- Indexar archivos JavaScript.
- Filtrar por archivo, símbolo o fecha, y paginar resultados.
- Cualquier interfaz web de búsqueda.
- Medir y optimizar el tiempo de carga del modelo (se tratará en la spec de la API).

## Criterios de finalización
- Cada requisito funcional tiene una prueba automatizada que pasa sin red, sin claves y sin descargar recursos externos.
- Los casos límite anteriores están cubiertos por pruebas.
- Los cuatro motivos de lista vacía se distinguen entre sí.
- Está verificado de forma automatizada que la búsqueda no ejecuta el código indexado ni abre conexiones de red.
- La spec pasa de borrador a aprobada antes de planificar la implementación.

## Dudas abiertas
Ninguna sobre el comportamiento. Los cambios de esta revisión se confirman al aprobar la spec:
- Se añaden RF-12 (consultas equivalentes) y RF-13 (caracteres especiales).
- Se compara la puntuación redondeada a 6 decimales.
- Se reescribe RNF-4 para medir solo la búsqueda sobre el índice.
- Se fija el orden de validación: primero consulta vacía, luego longitud.