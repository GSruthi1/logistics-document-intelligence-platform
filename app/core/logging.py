"""Minimal structured logging setup — JSON-ish key=value lines so log output
is grep/parse-friendly in a hosted environment (Azure Log Stream, Railway
logs) without pulling in a full logging stack for a portfolio project.
"""
import logging
import sys

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)

    # Quiet down noisy third-party loggers unless we're actually debugging them.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
