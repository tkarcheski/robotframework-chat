*** Settings ***
Documentation     C interview questions - code and concept oriented
...
...               25 questions covering memory management, strings, type system,
...               preprocessor, and common pitfalls in C programming.

Resource          c_interview.resource
Variables         ${CURDIR}/variables/c_concepts_questions.yaml
Test Tags         axis:model

*** Test Cases ***
C Interview - Malloc Vs Calloc Vs Realloc (IQ:110)
    [Documentation]    Can the LLM distinguish malloc, calloc, and realloc?
    [Tags]    IQ:110    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[0]

C Interview - Forgetting To Free Memory (IQ:100)
    [Documentation]    Can the LLM explain what happens when you forget to free memory?
    [Tags]    IQ:100    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[1]

C Interview - Gets Is Dangerous (IQ:110)
    [Documentation]    Can the LLM explain why gets is dangerous?
    [Tags]    IQ:110    security    strings    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[2]

C Interview - Pre Increment Vs Post Increment Via Pointer (IQ:120)
    [Documentation]    Can the LLM distinguish ++*p from (*p)++?
    [Tags]    IQ:120    pointers    operators    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[3]

C Interview - String Literal Vs Char Array (IQ:110)
    [Documentation]    Can the LLM distinguish char *s = "hello" from char s[] = "hello"?
    [Tags]    IQ:110    strings    pointers    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[4]

C Interview - Memory Leak Example (IQ:100)
    [Documentation]    Can the LLM explain what a memory leak is with an example?
    [Tags]    IQ:100    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[5]

C Interview - Sizeof Common Types (IQ:110)
    [Documentation]    Can the LLM explain sizeof(char), sizeof(int), sizeof(void *)?
    [Tags]    IQ:110    types    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[6]

C Interview - Pointer To Array Declaration (IQ:120)
    [Documentation]    Can the LLM explain int (*p)[10]?
    [Tags]    IQ:120    pointers    arrays    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[7]

C Interview - Sizeof Array Vs Sizeof Pointer (IQ:120)
    [Documentation]    Can the LLM predict sizeof output for array vs pointer?
    [Tags]    IQ:120    operators    arrays    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[8]

C Interview - Strcpy Is Dangerous (IQ:110)
    [Documentation]    Can the LLM explain why strcpy is dangerous?
    [Tags]    IQ:110    security    strings    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[9]

C Interview - Volatile Keyword (IQ:120)
    [Documentation]    Can the LLM explain what volatile means?
    [Tags]    IQ:120    qualifiers    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[10]

C Interview - Race Condition (IQ:110)
    [Documentation]    Can the LLM explain what a race condition is?
    [Tags]    IQ:110    concurrency    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[11]

C Interview - Mutex Purpose (IQ:110)
    [Documentation]    Can the LLM explain the purpose of a mutex?
    [Tags]    IQ:110    concurrency    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[12]

C Interview - Process Vs Thread (IQ:100)
    [Documentation]    Can the LLM distinguish a process from a thread?
    [Tags]    IQ:100    concurrency    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[13]

C Interview - Memset Usage (IQ:100)
    [Documentation]    Can the LLM explain what memset is used for?
    [Tags]    IQ:100    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[14]

C Interview - Strict Aliasing (IQ:130)
    [Documentation]    Can the LLM explain strict aliasing and its pitfalls?
    [Tags]    IQ:130    language-rules    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[15]

C Interview - Casting Malloc Result (IQ:120)
    [Documentation]    Can the LLM explain why casting malloc is discouraged in C?
    [Tags]    IQ:120    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[16]

C Interview - Returning Pointer To Local Array (IQ:110)
    [Documentation]    Can the LLM identify the bug in returning a pointer to a local array?
    [Tags]    IQ:110    pointers    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[17]

C Interview - Typedef For Function Pointers (IQ:120)
    [Documentation]    Can the LLM explain typedef for function pointers?
    [Tags]    IQ:120    pointers    types    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[18]

C Interview - Include Quotes Vs Angle Brackets (IQ:100)
    [Documentation]    Can the LLM explain the difference between #include "" and #include <>?
    [Tags]    IQ:100    preprocessor    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[19]

C Interview - Do Not Modify String Literals (IQ:110)
    [Documentation]    Can the LLM explain why modifying string literals is dangerous?
    [Tags]    IQ:110    strings    language-rules    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[20]

C Interview - Pragma Once Vs Include Guards (IQ:110)
    [Documentation]    Can the LLM compare #pragma once with include guards?
    [Tags]    IQ:110    preprocessor    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[21]

C Interview - Offsetof Macro (IQ:130)
    [Documentation]    Can the LLM explain the offsetof macro?
    [Tags]    IQ:130    structs    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[22]

C Interview - Complex Declaration (IQ:140)
    [Documentation]    Can the LLM decode int (*f(int))(double)?
    [Tags]    IQ:140    types    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[23]

C Interview - Reentrancy And Strtok (IQ:120)
    [Documentation]    Can the LLM explain reentrancy and why strtok is not reentrant?
    [Tags]    IQ:120    strings    concurrency    tier:2    verify:llm
    Ask C Interview Question    ${C_CONCEPTS_QUESTIONS}[24]

*** Keywords ***
Ask C Interview Question
    [Documentation]    Ask a C interview question and grade the LLM response
    [Arguments]    ${q}    ${max_retries}=3
    Ask And Validate    ${q}[question]    ${q}[expected]    max_retries=${max_retries}
