"""Banner title artwork used as the software start-screen name.

The letters are a crop of the supplied banner, not a font match. The banner
font was not identified, so the pixels are reused instead of a guessed face.
"""

WORDMARK_ASSET = "notautopilot/wordmark.png"
# Inclusive pixel box of NOTAUTOPILOT on source/banner-mike-nov6.jpg.
SOURCE_CROP = (549, 297, 1209, 353)
WORDMARK_NATIVE = (SOURCE_CROP[2] - SOURCE_CROP[0] + 1, SOURCE_CROP[3] - SOURCE_CROP[1] + 1)


def fitted_size(native_w: float, native_h: float, max_w: float, max_h: float) -> tuple[float, float]:
  if native_w <= 0 or native_h <= 0 or max_w <= 0 or max_h <= 0:
    return 0.0, 0.0
  scale = min(max_w / native_w, max_h / native_h)
  return native_w * scale, native_h * scale
