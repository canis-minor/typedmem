"""Provider-client tests. No live API calls — verifies wiring + error paths."""

import pytest

from typedmem import AnthropicClient, FakeClient, OpenAIClient


def test_fake_client_constant():
    c = FakeClient("hello")
    assert c.complete("anything") == "hello"
    assert c.complete("other") == "hello"
    assert c.calls == ["anything", "other"]


def test_fake_client_sequence():
    c = FakeClient(["a", "b"])
    assert c.complete("p1") == "a"
    assert c.complete("p2") == "b"
    with pytest.raises(RuntimeError, match="exhausted"):
        c.complete("p3")


def test_fake_client_callable():
    c = FakeClient(lambda p: p.upper())
    assert c.complete("hi") == "HI"


def test_openai_client_clean_error_without_dep(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "openai":
            raise ImportError("no openai")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match=r"typedmem\[openai\]"):
        OpenAIClient(api_key="ignored")


def test_anthropic_client_clean_error_without_dep(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match=r"typedmem\[anthropic\]"):
        AnthropicClient(api_key="ignored")
