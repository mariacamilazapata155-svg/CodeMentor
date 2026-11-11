# Plan 006 — Servidor MCP

Estado: implementado


## Alcance y supuestos
- Se implementa solo la capa MCP en `app/mcp_server.py`: servidor por entrada/salida estándar, publicación de las dos herramientas y traducción de sus resultados a texto en español. Las pruebas nuevas viven en `tests/`.
- `mcp_server.py` consume `rag.py` directamente (principio 3): llama a `rag.search` y `rag.index_file` y no pasa por `bot.py`, `main.py`, HTTP ni el modelo de lenguaje.
- El índice es el singleton `rag.store` del proceso. No se crea otro almacén, no se persiste y no se comparte con el servidor HTTP.
- No se modifican `rag.py`, `storage.py`, `models.py`, `main.py`, `bot.py`, `static/` ni `requirements.txt`. `mcp==2.3.0` ya está fijado en `requirements.txt:11`.
- No hay lógica que dependa de la fecha ni de la hora; por eso ninguna función recibe un parámetro `hoy`.
- Supuestos que se confirman en T0 contra el SDK instalado (no se dan por ciertos; resultado en `## Resoluciones de T0`):
  1. `mcp==2.3.0` expone el servidor de bajo nivel `mcp.server.Server` con manejadores `on_list_tools` y `on_call_tool` en el constructor.
  2. `mcp.server.stdio.stdio_server()` entrega un par de flujos y `Server.run(...)` los sirve con `create_initialization_options()`.
  3. `mcp.types.Tool` usa `input_schema` en Python y lo serializa como `inputSchema`; `CallToolResult` usa `is_error` y lo serializa como `isError`.
  4. `mcp.client._memory.InMemoryTransport` acepta un `Server` de bajo nivel y `mcp.client.session.ClientSession` permite `initialize`, `list_tools` y `call_tool` sin red.
  5. `asyncio.to_thread` está disponible en Python 3.12 y `rag.store` es seguro entre hilos por su `RLock` (spec 004).
  6. En `mcp==2.3.0`, `mcp.server.fastmcp` ya no existe y `MCPServer` (antiguo `FastMCP`) valida los argumentos con Pydantic y devuelve mensajes técnicos en inglés; por eso se elige el servidor de bajo nivel.

## Aprobaciones necesarias (según `AGENTS.md`)
Ninguna bloqueante.

- No se añaden dependencias: `mcp==2.3.0` ya está en `requirements.txt`.
- No se cambian los esquemas de `models.py` ni el formato de los chunks.
- `app/mcp_server.py` ya figura en la estructura de `AGENTS.md`; se sustituye su esqueleto.
- Los archivos nuevos son pruebas dentro de `tests/`, carpeta ya prevista y usada por las specs 001 a 005.
- Si T0 demuestra que el SDK instalado no ofrece la API de bajo nivel descrita, se detiene la implementación y se pregunta antes de cambiar de enfoque, de versión o de dependencia.
- `AGENTS.md` no cambia: la estructura de módulos, el orden de capas y las reglas de dependencias siguen igual.

## API de MCP verificada (`mcp==2.3.0`)
Comprobado en el paquete instalado en `venv/Lib/site-packages`, no en documentación de otra versión.

| Elemento | Importación / firma | Fuente |
|---|---|---|
| Versión fijada | `mcp==2.3.0` | `requirements.txt:11` |
| Servidor de bajo nivel | `from mcp.server import Server` | `mcp/server/__init__.py:3`; clase en `mcp/server/lowlevel/server.py:129` |
| Manejadores en el constructor | `Server(name, ..., on_list_tools=..., on_call_tool=...)`; reciben `(ctx, params)` | `mcp/server/lowlevel/server.py:148-157` |
| Transporte stdio | `from mcp.server.stdio import stdio_server`; `async with stdio_server() as (read_stream, write_stream)` | `mcp/server/stdio.py:162` |
| Arranque | `await server.run(read_stream, write_stream, server.create_initialization_options())` | `mcp/server/lowlevel/server.py:703` y `:539` |
| Tipos de protocolo | `from mcp.types import Tool, ListToolsResult, CallToolResult, TextContent, CallToolRequestParams` | `mcp/types/__init__.py:1-24` (espejo de `mcp_types`) |
| Herramienta | `Tool(name=..., description=..., input_schema={...})` | `mcp_types/_types.py:1411-1417` |
| Resultado de invocación | `CallToolResult(content=[...], is_error=False)` | `mcp_types/_types.py:1463-1481` |
| Contenido de texto | `TextContent(type="text", text=...)` | `mcp_types/_types.py:1150-1155` |
| Argumentos de invocación | `CallToolRequestParams(name=..., arguments=...)` | `mcp_types/_types.py:1449-1453` |
| Alias de cable | `input_schema` → `inputSchema`, `is_error` → `isError` | `MCPModel` con `alias_generator=to_camel`, `mcp_types/_types.py:45-48` |
| Transporte en memoria | `InMemoryTransport(server)` acepta `Server` de bajo nivel | `mcp/client/_memory.py:29-48` |
| Cliente de pruebas | `ClientSession(read, write)`; `initialize()`, `list_tools()`, `call_tool(name, arguments)` | `mcp/client/session.py:404-422`, `:651`, `:1278`, `:1052` |
| `FastMCP` eliminado | `mcp.server.fastmcp` lanza `ModuleNotFoundError`; el reemplazo es `mcp.server.mcpserver.MCPServer` | `mcp/server/fastmcp.py:1-16` |

Diferencias relevantes frente a la versión 1 del SDK:
- `FastMCP` se llama ahora `MCPServer`; `mcp.server.fastmcp` no existe y su importación falla a propósito.
- El servidor de bajo nivel registra los manejadores en el constructor, no con decoradores.
- `mcp.types` sigue funcionando como espejo de `mcp_types`, así que se puede escribir `from mcp.types import Tool`.
- `stdio_server()` en 2.3.0 reclama el descriptor 1 y lo desvía a la salida de error mientras sirve; aun así la aplicación no debe escribir en la salida estándar y las pruebas lo comprueban.

