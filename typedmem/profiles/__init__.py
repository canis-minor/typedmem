"""Profiles: typed schema for a domain.

Public surface: ``TypeSpec``, ``DomainProfile``, plus loaders. Built-in
profiles are accessed via ``DomainProfile.builtin(name)``.
"""

from .base import DomainProfile, TypeSpec
from .builtins import BUILTIN_PROFILES
from .loaders import from_json, from_yaml

__all__ = ["BUILTIN_PROFILES", "DomainProfile", "TypeSpec", "from_json", "from_yaml"]
