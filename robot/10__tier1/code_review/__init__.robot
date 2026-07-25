*** Settings ***
Documentation     Code review test suite.
...
...               Tests whether an LLM can identify bugs and security
...               vulnerabilities in code snippets using a multiple-choice
...               format.  The answer letter is extracted deterministically
...               from the first line of the response — Tier 1 / verify:python.

Test Tags         gold