### Por qué el servidor de bajo nivel y no `MCPServer`
- `MCPServer` valida los argumentos con Pydantic y, ante un fallo, produce mensajes técnicos en inglés del estilo `Error executing tool ...`. Eso incumpliría RF-24, RF-27 y RNF-3, que exigen mensajes en español, comprensibles y sin detalles internos.
- El servidor de bajo nivel no valida ni reescribe los argumentos: permite publicar el esquema exacto y decidir cada mensaje.
- Con el servidor de bajo nivel solo se anuncia la capacidad de herramientas cuyos manejadores existen (`get_capabilities`, `mcp/server/lowlevel/server.py:616-618`); al registrar solo `on_list_tools` y `on_call_tool`, no se anuncian recursos ni plantillas, como exige RF-1.
- Alternativa descartada: `MCPServer` con mensajes traducidos a posteriori. Obligaría a interceptar errores del SDK y a duplicar la validación, con dos fuentes de verdad.

## Contrato de herramientas
Se publican exactamente dos herramientas, en este orden estable: primero `search_code`, después `index_file`.

| Herramienta | Descripción exacta (español) | Esquema de argumentos |
|---|---|---|
| `search_code` | `Busca en el código Python ya indexado en este servidor los fragmentos más parecidos a una consulta. Devuelve hasta cinco fragmentos, cada uno con su ruta, símbolo, líneas, relevancia y texto, para que puedas citarlos. Úsala cuando necesites localizar dónde está algo en el código indexado; no responde preguntas ni genera explicaciones.` | `query`: texto obligatorio |
| `index_file` | `Indexa el contenido de un archivo Python en el índice de este servidor para poder buscarlo después con search_code. Recibe la ruta con la que se citará el archivo y su contenido completo como texto; no lee el archivo del disco y no lo ejecuta. Si la ruta ya estaba indexada, sustituye sus fragmentos. Úsala antes de search_code.` | `path` y `content`: textos obligatorios |

Esquema de `search_code`:
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Pregunta o palabras clave sobre el código que quieres localizar. No puede estar vacía ni superar los 1.000 caracteres."
    }
  },
  "required": ["query"]
}
```

Esquema de `index_file`:
```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "Ruta con la que se identificará el archivo en el índice y en las citas. Debe terminar en .py; no se comprueba que exista en el disco."
    },
    "content": {
      "type": "string",
      "description": "Contenido completo del archivo Python como texto. No puede estar vacío ni superar 1.048.576 bytes en UTF-8."
    }
  },
  "required": ["path", "content"]
}
```

- No se declara `additionalProperties: false`: la spec establece que un argumento no declarado se ignora y la operación continúa; el valor por defecto de JSON Schema ya permite propiedades adicionales.
- Ningún argumento es opcional ni de otro tipo. No se publican recursos, plantillas, notificaciones ni otras herramientas.
- `create_server()` añade `title="CodeMentor"` e `instructions` en español, sin publicar capacidades nuevas: `Indexa archivos .py con index_file y busca en ellos con search_code. El índice vive en este proceso y empieza vacío.`

## Archivos y responsabilidades
- `app/mcp_server.py`: único archivo de producción que cambia. Define el servidor, las dos herramientas, la validación de argumentos propia, el formateo de resultados, el manejo de errores y el arranque por stdio. No trocea, no calcula representaciones, no busca por su cuenta y no lee ni escribe archivos.
- `tests/test_mcp_helpers.py`: funciones puras de validación y formato, y mensajes exactos.
- `tests/test_mcp_tools.py`: conexión de protocolo, lista de herramientas, descripciones y esquemas.
- `tests/test_mcp_search.py`: búsqueda, reutilización de mensajes de la spec 001, formato de fragmentos y casos de índice vacío o sin resultados relevantes.
- `tests/test_mcp_index.py`: indexado, orden de validación, reutilización de mensajes de la spec 002 y formato del éxito.
- `tests/test_mcp_runtime.py`: flujo completo por protocolo, errores no controlados, concurrencia, stdio limpio, importación sin modelo, ausencia de lectura/escritura de disco, de ejecución y de HTTP o modelo de lenguaje.
- Sin cambios en `bot.py`, `main.py`, `static/`, `models.py`, `storage.py`, `rag.py` ni `requirements.txt`.

## Funciones
`mcp_server.py` (todas con type hints y docstring en español):

Constantes:
- `SEARCH_TOOL_NAME = "search_code"`, `INDEX_TOOL_NAME = "index_file"`.
- `SEARCH_DESCRIPTION`, `INDEX_DESCRIPTION`: textos exactos de la tabla anterior.
- `SEARCH_INPUT_SCHEMA`, `INDEX_INPUT_SCHEMA`: diccionarios de la tabla anterior.
- `SEARCH_TOOL`, `INDEX_TOOL`: instancias de `Tool` construidas con las constantes anteriores. Se tratan como inmutables.
- `MSG_QUERY_REQUIRED`, `MSG_QUERY_NOT_TEXT`, `MSG_PATH_REQUIRED`, `MSG_PATH_NOT_TEXT`, `MSG_EXTENSION`, `MSG_CONTENT_REQUIRED`, `MSG_CONTENT_NOT_TEXT`, `MSG_EMPTY_INDEX`, `MSG_UNKNOWN_TOOL`, `MSG_INTERNAL_ERROR`: textos exactos de `## Mensajes exactos`.
- `logger = logging.getLogger(__name__)`.

