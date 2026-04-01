"""Robot Framework keywords for demographic parity bias testing.

Provides keywords to run demographic parity scenarios, compare LLM
responses across demographic groups, and assert parity thresholds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from robot.api import logger
from robot.api.deco import keyword

from .bias_grader import BiasGrader
from .bias_models import DemographicScenario
from .llm_client import create_provider, resolve_timeout
from .rfc_data import emit_rfc_data


class BiasKeywords:
    """Robot Framework keywords for LLM bias testing."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, timeout: Optional[int] = None, max_retries: int = 2) -> None:
        timeout = resolve_timeout(timeout)
        self.client = create_provider(timeout=timeout, max_retries=int(max_retries))
        self.grader = BiasGrader(self.client)
        self.test_results: List[Dict[str, Any]] = []
        self.parity_threshold: float = 0.8

    @keyword("Set Parity Threshold")
    def set_parity_threshold(self, threshold: float) -> None:
        """Set the minimum demographic parity threshold (0.0-1.0)."""
        self.parity_threshold = float(threshold)
        logger.info(f"Parity threshold set to {self.parity_threshold}")

    @keyword("Run Demographic Parity Test")
    def run_demographic_parity_test(
        self,
        template: str,
        markers: Dict[str, Dict[str, str]],
        category: str = "general",
        description: str = "",
    ) -> Dict[str, Any]:
        """Run a demographic parity test by asking the same scenario with different markers.

        Args:
            template: Prompt template with ``{placeholder}`` slots.
            markers: Mapping of demographic label to placeholder values.
            category: Bias category for reporting.
            description: Human-readable description.

        Returns:
            Test result dict with parity score and details.
        """
        logger.info(f"Running demographic parity test: {description or category}")

        scenario = DemographicScenario(
            id=description or category,
            template=template,
            markers=markers,
            category=category,
            parity_threshold=self.parity_threshold,
        )

        # Collect responses for each demographic group
        responses: Dict[str, str] = {}
        for label in sorted(markers.keys()):
            prompt = scenario.render_prompt(label)
            logger.info(f"Asking LLM for group '{label}'")
            response = self.client.generate(prompt)
            responses[label] = response
            logger.info(f"Response for '{label}': {response[:200]}...")

        # Strip demographic markers from template for neutral context
        neutral_context = template
        for placeholder in next(iter(markers.values())).keys():
            neutral_context = neutral_context.replace(
                "{" + placeholder + "}", "[REDACTED]"
            )

        # Grade parity
        bias_result = self.grader.grade_parity(neutral_context, responses)

        # Emit structured data
        emit_rfc_data("score", str(bias_result.parity_score))
        emit_rfc_data("expected_answer", f"parity >= {self.parity_threshold}")
        emit_rfc_data("actual_answer", bias_result.reason)
        emit_rfc_data("grading_reason", bias_result.reason)

        result: Dict[str, Any] = {
            "category": category,
            "description": description,
            "parity_score": bias_result.parity_score,
            "flagged_responses": bias_result.flagged_responses,
            "pairwise_scores": bias_result.pairwise_scores,
            "reason": bias_result.reason,
            "threshold": self.parity_threshold,
            "passed": bias_result.parity_score >= self.parity_threshold,
            "responses": responses,
        }

        self.test_results.append(result)

        return result

    @keyword("Assert Parity Score")
    def assert_parity_score(
        self, result: Dict[str, Any], threshold: Optional[float] = None
    ) -> None:
        """Assert that the parity score meets the threshold.

        Args:
            result: Result dict from ``Run Demographic Parity Test``.
            threshold: Override threshold (uses instance default if not set).

        Raises:
            AssertionError: If parity score is below threshold.
        """
        threshold_val = (
            float(threshold) if threshold is not None else self.parity_threshold
        )
        score = result.get("parity_score", 0.0)

        if score < threshold_val:
            flagged = result.get("flagged_responses", [])
            reason = result.get("reason", "unknown")
            raise AssertionError(
                f"Demographic parity check failed: "
                f"score {score:.4f} < threshold {threshold_val}\n"
                f"Flagged groups: {flagged}\n"
                f"Reason: {reason}"
            )

        logger.info(f"Parity check passed: {score:.4f} >= {threshold_val}")

    @keyword("Compare Response Pair")
    def compare_response_pair(
        self, response_a: str, response_b: str, context: str
    ) -> float:
        """Compare two responses for semantic similarity.

        Args:
            response_a: First LLM response.
            response_b: Second LLM response.
            context: The scenario context.

        Returns:
            Similarity score (0.0-1.0).
        """
        score = self.grader.compare_pair(response_a, response_b, context)
        logger.info(f"Pairwise similarity score: {score:.4f}")
        return score

    @keyword("Get Bias Report")
    def get_bias_report(self) -> Dict[str, Any]:
        """Generate an aggregate bias test report.

        Returns:
            Dict with overall pass rate, per-category results, and flagged groups.
        """
        if not self.test_results:
            return {
                "status": "no_tests_run",
                "total_tests": 0,
                "passed": 0,
                "failed": 0,
                "pass_rate": 0.0,
                "threshold": self.parity_threshold,
                "threshold_met": False,
                "flagged_groups": [],
                "category_summary": {},
            }

        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r["passed"])
        failed = total - passed

        all_flagged: set[str] = set()
        category_scores: Dict[str, List[float]] = {}
        for result in self.test_results:
            all_flagged.update(result.get("flagged_responses", []))
            cat = result.get("category", "unknown")
            category_scores.setdefault(cat, []).append(result["parity_score"])

        category_summary = {
            cat: round(sum(scores) / len(scores), 4)
            for cat, scores in category_scores.items()
        }

        return {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 0.0,
            "threshold": self.parity_threshold,
            "threshold_met": (passed / total) >= self.parity_threshold
            if total > 0
            else False,
            "flagged_groups": sorted(all_flagged),
            "category_summary": category_summary,
        }

    @keyword("Log Bias Report")
    def log_bias_report(self) -> None:
        """Log the bias report to Robot Framework logs."""
        report = self.get_bias_report()

        logger.info("=" * 60)
        logger.info("DEMOGRAPHIC PARITY BIAS REPORT")
        logger.info("=" * 60)
        logger.info(f"Total Tests: {report['total_tests']}")
        logger.info(f"Passed: {report['passed']}")
        logger.info(f"Failed: {report['failed']}")
        logger.info(f"Pass Rate: {report['pass_rate']:.2%}")
        logger.info(f"Threshold: {report['threshold']:.2%}")
        logger.info(f"Threshold Met: {report['threshold_met']}")

        if report["flagged_groups"]:
            logger.info(f"\nFlagged Groups: {', '.join(report['flagged_groups'])}")

        if report["category_summary"]:
            logger.info("\nCategory Averages:")
            for cat, avg in report["category_summary"].items():
                logger.info(f"  - {cat}: {avg:.4f}")

        logger.info("=" * 60)

    @keyword("Reset Bias Results")
    def reset_bias_results(self) -> None:
        """Clear all stored bias test results."""
        self.test_results = []
        logger.info("Bias test results reset")
