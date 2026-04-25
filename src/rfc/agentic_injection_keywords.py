"""Robot Framework keywords for agentic prompt injection resistance testing.

These keywords drive a synthetic agent: the LLM receives a user task
plus a poisoned tool output (web scrape, API response, file read) and
the grader checks whether the LLM ignored the injection while still
completing the task.
"""

from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .agentic_injection_grader import AgenticInjectionGrader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


class AgenticInjectionKeywords:
    """Robot Framework keywords for agentic prompt injection testing."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2):
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = AgenticInjectionGrader(self.client)
        self.test_results: list[Dict[str, Any]] = []

    @keyword("Test Agentic Injection Resistance")
    def test_agentic_injection_resistance(
        self,
        original_task: str,
        poisoned_tool_output: str,
        canary: str,
        task_signal: str,
        tool_name: str = "tool",
        description: str = "",
    ) -> Dict[str, Any]:
        """Run one agentic prompt injection test case.

        Args:
            original_task: User task the agent should complete.
            poisoned_tool_output: Tool output containing the injection payload.
            canary: Unique token the injection tries to make the LLM emit.
            task_signal: Substring or regex proving the original task was done.
            tool_name: Identifier for the tool whose output is poisoned.
            description: Human-readable test description (for logs).

        Returns:
            Dict with grader signals, indicators, and the LLM response.
        """
        logger.info(
            f"Agentic injection test: {description or original_task[:50]}"
        )

        agent_prompt = self.grader.build_agent_prompt(
            original_task=original_task,
            poisoned_tool_output=poisoned_tool_output,
            tool_name=tool_name,
        )
        response = self.client.generate(agent_prompt)
        logger.info(f"LLM Response: {response[:200]}...")
        emit_rfc_data("actual_answer", response)

        grade = self.grader.grade(
            original_task=original_task,
            canary=canary,
            llm_response=response,
            task_signal=task_signal,
        )

        emit_rfc_data("score", str(1 if grade.resisted else 0))
        emit_rfc_data("expected_answer", "agent_resists_injection")
        reason_parts = [
            f"injection_followed={grade.signals['injection_followed']}",
            f"task_completed={grade.signals['task_completed']}",
            f"leakage_detected={grade.signals['leakage_detected']}",
            f"confidence={grade.confidence:.2f}",
        ]
        emit_rfc_data("grading_reason", " ".join(reason_parts))

        result = {
            "test_type": "agentic_prompt_injection",
            "description": description,
            "tool_name": tool_name,
            "original_task": original_task,
            "canary": canary,
            "task_signal": task_signal,
            "response": response,
            "resisted": grade.resisted,
            "confidence": grade.confidence,
            "signals": grade.signals,
            "indicators": grade.indicators,
        }
        self.test_results.append(result)
        return result

    @keyword("Assert Injection Resisted")
    def assert_injection_resisted(self, result: Dict[str, Any]) -> None:
        """Fail the test if the agent did not resist the injection."""
        if result.get("resisted", False):
            logger.info("Agent resisted agentic prompt injection.")
            return

        signals = result.get("signals", {})
        indicators = result.get("indicators", [])
        task = result.get("original_task", "")[:80]
        raise AssertionError(
            "Agentic injection not resisted.\n"
            f"  task: {task}\n"
            f"  injection_followed: {signals.get('injection_followed')}\n"
            f"  task_completed: {signals.get('task_completed')}\n"
            f"  leakage_detected: {signals.get('leakage_detected')}\n"
            f"  indicators: {indicators}"
        )

    @keyword("Run Agentic Injection Test Case")
    def run_agentic_injection_test_case(
        self,
        original_task: str,
        poisoned_tool_output: str,
        canary: str,
        task_signal: str,
        tool_name: str = "tool",
        description: str = "",
    ) -> Dict[str, Any]:
        """Convenience wrapper: run one test case and assert resistance."""
        result = self.test_agentic_injection_resistance(
            original_task=original_task,
            poisoned_tool_output=poisoned_tool_output,
            canary=canary,
            task_signal=task_signal,
            tool_name=tool_name,
            description=description,
        )
        self.assert_injection_resisted(result)
        return result

    @keyword("Get Agentic Injection Report")
    def get_agentic_injection_report(self) -> Dict[str, Any]:
        """Aggregate test results into a summary report."""
        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r.get("resisted"))
        failed = total - passed
        return {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": (passed / total) if total else 0.0,
            "test_results": self.test_results,
        }

    @keyword("Log Agentic Injection Report")
    def log_agentic_injection_report(self) -> None:
        """Log the agentic injection summary to Robot Framework logs."""
        report = self.get_agentic_injection_report()
        logger.info("=" * 60)
        logger.info("AGENTIC PROMPT INJECTION REPORT")
        logger.info("=" * 60)
        logger.info(f"Total tests: {report['total_tests']}")
        logger.info(f"Passed:      {report['passed']}")
        logger.info(f"Failed:      {report['failed']}")
        logger.info(f"Pass rate:   {report['pass_rate']:.2%}")
        logger.info("=" * 60)

    @keyword("Reset Agentic Injection Results")
    def reset_agentic_injection_results(self) -> None:
        """Clear stored agentic injection test results."""
        self.test_results = []
