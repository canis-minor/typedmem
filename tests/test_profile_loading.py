"""Loader tests: from_json (stdlib) and from_yaml (optional dep)."""

import json
from pathlib import Path

import pytest

from typedmem.profiles import from_json, from_yaml


def test_from_json_loads_dict(tmp_path: Path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({
        "name": "custom",
        "description": "test",
        "include_core_types": True,
        "types": {
            "claim": {"name": "claim", "conflict_policy": "keep_both"},
        },
    }))
    p = from_json(path)
    assert p.name == "custom"
    assert p.has_type("claim")
    assert p.has_type("fact")  # via core


def test_from_yaml_clean_error_without_dep(tmp_path: Path, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    path = tmp_path / "p.yaml"
    path.write_text("name: x")
    with pytest.raises(ImportError, match=r"typedmem\[yaml\]"):
        from_yaml(path)
