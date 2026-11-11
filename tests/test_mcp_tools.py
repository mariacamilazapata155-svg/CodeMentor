"""Pruebas de la publicación de herramientas del servidor MCP.

Usan el transporte en memoria y un cliente MCP real dentro de `asyncio.run`:
no abren red, no necesitan clave y no tocan el índice. Comprueban el contrato
público de las dos herramientas y que no se anuncian otras capacidades.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession
from mcp.types import InitializeResult, ListToolsResult

from app import mcp_server, rag
from app.storage import VectorStore


async def _initialize_and_list_tools() -> tuple[InitializeResult, ListToolsResult]:
    """Conecta un cliente en memoria, inicializa y pide la lista de herramientas."""
    server = mcp_server.create_server()
    async with (
        InMemoryTransport(server) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialization = await session.initialize()
        tools = await session.list_tools()
        return initialization, tools


# --- Lista de herramientas (RF-1, RF-2 y RNF-7) ------------------------------


def test_list_tools_publishes_exactly_two_tools_in_order() -> None:
    """Se publican exactamente `search_code` e `index_file`, en ese orden."""
    _, tools = asyncio.run(_initialize_and_list_tools())

    assert [tool.name for tool in tools.tools] == [
        mcp_server.SEARCH_TOOL_NAME,
        mcp_server.INDEX_TOOL_NAME,
    ]
    assert len(tools.tools) == 2


def test_tool_descriptions_match_the_plan_and_are_in_spanish() -> None:
    """Las descripciones son las constantes del plan y están en español."""
    _, tools = asyncio.run(_initialize_and_list_tools())

    assert tools.tools[0].description == mcp_server.SEARCH_DESCRIPTION
    assert tools.tools[1].description == mcp_server.INDEX_DESCRIPTION
    for tool in tools.tools:
        assert tool.description
        assert any(char in tool.description for char in "áéíóúñ¿¡")


def test_search_schema_declares_only_a_required_text_query() -> None:
    """`search_code` solo declara `query`, de tipo texto y obligatorio."""
    _, tools = asyncio.run(_initialize_and_list_tools())
    schema = tools.tools[0].input_schema

    assert schema["type"] == "object"
    assert list(schema["properties"]) == ["query"]
    assert schema["properties"]["query"]["type"] == "string"
    assert schema["required"] == ["query"]


def test_index_schema_declares_only_required_text_path_and_content() -> None:
    """`index_file` solo declara `path` y `content`, ambos texto y obligatorios."""
    _, tools = asyncio.run(_initialize_and_list_tools())
    schema = tools.tools[1].input_schema

    assert schema["type"] == "object"
    assert list(schema["properties"]) == ["path", "content"]
    assert schema["properties"]["path"]["type"] == "string"
    assert schema["properties"]["content"]["type"] == "string"
    assert schema["required"] == ["path", "content"]


def test_no_tool_declares_optional_arguments_or_closed_properties() -> None:
    """Todos los argumentos son obligatorios y se permiten propiedades extra."""
    _, tools = asyncio.run(_initialize_and_list_tools())

    for tool in tools.tools:
        schema = tool.input_schema
        assert set(schema["required"]) == set(schema["properties"])
        assert schema.get("additionalProperties") is not False


def test_no_resources_or_prompts_are_announced() -> None:
    """El servidor solo anuncia la capacidad de herramientas."""
    initialization, _ = asyncio.run(_initialize_and_list_tools())

    assert initialization.capabilities.tools is not None
    assert initialization.capabilities.resources is None
    assert initialization.capabilities.prompts is None


def test_create_server_and_list_tools_need_no_key_and_leave_the_index_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La lista funciona sin clave y con el índice vacío, sin modificarlo."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fresh_store = VectorStore()
    monkeypatch.setattr(rag, "store", fresh_store)
    assert fresh_store.count == 0

    _, tools = asyncio.run(_initialize_and_list_tools())

    assert len(tools.tools) == 2
    assert fresh_store.count == 0


def test_importing_the_server_does_not_import_the_embedding_model() -> None:
    """`import app.mcp_server` y `list_tools` no cargan `sentence_transformers`."""
    code = (
        "import asyncio, sys\n"
        "import app.mcp_server as m\n"
        "from mcp.client._memory import InMemoryTransport\n"
        "from mcp.client.session import ClientSession\n"
        "\n"
        "async def main():\n"
        "    async with InMemoryTransport(m.create_server()) as (read, write):\n"
        "        async with ClientSession(read, write) as session:\n"
        "            await session.initialize()\n"
        "            result = await session.list_tools()\n"
        "            return [tool.name for tool in result.tools]\n"
        "\n"
        "names = asyncio.run(main())\n"
        "print('sentence_transformers' in sys.modules, names)\n"
    )
    project_root = Path(__file__).resolve().parents[1]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() != "ANTHROPIC_API_KEY"
    }
    previous_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{project_root}{os.pathsep}{previous_path}"
        if previous_path
        else str(project_root)
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=project_root,
        env=environment,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "False ['search_code', 'index_file']"
