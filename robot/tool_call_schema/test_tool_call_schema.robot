*** Settings ***
Documentation     Tool/function-call schema accuracy tests.
...
...               Each test gives the model a task plus one or more tool
...               schemas, then validates the emitted call: required
...               fields present, no hallucinated fields, types correct,
...               enums respected, and (for ambiguous suites) the right
...               tool selected.

Resource          tool_call_schema.resource

Test Tags         tool-call-schema    tier:2    verify:llm

Test Timeout      3 minutes

*** Variables ***
# --- Single-tool schemas ---------------------------------------------------

${CREATE_USER_TOOLS}        SEPARATOR=
...    [{"name": "create_user",
...    "description": "Create a new user account.",
...    "parameters": {"type": "object",
...    "properties": {"username": {"type": "string"},
...    "email": {"type": "string"},
...    "role": {"type": "string", "enum": ["admin", "editor", "viewer"]},
...    "age": {"type": "integer"},
...    "is_active": {"type": "boolean"}},
...    "required": ["username", "email", "role"]}}]

${SET_LOG_LEVEL_TOOLS}      SEPARATOR=
...    [{"name": "set_log_level",
...    "description": "Change the logger's verbosity.",
...    "parameters": {"type": "object",
...    "properties": {"level": {"type": "string",
...    "enum": ["debug", "info", "warning", "error", "critical"]}},
...    "required": ["level"]}}]

${SCHEDULE_MEETING_TOOLS}   SEPARATOR=
...    [{"name": "schedule_meeting",
...    "description": "Book a meeting on the calendar.",
...    "parameters": {"type": "object",
...    "properties": {"title": {"type": "string"},
...    "duration_minutes": {"type": "integer"},
...    "attendees": {"type": "array"}},
...    "required": ["title", "duration_minutes"]}}]

# --- Ambiguous-by-name suite ----------------------------------------------

${USER_LOOKUP_TOOLS}        SEPARATOR=
...    [{"name": "get_user_by_id",
...    "description": "Look up a user by their numeric ID.",
...    "parameters": {"type": "object",
...    "properties": {"user_id": {"type": "integer"}},
...    "required": ["user_id"]}},
...    {"name": "get_user_by_email",
...    "description": "Look up a user by their email address.",
...    "parameters": {"type": "object",
...    "properties": {"email": {"type": "string"}},
...    "required": ["email"]}},
...    {"name": "get_user_by_username",
...    "description": "Look up a user by their unique username handle.",
...    "parameters": {"type": "object",
...    "properties": {"username": {"type": "string"}},
...    "required": ["username"]}}]

# --- Ambiguous-by-overlapping-params suite -------------------------------

${SEARCH_TOOLS}             SEPARATOR=
...    [{"name": "search_documents",
...    "description": "Full-text search over uploaded PDF and text documents.",
...    "parameters": {"type": "object",
...    "properties": {"query": {"type": "string"},
...    "limit": {"type": "integer"}},
...    "required": ["query"]}},
...    {"name": "search_code",
...    "description": "Search source code files in a repository.",
...    "parameters": {"type": "object",
...    "properties": {"query": {"type": "string"},
...    "language": {"type": "string"}},
...    "required": ["query"]}}]

# --- Ambiguous-by-intent suite -------------------------------------------

${SEND_MESSAGE_TOOLS}       SEPARATOR=
...    [{"name": "send_email",
...    "description": "Send an email message to one or more recipients.",
...    "parameters": {"type": "object",
...    "properties": {"to": {"type": "string"},
...    "subject": {"type": "string"},
...    "body": {"type": "string"}},
...    "required": ["to", "subject", "body"]}},
...    {"name": "send_slack",
...    "description": "Post a message to a Slack channel or DM.",
...    "parameters": {"type": "object",
...    "properties": {"channel": {"type": "string"},
...    "text": {"type": "string"}},
...    "required": ["channel", "text"]}},
...    {"name": "send_sms",
...    "description": "Send an SMS text message to a phone number.",
...    "parameters": {"type": "object",
...    "properties": {"phone": {"type": "string"},
...    "text": {"type": "string"}},
...    "required": ["phone", "text"]}}]


*** Test Cases ***
Required Fields Present For Simple Call
    [Documentation]    Model must include all required fields for a simple tool.
    [Tags]    schema_basic    required_fields
    ${result}=    Evaluate Tool Call
    ...    prompt=Create an admin user named alice with email alice@example.com.
    ...    tools=${CREATE_USER_TOOLS}
    ...    expected_tool=create_user
    Assert Tool Selected           ${result}    create_user
    Assert Required Fields Present    ${result}

No Extra Fields Hallucinated
    [Documentation]    Model must not invent fields outside the schema.
    [Tags]    schema_basic    extra_fields
    ${result}=    Evaluate Tool Call
    ...    prompt=Create an editor user named bob with email bob@example.com.
    ...    tools=${CREATE_USER_TOOLS}
    ...    expected_tool=create_user
    Assert Tool Selected    ${result}    create_user
    Assert No Extra Fields    ${result}

