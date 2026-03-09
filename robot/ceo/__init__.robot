*** Settings ***
Documentation     CEO Agent — Agentic Product Workflow Testing Pipeline
...
...               Multi-stage pipeline testing: idea brainstorming, market research,
...               IP analysis, patent strategy, and licensing strategy.
...
...               Each stage is tested independently with seeded inputs and graded
...               by multi-LLM majority vote (tier:3).

Resource          ceo.resource

Suite Setup       Setup CEO Test Environment
Suite Teardown    Cleanup CEO Tests

Force Tags        ceo    agentic    tier:3    verify:llms

Metadata          Version           1.0.0
Metadata          Author            RobotFramework-Chat CEO Agent Suite
Metadata          Category          Agentic Workflow Testing
