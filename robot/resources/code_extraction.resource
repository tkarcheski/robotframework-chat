*** Settings ***
Documentation     Shared keywords for extracting code blocks from LLM responses
Library           String
Library           Collections

*** Keywords ***
Extract Code Block
    [Documentation]    Extract first fenced markdown code block (optionally matching language). Falls back to any block, then full text.
    [Arguments]    ${text}    ${language}=python

    ${pattern}=    Set Variable    (?s)```(?:${language})?\s*(.*?)\s*```
    ${matches}=    Get Regexp Matches    ${text}    ${pattern}    1
    ${count}=      Get Length    ${matches}
    IF    ${count} > 0
        ${code}=    Set Variable    ${matches}[0]
        RETURN    ${code}
    END

    ${pattern}=    Set Variable    (?s)```\s*(.*?)\s*```
    ${matches}=    Get Regexp Matches    ${text}    ${pattern}    1
    ${count}=      Get Length    ${matches}
    IF    ${count} > 0
        ${code}=    Set Variable    ${matches}[0]
        RETURN    ${code}
    END

    RETURN    ${text}

Extract Shell Commands
    [Documentation]    Extract shell commands from LLM response
    [Arguments]    ${text}

    ${commands}=    Create List

    # Try to extract from markdown code block
    # Match content between ``` markers (with or without language)
    ${pattern}=    Set Variable    (?s)\`\`\`(?:bash|sh|shell)?\n(.*?)\n?\`\`\`
    ${matches}=    Get Regexp Matches    ${text}    ${pattern}    1

    ${has_matches}=    Get Length    ${matches}
    IF    ${has_matches} > 0
        # Extract lines from first match
        ${content}=    Set Variable    ${matches}[0]
        ${lines}=    Split String    ${content}    \n
        FOR    ${line}    IN    @{lines}
            ${stripped}=    Strip String    ${line}
            # Skip empty lines and comments
            IF    '${stripped}' != '' and not '${stripped}'.startswith('#')
                Append To List    ${commands}    ${stripped}
            END
        END
        RETURN    ${commands}
    END

    # If no code block, try to find lines that look like commands
    # Lines starting with common shell commands
    ${all_lines}=    Split String    ${text}    \n
    FOR    ${line}    IN    @{all_lines}
        ${stripped}=    Strip String    ${line}
        # Look for common shell command patterns
        ${is_command}=    Evaluate    bool(__import__('re').match(r'^(mkdir|cd|touch|echo|ls|cat|grep|awk|sed|wget|curl|pip|npm|python|node|docker)\\s', '${stripped}'))
        IF    ${is_command}
            Append To List    ${commands}    ${stripped}
        END
    END

    RETURN    ${commands}
