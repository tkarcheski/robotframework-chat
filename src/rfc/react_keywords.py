"""ReAct (Reason + Act) loop keywords for Robot Framework.

Implements a multi-step reasoning loop where the LLM can call simulated
tools and must reach a final answer within a configured step budget.
"""

import json
import re
from typing import Any, Dict, Optional, Tuple

from robot.api import logger
from robot.api.deco import keyword

from .grader import Grader
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data

_REACT_RE = re.compile(
    r"(?:^|\n)\s*(?P<type>ACTION|FINAL_ANSWER)\s*:\s*(?P<value>.+)",
    re.IGNORECASE,
)


def parse_react_response(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse an LLM response for ACTION or FINAL_ANSWER directives."""
    match = _REACT_RE.search(text)
    if match is None:
        return None, None
    directive = match.group("type").upper()
    value = match.group("value").strip()
    return directive, value


class ReActKeywords:
    """Robot Framework keywords for ReAct loop testing."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = Grader(self.client)

    @keyword("Run ReAct Loop")
    def run_react_loop(
        self,
        question: str,
        tool_descriptions: str,
        tool_results: str,
        expected_answer: str,
        max_steps: int = 5,
    ) -> Dict[str, Any]:
        """Execute a ReAct reasoning loop and grade the outcome."""
        max_steps = int(max_steps)
        tools_map: Dict[str, str] = json.loads(tool_results)
        trace: list[Dict[str, str]] = []

        system_prompt = (
            f"You are a reasoning agent. Answer the following question by "
            f"thinking step by step. You have access to these tools:\n"
            f"{tool_descriptions}\n\n"
            f"At each step, either call a tool or give your final answer.\n"
            f"To call a tool, write: ACTION: tool_name(args)\n"
            f"To give your final answer, write: FINAL_ANSWER: your answer\n\n"
            f"Question: {question}"
        )

        conversation = system_prompt
        final_answer: Optional[str] = None

        for step in range(1, max_steps + 1):
            logger.info(f"ReAct step {step}/{max_steps}")
            response = self.client.generate(conversation)
            directive, value = parse_react_response(response)

            if directive == "FINAL_ANSWER":
                final_answer = value
                trace.append(
                    {"step": str(step), "type": "FINAL_ANSWER", "content": value or ""}
                )
                break

            if directive == "ACTION":
                observation = tools_map.get(
                    value or "",
                    f"Error: tool '{value}' not found or returned no result.",
                )
                trace.append(
                    {
                        "step": str(step),
                        "type": "ACTION",
                        "action": value or "",
                        "observation": observation,
                    }
                )
                conversation += (
                    f"\n\nAssistant: {response}\nObservation: {observation}\n"
                )
            else:
                # Unparseable — treat as wasted step
                trace.append(
                    {"step": str(step), "type": "UNPARSEABLE", "content": response}
                )
                conversation += f"\n\nAssistant: {response}\nSystem: Please respond with ACTION: or FINAL_ANSWER:\n"

        budget_exceeded = final_answer is None
        steps_used = len(trace)

        if final_answer is not None:
            grade_result = self.grader.grade(question, expected_answer, final_answer)
            score = grade_result.score
            reason = grade_result.reason
        else:
            score = 0.0
            reason = f"Budget exceeded: no FINAL_ANSWER within {max_steps} steps"

        emit_rfc_data("score", str(score))
        emit_rfc_data("expected_answer", expected_answer)
        emit_rfc_data("actual_answer", final_answer or "")
        emit_rfc_data("grading_reason", reason)
        emit_rfc_data("react_steps_used", str(steps_used))
        emit_rfc_data("react_max_steps", str(max_steps))

        return {
            "score": score,
            "steps_used": steps_used,
            "max_steps": max_steps,
            "final_answer": final_answer,
            "budget_exceeded": budget_exceeded,
            "reason": reason,
            "trace": trace,
        }
