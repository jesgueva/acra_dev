"""ACR-43 / A8-2 — the benchmark harness.

These are the tests that make the harness trustworthy enough to publish numbers from: the
percentile definition is pinned against a known vector, and the credential redaction is asserted
against both artifacts rather than assumed.
"""
import json
import subprocess

import pytest

from app.core.benchmark import (
    BenchmarkRun,
    Outcome,
    RunMetadata,
    percentiles,
    redact_command,
    redact_dsn,
)

#: The exact `stats` and `as_dict()` shapes A8-2 published. Pinned here because A8-5 added optional
#: keys to both, and a run that does not use outcomes must keep producing the original artifact —
#: see `test_outcome_free_run_is_shaped_exactly_as_before`.
A8_2_STATS_KEYS = {"n", "min_ms", "max_ms", "mean_ms", "p50_ms", "p95_ms", "p99_ms"}
A8_2_PAYLOAD_KEYS = {"name", "metadata", "stats", "samples_ms"}

# ---------------------------------------------------------------------------
# percentiles — nearest-rank, pinned


def test_percentiles_against_known_vector():
    """1..100 makes the nearest-rank definition unambiguous: pN is exactly N."""
    result = percentiles(list(range(1, 101)))
    assert result == {50: 50, 95: 95, 99: 99}


def test_percentiles_sorts_its_input():
    """Callers must not have to pre-sort.

    The fixture is chosen so the value sitting at the rank index in the *original* order (99)
    differs from the one in sorted order (50) — otherwise the test passes even with the sort
    removed, which is exactly what an earlier version of it did.
    """
    assert percentiles([50, 1, 99, 2, 95], (50,))[50] == 50


def test_percentiles_single_sample_collapses_to_it():
    assert percentiles([7.5]) == {50: 7.5, 95: 7.5, 99: 7.5}


@pytest.mark.parametrize(
    "samples,p,expected",
    [
        ([10, 20], 50, 10),      # ceil(0.5*2)=1 -> index 0
        ([10, 20], 100, 20),     # ceil(1.0*2)=2 -> index 1
        ([10, 20, 30], 50, 20),  # ceil(0.5*3)=2 -> index 1
        ([10, 20, 30], 95, 30),
    ],
)
def test_percentiles_small_samples(samples, p, expected):
    assert percentiles(samples, (p,))[p] == expected


def test_percentiles_never_interpolates():
    """Every returned value must be an observation that actually happened."""
    samples = [1.0, 2.0, 3.0, 4.0]
    for value in percentiles(samples, (50, 95, 99)).values():
        assert value in samples


def test_percentiles_rejects_empty_sample():
    with pytest.raises(ValueError, match="at least one sample"):
        percentiles([])


@pytest.mark.parametrize("bad", [0, -1, 101])
def test_percentiles_rejects_out_of_range(bad):
    with pytest.raises(ValueError, match="must be in"):
        percentiles([1, 2, 3], (bad,))


# ---------------------------------------------------------------------------
# redaction


@pytest.mark.parametrize(
    "url,expected",
    [
        ("postgresql+asyncpg://postgres:hunter2@localhost:5435/acra_db", "localhost:5435/acra_db"),
        ("postgresql://user:pw@db.example.com/acra", "db.example.com/acra"),
        ("", "unknown"),
        ("not-a-url", "unknown"),
    ],
)
def test_redact_dsn(url, expected):
    assert redact_dsn(url) == expected


def test_redact_dsn_handles_an_unparseable_url():
    """urlsplit raises on a malformed IPv6 literal — that must not take a benchmark run down."""
    assert redact_dsn("postgresql://user:pw@[::1/acra") == "unknown"


def test_redact_dsn_drops_the_password():
    assert "hunter2" not in redact_dsn(
        "postgresql+asyncpg://postgres:hunter2@localhost:5435/acra_db"
    )


def test_redact_command_drops_a_password_passed_as_a_flag():
    """`database` was redacted while `command` was captured verbatim — one leak reopens the other.

    `concurrency_bench.py` accepts `--dsn` on the command line, so the password reaches an artifact
    that gets committed under `validation-evidence/` unless the *command* is redacted too.
    """
    command = redact_command(
        ["bench.py", "--dsn", "postgresql+asyncpg://postgres:hunter2@localhost:5435/acra_db"]
    )

    assert "hunter2" not in command
    assert "postgresql+asyncpg://localhost:5435/acra_db" in command, (
        "the scheme and host must survive — a Command line that no longer runs is not provenance"
    )


