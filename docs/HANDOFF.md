# Session Handoff

Last updated: 2026-09-17

## Current task

최신 local `main` `7dad294` 기반 `feature/garmin-recovery-integration`에서 기존
`feature/garmin-recovery` 구현을 현재 Activity/Strength/Swim/Nutrition 구조에 맞춰
production integration하는 작업이다.

## Completed

- `muscle50 garmin recovery YYYY-MM-DD` production flow를 연결했다.
- 잘못된 날짜는 Garmin 인증/네트워크 전에 거부한다.
- sleep, HRV, resting HR, Body Battery, stress, training readiness/recovery time,
  training status, sleep respiration을 기존 feature 범위 그대로 정규화한다.
- endpoint별 `None`, `{}`, `[]` no-data를 정상 RAW로 보존하고 missing field를 `None`으로
  정규화한다. 개별 endpoint 오류/malformed payload는 warning으로 격리한다.
- 인증 오류는 즉시 실패하고, 전 endpoint 실패도 빈 성공으로 저장하지 않는다.
- recovery RAW를 `raw/garmin/recovery/<date>/<capture-id>/`의 content-addressed immutable
  snapshot으로 보존한다. 동일 payload+diagnostic은 재사용하고 변경 응답은 새 capture로 남긴다.
- 날짜별 normalized row는 latest accepted capture 기준으로 upsert하며 과거 RAW capture는
  삭제하지 않는다.
- `DailyRecoveryRepository.find()`와 `find_source_capture()`로 날짜별 최신 값과 provenance를
  조회한다.
- provisional `002_daily_recovery.sql` 대신 global chain의
  `005_daily_recovery.sql`을 추가했고 공용 sorted migration loader를 재사용한다.
- 기존 Activity RAW local backfill, Strength, Swim, Nutrition schema/repository 동작을 유지했다.
- 실제 Garmin API는 호출하지 않았고 synthetic/fake payload만 사용했다.

## Files changed

- `README.md`
- `docs/CURRENT_STATE.md`
- `docs/HANDOFF.md`
- `docs/garmin-recovery-endpoint-discovery.md`
- `src/muscle50/application/sync_garmin_recovery.py`
- `src/muscle50/cli.py`
- `src/muscle50/config.py`
- `src/muscle50/domain/recovery.py`
- `src/muscle50/domain/recovery_normalization.py`
- `src/muscle50/infrastructure/garmin/client.py`
- `src/muscle50/infrastructure/raw_store.py`
- `src/muscle50/infrastructure/sqlite/database.py`
- `src/muscle50/infrastructure/sqlite/migrations/005_daily_recovery.sql`
- `src/muscle50/presentation/terminal.py`
- `tests/test_cli.py`
- `tests/test_config.py`
- `tests/test_database.py`
- `tests/test_garmin_recovery_connector.py`
- `tests/test_recovery_normalization.py`
- `tests/test_sync_recovery.py`

## Verification performed

```text
uv sync --extra dev                                                   passed
uv run pytest tests/test_recovery_normalization.py
  tests/test_garmin_recovery_connector.py tests/test_sync_recovery.py
  tests/test_database.py tests/test_cli.py tests/test_config.py -q    37 passed
uv run pytest -q                                                     151 passed
uv run ruff check .                                                  passed
uv run mypy src tests                                                passed (44 files)
uv run pytest tests/test_database.py::test_recovery_migration_upgrades_existing_001_through_004_database
  tests/test_database.py::test_numbered_migrations_can_be_reapplied_without_duplicate_versions -q
                                                                        2 passed
git diff --check                                                     passed
```

Migration coverage includes fresh DB, existing 001–004 DB upgrade to version 5,
repeated invocation, concurrent first startup, and preservation of Strength/Swim/Nutrition tables.

## Remaining work

- 별도의 명시적 승인 하에서 실제 Garmin 계정 live smoke를 수행한다.
- training readiness/status shape, recovery time semantics, no-data responses,
  account/device별 endpoint availability와 timezone/calendar attribution을 확인한다.
- 7-day/28-day analytics, generic replay framework, scheduler/dashboard는 이번 범위 밖이다.

## Known issues / risks

- Garmin Connect는 비공식 API이므로 endpoint와 response shape가 바뀔 수 있다.
- Training status에서 여러 device의 서로 다른 값이 발견되면 임의 선택하지 않고 `None`으로 둔다.
- Recovery capture identity에는 payload뿐 아니라 endpoint diagnostic도 포함된다.
- Recovery는 shared `client.py`, `raw_store.py`, `database.py`, `cli.py`, `terminal.py`를 수정하므로
  main에 이후 병행 변경이 생기면 merge 전 재검증이 필요하다.

## Recommended next action

logical integration commit과 최종 Git 상태를 검토한다. Live Garmin smoke는 별도 승인 후 진행하고,
현재 작업에서는 main merge와 remote push를 하지 않는다.
