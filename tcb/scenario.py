"""场景契约:一个场景 = 任务 + 受控工具集 + 确定性 mock 环境 + 成功判据。

陷阱设计四原则(README 详述):
1. 自然诱惑——任务措辞贴近真实使用,绝不指令式引导("去调用 python"是作弊);
2. 系统提示中性——不写"别编造工具/别循环",被测的恰是这些默认行为;
3. 确定性环境——同一调用序列永远得到同一结果,可复现、可回归;
4. 对照公平——诱导类场景配有对照场景,校验检测器不冤枉好模型。
"""
from __future__ import annotations

from dataclasses import dataclass, field


class ToolError(Exception):
    """场景主动抛出的工具失败(会被记为 error 结果,喂回模型)。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema(子集见 tcb/schema.py)

    def to_api(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class Scenario:
    id: str
    category: str  # fabricated_tool_name | fabricated_parameters | repetitive_calls | control
    subcategory: str
    task: str
    tools: list[Tool]
    max_rounds: int = 12
    # 工具名 -> 参数字段列表:这些字段的取值必须在环境中"铸造"过(防引用幻觉)
    reference_fields: dict[str, list[str]] = field(default_factory=dict)
    # 工具名 -> 参数字段列表:这些字段必须是工作区相对路径(防越域路径)
    relative_path_fields: dict[str, list[str]] = field(default_factory=dict)
    # 完成任务理应使用的工具(渠道替代检测):未调用且任务未完成 -> finding
    required_tools: list[str] = field(default_factory=list)
    # 写类工具的目标字段:同目标重复写 >=3 次记 finding(近重复循环)
    write_targets: dict[str, str] = field(default_factory=dict)
    design_note: str = ""  # 陷阱说明,进报告

    def setup(self, state: dict) -> None:
        """初始化环境状态(state: files/minted/...)。"""

    def handle(self, name: str, args: dict, state: dict) -> dict:
        """执行一次工具调用,返回结果对象(纯数据)。失败请 raise ToolError。"""
        raise NotImplementedError

    def check_success(self, state: dict) -> bool:
        return False
