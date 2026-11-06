"""报告汇总:results/<run_id>/ 下写 report.md + report.json + 每场景轨迹。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

CATEGORY_TITLES = {
    "fabricated_tool_name": "工具名编造",
    "fabricated_parameters": "参数编造",
    "repetitive_calls": "重复/循环调用",
    "control": "对照组(假阳性校验)",
}


def write_report(results: list[dict], out_root: Path, model_label: str) -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for result in results:
        trace_path = out_dir / f"{result['scenario_id']}.json"
        trace_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    summary = summarize(results)
    (out_dir / "report.json").write_text(
        json.dumps({"model": model_label, "summary": summary, "results": _slim(results)},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (out_dir / "report.md").write_text(render_markdown(summary, results, model_label),
                                       encoding="utf-8")
    return out_dir


def summarize(results: list[dict]) -> dict:
    categories: dict[str, dict] = {}
    for result in results:
        category = result["category"]
        bucket = categories.setdefault(
            category,
            {"scenarios": 0, "flagged": 0, "calls": 0, "violations": 0, "success": 0,
             "detectors": {}},
        )
        bucket["scenarios"] += 1
        violations = len(result["findings"])
        if violations:
            bucket["flagged"] += 1
        bucket["calls"] += result["total_calls"]
        bucket["violations"] += violations
        bucket["success"] += 1 if result["success"] else 0
        for finding in result["findings"]:
            bucket["detectors"][finding["detector"]] = (
                bucket["detectors"].get(finding["detector"], 0) + 1
            )
    for bucket in categories.values():
        bucket["violation_rate"] = (
            round(bucket["violations"] / bucket["calls"], 4) if bucket["calls"] else 0.0
        )
    usage_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    usage = {key: sum(r["usage"].get(key, 0) for r in results) for key in usage_keys}
    return {"categories": categories, "usage": usage}


def render_markdown(summary: dict, results: list[dict], model_label: str) -> str:
    lines: list[str] = []
    lines.append(f"# Tool-Call Guard Bench 报告")
    lines.append("")
    lines.append(f"- 模型: `{model_label}`")
    lines.append(f"- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 场景数: {len(results)} | 总调用: {sum(r['total_calls'] for r in results)}")
    usage = summary["usage"]
    lines.append(
        f"- Token: 输入 {usage['prompt_tokens']:,} / 输出 {usage['completion_tokens']:,}"
        f" / 合计 {usage['total_tokens']:,}"
    )
    lines.append("")
    lines.append("## 分类总览")
    lines.append("")
    lines.append("| 分类 | 场景 | 命中场景 | 违规调用/总调用 | 违规率 | 任务成功 | 检测器命中 |")
    lines.append("|---|---|---|---|---|---|---|")
    for key in ("fabricated_tool_name", "fabricated_parameters", "repetitive_calls", "control"):
        bucket = summary["categories"].get(key)
        if not bucket:
            continue
        detectors = ", ".join(f"{k}×{v}" for k, v in sorted(bucket["detectors"].items())) or "—"
        lines.append(
            f"| {CATEGORY_TITLES[key]} | {bucket['scenarios']} | {bucket['flagged']} "
            f"| {bucket['violations']}/{bucket['calls']} | {bucket['violation_rate']:.1%} "
            f"| {bucket['success']}/{bucket['scenarios']} | {detectors} |"
        )
    lines.append("")
    lines.append("## 场景明细")
    for result in results:
        lines.append("")
        title = CATEGORY_TITLES.get(result["category"], result["category"])
        flag = "✅ 成功" if result["success"] else "❌ 未成功"
        lines.append(
            f"### {result['scenario_id']} · {title}/{result['subcategory']} — {flag}"
        )
        if result["design_note"]:
            lines.append(f"- 陷阱: {result['design_note']}")
        lines.append(
            f"- 轮次 {result['rounds_used']}/{result['max_rounds']}"
            f" · 调用 {result['total_calls']} 次"
            f" · 正常收尾 {'是' if result['finished_normally'] else '否(轮次耗尽)'}"
            f" · 用时 {result['elapsed_s']}s"
        )
        adapt = result["adaptability"]
        if adapt["errors"]:
            lines.append(
                f"- 纠错: 出错 {adapt['errors']} 次,其后立刻变招 {adapt['adapted_after_error']} 次"
            )
        if result["findings"]:
            lines.append("- 发现:")
            for finding in result["findings"]:
                lines.append(
                    f"  - [{finding['detector']}/{finding['subtype']}] "
                    f"第 {finding['round']} 轮 {finding['tool']}: {finding['evidence']}"
                )
        else:
            lines.append("- 发现: 无")
    lines.append("")
    lines.append("---")
    lines.append("轨迹与原始数据见本目录下各 `*.json`;判分口径见项目 README。")
    return "\n".join(lines) + "\n"


def _slim(results: list[dict]) -> list[dict]:
    """report.json 里去掉 trace 大字段,轨迹单独存文件。"""
    slim = []
    for result in results:
        item = {k: v for k, v in result.items() if k != "trace"}
        slim.append(item)
    return slim
