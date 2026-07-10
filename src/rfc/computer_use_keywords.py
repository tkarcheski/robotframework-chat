"""Computer-use substrate v0: browser actions as dispatchable agent tools.

Wraps ``robotframework-browser`` (Browser library) page actions -- new page,
click, type text, read the current page as markdown, screenshot -- as
:class:`~rfc.agent_tool.ToolSchema` entries with an executor the ReAct runtime
(and the MCP server) can dispatch. This turns the primitives that already exist
(HTML->markdown in ``browser_keywords``; New Page / Click / Type Text /
screenshots in the Browser library) into real, callable tools.

The dispatcher is deliberately decoupled from Robot Framework: it takes a
``browser`` object (any instance exposing the Browser library's snake_case
keyword methods) and a markdown converter, so it is unit-testable with a mocked
Browser and reusable outside a Robot run (e.g. from the MCP server). The Robot
keyword library ``ComputerUseKeywords`` is a thin adapter that resolves the live
Browser instance via ``BuiltIn().get_library_instance``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from robot.api.deco import keyword

from .agent_tool import ToolCall, ToolResult, ToolSchema, new_tool_call
from .browser_keywords import BrowserKeywords

# Markdown converter callable: HTML string -> markdown string.
MarkdownConverter = Callable[[str], str]


def computer_use_tool_schemas() -> List[ToolSchema]:
    """Return the browser-action tool schemas exposed by the substrate.

    Names are prefixed ``browser_`` so they namespace cleanly when merged with
    other tool sets (e.g. over MCP).
    """
    return [
        ToolSchema(
            name="browser_new_page",
            description=(
                "Open a new browser page at the given URL. Accepts http(s), "
                "file:// and data: URLs."
            ),
            parameters={
                "url": {
                    "type": "string",
                    "description": "URL to navigate the new page to.",
                }
            },
            required=["url"],
        ),
        ToolSchema(
            name="browser_click",
            description="Click the first element matching a CSS/Browser selector.",
            parameters={
                "selector": {
                    "type": "string",
                    "description": "Selector of the element to click.",
                }
            },
            required=["selector"],
        ),
        ToolSchema(
            name="browser_type_text",
            description="Type text into the element matching a selector.",
            parameters={
                "selector": {
                    "type": "string",
                    "description": "Selector of the input element.",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type into the element.",
                },
            },
            required=["selector", "text"],
        ),
        ToolSchema(
            name="browser_read_markdown",
            description=(
                "Read the current page and return its content converted to "
                "markdown for LLM reasoning."
            ),
            parameters={},
            required=[],
        ),
        ToolSchema(
            name="browser_screenshot",
            description=(
                "Capture a screenshot of the current page. Returns the path to "
                "the saved artifact."
            ),
            parameters={
                "filename": {
                    "type": "string",
                    "description": (
                        "Screenshot filename or path. Defaults to the Browser "
                        "library's auto-embed behaviour."
                    ),
                }
            },
            required=[],
        ),
    ]


def tool_schema_to_dict(schema: ToolSchema) -> Dict[str, Any]:
    """Serialize a ToolSchema to a plain dict (for Robot / JSON consumers)."""
    return {
        "name": schema.name,
        "description": schema.description,
        "parameters": schema.parameters,
        "required": list(schema.required),
    }


def tool_result_to_dict(result: ToolResult) -> Dict[str, Any]:
    """Serialize a ToolResult to a plain dict Robot can index into."""
    return {
        "tool_call_id": result.tool_call_id,
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "execution_time_ms": result.execution_time_ms,
    }


def _default_markdown_converter(html: str) -> str:
    """Convert HTML to markdown via the existing BrowserKeywords logic."""
    return BrowserKeywords().convert_html_to_markdown(html)


class ComputerUseDispatcher:
    """Execute browser-action ToolCalls against a Browser library instance.

    ``browser`` is any object exposing the Browser library's keyword methods
    (``new_page``, ``click``, ``type_text``, ``get_page_source``,
    ``take_screenshot``). Keeping the dependency behind a plain attribute means
    the dispatcher unit-tests with a mock and does not import the (heavy,
    optional) Browser library itself.
    """

    def __init__(
        self,
        browser: Any,
        *,
        markdown_converter: Optional[MarkdownConverter] = None,
    ) -> None:
        self._browser = browser
        self._to_markdown: MarkdownConverter = (
            markdown_converter or _default_markdown_converter
        )
        self._handlers: Dict[str, Callable[[Dict[str, Any]], str]] = {
            "browser_new_page": self._act_new_page,
            "browser_click": self._act_click,
            "browser_type_text": self._act_type_text,
            "browser_read_markdown": self._act_read_markdown,
            "browser_screenshot": self._act_screenshot,
        }

    @property
    def tool_names(self) -> List[str]:
        """Names of the tools this dispatcher can execute."""
        return list(self._handlers)

    def dispatch(self, call: ToolCall) -> ToolResult:
        """Execute one ToolCall and return a ToolResult (never raises)."""
        start = time.perf_counter()
        handler = self._handlers.get(call.tool_name)
        if handler is None:
            return ToolResult(
                tool_call_id=call.id,
                success=False,
                output="",
                error=f"Unknown tool: {call.tool_name}",
                execution_time_ms=(time.perf_counter() - start) * 1000.0,
            )
        try:
            output = handler(call.arguments or {})
        except KeyError as exc:
            return ToolResult(
                tool_call_id=call.id,
                success=False,
                output="",
                error=f"Missing required argument: {exc}",
                execution_time_ms=(time.perf_counter() - start) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001 - surface as a failed ToolResult
            return ToolResult(
                tool_call_id=call.id,
                success=False,
                output="",
                error=f"{type(exc).__name__}: {exc}",
                execution_time_ms=(time.perf_counter() - start) * 1000.0,
            )
        return ToolResult(
            tool_call_id=call.id,
            success=True,
            output=output,
            error=None,
            execution_time_ms=(time.perf_counter() - start) * 1000.0,
        )

    # --- individual actions -------------------------------------------------

    def _act_new_page(self, args: Dict[str, Any]) -> str:
        url = args["url"]
        self._browser.new_page(url)
        return f"Opened page: {url}"

    def _act_click(self, args: Dict[str, Any]) -> str:
        selector = args["selector"]
        self._browser.click(selector)
        return f"Clicked: {selector}"

    def _act_type_text(self, args: Dict[str, Any]) -> str:
        selector = args["selector"]
        text = args["text"]
        self._browser.type_text(selector, text)
        return f"Typed {len(text)} char(s) into: {selector}"

    def _act_read_markdown(self, args: Dict[str, Any]) -> str:
        html = self._browser.get_page_source()
        return self._to_markdown(html)

    def _act_screenshot(self, args: Dict[str, Any]) -> str:
        filename = args.get("filename")
        if filename:
            path = self._browser.take_screenshot(filename=filename)
        else:
            path = self._browser.take_screenshot()
        return f"Screenshot saved: {path}"


def _coerce_arguments(arguments: Any) -> Dict[str, Any]:
    """Accept a dict, a JSON string, or None and return an arguments dict."""
    if arguments is None or arguments == "":
        return {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        parsed = json.loads(arguments)
        if not isinstance(parsed, dict):
            raise ValueError("arguments JSON must decode to an object")
        return parsed
    raise TypeError(
        f"arguments must be a dict or JSON string, got {type(arguments).__name__}"
    )


class ComputerUseKeywords:
    """Robot Framework keywords exposing browser actions as dispatchable tools.

    The Browser library must be imported in the suite (see the ``computer_use``
    suite for the import-or-skip pattern); this library resolves that live
    instance lazily so it can be imported even when playwright is absent.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, browser_library_name: str = "Browser") -> None:
        self._browser_library_name = browser_library_name
        self._dispatcher: Optional[ComputerUseDispatcher] = None

    def _get_dispatcher(self) -> ComputerUseDispatcher:
        if self._dispatcher is None:
            from robot.libraries.BuiltIn import (  # type: ignore[import-not-found]
                BuiltIn,
            )

            browser = BuiltIn().get_library_instance(self._browser_library_name)
            self._dispatcher = ComputerUseDispatcher(browser)
        return self._dispatcher

    @keyword("Get Computer Use Tools")
    def get_computer_use_tools(self) -> List[Dict[str, Any]]:
        """Return the browser-action tool schemas as a list of dicts."""
        return [tool_schema_to_dict(s) for s in computer_use_tool_schemas()]

    @keyword("Get Computer Use Tools JSON")
    def get_computer_use_tools_json(self) -> str:
        """Return the tool schemas as a JSON string (portable payload)."""
        return json.dumps([tool_schema_to_dict(s) for s in computer_use_tool_schemas()])

    @keyword("Get Computer Use Tool Names")
    def get_computer_use_tool_names(self) -> List[str]:
        """Return the names of the browser-action tools."""
        return [s.name for s in computer_use_tool_schemas()]

    @keyword("Dispatch Computer Use Call")
    def dispatch_computer_use_call(
        self,
        tool_name: str,
        arguments: Any = None,
        call_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dispatch one browser tool call through ToolSchema execution.

        ``arguments`` may be a Robot dictionary or a JSON string. Returns a
        result dict with ``success``/``output``/``error`` keys.
        """
        args = _coerce_arguments(arguments)
        call = new_tool_call(tool_name, args, call_id=call_id)
        result = self._get_dispatcher().dispatch(call)
        return tool_result_to_dict(result)

    @keyword("Assert Tool Call Succeeded")
    def assert_tool_call_succeeded(self, result: Dict[str, Any]) -> None:
        """Fail the test unless a dispatched tool result reports success."""
        if not result.get("success"):
            raise AssertionError(
                f"Tool call failed: {result.get('error')} "
                f"(tool_call_id={result.get('tool_call_id')})"
            )
