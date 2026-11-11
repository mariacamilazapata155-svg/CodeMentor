"""Pruebas de la aplicación HTTP en ejecución: `/health` y errores del framework.

Comprueban que `/health` no depende de la clave, del modelo ni del índice, y
que 404, 405, 422, 400 y 500 llegan con el formato de error propio y sin la
clave `detail`. No abren red, no usan claves reales y no cargan el modelo.

Las rutas que provocan errores de validación, multipart o internos se
registran en una `FastAPI` desechable dentro de la prueba: la app real no se
contamina y su documentación automática sigue describiendo solo las tres
rutas de la spec.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated

import pytest
from fastapi import FastAPI, File, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from app import bot, main, rag
from app.models import ApiReason, IndexResult
from app.storage import store

#: Claves exactas del cuerpo de error (RF-14).
ERROR_KEYS = {"message", "reason"}


class _Body(BaseModel):
    """Cuerpo mínimo para provocar un error de validación."""

    message: str


def _client(application: FastAPI) -> TestClient:
    """Crea un cliente que devuelve la respuesta 500 en lugar de relanzarla."""
    return TestClient(application, raise_server_exceptions=False)


def _make_test_app() -> FastAPI:
    """Crea una app desechable con los tres manejadores reales de `main.py`.

    No registra rutas de la aplicación real ni el middleware de tamaño: cada
    prueba añade solo la ruta que necesita para provocar su error.
    """
    test_app = FastAPI()
    test_app.add_exception_handler(RequestValidationError, main._on_validation_error)
    test_app.add_exception_handler(StarletteHTTPException, main._on_http_exception)
    test_app.add_exception_handler(Exception, main._on_unhandled)
    return test_app


def _assert_error(
    response: Response,
    status: int,
    reason: ApiReason,
    message: str,
) -> None:
    """Comprueba estado, formato de error y ausencia de `detail`."""
    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/json")

    body = response.json()

    assert set(body) == ERROR_KEYS
    assert "detail" not in body
    assert body["reason"] == reason.value
    assert body["message"] == message


# --- GET /health (RF-1) -----------------------------------------------------


def test_health_returns_ok_without_model_index_or_key(
    monkeypatch: pytest.MonkeyPatch,
    set_api_key,
) -> None:
    """`/health` responde sin clave, sin cargar el modelo y sin tocar el índice."""

    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("no debe llamarse durante /health")

    set_api_key(None)
    monkeypatch.setattr(rag, "warm_up", fail)
    monkeypatch.setattr(bot, "_get_client", fail)

    before = store.count
    response = _client(main.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert store.count == before


# --- Rutas bloqueantes en hilos (RNF-2) -------------------------------------


def test_health_responds_while_a_slow_upload_is_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una subida lenta no bloquea `/health` (RNF-2).

    `upload` se declara `def`, así que FastAPI la ejecuta en un hilo: mientras
    el indexado falso espera, el bucle del servidor sigue libre y `/health`
    responde. El cliente se usa como gestor de contexto para compartir un solo
    bucle entre las dos peticiones; `_load_env` y `rag.warm_up` se sustituyen
    para que el arranque no cargue nada.
    """
    started = threading.Event()
    release = threading.Event()

    def slow_index(path: str, source: str) -> IndexResult:
        """Espera a que la prueba libere la subida antes de devolver un éxito."""
        started.set()
        if not release.wait(timeout=10):
            raise AssertionError("la subida no se liberó a tiempo")
        return IndexResult(
            file_path=path,
            chunks_indexed=1,
            total_chunks=1,
            used_windows=False,
            message="Archivo indexado.",
        )

    main.app.dependency_overrides[main.get_index_file] = lambda: slow_index
    monkeypatch.setattr(main, "_load_env", lambda: None)
    monkeypatch.setattr(rag, "warm_up", lambda: None)

    try:
        with (
            TestClient(main.app, raise_server_exceptions=False) as client,
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            upload = executor.submit(
                client.post,
                "/upload",
                files={"file": ("a.py", b"x = 1\n", "text/x-python")},
            )
            assert started.wait(timeout=5), "la subida no llegó a empezar"

            health = executor.submit(client.get, "/health")
            try:
                health_response = health.result(timeout=5)
            finally:
                release.set()

            assert health_response.status_code == 200
            assert health_response.json() == {"status": "ok"}
            assert upload.result(timeout=5).status_code == 200
    finally:
        main.app.dependency_overrides.pop(main.get_index_file, None)


# --- Errores del framework (RF-14) ------------------------------------------


def test_unknown_route_returns_not_found() -> None:
    """Una ruta inexistente responde 404 `not_found` con el formato de error."""
    response = _client(main.app).get("/no-existe")

    _assert_error(response, 404, ApiReason.NOT_FOUND, main.MSG_NOT_FOUND)


@pytest.mark.parametrize("path", ["/upload", "/chat"])
def test_get_on_post_only_route_returns_method_not_allowed(path: str) -> None:
    """`GET /upload` y `GET /chat` responden 405, no 411 ni 404."""
    response = _client(main.app).get(path)

    _assert_error(
        response,
        405,
        ApiReason.METHOD_NOT_ALLOWED,
        main.MSG_METHOD_NOT_ALLOWED,
    )


def test_validation_error_returns_invalid_request() -> None:
    """Un cuerpo que no valida responde 422 `invalid_request` (RF-13)."""
    test_app = _make_test_app()

    @test_app.post("/echo")
    def echo(payload: _Body) -> _Body:
        """Ruta de prueba que exige un cuerpo con `message`."""
        return payload

    response = _client(test_app).post("/echo", json={"otra": "cosa"})

    _assert_error(
        response,
        422,
        ApiReason.INVALID_REQUEST,
        main.MSG_INVALID_REQUEST,
    )


def test_multipart_without_boundary_returns_invalid_request() -> None:
    """Un multipart sin `boundary` responde 400 `invalid_request` (RF-14)."""
    test_app = _make_test_app()

    @test_app.post("/upload")
    def upload(file: Annotated[UploadFile, File()]) -> dict[str, str]:
        """Ruta de prueba que obliga a leer el formulario."""
        return {"name": file.filename or ""}

    response = _client(test_app).post(
        "/upload",
        content=b"contenido",
        headers={"Content-Type": "multipart/form-data"},
    )

    _assert_error(
        response,
        400,
        ApiReason.INVALID_REQUEST,
        main.MSG_INVALID_REQUEST,
    )


# --- Errores no controlados (RF-15 y RNF-3) ---------------------------------


def test_unhandled_error_hides_details_and_logs_only_the_type(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un `RuntimeError` da 500 sin su texto, pero deja su tipo en el registro."""
    caplog.set_level(logging.ERROR)
    test_app = _make_test_app()

    @test_app.get("/explota")
    def explota() -> None:
        """Ruta de prueba que lanza un error no controlado."""
        raise RuntimeError("secreto")

    response = _client(test_app).get("/explota")

    _assert_error(
        response,
        500,
        ApiReason.INTERNAL_ERROR,
        main.MSG_INTERNAL_ERROR,
    )
    assert "secreto" not in response.text
    assert "secreto" not in caplog.text
    assert "RuntimeError" in caplog.text


# --- Límite de petición (RF-17) ---------------------------------------------


def test_oversized_upload_body_is_rejected_before_reading_the_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un cuerpo de 1,2 MiB da 413 sin llegar a leer el formulario.

    El middleware solo mira `Content-Length`, así que la petición se rechaza
    antes de que el enrutado procese el multipart. Se sustituye
    `starlette.requests.Request.form` por una función que falla: si se llegara
    a leer el cuerpo, la prueba lo detectaría en lugar de dar por bueno el 413.
    """
    form_calls: list[Request] = []

    async def fail_form(self: Request, *args: object, **kwargs: object) -> None:
        """Registra que se intentó leer el formulario y falla."""
        form_calls.append(self)
        raise AssertionError("no debe leerse el formulario")

    monkeypatch.setattr(Request, "form", fail_form)
    body = b"x" * 1_200_000
    assert len(body) > main.UPLOAD_BODY_LIMIT

    response = _client(main.app).post(
        "/upload",
        content=body,
        headers={"Content-Type": "multipart/form-data; boundary=limite"},
    )

    _assert_error(
        response,
        413,
        ApiReason.PAYLOAD_TOO_LARGE,
        main.MSG_UPLOAD_TOO_LARGE,
    )
    assert form_calls == []
