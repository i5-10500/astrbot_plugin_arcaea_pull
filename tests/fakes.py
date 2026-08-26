from __future__ import annotations

from collections import deque
from typing import Any


class FakeResponse:
    def __init__(self, status: int = 200, payload: Any = None, json_error: Exception | None = None):
        self.status = status
        self.payload = payload
        self.json_error = json_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self, **_kwargs):
        if self.json_error:
            raise self.json_error
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.popleft()
        if isinstance(result, BaseException):
            raise result
        return result

    async def close(self):
        self.closed = True

