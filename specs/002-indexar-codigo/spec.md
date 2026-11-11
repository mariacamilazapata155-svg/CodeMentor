# Spec 002 — Indexar código

Estado: implementada

## Contexto y objetivo
La spec 001 define cómo se busca: dada una consulta, devolver hasta cinco fragmentos por encima de un umbral. Pero presupone algo que todavía no existe: que el código ya esté cargado, troceado y con una representación semántica calculada. Esta spec define esa preparación.

El objetivo es que una persona pueda entregar el contenido de un archivo Python con su ruta y, desde ese momento, ese código sea localizable por la búsqueda: cada fragmento debe llevar la ruta, el símbolo y el rango de líneas exactos, porque son los datos con los que se cita una respuesta y se verifica abriendo el archivo. El troceado no es por párrafos: en Python las unidades con significado son las funciones, las clases y el código que vive a nivel de módulo.

Esta spec solo describe cómo se construye y se amplía el índice. No redefine la búsqueda, el umbral ni el número de resultados de la spec 001.

## Usuarios
- Persona que entrega código para consultarlo después, con conocimientos básicos de Python.
- La capacidad de búsqueda de la spec 001, que consume los fragmentos y sus representaciones semánticas sin saber cómo se produjeron.
- La capacidad de chat, que solo verá los fragmentos recuperados, pero depende de que las citas sean correctas.

## Historias de usuario
- HU-1. Como persona que entrega código, quiero entregar el contenido de un archivo Python con su ruta y que quede disponible para buscar en él, para no tener que leerlo entero cada vez.
- HU-2. Como persona que consulta código, quiero que cada fragmento corresponda a una función, una clase o al código de módulo, con sus líneas exactas, para abrir el archivo y comprobar la cita.
- HU-3. Como persona que consulta código, quiero que un archivo roto o que no es Python también se pueda indexar, aunque sea por trozos aproximados, para no quedarme sin nada que consultar.
- HU-4. Como persona que entrega código, quiero entender en español qué pasó con mi archivo (indexado, vacío, demasiado grande, con demasiados fragmentos, con un fallo al calcular su representación o troceado de forma aproximada) para saber qué esperar de las búsquedas.
- HU-5. Como capacidad de búsqueda, quiero recibir fragmentos con representaciones semánticas comparables entre sí y con la consulta, para que la relevancia tenga sentido.

