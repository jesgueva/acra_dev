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

**Known extension point.** A sample is currently one number: elapsed seconds. That covers A8-6
(aggregation latency at volume) as-is, and concurrency levels already fit through the free-form
`**params`. A8-5's three-arm ablation additionally needs *retry rate* and *correctness* per arm,
which this vocabulary cannot express — so it will want an outcome tag on `record()`/`time()` and a
counter in `stats`. That is deliberately not built yet: the three drawdown implementations fail in
different ways (optimistic-guard retry vs. SERIALIZABLE `40001` vs. unguarded lost update), and
guessing the schema before one exists would over-fit it. Extend here rather than starting a second
measurement structure alongside this one.
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
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.config import settings

DEFAULT_PERCENTILES: tuple[int, ...] = (50, 95, 99)

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
            command=shlex.join(sys.argv) if sys.argv else _UNKNOWN,
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


class BenchmarkRun:
    """Collects timing samples, then writes a JSON + text artifact pair.

    Usage:

        run = BenchmarkRun("api-latency", endpoint="/health", requests=200)
        for _ in range(200):
            with run.time():
                client.get("/health")
        run.write(Path("validation-evidence"))
    """

    def __init__(self, name: str, **params: Any) -> None:
        self.name = name
        self.metadata = RunMetadata.capture(**params)
        self._samples: list[float] = []

    def record(self, seconds: float) -> None:
        """Append one already-measured sample, in seconds."""
        if seconds < 0:
            raise ValueError(f"sample must be non-negative, got {seconds}")
        self._samples.append(seconds)

    @contextmanager
    def time(self) -> Iterator[None]:
        """Time the enclosed block and record it — including when it raises."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self._samples.append(time.perf_counter() - start)

    @property
    def samples_ms(self) -> list[float]:
        return [round(s * 1000, 3) for s in self._samples]

    @property
    def stats(self) -> dict[str, float]:
        """n / min / max / mean / p50 / p95 / p99, in milliseconds.

        `n` is always reported: a p99 over 20 samples is not a p99, and the artifact should make
        that impossible to hide.
        """
        ms = [s * 1000 for s in self._samples]
        pct = percentiles(ms, DEFAULT_PERCENTILES)
        return {
            "n": len(ms),
            "min_ms": round(min(ms), 3),
            "max_ms": round(max(ms), 3),
            "mean_ms": round(statistics.fmean(ms), 3),
            "p50_ms": round(pct[50], 3),
            "p95_ms": round(pct[95], 3),
            "p99_ms": round(pct[99], 3),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metadata": asdict(self.metadata),
            "stats": self.stats,
            "samples_ms": self.samples_ms,
        }

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
        lines = self.metadata.header_lines(f"benchmark: {self.name}", summary)
        if self.metadata.params:
            lines.append("")
            lines.append("Parameters")
            lines += [f"  {k:<20} {v}" for k, v in self.metadata.params.items()]
        lines.append("")
        lines.append("Latency (ms)")
        for key in ("n", "min_ms", "mean_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms"):
            lines.append(f"  {key:<20} {stats[key]}")

        txt_path = out / f"{self.name}.txt"
        txt_path.write_text("\n".join(lines) + "\n")
        return json_path, txt_path
