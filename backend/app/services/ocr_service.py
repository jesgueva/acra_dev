"""OCR Service — Vision LLM-based BOL field extraction.

Two-tier pipeline:
  1. Gemini    — primary  (`settings.gemini_model`, JSON schema output)
  2. Claude    — fallback (`settings.anthropic_model`, used when Gemini fails or confidence == 0.0)

Both model IDs are configuration, not constants, so a swap does not require a code change and the
A8-4 comparison bench can report the model that actually ran.

Both providers receive the raw file bytes (JPEG, PNG, or PDF) encoded as base64.

`settings.ocr_mock_mode` (ACR-50) short-circuits both providers with a canned response — see
`_mock_response()` — so the receiving flow is runnable without API keys.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import anthropic
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from app.core.config import settings
from app.schemas.delivery import OCRItemResult, OCRResponse

logger = logging.getLogger("acra.ocr")

# ---------------------------------------------------------------------------
# Lazy singletons — initialized on first use, reused across requests
# ---------------------------------------------------------------------------

_gemini_client: genai.Client | None = None
_anthropic_client: anthropic.Anthropic | None = None


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
    return _gemini_client


def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


_OCR_EXTRACTION_INSTRUCTIONS = (
    "Extract all Bill of Lading fields from this document.\n\n"
    "Return a JSON object with exactly these keys: "
    "supplier (string or null), "
    "carrier (string or null), "
    "bol_reference (string or null), "
    "delivery_date (string or null, any format you find), "
    "items (array — each element has: item_name, description, quantity as number, "
    "pallets as integer, units_per_pallet as integer or null).\n\n"
    "Rules:\n"
    "1) Supplier: If the carrier value contains 'TRANSFER' or 'TRANSFERENCIA' "
    "(case-insensitive), set supplier to the string 'Internal'.\n"
    "2) units_per_pallet: For each line item, if the table has a third numeric column "
    "(units per pallet, Ud/Pallet, U/C, bultos/pallet, or similar), fill units_per_pallet. "
    "Use null only when that value is truly absent or illegible.\n"
    "3) European thousands: When a number uses a dot as a thousands separator "
    "(e.g. 17.122 or 1.234.567 — typically groups of three digits after dots), "
    "do not treat the dot as a decimal point; normalize to the correct integer or count. "
    "When only one or two digits follow the dot (e.g. 5.44), treat as a decimal "
    "unless the triplet rule below clearly indicates otherwise.\n"
    "4) Triplet heuristic: If exactly three distinct numeric values appear on one item row "
    "(same logical line), sort them ascending: smallest → pallets, middle → units_per_pallet, "
    "largest → quantity (total units or weight for that row, per the document). "
    "pallets × units_per_pallet should be approximately equal to quantity (allow small OCR rounding); "
    "if column order is ambiguous, prefer this math over strict left-to-right order.\n"
    "5) If a field is not present, use null."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_items(raw: list[dict[str, Any]]) -> list[OCRItemResult]:
    items = []
    for entry in raw or []:
        try:
            items.append(
                OCRItemResult(
                    item_name=entry.get("item_name"),
                    description=entry.get("description"),
                    quantity=float(entry["quantity"]) if entry.get("quantity") is not None else None,
                    pallets=int(entry["pallets"]) if entry.get("pallets") is not None else None,
                    units_per_pallet=int(entry["units_per_pallet"]) if entry.get("units_per_pallet") is not None else None,
                )
            )
        except (TypeError, ValueError):
            pass
    return items


def _build_response(data: dict[str, Any], provider: str) -> OCRResponse:
    """Shape a provider's raw JSON into the wire response.

    `confidence` is a **header fill rate**, not an accuracy: it counts how many of the four header
    fields came back non-empty, so four wrong values still score 1.0. It keeps its meaning because
    the 422 gate and the Gemini→Claude fallback both key off `> 0.0`; `header_fill_rate` carries the
    same number under an honest name. Measured accuracy comes from the A8-4 bench
    (`backend/scripts/ocr_bench/`), which scores against a labelled corpus.
    """
    supplier = data.get("supplier")
    carrier = data.get("carrier")
    bol_reference = data.get("bol_reference")
    delivery_date = data.get("delivery_date")
    filled = sum(1 for v in [supplier, carrier, bol_reference, delivery_date] if v)
    fill_rate = round(filled / 4.0, 2)
    raw_items = data.get("items") or []
    return OCRResponse(
        supplier=supplier,
        carrier=carrier,
        bol_reference=bol_reference,
        delivery_date=delivery_date,
        items=_parse_items(raw_items),
        confidence=fill_rate,
        header_fill_rate=fill_rate,
        provider=provider,
    )


# ---------------------------------------------------------------------------
# Gemini 2.5 Flash (primary)
# ---------------------------------------------------------------------------

def _extract_with_gemini(file_bytes: bytes, content_type: str) -> OCRResponse:
    response = _get_gemini_client().models.generate_content(
        model=settings.gemini_model,
        contents=[
            _OCR_EXTRACTION_INSTRUCTIONS,
            genai_types.Part.from_bytes(data=base64.b64encode(file_bytes).decode(), mime_type=content_type),
        ],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )
    parsed = json.loads(response.text)
    return _build_response(parsed, "gemini")


# ---------------------------------------------------------------------------
# Claude Sonnet 4.6 (fallback)
# ---------------------------------------------------------------------------

_CLAUDE_TOOL = {
    "name": "extract_bol_fields",
    "description": _OCR_EXTRACTION_INSTRUCTIONS,
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
                        "item_name": {"type": ["string", "null"]},
                        "description": {"type": ["string", "null"]},
                        "quantity": {"type": ["number", "null"]},
                        "pallets": {"type": ["integer", "null"]},
                        "units_per_pallet": {"type": ["integer", "null"]},
                    },
                },
            },
        },
        "required": ["supplier", "carrier", "bol_reference", "delivery_date", "items"],
    },
}


def _extract_with_claude(file_bytes: bytes, content_type: str) -> OCRResponse:
    b64 = base64.b64encode(file_bytes).decode()
    file_block: dict[str, Any]
    if content_type == "application/pdf":
        file_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }
    else:
        file_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": content_type, "data": b64},
        }

    response = _get_anthropic_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        tools=[_CLAUDE_TOOL],
        tool_choice={"type": "tool", "name": "extract_bol_fields"},
        messages=[
            {
                "role": "user",
                "content": [
                    file_block,
                    {"type": "text", "text": _OCR_EXTRACTION_INSTRUCTIONS},
                ],
            }
        ],
    )
    tool_block = response.content[0]
    return _build_response(tool_block.input, "claude")


# ---------------------------------------------------------------------------
# Offline/mock mode (ACR-50 / A10-2)
# ---------------------------------------------------------------------------

def _mock_response() -> OCRResponse:
    """A canned extraction, used when `settings.ocr_mock_mode` is on.

    Field values mirror the `GRIDDED` layout in `backend/scripts/ocr_bench/ground_truth.py`
    (duplicated here, not imported — `ocr_bench/__init__.py` states the app must never import that
    package, since none of it is meant to ship in the request path). The one committed fixture,
    `backend/tests/fixtures/ocr/sample_bol_gridded.png`, is the matching image to upload against it.
    Content is ignored entirely in mock mode; every upload gets this same response.
    """
    return OCRResponse(
        supplier="Acme Steel Supply Co.",
        carrier="Iberia Logistics S.L.",
        bol_reference="BOL-2026-0623",
        delivery_date="2026-06-23",
        items=[
            OCRItemResult(item_name="Galvanized Steel Sheet", description=None, quantity=1000.0, pallets=5, units_per_pallet=200),
            OCRItemResult(item_name="Aluminum Coil 1050", description=None, quantity=450.0, pallets=3, units_per_pallet=150),
            OCRItemResult(item_name="Copper Wire Spool", description=None, quantity=1000.0, pallets=2, units_per_pallet=500),
        ],
        confidence=1.0,
        header_fill_rate=1.0,
        provider="mock",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def process_image_bytes(file_bytes: bytes, content_type: str) -> OCRResponse:
    if settings.ocr_mock_mode:
        return _mock_response()

    try:
        result = _extract_with_gemini(file_bytes, content_type)
        if result.confidence > 0.0:
            return result
    except genai_errors.ServerError as exc:
        logger.warning("[gemini] server error %s (%s) — falling back to Claude", exc.code, exc.status)
    except genai_errors.ClientError as exc:
        logger.warning("[gemini] client error %s (%s) — falling back to Claude", exc.code, exc.status)
    except json.JSONDecodeError as exc:
        logger.warning("[gemini] invalid JSON in response (pos %d) — falling back to Claude", exc.pos)
    except Exception:
        logger.warning("[gemini] unexpected error — falling back to Claude", exc_info=True)

    try:
        result = _extract_with_claude(file_bytes, content_type)
        return result
    except Exception as exc:
        logger.error("[claude] also failed: %s", exc, exc_info=True)
        return OCRResponse(confidence=0.0)
