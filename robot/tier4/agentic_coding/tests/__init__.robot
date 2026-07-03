*** Settings ***
Name              Sandboxed
Documentation     Tier:4 Docker-sandboxed agentic-coding scenarios (#290).
...
...               Each test seeds a disposable repo into a resource-capped
...               container, runs an agent inside it, and verifies the
...               resulting worktree state. Tests skip cleanly when the
...               Docker daemon is unavailable (DockerNotAvailableError
...               carries ROBOT_SKIP_EXECUTION).

Force Tags        sandbox
