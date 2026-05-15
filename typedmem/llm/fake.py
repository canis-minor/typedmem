"""FakeClient — scripted responses for tests and offline development.

Public API so users can test their own LLMExtractor integrations without
hitting a real provider.
"""

from __future__ import annotations

from typing import Callable, Iterable


class FakeClient:
    """Returns canned responses in order. Records every prompt it sees.

    ``responses`` may be:
      - a single string (used for every call), or
      - an iterable of strings (consumed in order), or
      - a callable ``prompt -> response`` for dynamic behavior.
    """

    def __init__(self, responses: str | Iterable[str] | Callable[[str], str]) -> None:
        self._responder: Callable[[str], str]
        if callable(responses):
            self._responder = responses  # type: ignore[assignment]
        elif isinstance(responses, str):
            const = responses
            self._responder = lambda _p: const
        else:
            it = iter(responses)
            def _next(_p: str) -> str:
                try:
                    return next(it)
                except StopIteration as e:
                    raise RuntimeError("FakeClient exhausted") from e
            self._responder = _next
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return self._responder(prompt)
