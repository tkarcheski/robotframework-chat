*** Settings ***
Documentation     Spanish-language instruction-following tests.
...
...               Each test issues a Spanish-language prompt and verifies a
...               structural constraint on the response with a deterministic
...               Python checker.  No LLM judge is involved.

Resource          ../multilingual.resource

Default Tags      multilingual    spanish    regression    tier:1    verify:python

Test Timeout      100 minutes
Test Tags         axis:model

*** Test Cases ***
Spanish Prompt Spanish Response Word Count
    [Documentation]    Spanish instruction asking for a 15-word Spanish reply.
    Run Multilingual IFEval Test
    ...    Describe el mar en exactamente 15 palabras. No escribas más ni menos. No incluyas ningún otro texto.
    ...    word_count    15

Spanish Prompt Spanish Response Bullet Points
    [Documentation]    Spanish prompt requesting exactly 4 bullet points in Spanish.
    Run Multilingual IFEval Test
    ...    Enumera 4 frutas tropicales. Usa solo viñetas (empezando con -). Escribe exactamente 4 viñetas y nada más.
    ...    bullet_points    4

Spanish Prompt Spanish Response Numbered List
    [Documentation]    Spanish prompt asking for a numbered list 1..5.
    Run Multilingual IFEval Test
    ...    Lista cinco colores primarios y secundarios. Numera cada elemento del 1 al 5 con el formato "N. elemento". Escribe solo la lista numerada.
    ...    numbered_list    5

Spanish Prompt English Response Sentence Count
    [Documentation]    Spanish instruction, response in English — tests cross-lingual instruction following.
    Run Multilingual IFEval Test
    ...    Responde en inglés. Describe la fotosíntesis en exactamente 3 oraciones. Termina cada oración con un punto. No incluyas otro texto.
    ...    sentence_count    3

Spanish Prompt English Response Ends With Word
    [Documentation]    Spanish prompt instructing English response that ends with FIN.
    Run Multilingual IFEval Test
    ...    Responde en inglés. Describe brevemente un atardecer en 2 o 3 oraciones. La última palabra de tu respuesta debe ser FIN.
    ...    ends_with_word    FIN

Spanish Prompt Spanish Response Paragraph Count
    [Documentation]    Spanish prompt requiring exactly 2 Spanish paragraphs.
    Run Multilingual IFEval Test
    ...    Explica la gravedad en exactamente 2 párrafos. Separa los párrafos con una línea en blanco. No agregues encabezados ni texto adicional.
    ...    paragraph_count    2

Spanish Prompt Spanish Response Single Word
    [Documentation]    Spanish prompt asking for a one-word answer.
    Run Multilingual IFEval Test
    ...    ¿Cuál es la capital de España? Responde con una sola palabra. Sin puntuación ni explicación.
    ...    word_count    1
