"""Field-level scorer for BOL extractions.

Replaces the positional line-item comparison in `scripts/validation/ocr_roundtrip.py`, which read
`got_items[gi]` — so a single dropped or reordered row misscored every row after it. Here, expected
and extracted rows are aligned by **name similarity** before any numeric field is compared, and
unmatched rows on either side are reported explicitly as misses or spurious extractions.

Three numbers come out, deliberately kept separate rather than blended:

* **header accuracy** — the four header fields. ISS-05 says these are robust; the bench should show
  that rather than assert it.
* **line-item F1** — precision and recall over rows. This is the layout-sensitive part.
* **numeric accuracy** — quantity / pallets / units-per-pallet within *matched* rows only, so a
  missed row is not double-counted as a numeric error.

Everything here is pure and offline: no network, no API keys, no database. Stdlib only at import
time — the one shared helper it borrows (`app.core.benchmark.percentiles`) is imported lazily,
so this module stays usable without loading the FastAPI app's settings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cached_property
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence

from .ground_truth import BolItem, BolSpec

#: Minimum name similarity for two rows to be considered the same line item.
ITEM_MATCH_THRESHOLD = 0.75
#: Minimum similarity for free-text header fields (supplier, carrier).
TEXT_FIELD_THRESHOLD = 0.90
#: Absolute tolerance on `quantity`. Pallets and units-per-pallet must match exactly.
QUANTITY_TOLERANCE = 0.01

HEADER_FIELDS = ("supplier", "carrier", "bol_reference", "delivery_date")
NUMERIC_FIELDS = ("quantity", "pallets", "units_per_pallet")

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")

#: Formats whose day/month order is unambiguous — year-first, or a spelled-out month.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d %B %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%b %d, %Y",
)

#: `03/08/2026` is March 8 to a US reader and August 3 to a European one, and the extractor is told
#: to return the date in "any format you find". Matching these positionally — as an ordered format
#: list does — silently resolves every ambiguous date one way, which both *credits* wrong
#: extractions and *penalises* right ones. Parsed explicitly instead, so genuine ambiguity is
#: reported as unparseable rather than guessed.
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})$")


def normalize_text(value: str | None) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace.

    'Fundición Ibérica S.L.' and 'FUNDICION IBERICA SL' normalize to the same string — a difference
    in diacritics or trailing punctuation is not an extraction error.

    Punctuation is *deleted* rather than replaced with a space, so 'S.L.' collapses to 'sl' and
    matches the unpunctuated spelling. Replacing it with a space would yield 's l' and score a
    correct extraction as wrong.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(value))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WS.sub(" ", _PUNCT.sub("", stripped)).strip().casefold()


def _ratio_of(a: str, b: str) -> float:
    """Similarity of two **already normalized** strings.

    Two empty strings score 0.0, not 1.0: a model that returns nothing must not be credited with a
    perfect match against a missing value. That rule lives here so the pairwise loop in
    `align_items` and the one-shot `similarity()` cannot disagree about it.
    """
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def similarity(left: str | None, right: str | None) -> float:
    """Normalized similarity in [0, 1]. Two empty strings are dissimilar, not identical."""
    return _ratio_of(normalize_text(left), normalize_text(right))


def parse_date(value: Any) -> date | None:
    """Best-effort date parse. The extractor is told to return the date in 'any format you find'.

    Returns `None` for anything that cannot be resolved to exactly one date — including a numeric
    date whose day/month order is genuinely ambiguous (`03/08/2026`). Refusing to guess is the
    conservative choice for a scorer: an ambiguous answer is not credited, so the gate can never be
    passed by a coin flip, and a wrong extraction can never be scored right by coincidence.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()

    numeric = _NUMERIC_DATE.match(text)
    if numeric:
        first, second, year = (int(g) for g in numeric.groups())
        if first > 12 and second <= 12:
            day, month = first, second       # 23/06/2026 — only DD/MM is possible
        elif second > 12 and first <= 12:
            day, month = second, first       # 06/23/2026 — only MM/DD is possible
        elif first == second:
            day, month = first, second       # 06/06/2026 — same date either way
        else:
            return None                      # 03/08/2026 — genuinely ambiguous
        try:
            return date(year, month, day)
        except ValueError:
            return None

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _attr(obj: Any, name: str) -> Any:
    """Read `name` off a pydantic model, a dataclass, or a plain dict."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


@dataclass(frozen=True)
class ItemMatch:
    """One aligned (expected, extracted) row and how its numeric fields compared."""

    expected: BolItem
    actual: Any
    name_similarity: float
    #: field -> (correct, comparable). Comparable is False when ground truth has no value to check.
    numeric: dict[str, tuple[bool, bool]]

    @property
    def numeric_correct(self) -> int:
        return sum(1 for ok, comparable in self.numeric.values() if comparable and ok)

    @property
    def numeric_comparable(self) -> int:
        return sum(1 for _, comparable in self.numeric.values() if comparable)


@dataclass
class BolScore:
    """Score for one document."""

    layout: str
    header: dict[str, bool] = field(default_factory=dict)
    matches: list[ItemMatch] = field(default_factory=list)
    missed: list[BolItem] = field(default_factory=list)
    spurious: list[Any] = field(default_factory=list)
    provider: str | None = None
    latency_ms: float | None = None
    error: str | None = None

    @property
    def header_correct(self) -> int:
        return sum(1 for ok in self.header.values() if ok)

    @property
    def header_total(self) -> int:
        return len(self.header)

    @property
    def header_accuracy(self) -> float:
        return _ratio(self.header_correct, self.header_total)

    @property
    def expected_items(self) -> int:
        return len(self.matches) + len(self.missed)

    @property
    def extracted_items(self) -> int:
        return len(self.matches) + len(self.spurious)

    @property
    def precision(self) -> float:
        return _ratio(len(self.matches), self.extracted_items)

    @property
    def recall(self) -> float:
        return _ratio(len(self.matches), self.expected_items)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 0.0 if (p + r) == 0 else round(2 * p * r / (p + r), 4)

    @property
    def numeric_correct(self) -> int:
        return sum(m.numeric_correct for m in self.matches)

    @property
    def numeric_comparable(self) -> int:
        return sum(m.numeric_comparable for m in self.matches)

    @property
    def numeric_accuracy(self) -> float:
        return _ratio(self.numeric_correct, self.numeric_comparable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout": self.layout,
            "provider": self.provider,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "header": dict(self.header),
            "header_accuracy": self.header_accuracy,
            "items": {
                "expected": self.expected_items,
                "extracted": self.extracted_items,
                "matched": len(self.matches),
                "missed": [m.item_name for m in self.missed],
                "spurious": [_attr(s, "item_name") for s in self.spurious],
                "precision": self.precision,
                "recall": self.recall,
                "f1": self.f1,
            },
            "numeric": {
                "correct": self.numeric_correct,
                "comparable": self.numeric_comparable,
                "accuracy": self.numeric_accuracy,
            },
        }


@dataclass
class CorpusScore:
    """Micro-averaged score across documents — every field weighted equally, not every document.

    **Accuracy is computed over documents that actually returned an extraction.** A provider that
    rate-limits or times out has an *availability* problem, not an accuracy one, and folding the
    two together produces a badly misleading comparison: the first live run of this bench scored
    gemini at 0.483 F1 purely because 14 of 21 calls came back 429, which reads as "the model is
    bad at reading BOLs" when it means "the free tier allows 5 requests a minute". Failures are
    reported separately via `error_count` / `error_rate`.
    """

    documents: list[BolScore] = field(default_factory=list)

    # cached: `documents` is populated once by `score_corpus` and never mutated afterwards, and
    # one `to_dict()` would otherwise re-filter it 16 times.
    @cached_property
    def succeeded(self) -> list[BolScore]:
        """Documents that returned an extraction — the only ones accuracy is computed over."""
        return [d for d in self.documents if d.error is None]

    @cached_property
    def failed(self) -> list[BolScore]:
        return [d for d in self.documents if d.error is not None]

    @property
    def error_count(self) -> int:
        return len(self.failed)

    @property
    def error_rate(self) -> float:
        return _ratio(len(self.failed), len(self.documents))

    @property
    def header_accuracy(self) -> float:
        return _ratio(
            sum(d.header_correct for d in self.succeeded),
            sum(d.header_total for d in self.succeeded),
        )

    @property
    def precision(self) -> float:
        return _ratio(
            sum(len(d.matches) for d in self.succeeded),
            sum(d.extracted_items for d in self.succeeded),
        )

    @property
    def recall(self) -> float:
        return _ratio(
            sum(len(d.matches) for d in self.succeeded),
            sum(d.expected_items for d in self.succeeded),
        )

    @property
    def item_f1(self) -> float:
        p, r = self.precision, self.recall
        return 0.0 if (p + r) == 0 else round(2 * p * r / (p + r), 4)

    @property
    def numeric_accuracy(self) -> float:
        return _ratio(
            sum(d.numeric_correct for d in self.succeeded),
            sum(d.numeric_comparable for d in self.succeeded),
        )

    @property
    def latencies_ms(self) -> list[float]:
        """Latencies of successful calls only — a 429 rejection returns in milliseconds and would
        otherwise flatter the percentiles."""
        return sorted(d.latency_ms for d in self.succeeded if d.latency_ms is not None)

    def latency_percentile(self, pct: int) -> float | None:
        """Nearest-rank percentile. Returns None when nothing was timed.

        Delegates the maths to `app.core.benchmark.percentiles`, which is where A8-2 defined the
        nearest-rank convention (`rank = ceil(p/100 x n)`, no interpolation) for every ACRA
        benchmark. Re-deriving it here would let this bench's published numbers drift from the
        other A8 artifacts'.
        """
        # Imported lazily: `app.core.benchmark` pulls in `app.core.config`, and this module is
        # deliberately importable without the FastAPI app's settings.
        from app.core.benchmark import percentiles

        samples = self.latencies_ms
        if not samples:
            return None
        return round(percentiles(samples, (pct,))[pct], 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "header_accuracy": self.header_accuracy,
            "item_precision": self.precision,
            "item_recall": self.recall,
            "item_f1": self.item_f1,
            "numeric_accuracy": self.numeric_accuracy,
            # Availability, kept distinct from accuracy on purpose — see the class docstring.
            "calls": len(self.documents),
            "scored": len(self.succeeded),
            "errors": self.error_count,
            "error_rate": self.error_rate,
            "latency_ms": {
                "p50": self.latency_percentile(50),
                "p95": self.latency_percentile(95),
                "p99": self.latency_percentile(99),
            },
            "documents": [d.to_dict() for d in self.documents],
        }


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 4)


def score_header(spec: BolSpec, extraction: Any) -> dict[str, bool]:
    """Grade the four header fields.

    Text fields use a similarity threshold so punctuation and accent noise do not count against the
    model; `bol_reference` demands exact normalized equality because a reference with one character
    wrong is a different document; the date is compared as a parsed date, so any input format is
    acceptable but an unparseable string is not.
    """
    supplier = _attr(extraction, "supplier")
    carrier = _attr(extraction, "carrier")
    reference = _attr(extraction, "bol_reference")
    delivery_date = parse_date(_attr(extraction, "delivery_date"))

    return {
        "supplier": similarity(spec.supplier, supplier) >= TEXT_FIELD_THRESHOLD,
        "carrier": similarity(spec.carrier, carrier) >= TEXT_FIELD_THRESHOLD,
        "bol_reference": bool(reference)
        and normalize_text(reference) == normalize_text(spec.bol_reference),
        "delivery_date": delivery_date is not None and delivery_date == spec.delivery_date,
    }


def _compare_numeric(expected: BolItem, actual: Any) -> dict[str, tuple[bool, bool]]:
    """Compare numeric fields within one matched pair.

    A field is *comparable* only when ground truth carries a value for it — `units_per_pallet` is
    legitimately absent on some rows, and grading an absence would punish the model for being right.
    """
    result: dict[str, tuple[bool, bool]] = {}
    for name in NUMERIC_FIELDS:
        want = getattr(expected, name)
        if want is None:
            result[name] = (False, False)
            continue
        got = _attr(actual, name)
        if got is None:
            result[name] = (False, True)
            continue
        try:
            got_value = float(got)
        except (TypeError, ValueError):
            result[name] = (False, True)
            continue
        tolerance = QUANTITY_TOLERANCE if name == "quantity" else 0.0
        result[name] = (abs(got_value - float(want)) <= tolerance, True)
    return result


def align_items(
    expected: Sequence[BolItem], actual: Sequence[Any]
) -> tuple[list[ItemMatch], list[BolItem], list[Any]]:
    """Greedily pair rows by name similarity, best pair first.

    Greedy-by-best-score rather than positional: reordering the table, dropping a row, or
    hallucinating one each affect only the rows involved. Every row is consumable once, so a single
    extracted row cannot satisfy two expected rows.
    """
    # Normalize each name once rather than once per pair: `similarity()` normalizes both sides on
    # every call, so the n x m matrix re-normalized the same few strings n and m times over.
    expected_names = [normalize_text(exp.item_name) for exp in expected]
    actual_names = [normalize_text(_attr(act, "item_name")) for act in actual]

    candidates = [
        (_ratio_of(a, b), i, j)
        for i, a in enumerate(expected_names)
        for j, b in enumerate(actual_names)
    ]
    # Sort by similarity desc, then by index for a deterministic result on ties.
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    used_expected: set[int] = set()
    used_actual: set[int] = set()
    matches: list[ItemMatch] = []

    for ratio, i, j in candidates:
        if ratio < ITEM_MATCH_THRESHOLD:
            break
        if i in used_expected or j in used_actual:
            continue
        used_expected.add(i)
        used_actual.add(j)
        matches.append(
            ItemMatch(
                expected=expected[i],
                actual=actual[j],
                name_similarity=round(ratio, 4),
                numeric=_compare_numeric(expected[i], actual[j]),
            )
        )

    missed = [e for i, e in enumerate(expected) if i not in used_expected]
    spurious = [a for j, a in enumerate(actual) if j not in used_actual]
    return matches, missed, spurious


def score_document(
    spec: BolSpec,
    extraction: Any,
    *,
    provider: str | None = None,
    latency_ms: float | None = None,
    error: str | None = None,
) -> BolScore:
    """Grade one extraction against its ground truth."""
    if error is not None or extraction is None:
        return BolScore(
            layout=spec.layout,
            header={f: False for f in HEADER_FIELDS},
            missed=list(spec.items),
            provider=provider,
            latency_ms=latency_ms,
            error=error or "no extraction returned",
        )

    actual_items = _attr(extraction, "items") or []
    matches, missed, spurious = align_items(spec.items, list(actual_items))
    return BolScore(
        layout=spec.layout,
        header=score_header(spec, extraction),
        matches=matches,
        missed=missed,
        spurious=spurious,
        provider=provider,
        latency_ms=latency_ms,
    )


def score_corpus(scores: Iterable[BolScore]) -> CorpusScore:
    """Aggregate per-document scores into one micro-averaged result."""
    return CorpusScore(documents=list(scores))


#: The metrics the no-regression gate enforces.
GATE_METRICS = ("header_accuracy", "item_f1", "numeric_accuracy")

#: Absolute slack allowed below the recorded baseline. Vision models are nondeterministic: the same
#: document and model can extract differently between runs, so a gate with no tolerance would flake.
#: If observed variance ever exceeds this, the honest fix is to widen the band and report the
#: variance — not to tighten until the suite goes green.
DEFAULT_TOLERANCE = 0.05


@dataclass(frozen=True)
class GateFailure:
    """One metric that fell below its floor."""

    metric: str
    measured: float
    baseline: float
    floor: float

    def __str__(self) -> str:
        return (
            f"{self.metric}: measured {self.measured:.4f} < floor {self.floor:.4f} "
            f"(baseline {self.baseline:.4f} - tolerance)"
        )


def compare_to_baseline(
    measured: CorpusScore | dict[str, Any],
    baseline: dict[str, Any],
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[GateFailure]:
    """Check a measured run against a recorded baseline.

    Returns the failing metrics — empty means the gate passes. Accepts either a `CorpusScore` or an
    already-serialized dict so the offline negative control exercises exactly the same comparison
    the live gate does.
    """
    values = measured.to_dict() if isinstance(measured, CorpusScore) else measured
    failures = []
    for metric in GATE_METRICS:
        if metric not in baseline:
            continue
        floor = baseline[metric] - tolerance
        actual = values.get(metric, 0.0)
        if actual < floor:
            failures.append(
                GateFailure(
                    metric=metric, measured=actual, baseline=baseline[metric], floor=round(floor, 4)
                )
            )
    return failures


def format_document_report(score: BolScore) -> str:
    """Human-readable per-document breakdown, for the round-trip and bench logs."""
    lines = [f"  {score.layout}  (provider={score.provider or 'n/a'})"]
    if score.error:
        lines.append(f"    ERROR: {score.error}")
        return "\n".join(lines)

    for name in HEADER_FIELDS:
        flag = "OK " if score.header.get(name) else "MISS"
        lines.append(f"    [{flag}] {name}")
    lines.append(
        f"    items: matched {len(score.matches)}/{score.expected_items}"
        f"  spurious {len(score.spurious)}"
        f"  P={score.precision:.2f} R={score.recall:.2f} F1={score.f1:.2f}"
    )
    for match in score.matches:
        wrong = [n for n, (ok, comparable) in match.numeric.items() if comparable and not ok]
        if wrong:
            detail = ", ".join(
                f"{n}: expected {getattr(match.expected, n)!r} got {_attr(match.actual, n)!r}"
                for n in wrong
            )
            lines.append(f"      ~ {match.expected.item_name}: {detail}")
    for item in score.missed:
        lines.append(f"      - MISSED {item.item_name!r}")
    for item in score.spurious:
        lines.append(f"      + SPURIOUS {_attr(item, 'item_name')!r}")
    lines.append(
        f"    numeric: {score.numeric_correct}/{score.numeric_comparable}"
        f" ({score.numeric_accuracy:.2f})"
    )
    return "\n".join(lines)