## Definiciones
- **Indexar**: trocear el contenido de un archivo, calcular la representación semántica de cada fragmento y dejarlos disponibles para la búsqueda.
- **Fragmento**: porción de código indexada, identificada por los seis campos del contrato ya congelado: ruta, nombre de símbolo, línea inicial, línea final, texto y tipo.
- **Nombre de símbolo**: nombre con el que se identifica un fragmento. Una función o una clase de nivel superior lleva su nombre simple (`login`, `User`). Un método definido directamente en el cuerpo de una clase lleva el nombre de esa clase, un punto y su nombre (`User.login`). Una clase definida directamente en el cuerpo de otra clase lleva el nombre de la clase que la contiene directamente, un punto y su nombre (`Outer.Inner`), y sus métodos llevan el nombre cualificado de su clase (`Outer.Inner.metodo`). Un bloque de módulo sin partir se llama `module`; si se parte, `module#1`, `module#2` y siguientes, con numeración única y correlativa en todo el archivo en orden de aparición, que no se reinicia al empezar otro bloque partido. Si un archivo tiene varios bloques de módulo sin partir, todos se llaman `module` y se distinguen por su rango de líneas: es el comportamiento previsto. Cada ventana se llama `window#1`, `window#2` y siguientes en orden de aparición. No se añaden campos al fragmento para esto.
- **Rango de líneas**: par de líneas inicial y final, numeradas desde 1 y con ambos extremos incluidos, que delimita el texto del fragmento dentro del archivo recibido.
- **Texto del fragmento**: contenido que se guarda y se cita de un fragmento. Es la subcadena exacta desde el inicio de su primera línea hasta el final de su última línea, sin el separador que termina esa última línea; si la última línea está vacía, el texto conserva el separador que la precede y termina en salto de línea. No se recortan líneas vacías de los bordes ni se ajusta el rango: rango y texto siempre cuadran.
- **Salto de línea**: solo `\n`, `\r\n` y `\r`. Cualquier otro carácter de control, como `\f`, no abre una línea nueva y cuenta como contenido de la línea en la que aparece.
- **Código a nivel de módulo**: el que no está dentro de ninguna definición indexada. Incluye importaciones, constantes, asignaciones, código de arranque, las cadenas de documentación del módulo y los comentarios que no están pegados a una definición.
- **Línea con código**: línea no vacía que no contiene solo un comentario. Es la unidad que exige RF-7 para considerar que el archivo está cubierto.
- **Bloque contiguo de módulo**: secuencia maximal de líneas consecutivas que no están dentro de ninguna definición indexada, ni son sus decoradores ni los comentarios pegados a esa definición. Se recortan las líneas en blanco del principio y del final del bloque, que no se indexan como parte de él. Los comentarios consecutivos pegados inmediatamente encima de una definición, sin línea en blanco en medio, pertenecen a esa definición; si hay una línea en blanco entre el último de esos comentarios y la definición, se quedan en el bloque de módulo. Si un bloque supera 120 líneas, se parte en trozos contiguos de hasta 120 líneas.
- **Ventana de 60 líneas**: fragmento de 60 líneas consecutivas, sin solape con la ventana siguiente; la última ventana del archivo puede tener menos de 60, incluso una sola línea. Es el plan alternativo cuando el contenido no se puede analizar y solo se usa en ese caso.
- **Representación semántica**: vector numérico que resume el significado de un fragmento o de una consulta y con el que se calcula la relevancia de la spec 001. Se calcula a partir del texto exacto del fragmento, sin recortarlo ni alterarlo (el posible truncado del modelo se trata en RNF-7).
- **Archivo ya indexado**: aquel cuya ruta ya está presente en el índice, con independencia de su contenido.
- **Límite de tamaño de archivo**: 1.048.576 bytes (1 MiB) medidos sobre los bytes UTF-8 del contenido recibido. Un contenido mayor no se indexa.
- **Tope de fragmentos por archivo**: 1.000 fragmentos. Se cuenta sobre los fragmentos que produciría el troceado del archivo recibido, no sobre los que ya hubiera en el índice. Si se supera, el archivo no se indexa.
- **Reemplazo atómico**: al indexar una ruta que ya existe, o se sustituyen todos sus fragmentos anteriores por los nuevos, o el índice queda exactamente como estaba; nunca se mezclan fragmentos viejos y nuevos de la misma ruta ni se deja el archivo a medio indexar. La misma regla se aplica a cualquier rechazo.

