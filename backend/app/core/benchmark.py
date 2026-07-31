"""A8-2 — reusable benchmark harness for the evidence package.

Before this module the repo had no measurement infrastructure: percentile math was hand-rolled
inline at the one call site that needed it (`tests/integration/test_reservation_availability.py`),
and nothing captured *how* a number was produced. A benchmark result that cannot be traced back to
a commit, a host, and an exact command is not evidence.

Three pieces, used together:

    percentiles()   nearest-rank p50/p95/p99, defined once so published numbers agree
    RunMetadata     git SHA / tag / dirty, host, Python, database, UTC timestamp, exact command
    BenchmarkRun    collects timings, then writes a JSON + text artifact pair

Artifacts land under `validation-evidence/` (gitignored — generated, never committed) and carry the
same provenance header `scripts/validation-run.sh` puts on its captures, so the two tools' outputs
read as one set.

Percentiles are **nearest-rank**: `rank = ceil(p/100 × n)` on the sorted sample, clamped to
`[1, n]`. `statistics.quantiles` is deliberately not used — it interpolates between samples, and
switching methods would silently move every number already published.

**Outcomes (A8-5).** A sample is a duration *and* an `Outcome`. A8-2 needed only the duration; the
three-arm ablation needs to say which attempts won, which were told to retry, and which silently
corrupted the books — a duration alone cannot distinguish a fast success from a fast abort, and an
arm that fails instantly would otherwise post the best latency in the table.

The vocabulary is deliberately small and maps to how the three drawdown shapes actually fail:

    ok                      the attempt did the work
    conflict                deterministic loser — ADR-02's 409
    serialization_failure   PostgreSQL SQLSTATE 40001, SERIALIZABLE's abort
    error                   anything else
    lost_update             a correctness violation, recorded by the caller's oracle

`Outcome.OK` is the default everywhere, and **a run that never names another outcome serialises
exactly as it did before this was added** — `stats` keeps its original seven keys and `as_dict()`
its original shape. That is load-bearing: A8-2's published numbers must not move because A8-5
extended the library underneath them.
"""
from __future__ import annotations

import json
import math
import os
import platform
import shlex
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings

DEFAULT_PERCENTILES: tuple[int, ...] = (50, 95, 99)


class Outcome(str, Enum):
    """How one attempt ended. See the module docstring for why duration alone is not enough."""

    OK = "ok"
    CONFLICT = "conflict"
    SERIALIZATION_FAILURE = "serialization_failure"
    ERROR = "error"
    LOST_UPDATE = "lost_update"


#: Outcomes that a caller could retry into a success. Kept separate from `ERROR`, which is a bug,
#: and from `LOST_UPDATE`, which is silent corruption — retrying that would not help.
RETRYABLE_OUTCOMES = frozenset({Outcome.CONFLICT, Outcome.SERIALIZATION_FAILURE})

# app/core/benchmark.py -> app/core -> app -> backend -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]

_UNKNOWN = "unknown"


def percentiles(
    samples: Sequence[float], ps: Sequence[int] = DEFAULT_PERCENTILES
) -> dict[int, float]:
    """Nearest-rank percentiles of `samples`.

    `rank = ceil(p/100 × n)`, clamped into `[1, n]`, indexing the sorted sample. No interpolation,
    so every returned value is an observation that actually happened.

    Raises ValueError on an empty sample or a percentile outside `(0, 100]`.
    """
    if not samples:
        raise ValueError("percentiles() needs at least one sample")

    ordered = sorted(samples)
    n = len(ordered)
    result: dict[int, float] = {}
    for p in ps:
        if not 0 < p <= 100:
            raise ValueError(f"percentile must be in (0, 100], got {p}")
        rank = min(max(math.ceil(p / 100 * n), 1), n)
        result[int(p)] = ordered[rank - 1]
    return result