def test_redact_command_handles_the_joined_spelling():
    """`--dsn=<url>` is one argv entry, so a per-argument check that only looks at bare values
    would walk straight past it."""
    command = redact_command(
        ["bench.py", "--dsn=postgresql://postgres:hunter2@db.example.com/acra"]
    )

    assert "hunter2" not in command
    assert "--dsn=postgresql://db.example.com/acra" in command


def test_redact_command_leaves_ordinary_arguments_alone():
    argv = ["bench.py", "out/", "--levels", "2,8,32", "--rounds", "5"]

    assert redact_command(argv) == "bench.py out/ --levels 2,8,32 --rounds 5"


def test_redact_command_leaves_a_credential_free_url_runnable():
    """`api_latency_bench.py --base-url` carries no password, and mangling it breaks the provenance.

    Redacting every `://` token would rewrite this to `staging.example.com`, which httpx reads as a
    relative path — so the `Command  :` line would no longer reproduce the run it documents. There
    is nothing to leak here, so there is nothing to redact.
    """
    argv = ["api_latency_bench.py", "out/", "--base-url", "https://staging.example.com"]

    assert redact_command(argv) == "api_latency_bench.py out/ --base-url https://staging.example.com"


def test_redact_command_keeps_a_credential_free_socket_dsn_intact():
    """No hostname and no credentials — `redact_dsn` alone would collapse this to `unknown`."""
    argv = ["bench.py", "--dsn", "postgresql:///acra?host=/var/run/postgresql"]

    assert redact_command(argv) == "bench.py --dsn 'postgresql:///acra?host=/var/run/postgresql'"


def test_redact_command_fails_closed_on_an_unparseable_url():
    """If it cannot be parsed it cannot be proven safe, so it must not be echoed verbatim."""
    command = redact_command(["bench.py", "--dsn", "postgresql://user:hunter2@[::1/acra"])

    assert "hunter2" not in command


# ---------------------------------------------------------------------------
# RunMetadata


def test_metadata_capture_records_provenance(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:hunter2@localhost:5435/acra_db"
    )
    meta = RunMetadata.capture(scale=10)

    # Not just "non-empty" — the _UNKNOWN sentinel is itself a non-empty string, so a truthiness
    # check cannot tell a captured SHA from git having failed outright.
    assert meta.git_sha != "unknown", "provenance must be a real SHA, not the failure sentinel"
    assert all(c in "0123456789abcdef" for c in meta.git_sha)
    assert meta.captured_at.endswith("+00:00"), "timestamp must be explicit UTC"
    assert meta.python_version.count(".") == 2
    assert meta.database == "localhost:5435/acra_db"
    assert meta.params == {"scale": 10}
    assert isinstance(meta.git_dirty, bool)


def test_metadata_falls_back_to_settings_when_env_is_unset(monkeypatch):
    """The documented local setup keeps DATABASE_URL in backend/.env, not the shell.

    pydantic-settings reads that file without populating os.environ, so reading only the env var
    would record "unknown" for the database on a normal developer machine — losing exactly the
    provenance this class exists to capture.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "app.core.benchmark.settings.database_url",
        "postgresql+asyncpg://postgres:hunter2@localhost:5999/from_env_file",
    )

    meta = RunMetadata.capture()

    assert meta.database == "localhost:5999/from_env_file"
    assert "hunter2" not in meta.database


def test_metadata_prefers_the_env_var_over_settings(monkeypatch):
    """validation-run.sh and CI export DATABASE_URL; that must win over the .env default."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@exported:5555/exported_db")
    monkeypatch.setattr(
        "app.core.benchmark.settings.database_url",
        "postgresql+asyncpg://u:p@dotenv:5435/dotenv_db",
    )

    assert RunMetadata.capture().database == "exported:5555/exported_db"


def test_metadata_capture_survives_git_failure(monkeypatch):
    """A tarball export with no .git must still produce an artifact, just a less traceable one."""
    monkeypatch.setattr(
        "app.core.benchmark.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no git")),
    )
    meta = RunMetadata.capture()
    assert meta.git_sha == "unknown"
    assert meta.git_dirty is False, "a failed git call says nothing about the tree"
    assert meta.git_tag == "untagged"


def test_metadata_capture_handles_nonzero_git(monkeypatch):
    monkeypatch.setattr(
        "app.core.benchmark.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a, 128, stdout="", stderr="fatal"),
    )
    assert RunMetadata.capture().git_sha == "unknown"


def test_header_lines_match_validation_run_shape():
    meta = RunMetadata.capture()
    lines = meta.header_lines("benchmark: demo", "n=3")

    assert lines[0] == "ACRA MES — benchmark: demo"
    assert lines[1].startswith("Captured : ")
    assert lines[2].startswith("Repo     : acra_dev @ ")
    assert lines[3].startswith("Command  : ")
    assert lines[4] == "Result   : n=3"
    assert set(lines[5]) == {"-"}


