# Current State

Last updated: 2026-09-30

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
- Garmin list endpoint와 detail endpoint의 payload shape는 다르며 코드가 이를 명시적으로 구분한다.
  `list_activities`/`latest_summary`는 측정값을 top-level flat key로 주고, `get_activity`는
  identity/name/type/timezone만 top-level에 두고 측정값을 `summaryDTO`에 중첩한다. Refresh는
  `_detail_summary()`로 `summaryDTO`를 top-level 위에 병합해 normalize에 넘긴다.
- SQLite schema는 package에 포함된 numbered migration을 순서대로 적용한다.
- Garmin source 값과 corrected/derived 값은 서로 덮어쓰지 않는다.
- Nutrition Core는 deterministic domain model, JSON interchange schema, 공용 SQLite DB의
  append-only nutrition fact history를 제공한다.
- Activity-load metric(training load/effect, HR zone, intensity minutes)은 shared
  `normalize_activity`가 아니라 전용 RAW-only backfill(`garmin backfill-load-metrics`)이 초기 flat
  `summary.json`에서 `activity_metrics`로 쓴다. Refresh 출력은 변하지 않고, refresh는 자신이
  생산하지 않는 기존 metric key를 그대로 유지한다.
- Recovery canonical row는 accepted RAW capture에서 언제든 재생성할 수 있다
  (`garmin recovery-renormalize`, Garmin 호출 없음, capture 생성 없음).

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
- Canonical activity-load metric 10종(`src/muscle50/domain/activity_load.py`): `training_load`,
  `aerobic_training_effect`, `anaerobic_training_effect`(unit `score`),
  `hr_time_in_zone_1_seconds`~`hr_time_in_zone_5_seconds`(`s`), `moderate_intensity_minutes`,
  `vigorous_intensity_minutes`(`min`). 기존 `activity_metrics` schema에 저장(migration 없음).
- `garmin backfill-load-metrics [--dry-run]`: 저장된 초기 flat `summary.json`만 읽어 위 10개 key만
  insert/update. Garmin connector 의존성 없음, RAW/parent activity/strength/swim/다른 metric 불변,
  idempotent.
- `garmin recovery --from YYYY-MM-DD --to YYYY-MM-DD [--yes]`: inclusive 날짜 범위 recovery sync.
  날짜별 순차 호출(날짜당 endpoint 9회), 최대 31일, 7일 초과는 `--yes` 필요, 역순/형식 오류는 인증
  전 거부, 날짜별 created/updated/unchanged/failed/not_attempted 보고, 인증 실패 또는 연속 3일
  실패 시 중단, 실패/미시도가 있으면 exit 1. 단일 날짜 `garmin recovery <date>`는 변경 없음.
- Recovery normalizer version 2: `training_status_key`는 문자열 `trainingStatusKey`/`trainingStatus`,
  없으면 `latestTrainingStatusData`의 `trainingStatusFeedbackPhrase` prefix(`RECOVERY_2` →
  `RECOVERY`)를 사용하고 numeric `trainingStatus` code는 쓰지 않는다. `sleep_avg_hrv_ms`는
  `dailySleepDTO.avgSleepHRV` 우선, 없으면 top-level `sleep.avgOvernightHrv`.
- `garmin recovery-renormalize [--dry-run]`: 각 날짜의 accepted capture artifact를 size/sha256
  검증 후 읽어 현재 normalizer로 재정규화. Garmin 호출·새 capture·RAW 쓰기 없음.

## Pending merge

- `feature/garmin-analytics-prerequisites` (base main `65a929a`): activity-load metric,
  recovery range sync, recovery normalizer v2. 로컬 커밋만 있고 merge/push 하지 않았다.
- 이전 항목: `feature/inbody-connector`는 2026-09-28에 local main으로 fast-forward 병합됐다
  (병합 시점 main HEAD `4618df8`). Migration 번호 충돌(main `006_activity_refresh.sql` vs feature
  `006_inbody.sql`)은 InBody를 `007_inbody.sql`로 재배정해 해결한 상태로 병합됐다.

## Garmin refresh hotfix

