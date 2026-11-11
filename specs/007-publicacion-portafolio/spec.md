# Spec 007 — Publicación y portafolio

Estado: implementada

## Contexto y objetivo

Las specs 001 a 006 dejan un producto que funciona en local: indexa archivos Python, responde preguntas con citas verificables, se usa por HTTP, por el navegador y como herramienta MCP. Sin embargo, hoy no se puede evaluar sin que alguien lo arranque a ciegas: el README es mínimo, no hay diagrama, no hay demo visual, no hay integración continua, `.gitignore` solo cubre tres patrones y `.env.example` tiene una sola línea. El directorio tampoco es todavía un repositorio git, así que no hay historial, ni remoto, ni workflow que valide los cambios. Esta spec no afirma que el proyecto ya sea público: define lo que falta para publicarlo como portafolio.

El objetivo es que el README permita a un recién llegado entender qué hace el proyecto y probarlo en cinco minutos, y que quien lo mantiene no pueda publicar una versión que no pase lint y pruebas, que prometa funciones inexistentes o que filtre una clave. La claridad de esa guía se verifica con una autoevaluación guiada del autor, no con una persona externa, porque no hay una disponible. Para lograrlo, esta spec define el contenido mínimo del README, un GIF de demostración del flujo real, un workflow de integración continua que se ejecuta sin claves ni descargas del modelo, una configuración de ejemplo sin secretos, un `.gitignore` completo, un `Dockerfile` que incluye el modelo en la imagen, la publicación en un repositorio público de GitHub con licencia MIT y badge de CI, y la decisión de qué carpetas y archivos de trabajo se publican y cuáles se excluyen.

Las decisiones de contenido y publicación están acordadas: el repositorio se llamará `codementor`, usará la rama principal `main` y vivirá en una cuenta personal de GitHub; el nombre de usuario u organización exacto y la URL real se fijan al publicar y no se inventan. Se publican `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` y `.agents/`, tras revisar secretos, tokens, datos personales innecesarios y rutas locales sensibles; el nombre de la titular en `LICENSE` y en esta spec y el identificador público de la cuenta en la URL y el badge son información permitida. El modelo de representaciones se descarga durante el build de Docker y queda dentro de la imagen. La verificación de comprensión es una autoevaluación guiada del autor, sin depender de una persona externa. La única información que no se puede fijar todavía es el usuario u organización de GitHub y, por tanto, la URL de clon y del badge; queda como pendiente de publicación, no como duda de la spec.

## Usuarios

- Persona que evalúa el proyecto para una contratación o una revisión técnica, que necesita entender en minutos qué hace y cómo está construido.
- Desarrollador que llega al repositorio por primera vez y quiere clonarlo, instalarlo y probarlo sin adivinar pasos.
- Persona sin clave de API que quiere comprobar una parte del producto sin depender de un servicio externo.
- Persona que no quiere preparar un entorno de Python y prefiere probar el proyecto con un contenedor local.
- Mantenedor del proyecto, que quiere que cada cambio se valide automáticamente y que el README no se desactualice.
- Responsable de seguridad o de privacidad, que necesita comprobar que no hay claves ni datos personales innecesarios en el repositorio.
- Contribuidor que quiere conocer las decisiones, los límites y el estado real del proyecto antes de proponer cambios.
- Autor del proyecto, que quiere que la planificación, las skills y la documentación de trabajo se vean en el repositorio público.

## Historias de usuario

- HU-1. Como persona que evalúa el proyecto, quiero entender qué hace, cómo está construido y qué decisiones lo sostienen, para decidir si merece la pena probarlo; la guía está escrita para un recién llegado y su claridad se valida con la autoevaluación guiada del autor.
- HU-2. Como desarrollador que llega por primera vez, quiero seguir una guía de inicio rápido con comandos copiables, para tener la aplicación funcionando siguiendo solo el README.
- HU-3. Como visitante sin clave de API, quiero saber de antemano qué puedo probar y qué no, para no confundir una limitación documentada con un fallo.
- HU-4. Como persona que no quiere instalar dependencias, quiero levantar el proyecto con un contenedor local, para probarlo sin preparar un entorno de Python.
- HU-5. Como mantenedor, quiero que cada cambio pase lint y pruebas en un entorno limpio y sin secretos, para no publicar una versión rota ni filtrar una clave.
- HU-6. Como responsable de seguridad, quiero que el repositorio no contenga `.env`, claves, datos personales innecesarios ni artefactos locales, para poder publicarlo sin riesgo.
- HU-7. Como revisor, quiero ver un GIF del flujo real con citas, para comprobar el resultado sin ejecutar el proyecto.
- HU-8. Como contribuidor, quiero conocer las decisiones, la estructura y los límites conocidos, para no proponer cambios que contradigan la arquitectura.
- HU-9. Como lector que vuelve meses después, quiero que el README distinga lo implementado de lo pendiente, para no tomar por terminado lo que aún no lo está.
- HU-10. Como revisor de portafolio, quiero ver la licencia MIT y el estado del CI, para saber que el proyecto es reutilizable y que se valida automáticamente.
- HU-11. Como autor del proyecto, quiero que `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` y `.agents/` se publiquen, para que el proceso de planificación y las skills SDD formen parte de lo que se muestra.

## Definiciones

- **Publicación**: poner el proyecto a disposición de terceros en un repositorio público de GitHub, con su documentación, su configuración de ejemplo, su validación automática, su licencia y su demo. No implica un despliegue en un servidor ni un dominio público.
- **Repositorio público**: repositorio de GitHub visible para cualquiera, en una cuenta personal, con el nombre `codementor`, la rama principal `main`, el workflow de CI, la licencia MIT y el badge de estado. La URL real se conoce al publicar.
- **Recién llegado**: persona sin contexto previo que solo dispone del repositorio, una máquina con Python 3.12 y conexión a internet para instalar dependencias.
- **Clon limpio**: copia del repositorio sin `.env`, sin entorno virtual, sin cachés ni artefactos generados por haber ejecutado el proyecto antes.
- **Camino de cinco minutos**: recorrido desde que el recién llegado abre el README hasta que la aplicación está levantada y ha subido un archivo `.py` correctamente. La respuesta con citas es el paso siguiente y requiere clave. Se mide con las dependencias ya instaladas y el modelo de representaciones ya descargado; la primera instalación y la primera descarga se documentan aparte con su tiempo real, porque pueden superar ese límite y el README no debe prometer lo contrario.
- **Demo visual**: un único GIF animado de 10 a 20 segundos que muestra el flujo real de la interfaz web, no un mockup ni una reconstrucción.
- **Integración continua (CI)**: ejecución automática de `ruff check .` y `pytest -q` en un entorno limpio cada vez que cambia el repositorio.
- **Repositorio de publicación**: repositorio git desde el que se distribuye el proyecto, con su rama principal, su historial y su remoto en GitHub.
- **Archivos auxiliares**: los archivos sueltos de la raíz `demo_sin_tokens.py` y `diagnostico.py`, que no forman parte del producto ni de su documentación y quedan fuera del repositorio público.
- **Imagen de contenedor**: imagen local construida desde el `Dockerfile`, que incluye el modelo de representaciones descargado durante el build, se ejecuta en la máquina de quien prueba el proyecto y no se publica en ningún registro.
- **Notas de seguridad**: sección del README que explica qué datos se manejan, qué se envía a servicios externos y qué garantías ofrece el producto.
- **Sin red en las pruebas**: el paso de pruebas no descarga el modelo ni consulta servicios externos; la instalación de dependencias desde PyPI sí puede usar la red del runner.
- **Autoevaluación guiada**: verificación en la que el autor sigue el README en un clon limpio con cronómetro y una checklist de pasos, anota dónde se atascó y corrige; no depende de una persona externa.
- **Pendiente de publicación**: dato que solo se puede fijar al publicar el repositorio, como el usuario u organización de GitHub y la URL real del clon y del badge. No es una duda de la spec ni bloquea su aprobación.
- **Identificador público de la cuenta**: nombre de usuario u organización de GitHub que aparece en la URL del repositorio y en el badge. Es información pública permitida y no cuenta como dato personal innecesario.
- **Datos personales innecesarios**: información de una persona que no es necesaria para que el proyecto funcione ni para acreditar la autoría, como correos, teléfonos, direcciones, nombres de usuario de la máquina del autor o rutas locales absolutas. El nombre de la titular en `LICENSE` y en la spec que define la licencia no se considera innecesario.
- **Titular de la licencia**: persona a cuyo nombre se emite la licencia MIT. En esta versión, María Camila, con año de publicación 2026; su nombre aparece en `LICENSE` y en esta spec por decisión del usuario.

