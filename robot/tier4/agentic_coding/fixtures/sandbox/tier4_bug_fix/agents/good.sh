#!/bin/sh
# Scripted stand-in for a live coding agent (#288): fixes the subtract bug
# and touches nothing else.
set -e
sed -i 's/return a + b  # BUG: should be a - b/return a - b/' calculator.py
