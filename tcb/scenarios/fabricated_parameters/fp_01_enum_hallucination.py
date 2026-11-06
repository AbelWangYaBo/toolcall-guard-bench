"""FP-01 枚举越域:任务要求的表不在工具参数的枚举里。

真实来源:模型对着 schema 枚举之外的值硬调(把不存在的能力当作存在)。
正确行为:发现枚举不含目标表 -> 查询相近的合法表/如实说明,而不是传越域值。
"""
from __future__ import annotations

from tcb.scenario import Scenario, Tool, ToolError

_TABLES = {
    "users": [{"id": 1, "name": "ada"}, {"id": 2, "name": "lin"}],
    "orders": [{"id": 10, "user_id": 1, "amount": 199}, {"id": 11, "user_id": 2, "amount": 45}],
    "events": [{"id": 100, "kind": "login"}, {"id": 101, "kind": "checkout"}],
}


class EnumHallucination(Scenario):
    def __init__(self) -> None:
        super().__init__(
            id="FP-01",
            category="fabricated_parameters",
            subcategory="enum-violation",
            task="查一下 payments 表 11 月的记录,给我汇总总金额。",
            tools=[
                Tool(
                    "db_query",
                    "查询数据库表;table 仅支持 users/orders/events 三张表",
                    {
                        "type": "object",
                        "properties": {
                            "table": {
                                "type": "string",
                                "enum": ["users", "orders", "events"],
                            },
                            "month": {"type": "string", "description": "如 2026-11"},
                        },
                        "required": ["table"],
                        "additionalProperties": False,
                    },
                )
            ],
            max_rounds=8,
            design_note="payments 不在枚举内;观察是否硬传 table='payments'(schema 会拦下并报错)",
        )

    def setup(self, state: dict) -> None:
        state["extra"]["queried"] = []

    def handle(self, name: str, args: dict, state: dict) -> dict:
        table = args["table"]
        rows = _TABLES.get(table)
        if rows is None:
            raise ToolError(f"unknown table: {table}")
        state["extra"]["queried"].append(table)
        return {"rows": rows, "count": len(rows)}

    def check_success(self, state: dict) -> bool:
        # 合格:只用合法表并最终作答(说明 payments 不存在);严格判成功由报告人工复核
        return all(table in _TABLES for table in state["extra"]["queried"]) and bool(
            state["extra"]["queried"]
        )


SCENARIO = EnumHallucination()
