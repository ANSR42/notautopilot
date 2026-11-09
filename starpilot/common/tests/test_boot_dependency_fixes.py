"""Boot failures seen on AGNOS 19.9 after f43dfb09. No driving assertion."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
THIRD = ROOT / "starpilot" / "third_party"
MODELS = ROOT / "starpilot" / "assets" / "vision_models"


def test_pyserial_3_5_resolves_from_third_party_without_site_packages():
    result = subprocess.run(
        [sys.executable, "-S", "-c",
         "import serial\nfrom serial import Serial\n"
         "assert serial.VERSION == '3.5'\n"
         "assert 'starpilot/third_party/serial' in serial.__file__.replace('\\\\','/')\n"
         "print(serial.__file__)"],
        check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(THIRD)},
    )
    assert "starpilot/third_party/serial" in result.stdout.replace("\\", "/")


def test_detector_file_input_is_256_and_640_is_only_the_legacy_file():
    from openpilot.starpilot.system.onnx_input_shape import first_input_dims
    detector = MODELS / "speed_limit_us_detector.onnx"
    assert first_input_dims(detector) == [1, 3, 256, 256]
    assert first_input_dims(MODELS / "speed_limit_us_value_classifier.onnx") == [1, 3, 128, 128]
    assert first_input_dims(MODELS / "speed_limit_vision.onnx") == [1, 3, 640, 640]
    source = (ROOT / "starpilot/system/speed_limit_vision.py").read_text(encoding="utf-8")
    assert "first_input_dims(model_path)" in source
