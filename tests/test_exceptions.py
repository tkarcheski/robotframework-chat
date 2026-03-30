"""Tests for rfc.exceptions — RFCSkipError hierarchy."""

from rfc.exceptions import (
    DockerNotAvailableError,
    EmptyLLMResponseError,
    MissingDependencyError,
    MissingEnvironmentError,
    MissingProviderConfigError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    PortAllocationError,
    RFCSkipError,
)


class TestRFCSkipError:
    def test_robot_skip_attribute(self) -> None:
        assert RFCSkipError.ROBOT_SKIP is True

    def test_is_exception(self) -> None:
        assert issubclass(RFCSkipError, Exception)


class TestOllamaModelNotFoundError:
    def test_inherits_skip(self) -> None:
        assert issubclass(OllamaModelNotFoundError, RFCSkipError)
        assert OllamaModelNotFoundError.ROBOT_SKIP is True

    def test_attributes(self) -> None:
        exc = OllamaModelNotFoundError("phi4:14b", "http://localhost:11434")
        assert exc.model == "phi4:14b"
        assert exc.endpoint == "http://localhost:11434"
        assert "ollama pull phi4:14b" in str(exc)

    def test_with_detail(self) -> None:
        exc = OllamaModelNotFoundError(
            "phi4:14b", "http://localhost:11434",
            detail="model 'phi4:14b' not found, try pulling it first",
        )
        assert "try pulling it first" in str(exc)


class TestOllamaTimeoutError:
    def test_inherits_skip(self) -> None:
        assert issubclass(OllamaTimeoutError, RFCSkipError)
        assert OllamaTimeoutError.ROBOT_SKIP is True

    def test_attributes(self) -> None:
        exc = OllamaTimeoutError(elapsed=120, models=["llama3"])
        assert exc.elapsed == 120
        assert exc.models == ["llama3"]
        assert "120" in str(exc)
        assert "llama3" in str(exc)


class TestEmptyLLMResponseError:
    def test_inherits_skip(self) -> None:
        assert issubclass(EmptyLLMResponseError, RFCSkipError)
        assert EmptyLLMResponseError.ROBOT_SKIP is True

    def test_attributes(self) -> None:
        exc = EmptyLLMResponseError(model="phi4:14b", prompt_snippet="Tell me a joke")
        assert exc.model == "phi4:14b"
        assert exc.prompt_snippet == "Tell me a joke"
        assert "phi4:14b" in str(exc)
        assert "empty response" in str(exc).lower()

    def test_without_snippet(self) -> None:
        exc = EmptyLLMResponseError(model="llama3")
        assert exc.model == "llama3"
        assert exc.prompt_snippet == ""
        assert "llama3" in str(exc)


class TestDockerNotAvailableError:
    def test_inherits_skip(self) -> None:
        assert issubclass(DockerNotAvailableError, RFCSkipError)
        assert DockerNotAvailableError.ROBOT_SKIP is True

    def test_message(self) -> None:
        exc = DockerNotAvailableError()
        assert "Docker" in str(exc)


class TestPortAllocationError:
    def test_inherits_skip(self) -> None:
        assert issubclass(PortAllocationError, RFCSkipError)
        assert PortAllocationError.ROBOT_SKIP is True

    def test_attributes(self) -> None:
        exc = PortAllocationError(start_port=11434, end_port=11500)
        assert exc.start_port == 11434
        assert exc.end_port == 11500
        assert "11434" in str(exc)
        assert "11500" in str(exc)


class TestMissingDependencyError:
    def test_inherits_skip(self) -> None:
        assert issubclass(MissingDependencyError, RFCSkipError)
        assert MissingDependencyError.ROBOT_SKIP is True

    def test_attributes(self) -> None:
        exc = MissingDependencyError(
            package="datasets",
            install_hint="uv pip install 'robotframework-chat[swebench]'",
        )
        assert exc.package == "datasets"
        assert "datasets" in str(exc)
        assert "uv pip install" in str(exc)


class TestMissingEnvironmentError:
    def test_inherits_skip(self) -> None:
        assert issubclass(MissingEnvironmentError, RFCSkipError)
        assert MissingEnvironmentError.ROBOT_SKIP is True

    def test_attributes(self) -> None:
        exc = MissingEnvironmentError(variable="DATABASE_URL")
        assert exc.variable == "DATABASE_URL"
        assert "DATABASE_URL" in str(exc)


class TestMissingProviderConfigError:
    def test_inherits_skip(self) -> None:
        assert issubclass(MissingProviderConfigError, RFCSkipError)
        assert MissingProviderConfigError.ROBOT_SKIP is True

    def test_attributes(self) -> None:
        exc = MissingProviderConfigError(provider="openai", variable="OPENAI_API_KEY")
        assert exc.provider == "openai"
        assert exc.variable == "OPENAI_API_KEY"
        assert "OPENAI_API_KEY" in str(exc)
