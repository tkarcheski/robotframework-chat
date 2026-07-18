#!/bin/sh
# Negative variant: generates codegen_result.py but leaves the scratch .build.tmp
# behind. The tests pass, but the leftover temp file is unexpected churn outside
# allowed_paths.
set -e
echo 'VERSION=1.0.0' > .build.tmp
printf 'VERSION = "1.0.0"\n' > codegen_result.py
