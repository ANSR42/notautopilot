"""speed_limit_vision imports cv2. The aarch64 wheel must be what that import finds."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
THIRD = ROOT / "starpilot" / "third_party"
ABI3 = THIRD / "cv2" / "cv2.abi3.so"
INIT = THIRD / "cv2" / "__init__.py"


def test_speed_limit_vision_still_imports_cv2():
    text = (ROOT / "starpilot" / "system" / "speed_limit_vision.py").read_text(encoding="utf-8")
    assert text.splitlines()[12] == "import cv2"


def test_vendored_extension_is_the_locked_aarch64_wheel_member():
    assert ABI3.stat().st_size == 31475073
    info = subprocess.run(["file", str(ABI3)], check=True, capture_output=True, text=True).stdout
    assert "ARM aarch64" in info
    dynamic = subprocess.run(["readelf", "-d", str(ABI3)], check=True, capture_output=True, text=True).stdout
    assert "$ORIGIN/../opencv_python_headless.libs" in dynamic
    for soname in (
        "libz.so.1",
        "libstdc++.so.6",
        "libgcc_s.so.1",
        "libc.so.6",
        "libpng16-0090a4c3.so.16.44.0",
        "libopenblas-r0-8966572e.3.3.so",
    ):
        assert soname in dynamic
    assert (THIRD / "opencv_python_headless.libs" / "libpng16-0090a4c3.so.16.44.0").is_file()


def test_pythonpath_finds_this_cv2_package():
    script = r"""
import importlib.util
import sys
sys.path.insert(0, sys.argv[1])
spec = importlib.util.find_spec("cv2")
assert spec is not None and spec.origin and spec.origin.endswith("starpilot/third_party/cv2/__init__.py"), spec
try:
    import cv2
except ImportError as exc:
    # This host is not aarch64. A missing package would be ModuleNotFoundError.
    assert type(exc) is ImportError
    assert "No module named" not in str(exc)
    assert "cv2.abi3.so" in str(exc)
else:
    assert "starpilot/third_party/cv2" in cv2.__file__
"""
    subprocess.run([sys.executable, "-c", script, str(THIRD)], check=True)
    assert INIT.is_file()
