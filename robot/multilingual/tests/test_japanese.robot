*** Settings ***
Documentation     Japanese-language instruction-following tests.
...
...               Each test issues a Japanese-language prompt and verifies a
...               structural constraint on the response with a deterministic
...               Python checker.  No LLM judge is involved.
...
...               Japanese has no inter-word whitespace, so word-level checks
...               on Japanese responses are not meaningful.  Tests that rely
...               on whitespace tokenisation request an English response,
...               while format-based checks (bullets, numbered lists,
...               paragraphs) work uniformly across scripts.

Resource          ../multilingual.resource

Default Tags      multilingual    japanese    regression    tier:1    verify:python

Test Timeout      2 minutes

*** Test Cases ***
Japanese Prompt Japanese Response Bullet Points
    [Documentation]    Japanese prompt requesting exactly 4 bullet points in Japanese.
    Run Multilingual IFEval Test
    ...    日本の伝統的な食べ物を4つ挙げてください。各項目は箇条書き(-で始まる)のみを使用してください。ちょうど4つの箇条書きを出力し、それ以外は何も書かないでください。
    ...    bullet_points    4

Japanese Prompt Japanese Response Numbered List
    [Documentation]    Japanese prompt asking for a numbered list 1..5 with Latin numerals.
    Run Multilingual IFEval Test
    ...    日本の有名な都市を5つ挙げてください。各項目に半角数字で1から5まで番号を付け、「N. 項目」の形式で書いてください。番号付きリスト以外は出力しないでください。
    ...    numbered_list    5

Japanese Prompt Japanese Response Paragraph Count
    [Documentation]    Japanese prompt requiring exactly 2 Japanese paragraphs.
    Run Multilingual IFEval Test
    ...    重力についてちょうど2段落で説明してください。段落は空行で区切ってください。見出しや余分な文章は入れないでください。
    ...    paragraph_count    2

Japanese Prompt English Response Word Count
    [Documentation]    Japanese instruction, response in English — tests cross-lingual instruction following.
    Run Multilingual IFEval Test
    ...    英語で答えてください。虹をちょうど20語の英語で説明してください。多くも少なくもない、ぴったり20語で書いてください。
    ...    word_count    20

Japanese Prompt English Response Sentence Count
    [Documentation]    Japanese prompt instructing a 3-sentence English response.
    Run Multilingual IFEval Test
    ...    英語で答えてください。光合成についてちょうど3文の英語で説明してください。各文はピリオドで終わらせてください。それ以外の文章は入れないでください。
    ...    sentence_count    3

Japanese Prompt English Response Ends With Word
    [Documentation]    Japanese prompt instructing an English response ending in OWARI.
    Run Multilingual IFEval Test
    ...    英語で答えてください。富士山について2〜3文の英語で簡単に説明してください。回答全体の最後の単語は OWARI でなければなりません。
    ...    ends_with_word    OWARI

Japanese Prompt English Response Bullet Points
    [Documentation]    Japanese prompt requesting English bullet-point response.
    Run Multilingual IFEval Test
    ...    英語で答えてください。運動の利点を3つ挙げてください。箇条書き(-で始まる)のみを使用してください。ちょうど3つの箇条書きを出力し、それ以外は何も書かないでください。
    ...    bullet_points    3