## Requisitos funcionales
- RF-1: CUANDO se recibe el contenido de un archivo y su ruta, EL SISTEMA lo trocea en fragmentos citables, calcula la representación semántica de cada uno y los deja disponibles para la búsqueda de la spec 001, todo en la misma operación.
- RF-2: CUANDO el contenido se puede analizar como Python válido, EL SISTEMA crea un fragmento por cada definición de función, incluidas las declaradas como asíncronas, y por cada definición de clase de nivel superior, y también por cada clase definida directamente en el cuerpo de otra clase y por cada método definido directamente en el cuerpo de una clase. Las definiciones dentro de un bloque condicional, de excepción, de contexto u otro bloque de nivel de módulo cuentan como definiciones de nivel superior. Solo lo definido directamente en el cuerpo de una clase genera fragmento propio: los métodos y las clases que están dentro de un bloque condicional, de excepción o de contexto de esa clase quedan enteros dentro del fragmento de la clase exterior, igual que los métodos de una clase definida dentro de una función, que quedan dentro del fragmento de esa función. Las funciones y las clases definidas dentro de una función no generan fragmento propio: quedan incluidas en el fragmento de su función contenedora. El fragmento de una clase abarca toda la clase, métodos incluidos, y el de cada método queda dentro de ese rango; fuera de esa relación de contención, ningún fragmento de símbolo se solapa con otro.
- RF-3: SI una función o una clase tiene decoradores o comentarios pegados encima, ENTONCES EL SISTEMA los incluye dentro del rango de líneas de su fragmento: el fragmento empieza en la primera línea del primer decorador o en la primera línea del grupo de comentarios consecutivos pegado, si es anterior, y los decoradores de varias líneas se incluyen completos.
- RF-4: CUANDO el archivo contiene líneas que no están dentro de ninguna definición indexada, EL SISTEMA las indexa como un fragmento de tipo `module` por cada bloque contiguo, con un rango de líneas continuo, sin las líneas en blanco del principio y del final del bloque, y con las cadenas de documentación del módulo contadas como código de módulo.
- RF-5: EL SISTEMA incluye en cada fragmento la ruta recibida, el nombre de símbolo, la línea inicial, la línea final, el texto del fragmento y su tipo, y el tipo es exactamente uno de estos cuatro literales: `function`, `class`, `module` o `window`.
- RF-6: EL SISTEMA numera las líneas desde 1 con ambos extremos incluidos, cuenta como salto de línea solo `\n`, `\r\n` y `\r`, y hace que el texto de cada fragmento sea la subcadena exacta desde el inicio de su primera línea hasta el final de su última línea, sin el separador que termina esa última línea y sin ningún otro recorte, de modo que abrir el archivo por esas líneas muestre exactamente lo citado; cuando esa última línea está vacía, el texto conserva el separador que la precede y termina en salto de línea, sin recortarla ni ajustar el rango.
- RF-7: EL SISTEMA garantiza que toda línea con código del archivo, entendida como línea no vacía que no contiene solo un comentario, pertenece al menos a un fragmento; ninguna parte analizable del archivo queda fuera del índice.
- RF-8: SI el contenido no se puede analizar, sea por sintaxis inválida, indentación inválida, prosa o código de otro lenguaje, ENTONCES EL SISTEMA no aborta ni rechaza la indexación por ese motivo: lo trocea en ventanas de 60 líneas sin solape, marca esos fragmentos con el tipo `window` y los numera `window#1`, `window#2` y siguientes.
- RF-9: CUANDO la indexación cae a ventanas de líneas, EL SISTEMA conserva en cada fragmento la ruta, el rango de líneas, el texto completo y el nombre de ventana, de modo que se puedan citar igual que los demás, incluida la última ventana cuando tiene menos de 60 líneas o cuando su última línea está vacía.
- RF-10: CUANDO termina la indexación con éxito, EL SISTEMA informa del resultado en español tanto si el archivo se troceó por símbolos como si se troceó por ventanas; los datos de ese mensaje se definen en RF-24.
- RF-11: EL SISTEMA calcula la representación semántica de cada fragmento en local, a partir del texto exacto del fragmento sin recortarlo ni alterarlo, y la normaliza a longitud 1 con una tolerancia de `|norma − 1| ≤ 1e-5`, para que la comparación de la spec 001 funcione sin cambios.
- RF-12: CUANDO termina la indexación, EL SISTEMA deja los fragmentos disponibles para la búsqueda en la misma sesión, sin reiniciar el servicio y sin volver a cargar nada.
- RF-13: SI el contenido está vacío o solo contiene espacios en blanco, ENTONCES EL SISTEMA no indexa el contenido nuevo y lo indica en español; la conservación de la versión anterior de esa ruta, si existía, se rige por RF-25. Esta comprobación se hace antes que cualquier otra, incluida la del tamaño y la del tope de fragmentos.
- RF-14: SI el contenido ocupa más de 1.048.576 bytes en UTF-8, ENTONCES EL SISTEMA no lo indexa y lo indica en español con el límite permitido (1 MiB) y el tamaño recibido en bytes. Esta comprobación se hace después de la de contenido vacío y antes de la del tope de fragmentos.
- RF-15: CUANDO se indexa un archivo cuya ruta no estaba en el índice, EL SISTEMA conserva los fragmentos ya indexados de otras rutas y añade los nuevos; indexar no vacía el índice.
- RF-16: CUANDO dos archivos distintos definen el mismo nombre de símbolo, EL SISTEMA los indexa por separado y cada fragmento conserva su propia ruta.
- RF-17: MIENTRAS el contenido y la ruta no cambien, indexar dos veces el mismo archivo produce los mismos fragmentos y deja el índice igual que si se hubiera indexado una sola vez. Los fragmentos de un archivo se ordenan por línea inicial ascendente; a igual línea inicial, primero el que termina más abajo, de modo que el contenedor precede a su contenido; y si persiste el empate, por nombre de símbolo en orden alfabético.
- RF-18: CUANDO se indexa un archivo cuya ruta ya está en el índice, EL SISTEMA sustituye todos los fragmentos anteriores de esa ruta por los nuevos, de modo que nunca coexistan fragmentos viejos y nuevos de la misma ruta y una búsqueda no devuelva dos veces el mismo fragmento; se mantiene la deduplicación por ruta y rango de líneas de la spec 001.
- RF-19: SI la representación semántica de algún fragmento no se puede calcular, ENTONCES EL SISTEMA rechaza la indexación completa de ese archivo, lo indica en español y no altera el índice; la conservación de la versión anterior se rige por RF-25 y la forma atómica del reemplazo, por RF-22.
- RF-20: CUANDO un bloque contiguo de módulo supera 120 líneas, EL SISTEMA lo parte en trozos contiguos de hasta 120 líneas, todos de tipo `module`, con los nombres `module#N` correlativos en todo el archivo, sin reiniciar la numeración al pasar a otro bloque partido.
- RF-21: SI el troceado de un archivo produciría más de 1.000 fragmentos, ENTONCES EL SISTEMA no lo indexa y lo indica en español con el tope permitido y la cantidad que habría producido. Esta comprobación se hace después de la del tamaño y antes de calcular ninguna representación semántica.
- RF-22: CUANDO se indexa una ruta que ya existía y el proceso no llega a terminar, EL SISTEMA aplica el reemplazo de forma atómica: no deja la ruta a medio actualizar y mantiene disponibles los fragmentos anteriores hasta que la nueva versión esté completa.
- RF-23: EL SISTEMA asigna el nombre de símbolo de cada fragmento según este esquema: nombre simple para funciones y clases de nivel superior; nombre de la clase más el del método, separados por un punto, para cada método definido directamente en el cuerpo de una clase; nombre cualificado de la clase contenedora más el propio, separados por un punto, para cada clase definida directamente en el cuerpo de otra clase, y nombre cualificado de su clase más el del método para los métodos de esa clase anidada, que solo se generan cuando la clase anidada genera fragmento propio; `module` para un bloque de módulo sin partir, compartido por todos los bloques sin partir del archivo y distinguible por el rango de líneas; `module#N` para cada trozo de un bloque partido, numerado desde 1 en orden de aparición y de forma correlativa en todo el archivo; `window#N` para cada ventana, numerada desde 1 en orden de aparición. Las definiciones que no generan fragmento propio, como los métodos y las clases dentro de bloques condicionales de una clase o las clases contenidas en funciones, no reciben nombre propio. No se añade ningún campo nuevo al fragmento para esto.
- RF-24: CUANDO la indexación termina con éxito, EL SISTEMA incluye en el mensaje en español el número de fragmentos de ese archivo, el número total de fragmentos del índice contado después del reemplazo y, por tanto, incluidos los del archivo, y si el archivo se troceó por ventanas en lugar de por símbolos.
- RF-25: SI la indexación de una ruta se rechaza por contenido vacío, por superar el tamaño permitido, por superar el tope de fragmentos o por un fallo al calcular una representación semántica, ENTONCES EL SISTEMA deja intacta la versión anterior de esa ruta si ya estaba indexada, y no añade nada si no lo estaba.
- RF-26: EL SISTEMA no aplica tamaño mínimo a los fragmentos: un bloque de módulo de una sola línea se indexa como fragmento propio, con su nombre de símbolo, y no se descarta ni se fusiona con otro.
- RF-27: EL SISTEMA fija el final del rango de una función en la línea de su última instrucción y el de una clase en la última línea de su cuerpo, sin incluir las líneas en blanco ni los comentarios posteriores que ya no forman parte del símbolo; el inicio es el primer decorador o el primer comentario del grupo pegado, según RF-3.