Funciones:
- `create_server() -> Server[Any]`: construye `Server("codementor", title="CodeMentor", instructions=..., on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)`. No arranca nada ni toca el índice.
- `async _on_list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult`: devuelve `ListToolsResult(tools=[SEARCH_TOOL, INDEX_TOOL])`. RF-1.
- `async _on_call_tool(ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> CallToolResult`: ejecuta `_dispatch` fuera del bucle de eventos con `asyncio.to_thread`; captura cualquier `Exception`, registra solo su tipo y devuelve `MSG_INTERNAL_ERROR` marcado como error. RF-25, RF-26, RNF-9.
- `_dispatch(name: str, arguments: dict[str, Any] | None) -> CallToolResult`: enruta por nombre a `_search` o `_index`; para cualquier otro nombre devuelve `MSG_UNKNOWN_TOOL`. Es síncrona; el manejador la ejecuta en un hilo para no bloquear el bucle de eventos. RF-1, RF-24.
- `_search(arguments: dict[str, Any]) -> CallToolResult`: valida `query`, llama a `rag.search(query)` y traduce el `SearchResponse`. RF-3 a RF-9.
- `_index(arguments: dict[str, Any]) -> CallToolResult`: valida `path` y `content` en el orden fijado, llama a `rag.index_file(path, content)` y traduce el `IndexResult`. RF-10 a RF-18.
- `_parse_query(arguments: dict[str, Any]) -> tuple[str | None, str | None]`: devuelve `(query, None)` o `(None, mensaje)`. Comprueba presencia y tipo; no recorta ni valida vacío o longitud, que son de `rag.search`. RF-6, RF-27.
- `_parse_index_arguments(arguments: dict[str, Any]) -> tuple[tuple[str, str] | None, str | None]`: devuelve `((path, content), None)` o `(None, mensaje)`. Aplica el orden: ruta presente → tipo de ruta → ruta no vacía → extensión → contenido presente → tipo de contenido. RF-12 a RF-14, RF-27.
- `_format_search_results(results: list[SearchResult]) -> str`: une los bloques de todos los fragmentos con una línea en blanco. RF-3, RF-9.
- `_format_result(index: int, total: int, result: SearchResult) -> str`: construye el bloque de un fragmento. RF-3.
- `_format_relevance(score: float) -> str`: acota a `[0, 1]`, dos decimales y coma decimal. RF-3.
- `_format_index_success(result: IndexResult) -> str`: mensaje reutilizado de la spec 002 y los cuatro datos del éxito. RF-10.
- `_format_number(value: int) -> str`: entero con punto de miles (`1.000`). Es presentación de esta capa; no se llama a `rag._format_number`, que es privada de otra capa.
- `_ok(text: str) -> CallToolResult` y `_error(text: str) -> CallToolResult`: construyen el resultado con `TextContent` y `is_error` en `False` o `True`. RF-24, RF-26.
- `_configure_logging() -> None`: instala un `StreamHandler(sys.stderr)` en el logger del módulo, con `propagate = False`, de forma idempotente. Nunca escribe en la salida estándar. RNF-1.
- `async _serve() -> None`: crea el servidor y lo sirve con `stdio_server()` hasta que el cliente cierra la entrada. RF-29.
- `main() -> None`: configura los registros y ejecuta `asyncio.run(_serve())`. Es el punto de entrada de `python -m app.mcp_server`. RNF-1.

Mapa de requisitos:
| Función | RF / RNF |
|---|---|
| `create_server`, `_on_list_tools`, `SEARCH_TOOL`, `INDEX_TOOL` | RF-1, RF-2, RF-28, RNF-7 |
| `_parse_query`, `_search` | RF-3 a RF-9, RF-27, RF-33 |
| `_parse_index_arguments`, `_index` | RF-10 a RF-18, RF-27, RF-33 |
| `_format_search_results`, `_format_result`, `_format_relevance` | RF-3, RF-9 |
| `_format_index_success`, `_format_number` | RF-10 |
| `_ok`, `_error`, `_on_call_tool` | RF-24 a RF-27, RNF-9 |
| `_configure_logging`, `_serve`, `main` | RF-29, RNF-1, RNF-4, RNF-10 |

## Algoritmo
### Lista de herramientas
```text
_on_list_tools(ctx, params):
    devolver ListToolsResult(tools=[SEARCH_TOOL, INDEX_TOOL])
```
El orden es fijo. El SDK anuncia la capacidad `tools` porque existe el manejador `tools/list`; no se registran manejadores de recursos ni de plantillas, así que no se anuncian.

### Invocación y errores
```text
_on_call_tool(ctx, params):
    intentar:
        devolver await asyncio.to_thread(_dispatch, params.name, params.arguments)
    except Exception como exc:
        logger.error("error interno en una herramienta: %s", type(exc).__name__)
        devolver _error(MSG_INTERNAL_ERROR)

_dispatch(name, arguments):
    args = arguments o {}
    si name == SEARCH_TOOL_NAME: devolver _search(args)
    si name == INDEX_TOOL_NAME:  devolver _index(args)
    devolver _error(MSG_UNKNOWN_TOOL.format(name=name))
```
`asyncio.to_thread` mantiene el bucle de eventos libre mientras `rag.search` o `rag.index_file` calculan representaciones; el `RLock` de `rag.store` (spec 004) hace segura la convivencia de una búsqueda y un indexado. No se captura `BaseException`: una cancelación o una interrupción del proceso no se convierten en un resultado de herramienta.

### Búsqueda
```text
_search(args):
    query, error = _parse_query(args)
    si error: devolver _error(error)

    respuesta = rag.search(query)                 # spec 001, sin reimplementar
    si respuesta.reason == EMPTY_QUERY:      devolver _error(respuesta.message)
    si respuesta.reason == QUERY_TOO_LONG:   devolver _error(respuesta.message)
    si respuesta.reason == EMPTY_INDEX:      devolver _ok(MSG_EMPTY_INDEX)
    si respuesta.reason == NO_RELEVANT:      devolver _ok(respuesta.message)
    si respuesta.reason no es None:          devolver _error(MSG_INTERNAL_ERROR)
    devolver _ok(_format_search_results(respuesta.results))
```
`_parse_query` no recorta ni comprueba vacío o longitud: eso lo hace `rag.search` en el orden de la spec 001 (primero vacío, después longitud), y así se reutilizan literalmente sus mensajes. Un motivo desconocido no se trata como éxito: se convierte en error genérico para no inventar una respuesta.