## Requisitos funcionales

### README y contenido

- RF-1: El README contiene, en este orden y con títulos visibles, estas secciones: qué es el proyecto y qué problema resuelve en tres frases como máximo; funcionalidades principales; diagrama de arquitectura; requisitos previos; inicio rápido; ejemplos de uso; demo con el GIF cuando exista; uso con Docker; decisiones y porqués; estructura del proyecto; stack; límites conocidos; pruebas y lint; seguridad; y licencia MIT con el badge del CI cuando el repositorio esté publicado; antes de publicar, la sección declara el estado del CI sin mostrar un badge inventado. Cada sección se verifica por separado y el requisito no se cumple hasta que todas pasan.
- RF-2: El README incluye un diagrama de arquitectura que muestra las capas reales del sistema y la vía de las herramientas MCP sin pasar por HTTP. El diagrama se entiende sin leer el código, coincide con la implementación publicada y se actualiza si la arquitectura cambia; puede ser texto, Mermaid o una imagen versionada con texto alternativo.
- RF-3: El README contiene una sección de inicio rápido que, seguida al pie de la letra en un clon limpio, deja la aplicación accesible en la dirección local documentada. La sección indica la versión de Python, los comandos de creación y activación del entorno virtual para Windows y para Linux/macOS, la instalación de dependencias con `requirements.txt`, la copia de `.env.example` a `.env`, el arranque con `uvicorn app.main:app` y la comprobación de `GET /health` con el resultado esperado; no supera diez comandos ni supone pasos que no estén escritos. Advierte de que, en la primera ejecución local sin el modelo descargado, el calentamiento ocurre en el arranque y la comprobación de salud puede tardar.
- RF-4: El README distingue explícitamente qué se puede probar sin clave de API (salud del servicio, subida de un archivo `.py`, uso del contenedor y búsqueda por MCP) y qué requiere clave (el chat con respuestas de Claude). Indica el mensaje que aparece si se intenta chatear sin clave y remite a la sección de configuración para añadirla; no presenta el chat sin clave como un fallo del producto.
- RF-5: El README incluye al menos un ejemplo copiable para cada vía de uso: API HTTP (`GET /health`, subida con `POST /upload` y chat con `POST /chat`; el ejemplo puede incluir `history: []` como convención, pero indica que es opcional y que si se omite se usa un historial vacío), interfaz web (abrir la página, subir un archivo `.py` y hacer una pregunta que devuelva una cita) y MCP (`python -m app.mcp_server` con el inspector oficial, indexado de un archivo y búsqueda posterior, con el resultado esperado). Los ejemplos usan archivos y rutas que existen en el repositorio y respetan las reglas de las specs 004 y 006.
- RF-6: El README documenta al menos seis decisiones de diseño, cada una con la decisión, el motivo y la alternativa descartada. Como mínimo cubre: la separación en capas, el troceado por función y clase con plan B por ventanas, la búsqueda con representaciones normalizadas y similitud coseno, las citas construidas desde los resultados de la búsqueda, el índice en memoria y la carga diferida del modelo. Una revisión cuenta las decisiones y comprueba que cada una tiene motivo y alternativa.
- RF-7: El README incluye la estructura real del proyecto, con las carpetas y los archivos principales y una línea de responsabilidad para cada uno, y distingue lo que es producto, lo que son pruebas, lo que es documentación de specs, lo que es configuración de trabajo, lo que son archivos raíz publicados y lo que son artefactos de publicación.
- RF-8: El README declara el stack con la versión de Python, las dependencias principales y su papel, y el modelo de representaciones utilizado, con un enlace a su ficha oficial. No enumera dependencias que no estén fijadas en `requirements.txt` ni versiones distintas de las fijadas.
- RF-9: El README enumera los límites conocidos y su consecuencia práctica, como mínimo: el índice vive en memoria y se pierde al reiniciar; el índice del servidor MCP es propio de cada proceso; solo se indexan archivos `.py`; el chat requiere clave y envía la pregunta, el historial y los fragmentos recuperados a Claude; la clave solo hace falta para el chat y no para arrancar; la primera ejecución local descarga el modelo y puede tardar; en Docker el modelo ya está en la imagen; no hay autenticación, TLS ni persistencia; y no se indexa JavaScript.
- RF-10: El README y el GIF solo muestran comandos, rutas, funciones, herramientas, badges, imágenes y funcionalidades que existen y funcionan en la versión publicada. Las ideas futuras se agrupan en una sección marcada como roadmap o pendiente y nunca se presentan como disponibles. Una revisión cruzada contra el repositorio comprueba cada referencia y una revisión visual práctica comprueba que las acciones y citas del GIF son reales.

### Demostración visual

- RF-11: El README incluye un único GIF animado de 10 a 20 segundos de la interfaz web que muestra, en este orden, la subida de un archivo, una pregunta y la respuesta con citas visibles. El proyecto guarda el GIF dentro del repositorio, lo referencia con una ruta relativa y consigue que se vea al abrir el README en el repositorio remoto; el GIF lleva texto alternativo en español que describe lo que se ve. No se añaden capturas estáticas adicionales.
- RF-12: El proyecto mantiene el GIF alineado con la versión publicada: la interfaz, los textos y las citas que aparecen coinciden con el producto actual. Si deja de representar la versión publicada, se actualiza o se retira antes de cerrar la spec.
- RF-13: El proyecto no publica un GIF con claves de API, tokens, datos personales innecesarios, nombres de usuario de la máquina del autor, rutas locales absolutas ni código que no sea del proyecto o un ejemplo inocuo. Si aparece una ruta o un nombre sensible, se recorta, se sustituye por un ejemplo o se vuelve a generar.
- RF-14: El proyecto publica un GIF que se entiende sin audio y sin una explicación externa, muestra una acción completa y no depende de un archivo que no esté en el repositorio. Si al implementar no hay una clave disponible para generar la respuesta con citas, la ausencia del GIF se documenta como pendiente, no se publica una imagen falsa y el README no enlaza un archivo inexistente.

