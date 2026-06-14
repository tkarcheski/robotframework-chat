"""Tests for rfc.output_xml — output XML resolution and compression helpers."""

import gzip
import os
from unittest.mock import patch

from rfc.output_xml import (
    build_output_xml_source,
    build_output_xml_url,
    format_size,
    read_and_compress_output_xml,
    resolve_output_dir,
    resolve_output_file,
)


# ---------------------------------------------------------------------------
# resolve_output_dir
# ---------------------------------------------------------------------------


class TestResolveOutputDir:
    def test_returns_env_var_when_set(self) -> None:
        with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": "/explicit/path"}):
            assert resolve_output_dir() == "/explicit/path"

    def test_returns_robot_variable_when_env_not_set(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROBOT_OUTPUT_DIR", None)
            with patch("rfc.output_xml.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.return_value = (
                    "/robot/output"
                )
                assert resolve_output_dir() == "/robot/output"

    def test_returns_empty_when_neither_available(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROBOT_OUTPUT_DIR", None)
            with patch("rfc.output_xml.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.return_value = None
                assert resolve_output_dir() == ""

    def test_returns_empty_when_builtin_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROBOT_OUTPUT_DIR", None)
            with patch("rfc.output_xml.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.side_effect = (
                    RuntimeError("not in robot")
                )
                assert resolve_output_dir() == ""

    def test_env_var_takes_precedence_over_robot_variable(self) -> None:
        with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": "/from/env"}):
            with patch("rfc.output_xml.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.return_value = (
                    "/from/robot"
                )
                assert resolve_output_dir() == "/from/env"


# ---------------------------------------------------------------------------
# resolve_output_file
# ---------------------------------------------------------------------------


class TestResolveOutputFile:
    def test_returns_env_var_path_when_set(self) -> None:
        with patch.dict(os.environ, {"ROBOT_OUTPUT_DIR": "/explicit/path"}):
            result = resolve_output_file()
        assert result == "/explicit/path/output.xml"

    def test_returns_robot_output_file_variable(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROBOT_OUTPUT_DIR", None)
            with patch("rfc.output_xml.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.return_value = (
                    "/robot/results/custom_output.xml"
                )
                assert resolve_output_file() == "/robot/results/custom_output.xml"

    def test_returns_empty_when_output_none(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROBOT_OUTPUT_DIR", None)
            with patch("rfc.output_xml.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.return_value = "NONE"
                assert resolve_output_file() == ""

    def test_returns_empty_when_neither_available(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROBOT_OUTPUT_DIR", None)
            with patch("rfc.output_xml.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.return_value = None
                assert resolve_output_file() == ""

    def test_returns_empty_when_builtin_raises(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ROBOT_OUTPUT_DIR", None)
            with patch("rfc.output_xml.BuiltIn") as mock_builtin_cls:
                mock_builtin_cls.return_value.get_variable_value.side_effect = (
                    RuntimeError("not in robot")
                )
                assert resolve_output_file() == ""


# ---------------------------------------------------------------------------
# build_output_xml_url
# ---------------------------------------------------------------------------


class TestBuildOutputXmlUrl:
    def test_from_report_base_url(self) -> None:
        env = {"REPORT_BASE_URL": "https://results.example.com/math"}
        with patch.dict(os.environ, env, clear=False):
            url = build_output_xml_url()
        assert url == "https://results.example.com/math/output.xml"

    def test_empty_when_no_env(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REPORT_BASE_URL", None)
            url = build_output_xml_url()
        assert url == ""


# ---------------------------------------------------------------------------
# build_output_xml_source
# ---------------------------------------------------------------------------


class TestBuildOutputXmlSource:
    def test_returns_path_when_file_exists(self, tmp_path: object) -> None:
        output_xml = tmp_path / "output.xml"  # type: ignore[operator]
        output_xml.write_text("<robot/>")
        with patch(
            "rfc.output_xml.resolve_output_file",
            return_value=str(output_xml),
        ):
            result = build_output_xml_source()
        assert result == os.path.abspath(str(output_xml))

    def test_returns_candidate_when_file_missing(self) -> None:
        with patch(
            "rfc.output_xml.resolve_output_file",
            return_value="/nonexistent/dir/output.xml",
        ):
            result = build_output_xml_source()
        assert result == "/nonexistent/dir/output.xml"

    def test_returns_empty_when_no_output_file(self) -> None:
        with patch("rfc.output_xml.resolve_output_file", return_value=""):
            result = build_output_xml_source()
        assert result == ""


# ---------------------------------------------------------------------------
# read_and_compress_output_xml
# ---------------------------------------------------------------------------


class TestReadAndCompressOutputXml:
    def test_returns_compressed_data_when_file_exists(self, tmp_path: object) -> None:
        output_xml = tmp_path / "output.xml"  # type: ignore[operator]
        output_xml.write_text("<robot/>")
        with patch(
            "rfc.output_xml.resolve_output_file",
            return_value=str(output_xml),
        ):
            result = read_and_compress_output_xml()
        assert len(result) > 0
        assert gzip.decompress(result) == b"<robot/>"

    def test_returns_empty_when_no_output_file(self) -> None:
        with patch("rfc.output_xml.resolve_output_file", return_value=""):
            result = read_and_compress_output_xml()
        assert result == b""

    def test_returns_empty_when_file_missing(self) -> None:
        with patch(
            "rfc.output_xml.resolve_output_file",
            return_value="/nonexistent/dir/output.xml",
        ):
            result = read_and_compress_output_xml()
        assert result == b""

    def test_returns_empty_on_oserror(self, tmp_path: object) -> None:
        output_xml = tmp_path / "output.xml"  # type: ignore[operator]
        output_xml.write_text("<robot/>")

        def _open_raises(*args: object, **kwargs: object) -> None:
            raise OSError("permission denied")

        with (
            patch(
                "rfc.output_xml.resolve_output_file",
                return_value=str(output_xml),
            ),
            patch("builtins.open", _open_raises),
        ):
            result = read_and_compress_output_xml()
        assert result == b""


# ---------------------------------------------------------------------------
# format_size
# ---------------------------------------------------------------------------


class TestFormatSize:
    def test_bytes(self) -> None:
        assert format_size(500) == "500B"

    def test_kilobytes(self) -> None:
        assert "KB" in format_size(5000)

    def test_megabytes(self) -> None:
        assert "MB" in format_size(5_000_000)
