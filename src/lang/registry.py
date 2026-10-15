#
# Copyright IBM Corp. 2026
# SPDX-License-Identifier: MIT
#
"""Extension/name -> language adapter.  Dispatch is total: never a parse heuristic."""

from __future__ import annotations

_ADAPTERS: dict = {}


def register(adapter) -> None:
    _ADAPTERS[adapter.name] = adapter


def get_adapter(language: str):
    if language not in _ADAPTERS:
        _load(language)
    if language not in _ADAPTERS:
        raise ValueError(f"No adapter for language {language!r}; have {sorted(_ADAPTERS)}")
    return _ADAPTERS[language]


def adapter_for_path(path: str, default: str = "python"):
    for adapter in _ADAPTERS.values():
        if path.endswith(adapter.extensions):
            return adapter
    return get_adapter(default)


def _load(language: str) -> None:
    if language == "java":
        from src.lang import java_extractor, java_usage  # noqa: F401
