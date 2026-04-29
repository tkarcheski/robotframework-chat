"""Robot Framework keywords for context window stress testing.

Tests how LLMs degrade as context fills up by injecting increasing amounts
of filler content before a retrieval question. Measures at 25%, 50%, 75%,
and 95% of the model's declared context window.
"""

import re
import time
from typing import Any, Dict, Optional

from robot.api import logger
from robot.api.deco import keyword

from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


# Filler corpus: Wikipedia-style passages for realistic RAG simulation.
# Rotated to fill budget.
_FILLER_PASSAGES = (
    """The history of the Internet traces back to the 1960s when the United
    States Department of Defense funded research into packet-switching networks.
    ARPANET, the precursor to the modern Internet, was first demonstrated in 1969,
    connecting four university nodes: UCLA, Stanford Research Institute, UC Santa
    Barbara, and the University of Utah. Through the 1970s, researchers developed
    key networking protocols. Vinton Cerf and Bob Kahn published the foundational
    paper on TCP/IP in 1974. By the 1980s, the network had expanded significantly.""",
    """Our solar system consists of eight planets orbiting the Sun. The four inner
    planets — Mercury, Venus, Earth, and Mars — are terrestrial worlds with solid
    rocky surfaces. The four outer planets are gas and ice giants. Jupiter, the
    largest planet, has a mass more than twice that of all other planets combined.
    Its Great Red Spot is a massive storm that has been observed for centuries.
    Saturn is famous for its extensive ring system made primarily of ice particles.""",
    """World War I began on July 28, 1914, triggered by the assassination of Archduke
    Franz Ferdinand of Austria-Hungary in Sarajevo on June 28, 1914. The conflict
    quickly escalated as a complex web of alliances drew major European powers into
    the war. The Central Powers — Germany, Austria-Hungary, the Ottoman Empire, and
    Bulgaria — fought against the Allied Powers including France, Britain, Russia,
    and later Italy and the United States. The war introduced devastating new
    technologies including machine guns, poison gas, tanks, and aircraft.""",
    """Ancient Rome was founded on the seven hills of the Tiber River valley. The
    Roman Republic, established around 509 BCE, developed a system of government
    featuring consuls, the Senate, and various assemblies. Over centuries, Rome
    expanded through military conquest, absorbing territories across the Mediterranean.
    The Roman Empire, established under Augustus in 27 BCE, witnessed unprecedented
    peace and prosperity known as the Pax Romana. Architecture, law, and engineering
    achievements from this era continue to influence modern civilization.""",
    """The human body contains approximately 37 trillion cells organized into various
    systems. The nervous system transmits electrical and chemical signals throughout
    the body, controlling voluntary and involuntary functions. The circulatory system,
    powered by the heart, distributes oxygen-rich blood to all tissues. The immune
    system defends against pathogens through white blood cells and antibodies. The
    digestive system breaks down food into nutrients that are absorbed into the
    bloodstream. All these systems work together in remarkable coordination.""",
)