Enum Field Uses Allowed Value
    [Documentation]    Enum fields must be restricted to declared values.
    [Tags]    enum_validation
    ${result}=    Evaluate Tool Call
    ...    prompt=Set the log level to warning.
    ...    tools=${SET_LOG_LEVEL_TOOLS}
    ...    expected_tool=set_log_level
    ...    expected_args={"level": "warning"}
    Assert Tool Selected    ${result}    set_log_level
    Assert Enum Values Valid    ${result}
    Assert Argument Values Match    ${result}

Enum Selection From Multiple Options
    [Documentation]    Verify each enum option is reachable, not just one.
    [Tags]    enum_validation
    ${result}=    Evaluate Tool Call
    ...    prompt=Switch the application logger to debug verbosity for troubleshooting.
    ...    tools=${SET_LOG_LEVEL_TOOLS}
    ...    expected_tool=set_log_level
    ...    expected_args={"level": "debug"}
    Assert Tool Selected    ${result}    set_log_level
    Assert Enum Values Valid    ${result}
    Assert Argument Values Match    ${result}

Numeric Field Has Correct Type
    [Documentation]    Integer fields must receive an integer, not a string.
    [Tags]    type_correctness
    ${result}=    Evaluate Tool Call
    ...    prompt=Schedule a 30 minute meeting titled "weekly sync".
    ...    tools=${SCHEDULE_MEETING_TOOLS}
    ...    expected_tool=schedule_meeting
    ...    expected_args={"duration_minutes": 30}
    Assert Tool Selected    ${result}    schedule_meeting
    Assert No Type Errors    ${result}
    Assert Argument Values Match    ${result}

Full Schema Validation On Simple Call
    [Documentation]    All categories clean: tool, required, types, enums, no extras.
    [Tags]    schema_full
    ${result}=    Evaluate Tool Call
    ...    prompt=Create a viewer user named carol (email carol@example.com).
    ...    tools=${CREATE_USER_TOOLS}
    ...    expected_tool=create_user
    Assert Tool Selected    ${result}    create_user
    Assert Schema Valid     ${result}

Ambiguous Names — Picks ID Variant For Numeric Lookup
    [Documentation]    With three lookup variants, the model must pick the ID one.
    [Tags]    ambiguous_names    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Look up the user whose ID is 42.
    ...    tools=${USER_LOOKUP_TOOLS}
    ...    expected_tool=get_user_by_id
    ...    expected_args={"user_id": 42}
    Assert Tool Selected    ${result}    get_user_by_id
    Assert Argument Values Match    ${result}

Ambiguous Names — Picks Email Variant For Email Lookup
    [Documentation]    With three lookup variants, the model must pick the email one.
    [Tags]    ambiguous_names    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Find the user account associated with dana@example.com.
    ...    tools=${USER_LOOKUP_TOOLS}
    ...    expected_tool=get_user_by_email
    ...    expected_args={"email": "dana@example.com"}
    Assert Tool Selected    ${result}    get_user_by_email
    Assert Argument Values Match    ${result}

Ambiguous Params — Picks Document Search Over Code Search
    [Documentation]    Both tools take a "query" string; description must drive selection.
    [Tags]    ambiguous_params    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Search our uploaded PDF reports for the phrase "quarterly revenue".
    ...    tools=${SEARCH_TOOLS}
    ...    expected_tool=search_documents
    Assert Tool Selected    ${result}    search_documents

Ambiguous Params — Picks Code Search Over Document Search
    [Documentation]    Same overlap, opposite intent — verify symmetric correctness.
    [Tags]    ambiguous_params    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Find every Python file in the repository that calls "requests.post".
    ...    tools=${SEARCH_TOOLS}
    ...    expected_tool=search_code
    Assert Tool Selected    ${result}    search_code

Ambiguous Intent — Picks Email For Email-Worded Task
    [Documentation]    Three send_* tools; "email" wording should pick send_email.
    [Tags]    ambiguous_intent    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Email eve@example.com with the subject "Welcome" and body "Glad you joined!".
    ...    tools=${SEND_MESSAGE_TOOLS}
    ...    expected_tool=send_email
    Assert Tool Selected             ${result}    send_email
    Assert Required Fields Present   ${result}

Ambiguous Intent — Picks Slack For Channel-Worded Task
    [Documentation]    Three send_* tools; "channel" wording should pick send_slack.
    [Tags]    ambiguous_intent    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Post "deploy started" in the #releases Slack channel.
    ...    tools=${SEND_MESSAGE_TOOLS}
    ...    expected_tool=send_slack
    Assert Tool Selected             ${result}    send_slack
    Assert Required Fields Present   ${result}

Ambiguous Intent — Picks SMS For Phone-Worded Task
    [Documentation]    Three send_* tools; phone-number wording should pick send_sms.
    [Tags]    ambiguous_intent    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Text +15551234567 with the message "Your code is 4242".
    ...    tools=${SEND_MESSAGE_TOOLS}
    ...    expected_tool=send_sms
    Assert Tool Selected             ${result}    send_sms
    Assert Required Fields Present   ${result}
