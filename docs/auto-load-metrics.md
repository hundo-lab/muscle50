# Auto Load Metrics on Garmin Sync (v1)

`muscle50 garmin latest` and `muscle50 garmin activities --from/--to` now fill the 10
activity-load metrics (`docs/garmin-analytics-prerequisites.md` section A) right after they
ingest, with the same RAW-only backfill and the same failure/warning rule as the `load_metrics`
stage of `muscle50 daily`. Running `garmin backfill-load-metrics` after an import is no longer
needed; that command stays for manual checks.

Spec: `docs/specs/auto-load-metrics.md`. No migration. Output change: additive (text only; neither
command has `--json`).

Not changed: the load-metric extraction rule, the shared normalizer (load metrics stay on their
own RAW-only path), `garmin refresh`, `garmin backfill-load-metrics`, and every byte of `daily`
(text and `--json`).

## Architecture

| Layer | Code |
| --- | --- |
| Application | `application/imported_load_metrics.py`: `check_imported_load_metrics` (the rule), `FillImportedLoadMetrics` (use case), `ImportedLoadMetricsResult` |
| Application | `application/daily_sync.py`: `RunDailySync._load_metrics` calls `check_imported_load_metrics`; its stage handling is unchanged |
| Output | `presentation/terminal.py`: `render_imported_load_metrics` |
| CLI | `cli.py`: `_garmin_latest` / `_garmin_activities` call `_fill_load_metrics` after printing the ingest output |

`FillImportedLoadMetrics` wraps the unchanged `BackfillActivityLoadMetrics` (no Garmin connector,
reads only each stored activity's initial `summary.json`, writes only the 10 load-metric rows).
The handler shares one `ActivityRepository` and one `RawStore` between the ingest and the fill.

"Stored in this run":

- `garmin latest`: the activity's ID when it was newly stored (`SyncResult.created`); otherwise none.
- `garmin activities`: every outcome with status `inserted`, the same expression `daily` uses.

## Commands

```powershell
muscle50 garmin latest
muscle50 garmin activities --from 2026-10-01 --to 2026-10-05
```

The existing output is unchanged and is followed, with no blank line, by the load-metric block.
It is always the last stdout lines (synthetic examples):

```text
새 activity 저장 완료
Garmin activity ID: 9002
종류: 러닝 (running)
이름: Synthetic Activity 9002
시작: 2026-10-05T07:00:00
시간: 00:30:00
Load metrics: metric rows inserted 10, updated 0, unchanged 0
```

Everything already stored (idempotent: unchanged only, nothing written):

```text
기간: 2026-10-01 ~ 2026-10-05
발견: 2건
신규 저장: 0건
이미 저장됨: 2건
실패: 0건
Load metrics: metric rows inserted 0, updated 0, unchanged 20
```

Block lines:

```text
Load metrics: metric rows inserted <n>, updated <n>, unchanged <n>   # omitted only if the backfill raised
Load metrics warning: <text>                                        # 0..2 lines, daily's order
Load metrics failed: <text>                                         # only on failure
```

The counts are `activity_metrics` rows across every stored activity, as in `daily`'s
`load_metrics` stage detail.

## Rules

The judgement is `daily`'s, from one shared function (`check_imported_load_metrics`); the texts are
identical to `daily`'s stage error and warnings:

- An activity stored in this run without a readable initial RAW summary (missing or unreadable
  `summary.json`) fails the step:
  `Load metrics failed: no readable RAW summary for activities imported in this run: <ids>`.
  A failure shows no warnings, as in `daily`.
- Otherwise these are warnings (exit code unchanged):
  - `<n> previously stored activities have no readable RAW summary (not from this run): <ids>`
  - `malformed load-metric values in activities imported in this run: <ids>`. The valid metrics of
    that activity are still stored; a malformed value is never coerced (missing is not zero).
  - Malformed values in older activities are not reported here (`garmin backfill-load-metrics` lists them).
- The step runs even when nothing new was stored; it then reports `unchanged` only.
- It runs only after an ingest that returned a result. Every existing ingestion error (no
  activities, login/connector/normalization/RAW errors, configuration error, bad dates rejected
  before authentication) exits 1 exactly as before, with empty stdout, and the step does not run.
- `garmin activities` with per-activity failures or a page-limit hit still exits 0 (unchanged);
  the step runs, and a failed activity is not stored, so it is not checked.
- A `sqlite3.Error` or `RawStoreError` raised by the backfill is caught, like `daily`'s stage
  handling: `Load metrics failed: <message>` (no counts line), exit 1. The ingest output is already
  printed and stays stored. Other exceptions propagate. (`garmin backfill-load-metrics` itself still
  lets `sqlite3.Error` propagate; unchanged.)
- Nothing in the step contacts Garmin or writes RAW, `activities`, strength or swim rows.

Exit codes:

| Case | Exit | Output |
| --- | --- | --- |
| Ingest ok, load ok (with or without warnings) | 0 | ingest output, then the block |
| `garmin activities` with per-activity failures or page limit | 0 (unchanged) | ingest output, then the block |
| Ingest ok, load failed (new gap or backfill exception) | 1 | same stdout plus the `failed` line; stderr: one `오류:` summary |
| Any existing ingestion error | 1 (unchanged) | stdout empty, stderr unchanged; the step does not run |
| Ctrl+C | 130 | as before |

The stderr summary on a load failure:

```text
오류: 이번 실행에서 저장한 activity의 load metric을 채우지 못했습니다. 저장된 activity와 RAW는 그대로 남아 있습니다.
```

It deliberately promises no repair (see Known issues).

## Tests

- `tests/test_daily_load_metrics_golden.py`: exact `daily --after-workout` text and JSON for an
  older RAW gap, both warnings (and an older malformed value that is not reported), and a new RAW
  gap that fails the stage. Captured before the rule was extracted and green before and after.
- `tests/test_auto_load_metrics.py`: both commands end to end with a fake Garmin session and
  synthetic RAW in a temporary home (fill, idempotent rerun, empty range, missing/unreadable new
  RAW, older gap warning, malformed warning, per-activity failure, backfill exception, Ctrl+C,
  ingestion failures that never reach the step, determinism), plus unit tests of the rule and the
  use case.

## Known issues / limitations

- A failed run downgrades on rerun. Once the activity is stored, a rerun no longer sees it as new,
  so a missing initial `summary.json` becomes the "previously stored" warning with exit 0. `daily`
  behaves the same way.
- No command recreates a lost initial `summary.json`: `garmin refresh` writes snapshots only.
- Every run re-checks all stored activities (one `summary.json` read each). Narrowing the check to
  newly stored activities is a follow-up candidate in the spec.
- Load metrics are not recomputed after `garmin refresh`; existing values are kept (spec limit).
- A backfill exception message is printed as received; the ASCII rule covers the block labels and
  the rule texts, not an exception message (the same as `daily`).
- Garmin live verification is a user gate; the tests use fakes only.
