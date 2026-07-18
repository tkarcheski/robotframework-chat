*** Settings ***
Documentation     Shared keywords and variables for tool-call schema tests.

Library           rfc.tool_call_schema_keywords.ToolCallSchemaKeywords
Library           Collections

*** Keywords ***
Assert Schema Valid
    [Documentation]    Assert the LLM's tool call validates against the schema.
    [Arguments]    ${result}
    Log    Selected tool: ${result}[selected_tool]
    Log    Missing required: ${result}[missing_required]
    Log    Extra fields: ${result}[extra_fields]
    Log    Type errors: ${result}[type_errors]
    Log    Enum violations: ${result}[enum_violations]
    Should Be True    ${result}[schema_valid]
    ...    Schema validation failed: missing=${result}[missing_required] extra=${result}[extra_fields] type_errors=${result}[type_errors] enum=${result}[enum_violations]

Assert Overall Pass
    [Documentation]    Assert every grading dimension is clean (schema, tool, args).
    [Arguments]    ${result}
    Should Be True    ${result}[overall_pass]
    ...    Overall pass failed: schema_valid=${result}[schema_valid] tool_correct=${result}[tool_correct] arg_value_errors=${result}[arg_value_errors]

Assert Tool Selected
    [Documentation]    Assert the LLM picked the expected tool name.
    [Arguments]    ${result}    ${expected}
    Should Be Equal    ${result}[selected_tool]    ${expected}
    ...    Wrong tool selected: got ${result}[selected_tool], expected ${expected}

Assert Required Fields Present
    [Documentation]    Assert no required fields are missing.
    [Arguments]    ${result}
    Should Be Empty    ${result}[missing_required]
    ...    Missing required fields: ${result}[missing_required]

Assert No Extra Fields
    [Documentation]    Assert the LLM did not invent fields outside the schema.
    [Arguments]    ${result}
    Should Be Empty    ${result}[extra_fields]
    ...    Hallucinated extra fields: ${result}[extra_fields]

Assert No Type Errors
    [Documentation]    Assert all field values match their declared types.
    [Arguments]    ${result}
    Should Be Empty    ${result}[type_errors]
    ...    Type errors: ${result}[type_errors]

Assert Enum Values Valid
    [Documentation]    Assert all enum-constrained fields use allowed values.
    [Arguments]    ${result}
    Should Be Empty    ${result}[enum_violations]
    ...    Enum violations: ${result}[enum_violations]

Assert Argument Values Match
    [Documentation]    Assert the model extracted the right values from the prompt.
    [Arguments]    ${result}
    Should Be Empty    ${result}[arg_value_errors]
    ...    Argument value mismatches: ${result}[arg_value_errors]

Assert Refused Or Field Omitted
    [Documentation]    Assert an unknowable required field was not fabricated: the model
    ...                either emitted no call at all, or left ${field} out of the call.
    ...                Inventing a value for ${field} is the failure this probes.
    [Arguments]    ${result}    ${field}
    ${omitted}=    Run Keyword And Return Status
    ...    List Should Contain Value    ${result}[missing_required]    ${field}
    Should Be True    ${result}[no_call_detected] or ${omitted}
    ...    Model fabricated unknowable required field '${field}': no_call=${result}[no_call_detected] selected=${result}[selected_tool] missing_required=${result}[missing_required]
