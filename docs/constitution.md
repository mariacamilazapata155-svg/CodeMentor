# Constitución de CodeMentor

Orden de autoridad: esta constitución > `spec.md` > `plan.md` y `tasks.md` > código. `AGENTS.md` define cómo trabaja el agente y no puede contradecirla.

1. **Stack mínimo**: Python 3.12 y las dependencias de `requirements.txt` (FastAPI, Pydantic v2, numpy, sentence-transformers, Anthropic SDK, MCP y herramientas de prueba); frontend sin frameworks. Cualquier dependencia nueva se justifica y se aprueba antes de añadirla.
2. **La spec manda**: todo cambio funcional nace de una spec en `specs/NNN-*/`; si código y spec discrepan, el cambio corrige uno de los dos y deja ambos alineados.
3. **Lógica lejos de la interfaz**: las capas son `main.py → bot.py → rag.py → storage.py`; `main.py` solo traduce HTTP y `static/` solo presenta; chunking, embeddings y búsqueda viven en `rag.py`/`storage.py`, y `mcp_server.py` consume `rag.py` sin pasar por HTTP.
4. **Tests sin red ni instalaciones**: `pytest -q` y `ruff check .` pasan solo con `requirements.txt`, sin API key, sin descargar modelos y mockeando Anthropic y embeddings. Las pruebas opcionales con el modelo real se omiten por defecto.
5. **Datos del usuario protegidos**: el código subido nunca se ejecuta, importa ni evalúa, y la aplicación no lo guarda en disco salvo que una spec aprobada lo defina. A Claude solo se envían la pregunta, el historial y los fragmentos recuperados; la clave vive en una variable de entorno y `.env` está en `.gitignore`.
6. **Respuestas fundamentadas**: el bot responde solo con los fragmentos recuperados y, si no alcanzan, lo dice; las citas (archivo, símbolo y líneas) salen de los resultados de la búsqueda, nunca del texto del modelo.
7. **Dos idiomas, un criterio**: identificadores, archivos de código y commits en inglés; comentarios, docstrings, UI, mensajes de error y documentos de spec (incluidas sus carpetas) en español.

Un cambio que incumpla un principio no se integra hasta enmendarlo. Enmendar es editar este archivo y anotar al final la fecha y el motivo.
