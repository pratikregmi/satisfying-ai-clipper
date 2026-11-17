import logging
from pathlib import Path

from backend.app.core.database import PROJECT_ROOT


LOG_FILE = PROJECT_ROOT / "logs.txt"

logger = logging.getLogger("satisfyingai.workflow")
logger.setLevel(logging.INFO)
logger.propagate = False

# Avoid duplicate file handlers during development reloads.
if not any(
    getattr(handler, "_workflow_file_handler", False)
    for handler in logger.handlers
):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(
        LOG_FILE,
        mode="a",
        encoding="utf-8",
    )

    file_handler._workflow_file_handler = True

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


def log_workflow(
    job_id: int,
    video_id: int,
    stage: str,
    status: str,
    message: str = "",
):
    """Write one workflow event to the persistent log."""

    logger.info(
        "JOB #%s | VIDEO #%s | %-22s | %-10s | %s",
        job_id,
        video_id,
        stage.upper(),
        status.upper(),
        message,
    )


def log_workflow_error(
    job_id: int,
    video_id: int,
    stage: str,
    error: Exception,
):
    """Write an error and its complete traceback."""

    logger.exception(
        "JOB #%s | VIDEO #%s | %s | FAILED | %s",
        job_id,
        video_id,
        stage.upper(),
        error,
    )
