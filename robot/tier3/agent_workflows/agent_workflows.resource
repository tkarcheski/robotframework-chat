*** Settings ***
Documentation     Common imports for OpenClaw-style agent workflow tests.
...               Provides the AgentWorkflowKeywords library and a small
...               helper for constructing JSON tool arguments inline.

Library           rfc.agent_workflow_keywords.AgentWorkflowKeywords    WITH NAME    Agent
Library           Collections