## Requisitos no funcionales
- RNF-1: La indexación no ejecuta, importa ni evalúa el contenido recibido; solo lo trata como texto, aunque el archivo parezca inofensivo.
- RNF-2: Durante la indexación, el contenido y los fragmentos no se escriben en disco ni se envían a servicios externos, y la representación semántica se calcula en local. Esta restricción se refiere solo a la indexación; el envío de fragmentos al modelo de lenguaje en el chat corresponde a otra capacidad y se rige por la constitución.
- RNF-3: Los mensajes están en español y son comprensibles para alguien que empieza, sin jerga técnica. Contienen como mínimo: en el éxito, el número de fragmentos del archivo, el total del índice después del reemplazo y el aviso de que el archivo se troceó por ventanas cuando sea el caso (RF-24); en el rechazo por tamaño, el límite de 1 MiB (1.048.576 bytes) y el tamaño recibido (RF-14); en el rechazo por tope de fragmentos, el límite de 1.000 y la cantidad que habría producido (RF-21); en el rechazo por contenido vacío, que el archivo está vacío (RF-13); y en el fallo al calcular una representación, el mensaje de "archivo no indexable" (RF-19).
- RNF-4: Trocear un archivo de 1.000 líneas, compuesto por funciones cortas de tamaño similar de unas 10 líneas cada una, tarda menos de 1 segundo, sin contar la carga del modelo de representación semántica ni el cálculo de las representaciones.
- RNF-5: Los fragmentos que produce la indexación son consumibles por la búsqueda de la spec 001 sin modificar su contrato, su umbral ni su número máximo de resultados.
- RNF-6: La ruta que se guarda en el fragmento es exactamente la ruta recibida, sin resolverla ni reescribirla, para que la cita coincida con lo que la persona entregó.
- RNF-7: El texto que se guarda y se cita de cada fragmento es el texto completo definido para el fragmento, aunque el modelo de representación haya truncado ese texto por su cuenta al calcular su vector.

