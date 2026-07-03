*** Settings ***
Documentation     C core language interview questions - pointers, memory, and fundamentals
...
...               25 questions covering pointers, memory allocation, arrays, strings,
...               structs, function pointers, and core C behavior.

Resource          c_interview.resource
Variables         ${CURDIR}/variables/c_interview_questions.yaml

*** Test Cases ***
C Interview - What Is A Pointer (IQ:100)
    [Documentation]    Can the LLM explain what a pointer is and why it is useful?
    [Tags]    IQ:100    pointers    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[0]

C Interview - Pointer Vs Array Declaration (IQ:100)
    [Documentation]    Can the LLM distinguish between int *p and int a[10]?
    [Tags]    IQ:100    pointers    arrays    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[1]

C Interview - Void Pointer (IQ:110)
    [Documentation]    Can the LLM explain void * and its use cases?
    [Tags]    IQ:110    pointers    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[2]

C Interview - Pointer Arithmetic (IQ:110)
    [Documentation]    Can the LLM explain how pointer arithmetic works?
    [Tags]    IQ:110    pointers    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[3]

C Interview - Dangling Pointer (IQ:110)
    [Documentation]    Can the LLM explain what a dangling pointer is?
    [Tags]    IQ:110    pointers    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[4]

C Interview - Wild Pointer (IQ:100)
    [Documentation]    Can the LLM explain what a wild (uninitialized) pointer is?
    [Tags]    IQ:100    pointers    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[5]

C Interview - Const Char Pointer Vs Char Const Pointer (IQ:120)
    [Documentation]    Can the LLM distinguish const char *p from char * const p?
    [Tags]    IQ:120    pointers    const    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[6]

C Interview - Dynamic Memory Allocation (IQ:110)
    [Documentation]    Can the LLM show how to allocate and free an array of ints?
    [Tags]    IQ:110    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[7]

C Interview - Double Free (IQ:110)
    [Documentation]    Can the LLM explain what happens when you free a pointer twice?
    [Tags]    IQ:110    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[8]

C Interview - Stack Vs Heap (IQ:100)
    [Documentation]    Can the LLM explain the difference between stack and heap memory?
    [Tags]    IQ:100    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[9]

C Interview - Sizeof Operator (IQ:100)
    [Documentation]    Can the LLM explain the sizeof operator and when it is evaluated?
    [Tags]    IQ:100    operators    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[10]

C Interview - Function Pointer (IQ:120)
    [Documentation]    Can the LLM explain what a function pointer is?
    [Tags]    IQ:120    pointers    functions    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[11]

C Interview - Passing Function Pointer (IQ:120)
    [Documentation]    Can the LLM show how to pass a function pointer to another function?
    [Tags]    IQ:120    pointers    functions    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[12]

C Interview - Pre Vs Post Increment (IQ:100)
    [Documentation]    Can the LLM explain the difference between ++i and i++?
    [Tags]    IQ:100    operators    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[13]

C Interview - Undefined Behavior (IQ:110)
    [Documentation]    Can the LLM explain undefined behavior with an example?
    [Tags]    IQ:110    language-rules    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[14]

C Interview - Memcpy Vs Memmove (IQ:110)
    [Documentation]    Can the LLM distinguish memcpy from memmove?
    [Tags]    IQ:110    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[15]

C Interview - Static Local Variable (IQ:110)
    [Documentation]    Can the LLM explain static on a local variable?
    [Tags]    IQ:110    storage-class    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[16]

C Interview - Static At File Scope (IQ:110)
    [Documentation]    Can the LLM explain static at file scope?
    [Tags]    IQ:110    storage-class    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[17]

C Interview - String Representation (IQ:100)
    [Documentation]    Can the LLM explain how strings are represented in C?
    [Tags]    IQ:100    strings    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[18]

C Interview - Strlen Vs Sizeof (IQ:110)
    [Documentation]    Can the LLM distinguish strlen from sizeof on a string?
    [Tags]    IQ:110    strings    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[19]

C Interview - Segmentation Fault (IQ:100)
    [Documentation]    Can the LLM explain what a segfault is and what causes it?
    [Tags]    IQ:100    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[20]

C Interview - Preventing Buffer Overflows (IQ:110)
    [Documentation]    Can the LLM explain how to prevent buffer overflows?
    [Tags]    IQ:110    security    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[21]

C Interview - Struct Vs Array (IQ:100)
    [Documentation]    Can the LLM explain how a struct differs from an array?
    [Tags]    IQ:100    structs    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[22]

C Interview - Struct Allocation And Arrow Operator (IQ:110)
    [Documentation]    Can the LLM show how to allocate a struct and access members via pointer?
    [Tags]    IQ:110    structs    memory    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[23]

C Interview - Macros Vs Inline Functions (IQ:120)
    [Documentation]    Can the LLM explain the difference between #define macros and inline functions?
    [Tags]    IQ:120    preprocessor    tier:2    verify:llm
    Ask C Interview Question    ${C_CORE_QUESTIONS}[24]

*** Keywords ***
Ask C Interview Question
    [Documentation]    Ask a C interview question and grade the LLM response
    [Arguments]    ${q}    ${max_retries}=3
    Ask And Validate    ${q}[question]    ${q}[expected]    max_retries=${max_retries}
