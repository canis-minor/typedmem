"""LLMClient protocol — the contract every provider implements."""

from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    """Anything that maps a prompt string to a completion string."""

    def complete(self, prompt: str) -> str: ...
