*** Settings ***
Documentation     Sycophancy Detection Test Suite
...
...               Measures whether an LLM maintains correct answers under
...               adversarial social pressure.  A sycophantic model abandons
...               its correct answer when a user confidently asserts a wrong
...               one; a trustworthy model politely but firmly holds its ground.
...
...               Suite categories:
...                 - test_factual_sycophancy.robot  — geography, history, science
...                 - test_mathematical_sycophancy.robot — arithmetic and logic
...                 - test_cumulative_pressure.robot — multi-turn escalating pushback
