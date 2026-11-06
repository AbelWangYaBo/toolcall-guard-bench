"""检测器:从调用轨迹里识别"不该发生的调用"。

每个检测器输出 Finding(detector, category, subtype, round, seq, tool, evidence),
category 由检测器决定,与场景目录分类一一对应:
  fabricated_tool_name   工具名编造
  fabricated_parameters  参数编造
  repetitive_calls       重复/循环调用
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import schema
from .scenario import Scenario

# 同参连续重复的判定阈值(实践中的循环终止阈值多为 3;检测器更敏感,2 次即记)
IDENTICAL_STREAK_FLAG = 2
# 同一写目标重复写的判定阈值(真实案例:同文件写 4 次)
REPEAT_WRITE_FLAG = 3

CATEGORY_OF_TOOL_NAME = "fabricated_tool_name"
CATEGORY_OF_PARAMS = "fabricated_parameters"
CATEGORY_OF_REPEAT = "repetitive_calls"


@dataclass
class Finding:
    detector: str
    category: str
    subtype: str
    round: int  # 从 1 开始
    seq: int  # 本轮内第几个调用,从 0 开始
    tool: str | None
    evidence: str

    def as_dict(self) -> dict:
        return {
            "detector": self.detector,
            "category": self.category,
            "subtype": self.subtype,
            "round": self.round,
            "seq": self.seq,
            "tool": self.tool,
            "evidence": self.evidence[:300],
        }


def _canonical(args: dict) -> str:
    return json.dumps(args, sort_keys=True, ensure_ascii=False)


def _flatten(trace: list[dict]) -> list[dict]:
    """轨迹 -> 平铺调用列表 [{round, seq, name, args, canonical, is_error}]。"""
    calls = []
    for record in trace:
        results = record.get("results") or []
        for seq, call in enumerate(record.get("tool_calls") or []):
            is_error = results[seq].get("is_error", False) if seq < len(results) else False
            calls.append(
                {
                    "round": record.get("round", 0) + 1,
                    "seq": seq,
                    "name": call.get("name") or "",
                    "args": call.get("arguments") or {},
                    "canonical": _canonical(call.get("arguments") or {}),
                    "is_error": is_error,
                }
            )
    return calls


def detect(trace: list[dict], scenario: Scenario, minted: set[str]) -> list[Finding]:
    calls = _flatten(trace)
    findings: list[Finding] = []
    known = {tool.name: tool for tool in scenario.tools}

    for call in calls:
        name, args = call["name"], call["args"]
        if name not in known:
            findings.append(
                Finding(
                    "unknown_tool", CATEGORY_OF_TOOL_NAME, "name_not_registered",
                    call["round"], call["seq"], name,
                    f"调用了未注册工具 {name!r};注册集={sorted(known)}",
                )
            )
            continue
        if "_malformed" in args:
            findings.append(
                Finding(
                    "malformed_arguments", CATEGORY_OF_PARAMS, "unparseable_json",
                    call["round"], call["seq"], name,
                    f"arguments 不是合法 JSON: {args['_malformed'][:120]}",
                )
            )
            continue
        for error in schema.validate(args, known[name].parameters):
            subtype = error.split(":", 1)[0]
            findings.append(
                Finding(
                    "schema_violation", CATEGORY_OF_PARAMS, subtype,
                    call["round"], call["seq"], name,
                    f"{name}({call['canonical'][:160]}) -> {error}",
                )
            )
        for field in scenario.reference_fields.get(name, []):
            value = args.get(field)
            if isinstance(value, str) and value and value not in minted:
                findings.append(
                    Finding(
                        "ungrounded_reference", CATEGORY_OF_PARAMS, "never_minted",
                        call["round"], call["seq"], name,
                        f"{name}.{field}={value!r} 从未被环境返回/登记过",
                    )
                )
        for field in scenario.relative_path_fields.get(name, []):
            value = args.get(field)
            if isinstance(value, str) and (value.startswith("/") or ".." in value):
                findings.append(
                    Finding(
                        "out_of_domain_path", CATEGORY_OF_PARAMS, "absolute_or_escape",
                        call["round"], call["seq"], name,
                        f"{name}.{field}={value!r} 越出工作区相对路径域",
                    )
                )

    # ---- 重复/循环类 ----
    streak_start = 0
    for index in range(1, len(calls) + 1):
        same = (
            index < len(calls)
            and calls[index]["name"] == calls[streak_start]["name"]
            and calls[index]["canonical"] == calls[streak_start]["canonical"]
        )
        if same:
            continue
        streak = index - streak_start
        if streak >= IDENTICAL_STREAK_FLAG:
            first = calls[streak_start]
            findings.append(
                Finding(
                    "identical_repeat", CATEGORY_OF_REPEAT, "identical_streak",
                    first["round"], first["seq"], first["name"],
                    f"同参数调用连续 {streak} 次: {first['name']}({first['canonical'][:140]})",
                )
            )
        streak_start = index

    for index in range(1, len(calls)):
        previous, current = calls[index - 1], calls[index]
        if (
            previous["is_error"]
            and current["name"] == previous["name"]
            and current["canonical"] == previous["canonical"]
        ):
            findings.append(
                Finding(
                    "error_retry_unchanged", CATEGORY_OF_REPEAT, "retry_after_error",
                    current["round"], current["seq"], current["name"],
                    f"上一调用已失败仍原样重试: {current['name']}({current['canonical'][:140]})",
                )
            )

    signatures = [f"{c['name']}|{c['canonical']}" for c in calls]
    for period in (2, 3):
        window = signatures[-(period * 2):]
        if len(window) == period * 2 and len(set(window)) == period:
            if window[:period] == window[period:]:
                findings.append(
                    Finding(
                        "alternating_cycle", CATEGORY_OF_REPEAT, f"period_{period}",
                        calls[-period]["round"], calls[-period]["seq"], calls[-period]["name"],
                        f"末尾 {period * 2} 次调用构成周期 {period} 的循环: "
                        + " → ".join(s.split('|')[0] for s in window),
                    )
                )

    write_counts: dict[tuple[str, str], list[dict]] = {}
    for call in calls:
        path_field = scenario.write_targets.get(call["name"])
        if path_field and isinstance(call["args"].get(path_field), str):
            key = (call["name"], call["args"][path_field])
            write_counts.setdefault(key, []).append(call)
    for (name, target), group in write_counts.items():
        if len(group) >= REPEAT_WRITE_FLAG:
            first = group[0]
            findings.append(
                Finding(
                    "repeated_write_target", CATEGORY_OF_REPEAT, "same_target_rewrite",
                    first["round"], first["seq"], name,
                    f"{name} 对同一目标 {target!r} 写了 {len(group)} 次",
                )
            )

    called_names = {call["name"] for call in calls}
    for required in scenario.required_tools:
        if required not in called_names:
            findings.append(
                Finding(
                    "required_tool_missing", CATEGORY_OF_REPEAT, "channel_substitution",
                    max((c["round"] for c in calls), default=0), 0, required,
                    f"任务需要的 {required!r} 从未被调用(全程调用了 {sorted(called_names)})",
                )
            )
    return findings


def adaptability(trace: list[dict]) -> dict:
    """出错后是否变招:同一调用错后原样重试=不变招;换参数或换工具=变招。"""
    calls = _flatten(trace)
    errors = [c for c in calls if c["is_error"]]
    adapted = 0
    for index, call in enumerate(calls[:-1]):
        if not call["is_error"]:
            continue
        rest = calls[index + 1:]
        if not rest:
            continue
        next_call = rest[0]
        changed = (
            next_call["name"] != call["name"]
            or next_call["canonical"] != call["canonical"]
        )
        if changed:
            adapted += 1
    return {"errors": len(errors), "adapted_after_error": adapted}
