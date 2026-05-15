"""LLM client adapters. The protocol is always importable; provider classes
are too — they only fail at instantiation if the optional dep is missing."""

from .anthropic import AnthropicClient
from .base import LLMClient
from .fake import FakeClient
from .openai import OpenAIClient

__all__ = ["AnthropicClient", "FakeClient", "LLMClient", "OpenAIClient"]
