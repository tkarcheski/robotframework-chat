*** Settings ***
Documentation     Tests LLM task management abilities: prioritization, decomposition,
...               dependency analysis, triage, scheduling, and planning.
Library           rfc.keywords.LLMKeywords    WITH NAME    LLM

*** Keywords ***
Ask And Validate
    [Arguments]    ${question}    ${expected}
    ${score}    ${reason}    ${answer}=    LLM.Ask And Grade With Retry    ${question}    ${expected}
    Should Be Equal As Integers    ${score}    1
    Log    Question: ${question} | Answer: ${answer} | Reason: ${reason}

*** Test Cases ***
IQ 100 Simple Task Prioritization
    [Documentation]    Can the LLM correctly rank 5 tasks by priority, identifying a production outage as highest?
    [Tags]    IQ:100
    ${question}=    Set Variable
    ...    Rank these 5 tasks from highest to lowest priority and explain your reasoning:
    ...    1. Update the team wiki with meeting notes from last week
    ...    2. Fix a production database outage affecting all customers
    ...    3. Review a coworker's pull request for a minor UI tweak
    ...    4. Respond to a non-urgent email from a vendor about a renewal next month
    ...    5. Prepare slides for a presentation happening tomorrow morning
    ${expected}=    Set Variable
    ...    The production database outage (task 2) must be ranked first because it affects all customers.
    ...    The presentation slides (task 5) should be second because the deadline is tomorrow.
    ...    The pull request review (task 3) should be in the middle.
    ...    The vendor email (task 4) and wiki update (task 1) should be lowest priority
    ...    since they have no immediate deadline.
    Ask And Validate    ${question}    ${expected}

IQ 110 Break Down Complex Task
    [Documentation]    Can the LLM decompose 'Set up a PostgreSQL database' into logically ordered subtasks?
    [Tags]    IQ:110
    ${question}=    Set Variable
    ...    Break down the following task into ordered subtasks:
    ...    "Set up a PostgreSQL database for a new web application."
    ...    List each subtask in the order it should be performed.
    ${expected}=    Set Variable
    ...    The subtasks should include, in a logical order:
    ...    installing PostgreSQL, configuring the server settings,
    ...    creating the database, creating a user/role with appropriate permissions,
    ...    setting up the schema or running migrations,
    ...    and testing the connection from the application.
    ...    Install must come before configuration, and configuration before creating the database.
    Ask And Validate    ${question}    ${expected}

IQ 120 Identify Task Dependencies
    [Documentation]    Can the LLM produce a valid execution order for 5 tasks with dependency constraints?
    [Tags]    IQ:120
    ${question}=    Set Variable
    ...    Given these software project tasks and their dependencies, provide a valid execution order:
    ...    Task A: Write unit tests (depends on Task B)
    ...    Task B: Implement the API endpoint (depends on Task C)
    ...    Task C: Design the database schema (no dependencies)
    ...    Task D: Write API documentation (depends on Task B)
    ...    Task E: Deploy to staging (depends on Task A and Task D)
    ...    List all tasks in an order that respects all dependency constraints.
    ${expected}=    Set Variable
    ...    Task C must come first since it has no dependencies.
    ...    Task B must come after Task C. Task A and Task D must both come after Task B.
    ...    Task E must come last since it depends on both Task A and Task D.
    ...    A valid order is: C, B, A, D, E or C, B, D, A, E.
    Ask And Validate    ${question}    ${expected}

IQ 120 Triage Support Tickets
    [Documentation]    Can the LLM correctly categorize 5 support tickets by severity (Critical/High/Medium/Low)?
    [Tags]    IQ:120
    ${question}=    Set Variable
    ...    Categorize each support ticket as Critical, High, Medium, or Low severity:
    ...    Ticket 1: "Users report that all data entered in the last hour has been lost."
    ...    Ticket 2: "The login page returns a 500 error for all users."
    ...    Ticket 3: "A typo in the footer says 'Copyrght' instead of 'Copyright'."
    ...    Ticket 4: "CSV export takes 30 seconds instead of the usual 5 seconds."
    ...    Ticket 5: "The mobile app crashes when rotating the screen on the settings page."
    ...    Explain your reasoning for each categorization.
    ${expected}=    Set Variable
    ...    Ticket 1 (data loss) should be Critical because data loss is the most severe issue.
    ...    Ticket 2 (login 500 error) should be Critical or High because it blocks all users from logging in.
    ...    Ticket 3 (typo) should be Low because it is cosmetic with no functional impact.
    ...    Ticket 4 (slow export) should be Medium because it is a performance degradation but not a blocker.
    ...    Ticket 5 (crash on rotate) should be Medium or High because it crashes the app but only in a specific scenario.
    Ask And Validate    ${question}    ${expected}

