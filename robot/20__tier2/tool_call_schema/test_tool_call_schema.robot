*** Settings ***
Documentation     Tool/function-call schema accuracy tests.
...
...               Each test gives the model a task plus one or more tool
...               schemas, then validates the emitted call: required
...               fields present, no hallucinated fields, types correct,
...               enums respected, and (for ambiguous suites) the right
...               tool selected.

Resource          tool_call_schema.resource

Test Tags         tool-call-schema    tier:2    verify:llm    axis:model

Test Timeout      150 minutes

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

# --- Nested object schema (required nested fields) ------------------------

${CREATE_CONTACT_TOOLS}     SEPARATOR=
...    [{"name": "create_contact",
...    "description": "Create a contact with a postal address.",
...    "parameters": {"type": "object",
...    "properties": {"name": {"type": "string"},
...    "address": {"type": "object",
...    "properties": {"street": {"type": "string"},
...    "city": {"type": "string"},
...    "zip": {"type": "string"}},
...    "required": ["street", "city", "zip"]}},
...    "required": ["name", "address"]}}]

# --- Nested object schema (optional field with no default) ----------------

${CREATE_WIDGET_TOOLS}      SEPARATOR=
...    [{"name": "create_widget",
...    "description": "Create a widget with a display configuration.",
...    "parameters": {"type": "object",
...    "properties": {"label": {"type": "string"},
...    "config": {"type": "object",
...    "properties": {"size": {"type": "string",
...    "enum": ["small", "medium", "large"]},
...    "color": {"type": "string"}},
...    "required": ["size"]}},
...    "required": ["label", "config"]}}]

# --- Deeply nested array-of-objects schema -------------------------------

${CREATE_INVOICE_TOOLS}     SEPARATOR=
...    [{"name": "create_invoice",
...    "description": "Create an invoice with one or more line items.",
...    "parameters": {"type": "object",
...    "properties": {"customer": {"type": "string"},
...    "line_items": {"type": "array",
...    "items": {"type": "object",
...    "properties": {"description": {"type": "string"},
...    "quantity": {"type": "integer"},
...    "unit_price": {"type": "number"}},
...    "required": ["description", "quantity", "unit_price"]}}},
...    "required": ["customer", "line_items"]}}]

# --- Ambiguous tool names across connectors ------------------------------

${CREATE_ISSUE_TOOLS}       SEPARATOR=
...    [{"name": "github_create_issue",
...    "description": "Open an issue in a GitHub repository.",
...    "parameters": {"type": "object",
...    "properties": {"repo": {"type": "string"},
...    "title": {"type": "string"}},
...    "required": ["repo", "title"]}},
...    {"name": "gitlab_create_issue",
...    "description": "Open an issue in a GitLab project.",
...    "parameters": {"type": "object",
...    "properties": {"project": {"type": "string"},
...    "title": {"type": "string"}},
...    "required": ["project", "title"]}},
...    {"name": "jira_create_issue",
...    "description": "Create a Jira ticket in a project.",
...    "parameters": {"type": "object",
...    "properties": {"project_key": {"type": "string"},
...    "summary": {"type": "string"}},
...    "required": ["project_key", "summary"]}}]

# --- Tool names with very high semantic overlap --------------------------

${CANCEL_TOOLS}             SEPARATOR=
...    [{"name": "cancel_order",
...    "description": "Cancel a one-time product order that has not yet shipped.",
...    "parameters": {"type": "object",
...    "properties": {"order_id": {"type": "string"}},
...    "required": ["order_id"]}},
...    {"name": "cancel_subscription",
...    "description": "Cancel a recurring subscription so it stops renewing.",
...    "parameters": {"type": "object",
...    "properties": {"subscription_id": {"type": "string"}},
...    "required": ["subscription_id"]}},
...    {"name": "cancel_reservation",
...    "description": "Cancel a hotel or restaurant reservation booking.",
...    "parameters": {"type": "object",
...    "properties": {"reservation_id": {"type": "string"}},
...    "required": ["reservation_id"]}}]

# --- Required field unknowable from the prompt ---------------------------

${TRANSFER_FUNDS_TOOLS}     SEPARATOR=
...    [{"name": "transfer_funds",
...    "description": "Transfer money from one account to another.",
...    "parameters": {"type": "object",
...    "properties": {"from_account": {"type": "string"},
...    "to_account": {"type": "string"},
...    "amount": {"type": "number"}},
...    "required": ["from_account", "to_account", "amount"]}}]


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

