"""Collectors. Each module in this package is one independent source.

A collector module defines:
    NAME         short identifier, also the folder name under data/raw and data/parsed
    DESCRIPTION  one line: what it collects and from where
    fetch(store, **options)   download from the publisher into the raw store
    parse(store)              rebuild parsed tables from what is in the raw store

To add a source, add a file here. To remove one, delete its file. Nothing else changes.
"""
from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType


def discover() -> dict[str, ModuleType]:
    found = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        found[module.NAME] = module
    return found
