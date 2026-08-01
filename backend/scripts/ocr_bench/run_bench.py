"""Opt-in provider comparison bench — the configured Gemini model vs the configured Claude model.

Renders the labelled corpus, sends every document to each provider, scores the extractions against
ground truth, and writes machine-readable evidence with enough run metadata to repeat the run.

This calls `_extract_with_gemini` / `_extract_with_claude` **directly** rather than going through
`process_image_bytes`, because the production entry point silently falls back from Gemini to Claude
— which is right for a user request and useless for a comparison, since a Gemini failure would be
scored as a Gemini result.

Costs real money and needs real API keys, so it never runs in CI. Usage from `backend/`:

    python -m scripts.ocr_bench.run_bench --provider both --repeat 3
    python -m scripts.ocr_bench.run_bench --provider gemini --out /tmp/bench

Writes `ocr-bench.json` (machine-readable) and `ocr-bench.md` (the head-to-head table) into the
output directory, plus the rendered corpus alongside them.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import corpus, scoring
from .ground_truth import CORPUS, BolSpec

PROVIDERS = ("gemini", "claude")

ENV_KEYS = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}


def models() -> dict[str, str]:
    """Model IDs read from settings, so the bench cannot report a model that is not what ran.

    Imported lazily for the same reason `_extractor` is: importing `app` loads backend settings.
    """
    from app.core.config import settings

    return {"gemini": settings.gemini_model, "claude": settings.anthropic_model}


def _extractor(provider: str) -> Callable[[bytes, str], Any]:
    """Import the service lazily — importing `app` requires the backend settings to load."""
    from app.services import ocr_service

    return {
        "gemini": ocr_service._extract_with_gemini,
        "claude": ocr_service._extract_with_claude,
    }[provider]


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def run_metadata(providers: list[str], repeat: int) -> dict[str, Any]:
    """Everything needed to repeat this run — the Evidence Packaging requirement."""
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "host": f"{platform.system()} {platform.release()} {platform.machine()}",
        "python": platform.python_version(),
        "models": {p: models()[p] for p in providers},
        "providers": providers,
        "repeat": repeat,
        "corpus": {
            "documents": len(CORPUS),
            "layouts": [s.layout for s in CORPUS],
            "line_items": sum(len(s.items) for s in CORPUS),
            "noise_seed": corpus.NOISE_SEED,
        },
        "scorer": {
            "item_match_threshold": scoring.ITEM_MATCH_THRESHOLD,
            "text_field_threshold": scoring.TEXT_FIELD_THRESHOLD,
            "quantity_tolerance": scoring.QUANTITY_TOLERANCE,
        },
    }


#: Substrings identifying a *transient* provider failure — worth retrying rather than scoring.
_RETRYABLE = ("429", "resource_exhausted", "rate limit", "overloaded", "503", "529", "timeout")

#: Seconds to wait before the first retry; doubles each attempt.
_BACKOFF_BASE = 8.0

#: Wall-clock ceiling for ONE document including every retry. Gemini's free tier answers a 429 with
#: its own retryDelay (~25s), so four retries can burn ~100s on a single document — and the corpus is
#: 7 documents x N rounds. Without a ceiling one exhausted key turns a 9-minute bench into a 45-minute
#: one. Exceeding it records an ERROR, never a zero score: scoring a quota failure as a bad extraction
#: is exactly the defect the retry logic was added to fix (gemini read 0.483 F1 on the first live run).
_DOC_BUDGET_S = 60.0

#: Consecutive retryable failures before the arm is abandoned. Quota exhaustion is a GLOBAL condition,
#: not a per-request accident: once three documents in a row have 429'd, grinding through the rest of
#: the corpus buys nothing but wall time. Fail the arm fast rather than the call fast.
_QUOTA_ABORT_AFTER = 3

_RETRY_DELAY_RE = re.compile(r"'retryDelay':\s*'(\d+)s'")


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _RETRYABLE)


def _retry_after(exc: Exception, attempt: int) -> float:
    """Honour the provider's own retryDelay when it sends one, else exponential backoff."""
    match = _RETRY_DELAY_RE.search(str(exc))
    if match:
        return float(match.group(1)) + 1.0
    return _BACKOFF_BASE * (2**attempt)


