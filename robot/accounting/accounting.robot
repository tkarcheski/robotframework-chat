*** Settings ***
Documentation     Applied accounting and financial math skill measurements.
Resource          ../resources/ask_and_validate.resource

*** Test Cases ***
IQ 100 Profit Or Loss
    [Documentation]    Can the LLM calculate profit or loss given revenue={revenue} and costs={cost}?
    [Tags]    IQ:100    tier:2    verify:llm
    ${revenue}=    Generate Positive Integer    min=1000    max=100000
    ${cost}=       Generate Positive Integer    min=1000    max=100000
    ${question}=   Set Variable    A business has revenue of ${revenue} and costs of ${cost}. What is the profit or loss? Give only the numeric answer.
    ${expected}=   Evaluate    ${revenue} - ${cost}
    Ask And Validate    ${question}    ${expected}

IQ 115 Profit Margin Percentage
    [Documentation]    Can the LLM compute profit margin percentage from revenue={revenue} and cost={cost}?
    [Tags]    IQ:115    tier:2    verify:llm
    ${revenue}=    Generate Positive Integer    min=5000    max=100000
    ${cost_pct}=   Generate Positive Integer    min=30    max=90
    ${cost}=       Evaluate    int(${revenue} * ${cost_pct} / 100)
    ${question}=   Set Variable    Revenue is ${revenue} and cost is ${cost}. What is the profit margin as a percentage? Round to 2 decimal places.
    ${expected}=   Evaluate    round((${revenue} - ${cost}) / ${revenue} * 100, 2)
    Ask And Validate    ${question}    ${expected}

IQ 110 Markup Calculation
    [Documentation]    Can the LLM calculate selling price with a {markup}% markup on cost={cost}?
    [Tags]    IQ:110    tier:2    verify:llm
    ${cost}=       Generate Positive Integer    min=100    max=10000
    ${markup}=     Generate Random Percent
    ${question}=   Set Variable    An item costs ${cost} to produce. With a ${markup}% markup, what is the selling price? Give only the numeric answer.
    ${expected}=   Evaluate    ${cost} * (1 + ${markup} / 100)
    Ask And Validate    ${question}    ${expected}

IQ 100 Sales Tax Total
    [Documentation]    Can the LLM calculate total price including {tax}% sales tax on {price}?
    [Tags]    IQ:100    tier:2    verify:llm
    ${price}=      Generate Positive Integer    min=1    max=5000
    ${tax}=        Generate Positive Integer    min=1    max=15
    ${question}=   Set Variable    An item costs ${price}. The sales tax rate is ${tax}%. What is the total price including tax? Round to 2 decimal places.
    ${expected}=   Evaluate    round(${price} * (1 + ${tax} / 100), 2)
    Ask And Validate    ${question}    ${expected}

IQ 115 Simple Interest
    [Documentation]    Can the LLM compute simple interest on principal={principal} at {rate}% for {years} years?
    [Tags]    IQ:115    tier:2    verify:llm
    ${principal}=    Generate Positive Integer    min=1000    max=100000
    ${rate}=         Generate Positive Integer    min=1    max=20
    ${years}=        Generate Small Positive Integer    min=1    max=10
    ${question}=     Set Variable    Calculate the simple interest on a principal of ${principal} at ${rate}% per year for ${years} years. Give only the numeric answer.
    ${expected}=     Evaluate    ${principal} * ${rate} / 100 * ${years}
    Ask And Validate    ${question}    ${expected}

IQ 130 Compound Interest Final Amount
    [Documentation]    Can the LLM compute compound interest on principal={principal} at {rate}% for {years} years?
    [Tags]    IQ:130    tier:2    verify:llm
    ${principal}=    Generate Positive Integer    min=1000    max=50000
    ${rate}=         Generate Positive Integer    min=1    max=15
    ${years}=        Generate Small Positive Integer    min=1    max=5
    ${question}=     Set Variable    What is the total amount after ${years} years if ${principal} is invested at ${rate}% annual interest compounded annually? Round to 2 decimal places.
    ${expected}=     Evaluate    round(${principal} * (1 + ${rate} / 100) ** ${years}, 2)
    Ask And Validate    ${question}    ${expected}

