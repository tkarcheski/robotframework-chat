"""Output XML resolution, compression, and URL-building helpers.

Extracted from ``db_listener.py`` so that other listeners or tools
can work with Robot Framework output.xml files without depending on
the database layer.
"""

import gzip
import os

from robot.libraries.BuiltIn import BuiltIn  # type: ignore


def resolve_output_dir() -> str:
    """Resolve the Robot Framework output directory.

    Priority:
    1. ``ROBOT_OUTPUT_DIR`` environment variable (explicit override).
    2. Robot Framework's ``${OUTPUT DIR}`` built-in variable.
    3. Empty string if neither is available.
    """
    env_dir = os.getenv("ROBOT_OUTPUT_DIR")
    if env_dir:
        return env_dir
    try:
        robot_dir = BuiltIn().get_variable_value("${OUTPUT DIR}")
        if robot_dir:
            return str(robot_dir)
    except Exception:
        pass  # Not running inside Robot context
    return ""


def resolve_output_file() -> str:
    """Resolve the full path to Robot Framework's output XML file.

    Priority:
    1. ``ROBOT_OUTPUT_DIR`` env var + ``output.xml`` (backward compatible).
    2. Robot Framework's ``${OUTPUT FILE}`` built-in variable (respects
       ``--output`` flag and ``--output NONE``).
    3. Empty string if neither is available.
    """
    env_dir = os.getenv("ROBOT_OUTPUT_DIR")
    if env_dir:
        return os.path.join(env_dir, "output.xml")
    try:
        output_file = BuiltIn().get_variable_value("${OUTPUT FILE}")
        if output_file and str(output_file).upper() != "NONE":
            return str(output_file)
    except Exception:
        pass  # Not running inside Robot context
    return ""


def read_and_compress_output_xml() -> bytes:
    """Read output.xml from Robot's output directory and gzip-compress it."""
    output_path = resolve_output_file()
    if not output_path:
        return b""
    if not os.path.isfile(output_path):
        return b""
    try:
        with open(output_path, "rb") as f:
            return gzip.compress(f.read())
    except OSError:
        return b""


def build_output_xml_source() -> str:
    """Return the filesystem path to the Robot Framework output.xml.

    This traces the test run back to the original output.xml that was
    produced by Robot Framework, enabling audit and replay.
    """
    output_path = resolve_output_file()
    if output_path:
        if os.path.isfile(output_path):
            return os.path.abspath(output_path)
        return output_path
    return ""


def build_output_xml_url() -> str:
    """Build a URL to the output.xml file from environment variables.

    Only returns proper web URLs. Returns empty string when no web URL
    is available (never stores filesystem paths).

    Priority:
    1. REPORT_BASE_URL — explicit base URL
    """
    base = os.getenv("REPORT_BASE_URL")
    if base:
        return f"{base.rstrip('/')}/output.xml"

    return ""


def format_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
