# Implementation Plan: OpenClaw-style Agent Workflow Testing

**Branch:** `claude/agentic-workflow-testing-IXENd`  
**Scope:** Multi-turn agent interaction tracking, tool-call validation, state management, database persistence  
**Start Date:** 2026-04-25  
**Status:** Planning

---

## Overview

Enable Robot Framework to test **OpenClaw-style agents** with:
- Multi-turn interaction tracking (full conversation, tool calls, state)
- Tool-call validation (schema, ordering, results)
- State management (memory, variables, execution context)
- Database persistence (queryable agent execution history)

### Key Architectural Patterns (from research)
- **ReAct loops**: Reasoning + action cycles maintained across turns
- **Multi-layer state**: Short-term (context window), long-term (vectors), persistent (SQL)
- **Declarative tool schemas**: Strict parameter validation before execution
- **Error recovery**: Deterministic failures (retry), semantic failures (reflection), state idempotence
- **Session awareness**: Resumability and cross-session state retrieval

---

## Phase 1: Core Data Models & Database Schema

### 1.1 Extended Data Models (src/rfc/)

**New files:**
- `agent_tool.py` — Tool definition and call tracking
- `agent_interaction.py` — Single conversation turn
- `agent_memory.py` — Short/long-term memory management
- `agent_state.py` — Execution state snapshots
- `agent_workflow.py` — Complete agent session with memory

**Data classes:**

```python
# agent_tool.py
@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    required: list[str]

@dataclass(frozen=True)
class ToolCall:
    id: str
    tool_name: str
    arguments: dict[str, Any]
    timestamp: float
    call_number: int  # Order in sequence

@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    success: bool
    output: str
    error: str | None = None
    execution_time_ms: float = 0.0

# agent_interaction.py
@dataclass(frozen=True)
class AgentMessage:
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float

@dataclass(frozen=True)
class AgentInteraction:
    """One turn in a multi-turn conversation."""
    turn_number: int
    messages: tuple[AgentMessage, ...]  # Full context for this turn
    tool_calls: tuple[ToolCall, ...]
    tool_results: tuple[ToolResult, ...]
    state_before: dict[str, Any]  # State snapshot before reasoning
    state_after: dict[str, Any]   # State snapshot after execution
    reasoning: str  # Agent's reasoning/thought process
    duration_ms: float
    success: bool
    error: str | None = None

# agent_memory.py
@dataclass
class AgentMemory:
    """Multi-layer memory system."""
    short_term: list[str]  # Sliding window of recent interactions
    long_term_vectors: dict[str, list[float]]  # Vector embeddings for retrieval
    persistent_facts: dict[str, Any]  # Schema-validated facts
    execution_ledger: list[dict[str, Any]]  # Immutable log of all actions

# agent_state.py
@dataclass(frozen=True)
class ExecutionState:
    """Snapshot of agent execution state at a point in time."""
    timestamp: float
    variables: dict[str, Any]
    memory: AgentMemory
    completed_tasks: list[str]
    failed_tasks: list[str]
    next_action: str | None
    context_usage: dict[str, int]  # Token counts, memory usage

# agent_workflow.py
@dataclass(frozen=True)
class AgentWorkflow:
    """Complete agent session: many interactions, unified state."""
    workflow_id: str
    agent_id: str
    task_description: str
    started_at: float
    ended_at: float | None
    status: str  # "running" | "completed" | "failed" | "paused"
    interactions: tuple[AgentInteraction, ...] = field(default_factory=tuple)
    memory: AgentMemory = field(default_factory=AgentMemory)
    initial_state: ExecutionState | None = None
    final_state: ExecutionState | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def interaction_count(self) -> int:
        return len(self.interactions)

    def tool_calls_by_name(self) -> dict[str, list[ToolCall]]:
        """Group all tool calls across all turns by tool name."""
        result: dict[str, list[ToolCall]] = {}
        for interaction in self.interactions:
            for call in interaction.tool_calls:
                result.setdefault(call.tool_name, []).append(call)
        return result

    def successful_tool_calls(self) -> list[tuple[ToolCall, ToolResult]]:
        """Return all tool call + result pairs that succeeded."""
        result = []
        for interaction in self.interactions:
            result_map = {r.tool_call_id: r for r in interaction.tool_results}
            for call in interaction.tool_calls:
                if call.id in result_map:
                    r = result_map[call.id]
                    if r.success:
                        result.append((call, r))
        return result
```