### Integración continua

- RF-15: CUANDO se empuja un cambio al repositorio o se abre o actualiza un pull request, El workflow de integración continua se ejecuta y realiza exactamente `ruff check .` y `pytest -q` sobre el código del repositorio. Las dos comprobaciones son obligatorias para considerar el cambio validado.
- RF-16: El workflow se ejecuta en un clon limpio, sin `.env`, sin claves de API, sin secretos del repositorio, sin servicios externos, sin base de datos, sin navegador y sin un servidor levantado. No define `ANTHROPIC_API_KEY` ni ninguna otra credencial, y funciona igual en un pull request de una bifurcación.
- RF-17: El workflow usa Python 3.12, instala las dependencias fijadas en `requirements.txt` y no instala paquetes adicionales para ejecutar las comprobaciones obligatorias.
- RF-18: MIENTRAS se ejecuta el paso de pruebas, El workflow no descarga el modelo de representaciones ni consulta servicios externos. La prueba opcional que necesita el modelo real permanece omitida por defecto y el registro del workflow no muestra descargas del modelo.
- RF-19: SI `ruff check .` o `pytest -q` falla, ENTONCES El workflow termina con estado de fallo y el cambio no se considera validado. Un fallo de lint o de una prueba no se puede compensar con el éxito de la otra comprobación.
- RF-20: El workflow no oculta ni relaja fallos: no usa `continue-on-error`, no encadena comandos con `|| true`, no excluye pruebas de forma selectiva y no usa opciones que conviertan un fallo en éxito. Tampoco reduce la suite a un subconjunto para ahorrar tiempo.
- RF-21: El workflow declara permisos mínimos de solo lectura sobre el contenido del repositorio, no usa el evento `pull_request_target` y no expone secretos a código de pull requests de bifurcaciones.
- RF-22: El workflow ejecuta los mismos comandos que el README documenta para la validación local, con la misma versión menor de Python y las mismas dependencias fijadas, de modo que un resultado verde en local sea reproducible en el runner salvo diferencias del entorno.
- RF-23: El workflow ejecuta solo `ruff check .` y `pytest -q`; no ejecuta `ruff format --check`, comprobaciones de frontend ni herramientas adicionales. El nombre y la estructura exacta del archivo de workflow se fijan en el plan, pero su ubicación es `.github/workflows/`.

### Configuración y seguridad

- RF-24: `.env.example` enumera todas las variables que la aplicación lee para funcionar, con valores vacíos o de ejemplo que no son credenciales válidas y con un comentario en español que explica para qué sirve cada una. Incluye `ANTHROPIC_API_KEY` vacía y, comentada, `CODEMENTOR_REAL_MODEL`, que habilita la prueba opcional con el modelo real, para que nadie la active por accidente. Copiar el archivo a `.env` produce una configuración válida que arranca la aplicación y deja el chat sin clave en el comportamiento documentado.
- RF-25: El proyecto mantiene `.env` fuera del repositorio: el archivo está ignorado, no aparece en `git status`, no se rastrea con `git ls-files` y no existe en el historial publicado. `.env.example` sí se rastrea y es el único archivo de ese tipo que se publica.
- RF-26: `.gitignore` cubre, como mínimo: `venv/` y otros entornos virtuales; `__pycache__/`, archivos compilados y cachés de pytest y ruff; cobertura y directorios de construcción; `.env` y sus variantes locales, manteniendo `.env.example`; `.vscode/`, `demo_sin_tokens.py` y `diagnostico.py`; artefactos de sistemas operativos y editores; registros; dependencias locales de herramientas como `node_modules`; y cualquier archivo de base de datos local, incluidas las de una futura persistencia. Se comprueba creando archivos y carpetas de prueba y verificando que git los ignora.
- RF-27: El proyecto no contiene claves, tokens ni credenciales en los archivos rastreados ni en su historial. Una búsqueda de patrones habituales de clave, incluida la cadena de una clave de Anthropic, no devuelve coincidencias en el contenido publicado; si alguna apareciera, se retira y se rota antes de publicar. La misma revisión se aplica a `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` y `.agents/` antes de publicarlos.
- RF-28: El README incluye notas de seguridad que explican, como mínimo: que la clave vive solo en una variable de entorno y nunca en el código ni en el repositorio; que `.env` está ignorado; que el `Dockerfile` no hornea la clave y que se pasa en tiempo de ejecución; que el código subido nunca se ejecuta, importa ni evalúa; que la aplicación no lo guarda en disco, salvo el archivo temporal efímero que el framework puede crear para subidas grandes y que se borra al terminar la petición; que a Claude solo se envían la pregunta, el historial y los fragmentos recuperados; que el índice vive en memoria y se pierde al reiniciar; y que no hay autenticación ni TLS, por lo que no debe exponerse directamente a internet.
- RF-29: El README explica el comportamiento sin clave: la aplicación arranca, la salud responde, la subida y las herramientas MCP funcionan, el contenedor arranca y el chat devuelve el error documentado. La explicación coincide con el comportamiento real de las specs 004 a 006.
- RF-30: El README advierte de que en local la primera ejecución descarga el modelo de representaciones, que el calentamiento ocurre en el arranque y que `GET /health` puede tardar hasta que termina; no promete que `/health` responda al instante en esa primera ejecución si el modelo no está descargado. También explica que, en Docker, el modelo se descarga en el build y no en el arranque.
- RF-31: El README y `.env.example` indican cómo configurar la clave sin escribirla en un archivo rastreado: copiar el ejemplo, completar `.env` en local y no hacer commit de ese archivo. Para Docker, el ejemplo usa `docker run -e ANTHROPIC_API_KEY=...` con un marcador, nunca una clave real. No muestran una clave real en ningún comando.

### Publicación y estado del repositorio

