import io
import json
import logging

from corelata.logs import configure_json_logging, remove_json_logging


def test_json_logging_is_idempotent_and_structured():
    stream = io.StringIO()
    first = configure_json_logging(stream=stream)
    handler = configure_json_logging(stream=stream)  # replaces, never doubles
    assert first not in logging.getLogger("corelata").handlers
    log = logging.getLogger("corelata.worker")
    log.info("stage complete", extra={"run_id": "r1", "stage": "gating"})
    try:
        raise ValueError("x")
    except ValueError:
        log.exception("failed")
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines[0]["message"] == "stage complete" and lines[0]["run_id"] == "r1"
    assert lines[0]["stage"] == "gating" and lines[0]["level"] == "info"
    assert lines[0]["ts"].endswith("+00:00") and lines[0]["logger"] == "corelata.worker"
    assert "ValueError: x" in lines[1]["exception"]
    remove_json_logging(handler)
    assert handler not in logging.getLogger("corelata").handlers
    assert handler not in logging.getLogger("procrastinate").handlers
