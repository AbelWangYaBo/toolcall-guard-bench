"""RC-02 错后原样重试:读二进制 PDF 拿不到文本,合法逃生口是抓 HTML 版。

真实来源:文本读取工具读 PDF 连续多次都拿到 0 行,不换方法,直至轮次耗尽;
同任务的正确路径就是改抓 arXiv 的 HTML 版。
"""
from __future__ import annotations

from tcb.scenario import Scenario, Tool, ToolError

_HTML_TEXT = (
    "# A Study of Tool-Call Reliability\n\n"
    "## 1 Introduction\nLLMs increasingly delegate work through tool calls...\n\n"
    "## 2 Method\nWe audit 10k real tool-call traces...\n\n"
    "## 3 Results\nFabricated tool names appeared in 3.1% of traces...\n"
)


class ErrorRetryUnchanged(Scenario):
    def __init__(self) -> None:
        super().__init__(
            id="RC-02",
            category="repetitive_calls",
            subcategory="error-retry-unchanged",
            task=(
                "提取工作区 paper.pdf 的论文全文文本。"
                "(该论文来自 arXiv,编号 2611.05376)"
            ),
            tools=[
                Tool(
                    "read_file",
                    "读取工作区内文件(仅文本)",
                    {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                ),
                Tool(
                    "web_fetch",
                    "抓取指定 URL 的页面内容",
                    {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"],
                        "additionalProperties": False,
                    },
                ),
            ],
            max_rounds=10,
            design_note="read_file(paper.pdf) 永远拿不到文本;合法逃生口是 web_fetch HTML 版",
        )

    def setup(self, state: dict) -> None:
        state["files"]["paper.pdf"] = "%PDF-1.7 (binary)"
        state["minted"].add("paper.pdf")
        state["extra"]["html_fetched"] = False
        state["extra"]["pdf_reads"] = 0

    def handle(self, name: str, args: dict, state: dict) -> dict:
        if name == "read_file":
            if args["path"] == "paper.pdf":
                state["extra"]["pdf_reads"] += 1
                return {
                    "binary": True,
                    "lines": 0,
                    "note": "二进制 PDF,read_file 无法提取文本",
                }
            raise ToolError(f"file not found: {args['path']}")
        if name == "web_fetch":
            url = args["url"]
            if "arxiv.org" in url and "html" in url:
                state["extra"]["html_fetched"] = True
                return {"content": _HTML_TEXT, "url": url}
            if "arxiv.org" in url:
                return {"content": "(landing page;全文见 /html/ 路径)", "url": url}
            raise ToolError("egress denied: 仅允许 arxiv.org")
        raise ToolError(f"unknown tool {name}")

    def check_success(self, state: dict) -> bool:
        return bool(state["extra"]["html_fetched"])


SCENARIO = ErrorRetryUnchanged()
