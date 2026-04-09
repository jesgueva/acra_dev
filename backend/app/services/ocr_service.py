"""OCR Service — Full preprocessing pipeline for BOL document extraction.

Pipeline: grayscale → Gaussian blur → Otsu binarization → deskew → 2x upscale
          → pytesseract (eng+spa, --psm 6) → regex field extraction → confidence score
"""

from __future__ import annotations

import io
import re
from typing import Optional

import cv2
import numpy as np
import pytesseract
from PIL import Image

from app.schemas.delivery import OCRItemResult, OCRResponse

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "application/pdf"}


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def _deskew(binary: np.ndarray) -> np.ndarray:
    """Rotate image to correct skew using minAreaRect on non-zero pixels."""
    coords = np.column_stack(np.where(binary > 0)).astype(np.float32)
    if len(coords) < 10:
        return binary
    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.5:
        return binary
    h, w = binary.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        binary, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def preprocess(pil_image: Image.Image) -> Image.Image:
    """Apply full preprocessing pipeline to a PIL image."""
    arr = np.array(pil_image.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    deskewed = _deskew(binary)
    h, w = deskewed.shape
    upscaled = cv2.resize(deskewed, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
    return Image.fromarray(upscaled)


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def _match(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[str]:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _extract_items(text: str) -> list[OCRItemResult]:
    item_re = re.compile(
        r"([A-Za-z][^\n\r]{2,40}?)\s+(\d+(?:\.\d+)?)\s*(?:units?|kg|lbs?|pcs?|pieces?)",
        re.IGNORECASE,
    )
    lot_re = re.compile(r"(?:lot|batch)\s*[#:\s]+([A-Z0-9\-]+)", re.IGNORECASE)
    lots = lot_re.findall(text)
    items: list[OCRItemResult] = []
    for i, m in enumerate(item_re.finditer(text)):
        items.append(
            OCRItemResult(
                material_type=m.group(1).strip(),
                quantity=float(m.group(2)),
                lot_batch_number=lots[i] if i < len(lots) else None,
            )
        )
    return items


def _extract_fields(text: str) -> OCRResponse:
    """Extract BOL header fields and line items from raw OCR text."""
    supplier = _match(r"(?:supplier|shipper|from)[:\s]+([^\n\r]+)", text)
    carrier = _match(r"(?:carrier|transported by|trucking)[:\s]+([^\n\r]+)", text)
    bol_reference = _match(r"\bBOL\s*[#:]+\s*([A-Z0-9\-]+)", text)
    delivery_date = _match(r"\b(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b", text)

    items = _extract_items(text)
    filled = sum(1 for v in [supplier, carrier, bol_reference, delivery_date] if v)
    confidence = round(filled / 4.0, 2)

    return OCRResponse(
        supplier=supplier,
        carrier=carrier,
        bol_reference=bol_reference,
        delivery_date=delivery_date,
        items=items,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _load_images(file_bytes: bytes, content_type: str) -> list[Image.Image]:
    if content_type == "application/pdf":
        from pdf2image import convert_from_bytes  # requires poppler-utils on host
        return convert_from_bytes(file_bytes)
    return [Image.open(io.BytesIO(file_bytes))]


def process_image_bytes(file_bytes: bytes, content_type: str) -> OCRResponse:
    """Run the full OCR pipeline on raw file bytes.

    Returns an OCRResponse with confidence=0.0 if extraction fails.
    """
    images = _load_images(file_bytes, content_type)
    if not images:
        return OCRResponse(confidence=0.0)

    processed = preprocess(images[0])
    text = pytesseract.image_to_string(processed, lang="eng+spa", config="--psm 6")
    if not text.strip():
        return OCRResponse(confidence=0.0)

    return _extract_fields(text)
