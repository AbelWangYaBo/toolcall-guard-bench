"""场景自动发现:导入分类包里的所有模块,收集 SCENARIO。"""
from __future__ import annotations

import importlib
import pkgutil

from ..scenario import Scenario

from . import control, fabricated_parameters, fabricated_tool_name, repetitive_calls  # noqa: F401

_CATEGORY_PACKAGES = (
    fabricated_tool_name,
    fabricated_parameters,
    repetitive_calls,
    control,
)


def load_all() -> list[Scenario]:
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for package in _CATEGORY_PACKAGES:
        for module_info in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f".{module_info.name}", package.__name__)
            scenario = getattr(module, "SCENARIO", None)
            if scenario is None:
                continue
            if scenario.id in seen:
                raise ValueError(f"场景 id 重复: {scenario.id}")
            seen.add(scenario.id)
            scenarios.append(scenario)
    return sorted(scenarios, key=lambda s: s.id)


def by_category(category: str) -> list[Scenario]:
    return [s for s in load_all() if s.category == category]