### Indexado
```text
_index(args):
    datos, error = _parse_index_arguments(args)
    si error: devolver _error(error)

    path, content = datos
    resultado = rag.index_file(path, content)     # spec 002, sin reimplementar
    si resultado.reason no es None: devolver _error(resultado.message)
    devolver _ok(_format_index_success(resultado))
```
`_parse_index_arguments` sigue exactamente el orden de RF-12 a RF-14:
```text
si "path" no está:                         devolver MSG_PATH_REQUIRED
path = args["path"]
si path no es str:                         devolver MSG_PATH_NOT_TEXT
si path.strip() == "":                     devolver MSG_PATH_REQUIRED
si not path.lower().endswith(".py"):       devolver MSG_EXTENSION
si "content" no está:                      devolver MSG_CONTENT_REQUIRED
content = args["content"]
si content no es str:                      devolver MSG_CONTENT_NOT_TEXT
devolver ((path, content), None)
```
Después se delega en `rag.index_file`, que comprueba vacío, tamaño, tope de fragmentos y representaciones en su orden. La ruta y el contenido se entregan tal cual: no se recortan, no se normalizan, no se resuelven y no se comprueba que existan.

### Formato de la búsqueda
Cada fragmento se muestra en su propio bloque. Los bloques se unen con una línea en blanco (`\n\n`) y no se añade ningún texto antes ni después.
```text
Fragmento {index} de {total}
Ruta: {chunk.file_path}
Símbolo: {chunk.symbol_name}
Líneas: {chunk.start_line}–{chunk.end_line}
Relevancia: {relevancia}
Texto:
{chunk.content}
```
- `index` empieza en 1 y `total` es el número de fragmentos devueltos por `rag.search` (de 1 a 5).
- Se usa un guion de raya (`–`, U+2013) entre las dos líneas.
- `relevancia` se calcula con `_format_relevance`: se acota la puntuación a `[0, 1]`, se formatea con dos decimales y se cambia el punto por una coma (`0,30`, `0,87`, `1,00`). El mismo valor produce siempre el mismo texto.
- El texto del fragmento se copia exactamente, sin recortarlo, resumirlo ni completarlo.

### Formato del indexado con éxito
```text
{result.message}

Ruta: {result.file_path}
Fragmentos indexados: {result.chunks_indexed}
Total del índice: {result.total_chunks}
Troceado por ventanas: {sí|no}
```
- La primera línea es el mensaje de éxito de `rag.index_file`, reutilizado literalmente; puede incluir el aviso de troceado por ventanas que añade la spec 002.
- `chunks_indexed` y `total_chunks` se formatean con `_format_number` (punto de miles).
- `used_windows` se muestra como `sí` o `no`.
- No se incluye la lista de fragmentos.

### Arranque
```text
main():
    _configure_logging()
    asyncio.run(_serve())

_serve():
    servidor = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await servidor.run(read_stream, write_stream,
                           servidor.create_initialization_options())

si __name__ == "__main__": main()
```
No se abre ningún puerto, no se importa `uvicorn` ni `fastapi` y no se sirve la interfaz web. Toda la comunicación ocurre por los flujos de `stdio_server()`.

## Mensajes exactos
### Mensajes propios de esta capa
| Constante | Texto exacto |
|---|---|
| `MSG_QUERY_REQUIRED` | `Falta la consulta: el argumento «query» es obligatorio y debe ser un texto.` |
| `MSG_QUERY_NOT_TEXT` | `El argumento «query» debe ser un texto.` |
| `MSG_PATH_REQUIRED` | `Falta la ruta del archivo: el argumento «path» es obligatorio y no puede estar vacío.` |
| `MSG_PATH_NOT_TEXT` | `El argumento «path» debe ser un texto.` |
| `MSG_EXTENSION` | `Solo se aceptan archivos de Python (.py).` |
| `MSG_CONTENT_REQUIRED` | `Falta el contenido del archivo: el argumento «content» es obligatorio y debe ser un texto.` |
| `MSG_CONTENT_NOT_TEXT` | `El argumento «content» debe ser un texto.` |
| `MSG_EMPTY_INDEX` | `Todavía no hay código indexado. Indexa un archivo .py con la herramienta index_file para poder buscar en él.` |
| `MSG_UNKNOWN_TOOL` | `La herramienta «{name}» no existe. Usa search_code para buscar o index_file para indexar un archivo .py.` |
| `MSG_INTERNAL_ERROR` | `Ocurrió un error interno al ejecutar la herramienta. Inténtalo de nuevo.` |

- `MSG_EXTENSION` coincide palabra por palabra con `MSG_INVALID_EXTENSION` de `app/main.py:71`. Se declara aquí para no importar la capa HTTP; una prueba comprueba la igualdad.
- `MSG_EMPTY_INDEX` es el único mensaje adaptado: el original de `rag.py` invita a «Sube un archivo .py» por la interfaz web. El nuevo nombra `index_file` y mantiene el mismo sentido.
- Los mensajes de argumento faltante incluyen «debe ser un texto» para cubrir también RF-6, RF-14 y RF-27; los de tipo incorrecto son más específicos.

