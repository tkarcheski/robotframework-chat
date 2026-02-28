# v2 Feature Tracker

Features under evaluation for the next major iteration of RFC.
Distinct from `ai/FEATURES.md` which tracks the current roadmap.

**Legend:** Done / In Progress / Not Started / Blocked / Under Evaluation

---

## HardSecBench — Hardware/Firmware Security Evaluation (Under Evaluation)

> **Source:** arXiv 2601.13864 (January 2026)
> **Status:** Assessment complete. Dataset not yet publicly available.

HardSecBench benchmarks LLM security awareness for hardware and firmware code
generation. It contains **924 tasks** (599 Verilog RTL + 325 C firmware) spanning
**76 CWEs** across 12 categories: buffer overflows, missing input validation,
unsafe casting, access control, crypto primitives, debug/test problems, and more.

Each task ships with a structured specification (functional + security requirements
separated), a golden implementation, and executable test harnesses that emit
deterministic PASS/FAIL verdicts.

### Alignment with RFC Architecture

| HardSecBench Need | RFC Already Has | Gap |
|---|---|---|
| Sandboxed code execution | `ContainerManager` + `docker_keywords.py` | None — direct reuse |
| LLM code generation | `OllamaClient.generate()` | None — direct reuse |
| Structured grading | `Grader` + `SafetyGrader` | Harness-based grading is Tier 0/4 hybrid |
| Security-focused evaluation | `robot/safety/` test suites | Different domain (LLM safety vs code security) |
| Results archival | `TestDatabase` + `DbListener` | Minor schema extension needed |
| Data-driven test patterns | `robot/docker/python/` templates | None — pattern transfers directly |
| CI integration | GitLab CI + `test_suites.yaml` | Config entries needed |

### What Would Need to Be Built

**New Python modules (`src/rfc/`):**

| Module | Purpose | Complexity |
|---|---|---|
| `hardsecbench_loader.py` | Parse task files (specs, harnesses, CWE metadata). Dataclasses: `HardSecTask`, `TaskSpec`, `TestHarness`, `CWEInfo`. Index by CWE/language/category. | Medium |
| `hardsecbench_keywords.py` | Robot keywords: `Compile Verilog`, `Run Verilog Simulation`, `Compile C Firmware`, `Run Firmware Tests`, `Parse Harness Result`, `Calculate Coverage`. Wraps `ContainerManager`. | Medium |
| `hardsecbench_report.py` | CWE-level aggregation, functional-vs-security pass rate comparison, coverage stats, JSON export. | Low |

**New Docker images (`docker/hardsecbench/`):**

| Image | Contents | Notes |
|---|---|---|
| `Dockerfile.verilog` | Icarus Verilog v12.0 + VVP runtime | Benchmark-specified toolchain |
| `Dockerfile.firmware` | gcc + gcov + standard C build tools | Coverage measurement via gcov |

Both images: minimal footprint, no network, read-only filesystem — matching
existing security patterns in `docker_config.py`.

**New Robot Framework suites (`robot/hardsecbench/`):**

```
robot/hardsecbench/
  __init__.robot              # Suite setup: verify Docker, pull toolchain images
  hardsecbench.resource       # Shared keywords and variables
  tests/
    verilog_eval.robot        # Verilog RTL evaluation (data-driven via [Template])
    firmware_eval.robot       # C firmware evaluation (data-driven via [Template])
```

**Database schema extension:**

Add optional fields to `TestResult` (or a dedicated `HardSecBenchResult` table):
- `cwe_id` — CWE identifier per task
- `language` — `verilog` or `c`
- `evaluation_mode` — `single` or `iterative`
- `iteration_count` — number of refinement rounds used
- `functional_pass` — boolean, all functional harnesses passed
- `security_pass` — boolean, all security harnesses passed
- `line_coverage` — percentage from gcov/static analysis

### Evaluation Modes

HardSecBench defines two settings that map to different Robot keyword patterns:

**Setting 1 — Single-attempt:** Send spec with functional requirements only
(security intent hidden) → LLM generates code → run both functional and security
harnesses → record results. Maps to existing single-shot test patterns.

**Setting 2 — Iterative refinement:** Up to 5 rounds of generate → compile →
run functional harnesses → feed errors back to LLM → repeat. Security harnesses
run only after functional correctness is achieved. This is the most novel piece
architecturally — requires a Python-side loop or new Robot keyword pattern.

### Grading Tier

Maps to **Tier 4** (Robot + LLM + Docker sandbox). The benchmark's own test
harnesses provide deterministic PASS/FAIL verdicts — no LLM-as-judge needed
for core evaluation. Coverage gate at 80% minimum line coverage.

### Key Risks & Blockers

1. **Dataset not public** — Paper says code/data "will be made available" but no
   release yet. Loader must be designed against the paper's documented format with
   stub data until the real dataset ships. **This is the primary blocker.**
2. **Verilog coverage** — Paper uses static analysis for Verilog coverage, not
   gcov. May need a simpler harness-only approach initially.
3. **Scale** — 924 tasks × N models × (up to 5 iterations) = significant compute.
   Needs parallelism across RFC's multi-node infrastructure (dev1/mini1/mini2).
4. **Iterative refinement loop** — More complex than existing single-shot patterns.
   Most novel engineering work in the integration.

### Effort Estimate

| Phase | Scope | Complexity |
|---|---|---|
| Phase 1: Foundation | Loader + Docker images + compilation keywords + unit tests | Medium |
| Phase 2: Robot suites | Test suites + single-attempt + iterative refinement | Medium-High |
| Phase 3: Reporting | DB extension + CWE reporting + config integration | Low-Medium |

**Bottom line:** RFC is well-positioned for this integration. Docker sandboxing,
database, and Robot Framework patterns transfer directly. No fundamental
architectural changes needed — additive integration into existing `robot/` +
`src/rfc/` structure. Primary blocker is dataset availability.

### New Files Summary

| File | Purpose |
|---|---|
| `src/rfc/hardsecbench_loader.py` | Dataset parsing, task models, CWE index |
| `src/rfc/hardsecbench_keywords.py` | Robot keywords: compile, run, parse Verilog/C |
| `src/rfc/hardsecbench_report.py` | CWE aggregation and reporting |
| `docker/hardsecbench/Dockerfile.verilog` | Icarus Verilog toolchain image |
| `docker/hardsecbench/Dockerfile.firmware` | gcc + gcov toolchain image |
| `robot/hardsecbench/__init__.robot` | Suite setup |
| `robot/hardsecbench/tests/verilog_eval.robot` | Verilog evaluation test suite |
| `robot/hardsecbench/tests/firmware_eval.robot` | C firmware evaluation test suite |
| `robot/hardsecbench/hardsecbench.resource` | Shared keywords/variables |
| `tests/test_hardsecbench_loader.py` | Unit tests for loader |
| `tests/test_hardsecbench_keywords.py` | Unit tests for keywords |
| `data/hardsecbench/sample/` | Sample/stub tasks for development |

### CWE Categories Covered (76 CWEs across 12 categories)

1. Security Flow Issues
2. Integration Issues
3. Privilege Separation and Access Control
4. General Circuit and Logic Design
5. Core and Compute Issues
6. Memory and Storage Issues
7. Peripherals and Interface/IO Problems
8. Security Primitives and Cryptography
9. Power, Clock, Thermal, and Reset Concerns
10. Debug and Test Problems
11. Cross-Cutting Problems
12. Physical Access Issues

### References

- [arXiv 2601.13864](https://arxiv.org/abs/2601.13864) — HardSecBench paper
- [arXiv HTML](https://arxiv.org/html/2601.13864) — Full HTML version with figures