IQ 130 Schedule Tasks With Time Constraints
    [Documentation]    Can the LLM schedule 5 tasks within an 8-hour workday respecting time constraints and dependencies?
    [Tags]    IQ:130
    ${question}=    Set Variable
    ...    You have an 8-hour workday (9am to 5pm) and these tasks to complete:
    ...    - Code review: 1 hour, must be done before noon
    ...    - Bug fix: 2 hours, no constraint
    ...    - Team meeting: 1 hour, fixed at 2pm-3pm (cannot be moved)
    ...    - Write tests: 2 hours, must be done after the bug fix
    ...    - Deploy to staging: 30 minutes, must be the last task of the day
    ...    Create a schedule that fits all tasks and respects every constraint.
    ...    Show start and end times for each task.
    ${expected}=    Set Variable
    ...    The schedule must satisfy all constraints:
    ...    Code review finishes before noon (e.g., 9am-10am).
    ...    Team meeting is exactly at 2pm-3pm.
    ...    Bug fix happens before write tests.
    ...    Deploy to staging is the last task of the day.
    ...    Total task time is 6.5 hours which fits in the 8-hour day.
    ...    All time slots must be non-overlapping.
    Ask And Validate    ${question}    ${expected}

IQ 130 Create Action Plan From Vague Request
    [Documentation]    Can the LLM create a structured diagnostic plan from 'Our website is slow, fix it'?
    [Tags]    IQ:130
    ${question}=    Set Variable
    ...    A manager says: "Our website is slow, fix it."
    ...    Create a structured action plan with concrete, ordered steps
    ...    to diagnose and resolve the performance issue.
    ...    Include what tools or metrics you would use at each step.
    ${expected}=    Set Variable
    ...    The plan should include diagnostic steps before jumping to fixes:
    ...    1. Measure current performance (mention tools like Lighthouse, browser devtools, or APM).
    ...    2. Identify bottlenecks (database queries, API response times, frontend rendering).
    ...    3. Prioritize the biggest bottlenecks by impact.
    ...    4. Implement specific fixes (e.g., add caching, optimize queries, compress assets, use a CDN).
    ...    5. Verify improvements with before/after metrics.
    ...    The plan must be structured (numbered or phased) and not jump straight to solutions.
    Ask And Validate    ${question}    ${expected}

IQ 140 Identify Blockers And Risks
    [Documentation]    Can the LLM identify blockers and risks in a 5-week project plan missing QA testing?
    [Tags]    IQ:140
    ${question}=    Set Variable
    ...    Review this project plan and identify all blockers, risks, and issues:
    ...    Week 1: Alice designs the database schema.
    ...    Week 2: Bob implements the backend API (needs the schema from Alice).
    ...    Week 3: Alice is on vacation. Bob writes unit tests for the API.
    ...    Week 4: Alice implements the frontend (needs the API from Bob).
    ...    Week 5: Bob deploys to production.
    ...    Note: No QA testing is mentioned. The client demo is scheduled for Week 5.
    ...    What problems do you see?
    ${expected}=    Set Variable
    ...    Must identify these issues:
    ...    1. No QA or testing phase before deployment and client demo in Week 5.
    ...    2. Alice is on vacation in Week 3 which is fine, but if Week 1 slips,
    ...       the entire chain is delayed since Bob depends on Alice's schema.
    ...    3. Bob deploys to production in the same week as the client demo,
    ...       which is risky because there is no buffer for deployment issues.
    ...    4. There is no integration testing between frontend and backend.
    ...    Should recommend adding QA time and a buffer before the demo.
    Ask And Validate    ${question}    ${expected}

IQ 150 Multi-Constraint Task Ordering
    [Documentation]    Can the LLM schedule a multi-course banquet with single-oven and appetizer-before-mains constraints?
    [Tags]    IQ:150
    ${question}=    Set Variable
    ...    A restaurant kitchen must prepare these dishes for a banquet at 7pm:
    ...    - Roast chicken: 30 min prep, 90 min oven, serves as main course
    ...    - Baked salmon: 20 min prep, 45 min oven, serves as main course
    ...    - Garlic bread: 10 min prep, 15 min oven, serves as appetizer
    ...    - Caesar salad: 15 min prep, no cooking needed, serves as appetizer
    ...    - Chocolate cake: 25 min prep, 40 min oven, must cool 30 min after baking
    ...    - Soup: 10 min prep, 30 min stovetop (no oven needed), serves as appetizer
    ...    Constraints:
    ...    - The kitchen has only ONE oven (only one dish in the oven at a time).
    ...    - Appetizers must be ready before main courses.
    ...    - All dishes must be ready by 7pm.
    ...    - It is currently 3pm, so you have 4 hours.
    ...    Create a timeline showing when to prep, cook, and serve each dish.
    ${expected}=    Set Variable
    ...    The schedule must respect the single-oven constraint (no overlapping oven times).
    ...    Total oven time is 190 minutes (chicken 90 + salmon 45 + bread 15 + cake 40),
    ...    which exceeds 3 hours, so oven scheduling is the critical path.
    ...    The chocolate cake needs oven time plus 30 min cooling, so it should go in early.
    ...    Caesar salad and soup use no oven so they can be prepared in parallel.
    ...    Appetizers (garlic bread, salad, soup) should be ready before mains.
    ...    The roast chicken takes the longest oven time and should be planned carefully.
    Ask And Validate    ${question}    ${expected}
