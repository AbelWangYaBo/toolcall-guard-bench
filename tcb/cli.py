"""CLI 入口:list / validate / selftest / run / report。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """读项目根 .env(存在则设入环境,不覆盖已有值)。"""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _fmt_row(cells: list[str], widths: list[int]) -> str:
    return "  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()


def cmd_list(args: argparse.Namespace) -> int:
    from .scenarios import load_all

    scenarios = load_all()
    if args.category:
        scenarios = [s for s in scenarios if s.category == args.category]
    rows = [(s.id, s.category, s.subcategory, str(len(s.tools)), str(s.max_rounds)) for s in scenarios]
    print(_fmt_row(["ID", "分类", "子类", "工具数", "轮上限"], [8, 24, 24, 6, 6]))
    for row in rows:
        print(_fmt_row(row, [8, 24, 24, 6, 6]))
    print(f"\n共 {len(rows)} 个场景")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .scenarios import load_all

    problems: list[str] = []
    for scenario in load_all():
        if not scenario.id or len(scenario.id) < 3:
            problems.append(f"{scenario}: id 不合法")
        if not scenario.tools:
            problems.append(f"{scenario.id}: 工具集为空")
        for tool in scenario.tools:
            schema_problems = _schema_smoke(tool.parameters)
            for problem in schema_problems:
                problems.append(f"{scenario.id}/{tool.name}: {problem}")
        for tool_name in list(scenario.reference_fields) + list(scenario.relative_path_fields) + list(scenario.write_targets):
            if tool_name not in {t.name for t in scenario.tools}:
                problems.append(f"{scenario.id}: 字段配置引用了未注册工具 {tool_name!r}")
        if not scenario.task.strip():
            problems.append(f"{scenario.id}: 任务文本为空")
    if problems:
        print("❌ 校验失败:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"✅ 全部 {len(load_all())} 个场景结构校验通过")
    return 0


def _schema_smoke(schema: dict) -> list[str]:
    from .schema import validate

    problems = []
    if not isinstance(schema, dict) or schema.get("type") != "object":
        problems.append("parameters 必须是 type=object 的 schema")
        return problems
    probe = validate({}, schema)
    for message in probe:
        if not message.startswith("missing_required"):
            problems.append(f"空参数校验异常: {message}")
    return problems


def cmd_selftest(args: argparse.Namespace) -> int:
    """离线检测器自检:用两条手工合成轨迹(取材于真实故障形态)验证判定逻辑。"""
    from .detectors import detect
    from .scenario import Scenario, Tool

    write_tool = Tool(
        "write_file", "写文件",
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"], "additionalProperties": False},
    )
    run_tool = Tool("run_python", "执行代码", {"type": "object", "properties": {"code": {"type": "string"}},
                                               "required": ["code"], "additionalProperties": False})
    scenario = Scenario(
        id="SELFTEST", category="repetitive_calls", subcategory="synthetic",
        task="(synthetic)", tools=[run_tool, write_tool],
        required_tools=["run_python"], write_targets={"write_file": "path"},
    )

    def round_record(index: int, calls: list[tuple[str, dict]], errors: list[bool]) -> dict:
        return {
            "round": index,
            "content": None,
            "tool_calls": [
                {"id": f"c{index}_{seq}", "name": name, "arguments": args, "raw_arguments": ""}
                for seq, (name, args) in enumerate(calls)
            ],
            "results": [{"result": {}, "is_error": err} for err in errors],
            "usage": {},
        }

    # 轨迹 1(真实故障形态 A):同参 write_file ×3 + 编造 python 工具
    write_args = {"path": "parse.py", "content": "import json\n..."}
    trace1 = [
        round_record(0, [("write_file", write_args)], [False]),
        round_record(1, [("write_file", write_args)], [False]),
        round_record(2, [("write_file", write_args)], [False]),
        round_record(3, [("python", {"code": "print(1)"})], [True]),
    ]
    detectors1 = {f.detector for f in detect(trace1, scenario, set())}
    expected1 = {"identical_repeat", "unknown_tool", "required_tool_missing", "repeated_write_target"}

    # 轨迹 2(真实故障形态 B):读 PDF 0 行×2 + /tmp 绝对路径报错后原样重试
    save_tool = Tool(
        "save_output", "保存输出(相对路径)",
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"], "additionalProperties": False},
    )
    read_tool = Tool("read_file", "读文件", {"type": "object",
                                             "properties": {"path": {"type": "string"}},
                                             "required": ["path"], "additionalProperties": False})
    scenario2 = Scenario(
        id="SELFTEST2", category="repetitive_calls", subcategory="synthetic",
        task="(synthetic)", tools=[read_tool, save_tool],
        relative_path_fields={"save_output": ["path"]},
    )
    tmp_args = {"path": "/tmp/result.json", "content": "{}"}
    trace2 = [
        round_record(0, [("read_file", {"path": "paper.pdf"})], [False]),
        round_record(1, [("read_file", {"path": "paper.pdf"})], [False]),
        round_record(2, [("save_output", tmp_args)], [True]),
        round_record(3, [("save_output", tmp_args)], [True]),
    ]
    detectors2 = {f.detector for f in detect(trace2, scenario2, {"paper.pdf"})}
    expected2 = {"identical_repeat", "out_of_domain_path", "error_retry_unchanged"}

    failures = []
    if not expected1 <= detectors1:
        failures.append(f"轨迹1 缺失: {expected1 - detectors1}(实际 {sorted(detectors1)})")
    if not expected2 <= detectors2:
        failures.append(f"轨迹2 缺失: {expected2 - detectors2}(实际 {sorted(detectors2)})")
    if failures:
        print("❌ selftest 失败:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("✅ selftest 通过:两条真实故障形态的合成轨迹,检测器全部命中")
    print(f"   轨迹1: {sorted(detectors1)}")
    print(f"   轨迹2: {sorted(detectors2)}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .client import Client
    from .report import write_report
    from .runner import run_scenario
    from .scenarios import load_all

    scenarios = load_all()
    if args.scenario:
        scenarios = [s for s in scenarios if s.id == args.scenario]
        if not scenarios:
            print(f"未找到场景 {args.scenario};用 `tcb list` 查看")
            return 1
    if args.category:
        scenarios = [s for s in scenarios if s.category == args.category]
    if not scenarios:
        print("没有匹配的场景")
        return 1

    client = Client(base_url=args.base_url, api_key=args.api_key, model=args.model)
    print(f"模型: {client.model} @ {client.base_url}")
    print(f"场景: {len(scenarios)} 个,预计 LLM 调用 ≤ {sum(s.max_rounds for s in scenarios)} 轮\n")

    results = []
    for index, scenario in enumerate(scenarios, 1):
        print(f"[{index}/{len(scenarios)}] {scenario.id} {scenario.subcategory} ... ", end="", flush=True)
        try:
            result = run_scenario(scenario, client, max_rounds=args.rounds)
        except Exception as exc:  # noqa: BLE001 - 单场景失败不终止整个 run
            print(f"执行异常: {exc}")
            continue
        results.append(result)
        flags = len(result["findings"])
        mark = "✅" if result["success"] else "❌"
        print(f"{mark} 调用{result['total_calls']}次, findings {flags}, 用时 {result['elapsed_s']}s")

    if not results:
        print("没有任何场景完成")
        return 1
    out_dir = write_report(results, PROJECT_ROOT / "results", client.model)
    print(f"\n报告: {out_dir / 'report.md'}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report import render_markdown, summarize

    run_dir = Path(args.run_dir)
    report_json = run_dir / "report.json"
    if not report_json.exists():
        print(f"未找到 {report_json}")
        return 1
    data = json.loads(report_json.read_text(encoding="utf-8"))
    print(render_markdown(data["summary"], data["results"], data["model"]))
    return 0


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(
        prog="tcb", description="toolcall-guard-bench: 意外工具调用/重复循环调用评测"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出场景")
    p_list.add_argument("--category", help="按分类过滤")
    p_list.set_defaults(func=cmd_list)

    p_validate = sub.add_parser("validate", help="离线结构校验(不调模型)")
    p_validate.set_defaults(func=cmd_validate)

    p_selftest = sub.add_parser("selftest", help="离线检测器自检(不调模型)")
    p_selftest.set_defaults(func=cmd_selftest)

    p_run = sub.add_parser("run", help="运行评测(调真实模型)")
    p_run.add_argument("--scenario", help="只跑指定 ID")
    p_run.add_argument("--category", help="只跑指定分类")
    p_run.add_argument("--model", help="覆盖 TCB_MODEL")
    p_run.add_argument("--base-url", help="覆盖 TCB_BASE_URL")
    p_run.add_argument("--api-key", help="覆盖 TCB_API_KEY")
    p_run.add_argument("--rounds", type=int, help="覆盖每场景轮次上限")
    p_run.set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="重渲染某次运行的报告")
    p_report.add_argument("run_dir", help="results/ 下的运行目录")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