- RF-32: El proyecto se entrega en un repositorio git inicializado, con `.gitignore` activo antes del primer commit y con un primer commit que no contiene `.env`, entorno virtual, cachés, archivos auxiliares, `.vscode/` ni artefactos generados. El historial no contiene secretos.
- RF-33: El proyecto se publica en un repositorio público de GitHub en una cuenta personal, con nombre `codementor` y rama principal `main`. El repositorio contiene el README, el workflow en `.github/workflows/`, `.env.example`, `.gitignore`, el `Dockerfile`, `.dockerignore`, la licencia MIT, `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` y `.agents/`, y el GIF cuando exista; si no existe por falta de clave, el README lo declara pendiente. No contiene `.env`, entorno virtual, cachés, bases de datos, `demo_sin_tokens.py`, `diagnostico.py` ni `.vscode/`. La secuencia es: repositorio local con `.gitignore` y primer commit, publicación en GitHub y, por último, URL de clon y badge con la URL real. La URL de clon se añade al README cuando el repositorio esté publicado; antes no se muestra una URL inventada.
- RF-34: El proyecto incluye un archivo de licencia MIT con año de publicación 2026 y titular María Camila, y el README declara la licencia MIT. El badge de estado del workflow se añade al publicar con la URL real del repositorio; antes de esa publicación, el README no muestra un badge con una URL inventada. Una vez publicado, el badge apunta a la rama `main` y al workflow reales y refleja la última ejecución.
- RF-35: El README declara el estado real del proyecto: las specs 001 a 006 implementadas, el estado del GIF y de la prueba manual con clave real como pendiente heredado si no se han podido completar, el índice sin persistencia y las limitaciones de la sección de límites. No presenta el proyecto como terminado, en producción o con funciones que aún no existen.
- RF-36: El proyecto excluye `demo_sin_tokens.py`, `diagnostico.py` y `.vscode/`: no se publican, no se referencian desde el README y se añaden a `.gitignore`. Su contenido no forma parte de la entrega.
- RF-37: El proyecto publica `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` y `.agents/` porque contienen la planificación, los agentes, las skills SDD y la documentación del proyecto. Antes de publicarlos se revisa que no contengan claves, tokens, datos personales innecesarios ni rutas locales sensibles; si se encuentra una credencial, se elimina o se sustituye y se rota. Se permiten de forma explícita el nombre de la titular de la licencia en `LICENSE` y en la spec que la define, y el identificador público de la cuenta de GitHub en la URL de clon y en el badge; ninguno de los dos cuenta como dato personal innecesario. No se publican dependencias locales como `node_modules` ni archivos generados por las herramientas. La revisión incluye corregir, antes de publicar, la «v» suelta al final de la línea 13 de `docs/constitution.md`; esta spec no corrige el archivo, solo fija la tarea de publicación.

### Empaquetado con Docker

- RF-38: El proyecto incluye un `Dockerfile` que construye una imagen local con Python 3.12 y las dependencias fijadas en `requirements.txt`, descarga el modelo de representaciones durante el build y lo deja dentro de la imagen, arranca la API escuchando en `0.0.0.0:8000` y sirve el frontend. La imagen se construye y se ejecuta solo en local; no se publica en Docker Hub, GHCR ni ningún otro registro, y no se incluye `docker-compose`.
- RF-39: El proyecto construye una imagen que no contiene la clave: no copia `.env`, no la declara en tiempo de construcción y no la deja en ninguna capa. `ANTHROPIC_API_KEY` se pasa al ejecutar con `docker run -e`; sin ella el contenedor arranca y sirve la salud, la subida y el frontend, y el chat devuelve el error documentado; con ella el chat funciona. Como el modelo ya está en la imagen, `docker run` no lo descarga y `GET /health` responde tras el arranque y el calentamiento, sin espera de descarga en runtime.
- RF-40: El proyecto incluye un `.dockerignore` que excluye de forma fija: `.env` y variantes; `venv/`; `__pycache__/`; `.pytest_cache/`; `.ruff_cache/`; `.git/`; `.github/`; `.vscode/`; `.opencode/`; `.agents/`; `node_modules/`; `docs/`; `specs/`; `tests/`; `demo_sin_tokens.py`; `diagnostico.py`; bases de datos; logs; GIF y artefactos de documentación; `README.md`; `AGENTS.md`; `MEMORY.md`; y `opencode.json`. Conserva solo lo necesario en runtime: `app/`, `static/` y `requirements.txt`. Se verifica el tamaño del contexto de construcción y que la imagen arranca.
- RF-41: El README documenta cómo construir y ejecutar la imagen, que el build necesita internet para descargar el modelo, que la imagen resultante es más grande y su tamaño real medido, que `docker run` no descarga el modelo y que la clave se pasa en tiempo de ejecución. El ejemplo de ejecución usa `docker run -p 8000:8000 -e ANTHROPIC_API_KEY=...` con un marcador, nunca una clave real. También indica que la imagen no se publica en ningún registro y no incluye comandos de `docker compose` ni de `docker push`.
- RF-42: El sistema, cuando se ejecuta en el contenedor, respeta el principio 5: no ejecuta, importa ni evalúa el código subido; no monta por defecto el código del usuario; no conserva el índice al detenerse; y no escribe datos de la aplicación en el sistema de archivos del host. El archivo temporal efímero del framework queda dentro del contenedor y se borra al terminar la petición.

## Requisitos no funcionales

- RNF-1: La verificación de comprensión es una autoevaluación guiada: el autor sigue el README en un clon limpio con cronómetro y una checklist de pasos, anota dónde se atascó y corrige. No depende de una persona externa ni se bloquea por falta de terceros.
- RNF-2: El camino de cinco minutos se completa en cinco minutos o menos con las dependencias instaladas y el modelo descargado. La primera instalación y la primera descarga se miden y se documentan con su tiempo real; el README no promete cinco minutos para ese caso si no se cumple.
- RNF-3: El workflow de integración continua termina en quince minutos o menos en un runner estándar de GitHub, incluida la instalación de dependencias. Si se acerca al límite, se investiga antes de cerrar la spec.
- RNF-4: El workflow es determinista y no depende de la hora, del estado de la caché del runner ni de datos externos. No se usan reintentos para ocultar pruebas inestables; una prueba inestable se corrige o se documenta como pendiente.
- RNF-5: La publicación no añade dependencias de Python: usa las versiones fijadas en `requirements.txt`, acciones oficiales de GitHub con versión fijada para el checkout y la configuración de Python, y la imagen base oficial `python:3.12-slim` con etiqueta concreta para el contenedor. La prohibición de `latest` se aplica a la imagen base y a las acciones del workflow; no alcanza a herramientas de desarrollo configuradas en `opencode.json`, como `chrome-devtools-mcp@latest`, que no forman parte de la imagen ni del workflow (constitución, principio 1).
- RNF-6: Toda la documentación de publicación está en español, salvo identificadores, nombres de archivos de código, comandos y nombres propios de herramientas, que se mantienen tal cual (constitución, principio 7).
- RNF-7: El README se renderiza correctamente en el repositorio remoto: los enlaces relativos resuelven, el GIF se ve cuando existe, los bloques de código declaran su lenguaje, los encabezados no saltan niveles y no hay rutas absolutas de la máquina del autor.
- RNF-8: Si el GIF existe, está comprimido, pesa como máximo 5 MB y tiene texto alternativo; el repositorio, sin entorno virtual ni artefactos, no supera 25 MB en ningún caso.
- RNF-9: La publicación respeta las garantías de seguridad de la constitución: el código subido nunca se ejecuta, el `.env` queda fuera del repositorio y de la imagen, y las notas de seguridad describen con exactitud qué se envía a Claude y qué se guarda en disco (principios 4 y 5). No se publican claves, tokens, credenciales, datos personales innecesarios ni rutas locales sensibles en el README, el GIF, `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` ni `.agents/`. Se permiten de forma explícita el nombre de María Camila como titular en `LICENSE` y en esta spec, que define la licencia, y el identificador público de la cuenta de GitHub en la URL de clon y en el badge; ninguno de los dos es un dato personal innecesario.
- RNF-10: El paso de pruebas del workflow no necesita red ni el modelo descargado; la instalación de dependencias desde PyPI sí puede usar la red del runner. Esta distinción se explica en el README y en los criterios para que nadie confunda «pruebas sin red» con «instalación sin red».
- RNF-11: El README y el workflow coinciden en la versión de Python y en los comandos de validación, y las dependencias que ambos citan son las fijadas en `requirements.txt`. Cualquier cambio futuro en esos comandos o versiones actualiza las referencias en el mismo cambio.
- RNF-12: La documentación es accesible: el GIF tiene texto alternativo cuando existe, los encabezados siguen una jerarquía lógica, los enlaces tienen texto descriptivo y los ejemplos no dependen solo del color para explicarse.
- RNF-13: La imagen de contenedor se considera reproducible en el sentido verificable de que usa insumos fijados: la base oficial `python:3.12-slim` con etiqueta concreta, las dependencias fijadas en `requirements.txt` y acciones del workflow con versión fijada. Un build limpio con esos insumos y red para descargar el modelo arranca y responde, y una segunda construcción del mismo commit produce una imagen funcionalmente equivalente, no necesariamente idéntica byte a byte. El tamaño real medido se documenta en el README. La base puede fijarse además por digest si se documenta y se verifica; no se usa `latest`.
- RNF-14: El badge del CI refleja el estado real del workflow y de la rama `main`; no se publica un badge con una URL inventada ni se muestra verde si la última ejecución ha fallado. Mientras el repositorio no esté publicado, el README no muestra badge.

