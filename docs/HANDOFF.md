# Session Handoff

Last updated: 2026-09-15

## Current task

최신 local `main` 기반 `feature/swim-integration`에서 기존 Garmin swim normalizer를
production sync, SQLite persistence, repository query, terminal summary에 연결하는 작업이다.

## Completed

- 작업 branch를 local `main` `0824c16`으로 fast-forward한 뒤 구현했다.
- `source_type_from()` 결과가 `lap_swimming`인 activity에만 기존
  `normalize_garmin_swim()`을 호출한다.
- `NormalizedActivity.swim_detail`을 통해 activity와 normalized swim hierarchy를 함께
  저장하고 조회한다.
- `004_swim_details.sql`에 `swim_activities`, `swim_laps`, `swim_lengths`를 추가했다.
- activity → lap → length foreign key와 sequence uniqueness로 hierarchy와 idempotency를
  보장한다.
- 기존 pool swim activity에 normalized rows가 없으면 로컬 `summary.json`,
  `activity.json`, optional `splits.json`만 사용해 backfill한다. Garmin API는 재호출하지 않는다.
- `muscle50 garmin latest` 결과에 normalized swim distance, lap/length 수, 평균 100m pace를
  표시한다.
- missing splits/optional values, empty laps/lengths, invalid duration, malformed hierarchy,
  non-pool activity와 Strength/일반 activity 회귀를 테스트했다.
- 실제 Garmin 계정 API는 호출하지 않았고 push/merge도 수행하지 않았다.

## Files changed

- `src/muscle50/application/sync_latest_garmin.py`
- `src/muscle50/domain/activity.py`
- `src/muscle50/domain/swim_normalization.py`
- `src/muscle50/domain/swimming.py`
- `src/muscle50/infrastructure/raw_store.py`
- `src/muscle50/infrastructure/sqlite/database.py`
- `src/muscle50/infrastructure/sqlite/migrations/004_swim_details.sql`
- `src/muscle50/presentation/terminal.py`
- `tests/test_database.py`
- `tests/test_swim_normalization.py`
- `tests/test_sync_latest.py`
- `docs/CURRENT_STATE.md`
- `docs/HANDOFF.md`

## Verification performed

```text
uv sync --extra dev                                                   passed
uv run pytest tests/test_swim_normalization.py tests/test_database.py
  tests/test_sync_latest.py -q                                       37 passed
uv run pytest -q                                                     126 passed
uv run ruff check .                                                  passed
uv run mypy src tests                                                passed (38 files)
git diff --check                                                     passed
```

migration test는 fresh DB, 기존 001~003 DB upgrade, repeated invocation, concurrent first
startup을 포함한다.

## Remaining work

- 별도의 명시적 단계에서 실제 Garmin pool swim 계정으로 live smoke를 수행한다.
- 실제 payload에서 device/API별 stroke, SWOLF, HR, rest/idle, missing length 변형을 확인한다.
- swimming progression analytics가 필요해지면 activity 기간 조회와 swim aggregate read/query
  layer를 추가한다.

## Known issues / risks

- Garmin Connect는 비공식 API이므로 splits response shape 변경 가능성이 있다.
- integration은 Garmin의 현재 pool type key인 `lap_swimming`만 허용한다. open-water swim은
  의도적으로 normalized lap/length persistence에 들어가지 않는다.
- `database.py`, `activity.py`, sync use-case, terminal renderer, migration test는 shared files라
  최신 main과 병행 변경이 생기면 충돌 가능성이 있다.
- 아직 통합되지 않은 InBody/Recovery migration은 global chain 4 이후 번호로 재배정해야 한다.

## Recommended next action

최종 quality gate를 확인하고 logical commit으로 정리한다. 그 뒤 live Garmin smoke는 별도
명시적 승인 하에서 수행한다. main merge와 remote push는 하지 않는다.
