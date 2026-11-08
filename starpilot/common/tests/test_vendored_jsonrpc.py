import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "starpilot" / "third_party" / "jsonrpc"
WHEEL_SHA256 = "4a4668bbbe7116feb4abbd0f54e64a4adcf4b8f648f19ffa0848ad0f6606a9bf"
SDIST_SHA256 = "e6441d56c1dcd54241c937d0a2dcd193bdf0bdc539b5316524713f554b7f85b9"
LICENSE_SHA256 = "65d2a4421f8d862eae81a9ce8ceaf16a264412e849ed654f75606fe5de6e8e4a"
TREE_SHA256 = "21ebc24e2d8cf973d7d1cc57a80c4d9d0b0ae0902e0eacd1f1d0010da7ad7bce"


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "LICENSE" and p.name != "PROVENANCE.txt"):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_vendored_jsonrpc_matches_locked_wheel_bytes():
    provenance = (PACKAGE / "PROVENANCE.txt").read_text(encoding="utf-8")
    assert "json-rpc 1.15.0" in provenance
    assert WHEEL_SHA256 in provenance
    assert SDIST_SHA256 in provenance
    assert "Requires-Dist count: 0" in provenance
    assert hashlib.sha256((PACKAGE / "LICENSE").read_bytes()).hexdigest() == LICENSE_SHA256
    assert _tree_sha256(PACKAGE) == TREE_SHA256
    assert not (PACKAGE / "json_rpc-1.15.0.dist-info").exists()


def test_athenad_startup_import_resolves_without_site_packages():
    result = subprocess.run(
        [sys.executable, "-S", "-c",
         "from jsonrpc import JSONRPCResponseManager, dispatcher\n"
         "import jsonrpc\n"
         "assert jsonrpc.__version__ == '1.15.0'\n"
         "assert JSONRPCResponseManager.__name__ == 'JSONRPCResponseManager'\n"
         "assert dispatcher is not None\n"
         "print(jsonrpc.__file__)"],
        check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(PACKAGE.parent), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert "starpilot/third_party/jsonrpc/__init__.py" in result.stdout.replace("\\", "/")
