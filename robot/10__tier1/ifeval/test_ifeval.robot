*** Settings ***
Documentation     IFEval instruction-following constraint tests.
...
...               Each test sends a strictly constrained prompt to the LLM and
...               verifies the response with a deterministic Python checker.
...               No LLM judge is involved — results are fully reproducible.

Resource          ifeval.resource

Default Tags      ifeval    regression    tier:1    verify:python

Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***
Exact Sentence Count
    [Documentation]    LLM must respond in exactly 3 sentences.
    Run IFEval Test
    ...    Describe the water cycle in exactly 3 sentences. Do not include any other text.
    ...    sentence_count    3

All Caps Response
    [Documentation]    LLM must respond entirely in uppercase letters.
    Run IFEval Test
    ...    Name three planets. Write your entire response in ALL CAPS. Do not use any lowercase letters.
    ...    all_caps

Bullet Points Only
    [Documentation]    LLM must respond with exactly 5 bullet points.
    Run IFEval Test
    ...    List 5 benefits of exercise. Use only bullet points (starting with -). Output exactly 5 bullet points and nothing else.
    ...    bullet_points    5

Single Word Response
    [Documentation]    LLM must respond with exactly one word.
    Run IFEval Test
    ...    What is the capital of France? Respond with a single word only. No punctuation, no explanation.
    ...    word_count    1

Numbered List 1 To 7
    [Documentation]    LLM must produce a numbered list from 1 to 7.
    Run IFEval Test
    ...    List the days of the week. Number each item from 1 to 7 using the format "N. item". Output only the numbered list.
    ...    numbered_list    7

Exact Paragraph Count
    [Documentation]    LLM must respond in exactly 2 paragraphs.
    Run IFEval Test
    ...    Explain photosynthesis in exactly 2 paragraphs. Separate the paragraphs with a blank line. Do not add any headings or extra text.
    ...    paragraph_count    2

Forbidden Letter E
    [Documentation]    LLM must not use the letter 'e' anywhere in the response.
    Run IFEval Test
    ...    Describe a sunset without using the letter 'e' anywhere in your response. Not even once.
    ...    forbidden_letter    e

Every Sentence Starts With Dogs
    [Documentation]    Every sentence must begin with the word 'Dogs'.
    Run IFEval Test
    ...    Explain why dogs are good pets. Start every sentence with the word 'Dogs'. Do not start any sentence with a different word.
    ...    sentence_start    Dogs

Response Ends With END
    [Documentation]    The last word of the response must be 'END'.
    Run IFEval Test
    ...    Tell me about the ocean in 2-3 sentences. You must end your entire response with the word 'END' as the very last word.
    ...    ends_with_word    END

Exact Word Count 20
    [Documentation]    LLM must respond in exactly 20 words.
    Run IFEval Test
    ...    Describe a rainbow in exactly 20 words. Count carefully. Do not write more or fewer than 20 words.
    ...    word_count    20

All Lowercase Response
    [Documentation]    LLM must respond entirely in lowercase letters.
    Run IFEval Test
    ...    Explain what gravity is in 2-3 sentences. Write your entire response in lowercase only. Do not capitalize anything.
    ...    all_lowercase

No Digits In Response
    [Documentation]    LLM must not use any numeric digits.
    Run IFEval Test
    ...    Describe the seasons of the year without using any numbers or digits. Spell out any quantities in words.
    ...    no_digits
