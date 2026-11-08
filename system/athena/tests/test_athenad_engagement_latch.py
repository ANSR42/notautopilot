import ast
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INSTALLED = "46c84f7dd06614dd50681d8f9dc2f389d0829941"
RESTORED = (
    "system/sentry.py",
    "system/manager/process.py",
    "system/athena/manage_athenad.py",
)
ATHENA_TRACE = """\
Traceback (most recent call last):
  File "/data/openpilot/system/athena/athenad.py", line 30, in <module>
    from jsonrpc import JSONRPCResponseManager, dispatcher
ModuleNotFoundError: No module named 'jsonrpc'
"""
CONTROL_TRACE = "controlsd failed\n" + ("x\n" * 12) + "final line\n"


def _installed_bytes(rel: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{INSTALLED}:{rel}"], cwd=ROOT)


def _function_source(text: str, name: str) -> str:
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(text, node)
            assert segment is not None
            return segment
    raise AssertionError(name)


def test_latch_sources_match_installed_46c84f7():
    for rel in RESTORED:
        assert (ROOT / rel).read_bytes() == _installed_bytes(rel)
    assert not (ROOT / "system/error_log_files.py").exists()
    assert not (ROOT / "system/athena/crash_policy.py").exists()


def test_capture_exception_and_save_exception_match_installed_text():
    current = (ROOT / "system/sentry.py").read_text(encoding="utf-8")
    installed = _installed_bytes("system/sentry.py").decode("utf-8")
    for name in ("capture_exception", "save_exception"):
        assert _function_source(current, name) == _function_source(installed, name)
    assert "latch_engagement" not in current


def _reference_write(directory: Path, exc_text: str, crash_log: bool, stamp: str) -> None:
    files = [directory / stamp, directory / "error.txt"]
    for file_path in files:
        if file_path.name == "error.txt" and crash_log:
            file_path.write_text("\n".join(exc_text.splitlines()[-10:]))
        else:
            file_path.write_text(exc_text)


def _run_save_exception(directory: Path, exc_text: str, crash_log: bool) -> None:
    source = _function_source((ROOT / "system/sentry.py").read_text(encoding="utf-8"), "save_exception")
    namespace = {"datetime": datetime, "ERROR_LOGS_PATH": directory}
    exec(source, namespace)
    namespace["save_exception"](exc_text, crash_log)


def test_control_and_athena_crashes_still_write_the_same_latch(tmp_path: Path):
    for label, exc_text in (("athena", ATHENA_TRACE), ("control", CONTROL_TRACE)):
        live = tmp_path / label / "live"
        reference = tmp_path / label / "reference"
        live.mkdir(parents=True)
        reference.mkdir()
        _run_save_exception(live, exc_text, True)
        stamped = [path for path in live.iterdir() if path.name != "error.txt"]
        assert len(stamped) == 1
        _reference_write(reference, exc_text, True, stamped[0].name)
        assert (live / "error.txt").read_bytes() == (reference / "error.txt").read_bytes()
        assert stamped[0].read_bytes() == (reference / stamped[0].name).read_bytes()
        assert (live / "error.txt").read_bytes()
