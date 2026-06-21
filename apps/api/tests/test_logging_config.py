import io
import logging

import structlog

from src.logging_config import configure_logging


def test_configure_logging_renders_exception_tracebacks() -> None:
    """log.exception() must emit the traceback, not a bare exc_info=true."""
    original_handlers = logging.getLogger().handlers
    try:
        configure_logging()
        root = logging.getLogger()
        assert root.handlers
        stream = io.StringIO()
        root.handlers[0].setStream(stream)  # redirect the configured handler

        log = structlog.get_logger("test.logging_config")
        try:
            raise ValueError("boom-marker-42")
        except ValueError:
            log.exception("operation failed")

        output = stream.getvalue()
    finally:
        logging.getLogger().handlers = original_handlers

    assert "operation failed" in output
    assert "boom-marker-42" in output
    assert "Traceback" in output