2026-09-29에 main에 커밋됐다: `c32cff3` — "fix: make Garmin activity refresh metadata-safe".
커밋 직전 전체 게이트(pytest 285 / Ruff / mypy 72 files / `git diff --check`)를 재실행해 통과했다.
Push는 하지 않았다(local main은 `origin/main`보다 앞서 있다). 포함된 변경:

- `src/muscle50/application/refresh_garmin_activity.py` — refresh metadata 파괴 hotfix
- `src/muscle50/domain/swim_normalization.py` — `unitOfPoolLength.factor` 처리와
  `pool_length_factor_applies` 플래그
- `src/muscle50/presentation/terminal.py` — recovery 출력의 em-dash 제거(cp949 콘솔 크래시)
- `tests/test_refresh_activity.py`, `tests/test_swim_normalization.py`, `tests/test_sync_recovery.py`

## Verification

2026-09-29~30 Garmin Analytics Prerequisites 실 DB 검증(production home `%LOCALAPPDATA%\muscle50`).
각 단계 전 SQLite backup API로 WAL-safe backup을 만들고(`db_backup_20260929e_pre_load_metrics`,
`db_backup_20260930a_pre_recovery_range`, `db_backup_20260930b_pre_recovery_renormalize`) before/after
evidence를 table digest와 RAW 전체 sha256으로 비교했다.

- Activity-load metric backfill: 42 activity 모두 RAW summary 존재, 420 insert, missing/malformed/
  skipped 0. 420/420 값이 저장된 RAW와 정확히 일치(반올림 없음). 두 번째 실행은 변경 0(420
  identical). `activities`, 기존 121개 metric, `strength_sets`, swim/lap/length, RAW 358 files 불변.
  검증된 Garmin refresh 동작은 수정하지 않았다(refresh 이후에도 backfill 값 유지는 synthetic
  test로 검증, live refresh는 실행하지 않음).
- Recovery range backfill(`garmin recovery --from 2026-09-01 --to 2026-09-28 --yes`, exit 0):
  28/28 날짜, 공백 없음. 26 created, 1 updated(2026-09-14: 이전 capture가 당일 22:54 local의
  미완성 하루라 `stress_average` 21 → 26만 변경, 이전 capture 보존), 1 unchanged(2026-09-27, 같은
  capture 재사용). 신규 capture 27개 모두 9개 endpoint artifact 보유, endpoint warning/실패 0.
  2026-09-13은 Garmin 원본 자체에 sleep/overnight HRV가 없다(legitimate no-sleep day).
- Recovery normalizer v2 재정규화(`garmin recovery-renormalize`, Garmin 호출 0): 변경 column은
  `training_status_key`(28), `sleep_avg_hrv_ms`(27), `normalizer_version`(28), `updated_at_utc`(28)뿐.
  `training_status_key` 28/28(MAINTAINING 12, PRODUCTIVE 9, RECOVERY 7; 관측 code 4/5/7과 1:1),
  `sleep_avg_hrv_ms` 27/28(2026-09-13은 RAW가 null). 28행 모두 RAW 재정규화와 일치. 두 번째
  실행은 변경 0(`updated_at_utc` 포함 row 완전 동일). recovery capture/artifact table, capture
  pointer, recovery RAW 290 files, activity/metric/strength/swim, non-recovery RAW 338 files 불변.
- 모든 단계 후 `PRAGMA integrity_check` = ok, `foreign_key_check` clean, 중복/orphan 0.
  2026-09-17 swim anomaly는 수정하지 않았다.
- Gates(커밋 전): `uv run pytest -q` 345 passed, `uv run ruff check .`, `uv run mypy src tests`
  (78 files), `git diff --check`, `uv build` 통과. `ruff format --check`는 configured gate가 아니며
  기존 파일 14개를 이미 지적한다.

2026-09-29 Garmin refresh safety gate (실기기 2건, 실 DB): refresh가 기존 canonical activity
metadata를 파괴하지 않음을 before/after 비교로 확인했다.

