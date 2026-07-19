"""Tests for rfc.computer_use_keywords: browser actions as dispatchable tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rfc.agent_tool import ToolCall, new_tool_call
from rfc.computer_use_keywords import (
    ComputerUseDispatcher,
    ComputerUseKeywords,
    _coerce_arguments,
    computer_use_tool_schemas,
    tool_result_to_dict,
    tool_schema_to_dict,
)

EXPECTED_TOOLS = {
    "browser_new_page",
    "browser_click",
    "browser_type_text",
    "browser_read_markdown",
    "browser_screenshot",
}


class TestToolSchemas:
    def test_exposes_five_browser_tools(self) -> None:
        schemas = computer_use_tool_schemas()
        assert {s.name for s in schemas} == EXPECTED_TOOLS

    def test_required_fields_are_declared(self) -> None:
        by_name = {s.name: s for s in computer_use_tool_schemas()}
        assert by_name["browser_new_page"].required == ["url"]
        assert by_name["browser_click"].required == ["selector"]
        assert by_name["browser_type_text"].required == ["selector", "text"]
        assert by_name["browser_read_markdown"].required == []
        assert by_name["browser_screenshot"].required == []

    def test_required_names_exist_in_parameters(self) -> None:
        for schema in computer_use_tool_schemas():
            for field in schema.required:
                assert field in schema.parameters

    def test_tool_schema_to_dict_round_trips_fields(self) -> None:
        schema = computer_use_tool_schemas()[0]
        d = tool_schema_to_dict(schema)
        assert d["name"] == schema.name
        assert d["required"] == schema.required
        assert d["parameters"] == schema.parameters


class TestDispatcher:
    def _dispatcher(self, browser: MagicMock) -> ComputerUseDispatcher:
        # Inject a trivial markdown converter to avoid the markdownify dep.
        return ComputerUseDispatcher(
            browser, markdown_converter=lambda html: f"MD::{html}"
        )

    def test_dispatch_new_page_calls_browser(self) -> None:
        browser = MagicMock()
        disp = self._dispatcher(browser)
        result = disp.dispatch(
            new_tool_call("browser_new_page", {"url": "data:text/html,<h1>hi</h1>"})
        )
        assert result.success is True
        browser.new_page.assert_called_once_with("data:text/html,<h1>hi</h1>")
        assert "Opened page" in result.output

    def test_dispatch_click_calls_browser(self) -> None:
        browser = MagicMock()
        disp = self._dispatcher(browser)
        result = disp.dispatch(new_tool_call("browser_click", {"selector": "#go"}))
        assert result.success is True
        browser.click.assert_called_once_with("#go")

    def test_dispatch_type_text_calls_browser(self) -> None:
        browser = MagicMock()
        disp = self._dispatcher(browser)
        result = disp.dispatch(
            new_tool_call("browser_type_text", {"selector": "#in", "text": "hello"})
        )
        assert result.success is True
        browser.type_text.assert_called_once_with("#in", "hello")
        assert "5 char" in result.output

    def test_dispatch_read_markdown_converts_page_source(self) -> None:
        browser = MagicMock()
        browser.get_page_source.return_value = "<h1>Report</h1>"
        disp = self._dispatcher(browser)
        result = disp.dispatch(new_tool_call("browser_read_markdown", {}))
        assert result.success is True
        assert result.output == "MD::<h1>Report</h1>"

    def test_dispatch_screenshot_returns_path(self) -> None:
        browser = MagicMock()
        browser.take_screenshot.return_value = "/tmp/shot.png"
        disp = self._dispatcher(browser)
        result = disp.dispatch(
            new_tool_call("browser_screenshot", {"filename": "shot"})
        )
        assert result.success is True
        browser.take_screenshot.assert_called_once_with(filename="shot")
        assert "/tmp/shot.png" in result.output

    def test_dispatch_screenshot_without_filename_uses_default(self) -> None:
        browser = MagicMock()
        browser.take_screenshot.return_value = "/tmp/embed.png"
        disp = self._dispatcher(browser)
        result = disp.dispatch(new_tool_call("browser_screenshot", {}))
        assert result.success is True
        browser.take_screenshot.assert_called_once_with()

    def test_unknown_tool_returns_failed_result(self) -> None:
        disp = self._dispatcher(MagicMock())
        result = disp.dispatch(new_tool_call("browser_teleport", {}))
        assert result.success is False
        assert "Unknown tool" in (result.error or "")

    def test_missing_required_argument_is_reported(self) -> None:
        disp = self._dispatcher(MagicMock())
        result = disp.dispatch(new_tool_call("browser_click", {}))
        assert result.success is False
        assert "Missing required argument" in (result.error or "")

    def test_browser_exception_becomes_failed_result(self) -> None:
        browser = MagicMock()
        browser.new_page.side_effect = RuntimeError("no browser process")
        disp = self._dispatcher(browser)
        result = disp.dispatch(new_tool_call("browser_new_page", {"url": "x"}))
        assert result.success is False
        assert "RuntimeError" in (result.error or "")
        assert "no browser process" in (result.error or "")

    def test_dispatch_never_raises(self) -> None:
        # A ToolCall carrying non-string args should still yield a ToolResult.
        browser = MagicMock()
        disp = self._dispatcher(browser)
        bad = ToolCall(
            id="c",
            tool_name="browser_new_page",
            arguments={"url": None},
            timestamp=0.0,
            call_number=0,
        )
        result = disp.dispatch(bad)
        assert result.tool_call_id == "c"

    def test_tool_names_property(self) -> None:
        disp = self._dispatcher(MagicMock())
        assert set(disp.tool_names) == EXPECTED_TOOLS

    def test_execution_time_is_recorded(self) -> None:
        disp = self._dispatcher(MagicMock())
        result = disp.dispatch(new_tool_call("browser_click", {"selector": "#a"}))
        assert result.execution_time_ms >= 0.0


class TestCoerceArguments:
    def test_none_becomes_empty_dict(self) -> None:
        assert _coerce_arguments(None) == {}

    def test_empty_string_becomes_empty_dict(self) -> None:
        assert _coerce_arguments("") == {}

    def test_dict_passthrough(self) -> None:
        assert _coerce_arguments({"a": 1}) == {"a": 1}

    def test_json_string_parsed(self) -> None:
        assert _coerce_arguments('{"selector": "#x"}') == {"selector": "#x"}

    def test_json_non_object_rejected(self) -> None:
        with pytest.raises(ValueError):
            _coerce_arguments("[1, 2]")

    def test_bad_type_rejected(self) -> None:
        with pytest.raises(TypeError):
            _coerce_arguments(123)


class TestToolResultToDict:
    def test_serializes_all_fields(self) -> None:
        result = tool_result_to_dict(
            ComputerUseDispatcher(MagicMock(), markdown_converter=str).dispatch(
                new_tool_call("browser_click", {"selector": "#a"})
            )
        )
        assert set(result) == {
            "tool_call_id",
            "success",
            "output",
            "error",
            "execution_time_ms",
        }


class TestComputerUseKeywords:
    def test_get_tool_names(self) -> None:
        kw = ComputerUseKeywords()
        assert set(kw.get_computer_use_tool_names()) == EXPECTED_TOOLS

    def test_get_tools_returns_dicts(self) -> None:
        kw = ComputerUseKeywords()
        tools = kw.get_computer_use_tools()
        assert all(isinstance(t, dict) for t in tools)
        assert {t["name"] for t in tools} == EXPECTED_TOOLS

    def test_get_tools_json_is_valid_json(self) -> None:
        import json

        kw = ComputerUseKeywords()
        parsed = json.loads(kw.get_computer_use_tools_json())
        assert {t["name"] for t in parsed} == EXPECTED_TOOLS

    def test_dispatch_resolves_browser_via_builtin(self) -> None:
        kw = ComputerUseKeywords()
        fake_browser = MagicMock()
        fake_browser.get_page_source.return_value = "<h1>ok</h1>"
        with patch(
            "robot.libraries.BuiltIn.BuiltIn.get_library_instance",
            return_value=fake_browser,
        ):
            # Force the default converter to avoid the markdownify dependency.
            with patch(
                "rfc.computer_use_keywords._default_markdown_converter",
                side_effect=lambda html: f"MD::{html}",
            ):
                result = kw.dispatch_computer_use_call("browser_read_markdown", None)
        assert result["success"] is True
        assert result["output"] == "MD::<h1>ok</h1>"

    def test_dispatch_accepts_json_string_arguments(self) -> None:
        kw = ComputerUseKeywords()
        fake_browser = MagicMock()
        with patch(
            "robot.libraries.BuiltIn.BuiltIn.get_library_instance",
            return_value=fake_browser,
        ):
            result = kw.dispatch_computer_use_call(
                "browser_click", '{"selector": "#submit"}'
            )
        assert result["success"] is True
        fake_browser.click.assert_called_once_with("#submit")

    def test_dispatcher_rebinds_when_live_browser_instance_changes(self) -> None:
        """Regression (#193): GLOBAL scope must not dispatch against a stale Browser.

        The library is ``ROBOT_LIBRARY_SCOPE = "GLOBAL"``, so one instance is
        reused across every suite. When a later suite resolves a *different*
        live Browser instance -- a SUITE-scoped Browser, or a second suite that
        imports its own -- the cached dispatcher must rebind to the live
        instance rather than keep driving the first, possibly-closed, Browser.
        """
        kw = ComputerUseKeywords()
        first_browser = MagicMock(name="suite1_browser")
        second_browser = MagicMock(name="suite2_browser")

        with patch(
            "robot.libraries.BuiltIn.BuiltIn.get_library_instance",
            return_value=first_browser,
        ):
            kw.dispatch_computer_use_call("browser_click", {"selector": "#a"})
        first_browser.click.assert_called_once_with("#a")

        # A later suite resolves a different live Browser instance.
        with patch(
            "robot.libraries.BuiltIn.BuiltIn.get_library_instance",
            return_value=second_browser,
        ):
            kw.dispatch_computer_use_call("browser_click", {"selector": "#b"})

        # The second suite's call must reach the live instance, not the stale one.
        second_browser.click.assert_called_once_with("#b")
        assert first_browser.click.call_count == 1

    def test_dispatcher_is_cached_for_the_same_live_browser(self) -> None:
        """The dispatcher is still cached across dispatches to one live Browser."""
        kw = ComputerUseKeywords()
        browser = MagicMock()
        with patch(
            "robot.libraries.BuiltIn.BuiltIn.get_library_instance",
            return_value=browser,
        ):
            kw.dispatch_computer_use_call("browser_click", {"selector": "#a"})
            first = kw._get_dispatcher()
            second = kw._get_dispatcher()
        assert first is second
        assert first.browser is browser

    def test_assert_tool_call_succeeded_passes_on_success(self) -> None:
        kw = ComputerUseKeywords()
        kw.assert_tool_call_succeeded({"success": True})

    def test_assert_tool_call_succeeded_raises_on_failure(self) -> None:
        kw = ComputerUseKeywords()
        with pytest.raises(AssertionError):
            kw.assert_tool_call_succeeded(
                {"success": False, "error": "boom", "tool_call_id": "c1"}
            )


class TestSchemaDispatchRoundTrip:
    """Consumer contract: the PUBLISHED schema JSON is dispatchable.

    A ReAct/MCP consumer only ever sees the serialized schema, then builds a
    ToolCall from a tool's declared ``required`` fields. This closes the loop
    schema JSON -> ToolCall -> dispatch -> ToolResult, proving each handler
    consumes exactly the fields its schema advertises as required -- drift the
    piecewise per-tool tests would not catch.
    """

    def _dispatcher(self) -> ComputerUseDispatcher:
        return ComputerUseDispatcher(
            MagicMock(), markdown_converter=lambda html: f"MD::{html}"
        )

    def test_every_published_tool_dispatches_from_its_required_fields(self) -> None:
        import json

        published = json.loads(ComputerUseKeywords().get_computer_use_tools_json())
        disp = self._dispatcher()
        for tool in published:
            args = {field: "x" for field in tool["required"]}
            result = disp.dispatch(new_tool_call(tool["name"], args))
            assert result.success is True, (
                f"{tool['name']} is not dispatchable from its declared required "
                f"fields {tool['required']}: {result.error}"
            )

    def test_omitting_a_required_field_fails_cleanly(self) -> None:
        import json

        published = [
            t
            for t in json.loads(ComputerUseKeywords().get_computer_use_tools_json())
            if t["required"]
        ]
        disp = self._dispatcher()
        for tool in published:
            # Drop the first declared required field; the handler must surface a
            # clean failed ToolResult, not raise.
            args = {field: "x" for field in tool["required"][1:]}
            result = disp.dispatch(new_tool_call(tool["name"], args))
            assert result.success is False
            assert "Missing required argument" in (result.error or "")
