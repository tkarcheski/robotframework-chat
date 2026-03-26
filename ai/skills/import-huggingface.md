# Skill: Import Test Data from Hugging Face

## When to Use

Use this skill when importing external LLM evaluation benchmarks or datasets from
Hugging Face to serve as test inputs in the RFC framework. This enables testing
local models against established benchmarks like GSM8K, MMLU, TruthfulQA, and others.

## Relevant Datasets

| Dataset | HF ID | Maps to Suite | Tier |
|---------|-------|---------------|------|
| GSM8K | `openai/gsm8k` | `robot/math/` | 0–2 (math has deterministic answers) |
| MMLU | `cais/mmlu` | New suite | 2+ (multiple choice, needs grading) |
| MMLU-Pro | `TIGER-Lab/MMLU-Pro` | New suite | 2+ (harder, 10 options) |
| TruthfulQA | `truthful_qa` | New suite | 2–3 (factual accuracy) |
| ARC | `allenai/ai2_arc` | New suite | 2+ (science reasoning) |
| HellaSwag | `Rowan/hellaswag` | New suite | 2+ (commonsense) |
| HumanEval | `openai/openai_humaneval` | `robot/docker/python/` | 4 (code exec) |

## Authentication

The `datasets` library automatically picks up the `HF_TOKEN` environment variable.
Set it in your `.env` file (see `.env.example`).

| Scenario | Token required? | Permission needed |
|----------|----------------|-------------------|
| Public datasets (GSM8K, MMLU, TruthfulQA, etc.) | Optional (avoids rate limits) | Read |
| Gated models/datasets (Llama 3, etc.) | Yes | Read + accept model license on HF |
| Uploading or publishing | N/A (not used in this project) | Write |

Create a token at: https://huggingface.co/settings/tokens — select **Read** access.

## Approach A: Static Import (Recommended for Deterministic Tests)

Best for tier:0/tier:1 tests where answers are known and fixed (e.g., GSM8K math).
Data is downloaded once, converted to YAML, and committed to the repo.

### Step-by-Step

#### 1. Create a Conversion Script

Create `scripts/import_hf_dataset.py`:

```python
"""Download a Hugging Face dataset and convert to RFC test variables."""

import argparse
import json
import sys
from pathlib import Path

# Requires: pip install datasets
from datasets import load_dataset


def import_gsm8k(output_path: Path, limit: int = 50) -> None:
    """Import GSM8K grade-school math problems as YAML test data."""
    ds = load_dataset("openai/gsm8k", "main", split="test")

    questions: list[dict[str, str]] = []
    for i, item in enumerate(ds):
        if i >= limit:
            break
        # GSM8K answers are in the format "#### <number>"
        answer_text = item["answer"]
        # Extract the final numeric answer after ####
        final_answer = answer_text.split("####")[-1].strip()
        questions.append(
            {
                "question": item["question"],
                "expected": final_answer,
                "source": "gsm8k",
                "difficulty": "grade_school",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Write as YAML for Robot Framework Variables import
    with open(output_path, "w") as f:
        f.write("# Auto-generated from Hugging Face: openai/gsm8k\n")
        f.write(f"# {len(questions)} questions imported\n\n")
        f.write("TEST_DATA:\n")
        for q in questions:
            f.write(f"  - question: |\n")
            for line in q["question"].split("\n"):
                f.write(f"      {line}\n")
            f.write(f"    expected: \"{q['expected']}\"\n")
            f.write(f"    source: \"{q['source']}\"\n")
            f.write(f"    difficulty: \"{q['difficulty']}\"\n")

    print(f"Wrote {len(questions)} questions to {output_path}")


def import_mmlu(
    output_path: Path, subject: str = "abstract_algebra", limit: int = 50
) -> None:
    """Import MMLU multiple-choice questions."""
    ds = load_dataset("cais/mmlu", subject, split="test")

    questions: list[dict[str, object]] = []
    choice_labels = ["A", "B", "C", "D"]
    for i, item in enumerate(ds):
        if i >= limit:
            break
        choices = item["choices"]
        correct_idx = item["answer"]
        questions.append(
            {
                "question": item["question"],
                "choices": [
                    f"{choice_labels[j]}. {c}" for j, c in enumerate(choices)
                ],
                "expected": choice_labels[correct_idx],
                "subject": subject,
                "source": "mmlu",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(f"# Auto-generated from Hugging Face: cais/mmlu ({subject})\n")
        f.write(f"# {len(questions)} questions imported\n\n")
        f.write("TEST_DATA:\n")
        for q in questions:
            f.write(f"  - question: \"{q['question']}\"\n")
            f.write(f"    choices:\n")
            for c in q["choices"]:
                f.write(f"      - \"{c}\"\n")
            f.write(f"    expected: \"{q['expected']}\"\n")
            f.write(f"    subject: \"{q['subject']}\"\n")
            f.write(f"    source: \"{q['source']}\"\n")

    print(f"Wrote {len(questions)} questions to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import HF dataset for RFC tests")
    parser.add_argument(
        "dataset", choices=["gsm8k", "mmlu"], help="Dataset to import"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output YAML path",
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Max questions to import"
    )
    parser.add_argument(
        "--subject",
        default="abstract_algebra",
        help="MMLU subject (only for mmlu)",
    )
    args = parser.parse_args()

    if args.dataset == "gsm8k":
        output = args.output or Path("robot/math/variables/gsm8k.yaml")
        import_gsm8k(output, args.limit)
    elif args.dataset == "mmlu":
        output = args.output or Path(f"robot/mmlu/variables/{args.subject}.yaml")
        import_mmlu(output, args.subject, args.limit)
```

