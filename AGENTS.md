# AGENTS.md — CodeMentor

CodeMentor es un asistente RAG que indexa código fuente (archivos `.py`, y opcionalmente `.js`) y responde preguntas como "¿dónde está la lógica de autenticación?" citando archivo, función y líneas. 

## Stack y estructura

- Python 3.12
- FastAPI + Pydantic v2 (API y validación); versiones exactas en requirements.txt
- sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`) + numpy (embeddings y similitud coseno)
- Anthropic SDK (`anthropic`) para generar respuestas
- MCP SDK (`mcp`) para exponer la búsqueda como herramienta
- Frontend en HTML/CSS/JS vanilla (sin frameworks)
- pytest + ruff para pruebas y lint

```
app/
  models.py      # Esquemas Pydantic compartidos entre capas
  storage.py     # Repositorio de vectores en memoria (aislado para poder migrarlo a SQLite)
  rag.py         # Chunking de código, embeddings y búsqueda. No sabe nada de HTTP ni del LLM
  bot.py         # System prompt + orquestación RAG → modelo. Aquí vive el "criterio" del bot
  main.py        # Solo HTTP: rutas /upload y /chat, delega a las capas de abajo
  mcp_server.py  # Misma búsqueda de rag.py expuesta como tool MCP (stdio)
static/          # index.html, style.css (tokens de diseño en variables CSS), app.js
tests/           # pytest; espeja la estructura de app/
```

Arquitectura en capas: `main.py → bot.py → rag.py → storage.py`. Cada capa solo conoce a la de abajo. `mcp_server.py` consume `rag.py` directamente.

## Comandos

```bash
# Entorno
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Ejecutar
export ANTHROPIC_API_KEY=tu_api_key
uvicorn app.main:app --reload                      # API + frontend en http://localhost:8000
python -m app.mcp_server                           # Servidor MCP (stdio)

# Probar y lint
pytest -q
ruff check .
ruff format .