- Strength `24481518495`(`MUSCLE50_HOME=C:\temp\muscle50-smoke`): 이전 버그로 NULL이었던
  `started_at_utc/local`, `elapsed_seconds`, `moving_seconds`, `distance_meters`,
  `calories_kcal`, `average_hr_bpm`, `max_hr_bpm` 8개 필드가 detail endpoint 값으로 복구됐다
  (2805.698 / 1359.479 / 0.0 / 334.0 / 115.0 / 154.0). Strength set 46건 유지, 교정된 종목 분류
  (DUMBBELL_HAMMER_CURL, CLOSE_GRIP_EZ_BAR_BICEPS_CURL, INCLINE_SMITH_MACHINE_BENCH_PRESS,
  CLOSE_GRIP_BARBELL_BENCH_PRESS) 유지.
- Swim `24391051389`(production home): parent metadata 11개 필드가 refresh 전후 완전히 동일하게
  유지됐다. distance 3025.0 m, pool 25.0 m, lap 20건, length 135건 유지. length distance 합계
  3025.0 m가 parent `distance_meters`와 정확히 일치한다.
- 두 activity 모두 refresh를 2회 실행해 canonical 값 drift 0을 확인했다(idempotent).
- 중복 row 0, orphan(strength/swim/lap/length/metric/refresh_state) 0, 기존 RAW 파일 변경·삭제 0
  (append-only snapshot만 증가), `activities.primary_raw_artifact_id`는 최초 import 증거를 그대로
  유지, 양쪽 DB `PRAGMA integrity_check` = ok.
- 검증 후 production 42건, smoke 2건 전체에서 `started_at_local`이 NULL인 activity는 0건이다.

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

2026-09-27 InBody integration 전 quality-gate cleanup에서 테스트 helper 반환형, optional identity
narrowing, source error annotation만 수정했다. `uv run pytest -q` 241 passed, Ruff 통과,
`uv run mypy src tests` 통과(66 files), `git diff --check` 통과. current main `85deeff`와의 read-only
비교에서 main은 migration을 추가하지 않아 `006_inbody.sql` 번호는 여전히 유효하다.

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

- Refresh는 매 실행마다 새 RAW capture를 append한다. "동일 payload면 같은 capture 재사용"이라는
  설계 의도는 실제 Garmin 응답에서는 성립하지 않는다 — `get_activity_details`가 의미상 동일한
  데이터를 호출마다 다른 column 순서로 돌려주고(`metricDescriptors`의 `metricsIndex` 배정이
  바뀌고 `activityDetailMetrics` 배열이 그에 맞춰 치환됨), `original.zip`은 zip 타임스탬프를
  포함해 바이트가 매번 달라진다. `activity.json`/`summary.json`/`splits.json`은 동일하다.
  데이터 손상은 없고 append-only 증가만 발생하므로 저장공간 이슈로만 취급한다.
- Swim `source_pool_length` provenance 값은 마지막으로 사용한 endpoint에 따라 달라진다.
  list endpoint ingest는 2500.0(factor 적용 전), detail endpoint refresh는 25.0(이미 적용된 값)을
  기록한다. 두 값 모두 해당 endpoint의 실제 source 값이며 canonical `pool_length_meters`는
  어느 경로든 25.0으로 동일하다.
- `normalization.py`의 `_append_pool_length()`(activity_metrics용)는 `poolLengthUnit`만 보고
  실제 payload의 `unitOfPoolLength`/`factor`를 읽지 않는다. `swim_normalization.py`와 별개
  경로이며 이번 hotfix 범위 밖이라 그대로 두었다.
- Refresh는 `avgSwolf`/`avgStrokeDistance`/`lapCount` 같은 list-endpoint 전용 key 이름을
  `summaryDTO`에서 찾지 못한다(detail은 `averageSWOLF`/`averageStrokeDistance`를 쓰고
  `lapCount`가 없다). 기존 metric은 `_preserve_missing_canonical_values()`가 유지하므로
  삭제되지는 않지만, refresh만으로 새로 채워지지도 않는다.