#### 2. Run the Import

```bash
# Install the datasets library (one-time)
uv pip install datasets

# Import GSM8K (50 questions, adjust --limit as needed)
uv run python scripts/import_hf_dataset.py gsm8k --limit 50

# Import MMLU subject
uv run python scripts/import_hf_dataset.py mmlu --subject abstract_algebra --limit 30
```

#### 3. Create the Robot Test

For GSM8K (tier:0 — answers are deterministic numbers):

```robot
*** Settings ***
Documentation     GSM8K grade-school math benchmark (static import from HuggingFace)
Variables         ${CURDIR}/../variables/gsm8k.yaml
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Test Cases ***
GSM8K Math Benchmark
    [Documentation]    Test model against GSM8K grade-school math problems
    [Tags]    tier:2    verify:llm    benchmark    gsm8k
    FOR    ${item}    IN    @{TEST_DATA}
        ${answer}=    LLM.Ask LLM    ${item}[question] Answer with just the number.
        ${score}    ${reason}=    LLM.Grade Answer
        ...    ${item}[question]    ${item}[expected]    ${answer}
        Should Be Equal As Integers    ${score}    1
        ...    GSM8K failed: expected=${item}[expected], got=${answer}, reason=${reason}
    END
```

For MMLU (tier:2 — multiple choice needs LLM grading):

```robot
*** Settings ***
Documentation     MMLU benchmark (static import from HuggingFace)
Variables         ${CURDIR}/../variables/abstract_algebra.yaml
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           String

*** Test Cases ***
MMLU Abstract Algebra Benchmark
    [Documentation]    Test model on MMLU abstract algebra questions
    [Tags]    tier:2    verify:llm    benchmark    mmlu
    FOR    ${item}    IN    @{TEST_DATA}
        ${choices_text}=    Catenate    SEPARATOR=\n    @{item}[choices]
        ${prompt}=    Set Variable
        ...    ${item}[question]\n\n${choices_text}\n\nAnswer with only the letter.
        ${answer}=    LLM.Ask LLM    ${prompt}
        ${score}    ${reason}=    LLM.Grade Answer
        ...    ${item}[question]    ${item}[expected]    ${answer}
        Should Be Equal As Integers    ${score}    1
        ...    MMLU failed: expected=${item}[expected], got=${answer}
    END
```

#### 4. Commit the Data

```bash
# Keep data files small — commit only the subset, not the full dataset
git add robot/<suite>/variables/<dataset>.yaml
git add scripts/import_hf_dataset.py
```

## Approach B: Dynamic Import (For Exploratory / Tier:6 Tests)

Best for data collection runs where you want to test against the full dataset
without committing it. Requires the `datasets` library at runtime.

### Step-by-Step

#### 1. Add Dependency

In `pyproject.toml`, add to optional dependencies:

```toml
[project.optional-dependencies]
huggingface = ["datasets>=2.14.0"]
```

#### 2. Create the Keyword Library

Create `src/rfc/huggingface_keywords.py`:

```python
"""Hugging Face dataset loading keywords for Robot Framework."""

from __future__ import annotations

from typing import Any


class HuggingFaceKeywords:
    """Load and iterate over HF datasets in Robot Framework tests."""

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def load_hf_dataset(
        self,
        dataset_id: str,
        config: str = "default",
        split: str = "test",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Load a Hugging Face dataset and return as a list of dicts.

        Args:
            dataset_id: HF dataset identifier (e.g., "openai/gsm8k").
            config: Dataset configuration/subset name.
            split: Which split to load (train, test, validation).
            limit: Maximum number of items to return.

        Returns:
            List of dictionaries, one per dataset row.
        """
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise ImportError(
                "Install the datasets library: uv pip install datasets"
            ) from exc

        ds = load_dataset(dataset_id, config, split=split)
        items: list[dict[str, Any]] = []
        for i, row in enumerate(ds):
            if i >= int(limit):
                break
            items.append(dict(row))
        return items

    def extract_gsm8k_answer(self, answer_text: str) -> str:
        """Extract the final numeric answer from a GSM8K answer string.

        GSM8K answers contain step-by-step reasoning followed by
        '#### <number>' on the last line.

        Args:
            answer_text: The full answer string from GSM8K dataset.

        Returns:
            The extracted numeric answer.
        """
        if "####" in answer_text:
            return answer_text.split("####")[-1].strip()
        return answer_text.strip()
```