# ---------------------------------------------------------------------------
# BenchmarkRun


def test_record_and_stats():
    run = BenchmarkRun("demo")
    for seconds in (0.001, 0.002, 0.003, 0.004):
        run.record(seconds)

    stats = run.stats
    assert stats["n"] == 4
    assert stats["min_ms"] == 1.0
    assert stats["max_ms"] == 4.0
    assert stats["mean_ms"] == 2.5
    assert stats["p50_ms"] == 2.0


def test_record_rejects_negative():
    with pytest.raises(ValueError, match="non-negative"):
        BenchmarkRun("demo").record(-0.1)


def test_time_context_manager_collects_one_sample_per_entry():
    run = BenchmarkRun("demo")
    for _ in range(3):
        with run.time():
            pass
    assert run.stats["n"] == 3
    assert all(s >= 0 for s in run.samples_ms)


def test_time_records_even_when_the_block_raises():
    """A benchmark that drops its slowest samples because they errored is worse than none."""
    run = BenchmarkRun("demo")
    with pytest.raises(RuntimeError):
        with run.time():
            raise RuntimeError("boom")
    assert run.stats["n"] == 1


def test_stats_on_empty_run_raises():
    with pytest.raises(ValueError, match="at least one sample"):
        _ = BenchmarkRun("demo").stats


def test_write_produces_both_artifacts(tmp_path):
    run = BenchmarkRun("api-latency", endpoint="/health", requests=3)
    for seconds in (0.010, 0.020, 0.030):
        run.record(seconds)

    json_path, txt_path = run.write(tmp_path)
    assert json_path.name == "api-latency.json"
    assert txt_path.name == "api-latency.txt"

    payload = json.loads(json_path.read_text())
    assert payload["name"] == "api-latency"
    assert payload["stats"]["n"] == 3
    assert payload["samples_ms"] == [10.0, 20.0, 30.0], "raw samples must be recomputable"
    assert payload["metadata"]["params"] == {"endpoint": "/health", "requests": 3}

    text = txt_path.read_text()
    assert text.startswith("ACRA MES — benchmark: api-latency")
    assert "p95=" in text
    assert "endpoint" in text and "/health" in text
    assert "p99_ms" in text


def test_write_creates_the_output_directory(tmp_path):
    run = BenchmarkRun("demo")
    run.record(0.001)
    json_path, _ = run.write(tmp_path / "validation-evidence" / "nested")
    assert json_path.exists()