# Empaquetar (no hay paso de compilación)
docker build -t codementor .
```

## Convenciones

- Código, nombres de funciones/variables y commits en inglés (`snake_case` para funciones y variables, `PascalCase` para clases).
- Comentarios, docstrings, textos de la UI y mensajes de error al usuario en español.
- Type hints en todas las funciones públicas; datos que cruzan capas van en modelos Pydantic de `models.py`, no en diccionarios sueltos.
- Cada módulo empieza con un docstring que dice qué responsabilidad tiene y qué NO hace.
- Una función = una responsabilidad. Si una función pasa de ~30 líneas, se divide.
- Estilo del frontend: solo variables CSS (`--color-*`, `--space-*`), clases tipo BEM (`.bubble--user`); nunca colores o espacios sueltos.

## Reglas de dominio / trampas conocidas

- Lee `docs/constitution.md` y la spec activa (`specs/NNN-*/`) antes de tocar código. 
- **El chunking de código NO es por párrafos.** Para Python se parte por función/clase con el módulo `ast` (`ast.parse` + `ast.get_source_segment`), guardando `lineno`/`end_lineno`. Cada chunk debe llevar ruta del archivo, nombre del símbolo y rango de líneas, porque son lo que el bot cita.
- Si `ast.parse` lanza `SyntaxError` (archivo roto o no-Python), no se aborta la subida: se cae a chunking por ventanas de líneas y se marca el chunk como tal.
- El código a nivel de módulo (imports, constantes) que queda fuera de funciones también debe indexarse, o las preguntas sobre configuración no encuentran nada.
- Los embeddings se generan con `normalize_embeddings=True`; por eso el producto punto equivale a similitud coseno. Si se cambia eso, la búsqueda se rompe en silencio.
- **Nunca ejecutar, importar ni evaluar el código subido.** Solo se lee como texto. Un archivo subido es entrada no confiable.
- El system prompt debe obligar al bot a responder solo con el contexto recuperado y a decir "no lo encontré" si no está. Sin esto alucina rutas y funciones.
- Un **servidor MCP por stdio nunca debe imprimir en stdout** (`print`, logs por defecto): corrompe el protocolo. Los logs van a stderr.
- `storage.py` es un singleton en memoria: al reiniciar el servidor se pierde el índice. Es esperado en esta versión, no es un bug.
- El modelo de embeddings tarda en cargar y es pesado: se carga una sola vez por proceso, de forma diferida (`lru_cache`), nunca dentro de una función por request. Así `import app.rag` no descarga nada y las pruebas corren sin red.
- `ANTHROPIC_API_KEY` solo viene de variable de entorno; nunca en el código ni en el repo.

## Forma de trabajar

- Antes de tocar código en un módulo nuevo o en un cambio que afecte a más de un archivo, proponer un plan corto (qué archivos, en qué orden, qué responsabilidad tiene cada uno) y esperar confirmación.
- Orden recomendado de construcción: `models.py` → `storage.py` → `rag.py` → `bot.py` → `main.py` → `static/` → `mcp_server.py` (este último, idealmente leyendo solo la documentación oficial de MCP).
- Cambios pequeños: una función o un archivo a la vez, con su prueba.
- Al terminar cada cambio, explicar en pocas líneas: qué se hizo, **por qué** se diseñó así.

## Límites

- ✅ **Siempre:** respetar la separación de capas; añadir type hints y docstring a lo nuevo; escribir o actualizar la prueba correspondiente; ejecutar `ruff check .` y `pytest -q` antes de dar algo por terminado; explicar el porqué de las decisiones.
- ✅ **Siempre:** actualizar `MEMORY.md` al terminar cada tarea. 
- ⚠ **Pregunta antes:** agregar dependencias nuevas a `requirements.txt`; crear archivos o carpetas que no estén en la estructura de arriba; cambiar los esquemas de `models.py` o el formato de los chunks; cambiar el modelo de embeddings o el modelo de Claude; pasar el storage de memoria a SQLite; escribir una implementación completa en vez de guiar.
- 🚫 **Nunca:** ejecutar o importar código subido por usuarios; escribir la API key en archivos o commits; hacer `print` en `mcp_server.py`; mover lógica de RAG a `main.py`; borrar pruebas para que pase el CI; hacer `git push --force` ni reescribir el historial.

## Verificación

Un cambio está terminado solo si:

1. `ruff check .` no reporta errores y `pytest -q` pasa. Las pruebas **mockean** la API de Anthropic y el modelo de embeddings (o usan vectores falsos) para ser rápidas y no gastar créditos.
2. Prueba manual del flujo completo con el servidor levantado:
   ```bash
   curl -F "file=@app/rag.py" http://localhost:8000/upload
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "¿Dónde se calculan los embeddings?"}'
   ```
    La respuesta debe citar el archivo, la función y las líneas correctas.
3. Prueba negativa: preguntar algo que no está en el código debe devolver "no lo encontré", no una respuesta inventada.
4. Si se tocó `mcp_server.py`: `npx @modelcontextprotocol/inspector python -m app.mcp_server` y confirmar que las tools aparecen y responden.
5. Si se tocó el frontend: abrir `http://localhost:8000`, subir un archivo y hacer una pregunta; revisar que no hay errores en la consola del navegador.

## Memoria 
- Al empezar, lee `MEMORY.md` para conocer el estado del proyecto y las decisiones tomadas. 
- Al terminar una tarea, actualízalo: estado actual, decisiones importantes (con su porqué) y errores a evitar. 
- Mantenlo breve (máximo ~50 líneas): resume o elimina lo que ya no aporte. 
- Si algo se convierte en una regla permanente, propón moverlo a `AGENTS.md` en lugar de dejarlo en la memoria. 
- No guardes nunca datos sensibles (claves, tokens, datos personales). 