## Casos límite

- Clon limpio sin `.env`: la aplicación arranca, `GET /health` responde y el chat devuelve el error documentado; el README explica que es el comportamiento esperado sin clave.
- Recién llegado sin clave: puede subir un archivo `.py`, usar el contenedor y usar las herramientas MCP; no puede obtener respuestas de chat y el README lo dice antes de que lo intente.
- Primera ejecución local sin el modelo descargado: el README advierte de la descarga y de que `/health` puede tardar por el calentamiento; el camino de cinco minutos se mide con el modelo ya disponible.
- `.env.example` copiado tal cual, con la clave vacía: la aplicación arranca y el chat informa de la falta de clave; no se produce un fallo de arranque.
- `.env` creado después de clonar: no aparece en `git status` ni se rastrea; el README no pide hacer commit de él.
- `.env` con `CODEMENTOR_REAL_MODEL` activada: sigue ignorado y el workflow no lo usa, porque no existe en el clon limpio.
- Archivo `.env` ya rastreado por error: `.gitignore` no lo oculta; la comprobación de `git ls-files` lo detecta y se retira del repositorio antes de publicar.
- Clave real visible en el GIF, en un registro o en un comando del README: se retira la imagen o el texto, se rota la clave y se vuelve a comprobar el historial.
- Workflow en un pull request de una bifurcación: se ejecuta sin secretos y sin `.env`; las comprobaciones obligatorias pasan o fallan por el código, no por credenciales ausentes.
- Fallo de `ruff check .` con `pytest -q` en verde: el workflow termina en rojo y el cambio no se valida.
- Fallo de `pytest -q` con `ruff check .` en verde: el workflow termina en rojo y el cambio no se valida.
- Prueba que intenta descargar el modelo en el workflow: se considera un defecto de la suite, no un caso que se deba omitir sin justificación; el registro del workflow no debe mostrar la descarga.
- Workflow que tarda más de quince minutos: se investiga el motivo antes de cerrar la spec; no se acepta como normal.
- Workflow con YAML inválido: GitHub no lo ejecuta; la sintaxis se valida antes de publicar.
- Rama principal llamada `main`: el workflow y el badge usan esa rama; un badge que apunta a otra rama se corrige.
- Repositorio local sin remoto todavía: el workflow existe y se prueba en local; no se muestra badge ni se afirma que el CI esté activo. Al publicar, se añade el remoto y después el badge con la URL real.
- README que menciona una funcionalidad, un comando o una ruta que ya no existe: se corrige antes de publicar; no se acepta como documentación aspiracional.
- README que enlaza `demo_sin_tokens.py`, `diagnostico.py` o `.vscode/`: se retira el enlace; esos archivos están excluidos y no se publican.
- README con una ruta absoluta de la máquina del autor (`C:\...` o `/home/...`): el enlace o el GIF se rompe en el repositorio remoto; se sustituye por una ruta relativa.
- README con un GIF que no existe o con un enlace relativo roto: se corrige antes de cerrar la spec.
- GIF con la interfaz antigua o con textos que ya no aparecen: se actualiza o se retira.
- GIF con código que no sea del proyecto o que no sea un ejemplo inocuo: se sustituye por código del proyecto o por un ejemplo inocuo.
- GIF de menos de 10 segundos o de más de 20: se regenera para respetar la duración.
- GIF que no muestra la subida, la pregunta y la respuesta con citas: se regenera; no se acepta un GIF que solo muestre la pantalla inicial.
- Implementación sin clave disponible: el GIF queda documentado como pendiente, el README no enlaza un archivo inexistente y la spec no se declara bloqueada por ello.
- Ejemplo de chat sin `history`: la API lo acepta y usa un historial vacío; el ejemplo puede incluir `history: []` como convención, pero debe decir que es opcional.
- Ejemplo de subida con un archivo que no es `.py`: la API devuelve el error de extensión; el ejemplo debe usar un archivo `.py` existente.
- Ejemplo MCP que busca antes de indexar: devuelve el mensaje de índice vacío; el README explica que primero se indexa en la misma sesión.
- Ejemplo MCP que indexa en una sesión y busca en otra: no encuentra lo indexado; el README explica que el índice es propio de cada proceso.
- README que afirma «no se guarda nada en disco» sin mencionar el archivo temporal efímero de las subidas grandes: la afirmación es inexacta y se corrige.
- README que afirma «funciona sin red» sin distinguir la instalación de dependencias y la primera descarga del modelo: se corrige la afirmación.
- README o criterio que afirma que el paso de pruebas usa red: es incorrecto; solo la instalación de dependencias desde PyPI puede usar la red del runner.
- `git status` después de ejecutar la aplicación y las pruebas: `.pytest_cache`, `.ruff_cache`, `__pycache__`, `venv/`, `.env`, `.vscode/`, `demo_sin_tokens.py` y `diagnostico.py` no aparecen como cambios pendientes.
- `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` o `.agents/` con una clave, un token, un dato personal innecesario o una ruta local sensible: se elimina o se sustituye antes de publicar; si es una credencial, se rota y se revisa el historial.
- Nombre de María Camila en `LICENSE` o en esta spec, o identificador público de la cuenta de GitHub en la URL de clon y en el badge: son permitidos y no se tratan como filtración; el README puede declarar la licencia sin repetir el nombre.
- `MEMORY.md` afirma que la prueba manual bloquea cerrar 004/005, mientras `docs/roadmap.md` las da por implementadas: antes de publicar se actualiza o matiza la frase para que refleje el estado real; esta spec no edita `MEMORY.md`.
- `.opencode/node_modules` o dependencias locales equivalentes: no se publican; el repositorio no incluye `node_modules`.
- `docs/constitution.md` conserva una «v» suelta al final de la línea 13: se corrige antes de publicar; no se publica con el defecto.
- Licencia MIT sin el año 2026 o sin María Camila como titular: se corrige antes de publicar; no se usan marcadores de posición.
- README con una URL de clon o un badge inventados antes de publicar: se retira; la URL y el badge se añaden con el valor real al publicar.
- Badge de CI en verde de una ejecución antigua: el badge apunta a la rama `main` y al workflow actuales; una ejecución fallida posterior debe ponerlo en rojo.
- README que presenta las specs 001 a 006 como «en producción» o el proyecto como «terminado»: se corrige para reflejar el estado real y el pendiente heredado.
- `docker build` sin red: falla al no poder descargar dependencias o el modelo; el README advierte de que el build necesita internet.
- `docker build` con red: descarga el modelo y lo deja en la imagen; el tamaño real de la imagen se mide y se documenta.
- `docker run` sin `ANTHROPIC_API_KEY`: el contenedor arranca, sirve la API y el frontend, `/health` responde tras el calentamiento sin descargar el modelo y el chat devuelve el error documentado.
- `docker run` sin `-p 8000:8000`: el contenedor escucha en `0.0.0.0:8000` pero no es accesible desde el host; el README documenta el mapeo de puertos.
- `docker run -p 8000:8000 ...`: la API y el frontend responden en `http://localhost:8000`; el README usa ese ejemplo.
- `opencode.json` usa `chrome-devtools-mcp@latest`: es una herramienta de desarrollo y la prohibición de `latest` no se aplica aquí, porque solo alcanza a la imagen base y a las acciones del workflow.
- `docker run -e ANTHROPIC_API_KEY=...` con una clave válida: el chat funciona y devuelve citas; la clave no queda en la imagen.
- Imagen que contiene `.env` o una clave en alguna capa: se corrige el `Dockerfile` o el `.dockerignore`, se reconstruye y se vuelve a inspeccionar.
- `.dockerignore` que excluye `app/`, `static/` o `requirements.txt`: la imagen no arranca; se corrige para conservar lo necesario en runtime.
- Contexto de build que incluye `docs/`, `specs/`, `tests/`, `.git/` o `node_modules`: se corrige el `.dockerignore` y se verifica el tamaño del contexto.
- Intento de publicar la imagen en Docker Hub o GHCR: está fuera de alcance; no hay pasos de `docker push` ni workflow de publicación de imagen.
- `docker-compose` o un archivo equivalente: no se incluye; el empaquetado es solo con `Dockerfile`.

