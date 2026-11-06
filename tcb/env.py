"""受控工具环境:注册表 + 模式校验 + 确定性执行 + 铸造(grounding)追踪。"""
from __future__ import annotations

from . import schema
from .scenario import Scenario, ToolError


class ToolEnv:
    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.registry = {tool.name: tool for tool in scenario.tools}
        self.state: dict = {"files": {}, "minted": set(), "calls": 0, "extra": {}}
        scenario.setup(self.state)

    def execute(self, name: str | None, args: dict) -> tuple[dict, bool]:
        """执行一次调用,返回 (结果, 是否出错)。未知工具/参数违规也走结果通道喂回模型。"""
        self.state["calls"] += 1
        if not name or name not in self.registry:
            known = ", ".join(sorted(self.registry))
            return (
                {"error": f"unknown tool {name!r} — 可用工具: {known}"},
                True,
            )
        errors = schema.validate(args, self.registry[name].parameters)
        if errors:
            return ({"error": "invalid arguments: " + "; ".join(errors)}, True)
        try:
            result = self.scenario.handle(name, args, self.state)
        except ToolError as exc:
            return ({"error": exc.message}, True)
        if not isinstance(result, dict):
            result = {"result": result}
        return (result, False)

    def mint(self, token: str) -> str:
        """登记一个"环境铸造过"的合法引用(ID/路径),供引用幻觉检测。"""
        self.state["minted"].add(token)
        return token
