"""RC-03 渠道替代循环(旗舰场景):执行器明明在,却反复写脚本文件。

真实来源:run_python 就在工具集里且排第一位,模型仍然连续 4 次
write_file 写同一个 parse.py、嘴上宣布"现在运行",从不调用执行器,
直至轮次耗尽——实践中最典型的死法之一。
"""
from __future__ import annotations

import json

from tcb.scenario import Scenario, Tool, ToolError

_LINE_LIMIT = 40


def _data_json() -> str:
    payload = {}
    for index in range(40):
        payload[f"key_{index:02d}"] = [index * step for step in range(1, 11)]
    return json.dumps(payload, indent=1)


class ChannelSubstitution(Scenario):
    def __init__(self) -> None:
        super().__init__(
            id="RC-03",
            category="repetitive_calls",
            subcategory="channel-substitution",
            task=(
                "解析工作区里的 data.json(40 个顶层 key,每个是数值数组),"
                "统计每个 key 下的元素个数,把 {key: count} 的 JSON 写入 out.json。"
            ),
            tools=[
                Tool(
                    "run_python",
                    "在持久 Python 内核中执行代码并返回 stdout——"
                    "本环境中唯一能执行计算的途径",
                    {
                        "type": "object",
                        "properties": {"code": {"type": "string"}},
                        "required": ["code"],
                        "additionalProperties": False,
                    },
                ),
                Tool(
                    "write_file",
                    "把文本内容写入工作区文件(仅存储,不执行)",
                    {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                ),
                Tool(
                    "read_file",
                    "分页读取工作区文本文件(limit<=40 行)",
                    {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "offset": {"type": "integer"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                ),
            ],
            max_rounds=12,
            required_tools=["run_python"],
            write_targets={"write_file": "path"},
            design_note=(
                "run_python 已注册且描述明确;弱模型会反复 write_file 脚本而不调用执行器"
                "(read_file 只回前 40 行,手数 2000+ 行不现实)"
            ),
        )
        self._data = _data_json()

    def setup(self, state: dict) -> None:
        state["files"]["data.json"] = self._data
        state["minted"].update({"data.json"})
        state["extra"]["python_runs"] = 0

    def handle(self, name: str, args: dict, state: dict) -> dict:
        if name == "run_python":
            state["extra"]["python_runs"] += 1
            code = args["code"]
            return {
                "stdout": f"(executed {len(code)} chars of code)",
                "executed": True,
            }
        if name == "write_file":
            state["files"][args["path"]] = args["content"]
            state["minted"].add(args["path"])
            return {"path": args["path"], "bytes": len(args["content"].encode("utf-8"))}
        if name == "read_file":
            if args.get("path") not in state["files"]:
                raise ToolError(f"file not found: {args.get('path')}")
            lines = state["files"][args["path"]].splitlines()
            offset = max(0, int(args.get("offset") or 0))
            limit = max(1, min(_LINE_LIMIT, int(args.get("limit") or _LINE_LIMIT)))
            window = lines[offset : offset + limit]
            return {
                "content": "\n".join(window),
                "returned": len(window),
                "total_lines": len(lines),
                "truncated": offset + limit < len(lines),
            }
        raise ToolError(f"unknown tool {name}")

    def check_success(self, state: dict) -> bool:
        out = state["files"].get("out.json")
        return bool(out) and '"key_00"' in out and state["extra"]["python_runs"] >= 1


SCENARIO = ChannelSubstitution()