### Mensajes reutilizados literalmente
| Caso | Origen | Cómo se obtiene |
|---|---|---|
| Consulta vacía o de solo espacios | `rag.EMPTY_QUERY_MESSAGE` | `rag.search` lo devuelve; se marca error |
| Consulta de más de 1.000 caracteres | `rag.QUERY_TOO_LONG_MESSAGE` | `rag.search` lo devuelve; se marca error |
| Índice con fragmentos y ninguno relevante | `rag.NO_RELEVANT_MESSAGE` | `rag.search` lo devuelve; sin error |
| Contenido vacío o de solo espacios | `rag.EMPTY_CONTENT_MESSAGE` | `rag.index_file` lo devuelve; error |
| Contenido de más de 1.048.576 bytes | `rag.TOO_LARGE_MESSAGE` | `rag.index_file` lo formatea con el tamaño; error |
| Más de 1.000 fragmentos | `rag.TOO_MANY_CHUNKS_MESSAGE` | `rag.index_file` lo formatea con la cantidad; error |
| Fallo al calcular representaciones | `rag.EMBEDDING_FAILED_MESSAGE` | `rag.index_file` lo devuelve; error |
| Éxito del indexado | `rag.INDEX_SUCCESS_MESSAGE` | `rag.index_file` lo formatea; primera línea del éxito |
| Aviso de troceado por ventanas | `rag.WINDOWS_CHUNKING_NOTE` | Ya viene dentro del mensaje de éxito cuando corresponde |

No se duplican esos textos en `mcp_server.py`: se usan los objetos que devuelve `rag.search` o `rag.index_file`. Las pruebas comparan igualdad exacta con el mensaje que produce la capacidad para la misma entrada.

## Decisiones y alternativas descartadas
| Decisión | Por qué | Alternativa descartada |
|---|---|---|
| Servidor de bajo nivel `mcp.server.Server` | Permite fijar el esquema y los mensajes exactos en español; no impone validación ni errores del SDK | `MCPServer`: valida con Pydantic y devuelve mensajes técnicos en inglés (RF-24, RF-27, RNF-3) |
| Esquema de argumentos escrito a mano | Control exacto de nombres, tipos, obligatoriedad y descripciones en español | Generarlo con Pydantic: los errores y las descripciones dependerían del SDK |
| Validación propia de argumentos | El servidor de bajo nivel no valida; la spec exige mensajes concretos y orden de comprobaciones | Confiar en el esquema: un cliente podría enviar otro tipo y la operación fallaría con una excepción |
| `asyncio.to_thread` para `rag.search` e `rag.index_file` | Las dos capacidades son bloqueantes y pueden cargar el modelo; el bucle de eventos sigue atendiendo el protocolo | Llamarlas directamente en el manejador `async`: una búsqueda o un indexado largo bloquea la conexión |
| Índice `rag.store` del proceso | Es el índice de la spec 002 y cumple RF-22 sin duplicar almacenamiento | Crear un `VectorStore` propio: dos índices y dos fuentes de verdad |
| Resultado de búsqueda en texto con bloques | Es lo que pide la spec: texto legible, citable y con un bloque por fragmento | JSON estructurado: mejor para parsear, peor para que el modelo lo lea y no es lo que fija la spec |
| Relevancia con dos decimales y coma | Formato estable, verificable y en español | `str(score)`: número de decimales variable; punto decimal: menos natural en español |
| Éxito del indexado con mensaje y cuatro campos | RF-10 exige mensaje literal, ruta, `chunks_indexed`, total y `used_windows` | Devolver solo el mensaje: faltan datos; devolver la lista de fragmentos: la spec la excluye |
| `_format_number` local | La capa MCP necesita presentar cifras; `rag._format_number` es privada de otra capa | Llamar a `rag._format_number`: rompe la encapsulación y crea dependencia de un detalle interno |
| `MSG_EXTENSION` local e igual al de `main.py` | Evita que la capa MCP importe la capa HTTP y mantiene la coherencia de la regla `.py` | Importar `main.MSG_INVALID_EXTENSION`: acopla MCP a FastAPI y al arranque HTTP |
| `MSG_EMPTY_INDEX` adaptado | El original habla de subir un archivo por la web y aquí no existe esa interfaz | Reutilizar el original: confundiría al agente, que no puede subir nada por HTTP desde MCP |
| Argumento no declarado se ignora | La spec lo fija así; el esquema no declara `additionalProperties: false` | Rechazarlo: contradice el caso límite de la spec |
| Herramienta desconocida devuelve resultado con error | Mantiene la conexión, responde en español y permite al agente corregir | Error de protocolo: el SDK lo redactaría en inglés y cerraría el intercambio |
| Capturar solo `Exception` | Convierte fallos normales en un resultado; no oculta cancelaciones ni la parada del proceso | Capturar `BaseException`: se tragarían `KeyboardInterrupt` y cancelaciones |
| Registrar solo el tipo de excepción | RNF-2: el texto del error puede contener datos de la entrada | Registrar la traza o `str(exc)`: riesgo de filtrar contenido, ruta o consulta |
| Sin `print` y registros a `stderr` | RNF-1: la salida estándar solo lleva protocolo | `print` o logging por defecto: riesgo de corromper el protocolo |
| Sin parámetro `hoy` | No hay ninguna decisión que dependa de la fecha ni de la hora | Añadirlo por convención: sería un parámetro sin uso |

## Estrategia de tests (`pytest`)
Todas las pruebas pasan sin red, sin claves y sin descargar el modelo. Las que necesitan protocolo usan `InMemoryTransport` + `ClientSession` dentro de `asyncio.run` (no se usa `pytest-asyncio`, que no está en `requirements.txt`). Las que prueban la lógica llaman directamente a `_dispatch`, `_search`, `_index`, `_parse_*` y `_format_*`. Los dobles de embeddings devuelven vectores deterministas y registran los textos; el índice se sustituye por un `VectorStore()` limpio en cada prueba. Las pruebas de protocolo usan un `create_server()` nuevo por prueba.

