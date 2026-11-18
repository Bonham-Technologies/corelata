"""A tiny OpenAI-compatible HTTP server (stdlib only) answering with the synthetic responder.
Used by integration tests, by `corelata fake-openai`, and by the demo stack (compose.demo.yaml),
which keeps no request log."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from corelata.llm.payload import parse_input
from corelata.testing.synthetic import chat_completion, synthetic_response


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    models: list[str]
    context_window: int | None
    requests: list[dict[str, Any]]
    keep_requests: bool
    delay_s: float
    needs_repair: bool
    lock: threading.Lock
    in_flight: int
    max_in_flight: int


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            data = [{"id": m, "object": "model"} for m in self.server.models]
            self._send(200, {"object": "list", "data": data})
        else:
            self._send(404, {"error": {"message": f"no route {self.path}"}})

    def do_POST(self) -> None:
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, {"error": {"message": f"no route {self.path}"}})
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        with self.server.lock:
            if self.server.keep_requests:
                self.server.requests.append(body)
            self.server.in_flight += 1
            self.server.max_in_flight = max(self.server.max_in_flight, self.server.in_flight)
        try:
            if self.server.delay_s:
                time.sleep(self.server.delay_s)
            self._reply(body)
        finally:
            with self.server.lock:
                self.server.in_flight -= 1

    def _reply(self, body: dict[str, Any]) -> None:
        window = self.server.context_window
        chars = sum(len(m.get("content") or "") for m in body.get("messages", []))
        if window is not None and chars / 2 > window:
            self._send(
                400,
                {"error": {"message": f"This model's maximum context length is {window} tokens"}},
            )
            return
        try:
            payload = parse_input(body["messages"])
            content = json.dumps(synthetic_response(payload), ensure_ascii=False)
        except (ValueError, KeyError) as e:
            self._send(400, {"error": {"message": str(e)}})
            return
        first_turn = not any(m.get("role") == "assistant" for m in body["messages"])
        if self.server.needs_repair and first_turn and payload.get("task") != "ping":
            # R-M15-5 rehearsal: a model whose first reply never parses and whose repaired one
            # does; `{}` lacks a required field of every structured output
            content = "{}"
        reason = "length" if body.get("max_tokens") == 1 else "stop"
        self._send(200, chat_completion(content, finish_reason=reason))

    def _send(self, status: int, obj: dict[str, Any]) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class FakeOpenAIServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        models: tuple[str, ...] = ("fake-model",),
        context_window: int | None = None,
        delay_s: float = 0.0,
        keep_requests: bool = True,
        needs_repair: bool = False,
    ) -> None:
        self._server = _Server((host, port), _Handler)
        self._server.models = list(models)
        self._server.context_window = context_window
        self._server.requests = []
        self._server.keep_requests = keep_requests
        self._server.delay_s = delay_s
        self._server.needs_repair = needs_repair
        self._server.lock = threading.Lock()
        self._server.in_flight = 0
        self._server.max_in_flight = 0
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self._server.requests

    @property
    def max_in_flight(self) -> int:
        """The most chat requests the server has handled at the same time."""
        return self._server.max_in_flight

    def start(self) -> "FakeOpenAIServer":
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def serve_forever(self) -> None:  # pragma: no cover - blocks until interrupted (CLI only)
        """Blocking variant for the CLI."""
        self._server.serve_forever()

    def stop(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join()
            self._thread = None
        self._server.server_close()  # also releases the socket when never started (CLI path)

    def __enter__(self) -> "FakeOpenAIServer":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