def test_written_artifacts_never_contain_the_password(tmp_path, monkeypatch):
    """The redaction guarantee, asserted end to end on both files."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://postgres:hunter2@localhost:5435/acra_db"
    )
    run = BenchmarkRun("secretless")
    run.record(0.001)
    json_path, txt_path = run.write(tmp_path)

    assert "hunter2" not in json_path.read_text()
    assert "hunter2" not in txt_path.read_text()
    assert "localhost:5435/acra_db" in json_path.read_text()


# ---------------------------------------------------------------------------
# Outcomes (A8-5) — the three-arm ablation's vocabulary
#
# The backward-compatibility tests come first on purpose: A8-2's numbers are already published, and
# the whole extension is only safe if a run that ignores outcomes is untouched by it.


def test_outcome_free_run_is_shaped_exactly_as_before(tmp_path):
    """The regression guard. A run that never names an outcome must serialise as it did in A8-2.

    Asserted as exact key *sets*, not `>=`: a superset check would pass while quietly adding the
    outcome block to every existing artifact, which is the exact failure this guards.
    """
    run = BenchmarkRun("api-latency", endpoint="/health", requests=3)
    for seconds in (0.010, 0.020, 0.030):
        run.record(seconds)

    assert set(run.stats) == A8_2_STATS_KEYS
    assert set(run.as_dict()) == A8_2_PAYLOAD_KEYS

    _, txt_path = run.write(tmp_path)
    text = txt_path.read_text()
    assert "Outcomes" not in text
    assert "success=" not in text
    assert "_ok_ms" not in text


def test_explicitly_ok_outcomes_still_count_as_outcome_free(tmp_path):
    """Passing `Outcome.OK` by hand is not "using outcomes" — it is the default said aloud."""
    run = BenchmarkRun("demo")
    run.record(0.001, Outcome.OK)
    with run.time(Outcome.OK):
        pass

    assert set(run.stats) == A8_2_STATS_KEYS
    assert "Outcomes" not in run.write(tmp_path)[1].read_text()


def test_time_defaults_to_ok():
    run = BenchmarkRun("demo")
    with run.time():
        pass
    assert run.outcomes == [Outcome.OK]


def test_outcome_counts_and_rates():
    run = BenchmarkRun("arm")
    run.record(0.001, Outcome.OK)
    run.record(0.002, Outcome.OK)
    run.record(0.003, Outcome.CONFLICT)
    run.record(0.004, Outcome.SERIALIZATION_FAILURE)
    run.record(0.005, Outcome.ERROR)

    stats = run.stats
    assert stats["n"] == 5
    assert stats["outcomes"] == {
        "ok": 2,
        "conflict": 1,
        "serialization_failure": 1,
        "error": 1,
    }
    assert stats["success_rate"] == 0.4
    # conflict + serialization_failure — the two a caller could retry into a success.
    assert stats["retry_rate"] == 0.4
    assert stats["error_rate"] == 0.2


def test_lost_update_is_counted_but_never_called_retryable():
    """Retrying silent corruption does not fix it, so it must not inflate the retry rate."""
    run = BenchmarkRun("unguarded")
    run.record(0.001, Outcome.OK)
    run.record(0.002, Outcome.LOST_UPDATE)

    stats = run.stats
    assert stats["lost_update_count"] == 1
    assert stats["retry_rate"] == 0.0
    assert stats["error_rate"] == 0.0


def test_success_percentiles_are_reported_separately():
    """A fast abort is not a fast operation.

    The failures here are deliberately the *quick* samples: if aborts were folded into the headline
    percentiles, the arm would look faster than it is. p50 over everything and p50 over successes
    must therefore disagree — that disagreement is the point of the split.
    """
    run = BenchmarkRun("arm")
    for seconds in (0.001, 0.002):
        run.record(seconds, Outcome.CONFLICT)
    for seconds in (0.100, 0.200):
        run.record(seconds, Outcome.OK)

    stats = run.stats
    assert stats["p50_ms"] == 2.0
    assert stats["p50_ok_ms"] == 100.0


def test_success_percentiles_omitted_when_nothing_succeeded():
    """An arm can lose every attempt; that must produce a report, not a ValueError."""
    run = BenchmarkRun("arm")
    run.record(0.001, Outcome.CONFLICT)

    stats = run.stats
    assert stats["success_rate"] == 0.0
    assert "p50_ok_ms" not in stats


def test_time_marks_an_escaping_exception_as_error():
    """An attempt that blew up is not a successful one."""
    run = BenchmarkRun("arm")
    with pytest.raises(RuntimeError):
        with run.time():
            raise RuntimeError("boom")

    assert run.outcomes == [Outcome.ERROR]
    assert run.stats["error_rate"] == 1.0


def test_caller_classification_survives_an_exception():
    """A 40001 that the driver already recognised must not be relabelled as a generic error."""
    run = BenchmarkRun("arm")
    with pytest.raises(RuntimeError):
        with run.time() as sample:
            sample.outcome = Outcome.SERIALIZATION_FAILURE
            raise RuntimeError("could not serialize access")

    assert run.outcomes == [Outcome.SERIALIZATION_FAILURE]
    assert run.stats["retry_rate"] == 1.0


def test_outcome_set_inside_the_block_is_recorded():
    run = BenchmarkRun("arm")
    with run.time() as sample:
        sample.outcome = Outcome.CONFLICT
    assert run.outcomes == [Outcome.CONFLICT]


def test_record_accepts_the_string_form():
    """Drivers deserialising an arm name from argv should not have to import the enum."""
    run = BenchmarkRun("arm")
    run.record(0.001, "conflict")
    assert run.outcomes == [Outcome.CONFLICT]


def test_record_rejects_an_unknown_outcome():
    with pytest.raises(ValueError):
        BenchmarkRun("arm").record(0.001, "probably_fine")


def test_outcomes_reach_both_artifacts(tmp_path):
    run = BenchmarkRun("ablation-optimistic-8", arm="optimistic", level=8)
    run.record(0.010, Outcome.OK)
    run.record(0.020, Outcome.CONFLICT)

    json_path, txt_path = run.write(tmp_path)

    payload = json.loads(json_path.read_text())
    assert payload["stats"]["outcomes"] == {"ok": 1, "conflict": 1}
    # Per-sample outcomes ride along so a later gate can recompute rather than trust the summary,
    # matching why raw samples_ms is already written.
    assert payload["outcomes_by_sample"] == ["ok", "conflict"]

    text = txt_path.read_text()
    assert "Outcomes" in text
    assert "success=50%" in text
    assert text.index("Outcomes") < text.index("Latency (ms)"), (
        "correctness must be read before speed — the fastest arm is the incorrect one"
    )
