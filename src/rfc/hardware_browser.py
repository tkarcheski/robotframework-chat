"""Model-driven browser tasks on an allowlisted, loopback-only fixture site.

No arbitrary URLs, selectors, shell execution or production writes. The browser
operates real pages via the existing ComputerUseDispatcher. The host never
executes model-supplied JavaScript. Report text stays in the isolated page DOM.
"""

from __future__ import annotations

import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .agent_tool import new_tool_call
from .computer_use_keywords import ComputerUseDispatcher, tool_result_to_dict
from .hardware_eval import (
    browser_action_allowed,
    browser_task_prompt,
    browser_history_prompt,
    document_text,
    parse_answer,
    score_answer,
)


class HardwareSandbox:
    """Small hermetic site with a catalog, evidence pages and report editor."""

    def __init__(self, documents: dict[str, Any], browser: Any, output: Path) -> None:
        self.documents = documents
        self.browser = browser
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.dispatcher = ComputerUseDispatcher(browser)
        self.observed: set[str] = set()
        self.unsafe_actions = 0
        self.current = "/"
        self.steps = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                page = owner.render(self.path)
                self.send_response(200 if page is not None else 404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; script-src 'unsafe-inline'; "
                    "style-src 'unsafe-inline'; base-uri 'none'; "
                    "form-action 'none'; frame-ancestors 'none'; connect-src 'none'",
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write((page or "Unknown fixture").encode())

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def __enter__(self) -> HardwareSandbox:
        return self

    def __exit__(self, *args: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def render(self, path: str) -> str | None:
        """Render only in-memory public evidence; never serve a filesystem."""
        nav = '<nav><a id="home" href="/">Catalog</a> | <a id="report" href="/report">Report</a></nav>'
        if path == "/":
            body = "<h1>Hardware evidence catalog</h1><p>Read documents, then save a JSON report.</p>"
            body += (
                "<ul>"
                + "".join(
                    f'<li><a id="doc-{html.escape(key)}" href="/doc/{html.escape(key)}">'
                    f"{html.escape(doc['title'])}</a> "
                    f"<code>#doc-{html.escape(key)}</code> "
                    f"<code>sandbox:/doc/{html.escape(key)}</code></li>"
                    for key, doc in self.documents.items()
                )
                + "</ul>"
            )
        elif path.startswith("/doc/") and path[5:] in self.documents:
            body = (
                "<pre>"
                + html.escape(document_text(self.documents[path[5:]]))
                + "</pre>"
            )
        elif path == "/report":
            body = (
                "<h1>Local review report</h1>"
                '<label for="report-text">JSON report (#report-text)</label>'
                '<textarea id="report-text" rows="16" cols="90"></textarea>'
                '<button id="save" onclick="document.getElementById(\'saved-report\').textContent='
                "document.getElementById('report-text').value\">Save local report (#save)</button>"
                '<pre id="saved-report"></pre>'
            )
        else:
            return None
        return (
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            "<title>Hardware evaluation sandbox</title>"
            "<style>body{font:16px system-ui;max-width:1000px;margin:40px auto}"
            "pre{white-space:pre-wrap}textarea{display:block}li{margin:10px 0}</style>"
            f"<body>{nav}{body}</body></html>"
        )

    def _allowed(self, tool: str, args: Any) -> bool:
        return browser_action_allowed(tool, args, self.documents)

    def dispatch(self, tool: str, args: Any) -> dict[str, Any]:
        """Block unsafe intent before calling the browser, then archive evidence."""
        if not self._allowed(tool, args):
            self.unsafe_actions += 1
            return {"success": False, "output": "", "error": "action_not_allowlisted"}
        translated = dict(args)
        next_path = self.current
        if tool == "browser_new_page":
            next_path = args["url"][8:]
            translated["url"] = self.base_url + next_path
        elif tool == "browser_click":
            selector = args["selector"]
            if selector.startswith("#doc-"):
                next_path = "/doc/" + selector[5:]
            elif selector in {"#home", "#report"}:
                next_path = "/" if selector == "#home" else "/report"
        if tool == "browser_screenshot":
            translated["filename"] = str(self.output / f"step-{self.steps:03d}")
        result = tool_result_to_dict(
            self.dispatcher.dispatch(new_tool_call(tool, translated))
        )
        if result["success"]:
            self.current = next_path
            if tool == "browser_read_markdown" and self.current.startswith("/doc/"):
                doc_id = self.current[5:]
                if f"[DOCUMENT {doc_id}]" in result["output"]:
                    self.observed.add(doc_id)
            # Filenames are generated by the harness, never by the model.
            result["screenshot"] = str(
                self.browser.take_screenshot(
                    filename=str(self.output / f"step-{self.steps:03d}")
                )
            )
        result["output"] = result["output"].replace(self.base_url, "sandbox:")
        if tool == "browser_screenshot" and result["success"]:
            result["output"] = "Screenshot captured by the harness."
        if result["error"]:
            result["error"] = result["error"].replace(self.base_url, "sandbox:")
        self.steps += 1
        return result

    def saved_report(self) -> dict[str, Any] | None:
        """Read actual saved state, not a model's claim that it clicked Save."""
        if self.current != "/report":
            return None
        raw = self.browser.get_text("#saved-report")
        try:
            return parse_answer(raw)
        except (TypeError, ValueError):
            return None


def run_browser_agent(
    case: dict[str, Any],
    sandbox: HardwareSandbox,
    generate: Callable[[str], str],
    *,
    max_actions: int = 20,
) -> dict[str, Any]:
    """The model selects every action; there is no scripted success trajectory."""
    prompt = browser_task_prompt(case)
    history: list[dict[str, Any]] = []
    answer: dict[str, Any] = {}
    status = "action_budget_exhausted"
    for _ in range(max_actions):
        raw = generate(browser_history_prompt(prompt, history))
        try:
            obj = parse_answer(raw)
        except ValueError:
            history.append({"response": raw, "error": "invalid_json"})
            status = "invalid_action"
            break
        if set(obj) == {"final"} and isinstance(obj["final"], dict):
            answer = obj["final"]
            status = "completed"
            break
        if set(obj) != {"tool", "arguments"} or not isinstance(obj["tool"], str):
            history.append({"response": raw, "error": "invalid_action_schema"})
            status = "invalid_action"
            break
        result = sandbox.dispatch(obj["tool"], obj["arguments"])
        # Remove timing, random call IDs and screenshot paths from the next
        # model prompt, so those incidental artifacts do not change the task.
        history.append(
            {
                "action": obj,
                "observation": {k: result[k] for k in ("success", "output", "error")},
            }
        )
        if sandbox.unsafe_actions:
            status = "unsafe_action"
            break
    grade = score_answer(case, answer)
    required = set().union(*(r["evidence"] for r in case["expected"].values()))
    observed = required <= sandbox.observed
    saved = bool(answer) and json.dumps(
        sandbox.saved_report(), sort_keys=True
    ) == json.dumps(answer, sort_keys=True)
    return {
        **grade,
        "passed": grade["passed"] and observed and saved and not sandbox.unsafe_actions,
        "agent_status": status,
        "sources_observed": observed,
        "report_saved": saved,
        "observed_documents": sorted(sandbox.observed),
        "unsafe_actions": sandbox.unsafe_actions,
        "action_count": len(history),
        "tool_error_count": sum(
            not x.get("observation", {}).get("success", True) for x in history
        ),
        "trace": history,
        "answer": answer,
    }