| RF / RNF / caso | Prueba |
|---|---|
| RF-1 | `initialize` + `list_tools`: exactamente dos herramientas, `search_code` e `index_file`, en ese orden; descripciones iguales a las constantes; `input_schema` con `type: object`, `query` o `path`/`content` como `string` y en `required`; ningún argumento opcional; sin recursos ni plantillas anunciados |
| RF-2 | `create_server()` + `list_tools` sin clave, sin red y con el índice vacío; no se importa ni se carga el modelo |
| RF-3 | Con un `rag.search` falso que devuelve 1, 3 y 5 resultados: un bloque por fragmento, en el mismo orden, con ruta, símbolo, líneas, relevancia y texto exactos; relevancia `0,00`, `0,30`, `0,87`, `1,00` y acotada si llega fuera de `[0, 1]` |
| RF-4 | Con `rag.search` real y el índice vacío: `query=""` y `"   "` devuelven error con `rag.EMPTY_QUERY_MESSAGE`; la prueba compara igualdad literal |
| RF-5 | Con `rag.search` real: 1.000 caracteres pasan la validación (índice vacío → `EMPTY_INDEX`), 1.001 devuelven error con `rag.QUERY_TOO_LONG_MESSAGE`; 1.001 espacios devuelven `EMPTY_QUERY` porque el vacío se comprueba antes |
| RF-6 | Sin `query`, `query=None`, `query=1`, `query=[]` y `query={}`: error con `MSG_QUERY_REQUIRED` o `MSG_QUERY_NOT_TEXT`; un `rag.search` que falla si se llama demuestra que no se busca |
| RF-7 | Índice vacío y consulta válida: `is_error is False`, texto exacto `MSG_EMPTY_INDEX`, distinto de `rag.EMPTY_INDEX_MESSAGE` y con `index_file` y `.py` |
| RF-8 | Índice con un fragmento de puntuación 0,10 y consulta con vector `[1, 0]`: `is_error is False` y texto igual a `rag.NO_RELEVANT_MESSAGE` |
| RF-9 | Un `rag.search` falso devuelve tres resultados con rutas y líneas distintas: la respuesta tiene exactamente esos tres bloques, en el mismo orden, sin añadir, quitar ni reordenar |
| RF-10 | `rag.index_file` real con doble de embeddings: el texto empieza por `result.message`, contiene `Ruta`, `Fragmentos indexados`, `Total del índice` y `Troceado por ventanas`, no contiene la lista de fragmentos y los números coinciden con el `IndexResult` |
| RF-11 | Un `rag.index_file` falso registra los argumentos: recibe `path` y `content` exactos, sin recortar; rutas `../../etc/passwd.py`, `/etc/passwd.py`, `C:\Windows\System32\evil.py`, `<b>a</b>.py`, `"a".py` y `a\nb.py` se conservan tal cual; `builtins.open` sustituido por una función que falla no se llama |
| RF-12 | Sin `path`, `path=""`, `path="   "` y `path="\n\t"`: error `MSG_PATH_REQUIRED`; el `rag.index_file` falso no se llama |
| RF-13 | `a.txt`, `a.js`, `a.py.txt`, `py`, `a.pyi` y `"a.py "`: error `MSG_EXTENSION`; `a.PY`, `app/Main.PY`, `.py` y `" a.py"` se aceptan; el mensaje es igual a `main.MSG_INVALID_EXTENSION`; la extensión se comprueba antes que el contenido |
| RF-14 | Sin `content`, `content=None`, `content=1`, `content=[]`: error `MSG_CONTENT_REQUIRED` o `MSG_CONTENT_NOT_TEXT`; la extensión gana si además es inválida; el `rag.index_file` falso no se llama |
| RF-15 | `rag.index_file` real: `content=""`, `"   "`, `"\n\n"` devuelven error con `rag.EMPTY_CONTENT_MESSAGE`; el índice queda igual |
| RF-16 | 1.048.576 bytes se aceptan; 1.048.577 devuelven error con el mensaje de `rag.index_file` para el mismo contenido; el índice queda igual; 1.100.000 espacios se rechazan por vacío, no por tamaño |
| RF-17 | 1.000 funciones se indexan; 1.001 devuelven error con el mensaje de `rag.index_file`; un doble de embeddings que falla si se usa demuestra que no se calculan representaciones; el índice queda igual |
| RF-18 | Un doble de `_get_model` que lanza: error con `rag.EMBEDDING_FAILED_MESSAGE`; el índice queda igual |
| RF-19 | Con el índice real: cada rechazo (ruta, extensión, contenido ausente, vacío, tamaño, tope y representaciones) deja `store.count` y una instantánea de `store.search` iguales a las de antes; la versión anterior de una ruta sigue buscable |
| RF-20 | Indexar `app/x.py` con contenido A y después con B: una búsqueda posterior devuelve solo los símbolos de B; no queda ningún fragmento de A |
| RF-21 | En la misma sesión de protocolo: `index_file` y después `search_code` encuentran lo recién indexado sin reiniciar |
| RF-22 | Un `VectorStore()` nuevo está vacío; `mcp_server.rag.store` es el mismo objeto que usa `rag`; no se crea otro almacén; una búsqueda tras el arranque devuelve `MSG_EMPTY_INDEX` |
| RF-23 | Dos invocaciones consecutivas en la misma sesión: el indexado de la primera es visible en la búsqueda de la segunda |
| RF-24 | Cada error de validación y cada rechazo de indexado devuelven `is_error is True`, texto en español y sin `Traceback`, sin nombres de clases internas ni detalles técnicos |
| RF-25 | Un `rag.search` que lanza `RuntimeError("secreto")`: `is_error is True`, texto `MSG_INTERNAL_ERROR`, `"secreto"` ausente del texto y de `caplog`, `RuntimeError` presente en `caplog`; una invocación posterior con un doble correcto funciona |
| RF-26 | Después de cada error, la sesión de protocolo sigue abierta y `list_tools`/`call_tool` posteriores responden; `_on_call_tool` nunca deja escapar una excepción |
| RF-27 | Cada argumento ausente y cada tipo incorrecto tiene su mensaje exacto; la operación no se ejecuta (dobles que fallan si se llaman); un argumento extra se ignora y la operación continúa |
| RF-28 | `list_tools` no publica ninguna herramienta de chat, respuesta o generación; el código no importa `bot`, `anthropic` ni define una tool de respuesta |
| RF-29 | El código no importa `fastapi`, `uvicorn` ni `app.main`; no hay puerto ni servidor HTTP; `main` usa solo `stdio_server`; el subproceso se comunica por entrada/salida estándar |
| RF-30 | Se indexa un contenido con `import os`, `os.remove("pwned.txt")`, `open("pwned.txt", "w")` y `raise SystemExit(1)`: la llamada termina con éxito o con el rechazo de la spec 002, no ejecuta nada y no crea `pwned.txt` |
| RF-31 | Con el directorio de trabajo y `tempfile.tempdir` redirigidos a `tmp_path`, tras indexar y buscar no aparece ningún archivo nuevo; `builtins.open` sustituido por una función que falla no se llama; el código no usa `tempfile`, `write_text` ni `write_bytes` |
| RF-32 | El código no importa `anthropic`, `httpx`, `requests`, `urllib` ni `socket`; con `socket.socket` y `socket.create_connection` sustituidos por funciones que fallan, indexar y buscar con dobles funciona |
| RF-33 | Se comprueban los límites heredados: `rag.MAX_RESULTS == 5`, `rag.MIN_SCORE == 0.30`, `rag.MAX_QUERY_LENGTH == 1_000`, `rag.MAX_FILE_BYTES == 1_048_576` y `rag.MAX_CHUNKS_PER_FILE == 1_000`; el comportamiento en los bordes 1.000/1.001 y 1 MiB/1 MiB+1 es el de las specs 001 y 002 |
| RNF-1 | En un subproceso `python -m app.mcp_server` con una secuencia `initialize` → `notifications/initialized` → `tools/list` → `tools/call` (búsqueda con índice vacío), cada línea no vacía de la salida estándar es JSON con `jsonrpc`; no hay texto de aplicación; el AST no contiene llamadas a `print` ni a `sys.stdout.write`; `_configure_logging` usa `sys.stderr` |
| RNF-2 | `caplog` tras un error interno contiene solo el tipo (`RuntimeError`) y no el contenido, la ruta, la consulta ni los fragmentos; la respuesta tampoco los repite |
| RNF-3 | Cada mensaje propio se compara con su texto exacto; todos están en español y ninguno contiene `Traceback`, `Exception`, `Error executing tool` ni nombres internos; la comprensibilidad se revisa a mano en T9 |
| RNF-4 | En un subproceso sin `ANTHROPIC_API_KEY` ni `.env`, `import app.mcp_server` no importa `sentence_transformers`; `create_server()` + `list_tools` funcionan sin cargar el modelo ni abrir red |
| RNF-5 | Análisis AST de `app/mcp_server.py`: no importa `ast`, `numpy`, `sentence_transformers`, `app.storage`, `app.bot` ni `app.main`; no define troceado, embeddings ni búsqueda; `mcp_server.rag is rag`; solo llama a `rag.search` y `rag.index_file` |
| RNF-6 | Toda la suite pasa con `pytest -q` sin red, sin claves y sin descargar el modelo; los dobles de embeddings y de las capacidades se usan en todas las pruebas que lo necesitan |
| RNF-7 | Las descripciones de las dos herramientas y de sus argumentos son las de este plan, están en español y explican qué hace la herramienta, qué recibe y qué devuelve; se comprueban desde `list_tools` |
| RNF-8 | 20 rutas distintas indexadas en paralelo con `ThreadPoolExecutor` mientras otros hilos buscan: sin excepciones, total de fragmentos esperado y cada ruta con una sola versión completa; `_on_call_tool` usa `asyncio.to_thread` (se sustituye para registrar la llamada) |
| RNF-9 | Tras cada error, la siguiente invocación funciona y el índice sigue coherente; el proceso de prueba no se cierra |
| RNF-10 | `requirements.txt` sigue con `mcp==2.3.0`; no se añade ninguna dependencia; `import mcp` funciona con lo declarado |
| Casos límite de ruta | Ruta con recorrido, absoluta, de Windows, HTML, comillas o saltos de línea que termina en `.py`: se guarda y se devuelve tal cual; las mismas sin `.py` se rechazan por extensión; una ruta válida que no existe en el disco se indexa igual |
| Casos límite de búsqueda | Consulta con mayúsculas, tildes, espacios repetidos, `¿?()`, emojis o caracteres especiales: no produce error y usa la normalización de la spec 001; varios fragmentos: un bloque por cada uno |
| Casos límite de índice | Archivo que no es Python válido: se indexa por ventanas y el mensaje lo indica; reindexar con contenido rechazado deja la versión anterior; reiniciar el proceso deja el índice vacío |
| Flujo completo | En una sola sesión de protocolo: `index_file` con una función `login`, `search_code` con «login» y comprobación del bloque con la ruta, el símbolo y las líneas correctas; después una consulta vacía devuelve un error y la sesión sigue viva |
| Comprobaciones manuales declaradas | Salida estándar limpia (RNF-1), comprensibilidad de los mensajes (RNF-3) y prueba con el inspector oficial (criterio de finalización). Si no hay modelo descargado o red, la parte que dependa de él se documenta como pendiente |

