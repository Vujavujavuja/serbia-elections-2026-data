"""Derived tables: built only from parsed tables, never from the network.

Each module defines NAME, DESCRIPTION and build() -> {table: row count}. Output goes to
data/parsed/derived/. These encode choices of ours (how to match, how to classify), so
every row states the rule that produced it.
"""
from __future__ import annotations

import importlib
import pkgutil


def discover() -> dict:
    return {m.NAME: m for m in (importlib.import_module(f"{__name__}.{i.name}")
                                for i in pkgutil.iter_modules(__path__) if not i.name.startswith("_"))}