class ContextWindowKeywords:
    """Robot Framework keywords for context window stress testing."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    # Regex for whitespace normalization in needle matching
    _WS_COLLAPSE = re.compile(r"\s+")

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: int = 2,
        client: Any = None,
    ):
        if client is not None:
            self.client = client
        else:
            timeout = resolve_timeout(timeout)
            self.client = create_provider(timeout=timeout, max_retries=int(max_retries))

    @keyword("Build Filled Prompt")
    def build_filled_prompt(
        self,
        needle_fact: str,
        question: str,
        fill_pct: float,
        context_window: int,
        position: str = "end",
        max_tokens: int = 256,
    ) -> str:
        """Build a prompt with filler content surrounding a needle fact.

        Args:
            needle_fact: The fact to embed (the "needle").
            question: The retrieval question to ask.
            fill_pct: Percentage of context window to fill (0-95).
            context_window: The model's context window size (tokens).
            position: Where to place the needle: 'start', 'middle', or 'end'.
            max_tokens: Response tokens to reserve (prevents overfill).

        Returns:
            Assembled prompt string with filler and needle positioned strategically.
        """
        # Reserve headroom for response generation
        safety_margin = 50
        usable_budget = context_window - max_tokens - safety_margin

        # Calculate target fill size
        target_tokens = int(usable_budget * fill_pct / 100)

        # Assemble filler by cycling through passages
        filler = self._assemble_filler(target_tokens)

        # Position the needle
        if position == "start":
            content = f"{needle_fact}\n\n{filler}"
        elif position == "middle":
            # Split filler in half
            filler_first = filler[: len(filler) // 2]
            filler_second = filler[len(filler) // 2 :]
            content = f"{filler_first}\n\n{needle_fact}\n\n{filler_second}"
        else:  # "end"
            content = f"{filler}\n\n{needle_fact}"

        # Build final prompt with context and question
        prompt = (
            f"Below is some reference material:\n\n{content}\n\n"
            f"Question: {question}\n\n"
            f"Answer the question based ONLY on the material above. Be concise."
        )

        return prompt

    def _assemble_filler(self, target_tokens: int) -> str:
        """Assemble filler content to approximately target size.

        Uses word-split token estimation (~4x rough vs BPE). Cycles through
        passages to reach target budget with deterministic, repeatable content.
        """
        filler = ""
        passage_idx = 0

        while True:
            passage = _FILLER_PASSAGES[passage_idx % len(_FILLER_PASSAGES)]
            passage = passage.strip()
            filler += passage + "\n\n"

            tokens = len(filler.split())
            if tokens >= target_tokens:
                break
            passage_idx += 1

        return filler.strip()

    @keyword("Ask At Fill Level")
    def ask_at_fill_level(
        self,
        needle_fact: str,
        question: str,
        expected_answer: str,
        fill_pct: float,
        position: str,
        context_window: int,
        max_tokens: int = 256,
    ) -> Dict[str, Any]:
        """Ask the LLM to retrieve the needle at a specific fill level.

        Builds a filled prompt, sends it to the LLM, checks if the needle
        was recalled, and emits metrics for analysis.

        Args:
            needle_fact: The fact embedded in context.
            question: The retrieval question.
            expected_answer: What the model should output.
            fill_pct: Context fill percentage (25, 50, 75, 95).
            position: Needle position ('start', 'middle', 'end').
            context_window: Model's context window size.
            max_tokens: Max response tokens.

        Returns:
            Dict with keys: 'response', 'recalled', 'latency_ms', 'prompt_tokens'.
        """
        # Build prompt
        prompt = self.build_filled_prompt(
            needle_fact, question, fill_pct, context_window, position, max_tokens
        )

        # Configure client context window before generation
        if hasattr(self.client, "num_ctx"):
            self.client.num_ctx = context_window
        if hasattr(self.client, "max_tokens"):
            self.client.max_tokens = max_tokens

        # Measure latency
        start_time = time.time()
        response = self.client.generate(prompt)
        latency_ms = (time.time() - start_time) * 1000

        # Check if needle was recalled
        recalled = self.check_needle_recalled(response, expected_answer)

        # Estimate tokens
        prompt_tokens = len(prompt.split())

        # Emit metrics
        emit_rfc_data("fill_pct", str(fill_pct))
        emit_rfc_data("needle_position", position)
        emit_rfc_data("prompt_tokens_est", str(prompt_tokens))
        emit_rfc_data("latency_ms", str(int(latency_ms)))
        emit_rfc_data("needle_recalled", str(recalled))

        logger.info(
            f"Fill {fill_pct}% @ {position}: "
            f"recalled={recalled}, latency={int(latency_ms)}ms, "
            f"tokens={prompt_tokens}"
        )

        return {
            "response": response,
            "recalled": recalled,
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
        }

    @keyword("Check Needle Recalled")
    def check_needle_recalled(self, response: str, expected_answer: str) -> bool:
        """Check if the expected answer appears in the response.

        Uses word-boundary matching to avoid false positives (e.g., "90 days"
        won't match "190 days"). Performs case-insensitive, whitespace-normalized
        matching on individual tokens.

        Args:
            response: The model's response text.
            expected_answer: The fact/snippet expected to be recalled.

        Returns:
            True if expected_answer tokens are found as a consecutive sequence.
        """
        if not response or not expected_answer:
            return False

        # Normalize and split into words
        resp_normalized = self._normalize_text(response)
        expected_normalized = self._normalize_text(expected_answer)

        resp_words = resp_normalized.split()
        expected_words = expected_normalized.split()

        if not expected_words or not resp_words:
            return False

        # Check if expected words appear as a consecutive subsequence
        for i in range(len(resp_words) - len(expected_words) + 1):
            if resp_words[i : i + len(expected_words)] == expected_words:
                return True

        return False

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison: lowercase, collapse whitespace."""
        text = text.lower()
        # Remove all non-alphanumeric except hyphens and spaces
        text = re.sub(r"[^\w\s\-]", "", text)
        # Normalize spaces around hyphens: " - " becomes "-"
        text = re.sub(r"\s*-\s*", "-", text)
        # Collapse remaining whitespace
        text = self._WS_COLLAPSE.sub(" ", text).strip()
        return text
