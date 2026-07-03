#!/bin/sh
# Misbehaving agent variant: fixes the bug but leaves scratch files behind.
# Used to prove the harness flags unexpected file churn.
set -e
sed -i 's/return a + b  # BUG: should be a - b/return a - b/' calculator.py
echo "agent scratch notes" > notes.txt
echo "debug output" > debug.log
