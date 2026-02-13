# Agent Skills and Capabilities

This document outlines the capabilities and skills of the AI agent working on robotframework-chat.

## Core Capabilities

### 1. Software Development

**Languages:**
- Python (3.11+)
- Robot Framework
- YAML
- Shell scripting
- GitLab CI/CD configuration

**Development Practices:**
- Test-driven development (TDD)
- Type hints and static analysis
- Code formatting with ruff
- Pre-commit hooks
- Documentation-driven development

### 2. Git and Version Control

**Git Operations:**
- Branch creation and management
- Commit with conventional commit messages
- Rebasing and merging
- Conflict resolution
- Tagging and releases

**Pull Request Workflow:**
- Create feature branches from main
- Push branches to remote: `git push origin feature-name`
- Create PRs/MRs with descriptive titles and bodies
- Monitor PRs for feedback and respond promptly
- Address review comments with additional commits
- Update PR descriptions if scope changes
- Only merge after approval and all checks pass

### 3. Continuous Integration/Deployment

**GitLab CI/CD:**
- Pipeline configuration (.gitlab-ci.yml)
- Multi-stage pipelines (lint, test, deploy)
- Artifact collection and management
- GitLab Pages integration
- Runner configuration and tagging
- CI/CD variable management

**Testing in CI:**
- Pre-commit hooks enforcement
- Unit and integration testing
- Robot Framework test execution
- Code quality checks (ruff, mypy)
- Test result artifact collection

### 4. LLM and AI Testing

**Model Management:**
- Ollama integration
- Model metadata research (Playwright)
- Dynamic test configuration based on available models
- Model performance tracking
- Release date tracking

**Test Patterns:**
- Math and reasoning tests (IQ:100-160)
- Code generation tests
- Safety and prompt injection tests
- Docker-based execution tests
- Multi-model comparison

### 5. Documentation

**Documentation Types:**
- README and setup guides
- API documentation
- Architecture decision records
- CI/CD setup guides
- Agent instructions (AGENTS.md, SKILLS.md)

**Documentation Standards:**
- Clear, concise language
- Code examples
- Step-by-step instructions
- Troubleshooting sections

### 6. DevOps and Infrastructure

**Docker:**
- Container configuration
- Image management
- Docker-in-Docker (DinD) setup
- Volume and network management
- Resource constraints

**Infrastructure:**
- GitLab runner setup
- Ollama deployment
- Environment configuration
- Secret management

## Workflow Standards

### When Starting Work

1. Read AGENTS.md and SKILLS.md
2. Understand project structure and conventions
3. Check for existing issues or PRs
4. Create feature branch: `git checkout -b feature/description`

### During Development

1. Follow TDD: write failing test first
2. Implement minimal code to pass
3. Refactor if needed
4. Run pre-commit hooks: `pre-commit run --all-files`
5. Commit with proper type: `<type>: <summary>`

### Before Completing

1. Ensure all tests pass
2. Run linting and type checking
3. Update documentation if needed
4. Push to remote: `git push origin feature-name`
5. Create PR/MR with comprehensive description
6. Monitor for feedback

### After PR Creation

1. Check CI pipeline status
2. Respond to review comments promptly
3. Make requested changes in new commits
4. Update PR description if scope changes
5. Ensure all checks pass before requesting merge

## Tools and Technologies

**Development Tools:**
- `uv` - Python package management
- `ruff` - Linting and formatting
- `mypy` - Type checking
- `pre-commit` - Git hooks
- `pytest` - Unit testing
- `robotframework` - Integration testing

**CI/CD Tools:**
- GitLab CI/CD
- GitLab Runner
- GitLab Pages
- Ollama
- Docker

**Monitoring Tools:**
- GitLab CI pipeline dashboard
- Test result artifacts
- Robot Framework reports
- CI metadata collection

## Communication

**Status Updates:**
- Provide progress updates during long tasks
- Report blockers immediately
- Summarize completed work
- Note any deviations from plan

**Code Reviews:**
- Explain reasoning for implementation choices
- Address feedback constructively
- Ask clarifying questions when needed
- Acknowledge suggestions

## Limitations

The agent:
- Cannot access external URLs not provided by the user
- Cannot install system packages without user approval
- Cannot execute destructive commands without confirmation
- Cannot access private repositories without credentials
- Cannot make assumptions about undocumented requirements

## Best Practices

1. **Always commit after significant progress**
2. **Always push to remote and create PR when feature is complete**
3. **Always monitor PR for feedback**
4. **Always run pre-commit before committing**
5. **Always update documentation for new features**
6. **Always test changes locally before pushing**
7. **Always verify CI pipeline passes**

## Learning Resources

**Robot Framework:**
- [Robot Framework User Guide](https://robotframework.org/robotframework/latest/RobotFrameworkUserGuide.html)
- [Robot Framework Library Documentation](https://robotframework.org/robotframework/latest/libraries.html)

**GitLab CI/CD:**
- [GitLab CI/CD Documentation](https://docs.gitlab.com/ee/ci/)
- [GitLab Runner Documentation](https://docs.gitlab.com/runner/)

**Ollama:**
- [Ollama GitHub Repository](https://github.com/ollama/ollama)
- [Ollama API Documentation](https://github.com/ollama/ollama/blob/main/docs/api.md)

## Contact and Support

For issues or questions:
- Check existing documentation
- Review AGENTS.md for project-specific rules
- Consult project maintainers
- Open an issue in the repository