def score_one(
    spec: BolSpec,
    path: Path,
    provider: str,
    extractor: Callable[[bytes, str], Any],
    *,
    max_retries: int = 4,
    doc_budget_s: float = _DOC_BUDGET_S,
    verbose: bool = True,
) -> scoring.BolScore:
    """Send one document to one provider and grade what comes back.

    Retries transient failures with backoff. Gemini's free tier allows 5 requests per minute, and
    without this the bench measures quota exhaustion rather than extraction quality — the first
    live run scored gemini at 0.483 F1 for exactly that reason.

    Retrying is bounded twice over: `max_retries` attempts AND `doc_budget_s` of wall clock. The
    budget is what stops an exhausted key from stretching the bench by an order of magnitude, since
    a provider that answers every 429 with a 25-second retryDelay makes the attempt count a poor
    proxy for elapsed time. Giving up returns an ERROR score, which the corpus aggregate counts
    separately from a graded document — never a zero.
    """
    payload = path.read_bytes()
    doc_started = time.perf_counter()

    for attempt in range(max_retries + 1):
        started = time.perf_counter()
        try:
            extraction = extractor(payload, spec.mime_type)
        except Exception as exc:  # noqa: BLE001 — a provider failure is a datum, not a crash
            latency_ms = (time.perf_counter() - started) * 1000.0
            retryable = _is_retryable(exc)
            if attempt < max_retries and retryable:
                delay = _retry_after(exc, attempt)
                spent = time.perf_counter() - doc_started
                # Check the budget against the delay we are ABOUT to sleep, not the time already
                # spent: sleeping 25s to then discover we are over budget wastes exactly the time
                # the budget exists to protect.
                if spent + delay > doc_budget_s:
                    if verbose:
                        print(
                            f"    [{provider}] {spec.layout}: giving up after {spent:.0f}s "
                            f"(budget {doc_budget_s:.0f}s) — recorded as an error, not a score"
                        )
                    return scoring.score_document(
                        spec,
                        None,
                        provider=provider,
                        latency_ms=latency_ms,
                        error=(
                            f"doc budget {doc_budget_s:.0f}s exceeded after {attempt + 1} "
                            f"attempt(s); last: {type(exc).__name__}: {exc}"
                        ),
                    )
                if verbose:
                    print(
                        f"    [{provider}] {spec.layout}: transient failure, "
                        f"retry {attempt + 1}/{max_retries} in {delay:.0f}s"
                    )
                time.sleep(delay)
                continue
            return scoring.score_document(
                spec,
                None,
                provider=provider,
                latency_ms=latency_ms,
                error=f"{type(exc).__name__}: {exc}",
            )
        latency_ms = (time.perf_counter() - started) * 1000.0
        return scoring.score_document(spec, extraction, provider=provider, latency_ms=latency_ms)

    raise AssertionError("unreachable")  # pragma: no cover


