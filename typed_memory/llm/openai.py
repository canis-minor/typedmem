"""OpenAI provider. Optional dep — install with ``pip install typed-memory[openai]``."""

from __future__ import annotations


class OpenAIClient:
    """Thin wrapper around openai.OpenAI.chat.completions.

    The ``openai`` package is imported lazily so this module is safe to import
    even when the extra isn't installed; instantiation is where it fails.
    """

    def __init__(
        self,
        model: str = "gpt-4.1-mini",
        api_key: str | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        base_url: str | None = None,
    ) -> None:
        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as e:
            raise ImportError(
                "openai package is not installed. "
                "Install with: pip install 'typed-memory[openai]'"
            ) from e
        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def complete(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return resp.choices[0].message.content or ""
