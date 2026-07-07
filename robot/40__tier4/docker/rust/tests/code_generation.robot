*** Settings ***
Documentation     Rust programming challenges - LLM generates Rust code compiled and executed in Docker
Resource          ../../../../resources/environments.resource
Resource          ../../../../resources/code_extraction.resource
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM
Library           Collections
Library           String
Variables         ${CURDIR}/../variables/rust_challenges.yaml

*** Test Cases ***
LLM Generates Rust Hello World (IQ:100)
    [Documentation]    Can the LLM write a Rust program that prints 'Hello World'?
    [Tags]    IQ:100    basic    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[0]

LLM Generates Rust Factorial Function (IQ:120)
    [Documentation]    Can the LLM write a Rust program with an iterative factorial function?
    [Tags]    IQ:120    algorithm    function-generation    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[1]

LLM Generates Rust Ownership Example (IQ:130)
    [Documentation]    Can the LLM write a Rust program demonstrating ownership and borrowing?
    [Tags]    IQ:130    ownership    borrowing    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[2]

LLM Generates Rust Pattern Matching (IQ:120)
    [Documentation]    Can the LLM write a Rust program using match expressions?
    [Tags]    IQ:120    pattern-matching    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[3]

LLM Generates Rust FizzBuzz (IQ:110)
    [Documentation]    Can the LLM write FizzBuzz in Rust?
    [Tags]    IQ:110    algorithm    fizzbuzz    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[4]

# === Rust Interview Questions (Q1-Q20) ===

LLM Generates Rust Ownership Move And Drop (IQ:120)
    [Documentation]    Q1: Can the LLM demonstrate ownership move semantics and automatic drop?
    [Tags]    IQ:120    ownership    move    drop    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[5]

LLM Generates Rust Borrowing Rules (IQ:130)
    [Documentation]    Q2: Can the LLM demonstrate mutable vs immutable borrowing rules?
    [Tags]    IQ:130    borrowing    references    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[6]

LLM Generates Rust Lifetime Annotations (IQ:140)
    [Documentation]    Q3: Can the LLM write a function with lifetime annotations?
    [Tags]    IQ:140    lifetimes    advanced    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[7]

LLM Generates Rust String Vs Str Slice (IQ:120)
    [Documentation]    Q4: Can the LLM demonstrate the difference between String and &str?
    [Tags]    IQ:120    string    str    types    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[8]

LLM Generates Rust Option Null Safety (IQ:120)
    [Documentation]    Q5: Can the LLM use Option<T> for null-safe programming?
    [Tags]    IQ:120    option    null-safety    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[9]

LLM Generates Rust Result Error Handling (IQ:130)
    [Documentation]    Q6: Can the LLM use Result<T,E> for recoverable error handling?
    [Tags]    IQ:130    result    error-handling    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[10]

LLM Generates Rust Question Mark Operator (IQ:130)
    [Documentation]    Q7: Can the LLM use the ? operator for error propagation?
    [Tags]    IQ:130    question-mark    error-propagation    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[11]

LLM Generates Rust Exhaustive Match On Enum (IQ:110)
    [Documentation]    Q8: Can the LLM write exhaustive match expressions on enums?
    [Tags]    IQ:110    enum    match    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[12]

LLM Generates Rust Box Heap Allocation (IQ:140)
    [Documentation]    Q9: Can the LLM use Box<T> for recursive types and heap allocation?
    [Tags]    IQ:140    box    heap    recursive    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[13]

LLM Generates Rust Trait Implementation (IQ:120)
    [Documentation]    Q10: Can the LLM define and implement traits for polymorphism?
    [Tags]    IQ:120    traits    polymorphism    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[14]

LLM Generates Rust Impl Trait Vs Generics (IQ:130)
    [Documentation]    Q11: Can the LLM use both impl Trait and generic type parameters?
    [Tags]    IQ:130    impl-trait    generics    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[15]

LLM Generates Rust Clone Vs Copy (IQ:120)
    [Documentation]    Q12: Can the LLM demonstrate the difference between Clone and Copy?
    [Tags]    IQ:120    clone    copy    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[16]

LLM Generates Rust Unsafe Demo (IQ:140)
    [Documentation]    Q13: Can the LLM correctly use unsafe Rust with raw pointers?
    [Tags]    IQ:140    unsafe    raw-pointers    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[17]