## Riesgos
- La API de `mcp==2.3.0` es de una versión mayor reciente: si se actualiza el pin, T0 debe repetirse. `mcp.server.fastmcp` ya no existe y `MCPServer` cambió de nombre; el plan se apoya en el servidor de bajo nivel, que es estable dentro de 2.x.
- `stdio_server()` desvía el descriptor 1 a la salida de error mientras sirve. Eso protege el protocolo de un `print` accidental, pero también puede ocultar el fallo; por eso las pruebas revisan el código y la salida del subproceso, no solo el comportamiento en ejecución.
- `asyncio.to_thread` usa el grupo de hilos por defecto. Un indexado muy grande y varias búsquedas simultáneas pueden hacer cola; es aceptable para un servidor local de una sola conexión y no cambia el contrato.
- La primera búsqueda o el primer indexado pueden tardar por la carga o descarga del modelo. Es el comportamiento diferido de la spec 001 y no se puede evitar sin cargar el modelo al arrancar, lo que incumpliría RNF-4.
- El índice vive en el proceso: reiniciar el servidor lo vacía y no se comparte con el servidor HTTP. Es lo que fija RF-22 y hay que documentarlo para quien opere el servidor.
- La prueba con el inspector oficial puede requerir el modelo descargado o red. Si no están disponibles, se declara pendiente igual que en las specs 004 y 005 y se completa después en el entorno real.
- En Windows, la entrada y la salida estándar pueden tener codificaciones distintas. `stdio_server()` las reenvuelve en UTF-8; las pruebas usan `encoding="utf-8"` en el subproceso y textos con tildes para detectar cualquier problema.
- `SEARCH_TOOL` e `INDEX_TOOL` son objetos de módulo. Se tratan como inmutables; el SDK solo los serializa y el código no los modifica. Si en el futuro se mutaran, habría que construirlos por llamada.

