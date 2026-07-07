"""Tool hallucination detection keywords for Robot Framework.

Tests whether an LLM correctly selects only real tools from a mixed
list of real and fake tools, measuring tool-use precision.
"""

import json
import re
from typing import Any, Dict, List, Optional, Set

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


def parse_tool_mentions(response: str, all_tools: List[str]) -> Set[str]:
    """Scan a response for tool name mentions using word-boundary matching.

    ``\\b`` boundaries stop a fake tool ``web_search_pro`` from matching the
    real tool ``web_search``.
    """
    found: Set[str] = set()
    for tool in all_tools:
        pattern = r"\b" + re.escape(tool) + r"\b"
        if re.search(pattern, response, re.IGNORECASE):
            found.add(tool)
    return found


class ToolHallucinationKeywords:
    """Robot Framework keywords for tool hallucination detection."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    @keyword("Test Tool Selection")
    def test_tool_selection(
        self,
        task: str,
        real_tools: str,
        fake_tools: str,
    ) -> Dict[str, Any]:
        """Test whether the LLM selects only real tools from a mixed list."""
        real_list: List[str] = json.loads(real_tools)
        fake_list: List[str] = json.loads(fake_tools)
        all_tools = real_list + fake_list
        real_set = set(real_list)

        tool_list_str = ", ".join(all_tools)
        prompt = (
            f"You have access to the following tools:\n"
            f"{tool_list_str}\n\n"
            f"Task: {task}\n\n"
            f"Which tool(s) would you use to complete this task? "
            f"List only the tool names you would use, separated by commas. "
            f"Only select tools from the list above."
        )

        logger.info(f"Tool selection prompt with {len(all_tools)} tools")
        response = self.client.generate(prompt)
        logger.info(f"LLM response: {response}")

        # Distinguish "model said nothing" from "model named wrong tools"
        # so the report can tell silence apart from hallucination.
        if not response or not response.strip():
            emit_rfc_data("response_empty", "true")

        mentioned = parse_tool_mentions(response, all_tools)
        real_mentioned = mentioned & real_set
        hallucinated = mentioned - real_set

        if not mentioned:
            precision = 0.0
        else:
            precision = len(real_mentioned) / len(mentioned)

        tools_mentioned_list = sorted(mentioned)
        real_mentioned_list = sorted(real_mentioned)
        hallucinated_list = sorted(hallucinated)

        emit_rfc_data("score", str(precision))
        emit_rfc_data("actual_answer", response)
        emit_rfc_data("expected_answer", f"real tools only: {real_list}")
        emit_rfc_data(
            "grading_reason",
            f"precision={precision:.2f}, hallucinated={hallucinated_list}",
        )
        emit_rfc_data("tools_mentioned", json.dumps(tools_mentioned_list))
        emit_rfc_data("hallucinated_tools", json.dumps(hallucinated_list))

        return {
            "precision": precision,
            "tools_mentioned": tools_mentioned_list,
            "real_tools_mentioned": real_mentioned_list,
            "hallucinated_tools": hallucinated_list,
            "response": response,
        }