## Fuera de alcance

- Cambiar el comportamiento, el contrato o los límites de las specs 001 a 006.
- Añadir funcionalidades al producto, nuevas rutas, nuevas herramientas MCP o nuevos modos de uso.
- Persistencia del índice (008a), soporte de JavaScript (008b), importación de repositorios (008c) y evaluación de calidad del RAG (008d).
- `docker-compose`, la publicación de la imagen en un registro, un despliegue en producción y cualquier uso del contenedor como servicio alojado.
- Despliegue en un servidor, un dominio público, HTTPS, autenticación, un proxy inverso o un servicio de hosting.
- Publicar en PyPI, GitHub Pages o cualquier otro canal de distribución distinto del repositorio de GitHub.
- Publicar una versión en inglés del README, un blog, un vídeo narrado o una presentación comercial.
- Analizadores de secretos, dependencias o calidad de código distintos de `ruff` y `pytest`, salvo que se aprueben expresamente en una enmienda a esta spec.
- Reescribir el historial de git o cambiar la licencia de dependencias de terceros. La licencia del proyecto es MIT, a nombre de María Camila y con año de publicación 2026.
- Publicar `demo_sin_tokens.py`, `diagnostico.py` o `.vscode/`: quedan excluidos del repositorio y de la documentación. Si se quisieran publicar en el futuro, necesitarían una spec o una enmienda propia.
- Resolver la prueba manual con clave real de las specs 004 y 005: queda como pendiente heredado y no bloquea el cierre de esta spec.

## Criterios de finalización

