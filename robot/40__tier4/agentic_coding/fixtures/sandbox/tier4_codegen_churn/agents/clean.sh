#!/bin/sh
# Reference variant: generates codegen_result.py, uses a scratch .build.tmp
# intermediate, then removes it -- net churn is exactly the allowed generated
# output, so the churn budget holds.
set -e
echo 'VERSION=1.0.0' > .build.tmp
printf 'VERSION = "1.0.0"\n' > codegen_result.py
rm -f .build.tmp