### 1.2 Database Schema

**New tables (PostgreSQL migrations):**

```sql
-- agent_workflows
CREATE TABLE agent_workflows (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR UNIQUE NOT NULL,
    agent_id VARCHAR NOT NULL,
    task_description TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,  -- running, completed, failed, paused
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    error TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- agent_interactions (one row per turn)
CREATE TABLE agent_interactions (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR NOT NULL REFERENCES agent_workflows(workflow_id),
    turn_number INT NOT NULL,
    reasoning TEXT,
    state_before JSONB,
    state_after JSONB,
    duration_ms FLOAT,
    success BOOLEAN,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workflow_id, turn_number)
);

-- agent_messages (within each interaction)
CREATE TABLE agent_messages (
    id SERIAL PRIMARY KEY,
    interaction_id INT NOT NULL REFERENCES agent_interactions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,  -- user, assistant, system
    content TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    message_number INT NOT NULL
);

-- tool_calls (calls made during interactions)
CREATE TABLE tool_calls (
    id SERIAL PRIMARY KEY,
    call_id VARCHAR UNIQUE NOT NULL,
    workflow_id VARCHAR NOT NULL REFERENCES agent_workflows(workflow_id),
    interaction_id INT REFERENCES agent_interactions(id),
    tool_name VARCHAR NOT NULL,
    arguments JSONB NOT NULL,
    call_number INT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- tool_results (outcomes of tool calls)
CREATE TABLE tool_results (
    id SERIAL PRIMARY KEY,
    tool_call_id VARCHAR NOT NULL REFERENCES tool_calls(call_id) ON DELETE CASCADE,
    workflow_id VARCHAR NOT NULL REFERENCES agent_workflows(workflow_id),
    success BOOLEAN NOT NULL,
    output TEXT,
    error TEXT,
    execution_time_ms FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- tool_schemas (register expected tool schemas)
CREATE TABLE tool_schemas (
    id SERIAL PRIMARY KEY,
    tool_name VARCHAR UNIQUE NOT NULL,
    description TEXT,
    parameters JSONB NOT NULL,  -- JSON Schema
    required_fields TEXT[],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- agent_memory (persistent memory snapshots)
CREATE TABLE agent_memory (
    id SERIAL PRIMARY KEY,
    workflow_id VARCHAR NOT NULL REFERENCES agent_workflows(workflow_id),
    timestamp TIMESTAMP NOT NULL,
    short_term TEXT[],
    long_term_facts JSONB,
    execution_ledger JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- execution_states (state snapshots per turn)
CREATE TABLE execution_states (
    id SERIAL PRIMARY KEY,
    interaction_id INT NOT NULL REFERENCES agent_interactions(id) ON DELETE CASCADE,
    workflow_id VARCHAR NOT NULL REFERENCES agent_workflows(workflow_id),
    variables JSONB,
    completed_tasks TEXT[],
    failed_tasks TEXT[],
    context_usage JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Migration strategy:**
- Create `migrations/0001_agent_workflows_schema.sql`
- Run during `make install` if PostgreSQL is available
- SQLite support for local testing via Alembic

---

## Phase 2: Agent Interaction Tracking

### 2.1 Core Tracking Classes (src/rfc/)

**New file: `agent_interaction_tracker.py`**

```python
class AgentInteractionTracker:
    """Capture multi-turn agent interactions in real-time."""
    
    def __init__(self, workflow_id: str, agent_id: str, task: str):
        self.workflow = AgentWorkflow(
            workflow_id=workflow_id,
            agent_id=agent_id,
            task_description=task,
            started_at=time.time()
        )
        self.current_interaction: AgentInteraction | None = None
        self._tools_registry: dict[str, ToolSchema] = {}
    
    def start_interaction(self, turn_number: int) -> None:
        """Begin tracking a new conversation turn."""
        self.current_interaction = AgentInteraction(
            turn_number=turn_number,
            messages=(),
            tool_calls=(),
            tool_results=(),
            state_before={},
            state_after={},
            reasoning="",
            duration_ms=0.0,
            success=True
        )
    
    def add_message(self, role: str, content: str) -> None:
        """Log a message (user/assistant/system)."""
        msg = AgentMessage(role=role, content=content, timestamp=time.time())
        self.current_interaction.messages += (msg,)
    
    def add_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Log a tool call, return call ID."""
        call_id = str(uuid.uuid4())
        call = ToolCall(
            id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            timestamp=time.time(),
            call_number=len(self.current_interaction.tool_calls)
        )
        self.current_interaction.tool_calls += (call,)
        return call_id
    
    def add_tool_result(self, call_id: str, success: bool, 
                       output: str = "", error: str | None = None, 
                       execution_time_ms: float = 0.0) -> None:
        """Log result from tool execution."""
        result = ToolResult(
            tool_call_id=call_id,
            success=success,
            output=output,
            error=error,
            execution_time_ms=execution_time_ms
        )
        self.current_interaction.tool_results += (result,)
    
    def set_interaction_state(self, reasoning: str, 
                             state_before: dict, state_after: dict) -> None:
        """Capture reasoning and state snapshots."""
        self.current_interaction.reasoning = reasoning
        self.current_interaction.state_before = state_before
        self.current_interaction.state_after = state_after
    
    def end_interaction(self, success: bool, error: str | None = None) -> AgentInteraction:
        """Finalize current turn and add to workflow."""
        self.current_interaction.success = success
        self.current_interaction.error = error
        self.current_interaction.duration_ms = time.time() - self.current_interaction.messages[0].timestamp if self.current_interaction.messages else 0
        
        self.workflow.interactions += (self.current_interaction,)
        return self.current_interaction
    
    def end_workflow(self, success: bool, error: str | None = None) -> AgentWorkflow:
        """Finalize entire agent session."""
        self.workflow.ended_at = time.time()
        self.workflow.status = "completed" if success else "failed"
        self.workflow.error = error
        return self.workflow
```

### 2.2 Memory Management (src/rfc/)

**New file: `agent_memory_manager.py`**

```python
class MemoryManager:
    """Manage short-term, long-term, and persistent memory for agents."""
    
    def __init__(self, memory_size: int = 5):
        self.memory = AgentMemory(
            short_term=[],
            long_term_vectors={},
            persistent_facts={},
            execution_ledger=[]
        )
        self.memory_size = memory_size
    
    def add_to_short_term(self, message: str) -> None:
        """Add message to sliding window."""
        self.memory.short_term.append(message)
        if len(self.memory.short_term) > self.memory_size:
            self.memory.short_term.pop(0)
    
    def add_persistent_fact(self, key: str, value: Any, 
                           schema: dict[str, Any] | None = None) -> None:
        """Store schema-validated persistent fact."""
        if schema:
            jsonschema.validate(value, schema)
        self.memory.persistent_facts[key] = value
    
    def log_action(self, action: dict[str, Any]) -> None:
        """Append immutable action to execution ledger."""
        action_with_timestamp = {**action, "timestamp": time.time()}
        self.memory.execution_ledger.append(action_with_timestamp)
    
    def get_short_term_context(self) -> str:
        """Retrieve recent context for prompt."""
        return "\n".join(self.memory.short_term)
```

---

## Phase 3: Tool-Call Validation

### 3.1 Validation Engine (src/rfc/)

**New file: `tool_call_validator.py`**

```python
class ToolCallValidator:
    """Validate tool calls against schemas, ordering, and results."""
    
    def __init__(self):
        self.schemas: dict[str, ToolSchema] = {}
        self.call_history: list[ToolCall] = []
    
    def register_tool(self, schema: ToolSchema) -> None:
        """Register tool with JSON Schema."""
        self.schemas[schema.name] = schema
    
    def validate_call_schema(self, call: ToolCall) -> tuple[bool, str]:
        """Check call parameters against registered schema."""
        if call.tool_name not in self.schemas:
            return False, f"Tool '{call.tool_name}' not registered"
        
        schema = self.schemas[call.tool_name]
        try:
            jsonschema.validate(call.arguments, {
                "type": "object",
                "properties": {
                    param: {"type": type(call.arguments.get(param)).__name__}
                    for param in schema.parameters
                },
                "required": schema.required
            })
            return True, ""
        except jsonschema.ValidationError as e:
            return False, str(e)
    
    def validate_call_sequence(self, calls: list[ToolCall], 
                              expected_order: list[str] | None = None) -> tuple[bool, str]:
        """Verify calls appeared in expected order."""
        if expected_order is None:
            return True, ""
        
        actual_order = [c.tool_name for c in calls]
        if actual_order != expected_order:
            return False, f"Expected {expected_order}, got {actual_order}"
        
        return True, ""
    
    def validate_result(self, call: ToolCall, result: ToolResult, 
                       expected_type: type | None = None) -> tuple[bool, str]:
        """Check result matches expectations."""
        if not result.success:
            return False, f"Tool call failed: {result.error}"
        
        if expected_type is not None:
            try:
                # Try to parse output as the expected type
                if expected_type == int:
                    int(result.output)
                elif expected_type == dict:
                    json.loads(result.output)
            except (ValueError, json.JSONDecodeError) as e:
                return False, f"Result type mismatch: {e}"
        
        return True, ""

class ToolResultValidator:
    """Validate tool results against assertions."""
    
    def __init__(self, confidence_threshold: float = 0.8):
        self.confidence_threshold = confidence_threshold
        self.assertions: list[tuple[str, Callable]] = []
    
    def assert_output_contains(self, substring: str) -> None:
        """Assert result output contains substring."""
        self.assertions.append(("contains", lambda o: substring in o))
    
    def assert_output_matches_regex(self, pattern: str) -> None:
        """Assert result matches regex."""
        self.assertions.append(("regex", lambda o: re.search(pattern, o) is not None))
    
    def assert_result_valid_json(self) -> None:
        """Assert result is valid JSON."""
        self.assertions.append(("json", lambda o: json.loads(o) is not None))
    
    def validate(self, result: ToolResult) -> tuple[bool, list[str]]:
        """Run all assertions, return pass/failures."""
        failures = []
        for name, assertion in self.assertions:
            try:
                if not assertion(result.output):
                    failures.append(f"Assertion '{name}' failed")
            except Exception as e:
                failures.append(f"Assertion '{name}' error: {e}")
        
        return len(failures) == 0, failures
```

---

## Phase 4: Robot Framework Integration

### 4.1 Keywords (src/rfc/)

**New file: `agent_workflow_keywords.py`**

```python
class AgentWorkflowKeywords:
    """Robot Framework keywords for agentic workflow testing."""
    
    def __init__(self):
        self.tracker: AgentInteractionTracker | None = None
        self.validator: ToolCallValidator | None = None
    
    def start_agent_workflow(self, workflow_id: str, agent_id: str, task: str) -> None:
        """Initialize agent workflow tracking."""
        self.tracker = AgentInteractionTracker(workflow_id, agent_id, task)
    
    def start_interaction(self, turn_number: int) -> None:
        """Begin new conversation turn."""
        assert self.tracker, "Start workflow first"
        self.tracker.start_interaction(turn_number)
    
    def agent_message(self, role: str, content: str) -> None:
        """Log agent message."""
        assert self.tracker, "Start interaction first"
        self.tracker.add_message(role, content)
    
    def agent_calls_tool(self, tool_name: str, arguments: str) -> str:
        """Log tool call (arguments as JSON string)."""
        assert self.tracker, "Start interaction first"
        args = json.loads(arguments)
        return self.tracker.add_tool_call(tool_name, args)
    
    def agent_receives_tool_result(self, call_id: str, success: bool, 
                                   output: str, error: str = "", 
                                   execution_time_ms: float = 0.0) -> None:
        """Log tool result."""
        assert self.tracker, "Start interaction first"
        self.tracker.add_tool_result(
            call_id, 
            success, 
            output, 
            error if error else None,
            execution_time_ms
        )
    
    def end_interaction(self, success: bool, error: str = "") -> None:
        """Finalize turn."""
        assert self.tracker, "Start interaction first"
        self.tracker.end_interaction(success, error if error else None)
    
    def end_agent_workflow(self, success: bool, error: str = "") -> None:
        """Finalize workflow and return as dict."""
        assert self.tracker, "Start workflow first"
        workflow = self.tracker.end_workflow(success, error if error else None)
        # Emit as RFC data for listener pickup
        logger.info(f"AGENT_WORKFLOW:{json.dumps(workflow_to_dict(workflow))}")
        return workflow
    
    def register_tool_schema(self, tool_name: str, schema_json: str) -> None:
        """Register expected tool schema."""
        if not self.validator:
            self.validator = ToolCallValidator()
        schema_dict = json.loads(schema_json)
        schema = ToolSchema(
            name=tool_name,
            description=schema_dict.get("description", ""),
            parameters=schema_dict.get("parameters", {}),
            required=schema_dict.get("required", [])
        )
        self.validator.register_tool(schema)
    
    def validate_tool_call_schema(self, call_id: str, tool_name: str, 
                                  arguments_json: str) -> None:
        """Validate tool call against registered schema."""
        assert self.validator, "Register schemas first"
        call = ToolCall(
            id=call_id,
            tool_name=tool_name,
            arguments=json.loads(arguments_json),
            timestamp=time.time(),
            call_number=0
        )
        valid, msg = self.validator.validate_call_schema(call)
        assert valid, f"Tool call validation failed: {msg}"
    
    def assert_tool_calls_in_order(self, *tool_names: str) -> None:
        """Assert tool calls appeared in expected order."""
        assert self.tracker, "Start workflow first"
        all_calls = []
        for interaction in self.tracker.workflow.interactions:
            all_calls.extend(interaction.tool_calls)
        
        valid, msg = self.validator.validate_call_sequence(
            all_calls, 
            list(tool_names)
        )
        assert valid, msg
    
    def assert_tool_was_called(self, tool_name: str, count: int = 1) -> None:
        """Assert tool was called N times."""
        assert self.tracker, "Start workflow first"
        calls = self.tracker.workflow.tool_calls_by_name()
        actual = len(calls.get(tool_name, []))
        assert actual == count, f"Expected {count} calls to {tool_name}, got {actual}"
    
    def assert_all_tool_calls_succeeded(self) -> None:
        """Assert all tool calls returned successfully."""
        assert self.tracker, "Start workflow first"
        for interaction in self.tracker.workflow.interactions:
            for result in interaction.tool_results:
                assert result.success, f"Tool call {result.tool_call_id} failed: {result.error}"
    
    def get_workflow_summary(self) -> dict:
        """Return human-readable workflow summary."""
        assert self.tracker, "Start workflow first"
        return {
            "workflow_id": self.tracker.workflow.workflow_id,
            "turns": len(self.tracker.workflow.interactions),
            "tool_calls": sum(
                len(i.tool_calls) for i in self.tracker.workflow.interactions
            ),
            "successful_calls": len(self.tracker.workflow.successful_tool_calls()),
            "status": self.tracker.workflow.status
        }
```

### 4.2 Test Suite

**New directory: `robot/agent_workflows/`**

**File: `robot/agent_workflows/tests/basic_workflow.robot`**

```robot
*** Settings ***
Documentation     Basic agentic workflow test
Library           rfc.agent_workflow_keywords.AgentWorkflowKeywords    WITH NAME    Agent
Library           Collections

*** Test Cases ***
Agent Completes Multi-Turn Task
    [Documentation]    Test multi-turn agent workflow
    [Tags]    tier:2    agent-workflow    github-issue
    
    Agent.Start Agent Workflow    workflow-001    claude-agent    Resolve GitHub issue by creating PR
    
    # Turn 1: Analyze issue
    Agent.Start Interaction    1
    Agent.Agent Message    user    Resolve issue: "Add dark mode toggle"
    Agent.Agent Message    assistant    I'll analyze the issue and create a PR
    Agent.Agent Calls Tool    git    {"cmd": "clone", "url": "https://github.com/..."}
    Agent.Agent Receives Tool Result    tool-1    ${True}    Cloned repository
    Agent.End Interaction    ${True}
    
    # Turn 2: Make changes
    Agent.Start Interaction    2
    Agent.Agent Message    user    Now implement the feature
    Agent.Agent Calls Tool    filesystem    {"cmd": "write", "path": "src/theme.js"}
    Agent.Agent Receives Tool Result    tool-2    ${True}    File written
    Agent.End Interaction    ${True}
    
    # Turn 3: Create PR
    Agent.Start Interaction    3
    Agent.Agent Calls Tool    github    {"action": "create_pr", "title": "Add dark mode"}
    Agent.Agent Receives Tool Result    tool-3    ${True}    PR created #123
    Agent.End Interaction    ${True}
    
    # Validate workflow
    Agent.Assert Tool Was Called    git    1
    Agent.Assert Tool Was Called    filesystem    1
    Agent.Assert Tool Was Called    github    1
    Agent.Assert Tool Calls In Order    git    filesystem    github
    Agent.Assert All Tool Calls Succeeded
    
    # Finalize
    ${summary}=    Agent.Get Workflow Summary
    Log    ${summary}
    Should Be Equal    ${summary}[turns]    3
    Should Be Equal    ${summary}[status]    completed
    
    Agent.End Agent Workflow    ${True}

Agent Handles Tool Failures Gracefully
    [Documentation]    Test error recovery in workflow
    [Tags]    tier:2    agent-workflow    error-handling
    
    Agent.Start Agent Workflow    workflow-002    claude-agent    Handle API failure
    
    Agent.Start Interaction    1
    Agent.Agent Calls Tool    api    {"endpoint": "/broken"}
    Agent.Agent Receives Tool Result    tool-1    ${False}    error    API returned 500    150
    Agent.Agent Message    assistant    API failed, retrying...
    Agent.End Interaction    ${True}
    
    Agent.Start Interaction    2
    Agent.Agent Calls Tool    api    {"endpoint": "/broken"}
    Agent.Agent Receives Tool Result    tool-2    ${True}    Success
    Agent.End Interaction    ${True}
    
    Agent.Assert All Tool Calls Succeeded    # Second attempt succeeded
    Agent.End Agent Workflow    ${True}
```

### 4.3 Listener Integration

**New file: `src/rfc/agent_workflow_listener.py`**

```python
"""Robot Framework listener for agent workflow data persistence."""

class AgentWorkflowListener:
    """Capture and persist agent workflow data to database."""
    
    ROBOT_LISTENER_API_VERSION = 3
    
    def __init__(self, db_url: str | None = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.workflows: dict[str, AgentWorkflow] = {}
    
    def start_test(self, data: dict, result: dict):
        """Extract workflow ID from test if present."""
        # Workflow setup happens in test; we'll capture from log messages
        pass
    
    def message(self, message: dict):
        """Listen for AGENT_WORKFLOW: log messages."""
        if "AGENT_WORKFLOW:" in message["message"]:
            workflow_json = message["message"].split("AGENT_WORKFLOW:")[1]
            workflow_dict = json.loads(workflow_json)
            workflow = dict_to_workflow(workflow_dict)
            self.workflows[workflow.workflow_id] = workflow
    
    def end_suite(self, suite: dict, result: dict):
        """Persist all captured workflows to database."""
        if not self.db_url:
            return
        
        with TestDatabase(self.db_url) as db:
            for workflow in self.workflows.values():
                self._persist_workflow(db, workflow)
    
    def _persist_workflow(self, db: TestDatabase, workflow: AgentWorkflow):
        """Write workflow and all related data to database."""
        # Insert workflow
        workflow_row = {
            "workflow_id": workflow.workflow_id,
            "agent_id": workflow.agent_id,
            "task_description": workflow.task_description,
            "status": workflow.status,
            "started_at": workflow.started_at,
            "ended_at": workflow.ended_at,
            "error": workflow.error,
            "metadata": json.dumps(workflow.metadata)
        }
        db.execute("INSERT INTO agent_workflows (...) VALUES (...)", workflow_row)
        
        # Insert interactions
        for interaction in workflow.interactions:
            interaction_row = {
                "workflow_id": workflow.workflow_id,
                "turn_number": interaction.turn_number,
                "reasoning": interaction.reasoning,
                "state_before": json.dumps(interaction.state_before),
                "state_after": json.dumps(interaction.state_after),
                # ...
            }
            db.execute("INSERT INTO agent_interactions (...) VALUES (...)", interaction_row)
            
            # Insert tool calls and results
            for call in interaction.tool_calls:
                self._persist_tool_call(db, workflow.workflow_id, call)
            
            for result in interaction.tool_results:
                self._persist_tool_result(db, workflow.workflow_id, result)
```

---

## Phase 5: Testing & Documentation

### 5.1 Python Unit Tests (tests/)

- `test_agent_interaction_tracker.py` — Capture turns, messages, tool calls
- `test_tool_call_validator.py` — Schema validation, ordering, result checks
- `test_agent_memory_manager.py` — Memory operations
- `test_agent_workflow.py` — End-to-end workflow construction

### 5.2 Robot Tests (robot/agent_workflows/)

- `basic_workflow.robot` — Multi-turn interaction
- `tool_validation.robot` — Schema and result validation
- `error_recovery.robot` — Failure handling
- `memory_and_state.robot` — State management across turns
- `github_issue_workflow.robot` — Real use case (GitHub PR creation)

### 5.3 Documentation

- `robot/agent_workflows/README.md` — Test suite guide
- Update `ai/testing.md` with agent workflow tier guidance
- Update `ai/agents.md` with agent testing patterns
- Example agent configuration YAML

---

## Implementation Order

1. **Phase 1.1** — Data models (no tests yet, exploratory)
2. **Phase 1.2** — Database schema and migrations
3. **Phase 2** — Tracker and memory classes + unit tests
4. **Phase 3** — Validator + unit tests
5. **Phase 4.1** — Keywords + unit tests
6. **Phase 4.2** — Robot test suite (start with one test)
7. **Phase 4.3** — Listener + integration
8. **Phase 5** — Complete test coverage, documentation

---

## Success Criteria

✅ Multi-turn interactions captured with full state  
✅ Tool calls validated against schemas  
✅ Tool results validated for correctness  
✅ Agent memory managed across turns  
✅ Workflow data persisted to database (queryable)  
✅ Robot tests passing with tier tags  
✅ Example: GitHub issue → PR workflow passing  
✅ Full pytest coverage for new modules  
✅ Documentation complete  

---

## Estimated Effort

- Phase 1 (Data models + schema): ~4-6 hours
- Phase 2 (Interaction tracking): ~3-4 hours
- Phase 3 (Validation): ~2-3 hours
- Phase 4 (Robot integration): ~4-5 hours
- Phase 5 (Testing + docs): ~3-4 hours

**Total: ~16-22 hours of focused development**

---

*Plan created: 2026-04-25*  
*Status: Ready for approval*