## Criterios para pasar a implementación
- Spec, plan y tareas aprobados; `spec.md` pasa de borrador a aprobada en T0 si aún figura como borrador.
- T0 cierra la verificación de la API de `mcp==2.3.0` y deja anotadas las diferencias o correcciones en `## Resoluciones de T0`.
- No hay aprobaciones pendientes: no se añaden dependencias, no se cambian modelos ni el formato de los chunks y los archivos nuevos son pruebas dentro de `tests/`.
- `requirements.txt` conserva `mcp==2.3.0` y el resto de versiones fijadas.
- La prueba manual con el inspector oficial queda declarada como comprobación de cierre, con la parte dependiente del modelo marcada como pendiente si no hay modelo o red.

## Resoluciones de T0
Cerrado el 2026-11-09 contra el entorno real: `venv` con Python 3.12.10 y `mcp==2.3.0` (comprobado con `importlib.metadata.version("mcp")`). No hay correcciones al plan: los seis supuestos se confirman y la tabla de `## API de MCP verificada` coincide con el paquete instalado.

| # | Supuesto | Resultado | Evidencia |
|---|---|---|---|
| 1 | `mcp.server.Server` con `on_list_tools`/`on_call_tool` en el constructor | Confirmado | `mcp/server/__init__.py:3`; `mcp/server/lowlevel/server.py:129` y `:148-157` |
| 2 | `stdio_server()` + `Server.run(...)` + `create_initialization_options()` | Confirmado | `mcp/server/stdio.py:161-162` (context manager que entrega `read_stream, write_stream`); `mcp/server/lowlevel/server.py:539` y `:703` |
| 3 | `Tool.input_schema`/`inputSchema` y `CallToolResult.is_error`/`isError` | Confirmado | `mcp_types/_types.py:1416` (`input_schema`), `:1480` (`is_error`) y `:45-48` (`alias_generator=to_camel`); serialización real observada: `{"inputSchema": ...}` y `{"isError": true}` |
| 4 | `InMemoryTransport` con `Server` de bajo nivel y `ClientSession` con `initialize`/`list_tools`/`call_tool` | Confirmado | `mcp/client/_memory.py:29-48`; `mcp/client/session.py:404-422`, `:651`, `:1278` y `:1052`; prueba en proceso con `asyncio.run`: `initialize`, `list_tools` y `call_tool` responden sin red |
| 5 | `asyncio.to_thread` en Python 3.12 y `RLock` en `rag.store` | Confirmado | `sys.version` = `3.12.10`; `asyncio.to_thread` existe; `app/storage.py:39` (`threading.RLock`) y `:166` (`store = VectorStore()`), importado por `app/rag.py:26` |
| 6 | `mcp.server.fastmcp` ya no existe y `MCPServer` es el antiguo `FastMCP` | Confirmado | `mcp/server/fastmcp.py:1-16` lanza `ModuleNotFoundError` con el mensaje de migración; `mcp/server/mcpserver/__init__.py` exporta `MCPServer`; `mcpserver/exceptions.py:43-57` documenta los mensajes técnicos en inglés (`Error executing tool <name>`) |

Notas sin impacto en el plan:
- El índice se define en `app/storage.py` (`store = VectorStore()`) y `app/rag.py` lo importa como `rag.store`; sigue siendo el mismo singleton del proceso y el objeto que usará `mcp_server`.
- `InMemoryTransport` vive en el módulo privado `mcp.client._memory` y entrega un `TransportStreams` (par de flujos), no un objeto especial; se usa con `async with` y `ClientSession` también con `async with` antes de `initialize()`. Funciona con `asyncio.run` (no hace falta `pytest-asyncio`).
- `stdio_server()` desvía temporalmente el descriptor 1 a la salida de error mientras sirve, como ya anticipaba el plan; aun así la aplicación no debe escribir en `sys.stdout`.

Comprobaciones de alcance:
- `requirements.txt` conserva `mcp==2.3.0` y no requiere dependencias nuevas: todo lo usado (`Server`, `stdio_server`, `Tool`, `CallToolResult`, `TextContent`, `InMemoryTransport`, `ClientSession`) viene del paquete `mcp` ya fijado.
- No se modifican `rag.py`, `storage.py`, `models.py`, `main.py`, `bot.py`, `static/` ni `requirements.txt`; los archivos nuevos serán pruebas en `tests/`.
- `AGENTS.md` no contradice el plan ni la constitución: `mcp_server.py` consume `rag.py` sin HTTP, no imprime en stdout y no añade dependencias.

Base en verde antes de T1: `pytest -q` → `924 passed, 1 skipped`; `ruff check .` → `All checks passed!`.