- C-1: El repositorio git está inicializado, `.gitignore` está activo antes del primer commit y el primer commit no contiene `.env`, entorno virtual, cachés, archivos auxiliares ni `.vscode/`.
- C-2: La autoevaluación guiada se completa: el autor sigue el README en un clon limpio con cronómetro y una checklist, anota dónde se atascó y corrige; el camino de cinco minutos se mide en una segunda ejecución con dependencias y modelo disponibles, y la primera instalación y descarga quedan medidas y documentadas.
- C-3: `GET /health` responde; la subida de un archivo `.py` y la búsqueda funcionan sin clave; el chat sin clave devuelve el error documentado. La prueba manual con clave real queda como pendiente heredado de las specs 004 y 005 y no bloquea el cierre.
- C-4: El README contiene y verifica por separado todas las secciones de RF-1, la distinción entre lo que funciona sin clave y lo que requiere clave de RF-4, el diagrama de RF-2, el inicio rápido de RF-3, los ejemplos de RF-5, las decisiones de RF-6, la estructura de RF-7, el stack de RF-8, los límites de RF-9 y la licencia MIT de RF-34.
- C-5: Cada comando, ruta, función, herramienta, badge e imagen citada por el README existe y funciona en la versión publicada; no hay enlaces relativos rotos ni promesas de funciones futuras presentadas como disponibles; una revisión visual práctica confirma que las acciones y citas del GIF son reales.
- C-6: El proyecto publica el GIF o, si no hay clave disponible al implementar, lo deja registrado como pendiente, el README no enlaza un archivo inexistente y la spec no se declara bloqueada por ello. Si existe, dura entre 10 y 20 segundos, muestra la subida, la pregunta y la respuesta con citas, tiene texto alternativo, no contiene claves, datos personales innecesarios ni rutas locales y no se añaden capturas estáticas.
- C-7: Existe un workflow en `.github/workflows/` que se ejecuta en los push y en los pull requests, usa Python 3.12 y ejecuta exactamente `ruff check .` y `pytest -q`; un fallo de lint o de prueba lo pone en rojo, no hay `continue-on-error`, `|| true` ni pruebas excluidas de la suite; la única omisión por defecto es la prueba opcional con el modelo real de RF-18, declarada en la propia prueba, que no cuenta como exclusión; declara permisos de solo lectura sin `pull_request_target`.
- C-8: El workflow pasa en un clon limpio sin `.env`, sin secretos, sin servicios externos y sin descargar el modelo; la instalación de dependencias desde PyPI sí puede usar la red del runner; la prueba opcional con el modelo real aparece omitida por defecto y esa omisión declarada no cuenta como exclusión; el workflow termina en quince minutos o menos.
- C-9: `.env` no aparece en `git status` ni en `git ls-files`; `.env.example` sí está rastreado y copiarlo a `.env` produce una configuración válida. La búsqueda de patrones de clave en archivos rastreados no devuelve coincidencias.
- C-10: `.gitignore` cubre las categorías de RF-26 y se verifica creando archivos y carpetas de prueba: `venv/`, cachés de Python, pytest y ruff, `.env`, `.vscode/`, `demo_sin_tokens.py`, `diagnostico.py`, artefactos de sistema operativo y editor, registros, bases de datos locales y `node_modules`.
- C-11: Las notas de seguridad del README son exactas: describen la clave fuera del repositorio y de la imagen, el código que nunca se ejecuta, la ausencia de persistencia salvo el temporal efímero documentado, los datos que se envían a Claude y la falta de autenticación y TLS.
- C-12: El README explica el comportamiento sin clave y el arranque: en local, la primera ejecución descarga el modelo y `/health` puede tardar por el calentamiento; en Docker, el modelo se descarga en el build, `docker run` no lo descarga y `/health` responde tras el arranque y el calentamiento.
- C-13: El README y `.env.example` explican cómo configurar la clave sin escribirla en un archivo rastreado y usan un marcador, nunca una clave real, en el ejemplo de `docker run -p 8000:8000 -e`.
- C-14: El repositorio público se llama `codementor`, usa la rama `main`, vive en una cuenta personal de GitHub y contiene el README, el workflow, `.env.example`, `.gitignore`, el `Dockerfile`, `.dockerignore`, la licencia MIT, `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` y `.agents/`, y el GIF cuando exista; no contiene `.env`, entorno virtual, cachés, bases de datos, `demo_sin_tokens.py`, `diagnostico.py` ni `.vscode/`. La URL real se añade al publicar y no se inventa antes.
- C-15: El archivo de licencia MIT contiene el año 2026 y el titular María Camila, sin marcadores de posición; el README declara la licencia MIT y solo muestra el badge cuando existe la URL real y apunta a la rama `main` y al workflow reales.
- C-16: El README declara el estado real de las specs 001 a 006 y el pendiente heredado de la prueba manual; no presenta el proyecto como terminado ni en producción.
- C-17: `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` y `.agents/` se revisan antes de publicar y no contienen claves, tokens, datos personales innecesarios ni rutas locales sensibles; se permiten el nombre de María Camila en `LICENSE` y en esta spec, y el identificador público de la cuenta de GitHub en la URL de clon y el badge; no se publican `node_modules` ni archivos generados; la «v» suelta al final de la línea 13 de `docs/constitution.md` se corrige antes de publicar.
- C-18: La imagen se construye con `python:3.12-slim`, las dependencias fijadas y sin `latest` en la base; el build descarga el modelo y necesita internet; la imagen arranca; el tamaño real medido se documenta; el `.dockerignore` excluye los archivos listados en RF-40 y conserva `app/`, `static/` y `requirements.txt`; no hay publicación en ningún registro ni `docker-compose`.
- C-19: El contenedor arranca sin clave, escucha en `0.0.0.0:8000`, es accesible con `-p 8000:8000`, sirve la API y el frontend, `/health` responde tras el calentamiento sin descargar el modelo en runtime y el chat devuelve el error documentado; con `ANTHROPIC_API_KEY` en tiempo de ejecución el chat funciona; no escribe datos de la aplicación en el sistema de archivos del host y no conserva el índice al detenerse.
- C-20: La publicación no añade dependencias de Python; usa `requirements.txt`, acciones oficiales con versión fijada y la base `python:3.12-slim`, sin `latest` en la base ni en las acciones (la prohibición no alcanza a herramientas de desarrollo de `opencode.json`); un build limpio con esos insumos arranca y responde, y una segunda construcción del mismo commit produce una imagen funcionalmente equivalente.
- C-21: Toda la documentación de publicación está en español, salvo identificadores, nombres de archivos de código, comandos y nombres propios de herramientas.
- C-22: Si el GIF existe, pesa como máximo 5 MB; el repositorio, sin entorno virtual ni artefactos, no supera 25 MB.
- C-23: Si el GIF existe, tiene texto alternativo; los encabezados siguen una jerarquía lógica, los enlaces tienen texto descriptivo y los ejemplos no dependen solo del color.
- C-24: `ruff check .` y `pytest -q` pasan en local al cerrar la spec, con las mismas versiones que usa el workflow.
- C-25: La spec pasa de borrador a aprobada antes de implementar la primera tarea.
- C-26: El workflow no usa acciones ni pasos de reintento; dos ejecuciones del mismo commit producen el mismo resultado salvo causas externas documentadas; no depende de la hora, de la caché del runner ni de datos externos.
- C-27: Un pull request desde una bifurcación ejecuta el workflow sin secretos, sin `.env` y sin `ANTHROPIC_API_KEY`; las dos comprobaciones pasan o fallan solo por el código.
- C-28: El workflow instala exclusivamente las dependencias fijadas en `requirements.txt`; el registro no muestra paquetes adicionales y las comprobaciones se ejecutan con esa instalación.
- C-29: Los comandos del workflow (`ruff check .` y `pytest -q`) y la versión menor de Python coinciden literalmente con los del README; una comparación textual no encuentra diferencias.
- C-30: `MEMORY.md` actualiza o matiza la frase que afirma que la prueba manual bloquea cerrar 004/005, para que coincida con `docs/roadmap.md`, que las da por implementadas; esta spec no edita `MEMORY.md`.

### Trazabilidad de requisitos

| Requisito | Comprobación |
|---|---|
| RF-1 a RF-9 | C-4 (cada sección, por separado) |
| RF-10 | C-5 |
| RF-11 a RF-14 | C-6 |
| RF-15 | C-7 |
| RF-16 | C-27 |
| RF-17 | C-28 |
| RF-18 | C-8 (omisión declarada, ver C-7) |
| RF-19, RF-20, RF-21, RF-23 | C-7, C-8 |
| RF-22 | C-29 |
| RF-24, RF-25, RF-27 | C-9, C-17 |
| RF-26 | C-10 |
| RF-28 | C-11 |
| RF-29 | C-3, C-12 |
| RF-30 | C-12 |
| RF-31 | C-13 |
| RF-32 | C-1 |
| RF-33, RF-36 | C-14 |
| RF-34 | C-15 |
| RF-35 | C-16 |
| RF-37 | C-14, C-17, C-30 |
| RF-38, RF-40, RF-41 | C-18 |
| RF-39, RF-42 | C-19 |
| RNF-1, RNF-2 | C-2 |
| RNF-3 | C-8 |
| RNF-4 | C-26 |
| RNF-5 | C-20 |
| RNF-6 | C-21 |
| RNF-7 | C-4, C-5, C-23 |
| RNF-8 | C-22 |
| RNF-9 | C-9, C-11, C-15, C-17 |
| RNF-10 | C-8 |
| RNF-11 | C-29 |
| RNF-12 | C-23 |
| RNF-13 | C-18, C-20 |
| RNF-14 | C-15 |

## Decisiones acordadas con el usuario

