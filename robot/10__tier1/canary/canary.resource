*** Settings ***
Documentation     Shared keywords for the deterministic canary-degradation logic
...               suite. Imports only the pure engine surface
...               (``rfc.canary.CanaryEngineKeywords``) — no LLM, no harness — so
...               the suite is honestly ``axis:none`` and always green in CI.

Library           rfc.canary.CanaryEngineKeywords
Library           Collections
