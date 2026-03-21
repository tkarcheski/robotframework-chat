*** Settings ***
Documentation     Token output benchmark: measures completion ratio and throughput
...               across 8 token levels (512–65536) with 3 prompt categories.
...
...               Each test sets max_tokens to a power-of-2 budget and sends a
...               self-scaling prompt. The existing DbListener infrastructure
...               captures eval_count, eval_rate, and total_duration automatically.
...               The benchmark keyword additionally emits completion_ratio and
...               estimated_response_tokens as RFC_DATA.
...
...               Prompt categories:
...               - **Technical Reference**: Python standard library documentation
...               - **Implementation Code**: Task management system in Python
...               - **Architecture Analysis**: Distributed systems deep-dive
Resource          ../benchmark.resource
Suite Setup       Verify LLM Available

*** Variables ***
${REFERENCE_PROMPT}    Write a comprehensive reference guide for Python's standard library. Cover modules, classes, methods, parameters, return types, exceptions, and practical examples. Start with os and sys, then continue through collections, itertools, functools, pathlib, json, re, typing, dataclasses, logging, unittest, argparse, subprocess, threading, asyncio, and as many more as space allows. For each module, provide real-world usage patterns.

${CODE_PROMPT}    Write a complete, production-ready Python implementation of a task management system. Include: data models with type hints, a repository layer with CRUD operations, a service layer with business logic, input validation, error handling, logging, and comprehensive docstrings. Use dataclasses, enums, and abstract base classes. Build incrementally — start with the core models and keep adding layers until done.

${ANALYSIS_PROMPT}    Write a detailed technical analysis comparing approaches to building distributed systems. Cover: monoliths vs microservices, synchronous vs asynchronous communication, SQL vs NoSQL data stores, event sourcing vs CRUD, container orchestration strategies, observability patterns, failure modes, and capacity planning. For each topic, explain the trade-offs with concrete examples from real-world systems. Include decision frameworks for choosing between approaches.

*** Test Cases ***
# ---------- 512 tokens ----------

Technical Reference 512 Tokens
    [Tags]    tier:0    verify:robot    tokens:512    prompt:reference
    Run Token Benchmark    512    ${REFERENCE_PROMPT}

Implementation Code 512 Tokens
    [Tags]    tier:0    verify:robot    tokens:512    prompt:code
    Run Token Benchmark    512    ${CODE_PROMPT}

Architecture Analysis 512 Tokens
    [Tags]    tier:0    verify:robot    tokens:512    prompt:analysis
    Run Token Benchmark    512    ${ANALYSIS_PROMPT}

# ---------- 1024 tokens ----------

Technical Reference 1024 Tokens
    [Tags]    tier:0    verify:robot    tokens:1024    prompt:reference
    Run Token Benchmark    1024    ${REFERENCE_PROMPT}

Implementation Code 1024 Tokens
    [Tags]    tier:0    verify:robot    tokens:1024    prompt:code
    Run Token Benchmark    1024    ${CODE_PROMPT}

Architecture Analysis 1024 Tokens
    [Tags]    tier:0    verify:robot    tokens:1024    prompt:analysis
    Run Token Benchmark    1024    ${ANALYSIS_PROMPT}

# ---------- 2048 tokens ----------

Technical Reference 2048 Tokens
    [Tags]    tier:0    verify:robot    tokens:2048    prompt:reference
    Run Token Benchmark    2048    ${REFERENCE_PROMPT}

Implementation Code 2048 Tokens
    [Tags]    tier:0    verify:robot    tokens:2048    prompt:code
    Run Token Benchmark    2048    ${CODE_PROMPT}

Architecture Analysis 2048 Tokens
    [Tags]    tier:0    verify:robot    tokens:2048    prompt:analysis
    Run Token Benchmark    2048    ${ANALYSIS_PROMPT}

# ---------- 4096 tokens ----------

Technical Reference 4096 Tokens
    [Tags]    tier:0    verify:robot    tokens:4096    prompt:reference
    Run Token Benchmark    4096    ${REFERENCE_PROMPT}

Implementation Code 4096 Tokens
    [Tags]    tier:0    verify:robot    tokens:4096    prompt:code
    Run Token Benchmark    4096    ${CODE_PROMPT}

Architecture Analysis 4096 Tokens
    [Tags]    tier:0    verify:robot    tokens:4096    prompt:analysis
    Run Token Benchmark    4096    ${ANALYSIS_PROMPT}

# ---------- 8192 tokens ----------

Technical Reference 8192 Tokens
    [Tags]    tier:0    verify:robot    tokens:8192    prompt:reference
    Run Token Benchmark    8192    ${REFERENCE_PROMPT}

Implementation Code 8192 Tokens
    [Tags]    tier:0    verify:robot    tokens:8192    prompt:code
    Run Token Benchmark    8192    ${CODE_PROMPT}

Architecture Analysis 8192 Tokens
    [Tags]    tier:0    verify:robot    tokens:8192    prompt:analysis
    Run Token Benchmark    8192    ${ANALYSIS_PROMPT}

# ---------- 16384 tokens ----------

Technical Reference 16384 Tokens
    [Tags]    tier:0    verify:robot    tokens:16384    prompt:reference
    Run Token Benchmark    16384    ${REFERENCE_PROMPT}

Implementation Code 16384 Tokens
    [Tags]    tier:0    verify:robot    tokens:16384    prompt:code
    Run Token Benchmark    16384    ${CODE_PROMPT}

Architecture Analysis 16384 Tokens
    [Tags]    tier:0    verify:robot    tokens:16384    prompt:analysis
    Run Token Benchmark    16384    ${ANALYSIS_PROMPT}

# ---------- 32768 tokens ----------

Technical Reference 32768 Tokens
    [Tags]    tier:0    verify:robot    tokens:32768    prompt:reference
    Run Token Benchmark    32768    ${REFERENCE_PROMPT}

Implementation Code 32768 Tokens
    [Tags]    tier:0    verify:robot    tokens:32768    prompt:code
    Run Token Benchmark    32768    ${CODE_PROMPT}

Architecture Analysis 32768 Tokens
    [Tags]    tier:0    verify:robot    tokens:32768    prompt:analysis
    Run Token Benchmark    32768    ${ANALYSIS_PROMPT}

# ---------- 65536 tokens ----------

Technical Reference 65536 Tokens
    [Tags]    tier:0    verify:robot    tokens:65536    prompt:reference
    Run Token Benchmark    65536    ${REFERENCE_PROMPT}

Implementation Code 65536 Tokens
    [Tags]    tier:0    verify:robot    tokens:65536    prompt:code
    Run Token Benchmark    65536    ${CODE_PROMPT}

Architecture Analysis 65536 Tokens
    [Tags]    tier:0    verify:robot    tokens:65536    prompt:analysis
    Run Token Benchmark    65536    ${ANALYSIS_PROMPT}
