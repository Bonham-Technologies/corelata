"""In-process Backend for tests: scripted faults first, synthetic answers otherwise."""

import json
from collections import defaultdict, deque

from corelata.llm.payload import parse_input
from corelata.llm.types import ChatRequest, ChatResponse
from corelata.testing.synthetic import synthetic_response

Scripted = str | BaseException


class FakeBackend:
    def __init__(self, name: str = "fake", models: tuple[str, ...] = ("fake-model",)) -> None:
        self.name = name
        self._models = list(models)
        self._scripts: dict[str, deque[Scripted]] = defaultdict(deque)
        self.requests: list[ChatRequest] = []
        self.closed = False

    def script(self, task: str, *items: Scripted) -> None:
        """Queue raw replies (str) or exceptions to raise for the next calls of `task`."""
        self._scripts[task].extend(items)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        payload = parse_input([m.model_dump() for m in request.messages])
        queue = self._scripts.get(payload["task"])
        if queue:
            item = queue.popleft()
            if isinstance(item, BaseException):
                raise item
            return ChatResponse(content=item, tokens_in=1, tokens_out=1)
        content = json.dumps(synthetic_response(payload), ensure_ascii=False)
        return ChatResponse(content=content, tokens_in=10, tokens_out=10)

    async def list_models(self) -> list[str]:
        return list(self._models)

    async def aclose(self) -> None:
        self.closed = True