- **D1 — Docker solo con `Dockerfile`, local y sin registro.** Se incluye un `Dockerfile` que construye y ejecuta la aplicación en local, sirve la API y el frontend, y no se publica en Docker Hub, GHCR ni ningún otro registro. No se incluye `docker-compose`. La clave se pasa en tiempo de ejecución con `docker run -e ANTHROPIC_API_KEY=...`; no se hornea en la imagen, no se copia `.env` y el contenedor arranca sin clave. Por qué: permite probar el proyecto sin preparar Python, mantiene el alcance pequeño y respeta el principio 5, porque la clave no queda en capas ni en archivos de la imagen. Alternativa descartada: `docker-compose` y publicación en un registro, que añaden configuración, credenciales y superficie de publicación sin una necesidad demostrada.
- **D2 — Un único GIF de 10 a 20 segundos de la interfaz web.** El proyecto publica un GIF que muestra la subida de un archivo, una pregunta y la respuesta con citas; no se añaden capturas estáticas. Por qué: en una sola imagen se ve el flujo real completo y se entiende el producto sin ejecutarlo, que es el objetivo del portafolio. Alternativa descartada: varias capturas estáticas, que obligan a encadenar imágenes y no muestran la interacción, o GIF más capturas, que duplican mantenimiento y peso.
- **D3 — CI solo con `ruff check .` y `pytest -q`.** El workflow se ejecuta en push y pull request, con Python 3.12, sin claves y sin descargar modelos; el paso de pruebas no usa red, pero la instalación de dependencias desde PyPI sí puede usar la red del runner. No ejecuta `ruff format --check` ni comprobaciones de frontend. Por qué: son las dos comprobaciones que exige la constitución, ya están fijadas y mantienen el workflow rápido y reproducible sin herramientas nuevas. Alternativa descartada: añadir formato y frontend, que hoy no tienen una comprobación acordada, añaden ruido y podrían exigir dependencias o decisiones nuevas.
- **D4 — Repositorio público de GitHub con licencia MIT y badge de CI.** La creación y publicación efectiva del repositorio forma parte de la entrega; el README declara la licencia MIT y muestra el badge del workflow cuando el repositorio esté publicado. La licencia se emite a nombre de María Camila con año de publicación 2026. Por qué: un repositorio público con licencia y CI visible es lo que convierte el trabajo en portafolio reutilizable y demuestra que el proyecto se valida. Alternativa descartada: repositorio privado o sin licencia, que limita la reutilización y no da señal pública de calidad.
- **D5 — Excluir los archivos auxiliares y `.vscode/`, y publicar el resto de la documentación de trabajo.** `demo_sin_tokens.py`, `diagnostico.py` y `.vscode/` quedan fuera del repositorio y se añaden a `.gitignore`. Se publican `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` y `.agents/` porque muestran la planificación, los agentes, las skills SDD y la documentación del proyecto, después de revisar que no contengan claves, tokens, datos personales innecesarios ni rutas locales sensibles; se permiten el nombre de la titular en `LICENSE` y en la spec, y el identificador público de la cuenta en la URL y el badge. Por qué: el repositorio queda limpio de archivos personales y, a la vez, muestra el proceso de trabajo, que es parte del valor del portafolio. Alternativa descartada: publicar todo, que arrastra configuración local y riesgo de filtrar datos, o no publicar nada de la planificación, que oculta una parte diferencial del proyecto.
- **D6 — La prueba manual con clave real queda como pendiente heredado y no bloquea la 007.** El proyecto genera el GIF cuando haya clave disponible; si no la hay al implementar, su ausencia se documenta igual que las pruebas manuales de las specs 004 y 005, sin declarar el cierre bloqueado. Por qué: la prueba real depende de una credencial externa y ya venía pendiente; bloquear la publicación por ella retrasaría la entrega sin aportar una validación que las pruebas automatizadas y el flujo sin clave ya cubren en parte. Alternativa descartada: exigir la prueba real y el GIF para cerrar, que dejaría la spec abierta indefinidamente por una dependencia externa.
- **D7 — Repositorio `codementor` en una cuenta personal, rama `main`, usuario pendiente de publicación.** El repositorio se llamará `codementor`, usará la rama `main` y vivirá en una cuenta personal de GitHub. El nombre de usuario u organización exacto se decide al publicar; hasta entonces no se fija la URL de clon ni la del badge. Por qué: el nombre y la rama ya están decididos, pero inventar el usuario o una URL produciría enlaces falsos. Alternativa descartada: fijar un usuario y una URL ficticios, que romperían el README y el badge desde el primer commit.
- **D8 — Publicar los archivos raíz y la documentación de trabajo.** Se publican `opencode.json`, `AGENTS.md`, `MEMORY.md`, `docs/`, `specs/`, `.opencode/` y `.agents/`, además de los artefactos de producto. Se revisan antes secretos, tokens, datos personales innecesarios y rutas locales sensibles; se permiten el nombre de la titular en `LICENSE` y en la spec, y el identificador público de la cuenta en la URL y el badge. Se excluyen `node_modules` y archivos generados. Por qué: el proceso de planificación, las decisiones y las skills forman parte del valor del portafolio, y la revisión previa evita filtrar datos. Alternativa descartada: publicar solo el código, que oculta el trabajo de diseño, o publicar sin revisar, que expone configuración local.
- **D9 — «Sin red» significa sin red en el paso de pruebas.** El paso de `pytest -q` no descarga el modelo ni consulta servicios externos; la instalación de dependencias desde PyPI sí puede usar la red del runner. Por qué: mezclar ambas cosas haría imposible instalar las dependencias y volvería ambiguo el requisito de la constitución. Alternativa descartada: exigir un workflow completamente offline, que necesitaría artefactos o cachés previas y añadiría complejidad sin mejorar las pruebas.
- **D10 — El modelo se descarga en el build de Docker y queda en la imagen.** El `docker build` necesita internet para descargar dependencias y el modelo; la imagen resultante es más grande y su tamaño real se documenta. `docker run` no descarga el modelo y `GET /health` responde tras el arranque y el calentamiento, sin espera de descarga en runtime. En local, sin Docker, la primera ejecución sigue descargando el modelo. Por qué: el arranque en el contenedor es predecible y no depende de la red ni de la caché del host. Alternativa descartada: descargar el modelo en el arranque del contenedor, que hace el primer `docker run` lento y dependiente de la red, o no incluirlo, que obliga a tener red en runtime.
- **D11 — Autoevaluación guiada en lugar de una persona externa.** El autor sigue el README en un clon limpio con cronómetro y una checklist, anota dónde se atascó y corrige. Por qué: no hay una persona externa disponible y la autoevaluación deja evidencia concreta de los pasos y los tiempos. Alternativa descartada: depender de una persona ajena, que bloquearía la verificación sin aportar una garantía distinta.

## Pendientes de publicación

- **Usuario u organización de GitHub:** pendiente de fijar al publicar. El repositorio será `codementor` en una cuenta personal y usará la rama `main`; no se inventa el usuario ni la URL. Al publicar, ese identificador público aparecerá en la URL de clon y en el badge y es información permitida.
- **URL de clon y badge:** se añaden al README con la URL real cuando el repositorio esté publicado. Antes de esa fecha, el README no muestra una URL ni un badge inventados.
- Estos pendientes no bloquean la aprobación de la spec; son datos que se completan en la tarea de publicación.

## Dudas abiertas

Ninguna. No quedan puntos pendientes de aclaración ni elementos marcados como `[NECESITA ACLARACIÓN]`. El usuario u organización de GitHub y la URL real del clon y del badge se recogen en «Pendientes de publicación», no como duda de la spec.
