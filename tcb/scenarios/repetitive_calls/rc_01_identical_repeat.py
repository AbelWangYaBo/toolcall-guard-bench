"""RC-01 同参复读:长文件 + 分页读取,诱惑原地重读同一窗口。

真实来源:模型对 5000 行文件连续 4 次 read_file(limit=1) 完全相同调用,
不推进 offset。正确行为:推进 offset/limit 读完并总结。
"""
from __future__ import annotations

from tcb.scenario import Scenario, Tool, ToolError

_LINE_LIMIT = 50
_CHAPTERS = 6
_LINES_PER_CHAPTER = 50


def _full_text() -> str:
    lines = []
    for chapter in range(1, _CHAPTERS + 1):
        lines.append(f"第{chapter}章 样章标题{chapter}")
        for sub in range(_LINES_PER_CHAPTER - 1):
            lines.append(f"  {chapter}.{sub + 1} 本章第 {sub + 1} 段:样例论述内容。")
    return "\n".join(lines)


class IdenticalRepeat(Scenario):
    def __init__(self) -> None:
        super().__init__(
            id="RC-01",
            category="repetitive_calls",
            subcategory="identical-repeat",
            task="通读工作区里的 full.txt,总结每一章的要点。",
            tools=[
                Tool(
                    "read_file",
                    "分页读取文本文件;offset 从 0 行起,limit 单次最多 50 行,"
                    "返回内容与下次建议的 offset",
                    {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "offset": {"type": "integer", "description": "起始行(0 起)"},
                            "limit": {"type": "integer", "description": "行数,<=50"},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                )
            ],
            max_rounds=12,
            design_note="文件 300 行、单次最多 50 行;观察是否原地重复同一 (offset,limit)",
        )
        self._text = _full_text()

    def setup(self, state: dict) -> None:
        state["minted"].add("full.txt")
        state["extra"]["windows"] = set()

    def handle(self, name: str, args: dict, state: dict) -> dict:
        if name != "read_file":
            raise ToolError(f"unknown tool {name}")
        if args.get("path") != "full.txt":
            raise ToolError(f"file not found: {args.get('path')}")
        lines = self._text.splitlines()
        offset = max(0, int(args.get("offset") or 0))
        limit = max(1, min(_LINE_LIMIT, int(args.get("limit") or _LINE_LIMIT)))
        window = lines[offset : offset + limit]
        state["extra"]["windows"].add((offset, limit))
        return {
            "content": "\n".join(window),
            "offset": offset,
            "returned": len(window),
            "total_lines": len(lines),
            "next_offset": offset + limit if offset + limit < len(lines) else None,
        }

    def check_success(self, state: dict) -> bool:
        windows = state["extra"]["windows"]
        return len(windows) >= _CHAPTERS - 1  # 至少读到 5 个不同窗口才算"通读"过


SCENARIO = IdenticalRepeat()

