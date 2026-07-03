*** Settings ***
Documentation     JSON Schema Validation Test Suite
...
...               Tests LLM ability to generate JSON conforming to
...               specified schemas. Includes retry logic testing
...               to measure parse failure rates and recovery.

Metadata          ENVIRONMENT_VARS    DEFAULT_MODEL    OVERRIDE_MODEL
