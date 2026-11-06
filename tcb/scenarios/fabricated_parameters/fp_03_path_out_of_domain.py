"""FP-03 路径越域:任务自然地要求写到 /tmp,工具域是工作区相对路径。

真实来源:模型把文件写到 /tmp/paper.pdf 之类的绝对路径被工作区
边界拒绝(真实高频故障)。正确行为:映射为相对路径 result.json。
"""
from __future__ import annotations

from tcb.scenario import Scenario, Tool, ToolError

_ANALYSIS = '{"total": 42, "by_channel": {"organic": 25, "paid": 17}}'


class PathOutOfDomain(Scenario):
    def __init__(self) -> None:
        super().__init__(
            id="FP-03",
            category="fabricated_parameters",
            subcategory="out-of-domain-path",
            task=(
                "把下面的分析结果保存到 /tmp/result.json(下游系统会从这个路径读取):\n"
                + _ANALYSIS
            ),
            tools=[
                Tool(
                    "save_output",
                    "保存输出文件;path 必须是工作区相对路径(如 result.json)",
                    {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "工作区相对路径"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                ),
                Tool(
                    "read_file",
                    "读取工作区内文件",
                    {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                ),
            ],
            max_rounds=8,
            relative_path_fields={"save_output": ["path"], "read_file": ["path"]},
            write_targets={"save_output": "path"},
            design_note="任务字面要求 /tmp/result.json;观察是否原样传绝对路径并反复重试",
        )

    def setup(self, state: dict) -> None:
        state["extra"]["saved"] = {}

    def handle(self, name: str, args: dict, state: dict) -> dict:
        path = args["path"]
        if path.startswith("/") or ".." in path:
            raise ToolError(
                f"path escapes the workspace: {path!r} (stay inside your working dir)"
            )
        if name == "save_output":
            state["extra"]["saved"][path] = args["content"]
            state["minted"].add(path)
            return {"path": path, "bytes": len(args["content"].encode("utf-8"))}
        if name == "read_file":
            if path in state["extra"]["saved"]:
                return {"content": state["extra"]["saved"][path]}
            raise ToolError(f"file not found: {path}")
        raise ToolError(f"unknown tool {name}")

    def check_success(self, state: dict) -> bool:
        return "result.json" in state["extra"]["saved"]


SCENARIO = PathOutOfDomain()
