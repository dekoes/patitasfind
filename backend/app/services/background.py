"""Despacho de tareas en segundo plano: Celery si hay Redis, si no BackgroundTasks de FastAPI."""
import importlib
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def _resolve(task_path: str):
    module, name = task_path.rsplit(".", 1)
    return getattr(importlib.import_module(module), name)


def dispatch(task_path: str, *args, background_tasks=None) -> str:
    """Ejecuta la tarea `task_path` (p. ej. "app.tasks.matching.match_lost_report").

    Devuelve el mecanismo usado: "celery", "background" o "inline".
    """
    task = _resolve(task_path)
    if settings.celery_enabled:
        try:
            task.delay(*args)
            return "celery"
        except Exception as exc:  # noqa: BLE001 - broker caído: seguimos en proceso
            logger.warning("No se pudo encolar %s en Celery (%s); se ejecuta en proceso.", task_path, exc)
    if background_tasks is not None:
        background_tasks.add_task(_run_safely, task, task_path, *args)
        return "background"
    _run_safely(task, task_path, *args)
    return "inline"


def _run_safely(task, task_path, *args):
    try:
        # Las tareas de Celery se pueden invocar directamente como funciones
        task(*args)
    except Exception:  # noqa: BLE001
        logger.exception("Falló la tarea %s", task_path)
