"""Anthropic provider. Optional dep — install with ``pip install typed-memory[anthropic]``."""

from __future__ import annotations


class AnthropicClient:
    """Thin wrapper around anthropic.Anthropic.messages.create.

    Default model is Haiku — extraction is exactly its sweet spot (short,
    structured outputs, latency-sensitive). Override for higher quality."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> None:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "anthropic package is not installed. "
                "Install with: pip install 'typed-memory[anthropic]'"
            ) from e
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def complete(self, prompt: str) -> str:
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        # Anthropic returns a list of content blocks; concatenate text blocks.
        parts: list[str] = []
        for block in msg.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)
