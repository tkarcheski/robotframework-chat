*** Settings ***
Documentation     Theory-of-mind tests.
...
...               Tests whether the LLM can track agent beliefs that differ
...               from reality (false-belief attribution) and reason about
...               intentions and emotional states (perspective-taking).
...
...               False-belief tests are tier:1 (the expected word must appear).
...               Open-ended perspective-taking tests are tier:2 (LLM-graded).

Resource          epistemic.resource

Test Timeout      2 minutes

*** Test Cases ***

# ── False Belief (Tier:1) ─────────────────────────────────────────────────────

Sally-Anne Classic False Belief
    [Documentation]    Sally places her marble in a red basket and leaves.
    ...                Anne moves it to a blue box while Sally is away.
    ...                When Sally returns, she will look in the red basket
    ...                (her last known location) — not the blue box.
    [Tags]    epistemic    theory_of_mind    false_belief    tier:1    verify:python
    Assert Theory Of Mind
    ...    Sally places her marble in a red basket and then leaves the room. While Sally is gone, Anne moves the marble from the red basket to a blue box. When Sally returns to the room, which container will she look in first to find her marble? Reply with only the container name.
    ...    red basket

False Belief About Money Amount
    [Documentation]    Mark thinks he has $100 because he doesn't know $30 was stolen.
    ...                If asked, he will say "$100".
    [Tags]    epistemic    theory_of_mind    false_belief    tier:1    verify:python
    Assert Theory Of Mind
    ...    Mark has $100 in his wallet. While Mark is asleep, his roommate secretly takes $30 from the wallet. Mark does not know money was taken. If a friend asks Mark how much money he has in his wallet, what amount will Mark say? Reply with only the dollar amount.
    ...    $100

False Belief About Object Location
    [Documentation]    A book was moved from the shelf to the desk while its owner was away.
    ...                The owner will look on the shelf — where they left it.
    [Tags]    epistemic    theory_of_mind    false_belief    tier:1    verify:python
    Assert Theory Of Mind
    ...    Emma leaves her favourite book on the bedroom shelf and goes to work. While Emma is at work, her sister moves the book from the shelf to the kitchen table. When Emma comes home and wants to read the book, where will she look for it first? Reply with only the location.
    ...    shelf

False Belief — What Does The Agent Think, Not What Is True
    [Documentation]    Tests whether the model answers from the agent's perspective
    ...                rather than from the ground truth.
    [Tags]    epistemic    theory_of_mind    false_belief    tier:1    verify:python
    Assert Theory Of Mind
    ...    John tells his coworkers he is going to be at the office all day Friday. Unknown to John, his manager scheduled him to work from home on Friday. On Friday morning, where does John think he will be working? Reply with only the location.
    ...    office

# ── Perspective-Taking (Tier:2) ───────────────────────────────────────────────

Surprise Gift — Emotional Perspective Taking
    [Documentation]    A child receives a duplicate birthday gift and must navigate
    ...                two conflicting goals: honesty and not hurting the giver's feelings.
    [Tags]    epistemic    theory_of_mind    perspective_taking    tier:2    verify:llm
    Assert Perspective Taking
    ...    A child receives a birthday present and unwraps it to find a toy they already have. How is the child likely to feel, and how might they behave to avoid hurting the gift-giver's feelings?
    ...    The child likely feels disappointed or awkward but will probably hide this by thanking the giver warmly, smiling, and pretending enthusiasm to protect the giver's feelings — a classic example of managing social emotions and others' beliefs simultaneously.
    ...    min_score=0.5

Deceptive Intent Attribution
    [Documentation]    A person tells a false reason for absence. The model must
    ...                correctly attribute the speaker's intended false belief to their audience.
    [Tags]    epistemic    theory_of_mind    intent    perspective_taking    tier:2    verify:llm
    Assert Perspective Taking
    ...    Jane calls in sick to work because she wants to attend a concert, even though she is perfectly healthy. What does Jane want her boss to believe? And what does Jane's boss actually have reason to believe after the call?
    ...    Jane wants her boss to believe she is genuinely ill. Her boss, having no contrary evidence, has reason to believe the stated excuse — that Jane is sick — even though this belief is false. Jane has intentionally created a false belief in her boss's mind.
    ...    min_score=0.5

Second-Order Belief Attribution
    [Documentation]    Does the model track what Agent A knows about what Agent B believes?
    [Tags]    epistemic    theory_of_mind    second_order    tier:2    verify:llm
    Assert Perspective Taking
    ...    Anna hides a birthday cake in the pantry. Ben sees Anna do this. Anna does not know Ben was watching. Later, Ben tells no one. Does Ben know where the cake is? Does Anna know that Ben knows? Explain your reasoning.
    ...    Ben knows where the cake is (he watched Anna hide it). Anna does not know Ben knows — she is unaware he observed her. This demonstrates a second-order belief gap: Ben's knowledge state differs from Anna's model of Ben's knowledge state.
    ...    min_score=0.5
