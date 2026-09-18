# Current State

Last updated: 2026-09-19

## Project goal

muscle50는 개인 fitness 데이터를 로컬에 보존하고 RAW → NORMALIZED → DERIVED → REPORT
흐름으로 처리하는 Windows용 Python 프로젝트다.

## Current architecture

- Python 3.12 패키지와 `muscle50` CLI를 사용한다.
- 개인정보, Garmin token, RAW 파일, SQLite DB는 기본적으로
  `%LOCALAPPDATA%\muscle50`에 저장한다.
- Garmin Activity Sync는 immutable RAW artifact와 normalized SQLite activity를 분리한다.
- `IngestGarminActivity`(RAW capture → normalize → persist, Strength/Swim local backfill 포함)가
  단일 canonical per-activity ingestion path이며, `garmin latest`와 `garmin activities
  --from/--to`가 동일하게 이 경로를 사용한다.
- Garmin Recovery Sync는 endpoint별 content-addressed RAW snapshot history와 날짜별 최신
  normalized row를 분리하고, normalized row에서 accepted source capture를 추적한다.
- SQLite schema는 package에 포함된 numbered migration을 순서대로 적용한다.
- Garmin source 값과 corrected/derived 값은 서로 덮어쓰지 않는다.
- Nutrition Core는 deterministic domain model, JSON interchange schema, 공용 SQLite DB의
  append-only nutrition fact history를 제공한다.

## Implemented

- 최신 Garmin activity 1건 동기화 및 activity ID 기반 idempotency
- 날짜 범위 Garmin activity 동기화(`garmin activities --from/--to`): newest-first pagination,
  범위 밖 activity 발견 시 안전한 pagination 중단, 페이지 간 중복 activity 제거,
  activity별 실패 격리(inserted/skipped/failed count), `garmin latest`와 동일한 canonical
  per-activity ingestion path 재사용
- Garmin RAW JSON/original archive 보존과 normalized activity 저장
- 러닝, 수영, 웨이트 등 기본 activity 요약
- Garmin strength exercise set 정규화, SQLite 저장 및 기존 RAW 기반 local backfill
- Garmin 수영 activity/lap/length 정규화와 Garmin/corrected 거리 분리
- Garmin pool swim sync의 lap/length SQLite 저장, 조회, local RAW backfill 및 CLI summary
- 명시 날짜 Garmin recovery/daily-health sync, partial endpoint failure 격리, immutable RAW
  capture history, 날짜별 latest-value upsert, date/provenance 조회와 CLI summary
- Nutrition meal/food profile domain, parser/repository ports, Decimal 기반 계산과 직렬화
- Nutrition meal/food profile SQLite repository와 supersession-aware append-only fact 저장

## Not integrated

- `feature/inbody-connector`: 별도 integration 필요

## Verification

2026-09-19 garmin-activity-ingestion(날짜 범위 동기화) 작업에서 실행:

```powershell
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run mypy src tests
git diff --check
```

결과: 전체 178 tests 통과(기존 151 + 신규 27), Ruff 통과, `mypy src tests` 통과(47 files).
`garmin latest`, Strength, Swim 기존 회귀 테스트는 변경 없이 모두 통과했다. 실제 Garmin
API는 호출하지 않았고 synthetic fixture만 사용했다.

2026-09-17 Recovery production integration에서 실행:

```powershell
uv sync --extra dev
uv run pytest tests/test_recovery_normalization.py tests/test_garmin_recovery_connector.py
  tests/test_sync_recovery.py tests/test_database.py tests/test_cli.py tests/test_config.py -q
uv run pytest -q
uv run ruff check .
uv run mypy src tests
git diff --check
```

결과: recovery/migration/CLI subset 37 tests와 전체 151 tests 통과, Ruff 통과,
`mypy src tests` 통과. migration tests에서 새 DB의 001 → 005 순차 적용, 기존 001~004 DB의
version 5 추가, 전체 migration 반복 적용 idempotency를 확인했다.

## SQLite migrations

1. `001_initial.sql` — Garmin activity/RAW/correction 기본 schema
2. `002_strength_sets.sql` — normalized Garmin strength sets
3. `003_nutrition.sql` — Nutrition meal, food profile, append-only fact schema와 triggers
4. `004_swim_details.sql` — normalized pool swim activity/lap/length hierarchy
5. `005_daily_recovery.sql` — recovery RAW capture history와 날짜별 normalized latest row

`SqliteMealRepository`와 `SqliteFoodNutritionRepository`의 `migrate()`는 공용 numbered
migration loader를 사용한다. feature-local `nutrition_schema.sql`은 제거되어 schema source는
`003_nutrition.sql` 하나다. Recovery repository도 같은 공용 numbered migration loader를 사용한다.

## Known issues

- Garmin Connect 연동은 비공식 API이므로 인증 및 응답 shape 변경 위험이 있다.
- 실제 Garmin 계정/개인 데이터 기반 smoke test는 자동 검증에 포함하지 않는다.
- 실제 Garmin pool swim payload의 optional field 변형은 synthetic fixture 외에 아직 검증하지 않았다.
- Recovery endpoint의 training readiness/status, recovery time, no-data day, timezone/date attribution은
  synthetic payload만 검증했고 live smoke는 수행하지 않았다.
- swimming progression analytics용 기간/집계 read layer는 아직 없다.
- Nutrition은 아직 public CLI command에 연결되지 않았다.
- 기존 provisional nutrition schema로 직접 만든 외부 DB가 있다면 정식 migration marker가
  없으므로 별도 호환성 검토가 필요하다.
- InBody가 통합될 경우 migration 번호는 최신 global chain 5 이후로 다시 배정해야 한다.
- 날짜 범위 동기화의 pagination은 안전장치로 50페이지(최대 1000개 activity)까지만 조회한다.
  계정에 최근 activity가 매우 많으면 이 한도에 먼저 도달할 수 있으며, 이 경우 결과에
  `page_limit_reached`로 표시하고 조용히 잘라내지 않는다.

## Important decisions

- 미커밋 feature worktree는 integration agent가 대신 commit하거나 추정해 통합하지 않는다.
- `feature/strength-sets`를 migration 2로 먼저 통합하고, migration이 없는
  `feature/swim-details`를 그다음 통합했다.
- `feature/nutrition-core`의 provisional schema는 migration 3으로 승격하고 공용 loader에
  연결했다.
- 원본 feature branch와 Paseo worktree는 삭제하거나 수정하지 않는다.
- `feature/garmin-recovery`의 provisional migration 2는 가져오지 않고 최신 global chain의
  `005_daily_recovery.sql`로 재통합했다.
- Recovery endpoint는 개별 실패를 warning으로 격리하되 인증 오류와 전 endpoint 실패는 전체
  sync 실패로 처리한다.
- `SyncLatestGarminActivity.execute()`의 activity별 로직(RAW capture, normalize, Strength/Swim
  local backfill 포함)을 `IngestGarminActivity`로 추출해 `garmin latest`와 `garmin activities
  --from/--to`가 같은 코드를 공유하도록 했다. Swim이 필요로 하는 lap/length 계층은 이미
  모든 activity에서 무조건 가져오는 `splits` RAW로 충분해 새 RAW endpoint나 migration을
  추가하지 않았다.
- 날짜 범위 sync/run 결과는 CLI 출력의 inserted/skipped/failed count로 제공한다. 기존 스키마의
  `sync_runs` 테이블은 여전히 어떤 코드에서도 쓰지 않는 상태로 남겨 두었다 — command/error_code
  값 체계가 아직 정의되어 있지 않아 이번 범위에서 추측해 만들지 않았다.