IQ 115 Straight Line Depreciation
    [Documentation]    Can the LLM calculate straight-line depreciation (cost={asset_cost}, salvage={salvage}, life={life} years)?
    [Tags]    IQ:115    tier:2    verify:llm
    ${asset_cost}=    Generate Positive Integer    min=5000    max=100000
    ${salvage}=       Generate Positive Integer    min=500    max=4999
    ${life}=          Generate Small Positive Integer    min=3    max=20
    ${question}=      Set Variable    An asset costs ${asset_cost}, has a salvage value of ${salvage}, and a useful life of ${life} years. What is the annual straight-line depreciation? Give only the numeric answer.
    ${expected}=      Evaluate    (${asset_cost} - ${salvage}) / ${life}
    Ask And Validate    ${question}    ${expected}

IQ 125 Break Even Quantity
    [Documentation]    Can the LLM calculate break-even quantity (fixed={fixed}, price={price}, variable cost={var_cost})?
    [Tags]    IQ:125    tier:2    verify:llm
    ${fixed}=        Generate Positive Integer    min=1000    max=50000
    ${price}=        Generate Positive Integer    min=50    max=500
    ${var_cost}=     Generate Positive Integer    min=5    max=49
    ${question}=     Set Variable    Fixed costs are ${fixed}. Each unit sells for ${price} and has a variable cost of ${var_cost}. How many units must be sold to break even? Round up to the nearest whole number.
    ${expected}=     Evaluate    math.ceil(${fixed} / (${price} - ${var_cost}))    modules=math
    Ask And Validate    ${question}    ${expected}

IQ 100 Balance Sheet Equity
    [Documentation]    Can the LLM calculate owner's equity from total assets={assets} and liabilities={liabilities}?
    [Tags]    IQ:100    tier:2    verify:llm
    ${assets}=       Generate Positive Integer    min=10000    max=500000
    ${liabilities}=  Generate Positive Integer    min=5000    max=9999
    ${question}=     Set Variable    A company has total assets of ${assets} and total liabilities of ${liabilities}. What is the owner's equity? Give only the numeric answer.
    ${expected}=     Evaluate    ${assets} - ${liabilities}
    Ask And Validate    ${question}    ${expected}

IQ 100 Revenue From Units
    [Documentation]    Can the LLM calculate total revenue from {qty} units at {unit_price} each?
    [Tags]    IQ:100    tier:2    verify:llm
    ${qty}=          Generate Positive Integer    min=10    max=1000
    ${unit_price}=   Generate Positive Integer    min=5    max=500
    ${question}=     Set Variable    A company sells ${qty} units at ${unit_price} each. What is the total revenue? Give only the numeric answer.
    ${expected}=     Evaluate    ${qty} * ${unit_price}
    Ask And Validate    ${question}    ${expected}

IQ 140 Present Value
    [Documentation]    Can the LLM compute present value of {fv} at {rate}% discount over {years} years?
    [Tags]    IQ:140    tier:2    verify:llm
    ${fv}=           Generate Positive Integer    min=1000    max=100000
    ${rate}=         Generate Positive Integer    min=1    max=15
    ${years}=        Generate Small Positive Integer    min=1    max=10
    ${question}=     Set Variable    What is the present value of ${fv} to be received in ${years} years at a discount rate of ${rate}%? Round to 2 decimal places.
    ${expected}=     Evaluate    round(${fv} / (1 + ${rate} / 100) ** ${years}, 2)
    Ask And Validate    ${question}    ${expected}

IQ 110 Gross Margin
    [Documentation]    Can the LLM calculate gross margin from revenue={revenue} and COGS={cogs}?
    [Tags]    IQ:110    tier:2    verify:llm
    ${revenue}=      Generate Positive Integer    min=10000    max=500000
    ${cogs_pct}=     Generate Positive Integer    min=20    max=80
    ${cogs}=         Evaluate    int(${revenue} * ${cogs_pct} / 100)
    ${question}=     Set Variable    Revenue is ${revenue} and cost of goods sold is ${cogs}. What is the gross margin? Give only the numeric answer.
    ${expected}=     Evaluate    ${revenue} - ${cogs}
    Ask And Validate    ${question}    ${expected}