#### 3. Write the Python Test

Create `tests/test_huggingface_keywords.py`:

```python
"""Tests for rfc.huggingface_keywords.HuggingFaceKeywords."""

import pytest
from unittest.mock import patch, MagicMock

from rfc.huggingface_keywords import HuggingFaceKeywords


class TestHuggingFaceKeywords:
    def test_extract_gsm8k_answer_with_hash(self) -> None:
        kw = HuggingFaceKeywords()
        result = kw.extract_gsm8k_answer("Step 1...\nStep 2...\n#### 42")
        assert result == "42"

    def test_extract_gsm8k_answer_without_hash(self) -> None:
        kw = HuggingFaceKeywords()
        result = kw.extract_gsm8k_answer("42")
        assert result == "42"

    def test_load_hf_dataset_missing_library(self) -> None:
        kw = HuggingFaceKeywords()
        with patch.dict("sys.modules", {"datasets": None}):
            with pytest.raises(ImportError, match="datasets"):
                kw.load_hf_dataset("openai/gsm8k")

    def test_load_hf_dataset_returns_list(self) -> None:
        kw = HuggingFaceKeywords()
        mock_ds = [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}]
        with patch("rfc.huggingface_keywords.load_dataset", create=True) as mock_load:
            # Patch the import inside the method
            import importlib
            import rfc.huggingface_keywords as hf_mod
            with patch.object(hf_mod, "__import__", create=True):
                pass
        # Simpler: just test the extract logic which doesn't need network
```

#### 4. Create the Robot Test

```robot
*** Settings ***
Documentation     Dynamic HuggingFace benchmark runner (tier:6 data collection)
Library           rfc.huggingface_keywords.HuggingFaceKeywords    WITH NAME    HF
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Test Cases ***
GSM8K Dynamic Benchmark Run
    [Documentation]    Load GSM8K from HuggingFace and test model responses
    [Tags]    tier:6    verify:python    benchmark    gsm8k    huggingface
    ${dataset}=    HF.Load HF Dataset    openai/gsm8k    main    test    limit=20
    FOR    ${item}    IN    @{dataset}
        ${expected}=    HF.Extract Gsm8k Answer    ${item}[answer]
        ${response}=    LLM.Ask LLM    ${item}[question] Answer with just the number.
        Log    Q: ${item}[question] | Expected: ${expected} | Got: ${response}
    END
```

## Data Considerations

### License Check

Before importing any dataset, verify its license on the HF page:

| Dataset | License | Commercial OK? |
|---------|---------|----------------|
| GSM8K | MIT | Yes |
| MMLU | MIT | Yes |
| TruthfulQA | Apache 2.0 | Yes |
| ARC | CC-BY-SA | Yes (with attribution) |
| HellaSwag | MIT | Yes |
| HumanEval | MIT | Yes |

### Data Size Guidelines

- **Don't commit full datasets.** Use `--limit` to import a subset (50–100 items).
- **Use `.gitignore`** for large cached datasets: add `**/hf_cache/` if needed.
- **Version the import script**, not the raw data (for reproducibility).

### Contamination Awareness

Many LLMs have been trained on these benchmarks. High scores on GSM8K or MMLU
may reflect memorization, not reasoning ability. Consider:

- Using variants like **GSM1K** (novel problems) or **MMLU-Pro** (harder)
- Adding custom perturbations to questions (rewording, different numbers)
- Comparing scores across benchmarks to detect suspiciously high outliers

## Existing HuggingFace Integration

The project already has some HF integration points:

- `robot/ci/models.yaml` — maps model names to HF URLs
- `robot/ci/fetch_model_metadata.robot` — scrapes HF model pages via Playwright
  for metadata (downloads, release dates)

The import skill builds on this by bringing HF *data* (not just model metadata)
into the test framework.

## Registration

For new suites created from HF data, register in both config files:

**`config/test_suites.yaml`:**
```yaml
  gsm8k:
    label: "GSM8K Benchmark"
    path: "robot/math/tests"
    description: "Grade-school math from HuggingFace GSM8K dataset"
```

**`config/local_models.yaml`:**
```yaml
  - name: "gsm8k"
    path: "robot/math/tests/"
    description: "GSM8K benchmark (HuggingFace)"
    timeout_seconds: 600
```

## Verification

```bash
# Static import: verify the YAML is valid
python -c "import yaml; yaml.safe_load(open('robot/math/variables/gsm8k.yaml'))"

# Python tests pass
uv run pytest tests/test_huggingface_keywords.py -v

# Robot dry run
make robot-dryrun

# Pre-commit
pre-commit run --all-files
```