def _git(*args: str) -> str:
    """Run a git command at the repo root, returning `_UNKNOWN` if it fails for any reason."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return _UNKNOWN
    return out.stdout.strip() if out.returncode == 0 else _UNKNOWN


def redact_dsn(url: str) -> str:
    """Reduce a database URL to `host:port/dbname`, dropping the credentials.

    `DATABASE_URL` carries a password. Benchmark artifacts get read, pasted into writeups and
    attached to tickets, so the password must never reach one.
    """
    if not url:
        return _UNKNOWN
    try:
        parts = urlsplit(url)
    except ValueError:
        return _UNKNOWN
    if not parts.hostname:
        return _UNKNOWN
    host = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    return f"{host}{parts.path}"


def redact_command(argv: list[str]) -> str:
    """`shlex.join(argv)` with any argument that looks like a database URL reduced to host/db.

    `redact_dsn` keeps the password out of the `database` field, but the *command* is captured
    verbatim — so a bench invoked as `--dsn postgresql://user:password@host/db` writes the password
    straight into an artifact that gets committed under `validation-evidence/` and pasted into
    writeups. The redaction has to cover both paths or it only covers the one nobody uses.

    Both spellings are handled: `--dsn <url>` as two argv entries, and `--dsn=<url>` as one.
    """
    cleaned: list[str] = []
    for arg in argv:
        flag, sep, value = arg.partition("=")
        if sep and "://" in value:
            cleaned.append(f"{flag}={redact_dsn(value)}")
        elif "://" in arg:
            cleaned.append(redact_dsn(arg))
        else:
            cleaned.append(arg)
    return shlex.join(cleaned)


@dataclass(frozen=True)
class RunMetadata:
    """Everything needed to repeat a run, captured at the moment it happened."""

    git_sha: str
    git_tag: str
    git_dirty: bool
    host: str
    python_version: str
    database: str
    captured_at: str
    command: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def capture(cls, **params: Any) -> RunMetadata:
        # A git call that failed says nothing about the tree — it must not be reported as dirty,
        # which is what a bare truthiness check on the `_UNKNOWN` sentinel would do.
        status = _git("status", "--porcelain")
        tag = _git("describe", "--tags")
        return cls(
            git_sha=_git("rev-parse", "--short", "HEAD"),
            git_tag="untagged" if tag == _UNKNOWN else tag,
            git_dirty=status != _UNKNOWN and bool(status.strip()),
            host=f"{platform.system()} {platform.release()} {platform.machine()}",
            python_version=platform.python_version(),
            # Env first (validation-run.sh and CI export it), then the app's own settings.
            # Reading only os.environ would report "unknown" in the documented local setup, where
            # DATABASE_URL lives in backend/.env — pydantic-settings loads that file without
            # populating os.environ, so the provenance would silently lose the database it ran on.
            database=redact_dsn(os.getenv("DATABASE_URL") or settings.database_url),
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            command=redact_command(sys.argv) if sys.argv else _UNKNOWN,
            params=dict(params),
        )

    def header_lines(self, title: str, result: str) -> list[str]:
        """The `scripts/validation-run.sh` `hdr()` shape, so artifacts read uniformly."""
        dirty = " +dirty" if self.git_dirty else ""
        return [
            f"ACRA MES — {title}",
            f"Captured : {self.captured_at}  (host: {self.host})",
            f"Repo     : acra_dev @ {self.git_tag} ({self.git_sha}{dirty})",
            f"Command  : {self.command}",
            f"Result   : {result}",
            "-" * 79,
        ]


@dataclass
class Sample:
    """Handle yielded by `BenchmarkRun.time()` so the caller can classify what just happened.

    An attempt's outcome is usually only knowable *after* the block has run — a worksheet close
    either wins or comes back 409 — so this is settable rather than an argument-only.
    """

    outcome: Outcome = Outcome.OK


class BenchmarkRun:
    """Collects timing samples, then writes a JSON + text artifact pair.

    Usage:

        run = BenchmarkRun("api-latency", endpoint="/health", requests=200)
        for _ in range(200):
            with run.time():
                client.get("/health")
        run.write(Path("validation-evidence"))

    With outcomes (A8-5), when the attempt can fail in more than one way:

        with run.time() as sample:
            sample.outcome = Outcome.CONFLICT
    """

    def __init__(self, name: str, **params: Any) -> None:
        self.name = name
        self.metadata = RunMetadata.capture(**params)
        self._samples: list[float] = []
        self._outcomes: list[Outcome] = []

    def record(self, seconds: float, outcome: Outcome = Outcome.OK) -> None:
        """Append one already-measured sample, in seconds, with how the attempt ended."""
        if seconds < 0:
            raise ValueError(f"sample must be non-negative, got {seconds}")
        self._samples.append(seconds)
        self._outcomes.append(Outcome(outcome))

    @contextmanager
    def time(self, outcome: Outcome = Outcome.OK) -> Iterator[Sample]:
        """Time the enclosed block and record it — including when it raises.

        `outcome` seeds the sample; reassign `sample.outcome` inside the block to classify after
        the fact. An exception escaping the block is recorded as `Outcome.ERROR` unless the caller
        already said otherwise — an attempt that blew up is not a successful one, and folding it
        into the success latencies is how a broken arm looks fast.
        """
        handle = Sample(outcome=Outcome(outcome))
        start = time.perf_counter()
        try:
            yield handle
        except BaseException:
            if handle.outcome is Outcome.OK:
                handle.outcome = Outcome.ERROR
            raise
        finally:
            self._samples.append(time.perf_counter() - start)
            self._outcomes.append(handle.outcome)

    @property
    def samples_ms(self) -> list[float]:
        return [round(s * 1000, 3) for s in self._samples]

    @property
    def outcomes(self) -> list[Outcome]:
        return list(self._outcomes)

    @property
    def _has_outcomes(self) -> bool:
        """True once any attempt ended as something other than OK.

        Gates every addition below, so a run that never classifies anything serialises byte for
        byte as it did before outcomes existed — A8-2's published artifacts must not move.
        """
        return any(o is not Outcome.OK for o in self._outcomes)

    @property
    def stats(self) -> dict[str, float]:
        """n / min / max / mean / p50 / p95 / p99, in milliseconds.

        `n` is always reported: a p99 over 20 samples is not a p99, and the artifact should make
        that impossible to hide.

        When outcomes are in play this also carries per-outcome counts, the derived success/retry/
        error rates, and a second percentile set over the successful attempts only — reported
        alongside the all-attempt figures rather than replacing them, because both are needed to
        read an arm honestly.
        """
        ms = [s * 1000 for s in self._samples]
        pct = percentiles(ms, DEFAULT_PERCENTILES)
        result: dict[str, Any] = {
            "n": len(ms),
            "min_ms": round(min(ms), 3),
            "max_ms": round(max(ms), 3),
            "mean_ms": round(statistics.fmean(ms), 3),
            "p50_ms": round(pct[50], 3),
            "p95_ms": round(pct[95], 3),
            "p99_ms": round(pct[99], 3),
        }
        if not self._has_outcomes:
            return result

        counts = Counter(self._outcomes)
        n = len(ms)
        result["outcomes"] = {o.value: counts[o] for o in Outcome if counts[o]}
        result["success_rate"] = round(counts[Outcome.OK] / n, 4)
        result["retry_rate"] = round(
            sum(counts[o] for o in RETRYABLE_OUTCOMES) / n, 4
        )
        result["error_rate"] = round(counts[Outcome.ERROR] / n, 4)
        result["lost_update_count"] = counts[Outcome.LOST_UPDATE]

        ok_ms = [d for d, o in zip(ms, self._outcomes) if o is Outcome.OK]
        if ok_ms:
            ok_pct = percentiles(ok_ms, DEFAULT_PERCENTILES)
            result["p50_ok_ms"] = round(ok_pct[50], 3)
            result["p95_ok_ms"] = round(ok_pct[95], 3)
            result["p99_ok_ms"] = round(ok_pct[99], 3)
        return result

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "metadata": asdict(self.metadata),
            "stats": self.stats,
            "samples_ms": self.samples_ms,
        }
        if self._has_outcomes:
            payload["outcomes_by_sample"] = [o.value for o in self._outcomes]
        return payload

    def write(self, out_dir: Path | str) -> tuple[Path, Path]:
        """Write `<name>.json` and `<name>.txt`, returning both paths.

        Raw samples go into the JSON so a later no-regression gate can recompute rather than trust
        the summary.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        # `stats` re-sorts and re-reduces on every access, so take one snapshot for both artifacts.
        payload = self.as_dict()
        stats = payload["stats"]

        json_path = out / f"{self.name}.json"
        json_path.write_text(json.dumps(payload, indent=2) + "\n")

        summary = (
            f"n={stats['n']}  p50={stats['p50_ms']:.1f}ms  "
            f"p95={stats['p95_ms']:.1f}ms  p99={stats['p99_ms']:.1f}ms"
        )
        if self._has_outcomes:
            summary += f"  success={stats['success_rate']:.0%}  retry={stats['retry_rate']:.0%}"
        lines = self.metadata.header_lines(f"benchmark: {self.name}", summary)
        if self.metadata.params:
            lines.append("")
            lines.append("Parameters")
            lines += [f"  {k:<20} {v}" for k, v in self.metadata.params.items()]
        if self._has_outcomes:
            # Correctness before speed, deliberately: the fastest arm here is the one that takes no
            # locks, and a reader who meets its latency first has already been misled.
            lines.append("")
            lines.append("Outcomes")
            for name, count in stats["outcomes"].items():
                lines.append(f"  {name:<22} {count}")
            for key in ("success_rate", "retry_rate", "error_rate", "lost_update_count"):
                lines.append(f"  {key:<20} {stats[key]}")
        lines.append("")
        lines.append("Latency (ms)")
        for key in ("n", "min_ms", "mean_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms"):
            lines.append(f"  {key:<20} {stats[key]}")
        if self._has_outcomes and "p50_ok_ms" in stats:
            for key in ("p50_ok_ms", "p95_ok_ms", "p99_ok_ms"):
                lines.append(f"  {key:<20} {stats[key]}")

        txt_path = out / f"{self.name}.txt"
        txt_path.write_text("\n".join(lines) + "\n")
        return json_path, txt_path
