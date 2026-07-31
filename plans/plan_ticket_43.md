# Plan — ACR-43: A8-2 Benchmark harness + A8-3 request-timing middleware

**Ticket:** [ACR-43](https://linear.app/chronos-laboral/issue/ACR-43/a8-2-a8-3-benchmark-harness-and-request-timing-middleware) (High, In Progress)
**Branch:** `ticket-43/bench-harness-request-timing`
**Worktree:** `/Users/jesusesgueva/dev/acra/acra-worktrees/ticket-43-bench-harness-request-timing`, cut from `origin/master` @ `7649a6e`
**Source plan:** `plans/plan_a8_a10_readiness.md` §2.3 items **A8-2** and **A8-3**
**Blockers:** none — both items are listed with no dependencies.

---

## 1. Current state

`plan_a8_a10_readiness.md` §1 claims "no measurement infrastructure of any kind." Re-verified on this
worktree — it holds, with one qualification: there is *ad-hoc* measurement, and it is duplicated.

| Fact | Evidence |
|---|---|
| No middleware except CORS | `backend/app/main.py:22-28` is the only `add_middleware` call |
| Logging is one global `basicConfig` | `backend/app/main.py:10-14` — plain text, no request context |
| Two loggers exist, both service-scoped | `app/services/delivery_service.py:25`, `app/services/ocr_service.py:25` |
| No per-request timing, request id, or route label | `grep` for `perf_counter` in `app/` returns nothing |
| Percentile math is hand-rolled and local | `backend/tests/integration/test_reservation_availability.py:343-345` sorts a list and does `timings_ms[int(len*0.95)-1]` inline |
| Evidence artifacts have a house style | `scripts/validation-run.sh:43-50` — `hdr()` emits title / captured+host / repo@tag(sha) / exact command / result |
| `validation-evidence/` is **gitignored** | `.gitignore:33` — artifacts are generated, never committed |
| Evidence tooling lives in `scripts/validation/` | `dump_routes.py`, `ocr_roundtrip.py`, `pipeline_trace.py`, invoked with `PYTHONPATH=$ROOT/backend` (`validation-run.sh:69,92,98`) |
| Coverage floor is on `app.*` only | `.github/workflows/ci.yml:55` — `--cov=app --cov-fail-under=85` |
| Cross-cutting concerns live in `app/core/` | `audit.py`, `config.py`, `database.py`, `rbac.py`, `security.py` |

**The single most useful thing this ticket removes** is `test_reservation_availability.py:343-345`.
A8-6 is an aggregation benchmark over that exact code path, and A8-5 needs the same percentile math
at 2/4/8/16/32 concurrency. Three copies of a hand-rolled nearest-rank index is how the numbers in
the A8 writeup end up disagreeing with each other.

### Port inconsistency found while exploring (not this ticket's to fix)

`scripts/validation-run.sh:36` defaults `DATABASE_URL` to port **5433**; `backend/tests/conftest.py:14`
and `tests/integration/test_reservation_availability.py:36` default to **5434**. `CLAUDE.md` documents
5433. The harness must therefore **record the port it actually used** rather than assume one — which
is itself an argument for A8-2. Noted for §7 of the readiness plan; not fixed here.

---

## 2. Decisions taken (no user input needed)

Per the readiness plan's own guidance, ambiguity resolvable by following an existing pattern is
resolved here rather than escalated:

1. **Harness lives at `backend/app/core/benchmark.py`.** It must be importable by pytest integration
   tests (`backend/` rootdir) *and* by `scripts/validation/*.py` (already run with
   `PYTHONPATH=$ROOT/backend`). `app/core/` is where cross-cutting modules already live, and it is
   the only location both callers reach with zero `sys.path` manipulation. Side effect, accepted
   deliberately: it falls under `--cov=app`, so the measurement tool is itself held to the 85% floor.
2. **Percentiles use nearest-rank**, `ceil(p/100 × n)` on the sorted sample, documented in the
   docstring. This matches the intent of the existing inline code and has no interpolation ambiguity
   to argue about in the writeup. `statistics.quantiles` is deliberately *not* used — its default
   interpolation would silently change published numbers.
3. **JSON logging is opt-in** via a new `log_format` setting (`text` default, `json` opt-in). Flipping
   every developer's console to JSON is a gratuitous change; CI and container runs set `LOG_FORMAT=json`.
4. **Logs label the route template**, not the raw path — `request.scope["route"].path` gives
   `/api/v1/deliveries/{delivery_id}`, falling back to `request.url.path` on 404 where no route
   matched. Logging raw paths would make every id its own cardinality bucket and make the API
   evidence row unaggregatable.
5. **Zero new dependencies.** Everything needed is stdlib (`statistics`, `json`, `uuid`, `platform`,
   `subprocess`, `time`). This is also a deliberate no-collision choice — ACR-42 owns
   `backend/requirements.txt` right now for the SDK pinning work.

---

## 3. Change list

### Create

| File | Purpose |
|---|---|
| `backend/app/core/benchmark.py` | **A8-2.** `percentiles()`, `RunMetadata`, `BenchmarkRun` — sample collection, p50/p95/p99, provenance capture, JSON + text artifact writers |
| `backend/app/core/observability.py` | **A8-3.** `configure_logging()`, `StructuredFormatter`, `RequestTimingMiddleware` |
| `backend/tests/test_benchmark.py` | Unit tests — percentile math, metadata capture, credential redaction, artifact shape |
| `backend/tests/test_observability.py` | Unit tests — middleware on 2xx / 4xx / 5xx, request-id propagation, formatter output |
| `scripts/validation/api_latency_bench.py` | Thin CLI driving `BenchmarkRun` against a live backend, matching the `dump_routes.py` / `pipeline_trace.py` pattern |
| `frontend/e2e/ticket-43.spec.ts` | E2E — every API response carries a correlatable `X-Request-ID` |

### Modify

| File | Change |
|---|---|
| `backend/app/main.py:10-14` | Replace `logging.basicConfig` with `configure_logging()` |
| `backend/app/main.py:22-28` | Register `RequestTimingMiddleware` (⚠️ `CLAUDE.md` flags `main.py` as the known concurrent-branch conflict point) |
| `backend/app/core/config.py:14` | Add `log_format: str = "text"` |
| `backend/tests/integration/test_reservation_availability.py:343-345` | Replace the inline percentile index with `percentiles()` — the duplication this ticket exists to remove |
| `scripts/validation-run.sh` | Add an API-latency stage (7/8) so the harness produces a real artifact, not unused scaffolding |
| `README.md` | Document the harness invocation and `LOG_FORMAT` |

---

## 4. API / contracts

**No schema change. No migration.** The next free Alembic revision stays `015` for whoever lands the
ledger. No new endpoints, no new privileges — RBAC is untouched.

### `app/core/benchmark.py`

```python
def percentiles(samples: Sequence[float], ps=(50, 95, 99)) -> dict[int, float]
    # nearest-rank; raises ValueError on empty input

@dataclass(frozen=True)
class RunMetadata:
    git_sha: str; git_tag: str; git_dirty: bool
    host: str; python_version: str; captured_at: str  # UTC ISO-8601
    command: str                                      # shlex.join(sys.argv)
    database: str                                     # host:port/dbname — credentials stripped
    params: dict[str, Any]
    @classmethod
    def capture(cls, **params) -> RunMetadata

class BenchmarkRun:
    def __init__(self, name: str, **params)
    def time(self) -> ContextManager[None]   # times a block, appends the sample
    def record(self, seconds: float) -> None
    @property def stats(self) -> dict        # n, min, max, mean, p50, p95, p99
    def write(self, out_dir: Path) -> tuple[Path, Path]   # <name>.json + <name>.txt
```

`<name>.txt` reuses the exact `validation-run.sh:43-50` header shape so the two tools' artifacts read
as one set. `<name>.json` is the machine-readable form a later no-regression gate can diff.

**Credential redaction is a hard requirement:** `DATABASE_URL` carries a password. `RunMetadata`
stores `host:port/dbname` only, and a test asserts the password never appears in either artifact.

### `app/core/observability.py`

One structured line per request:

```json
{"ts":"…","level":"INFO","logger":"acra.request","request_id":"a3f9c1d20b74",
 "method":"POST","route":"/api/v1/deliveries/{delivery_id}","status":200,"duration_ms":42.7}
```

- Request id: incoming `X-Request-ID` if present, else `uuid4().hex[:12]`; exposed on
  `request.state.request_id` and echoed as the `X-Request-ID` **response header** — that echo is what
  makes the log line correlatable from the client side, and it is what the e2e spec asserts.
- `time.perf_counter()` around `call_next`, in a **`try/finally`** so a raising handler is still
  logged (with `status=500`) and the exception still propagates to
  `main.py:41` `unhandled_exception_handler`. Getting this wrong would swallow 500s — hence a
  dedicated test.

---

## 5. Test plan

### Backend — `tests/test_benchmark.py`
- `percentiles` against a known vector `[1..100]` → p50=50, p95=95, p99=99.
- Edge cases: single sample (all percentiles equal it); `n=2`, `n=3`; unsorted input; empty raises
  `ValueError`.
- `RunMetadata.capture()` returns a non-empty git SHA and an ISO-8601 UTC timestamp.
- **Redaction:** a `DATABASE_URL` containing `hunter2` → that string appears in neither artifact.
- `write()` produces both files; the JSON round-trips; the text carries the 5-line provenance header.
- `BenchmarkRun.time()` accumulates one sample per entry.

### Backend — `tests/test_observability.py`
Driven through `TestClient` against a small local `FastAPI` app with the middleware attached, so
these do not depend on the RBAC mock sequence:
- 200 → exactly one `acra.request` record, with route template, status, positive `duration_ms`, and a
  request id.
- Supplied `X-Request-ID` is reused and echoed; absent → one is generated and echoed.
- 404 (no route matched) → logged with `status=404`, falling back to the raw path.
- **Handler raises → response is still the 500 JSON from `unhandled_exception_handler`, and the log
  line was still emitted.** This is the try/finally regression test.
- `StructuredFormatter` emits parseable JSON; `log_format="text"` keeps the human format.

### Regression
- Full `pytest tests/` must stay green — the middleware must not perturb the `require_privilege`
  3-query mock sequence documented in `CLAUDE.md`.
- Coverage: `--cov=app.core.benchmark --cov=app.core.observability` at ≥85%, plus the suite-wide
  `--cov=app --cov-fail-under=85` CI gate.

### Frontend
No component changes → no new Jest tests. `npx jest`, `npm run lint`, `npm run build` must stay green.

### E2E — `frontend/e2e/ticket-43.spec.ts`
Log in, navigate to Inventory, and assert every captured `/api/v1/**` response carries a non-empty
`X-Request-ID`. Run against `npm run build && npm run start`, never `next dev` (KI-02).

---

## 6. Live verification

1. `LOG_FORMAT=json uvicorn app.main:app --port 8000` → each request prints one JSON line with route
   template, status, duration, id.
2. `curl -i -H 'X-Request-ID: manual-trace-1' localhost:8000/health` → header echoed back **and** the
   same id in the log line.
3. Hit a 404 and a deliberately-failing route → both logged; the 500 still returns
   `{"detail": "Internal server error"}`.
4. `./scripts/validation-run.sh` → `validation-evidence/api-latency-bench.{json,txt}` exist, the text
   carries the provenance header, and the JSON has p50/p95/p99.
5. Browser pass over the app in both locales confirming nothing regressed and no console errors.

---

## 7. Risks / open questions

**No blocking questions.** Items 1–5 of §2 are decided.

| Risk | Handling |
|---|---|
| `main.py` conflicts with ACR-41/42/36 | `CLAUDE.md` already flags this; the change is 2 lines, resolve at merge by keeping all registrations |
| `BaseHTTPMiddleware` can mask exceptions | Explicit try/finally + the raising-handler test above |
| Timing middleware slows the suite | Measure suite wall-clock before/after; it is one `perf_counter` pair per request |
| Harness ships inside `app/` and thus the container image | Accepted — one stdlib-only module; noted for ACR-42 |
| Percentiles over small `n` are weakly meaningful | `stats` always reports `n`; artifacts show it, and the writeup must not quote p99 off 20 samples |

---

## 8. Build order

1. `app/core/benchmark.py` + `tests/test_benchmark.py` (tests alongside, not batched).
2. Swap `test_reservation_availability.py:343-345` onto `percentiles()`; confirm that test still passes.
3. `app/core/config.py` — add `log_format`.
4. `app/core/observability.py` + `tests/test_observability.py`.
5. Wire both into `main.py`; run the full backend suite for the RBAC-sequence regression.
6. `scripts/validation/api_latency_bench.py` + the new `validation-run.sh` stage; run it end to end.
7. `frontend/e2e/ticket-43.spec.ts` against a production build.
8. README notes.
9. Full gate: pytest + coverage, jest, lint, build, smoke, Playwright.
