# Current State

Last updated: 2026-09-28

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
- Garmin Activity Refresh는 기존 flat initial RAW를 유지하면서 activity별
  `snapshots/<content-sha256>/` history를 추가하고, accepted capture만 canonical row와 연결한다.
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
- 기존 Garmin activity 명시적 refresh(`garmin refresh <activity-id>`), immutable RAW snapshot
  history, Strength/Swim child replacement, canonical transaction rollback
- UNKNOWN/missing ACTIVE strength classification에 대한 동적 structured review state
- 명시 날짜 Garmin recovery/daily-health sync, partial endpoint failure 격리, immutable RAW
  capture history, 날짜별 latest-value upsert, date/provenance 조회와 CLI summary
- Nutrition meal/food profile domain, parser/repository ports, Decimal 기반 계산과 직렬화
- Nutrition meal/food profile SQLite repository와 supersession-aware append-only fact 저장

## Pending merge

- `feature/inbody-connector`: Samsung Health Data SDK Android diagnostic companion과 Python JSON source가
  feature branch에서 shared migration/DB/CLI까지 통합됐다. 사용자 Galaxy에서
  Professional Body Composition read와 SMM presence, Android actual-AAR build는 통과했다. 실제 exported
  JSON도 Windows RAW/normalization/SQLite에 저장됐고 동일 파일 재수집은 0건 추가로 idempotent했다.
  아직 main에는 merge하지 않았다.

## Verification

2026-09-28 Garmin activity refresh live E2E validation: 사용자가 이 Paseo 세션 밖에서
`MUSCLE50_HOME=C:\temp\muscle50-smoke`, 실제 Garmin 계정, activity 24481518495로
`uv run muscle50 garmin refresh 24481518495`를 실행했다. Strength sets 46건 교체, review
warning 없음, Garmin Connect에서 수동으로 수정한 종목 분류(DUMBBELL_HAMMER_CURL,
CLOSE_GRIP_EZ_BAR_BICEPS_CURL, INCLINE_SMITH_MACHINE_BENCH_PRESS, BENCH_PRESS,
CLOSE_GRIP_BARBELL_BENCH_PRESS 포함)가 canonical DB에 정확히 반영됨을 수동으로 확인했다.
1회성 수동 smoke이며 자동 테스트 스위트에는 포함되지 않는다. 상세는
`docs/HANDOFF.md`의 "Live E2E validation" 참고.

2026-09-27 Garmin activity refresh 작업(commit 전)에서 실행:

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src tests
git diff --check
```

결과: 전체 191 tests 통과, Ruff 통과, `mypy src tests` 통과(50 source files), diff whitespace
검사 통과. 커밋 직전 동일한 4개 명령을 재실행해 같은 결과(191 passed / Ruff 통과 / mypy 통과 /
diff --check 통과)를 다시 확인했다. 자동 테스트는 실제 Garmin API를 호출하지 않고 synthetic
payload만 사용한다 — 위 live E2E 절과는 별개다.

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

2026-09-18 InBody production integration에서 전체 241 tests, Ruff, `mypy src`(43 files), `uv build`,
`git diff --check`, Android actual-AAR `:app:assembleDebug`가 통과했다. clean temporary home의
`muscle50 inbody sync --file` 2회 smoke에서 migration 1~6, normalized 1 row, duplicate 0건 추가,
list/detail RAW 2 files를 확인했다.

## SQLite migrations

1. `001_initial.sql` — Garmin activity/RAW/correction 기본 schema
2. `002_strength_sets.sql` — normalized Garmin strength sets
3. `003_nutrition.sql` — Nutrition meal, food profile, append-only fact schema와 triggers
4. `004_swim_details.sql` — normalized pool swim activity/lap/length hierarchy
5. `005_daily_recovery.sql` — recovery RAW capture history와 날짜별 normalized latest row
6. `006_activity_refresh.sql` — activity refresh RAW capture history와 canonical accepted-capture pointer
7. `007_inbody.sql` — InBody RAW provenance, source identity, normalized body composition

`SqliteMealRepository`와 `SqliteFoodNutritionRepository`의 `migrate()`는 공용 numbered
migration loader를 사용한다. feature-local `nutrition_schema.sql`은 제거되어 schema source는
`003_nutrition.sql` 하나다. Recovery와 InBody repository도 같은 공용 numbered migration loader를
사용하며 feature-local `inbody_schema.sql`은 `007_inbody.sql`로 승격되어 제거됐다. InBody는
원래 `006_inbody.sql`로 준비됐으나, main이 같은 번호로 `006_activity_refresh.sql`을 먼저
통합해 실제 실행 시 `schema_migrations`의 `INSERT OR IGNORE ... VALUES (6, ...)`가 조용히
무시되고 InBody DDL만 버전 마커 없이 실행되는 충돌이 있었다. Integration 시점에 `007_inbody.sql`로
재번호를 매겨 해결했다.

## Known issues

- Garmin Connect 연동은 비공식 API이므로 인증 및 응답 shape 변경 위험이 있다.
- 실제 Garmin 계정/개인 데이터 기반 smoke test는 자동 검증에 포함하지 않는다. 2026-09-28에
  `garmin refresh`에 한해 1회 수동 live smoke(activity 24481518495)를 수행했지만, 이는
  자동 회귀 스위트를 대체하지 않는다.
- (future review-rule candidate, 아직 구현하지 않음) 2026-09-28 live 검증에서 ACTIVE
  strength set의 weight가 Garmin 분류상 정상인데도 `0.0 kg`로 기록되는 경우를 관찰했다
  (activity 24481518495, sequence 1, `DUMBBELL_HAMMER_CURL` / 8 reps / 0.0 kg). 현재
  `derive_activity_review()`는 UNKNOWN/missing 종목 분류만 검토 대상으로 삼고 weight 값은
  보지 않는다. 이 케이스에 대한 휴리스틱(예: ACTIVE set의 weight == 0 을 review 후보로
  표시)은 의도적으로 아직 추가하지 않았다 — 맨몸 운동(예: pull-up 변형)에서는 0 kg가
  정당할 수 있어 오탐 위험이 있으므로 더 많은 사례를 관찰한 뒤 규칙을 설계해야 한다.
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
- Refresh에서 Strength `exercise_sets` 또는 pool-swim `splits` endpoint가 실패하면 snapshot과
  warning은 보존하지만 불완전한 payload로 canonical child를 지우지 않고 refresh를 거부한다.
- Samsung Health live export에서 `dataSource.appId=com.inbody2014.inbody`, weight/BMI 2/2,
  SMM/BFM/PBF/BMR/FFM 1/2, TBW 0/2가 확인됐다. 독립적인 재-export 간 UID/appId 안정성과
  historical/backfill behavior는 아직 미확인이다.

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
- Activity refresh snapshot은 Recovery와 같은 content-addressed 패턴을 사용한다. 기존
  `activities.primary_raw_artifact_id`는 최초 import 증거를 계속 가리키고, 최신 성공 refresh는
  `activity_refresh_state.current_capture_id`로 별도 추적한다.
- Review 상태는 canonical `strength_sets`에서 동적으로 계산한다. 별도 persisted state는 최신
  canonical과 불일치할 위험만 늘리고 현재 요구에는 구체적 이점이 없어 추가하지 않았다.
