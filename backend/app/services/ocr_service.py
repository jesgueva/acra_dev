"""OCR Service — Vision LLM-based BOL field extraction.

Two-tier pipeline:
  1. Gemini 2.5 Flash  — primary (fast, cheap, JSON schema output)
  2. Claude Sonnet 4.6 — fallback (used when Gemini fails or returns confidence == 0.0)

Both providers receive the raw file bytes (JPEG, PNG, or PDF) encoded as base64.
No image preprocessing required — the models handle orientation, quality, and layout.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import anthropic
from google import genai
from google.genai import types as genai_types

from app.core.config import settings
from app.schemas.delivery import OCRItemResult, OCRResponse

logger = logging.getLogger("acra.ocr")

_PROMPT = (
    "Extract all Bill of Lading fields from this document. "
    "Return a JSON object with exactly these keys: "
    "supplier (string or null), "
    "carrier (string or null), "
    "bol_reference (string or null), "
    "delivery_date (string or null, any format you find), "
    "items (array — each element has material_type, quantity as number, lot_batch_number). "
    "If a field is not present, use null."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _confidence(r: OCRResponse) -> float:
    filled = sum(1 for v in [r.supplier, r.carrier, r.bol_reference, r.delivery_date] if v)
    return round(filled / 4.0, 2)


def _parse_items(raw: list[dict[str, Any]]) -> list[OCRItemResult]:
    items = []
    for entry in raw or []:
        try:
            items.append(
                OCRItemResult(
                    material_type=entry.get("material_type"),
                    quantity=float(entry["quantity"]) if entry.get("quantity") is not None else None,
                    lot_batch_number=entry.get("lot_batch_number"),
                )
            )
        except (TypeError, ValueError):
            pass
    return items


def _build_response(data: dict[str, Any]) -> OCRResponse:
    r = OCRResponse(
        supplier=data.get("supplier"),
        carrier=data.get("carrier"),
        bol_reference=data.get("bol_reference"),
        delivery_date=data.get("delivery_date"),
        items=_parse_items(data.get("items", [])),
        confidence=0.0,
    )
    r.confidence = _confidence(r)
    return r


# ---------------------------------------------------------------------------
# Gemini 2.5 Flash (primary)
# ---------------------------------------------------------------------------

def _extract_with_gemini(file_bytes: bytes, content_type: str) -> OCRResponse:
    client = genai.Client(api_key=settings.gemini_api_key)
    b64 = base64.b64encode(file_bytes).decode()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            _PROMPT,
            genai_types.Part.from_bytes(data=b64, mime_type=content_type),
        ],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    data = json.loads(response.text)
    return _build_response(data)


# ---------------------------------------------------------------------------
# Claude Sonnet 4.6 (fallback)
# ---------------------------------------------------------------------------

_CLAUDE_TOOL = {
    "name": "extract_bol_fields",
    "description": "Extract structured Bill of Lading fields from a document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "supplier": {"type": ["string", "null"]},
            "carrier": {"type": ["string", "null"]},
            "bol_reference": {"type": ["string", "null"]},
            "delivery_date": {"type": ["string", "null"]},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "material_type": {"type": ["string", "null"]},
                        "quantity": {"type": ["number", "null"]},
                        "lot_batch_number": {"type": ["string", "null"]},
                    },
                },
            },
        },
        "required": ["supplier", "carrier", "bol_reference", "delivery_date", "items"],
    },
}


def _extract_with_claude(file_bytes: bytes, content_type: str) -> OCRResponse:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    b64 = base64.standard_b64encode(file_bytes).decode()

    if content_type == "application/pdf":
        file_block: dict[str, Any] = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }
    else:
        file_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": content_type, "data": b64},
        }

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        tools=[_CLAUDE_TOOL],
        tool_choice={"type": "tool", "name": "extract_bol_fields"},
        messages=[
            {
                "role": "user",
                "content": [
                    file_block,
                    {"type": "text", "text": "Extract all Bill of Lading fields from this document."},
                ],
            }
        ],
    )
    tool_input: dict[str, Any] = response.content[0].input
    return _build_response(tool_input)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def process_image_bytes(file_bytes: bytes, content_type: str) -> OCRResponse:
    """Run the two-tier OCR pipeline.

    Tries Gemini 2.5 Flash first; falls back to Claude Sonnet 4.6 on any
    exception or if Gemini returns confidence == 0.0.
    Returns confidence=0.0 if both providers fail.
    """
    try:
        result = _extract_with_gemini(file_bytes, content_type)
        if result.confidence > 0.0:
            return result
        logger.info("Gemini returned confidence=0.0 — falling back to Claude")
    except Exception as exc:
        logger.warning("Gemini OCR failed (%s) — falling back to Claude", exc)

    try:
        return _extract_with_claude(file_bytes, content_type)
    except Exception as exc:
        logger.error("Claude OCR also failed: %s", exc)
        return OCRResponse(confidence=0.0)
