*** Settings ***
Name              Superset Connectivity
Documentation     Superset/PostgreSQL connectivity and host registration suite.
...
...               Verifies the database connection, pushes host info, and
...               validates that the data pipeline tables exist with data.
...               No LLM required — this is a pure infrastructure check.
Test Tags         superset    tier:0    verify:robot
