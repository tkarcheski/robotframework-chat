"""Robot Framework keywords for browser-based page evaluation.

Converts page HTML to markdown for LLM analysis instead of passing
raw HTML or screenshots. This gives the LLM structured text to reason
about rather than noisy markup.
"""

from __future__ import annotations

from robot.api.deco import keyword

try:
    from markdownify import markdownify as md  # type: ignore[import-not-found]
except ImportError:
    md = None  # type: ignore[assignment]

try:
    from bs4 import (  # type: ignore[import-not-found,import-untyped]
        BeautifulSoup,
    )
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]


class BrowserKeywords:
    """Keywords for converting web page content to markdown for LLM evaluation."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    @keyword("Convert HTML To Markdown")
    def convert_html_to_markdown(
        self,
        html: str,
        *,
        strip: str = "img,script,style,svg,noscript,iframe",
        max_length: int = 8000,
    ) -> str:
        """Convert HTML content to clean markdown for LLM consumption."""
        if md is None:
            raise RuntimeError(
                "markdownify is not installed. Run: uv sync --extra playwright"
            )

        strip_tags = [t.strip() for t in strip.split(",") if t.strip()]

        # decompose() drops the tags and their content, not just the markup
        if BeautifulSoup is not None and strip_tags:
            soup = BeautifulSoup(html, "html.parser")
            for tag_name in strip_tags:
                for tag in soup.find_all(tag_name):
                    tag.decompose()
            html = str(soup)

        result: str = md(
            html,
            heading_style="ATX",
            bullets="-",
        )

        # Collapse excessive whitespace
        lines = result.split("\n")
        cleaned: list[str] = []
        blank_count = 0
        for line in lines:
            stripped = line.rstrip()
            if not stripped:
                blank_count += 1
                if blank_count <= 2:
                    cleaned.append("")
            else:
                blank_count = 0
                cleaned.append(stripped)

        output = "\n".join(cleaned).strip()

        if len(output) > max_length:
            output = output[:max_length] + "\n\n[...truncated]"

        return output

    @keyword("Build Evaluation Prompt")
    def build_evaluation_prompt(
        self,
        markdown: str,
        page_type: str = "dashboard",
        context: str = "",
    ) -> str:
        """Build an LLM evaluation prompt for a page converted to markdown."""
        prompts = {
            "dashboard": (
                "You are reviewing an Apache Superset dashboard. "
                "The dashboard content has been converted to markdown below.\n\n"
                "Evaluate the following:\n"
                "1. Does the dashboard contain meaningful data or is it empty?\n"
                "2. Are there any charts with missing data, errors, or stale dates?\n"
                "3. Is the layout logical and the information actionable?\n"
                "4. What specific improvements would you suggest?\n\n"
                "Be concise. List issues as bullet points. "
                "If everything looks good, say so briefly.\n\n"
            ),
            "repository": (
                "You are reviewing a GitHub repository page. "
                "The page content has been converted to markdown below.\n\n"
                "Evaluate the following:\n"
                "1. Is the README clear and complete?\n"
                "2. How many open issues and PRs are visible?\n"
                "3. Is the project actively maintained (recent commits)?\n"
                "4. What improvements would you suggest for the repo?\n\n"
                "Be concise. List findings as bullet points.\n\n"
            ),
            "issues": (
                "You are reviewing a GitHub issues page. "
                "The page content has been converted to markdown below.\n\n"
                "Evaluate the following:\n"
                "1. How many issues are open?\n"
                "2. Are issues well-labeled and categorized?\n"
                "3. Which issues are highest priority based on labels and age?\n"
                "4. Are there stale issues that should be closed?\n"
                "5. Suggest the top 3 issues to work on next and why.\n\n"
                "Be concise. List findings as bullet points.\n\n"
            ),
        }

        prompt = prompts.get(page_type, prompts["dashboard"])
        if context:
            prompt += f"Additional context: {context}\n\n"
        prompt += f"--- PAGE CONTENT (markdown) ---\n\n{markdown}"

        return prompt
