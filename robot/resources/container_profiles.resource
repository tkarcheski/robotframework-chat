*** Settings ***
Documentation     Reusable container configuration profiles for Docker-based testing
Library           rfc.docker_keywords.ConfigurableDockerKeywords    WITH NAME    Docker

*** Variables ***
# Resource Profiles - Define resource constraints
&{MINIMAL}          image=python:3.11-alpine    command=sleep infinity    cpu_cores=0.25    memory_mb=128    scratch_mb=64     network_mode=none    read_only=True
&{STANDARD}         image=python:3.11-slim      command=sleep infinity    cpu_cores=0.5     memory_mb=512    scratch_mb=256    network_mode=none    read_only=True
&{PERFORMANCE}      image=python:3.11-slim      command=sleep infinity    cpu_cores=1.0     memory_mb=1024   scratch_mb=512    network_mode=none    read_only=True
&{NETWORKED}        image=python:3.11-slim      command=sleep infinity    cpu_cores=0.5     memory_mb=512    scratch_mb=256    network_mode=bridge  read_only=True

# Language-specific profiles
&{PYTHON_MINIMAL}   image=python:3.11-alpine    command=sleep infinity    cpu_cores=0.25    memory_mb=128    scratch_mb=64     network_mode=none    read_only=True    user=nobody
&{PYTHON_STANDARD}  image=python:3.11-slim      command=sleep infinity    cpu_cores=0.5     memory_mb=512    scratch_mb=256    network_mode=none    read_only=True    user=nobody
&{PYTHON_PERF}      image=python:3.11-slim      command=sleep infinity    cpu_cores=2.0     memory_mb=2048   scratch_mb=1024   network_mode=none    read_only=True    user=nobody
&{NODE_STANDARD}    image=node:18-alpine        command=sleep infinity    cpu_cores=0.5     memory_mb=512    scratch_mb=256    network_mode=none    read_only=True    user=node
&{ALPINE_SHELL}     image=alpine:latest         command=sleep infinity    cpu_cores=0.25    memory_mb=128    scratch_mb=64     network_mode=none    read_only=True    user=nobody
&{UBUNTU_DEV}       image=ubuntu:22.04          command=sleep infinity    cpu_cores=0.5     memory_mb=1024   scratch_mb=512    network_mode=none    read_only=False   user=root

# LLM Container Profiles (Ollama) - ports are assigned dynamically
&{OLLAMA_CPU}       image=ollama/ollama:latest    cpu_cores=2.0     memory_mb=4096    scratch_mb=1024   network_mode=bridge    read_only=False    user=root
&{OLLAMA_GPU}       image=ollama/ollama:latest    cpu_cores=4.0     memory_mb=8192    scratch_mb=2048   network_mode=bridge    read_only=False    user=root

# Default timeouts
${DEFAULT_TIMEOUT}      30
${LLM_TIMEOUT}          120
${LONG_TIMEOUT}         300

*** Keywords ***
Create Container From Profile
    [Documentation]    Create a Docker container using a predefined profile
    [Arguments]    ${profile_name}    ${container_name}=None    ${custom_volumes}=None
    ${profile}=    Get Variable Value    ${${profile_name}}
    ${container_id}=    Docker.Create Configurable Container    ${profile}    ${container_name}
    RETURN    ${container_id}

Apply Resource Constraints
    [Documentation]    Update resource limits on a running container
    [Arguments]    ${container_id}    &{resources}
    Docker.Update Container Resources    ${container_id}    ${resources}

Verify Docker Available
    [Documentation]    Verify Docker daemon is accessible
    ${available}=    Docker.Docker Is Available
    Should Be True    ${available}    Docker is not available. Please ensure Docker is installed and running.
    Log    Docker daemon is available
