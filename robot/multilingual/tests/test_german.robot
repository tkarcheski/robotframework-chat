*** Settings ***
Documentation     German-language instruction-following tests.
...
...               Each test issues a German-language prompt and verifies a
...               structural constraint on the response with a deterministic
...               Python checker.  No LLM judge is involved.

Resource          ../multilingual.resource

Default Tags      multilingual    german    regression    tier:1    verify:python

Test Timeout      2 minutes

*** Test Cases ***
German Prompt German Response Word Count
    [Documentation]    German instruction asking for a 12-word German reply.
    Run Multilingual IFEval Test
    ...    Beschreibe einen Wald in genau 12 Wörtern. Schreibe nicht mehr und nicht weniger. Füge keinen weiteren Text hinzu.
    ...    word_count    12

German Prompt German Response Bullet Points
    [Documentation]    German prompt requesting exactly 4 bullet points in German.
    Run Multilingual IFEval Test
    ...    Nenne vier Vorteile von Bewegung. Verwende ausschließlich Aufzählungspunkte (beginnend mit -). Schreibe genau 4 Punkte und sonst nichts.
    ...    bullet_points    4

German Prompt German Response Numbered List
    [Documentation]    German prompt asking for a numbered list 1..6.
    Run Multilingual IFEval Test
    ...    Liste die ersten sechs Planeten unseres Sonnensystems auf. Nummeriere jeden Eintrag von 1 bis 6 im Format "N. Element". Gib nur die nummerierte Liste aus.
    ...    numbered_list    6

German Prompt English Response Sentence Count
    [Documentation]    German instruction, response in English — tests cross-lingual instruction following.
    Run Multilingual IFEval Test
    ...    Antworte auf Englisch. Beschreibe den Wasserkreislauf in genau 3 Sätzen. Beende jeden Satz mit einem Punkt. Kein zusätzlicher Text.
    ...    sentence_count    3

German Prompt English Response Ends With Word
    [Documentation]    German prompt instructing English response that ends with ENDE.
    Run Multilingual IFEval Test
    ...    Antworte auf Englisch. Beschreibe in 2 bis 3 Sätzen einen Berg. Das letzte Wort deiner Antwort muss ENDE sein.
    ...    ends_with_word    ENDE

German Prompt German Response Paragraph Count
    [Documentation]    German prompt requiring exactly 2 German paragraphs.
    Run Multilingual IFEval Test
    ...    Erkläre die Schwerkraft in genau 2 Absätzen. Trenne die Absätze durch eine Leerzeile. Keine Überschriften und kein weiterer Text.
    ...    paragraph_count    2

German Prompt German Response Single Word
    [Documentation]    German prompt asking for a one-word answer.
    Run Multilingual IFEval Test
    ...    Was ist die Hauptstadt von Deutschland? Antworte mit einem einzigen Wort. Keine Satzzeichen und keine Erklärung.
    ...    word_count    1
