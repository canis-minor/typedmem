"""Profile loaders. JSON is stdlib; YAML lives behind the [yaml] extra."""

from __future__ import annotations

import json
from pathlib import Path

from .base import DomainProfile


def from_json(path: str | Path) -> DomainProfile:
    return DomainProfile.from_dict(json.loads(Path(path).read_text()))


def from_yaml(path: str | Path) -> DomainProfile:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(
            "yaml support requires the optional dep. "
            "Install with: pip install 'typedmem[yaml]'"
        ) from e
    return DomainProfile.from_dict(yaml.safe_load(Path(path).read_text()))