## Casos límite
- Contenido de exactamente 1.048.576 bytes en UTF-8: se acepta. De 1.048.577 bytes en UTF-8: se rechaza con el mensaje correspondiente.
- Contenido de 600.000 caracteres que ocupa más de 1.048.576 bytes en UTF-8: se rechaza por tamaño, porque el límite se mide en bytes y no en caracteres.
- Troceado que produce exactamente 1.000 fragmentos: se acepta. Que produciría 1.001: se rechaza sin calcular ninguna representación semántica.
- Contenido vacío de 1.100.000 bytes en UTF-8 formado por espacios: se rechaza como vacío, no como demasiado grande.
- Archivo vacío, con solo espacios o con solo saltos de línea: no se indexa nada y se informa; no se considera un error del sistema.
- Archivo de una sola línea con una asignación: un fragmento de módulo de una línea.
- Archivo que solo contiene código de módulo, sin funciones ni clases: se indexa igualmente y las preguntas sobre configuración encuentran un fragmento.
- Archivo que solo contiene una cadena de documentación de módulo: la cadena cuenta como código de módulo y produce un fragmento.
- Archivo que solo contiene comentarios: el bloque de módulo está formado por esas líneas y produce un fragmento; ninguna línea cuenta como línea con código para RF-7.
- Archivo con una única función y ningún código de módulo: produce un solo fragmento.
- Clase sin métodos: produce un solo fragmento, el de la clase.
- Archivo con un bloque de arranque condicional: sus líneas forman parte del bloque contiguo de módulo; si dentro hay una función o una clase, esa definición genera su propio fragmento y corta el bloque.
- Bloque contiguo de módulo de una sola línea, como un `import` suelto: es un fragmento válido de una línea llamado `module`; no se descarta ni se fusiona con otro bloque.
- Bloque contiguo de módulo de exactamente 120 líneas: un solo fragmento llamado `module`. De 121 líneas: dos fragmentos contiguos, uno de 120 líneas llamado `module#1` y otro de 1 línea llamado `module#2`.
- Dos bloques de módulo partidos en el mismo archivo: la numeración de sus trozos continúa en todo el archivo en lugar de reiniciarse, de modo que si el primer bloque dejó dos trozos, el siguiente empieza en `module#3`.
- Dos bloques de módulo sin partir en el mismo archivo: ambos se llaman `module` y se distinguen por su rango de líneas; no es un error.
- Varios comentarios consecutivos pegados encima de una función o clase, sin línea en blanco: el fragmento empieza en el primero del grupo. Un comentario separado por una línea en blanco de la definición: se queda en el bloque de módulo.
- Función o clase con un decorador: el fragmento empieza en la línea del decorador. Con un decorador de varias líneas: empieza en la primera línea del primer decorador.
- Texto del fragmento: es la subcadena exacta desde el inicio de su primera línea hasta el final de su última línea, sin el separador que termina esa última línea; no se eliminan espacios ni comentarios intermedios. Si la última línea está vacía, el texto conserva el separador anterior y termina en salto de línea.
- Función con líneas en blanco y comentarios después de su última instrucción: el rango termina en la línea de esa última instrucción y no incluye lo que sigue. Clase: el rango termina en la última línea de su cuerpo.
- Función de 2.000 líneas: se indexa entera, sin partirla, aunque el fragmento sea grande y el modelo trunce su representación.
- Función con una función anidada: la anidada no genera fragmento propio; su texto queda dentro del fragmento de la función contenedora.
- Clase con métodos: la clase produce un fragmento que abarca toda la clase y cada método definido directamente en su cuerpo produce el suyo, contenido en el rango de la clase y llamado `Clase.metodo`; los métodos no se solapan entre sí.
- Clase con un método dentro de un bloque condicional, de excepción o de contexto dentro de la clase: ese método no genera fragmento propio y queda dentro del fragmento de la clase.
- Clase definida dentro de una función: no genera fragmento propio, y sus métodos tampoco; todo queda dentro del fragmento de la función.
- Clase definida directamente en el cuerpo de otra clase: genera fragmento propio llamado `Outer.Inner`, y sus métodos generan el suyo llamado `Outer.Inner.metodo`.
- Clase definida dentro de un bloque condicional, de excepción o de contexto de otra clase: no genera fragmento propio, ni sus métodos; queda entera dentro del fragmento de la clase exterior.
- Dos fragmentos con la misma línea inicial: se ordena primero el que termina más abajo, y si también empatan, por nombre de símbolo en orden alfabético.
- Función declarada como asíncrona: produce un fragmento de tipo `function` igual que una función normal.
- Archivo con error de sintaxis, con indentación inválida, con texto en prosa o con código de otro lenguaje: se indexa por ventanas de 60 líneas y se informa de que el troceado es aproximado; no se rechaza por parecer otro lenguaje.
- Archivo no analizable de exactamente 60 líneas: una sola ventana, `window#1`. De 61 líneas: dos ventanas, una de 60 y otra de 1 línea, `window#1` y `window#2`.
- Archivo no analizable de 61 líneas en el que la línea 60 está vacía: la primera ventana abarca las líneas 1 a 60 y su texto conserva el separador anterior, por lo que termina en salto de línea; la segunda ventana es la línea 61. El rango y el texto cuadran sin recortar la línea vacía.
- Archivo con finales de línea de Windows o antiguos de Mac: la numeración de líneas sigue coincidiendo con lo que se ve al abrir el archivo.
- Archivo con un carácter de control como `\f` dentro de una línea: no abre una línea nueva y la numeración no cambia.
- Archivo con líneas muy largas o muy cortas: los fragmentos se citan igual; la línea larga no se recorta ni se parte por caracteres.
- Archivo malicioso, con instrucciones para borrar archivos o abrir conexiones: se indexa como texto y su código no se ejecuta.
- Mismo nombre de símbolo en dos archivos: dos fragmentos distintos, cada uno con su ruta.
- Re-subida de la misma ruta con contenido válido: los fragmentos anteriores de esa ruta desaparecen y quedan solo los nuevos.
- Archivo que antes producía 3 fragmentos y ahora produce 7: tras la re-subida quedan 7 de esa ruta, no 10. Al contrario, de 7 a 3: quedan 3, no 7.
- Re-subida de la misma ruta con contenido que falla al calcular alguna representación semántica: el índice conserva los fragmentos de la versión anterior, se avisa en español y no queda nada a medio actualizar.
- Re-subida de la misma ruta con contenido vacío, demasiado grande o con demasiados fragmentos: el índice conserva la versión anterior y se informa del motivo del rechazo.
- Archivo que se indexa después de otros: los fragmentos de las demás rutas siguen disponibles y buscables.