Nested Object Requires All Nested Fields
    [Documentation]    A required nested object must carry all of its own required
    ...                fields; a flattened or partial address fails the exact match.
    [Tags]    nested_schema    required_fields
    ${result}=    Evaluate Tool Call
    ...    prompt=Create a contact named Marge whose address is 742 Evergreen Terrace, Springfield, ZIP 49007.
    ...    tools=${CREATE_CONTACT_TOOLS}
    ...    expected_tool=create_contact
    ...    expected_args={"name": "Marge", "address": {"street": "742 Evergreen Terrace", "city": "Springfield", "zip": "49007"}}
    Assert Tool Selected             ${result}    create_contact
    Assert Required Fields Present   ${result}
    Assert No Type Errors            ${result}
    Assert Argument Values Match     ${result}

Nested Object Omits Unmentioned Optional Field
    [Documentation]    An optional nested field the prompt never mentions must stay
    ...                absent; fabricating a default breaks the exact nested match.
    [Tags]    nested_schema    optional_defaults
    ${result}=    Evaluate Tool Call
    ...    prompt=Create a widget labeled "Save" with a large config size.
    ...    tools=${CREATE_WIDGET_TOOLS}
    ...    expected_tool=create_widget
    ...    expected_args={"label": "Save", "config": {"size": "large"}}
    Assert Tool Selected             ${result}    create_widget
    Assert No Type Errors            ${result}
    Assert Argument Values Match     ${result}

Deeply Nested Array Of Objects Preserved
    [Documentation]    Each line item in an array-of-objects must keep its own fields
    ...                and types; a dropped field or wrong type fails the exact match.
    [Tags]    array_schema    nested_schema
    ${result}=    Evaluate Tool Call
    ...    prompt=Create an invoice for customer Acme with two line items: 3 units of "Widget" at 9.99 each, and 1 unit of "Gadget" at 19.5 each.
    ...    tools=${CREATE_INVOICE_TOOLS}
    ...    expected_tool=create_invoice
    ...    expected_args={"customer": "Acme", "line_items": [{"description": "Widget", "quantity": 3, "unit_price": 9.99}, {"description": "Gadget", "quantity": 1, "unit_price": 19.5}]}
    Assert Tool Selected             ${result}    create_invoice
    Assert No Type Errors            ${result}
    Assert Argument Values Match     ${result}

Cross-Connector Names — Picks GitHub Issue Creator
    [Documentation]    Three create-issue tools across connectors; a GitHub-worded
    ...                task must pick github_create_issue, not the GitLab/Jira peers.
    [Tags]    cross_connector    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Open an issue titled "Broken build" in the GitHub repo acme/website.
    ...    tools=${CREATE_ISSUE_TOOLS}
    ...    expected_tool=github_create_issue
    Assert Tool Selected             ${result}    github_create_issue
    Assert Required Fields Present   ${result}

Cross-Connector Names — Picks Jira Issue Creator
    [Documentation]    Same three connectors, opposite target; a Jira-worded task
    ...                must pick jira_create_issue for symmetric correctness.
    [Tags]    cross_connector    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Create a Jira ticket in project OPS with the summary "Rotate the API keys".
    ...    tools=${CREATE_ISSUE_TOOLS}
    ...    expected_tool=jira_create_issue
    Assert Tool Selected             ${result}    jira_create_issue
    Assert Required Fields Present   ${result}

High Overlap Names — Picks Cancel Subscription For Renewal Wording
    [Documentation]    Three cancel_* tools with near-identical names; renewal wording
    ...                (not the tool name) must drive selection of cancel_subscription.
    [Tags]    high_overlap    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=Stop my monthly plan from renewing next cycle; the subscription id is SUB-77.
    ...    tools=${CANCEL_TOOLS}
    ...    expected_tool=cancel_subscription
    ...    expected_args={"subscription_id": "SUB-77"}
    Assert Tool Selected             ${result}    cancel_subscription
    Assert Argument Values Match     ${result}

High Overlap Names — Picks Cancel Reservation For Booking Wording
    [Documentation]    Same three cancel_* tools; a dinner-booking task must resolve to
    ...                cancel_reservation despite the high lexical overlap.
    [Tags]    high_overlap    tool_selection
    ${result}=    Evaluate Tool Call
    ...    prompt=I need to cancel the dinner booking I made for Friday; the reservation id is RSV-12.
    ...    tools=${CANCEL_TOOLS}
    ...    expected_tool=cancel_reservation
    ...    expected_args={"reservation_id": "RSV-12"}
    Assert Tool Selected             ${result}    cancel_reservation
    Assert Argument Values Match     ${result}

Refuses Or Omits When Required Field Is Unknowable
    [Documentation]    A required recipient account the prompt never supplies must not
    ...                be fabricated: the model must refuse or omit it, not invent one.
    [Tags]    refuse_call    required_fields
    ${result}=    Evaluate Tool Call
    ...    prompt=Transfer $500 to my landlord's account.
    ...    tools=${TRANSFER_FUNDS_TOOLS}
    Assert Refused Or Field Omitted    ${result}    to_account
