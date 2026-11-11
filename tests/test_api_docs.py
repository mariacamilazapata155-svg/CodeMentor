"""Pruebas de la documentación automática y de la forma de las rutas (RF-23).

Comprueban que `/openapi.json` describe las tres rutas con sus errores en
español, que las rutas bloqueantes se declaran síncronas, que `main.py` no usa
el troceado ni la construcción de mensajes de las capas de abajo y que las
capacidades entran por `Depends`. No abren red, no usan claves y no cargan el
modelo.
"""

import inspect
import re
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import main
from app.models import ChatMessage, ChatResponse, IndexResult

#: Estados de error que declara cada ruta (RF-23).
HEALTH_ERROR_STATUSES = (405,)
UPLOAD_ERROR_STATUSES = (400, 411, 413, 422, 500)
CHAT_ERROR_STATUSES = (*UPLOAD_ERROR_STATUSES, 502, 503, 504)

#: Rutas públicas y su método, en el orden de la spec.
ROUTES = (
    ("/health", "get"),
    ("/upload", "post"),
    ("/chat", "post"),
)

#: Marcas que solo aparecen en texto redactado en español.
SPANISH_MARKERS = re.compile(r"[áéíóúüñÁÉÍÓÚÜÑ¿¡]")


def _openapi() -> dict[str, Any]:
    """Descarga la documentación sin ejecutar el arranque ni cargar el modelo."""
    response = TestClient(main.app).get("/openapi.json")

    assert response.status_code == 200
    return response.json()


def _operation(spec: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    """Devuelve la operación documentada de una ruta."""
    return spec["paths"][path][method]


def _assert_spanish(text: str, where: str) -> None:
    """Comprueba que un texto de documentación no está vacío y es español."""
    assert text.strip(), f"{where} está vacío"
    assert SPANISH_MARKERS.search(text), f"{where} no parece estar en español: {text!r}"


def test_openapi_json_lists_the_three_routes() -> None:
    """`/openapi.json` contiene las tres rutas públicas con su método."""
    paths = _openapi()["paths"]

    assert {"/health", "/upload", "/chat"} <= set(paths)
    for path, method in ROUTES:
        assert method in paths[path]


@pytest.mark.parametrize(
    ("path", "method", "statuses"),
    [
        ("/health", "get", HEALTH_ERROR_STATUSES),
        ("/upload", "post", UPLOAD_ERROR_STATUSES),
        ("/chat", "post", CHAT_ERROR_STATUSES),
    ],
)
def test_each_route_declares_its_error_responses(
    path: str,
    method: str,
    statuses: tuple[int, ...],
) -> None:
    """Cada estado de error se declara con `ErrorResponse` y texto en español."""
    responses = _operation(_openapi(), path, method)["responses"]

    for status in statuses:
        response = responses.get(str(status))

        assert response is not None, f"{path} no declara el estado {status}"
        _assert_spanish(response.get("description", ""), f"{path} {status}")

        schema = response["content"]["application/json"]["schema"]
        assert schema["$ref"].endswith("/ErrorResponse")


def test_api_title_and_description_are_in_spanish() -> None:
    """El título y la descripción de la API están redactados en español."""
    info = _openapi()["info"]

    _assert_spanish(info["title"], "título de la API")
    _assert_spanish(info["description"], "descripción de la API")


@pytest.mark.parametrize(("path", "method"), ROUTES)
def test_route_summaries_and_descriptions_are_in_spanish(
    path: str,
    method: str,
) -> None:
    """Cada ruta tiene un resumen y una descripción en español."""
    operation = _operation(_openapi(), path, method)

    _assert_spanish(operation["summary"], f"resumen de {path}")
    _assert_spanish(operation["description"], f"descripción de {path}")


def test_blocking_routes_are_sync_and_health_is_async() -> None:
    """`upload` y `chat` se ejecutan en hilos y `health` es asíncrona (RNF-2)."""
    assert inspect.iscoroutinefunction(main.health)
    assert not inspect.iscoroutinefunction(main.upload)
    assert not inspect.iscoroutinefunction(main.chat)


@pytest.mark.parametrize("attribute", ["chunk_python_file", "_build_messages"])
def test_main_does_not_import_or_use_lower_layer_internals(attribute: str) -> None:
    """`main.py` no importa ni usa el troceado ni la construcción de mensajes."""
    assert attribute not in vars(main)
    assert not hasattr(main, attribute)


def test_capabilities_are_injected_through_dependencies() -> None:
    """Las rutas declaran `get_index_file` y `get_answer` como dependencias."""
    routes = {
        route.path: route for route in main.app.routes if isinstance(route, APIRoute)
    }

    upload_calls = {
        dependency.call for dependency in routes["/upload"].dependant.dependencies
    }
    chat_calls = {
        dependency.call for dependency in routes["/chat"].dependant.dependencies
    }

    assert main.get_index_file in upload_calls
    assert main.get_answer in chat_calls


def test_dependency_overrides_replace_the_capabilities_without_the_model() -> None:
    """Sustituir las dependencias evita el indexado y la respuesta reales."""
    calls: list[tuple[str, str]] = []

    def fake_index(path: str, source: str) -> IndexResult:
        """Registra la ruta y devuelve un éxito mínimo."""
        calls.append(("index", path))
        return IndexResult(
            file_path=path,
            chunks_indexed=1,
            total_chunks=1,
            used_windows=False,
            message="Archivo indexado.",
        )

    def fake_answer(message: str, history: list[ChatMessage]) -> ChatResponse:
        """Registra la pregunta y devuelve una respuesta fundamentada."""
        calls.append(("answer", message))
        return ChatResponse(reply="Respuesta de prueba.")

    main.app.dependency_overrides[main.get_index_file] = lambda: fake_index
    main.app.dependency_overrides[main.get_answer] = lambda: fake_answer

    try:
        client = TestClient(main.app)
        upload = client.post(
            "/upload",
            files={"file": ("a.py", b"x = 1\n", "text/x-python")},
        )
        chat = client.post("/chat", json={"message": "hola"})
    finally:
        main.app.dependency_overrides.pop(main.get_index_file, None)
        main.app.dependency_overrides.pop(main.get_answer, None)

    assert upload.status_code == 200
    assert chat.status_code == 200
    assert calls == [("index", "a.py"), ("answer", "hola")]
