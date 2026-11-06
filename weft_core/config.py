"""Loaders for config/rules.yaml and config/pipeline.yaml."""

from pathlib import Path
from typing import Any

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config"


def load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((CONFIG / name).read_text())
    assert isinstance(data, dict)
    return data


def pipeline() -> dict[str, Any]:
    return load("pipeline.yaml")


def rules() -> dict[str, Any]:
    return load("rules.yaml")