- Garmin Connect 연동은 비공식 API이므로 인증 및 응답 shape 변경 위험이 있다.
- `garmin latest`/`garmin activities`는 activity-load metric을 채우지 않는다. 새 activity import 후
  `garmin backfill-load-metrics`를 다시 실행해야 한다. 자동 enrichment 여부는 향후 설계 결정이다.
- `sync_runs`로 recovery date coverage를 기록할 수 없다: 날짜 column이 없어 "sync했지만 데이터 없음"과
  "sync한 적 없음"을 구분하지 못한다. 날짜 단위 coverage table(migration 필요)은 보류했다.
  상세는 `docs/garmin-analytics-prerequisites.md`.
- `mostRecentTrainingStatus`는 원리상 이전 날짜의 status를 담을 수 있다. 관측된 28일은 모두 entry
  `calendarDate`가 요청 날짜와 같아 필터를 추가하지 않았다(향후 stale-attribution 위험).
- `sleep_avg_hrv_ms`는 관측된 27일 모두 `hrv_last_night_avg_ms`와 같은 값이다(두 endpoint의 같은 측정).
- Recovery의 일부 endpoint만 실패한 날짜는 range 결과에서 성공(exit 0)으로 집계되고 날짜별 warning
  줄로만 드러난다.
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
- Recovery endpoint는 2026-09-01~28 live RAW로 검증했다(training status/sleep HRV shape 포함).
  Timezone/date attribution의 경계 사례는 아직 synthetic payload만 검증했다.
- swimming progression analytics용 기간/집계 read layer는 아직 없다.
- Nutrition은 아직 public CLI command에 연결되지 않았다.
- 기존 provisional nutrition schema로 직접 만든 외부 DB가 있다면 정식 migration marker가
  없으므로 별도 호환성 검토가 필요하다.
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
- Activity-load metric은 shared normalization에 넣지 않고 전용 RAW-only backfill로 채운다 — 검증된
  refresh 경로가 쓰는 값을 바꾸지 않기 위해서다. 값은 그대로 복사하고 범위/생리학적 검증은 향후
  Analytics quality layer 책임으로 남겼다.
- Training status canonical 값은 Garmin phrase prefix(`RECOVERY`)이며 numeric code나 suffix가
  붙은 phrase(`RECOVERY_2`, suffix는 같은 status 기간 중에도 바뀌는 message variant)는 쓰지 않는다.
- 날짜 범위 sync/run 결과는 CLI 출력의 inserted/skipped/failed count로 제공한다. 기존 스키마의
  `sync_runs` 테이블은 여전히 어떤 코드에서도 쓰지 않는 상태로 남겨 두었다 — command/error_code
  값 체계가 아직 정의되어 있지 않아 이번 범위에서 추측해 만들지 않았다.
- Activity refresh snapshot은 Recovery와 같은 content-addressed 패턴을 사용한다. 기존
  `activities.primary_raw_artifact_id`는 최초 import 증거를 계속 가리키고, 최신 성공 refresh는
  `activity_refresh_state.current_capture_id`로 별도 추적한다.
- Review 상태는 canonical `strength_sets`에서 동적으로 계산한다. 별도 persisted state는 최신
  canonical과 불일치할 위험만 늘리고 현재 요구에는 구체적 이점이 없어 추가하지 않았다.
- Endpoint shape 차이는 domain normalizer가 아니라 application 경계(`refresh_garmin_activity.py`)
  에서 흡수한다. `normalize_activity`/`normalize_garmin_swim`은 "summary는 flat shape"라는 단일
  규약을 유지하고, refresh가 `_detail_summary()`로 변환해 넘긴다. 단 `poolLength`는 detail에서
  이미 factor가 적용된 값이라 `pool_length_factor_applies=False`로 명시해 이중 적용을 막는다.
- `ActivityRepository.refresh()`는 계약대로 전 컬럼 replace를 유지한다. "source 값이 없으면 기존
  값을 지우지 않는다"는 규칙은 repository가 아니라 `RefreshGarminActivity`에서
  `_preserve_missing_canonical_values()`로 적용한다 — replace 계약을 바꾸면 다른 호출자에서
  의도적인 값 삭제까지 막히기 때문이다.