def run(
    providers: list[str],
    repeat: int,
    out_dir: Path,
    verbose: bool = True,
    delay: float = 0.0,
    max_retries: int = 4,
    doc_budget_s: float = _DOC_BUDGET_S,
    quota_abort_after: int = _QUOTA_ABORT_AFTER,
) -> dict[str, Any]:
    """Render, extract, score. Returns the full result payload.

    `delay` paces requests to stay inside a provider's rate limit — see `--delay`.

    An arm is abandoned after `quota_abort_after` consecutive failed documents and reported as
    INCOMPLETE. That is not the same as scoring badly, and the writeup must not read it as such: an
    aborted arm has no accuracy claim at all, which is honest, where a partial average over whichever
    documents happened to squeak past the quota would be a number with no meaning.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = corpus.render_all(out_dir / "corpus")

    results: dict[str, scoring.CorpusScore] = {}
    incomplete: dict[str, str] = {}
    for provider in providers:
        extractor = _extractor(provider)
        scores: list[scoring.BolScore] = []
        first = True
        consecutive_failures = 0
        aborted: str | None = None
        for round_no in range(1, repeat + 1):
            if aborted:
                break
            for spec in CORPUS:
                if delay and not first:
                    time.sleep(delay)
                first = False
                score = score_one(
                    spec,
                    rendered[spec.layout],
                    provider,
                    extractor,
                    max_retries=max_retries,
                    doc_budget_s=doc_budget_s,
                    verbose=verbose,
                )
                scores.append(score)
                if score.error:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                if verbose:
                    if score.error:
                        print(
                            f"! [{provider:6}] round {round_no}/{repeat} {spec.layout:19}"
                            f" FAILED: {score.error[:80]}"
                        )
                    else:
                        print(
                            f"  [{provider:6}] round {round_no}/{repeat} {spec.layout:19}"
                            f" header={score.header_accuracy:.2f} F1={score.f1:.2f}"
                            f" num={score.numeric_accuracy:.2f} {score.latency_ms:7.0f}ms"
                        )
                if consecutive_failures >= quota_abort_after:
                    aborted = (
                        f"{consecutive_failures} consecutive failed documents "
                        f"(scored {len([s for s in scores if not s.error])} of "
                        f"{len(CORPUS) * repeat}) — provider quota or availability, not accuracy"
                    )
                    if verbose:
                        print(f"! [{provider:6}] ARM ABANDONED: {aborted}")
                    break
        results[provider] = scoring.score_corpus(scores)
        if aborted:
            incomplete[provider] = aborted

    return {
        "run": {
            **run_metadata(providers, repeat),
            "delay_s": delay,
            "max_retries": max_retries,
            "doc_budget_s": doc_budget_s,
            "quota_abort_after": quota_abort_after,
        },
        # Present but empty on a healthy run, so a reader never has to infer completeness from the
        # absence of a key.
        "incomplete_arms": incomplete,
        "results": {p: s.to_dict() for p, s in results.items()},
    }


def _row(*cells: Any) -> str:
    """One markdown table row. Centralized so adding a column cannot desync the pipes."""
    return "| " + " | ".join(str(c) for c in cells) + " |"


def format_markdown(payload: dict[str, Any]) -> str:
    """The head-to-head table for the A8 writeup."""
    meta = payload["run"]
    lines = [
        "# OCR provider comparison — ACRA MES (A8-4)",
        "",
        f"- **Captured:** {meta['captured_at']}",
        f"- **Repo:** acra_dev @ `{meta['git_sha']}`",
        f"- **Host:** {meta['host']} · Python {meta['python']}",
        f"- **Corpus:** {meta['corpus']['documents']} synthetic documents, "
        f"{meta['corpus']['line_items']} line items "
        f"({', '.join(meta['corpus']['layouts'])})",
        f"- **Repeats:** {meta['repeat']} per document",
        f"- **Scorer:** item match ≥ {meta['scorer']['item_match_threshold']}, "
        f"text field ≥ {meta['scorer']['text_field_threshold']}, "
        f"quantity ± {meta['scorer']['quantity_tolerance']}",
        "",
        "Synthetic documents are cleaner than real phone photos of paper BOLs, so these figures are",
        "an **upper bound** on field performance, not a production accuracy claim.",
        "",
        "Accuracy is computed over calls that returned an extraction. Calls that failed (rate",
        "limits, timeouts) are counted separately under *availability* — a provider that is",
        "throttled has an availability problem, not an accuracy one, and averaging the two together",
        "produces a badly misleading comparison.",
        "",
        "## Accuracy",
        "",
        "| Provider | Model | Header acc. | Item P | Item R | Item F1 | Numeric acc. |",
        "|---|---|---|---|---|---|---|",
    ]

    for provider, result in payload["results"].items():
        lines.append(
            _row(
                f"`{provider}`",
                f"`{meta['models'][provider]}`",
                f"{result['header_accuracy']:.3f}",
                f"{result['item_precision']:.3f}",
                f"{result['item_recall']:.3f}",
                f"**{result['item_f1']:.3f}**",
                f"{result['numeric_accuracy']:.3f}",
            )
        )

    lines += [
        "",
        "## Availability and latency",
        "",
        "| Provider | Calls | Scored | Errors | Error rate | p50 | p95 | p99 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    def cell(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0f} ms"

    for provider, result in payload["results"].items():
        latency = result["latency_ms"]
        lines.append(
            _row(
                f"`{provider}`",
                result["calls"],
                result["scored"],
                result["errors"],
                f"{result['error_rate']:.3f}",
                cell(latency["p50"]),
                cell(latency["p95"]),
                cell(latency["p99"]),
            )
        )

    lines += [
        "",
        "## Per-layout item F1",
        "",
        "Scored calls only; `n/a` means every call for that layout failed.",
        "",
        _row("Layout", *payload["results"]),
        "|---|" + "---|" * len(payload["results"]),
    ]
    for layout in meta["corpus"]["layouts"]:
        cells = []
        for result in payload["results"].values():
            docs = [
                d for d in result["documents"] if d["layout"] == layout and not d["error"]
            ]
            cells.append(
                f"{sum(d['items']['f1'] for d in docs) / len(docs):.3f}" if docs else "n/a"
            )
        lines.append(_row(f"`{layout}`", *cells))

    errors = [
        (p, d["layout"], d["error"])
        for p, r in payload["results"].items()
        for d in r["documents"]
        if d["error"]
    ]
    # Placed above the error list because it changes how every table on this page must be read.
    if payload.get("incomplete_arms"):
        lines += ["", "## ⚠ Incomplete arms", ""]
        lines += [
            "These arms were abandoned mid-run. Their rows above are computed over whichever "
            "documents completed and **are not accuracy results** — cite them as provider "
            "availability failures, not as measured quality.",
            "",
        ]
        lines += [f"- `{p}`: {reason}" for p, reason in payload["incomplete_arms"].items()]

    if errors:
        lines += ["", "## Errors", ""]
        # Provider error payloads run to hundreds of lines; the class and first line is the datum.
        lines += [
            f"- `{p}` / `{layout}`: {err.splitlines()[0][:160]}" for p, layout, err in errors
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=(*PROVIDERS, "both"), default="both")
    parser.add_argument("--repeat", type=int, default=1, help="rounds per document (default 1)")
    parser.add_argument("--out", default="validation-evidence/ocr-bench", type=Path)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help=(
            "seconds to pace between calls. Gemini's free tier allows only 5 requests per "
            "minute, so --delay 13 keeps a single-provider run inside it"
        ),
    )
    parser.add_argument(
        "--max-retries", type=int, default=4, help="retries on transient provider failures"
    )
    parser.add_argument(
        "--doc-budget",
        type=float,
        default=_DOC_BUDGET_S,
        help=(
            f"wall-clock ceiling in seconds for one document including retries "
            f"(default {_DOC_BUDGET_S:.0f}). Exceeding it records an error, not a zero score"
        ),
    )
    parser.add_argument(
        "--quota-abort-after",
        type=int,
        default=_QUOTA_ABORT_AFTER,
        help=(
            f"abandon an arm after this many consecutive failed documents "
            f"(default {_QUOTA_ABORT_AFTER}); quota exhaustion is global, so retrying the rest "
            f"of the corpus only costs wall time"
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    providers = list(PROVIDERS) if args.provider == "both" else [args.provider]

    missing = [ENV_KEYS[p] for p in providers if not os.getenv(ENV_KEYS[p])]
    if missing:
        print(
            f"error: {', '.join(missing)} not set — this bench calls the real providers.",
            file=sys.stderr,
        )
        return 2
    if args.repeat < 1:
        print("error: --repeat must be at least 1", file=sys.stderr)
        return 2

    payload = run(
        providers,
        args.repeat,
        Path(args.out),
        verbose=not args.quiet,
        delay=args.delay,
        max_retries=args.max_retries,
        doc_budget_s=args.doc_budget,
        quota_abort_after=args.quota_abort_after,
    )

    out_dir = Path(args.out)
    (out_dir / "ocr-bench.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "ocr-bench.md").write_text(format_markdown(payload), encoding="utf-8")

    print()
    print(format_markdown(payload))
    print(f"Artifacts written to: {out_dir}")

    # Artifacts are written first, then the run fails: an abandoned arm is exactly the case where the
    # evidence of what happened matters most, and the caller still needs a non-zero status so a
    # publication capture cannot ship a comparison with a missing side.
    if payload["incomplete_arms"]:
        print(file=sys.stderr)
        for provider, reason in payload["incomplete_arms"].items():
            print(f"INCOMPLETE — {provider}: {reason}", file=sys.stderr)
        print(
            "This is a provider availability result, not an accuracy result. "
            "Do not quote the affected arm's scores.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
