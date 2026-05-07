*** Settings ***
Documentation     Logical flaw and argument correction tests.
...
...               Presents the LLM with arguments that contain formal logical
...               fallacies or flawed reasoning and asks the model to identify
...               the flaw.  Graded by an LLM judge (tier:2) because the
...               explanation of a fallacy cannot be reduced to a keyword check.

Resource          self_correction.resource

Default Tags      self_correction    logical_flaw    tier:2    verify:llm

Test Timeout      2 minutes

*** Test Cases ***

Post Hoc Ergo Propter Hoc — Rooster And Sunrise
    [Documentation]    Classic post-hoc fallacy: the rooster crows before dawn,
    ...                therefore the rooster causes the sun to rise.
    [Tags]    self_correction    logical_flaw    post_hoc    tier:2    verify:llm
    Assert Logical Flaw Identified
    ...    Every day, the rooster crows just before sunrise. Therefore, the rooster crowing causes the sun to rise.
    ...    This is a post hoc ergo propter hoc fallacy (correlation implies causation). The rooster crows at dawn due to its circadian rhythm; the sun rises independently. Temporal precedence alone does not establish causation.

Ad Hominem — Dismissing The Argument By Attacking The Person
    [Documentation]    Classic ad hominem: dismissing an argument by attacking the person making it.
    [Tags]    self_correction    logical_flaw    ad_hominem    tier:2    verify:llm
    Assert Logical Flaw Identified
    ...    We should not trust Dr. Smith's research on climate change because she once made an error in a different paper ten years ago.
    ...    This is an ad hominem attack — it attacks the credibility of the person rather than engaging with the content of the research. A past mistake in a different domain does not invalidate current work, which must be evaluated on its own merits.

False Dilemma — Only Two Options
    [Documentation]    False dilemma presents only two options when more exist.
    [Tags]    self_correction    logical_flaw    false_dilemma    tier:2    verify:llm
    Assert Logical Flaw Identified
    ...    You are either with us or against us. Since you did not sign our petition, you must be against us.
    ...    This is a false dilemma (false dichotomy). It presents only two options when many others exist — someone might be neutral, uninformed, or supportive of the goal but opposed to the petition's wording. Disagreement on method does not imply opposition to the cause.

Slippery Slope — Video Games Lead To Violence
    [Documentation]    Slippery slope fallacy assumes a chain of events without justification.
    [Tags]    self_correction    logical_flaw    slippery_slope    tier:2    verify:llm
    Assert Logical Flaw Identified
    ...    If we allow teenagers to play violent video games, they will become desensitised to violence, then they will start committing minor crimes, and eventually they will become violent criminals.
    ...    This is a slippery slope fallacy. It assumes a chain of causal steps without evidence that each step necessarily leads to the next. The argument skips from a starting condition to an extreme outcome without justifying the intermediate links.

Affirming The Consequent — Classic Syllogism Error
    [Documentation]    Formal logical error: affirming the consequent.
    ...                P→Q, Q is true, therefore P is true — this is invalid.
    [Tags]    self_correction    logical_flaw    affirming_consequent    tier:2    verify:llm
    Assert Logical Flaw Identified
    ...    If it is raining, the ground is wet. The ground is wet. Therefore it is raining.
    ...    This is the formal fallacy of affirming the consequent. The ground can be wet for many reasons (sprinklers, flooding, spillage), so wetness does not prove it is raining. Valid inference would require: if and only if it is raining, the ground is wet.

Circular Reasoning — Bible Is True Because God Says So
    [Documentation]    Circular argument: the conclusion is used as a premise.
    [Tags]    self_correction    logical_flaw    circular_reasoning    tier:2    verify:llm
    Assert Logical Flaw Identified
    ...    The Bible is the word of God. We know this because the Bible itself says that it is the word of God. Therefore the Bible is true.
    ...    This is circular reasoning (begging the question). The argument uses the Bible's claims to prove the Bible's claims. The conclusion is embedded in the premise, providing no independent evidence.

Hasty Generalisation — One Bad Experience
    [Documentation]    Hasty generalisation from a single data point.
    [Tags]    self_correction    logical_flaw    hasty_generalisation    tier:2    verify:llm
    Assert Logical Flaw Identified
    ...    I had one bad experience at a restaurant last week, so all restaurants in this city are terrible.
    ...    This is a hasty generalisation — drawing a broad conclusion from a single, unrepresentative example. One negative experience at one restaurant provides no basis for judging all restaurants in the city.
