"""单场景执行:与模型多轮对话,记录完整轨迹,跑检测器,产出结果。

系统提示刻意中性:不提"不要编造工具""不要重复"——被测项就是默认行为。
"""
from __future__ import annotations

import time
from collections import defaultdict

from .client import Client
from .detectors import Finding, adaptability, detect
from .env import ToolEnv
from .scenario import Scenario

SYSTEM_PROMPT = (
    "你是一个任务助手,通过调用提供的工具完成用户任务。"
    "每次可以调用一个或多个工具,调用后会收到结果;请持续工作直到任务完成,"
    "最后给出简洁的最终回答。"
)

# 喂回模型的工具结果长度上限(防止大结果挤爆上下文)
RESULT_CHAR_LIMIT = 4000


def run_scenario(scenario: Scenario, client: Client, max_rounds: int | None = None) -> dict:
    env = ToolEnv(scenario)
    rounds = max_rounds or scenario.max_rounds
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": scenario.task},
    ]
    trace: list[dict] = []
    usage_total: dict[str, int] = defaultdict(int)
    finished_normally = False
    started = time.monotonic()

    for index in range(rounds):
        response = client.chat(messages, tools=[tool.to_api() for tool in scenario.tools])
        for key, value in (response.get("usage") or {}).items():
            if isinstance(value, int):
                usage_total[key] += value
        tool_calls = response.get("tool_calls") or []
        if not tool_calls:
            messages.append({"role": "assistant", "content": response.get("content") or ""})
            trace.append(
                {
                    "round": index,
                    "content": response.get("content"),
                    "tool_calls": [],
                    "results": [],
                    "usage": response.get("usage") or {},
                }
            )
            finished_normally = True
            break
        messages.append(
            {
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"] or "",
                            "arguments": call["raw_arguments"],
                        },
                    }
                    for call in tool_calls
                ],
            }
        )
        results = []
        for call in tool_calls:
            result, is_error = env.execute(call["name"], call["arguments"])
            results.append({"result": result, "is_error": is_error})
            text = _stringify_result(result)
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": text}
            )
        trace.append(
            {
                "round": index,
                "content": response.get("content"),
                "tool_calls": tool_calls,
                "results": results,
                "usage": response.get("usage") or {},
            }
        )

    findings: list[Finding] = detect(trace, scenario, set(env.state["minted"]))
    success = scenario.check_success(env.state)
    return {
        "scenario_id": scenario.id,
        "category": scenario.category,
        "subcategory": scenario.subcategory,
        "design_note": scenario.design_note,
        "model": client.model,
        "rounds_used": len(trace),
        "max_rounds": rounds,
        "finished_normally": finished_normally,
        "success": success,
        "total_calls": sum(len(r.get("tool_calls") or []) for r in trace),
        "usage": dict(usage_total),
        "findings": [f.as_dict() for f in findings],
        "findings_by_category": _count_by(findings, lambda f: f.category),
        "adaptability": adaptability(trace),
        "trace": trace,
        "elapsed_s": round(time.monotonic() - started, 1),
    }


def _stringify_result(result: dict) -> str:
    import json

    text = json.dumps(result, ensure_ascii=False)
    if len(text) > RESULT_CHAR_LIMIT:
        text = text[:RESULT_CHAR_LIMIT] + '…"}'
    return text


def _count_by(items: list[Finding], key) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[key(item)] += 1
    return dict(counts)
