*** Settings ***
Documentation     C interview questions - multithreading and concurrency
...
...               35 questions covering POSIX threads, mutexes, condition variables,
...               synchronization primitives, and common concurrency pitfalls.

Resource          ../c_interview.resource
Variables         ${CURDIR}/../variables/c_threading_questions.yaml

*** Test Cases ***
C Interview - Thread Vs Process (IQ:100)
    [Documentation]    Can the LLM explain the difference between a thread and a process?
    [Tags]    IQ:100    threads
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[0]

C Interview - Pthread Create (IQ:110)
    [Documentation]    Can the LLM explain how to create a thread with pthreads?
    [Tags]    IQ:110    threads    pthreads
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[1]

C Interview - Pthread Join (IQ:110)
    [Documentation]    Can the LLM explain how to wait for a thread to finish?
    [Tags]    IQ:110    threads    pthreads
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[2]

C Interview - Race Condition Definition (IQ:110)
    [Documentation]    Can the LLM define a race condition?
    [Tags]    IQ:110    concurrency
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[3]

C Interview - Mutex With Pthreads (IQ:110)
    [Documentation]    Can the LLM explain how to use a mutex with pthreads?
    [Tags]    IQ:110    synchronization    pthreads
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[4]

C Interview - Protecting Shared Counter (IQ:110)
    [Documentation]    Can the LLM show how to protect a shared counter with a mutex?
    [Tags]    IQ:110    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[5]

C Interview - Deadlock (IQ:120)
    [Documentation]    Can the LLM explain what a deadlock is?
    [Tags]    IQ:120    concurrency
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[6]

C Interview - Avoiding Deadlocks (IQ:120)
    [Documentation]    Can the LLM explain how to avoid deadlocks?
    [Tags]    IQ:120    concurrency
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[7]

C Interview - Condition Variable (IQ:120)
    [Documentation]    Can the LLM explain what a condition variable is?
    [Tags]    IQ:120    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[8]

C Interview - Condition Variable Wait Pattern (IQ:120)
    [Documentation]    Can the LLM describe the typical condition variable wait pattern?
    [Tags]    IQ:120    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[9]

C Interview - Signal Vs Broadcast (IQ:120)
    [Documentation]    Can the LLM distinguish pthread_cond_signal from pthread_cond_broadcast?
    [Tags]    IQ:120    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[10]

C Interview - Spurious Wakeups (IQ:120)
    [Documentation]    Can the LLM explain why a loop is needed around pthread_cond_wait?
    [Tags]    IQ:120    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[11]

C Interview - Spinlock Vs Mutex (IQ:120)
    [Documentation]    Can the LLM explain what a spinlock is and when to prefer it?
    [Tags]    IQ:120    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[12]

C Interview - Barrier (IQ:120)
    [Documentation]    Can the LLM explain what a barrier is in multithreaded code?
    [Tags]    IQ:120    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[13]

C Interview - Producer Consumer Queue (IQ:130)
    [Documentation]    Can the LLM describe a producer-consumer queue implementation?
    [Tags]    IQ:130    synchronization    patterns
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[14]

C Interview - Pthread Create Arguments (IQ:110)
    [Documentation]    Can the LLM list pthread_create arguments and return value?
    [Tags]    IQ:110    pthreads
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[15]

C Interview - Pthread Detach (IQ:110)
    [Documentation]    Can the LLM explain pthread_detach and its use case?
    [Tags]    IQ:110    pthreads
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[16]

C Interview - Zombie Thread (IQ:110)
    [Documentation]    Can the LLM explain what happens if you never join or detach a thread?
    [Tags]    IQ:110    threads
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[17]

C Interview - Start Routine Returns Void Star (IQ:110)
    [Documentation]    Can the LLM explain why pthread start routines return void *?
    [Tags]    IQ:110    pthreads
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[18]

C Interview - Thread Safe Code (IQ:110)
    [Documentation]    Can the LLM define thread-safe code?
    [Tags]    IQ:110    concurrency
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[19]

C Interview - POSIX Synchronization Primitives (IQ:110)
    [Documentation]    Can the LLM list common POSIX synchronization primitives?
    [Tags]    IQ:110    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[20]

C Interview - Read Write Lock (IQ:120)
    [Documentation]    Can the LLM explain a read-write lock and when to use it?
    [Tags]    IQ:120    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[21]

C Interview - Mutex Initialization (IQ:110)
    [Documentation]    Can the LLM explain how to initialize a pthread_mutex_t?
    [Tags]    IQ:110    pthreads    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[22]

C Interview - Consistent Mutex Usage (IQ:120)
    [Documentation]    Can the LLM explain why shared data needs the same mutex?
    [Tags]    IQ:120    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[23]

C Interview - False Sharing (IQ:130)
    [Documentation]    Can the LLM explain false sharing and its performance impact?
    [Tags]    IQ:130    performance
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[24]

C Interview - Memory Fence (IQ:130)
    [Documentation]    Can the LLM explain what a memory fence is?
    [Tags]    IQ:130    concurrency
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[25]

C Interview - Signal Handler Safety (IQ:130)
    [Documentation]    Can the LLM explain why printf is unsafe in signal handlers?
    [Tags]    IQ:130    signals    concurrency
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[26]

C Interview - Spinlock Implementation (IQ:130)
    [Documentation]    Can the LLM describe how to implement a simple spinlock?
    [Tags]    IQ:130    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[27]

C Interview - Priority Inversion (IQ:130)
    [Documentation]    Can the LLM explain priority inversion?
    [Tags]    IQ:130    concurrency
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[28]

C Interview - Condition Variables Avoid Busy Wait (IQ:120)
    [Documentation]    Can the LLM explain how condition variables avoid busy waiting?
    [Tags]    IQ:120    synchronization
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[29]

C Interview - Producer Pattern Bounded Queue (IQ:120)
    [Documentation]    Can the LLM describe the producer pattern for a bounded queue?
    [Tags]    IQ:120    patterns
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[30]

C Interview - Consumer Pattern Bounded Queue (IQ:120)
    [Documentation]    Can the LLM describe the consumer pattern for a bounded queue?
    [Tags]    IQ:120    patterns
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[31]

C Interview - Minimize Critical Section Work (IQ:120)
    [Documentation]    Can the LLM explain why work should be done outside critical sections?
    [Tags]    IQ:120    performance
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[32]

C Interview - Thread Safe Singleton (IQ:130)
    [Documentation]    Can the LLM describe a thread-safe singleton with pthread_once?
    [Tags]    IQ:130    patterns
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[33]

C Interview - Debugging Race Conditions (IQ:120)
    [Documentation]    Can the LLM explain how to debug race conditions and deadlocks?
    [Tags]    IQ:120    debugging
    Ask C Interview Question    ${C_THREADING_QUESTIONS}[34]

*** Keywords ***
Ask C Interview Question
    [Documentation]    Ask a C interview question and grade the LLM response
    [Arguments]    ${q}    ${max_retries}=3
    Ask And Validate    ${q}[question]    ${q}[expected]    max_retries=${max_retries}