LLM Generates Rust Arc Mutex Concurrency (IQ:140)
    [Documentation]    Q14: Can the LLM use Arc<Mutex<T>> for thread-safe shared state?
    [Tags]    IQ:140    concurrency    arc    mutex    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[18]

LLM Generates Rust Send And Sync (IQ:130)
    [Documentation]    Q15: Can the LLM demonstrate Send by moving data into a thread?
    [Tags]    IQ:130    send    sync    threads    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[19]

LLM Generates Rust Rc Reference Counting (IQ:130)
    [Documentation]    Q16: Can the LLM use Rc<T> and track reference counts?
    [Tags]    IQ:130    rc    reference-counting    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[20]

LLM Generates Rust RefCell Interior Mutability (IQ:140)
    [Documentation]    Q17: Can the LLM use RefCell<T> for interior mutability?
    [Tags]    IQ:140    refcell    interior-mutability    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[21]

LLM Generates Rust Concurrent Tasks (IQ:120)
    [Documentation]    Q18: Can the LLM use threads for concurrent computation?
    [Tags]    IQ:120    threads    concurrency    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[22]

LLM Generates Rust Module System (IQ:120)
    [Documentation]    Q19: Can the LLM demonstrate Rust's module system in a single file?
    [Tags]    IQ:120    modules    organization    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[23]

LLM Generates Rust Memory Safety Guarantees (IQ:120)
    [Documentation]    Q20: Can the LLM demonstrate memory safety without a garbage collector?
    [Tags]    IQ:120    memory-safety    vec    option    tier:4    verify:robot
    Run Compiled Challenge    ${RUST_CODE_CHALLENGES}[24]

*** Keywords ***
Run Compiled Challenge
    [Documentation]    Run a YAML-defined compiled code challenge.
    ...    When expected_outputs (list) is present, verifies each entry appears
    ...    as an ordered subsequence of stdout lines. Duplicates consume separate
    ...    lines. Falls back to expected_output (single string) containment check.
    [Arguments]    ${challenge}

    ${response}=    LLM.Ask LLM    ${challenge}[prompt]
    ${code}=    Extract Code Block    ${response}    ${challenge}[language]

    ${result}=    Compile And Run In Container
    ...    RUST_CONTAINER    ${code}
    ...    ${challenge}[source_file]    ${challenge}[compile_command]
    ...    ${challenge}[run_command]    timeout=${challenge}[timeout]

    Should Be Equal As Integers    ${result}[exit_code]    ${challenge}[expected_exit_code]

    # Multi-line verification: ordered subsequence of stdout lines
    ${has_outputs}=    Evaluate    "expected_outputs" in $challenge
    IF    ${has_outputs}
        Verify Ordered Output    ${result}[stdout]    ${challenge}[expected_outputs]
    ELSE
        Should Contain    ${result}[stdout]    ${challenge}[expected_output]
    END

Verify Ordered Output
    [Documentation]    Verify that expected strings appear as an ordered subsequence
    ...    of stdout lines. Each expected entry is matched against successive stdout
    ...    lines (starting from where the previous match was found), so order is
    ...    enforced and duplicate entries consume separate lines.
    [Arguments]    ${stdout}    ${expected_list}
    ${stdout_lines}=    Split String    ${stdout}    \n
    ${search_start}=    Set Variable    ${0}
    FOR    ${expected}    IN    @{expected_list}
        ${found}=    Set Variable    ${FALSE}
        ${stdout_len}=    Get Length    ${stdout_lines}
        FOR    ${i}    IN RANGE    ${search_start}    ${stdout_len}
            ${line}=    Set Variable    ${stdout_lines}[${i}]
            ${stripped}=    Strip String    ${line}
            ${contains}=    Evaluate    $expected in $stripped
            IF    ${contains}
                ${search_start}=    Evaluate    ${i} + 1
                ${found}=    Set Variable    ${TRUE}
                BREAK
            END
        END
        IF    not ${found}
            ${remaining}=    Evaluate    '\\n'.join($stdout_lines[$search_start:])
            Fail    Expected '${expected}' not found in order in stdout. Remaining stdout after previous match:\n${remaining}
        END
    END
