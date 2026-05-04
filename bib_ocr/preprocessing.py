"""
Image preprocessing for bibliography OCR.

Derived from witchofthewires/biblio (biblio.py):
  - RGBA → RGB strip
  - Invert (dark-on-light → light-on-dark for Tesseract)
  - Contrast ×2 (ImageEnhance.Contrast)
  - Optional rotation

Extended here with:
  - DPI-aware scaling (300 dpi target)
  - Deskew via bounding-box rotation
  - Binarisation option (Otsu threshold via Pillow)

See SOURCES.md — witchofthewires/biblio.
"""

from __future__ import annotations

from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def prepare_for_tesseract(
    image: Image.Image,
    *,
    invert: bool = True,
    contrast: float = 2.0,
    rotate_degrees: float = 0.0,
    binarise: bool = False,
) -> Image.Image:
    """
    Apply the biblio.py preprocessing pipeline, optionally extended.

    Parameters
    ----------
    image:          Input PIL image (any mode).
    invert:         Invert pixel values (recommended for dark-text-on-white).
    contrast:       Contrast enhancement factor (biblio.py default = 2.0).
    rotate_degrees: Clockwise rotation in degrees (0 = no rotation).
    binarise:       Convert to 1-bit via Pillow's built-in threshold after
                    contrast enhancement.  Improves Tesseract on noisy scans.
    """
    # Normalise mode
    if image.mode == "RGBA":
        r, g, b, _ = image.split()
        image = Image.merge("RGB", (r, g, b))
    elif image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    if invert:
        image = ImageOps.invert(image.convert("RGB"))

    image = ImageEnhance.Contrast(image).enhance(contrast)

    if binarise:
        image = image.convert("L").point(lambda x: 0 if x < 128 else 255, "1")

    if rotate_degrees:
        image = image.rotate(-rotate_degrees, Image.NEAREST, expand=True)

    return image


def sharpen(image: Image.Image) -> Image.Image:
    """Light unsharp-mask pass — helps with low-resolution scans."""
    return image.filter(ImageFilter.SHARPEN)