## Fuera de alcance
- Leer el archivo desde el disco, recibirlo por HTTP, validar su extensión o su lenguaje y gestionar los errores de lectura: corresponden a la capa de subida, que tendrá su propia spec. Esta capacidad recibe el contenido ya leído y su ruta, y no rechaza nada por parecer otro lenguaje.
- Indexar JavaScript o cualquier lenguaje que no sea Python con un troceado por símbolos: esos contenidos se indexan solo por ventanas.
- Persistir el índice: vive en memoria y se pierde al reiniciar el servicio, como ya es esperado en esta versión.
- Buscar, aplicar el umbral, ordenar o limitar resultados: es la spec 001.
- Borrar explícitamente un archivo del índice por petición de la persona, sin volver a indexarlo: la única eliminación de fragmentos prevista es la sustitución al re-indexar la misma ruta.
- Detectar cambios en el archivo en disco y reindexar automáticamente.
- Detectar duplicados por contenido idéntico en rutas distintas.
- Cambiar el modelo de representación semántica o recalibrar el umbral.
- Corregir, formatear o completar el código indexado.
- Interfaz web de subida, chat y exposición por MCP.

## Criterios de finalización
- Cada requisito funcional y no funcional tiene una prueba automatizada que pasa sin red, sin claves y sin descargar el modelo.
- Todos los casos límite anteriores están cubiertos por pruebas.
- Está verificado de forma automatizada que la indexación no ejecuta ni importa el contenido recibido, no abre conexiones de red y no crea archivos en disco, usando un archivo con código malicioso como entrada.
- Está verificado que el texto de cada fragmento es la subcadena exacta de sus líneas, sin el separador final, que toda línea con código queda cubierta y que la numeración solo cuenta `\n`, `\r\n` y `\r`, sobre varios archivos de ejemplo, incluido código real del proyecto.
- Está verificado que una ventana cuya última línea está vacía conserva el separador anterior, termina en salto de línea y no recorta la línea vacía ni ajusta el rango.
- Está verificado el final del rango de una función en su última instrucción y el de una clase en la última línea de su cuerpo, sin líneas en blanco ni comentarios posteriores.
- Está verificado el esquema de nombres de símbolo: nombre simple en el nivel superior, `Clase.metodo` en métodos directos, nombre cualificado en clases anidadas y sus métodos, `module` y `module#N` con numeración global por archivo, y `window#N` en ventanas.
- Está verificado que los métodos de clases contenidas en funciones y las clases y métodos contenidos en bloques condicionales dentro de una clase no generan fragmento propio.
- Está verificado el orden de los fragmentos de un archivo: línea inicial ascendente, después el que termina más abajo y, por último, nombre de símbolo alfabético.
- Está verificado el recorrido completo: indexar un archivo y después buscar una pregunta cuya respuesta esté en él devuelve un fragmento con la ruta, el símbolo y las líneas correctas.
- Está verificado que el mensaje de éxito incluye los fragmentos de ese archivo, el total del índice contado después del reemplazo y el aviso de troceado por ventanas cuando corresponda.
- Está verificado que indexar dos veces el mismo archivo no altera los fragmentos ni el orden, y que la ruta sigue teniendo el mismo número de fragmentos que tendría con una sola indexación.
- Está verificado el reemplazo atómico: con un fallo provocado al calcular una representación semántica a mitad de la re-subida, la ruta conserva exactamente los fragmentos de la versión anterior, la búsqueda sigue encontrándolos y se informa en español.
- Está verificado que los cuatro motivos de rechazo (vacío, tamaño, tope de fragmentos y fallo de representación) dejan intacta la versión anterior de la ruta y no añaden nada si la ruta era nueva.
- Está verificado el tope de 1.000 fragmentos: un archivo que produce 1.000 se indexa y uno que produciría 1.001 se rechaza sin añadir nada al índice.
- Está verificado que el límite de tamaño se mide en bytes UTF-8: un contenido de 1.048.576 bytes se acepta y uno de 1.048.577 bytes se rechaza.
- Está verificado que no hay tamaño mínimo: un bloque de módulo de una línea se indexa como fragmento propio y no se fusiona.
- Está verificado que la comprobación de vacío se aplica antes que la de tamaño y esta antes que la de tope de fragmentos.
- La spec pasa de borrador a aprobada antes de planificar la implementación.

## Dudas abiertas
Ninguna.
