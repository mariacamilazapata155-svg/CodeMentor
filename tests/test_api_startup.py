"""Pruebas del arranque de la aplicación: `.env` y calentamiento del modelo.

Comprueban que el `lifespan` carga el entorno antes de calentar el modelo, que
un fallo del calentamiento no impide arrancar ni filtra el texto del error, y
que importar `app.main` no carga `sentence_transformers`. No abren red, no usan
claves reales y no descargan el modelo: salvo en las pruebas que verifican
`_load_env` de verdad, `_load_env` y `rag.warm_up` se sustituyen por dobles.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main, rag
from app.storage import VectorStore

#: Variable propia de las pruebas: nunca es una clave ni un dato real.
STARTUP_VAR = "CODEMENTOR_STARTUP_VAR"
STARTUP_VALUE = "valor-desde-el-archivo"


def _write_env(path: Path, name: str, value: str) -> Path:
    """Escribe un `.env` mínimo y devuelve su ruta."""
    path.write_text(f"{name}={value}\n", encoding="utf-8")
    return path


def _clear_startup_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deja la variable sin definir y registra su estado para restaurarla.

    `load_dotenv` escribe en `os.environ` directamente, así que `monkeypatch`
    no podría revertirlo si solo se borrara con `delenv` cuando la variable no
    existía. Fijarla antes y borrarla después hace que el teardown de
    `monkeypatch` restaure el valor original.
    """
    monkeypatch.setenv(STARTUP_VAR, "valor-temporal")
    monkeypatch.delenv(STARTUP_VAR)


# --- `lifespan` (RF-19) -----------------------------------------------------


def test_lifespan_loads_env_before_warming_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con `with TestClient`, primero se carga el entorno y después el modelo."""
    order: list[str] = []
    monkeypatch.setattr(main, "_load_env", lambda: order.append("env"))
    monkeypatch.setattr(rag, "warm_up", lambda: order.append("warm_up"))

    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200

    assert order == ["env", "warm_up"]


def test_startup_does_not_run_without_context_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin usar el cliente como gestor de contexto, el arranque no se ejecuta."""
    calls: list[str] = []
    monkeypatch.setattr(main, "_load_env", lambda: calls.append("env"))
    monkeypatch.setattr(rag, "warm_up", lambda: calls.append("warm_up"))

    client = TestClient(main.app)

    assert client.get("/health").status_code == 200
    assert calls == []


# --- `_load_env` (RF-19 y RF-21) --------------------------------------------


def test_load_env_defines_variable_from_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un `.env` existente define la variable que no estaba en el entorno."""
    _clear_startup_var(monkeypatch)
    env_path = _write_env(tmp_path / ".env", STARTUP_VAR, STARTUP_VALUE)

    main._load_env(env_path)

    assert os.environ[STARTUP_VAR] == STARTUP_VALUE


def test_load_env_does_not_override_existing_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si la variable ya está definida, el valor del entorno gana (`override=False`)."""
    monkeypatch.setenv(STARTUP_VAR, "valor-del-entorno")
    env_path = _write_env(tmp_path / ".env", STARTUP_VAR, STARTUP_VALUE)

    main._load_env(env_path)

    assert os.environ[STARTUP_VAR] == "valor-del-entorno"


def test_load_env_ignores_missing_file(tmp_path: Path) -> None:
    """Una ruta de `.env` inexistente no lanza ningún error."""
    main._load_env(tmp_path / "no-existe.env")


# --- Fallo del calentamiento (RF-20 y RNF-3) --------------------------------


class _FixedModel:
    """Doble del modelo de embeddings que no descarga nada ni usa red."""

    def encode(self, texts: list[str], normalize_embeddings: bool = True) -> np.ndarray:
        """Devuelve una fila constante por texto, ya normalizable."""
        return np.ones((len(texts), 2), dtype=np.float32)


def test_warm_up_failure_does_not_block_startup_and_next_request_retries(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un fallo al calentar se registra sin texto, el cliente arranca y se reintenta.

    El doble de `_get_model` falla solo la primera vez: esa llamada es la que
    hace `rag.warm_up` durante el arranque. La primera petición que usa el
    modelo (`/upload` con el indexado real) vuelve a pedirlo y funciona, así que
    el fallo no dejó el modelo en un estado irrecuperable.
    """
    calls: list[str] = []

    def model_loader() -> _FixedModel:
        calls.append("load")
        if len(calls) == 1:
            raise RuntimeError("secreto")
        return _FixedModel()

    monkeypatch.setattr(main, "_load_env", lambda: None)
    monkeypatch.setattr(rag, "_get_model", model_loader)
    monkeypatch.setattr(rag, "store", VectorStore())
    caplog.set_level(logging.WARNING, logger=main.logger.name)

    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        response = client.post(
            "/upload",
            files={
                "file": ("a.py", b"def f():\n    return 1\n", "text/x-python"),
            },
        )

    assert response.status_code == 200
    assert calls == ["load", "load"]
    assert "RuntimeError" in caplog.text
    assert "secreto" not in caplog.text


# --- Importación sin el modelo (RNF-5) --------------------------------------


def test_importing_main_and_health_do_not_import_the_embedding_model(
    tmp_path: Path,
) -> None:
    """`import app.main` y `/health` no cargan el modelo ni exigen clave.

    El cliente se usa sin `with` a propósito: así no se ejecuta el `lifespan`,
    no se calienta el modelo y se comprueba que `/health` responde por sí solo.
    El subproceso corre sin `ANTHROPIC_API_KEY` y en un directorio sin `.env`.
    """
    code = (
        "import sys\n"
        "import app.main as main_module\n"
        "before = 'sentence_transformers' in sys.modules\n"
        "from fastapi.testclient import TestClient\n"
        "response = TestClient(main_module.app).get('/health')\n"
        "after = 'sentence_transformers' in sys.modules\n"
        "print(before, after, response.status_code, response.json()['status'])\n"
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
        cwd=tmp_path,
        env=environment,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "False False 200 ok"
