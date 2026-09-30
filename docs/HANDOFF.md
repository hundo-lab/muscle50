# Session Handoff

Last updated: 2026-09-30

## Current task

Garmin Analytics Prerequisites (2026-09-29~30), branch `feature/garmin-analytics-prerequisites`
(Paseo worktree `strong-bat`, base main `65a929a`). Activity-load metric, recovery range sync,
recovery normalizer v2를 구현해 `4645f5f`로 커밋했고, 이어서 historical activity import
(2026-07-01~08-02)와 load-metric backfill을 production DB에서 검증했다(이 문서 갱신은 별도
docs-only 커밋). **Garmin Analytics Prerequisites는 이 feature branch에서 구현 및 실데이터 검증
완료 상태다. Merge/push 하지 않았다. Analytics Engine은 시작하지 않았다.**

## Garmin Analytics Prerequisites (2026-09-29~30)

### What was attempted / completed

1. **Activity-load metrics.** 10개 canonical key(`training_load`, `aerobic_training_effect`,
   `anaerobic_training_effect`, `hr_time_in_zone_1..5_seconds`, `moderate_intensity_minutes`,
   `vigorous_intensity_minutes`)를 `domain/activity_load.py`에 정의했다. 42개 production RAW 전수로
   source path와 unit(score/s/min)을 확인했다. Shared `normalize_activity`에는 넣지 않았다 — 검증된
   refresh 출력이 바뀌지 않게 하기 위해서다. `garmin backfill-load-metrics [--dry-run]`가 초기 flat
   `summary.json`만 읽어(refresh `snapshots/`는 읽지 않음) 이 10개 key만 upsert한다.
   Production: 42 activity, 420 insert, 420/420 RAW 일치, 두 번째 실행 변경 0. activity/strength/swim/
   기존 metric/RAW 불변.
2. **Recovery range sync.** `garmin recovery --from --to [--yes]`. Production
   `--from 2026-09-01 --to 2026-09-28 --yes`(Garmin 약 252회 호출, exit 0): 28/28 날짜, 26 created,
   1 updated(2026-09-14, 당일 저녁 partial capture였던 `stress_average` 21 → 26), 1 unchanged
   (2026-09-27). 신규 capture 27개 모두 9 endpoint, endpoint 실패 0. 2026-09-13은 Garmin 원본에
   sleep/overnight HRV가 없다.
3. **Recovery normalizer v2.** Range 검증에서 `training_status_key`와 `sleep_avg_hrv_ms`가 28일 모두
   NULL임을 발견했다. 원인: 실제 RAW는 `trainingStatus`가 numeric code(4/5/7)이고 key는
   `trainingStatusFeedbackPhrase` prefix에 있으며, sleep HRV는 `dailySleepDTO.avgSleepHRV`가 아니라
   top-level `avgOvernightHrv`에 있다. 정규화를 고치고 `normalizer_version`을 2로 올렸으며
   `garmin recovery-renormalize [--dry-run]`(RAW-only, Garmin 호출 0)으로 28행을 재정규화했다.
   결과: `training_status_key` 28/28(MAINTAINING 12, PRODUCTIVE 9, RECOVERY 7), `sleep_avg_hrv_ms`
   27/28(2026-09-13 RAW null). 두 번째 실행 변경 0.

### Files changed

- 신규: `src/muscle50/domain/activity_load.py`, `src/muscle50/application/backfill_activity_load_metrics.py`,
  `src/muscle50/application/renormalize_garmin_recovery.py`, `tests/test_activity_load_backfill.py`,
  `tests/test_recovery_range.py`, `tests/test_recovery_renormalize.py`,
  `docs/garmin-analytics-prerequisites.md`
- 수정: `src/muscle50/cli.py`, `src/muscle50/application/sync_garmin_recovery.py`(range use case),
  `src/muscle50/domain/recovery.py`(`RECOVERY_NORMALIZER_VERSION = 2`),
  `src/muscle50/domain/recovery_normalization.py`, `src/muscle50/infrastructure/garmin/client.py`
  (`GarminAuthenticationError` subclass), `src/muscle50/infrastructure/raw_store.py`
  (`load_initial_summary`, `load_capture_payloads`), `src/muscle50/infrastructure/sqlite/database.py`
  (`list_source_activity_ids`, `upsert_activity_metrics`, `list_calendar_dates`),
  `src/muscle50/presentation/terminal.py`, `tests/test_recovery_normalization.py`(추가만),
  `tests/test_sync_recovery.py`(normalizer version literal 1 → constant; 기존 테스트 중 유일한 수정),
  `docs/garmin-recovery-endpoint-discovery.md`, `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`
- Migration 없음. Refresh 코드(`refresh_garmin_activity.py`)는 수정하지 않았다.

### Tests / checks run

`uv run pytest -q` 345 passed(기존 285 → 319 → 345), `uv run ruff check .`, `uv run mypy src tests`
(78 files), `git diff --check`, `uv build` 통과. 모든 production 단계 후 `PRAGMA integrity_check` = ok,
`foreign_key_check` clean, 중복/orphan 0. 상세 evidence는 `docs/CURRENT_STATE.md` "Verification".
Evidence 파일(repo 밖): `C:\temp\muscle50-evidence-20260929\`, `C:\temp\muscle50-evidence-20260930\`,
`C:\temp\muscle50-evidence-20260930-hist\`.
Backups: `%LOCALAPPDATA%\muscle50\db_backup_20260929e_pre_load_metrics`,
`db_backup_20260930a_pre_recovery_range`, `db_backup_20260930b_pre_recovery_renormalize`,
`db_backup_20260930c_pre_historical_import`.

### Historical activity import (2026-09-30)

Commit `4645f5f` 코드 그대로 실행했다(코드 변경 없음).

- 명령: `uv run muscle50 garmin activities --from 2026-07-01 --to 2026-08-02` → exit 0.
  Garmin이 36건을 반환했고 36건 모두 신규 import(이미 저장됨 0, 실패 0, RAW manifest warning 0).
  실제 activity 날짜는 2026-07-01~2026-07-31이며 2026-08-01/08-02에는 activity가 없다.
  Strength 24, pool swim 12, training day 21. RAW 240 files 추가(모두 신규 activity 디렉터리).
- Strength: 신규 24건, canonical set 933(ACTIVE 471 / REST 462). 933 set 전부를 RAW 필드
  (messageIndex, setType, reps, weight g/1000, category, name, duration)와 직접 비교해 불일치 0.
  ACTIVE 중 UNKNOWN 분류 147/471, weight 0/누락 39, reps 0 20 — ingestion 실패가 아니라
  data-quality/review 이슈다.
- Swim: 신규 12 session, lap 286, length 645(수영 417 / rest 228). 모든 lap/length 값을 RAW
  `splits`와 비교해 불일치 0. 11 session은 50 m pool, 2026-07-23은 source와 일관된 20 m pool.
  Session별 수영 length 거리 합 = parent distance, 수영 length 수 = source active length count.
  누락된 swim child record 없음.
- Load metrics: `backfill-load-metrics --dry-run` 예측(36 changed, 360 insert, 420 identical)과 실제
  실행이 동일. 78 activity 모두 10개 metric 보유, 780/780 값이 각자의 RAW와 일치. 기존 420 load
  metric 불변. 두 번째 실행 canonical 변경 0.
- Regression: 기존 42 activity의 parent row, metric, strength set, swim/lap/length, refresh state,
  RAW 파일이 activity별 fingerprint로 모두 불변. `daily_recovery`와 recovery RAW 불변. 중복/orphan 0,
  `PRAGMA integrity_check` = ok, `foreign_key_check` clean, 기존 RAW 628 files 불변(최종 868 files).
  2026-09-17 swim anomaly 불변.
- Final Garmin activity coverage: 78 activities, 2026-07-01~2026-09-28, 54 distinct training days
  (strength 55, lap swimming 21, running 1, track running 1).

### Data-quality findings (future Analytics quality layer; 수정하지 않음)

- 신규 기간 수영 length 40/417이 42 s/100 m보다 빠르다(세계기록 페이스 미만, 12 session 중 9개).
  기존 swim 데이터에도 같은 현상(110 lengths)이 있어 import 실패가 아니라 systemic source/data-quality
  이슈다. 예: 2026-07-07 `23503867925` length 53, breaststroke 50 m 5.6 s.
- Strength UNKNOWN 분류 147/471, weight 0/누락 39, reps 0 20(신규 ACTIVE set 기준). 일부는 bodyweight
  운동으로 정당할 수 있다.
- 2026-07-20 swim 2건(`23659117397`, `23659117767`)은 27분 간격이며 split session일 수 있다. 자동으로
  합치지 않는다.
- 2026-07-23 20 m pool은 내부적으로 일관된다. 평소 pool 길이와 다르다는 이유만으로 오류로 취급하지 않는다.

### Known risks

- 새 activity import(`garmin latest`/`garmin activities`)는 load metric을 채우지 않는다 — import 후
  backfill을 다시 실행해야 한다. 자동 enrichment는 향후 설계 결정.
- `sync_runs` recovery coverage는 보류(schema에 날짜 column 없음, migration 필요).
- `mostRecentTrainingStatus`의 stale-date 가능성은 필터 없이 남겨 두었다(관측 28일은 모두 날짜 일치).
- Range 실행 중 repository integrity `RuntimeError`는 날짜별 요약 없이 traceback으로 멈춘다(완료된
  날짜는 유지, 재실행 안전 — activity range import와 동일).
- 2026-09-17 swim anomaly는 의도적으로 수정하지 않았다(향후 Analytics quality layer).

### Prerequisite status

- Garmin Analytics Prerequisites: 이 feature branch에서 구현 및 실데이터 검증 완료.
- 완료: historical activity import, recovery 28일 backfill, recovery normalizer v2 re-normalization,
  activity load-metric backfill.
- Strength refresh/review는 Analytics Engine 전에 필요하지 않다.
- 보류: `sync_runs` recovery coverage, 향후 import의 자동 load-metric enrichment.
- Analytics Engine은 시작하지 않았다.

### Recommended next action

1. 이 branch(`4645f5f` + docs-only 커밋)의 main 통합 여부 결정(명시적 승인 필요). main은 여전히
   `65a929a`이므로 fast-forward 가능하다. 통합 전 main에서 전체 게이트(pytest/Ruff/mypy/
   `git diff --check`/`uv build`) 재실행 권장.
2. 그 뒤 Analytics Engine(명시적 승인 필요).
3. 새 activity를 import할 때마다 `garmin backfill-load-metrics`를 이어서 실행한다.

## Previous task: Garmin refresh safety gate (2026-09-29)

Garmin refresh safety gate를 닫았다. `garmin refresh`가 기존 canonical activity metadata를 NULL로
덮어쓰던 버그를 hotfix하고, 실기기 activity 2건으로 실 DB 회귀 검증을 마쳤다. **판정: SAFE.**

Hotfix는 main에 커밋됐다: `c32cff3` — "fix: make Garmin activity refresh metadata-safe"
(부모 `4618df8`). 이 handoff 문서 갱신은 그 뒤 별도 docs-only 커밋이다. Push는 하지 않았다.

## Garmin refresh hotfix (2026-09-29)

### Root cause

`PythonGarminConnector.fetch_raw_activity()`는 단일 activity 조회라 list endpoint를 호출하지 않고
`summary={}`를 반환한다. `RefreshGarminActivity`는 그 자리를 `raw.activity`(= `get_activity()`
detail payload)로 채운 뒤 `normalize_activity(raw.activity, raw.activity, ...)`로 넘겼다.

그런데 detail payload는 list summary와 shape가 다르다. `startTimeGMT`, `startTimeLocal`,
`duration`, `elapsedDuration`, `movingDuration`, `distance`, `calories`, `averageHR`, `maxHR`가
top-level에 전혀 없고 전부 `summaryDTO` 안에 중첩돼 있다(실제 RAW로 swim/strength 양쪽 확인).
따라서 `normalize_activity`의 flat key 조회가 모두 None을 반환했고,
`ActivityRepository.refresh()`가 계약대로 전 컬럼을 무조건 UPDATE하면서 정상값이 NULL로 덮였다.

`timezone_name`(`timeZoneUnitDTO`)과 `name`(`activityName`)은 detail top-level에 있어 깨지지
않았다 — 실제 관측된 손상 필드 목록과 정확히 일치한다.

이 버그는 refresh 기능 도입 시점부터 있었고, 2026-09-28 "Live E2E validation"이 성공으로 기록된
strength `24481518495`도 실제로는 parent row가 NULL이 된 상태였다. 그 검증이 `strength_sets`만
확인하고 parent row를 보지 않아 놓쳤다.

### Code change

- `_detail_summary()`: `summaryDTO`를 top-level 위에 병합해 flat shape로 만든다. `summaryDTO`가
  없는 synthetic/legacy payload는 그대로 통과시킨다.
- `_preserve_missing_canonical_values()`: refresh가 값을 주지 못한 필드만 기존 DB 값을 유지한다
  (name/timezone 포함 11개 scalar, 기존 activity_metric, swim pool 관련 4개 필드). 새 값이 있으면
  항상 새 값이 이긴다.
- `normalize_garmin_swim(..., pool_length_factor_applies=)`: detail의 `summaryDTO.poolLength`는
  이미 factor가 적용된 값(25.0)이고 list의 `poolLength`는 적용 전 값(2500.0)이라, refresh 경로에서만
  factor 적용을 끈다. `swim_normalization.py`의 기존 factor 처리 자체는 그대로 둔다.
- `ActivityRepository.refresh()`의 전 컬럼 replace 계약은 변경하지 않았다.

### Regression tests

`tests/test_refresh_activity.py`에 3건 추가(전체 285 passed).

- `test_strength_refresh_reads_summary_dto_and_preserves_missing_parent_metadata`
- `test_swim_refresh_preserves_pool_metadata_when_detail_omits_pool_length`
- `test_swim_refresh_does_not_rescale_detail_summary_dto_pool_length`

### Real-device validation

`docs/CURRENT_STATE.md`의 "Verification" 2026-09-29 절 참고. 두 activity 모두 refresh 2회 실행 후
parent metadata drift 0, child row 수/내용 유지, 중복·orphan 0, 기존 RAW 불변, integrity ok.

### Known issue (데이터 안전성과 무관)

Refresh는 매번 새 capture를 append한다. `get_activity_details`가 호출마다 column 순서를 바꿔
돌려주고 `original.zip`이 타임스탬프를 포함하기 때문에 content-addressed dedup이 실제 응답에서는
절대 걸리지 않는다. 손상은 없고 저장공간만 증가한다.

## InBody integration rebase (2026-09-28)

- 이전 세션 대비 local main이 16 commits 전진했다(`85deeff` 날짜 범위 ingestion,
  `cba6a08` activity refresh 포함). `git branch -vv`로 local main을 직접 확인했다(origin과는
  별개로 diverge할 수 있다는 이전 경험 때문에 항상 local을 기준으로 삼는다).
- `git rebase main`으로 4개 feature commit(`8694abc` InBody foundation, `94fd37b` Samsung Health
  source, `68dee75` Samsung Health sync 통합, `774ca05` typing fix)을 순서대로 재적용했다.
  merge commit 없이 선형 history를 유지했다.
- 충돌은 매 커밋마다 `docs/HANDOFF.md`(세션별 로그라 매번 재작성하는 대신 main측 누적 내용을
  유지하고 이 파일에서 최종 정리), `docs/CURRENT_STATE.md`(durable state라 실제 내용을 비교해
  두 쪽을 모두 보존하도록 병합 — 특히 feature 쪽의 Galaxy live 검증 결과(`dataSource.appId=
  com.inbody2014.inbody` 확인)를 놓치지 않게 주의했다), `src/muscle50/cli.py`(양쪽이 각각 독립적인
  하위 명령을 추가한 것이라 실제 의미 충돌은 아니었고, import/`build_parser()`/`main()` dispatch/
  함수 목록을 전부 합쳐 하나의 완전한 파일로 재작성했다), `tests/test_cli.py`와
  `tests/test_database.py`(양쪽이 각자 추가한 테스트 함수를 모두 보존하고, `EXPECTED_TABLES`/
  `EXPECTED_VERSIONS`와 여러 개별 테스트에 흩어져 있던 하드코딩된 migration 버전 목록
  `[1,2,3,4,5,6]`을 전부 `[1,2,3,4,5,6,7]`로 업데이트)에서 발생했다. `ours`/`theirs`를 그대로 채택한
  곳은 로그성 `docs/HANDOFF.md`뿐이고, 나머지는 모두 두 내용을 직접 읽고 의미를 확인한 뒤 손으로
  재작성했다.
- Migration 충돌: `src/muscle50/infrastructure/sqlite/migrations/006_inbody.sql`을
  `007_inbody.sql`로 `git mv`하고 내부 `INSERT OR IGNORE INTO schema_migrations(...) VALUES (6, ...)`
  를 `VALUES (7, ...)`로 수정했다. `docs/CURRENT_STATE.md`, `docs/inbody-sync-design.md`,
  `tests/test_cli.py`, `tests/test_database.py`의 관련 참조를 모두 갱신했다. `tests/test_inbody_schema.py`
  등 shared loader(`ActivityRepository(...).migrate()`)만 쓰는 파일은 하드코딩된 파일명/버전이 없어
  수정이 필요 없었다.
- `android/inbody-diagnostic-companion/.gitignore`에 남아 있던 EOF 공백 줄(`git diff --check`가
  지적)을 제거했다.
- 재검증: `uv run pytest -q` 281 passed, `uv run ruff check .` 통과, `uv run mypy src tests` 통과
  (72 source files), `git diff --check` 통과. Migration 순서 001~007이 정확히 적용됨을
  `ls`와 `EXPECTED_VERSIONS`/`EXPECTED_TABLES` 테스트로 확인했다.
- Main merge/push는 이번 세션 범위 밖이다(명시적으로 지시받지 않음). Fast-forward는 가능한 상태다.

## Garmin Activity Refresh (2026-09-27)

- `RefreshGarminActivity`가 이미 local DB에 있는 activity만 대상으로 activity/details,
  splits, conditional strength exercise sets, original archive를 다시 가져온다.
- RAW는 기존 Recovery와 같은 content-addressed 방식으로
  `raw/garmin/activities/<id>/snapshots/<capture-id>/`에 보존한다. 초기 flat RAW와 이전
  refresh snapshot은 수정하지 않는다. 동일한 payload+warnings는 같은 capture를 재사용한다.
- RAW 파일 저장과 capture metadata 등록은 normalization보다 먼저 별도 commit한다.
  이후 normalization 또는 canonical persistence가 실패해도 새 RAW evidence는 남는다.
- Canonical update는 `activities` scalar fields/metrics, `strength_sets`, `swim_activities`
  (cascade로 laps/lengths 포함), accepted capture pointer를 하나의 `BEGIN IMMEDIATE`
  transaction에서 교체한다. 실패하면 이전 canonical 상태 전체가 rollback된다.
- Strength refresh에서 `exercise_sets`, pool swim refresh에서 `splits`가 없으면 불완전한
  refresh를 거부한다. 다른 sport의 optional split 실패와 original archive 실패는 warning만
  남기고 처리할 수 있다.
- `derive_activity_review()`는 ACTIVE set의 UNKNOWN/missing Garmin classification을
  `unknown_exercise_classification` reason과 set sequence 목록으로 반환한다. DB에 중복
  저장하지 않으며 종목을 추측하거나 자동 수정하지 않는다.
- Migration 6은 `activity_raw_captures`, `activity_raw_capture_artifacts`,
  `activity_refresh_state`를 추가한다. 기존 `activities.primary_raw_artifact_id`는 최초 import
  증거를 계속 가리키고, 최신 성공 refresh는 refresh state가 가리킨다.
- 테스트는 Strength UNKNOWN→corrected, child replacement, initial/previous/new RAW 보존,
  identical refresh, normalization/persistence rollback, required optional endpoint failure,
  Swim child replacement, normal range ingest의 non-refresh/idempotency를 synthetic data로 검증한다.

## Live E2E validation (2026-09-28)

사용자가 이 Paseo 세션 밖에서 실제 Garmin 계정으로 아래를 수행하고 결과를 보고했다:

- `MUSCLE50_HOME=C:\temp\muscle50-smoke`에서 activity 24481518495의 Garmin Connect 종목
  분류를 수동으로 수정한 뒤 이 feature worktree에서 다음을 실행했다.
  ```powershell
  uv run muscle50 garmin refresh 24481518495
  ```
- 출력:
  ```text
  Garmin activity refresh complete
  Garmin activity ID: 24481518495
  RAW snapshot:
  raw/garmin/activities/24481518495/snapshots/782859ca841d536670ef696f65e3959d1ed3a74b062e771542c6e2a04a595e75/manifest.json
  Strength sets replaced: 46
  Swim laps/lengths replaced: 0/0
  Review warnings remaining: none
  ```
- Canonical DB를 수동으로 확인한 결과, 이전에 `UNKNOWN`이거나 잘못 분류됐던 종목이
  사용자가 Garmin Connect에서 수정한 대로 정확히 교체됐다: `DUMBBELL_HAMMER_CURL`,
  `CLOSE_GRIP_EZ_BAR_BICEPS_CURL`, `INCLINE_SMITH_MACHINE_BENCH_PRESS`, `BENCH_PRESS`,
  `CLOSE_GRIP_BARBELL_BENCH_PRESS`.
- 이전에 의심스러웠던 `PUSH_UP` 40/50 kg 기록은 Garmin Connect 수정 후 `BENCH_PRESS`가
  됐다 — 이는 muscle50 정규화 버그가 아니라 Garmin 원본 분류 문제였음을 확인한다.
- 남은 관찰 사항: sequence 1은 `DUMBBELL_HAMMER_CURL` / 8 reps / 0.0 kg다. 지금은 별도
  휴리스틱을 추가하지 않는다 — 향후 data-quality/review 규칙 후보로만 기록한다(예:
  ACTIVE set의 weight가 0인 경우 review warning 후보로 검토).
- 이 live 실행은 수동 1회 smoke이며 자동 테스트 스위트에는 포함되지 않는다. 자동
  테스트는 여전히 synthetic fixture만 사용한다.

## Refresh files changed

- `README.md`, `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`
- `src/muscle50/application/refresh_garmin_activity.py` (신규)
- `src/muscle50/domain/activity_review.py` (신규)
- `src/muscle50/infrastructure/sqlite/migrations/006_activity_refresh.sql` (신규)
- `src/muscle50/infrastructure/raw_store.py`
- `src/muscle50/infrastructure/sqlite/database.py`
- `src/muscle50/infrastructure/garmin/client.py`
- `src/muscle50/cli.py`, `src/muscle50/presentation/terminal.py`
- `tests/test_refresh_activity.py` (신규)
- `tests/test_cli.py`, `tests/test_database.py`, `tests/test_garmin_connector.py`,
  `tests/test_ingest_range.py`

## Refresh verification

```text
uv run pytest -q                    191 passed
uv run ruff check .                 passed
uv run mypy src tests               passed (50 source files)
git diff --check                    passed
```

## Previous range-ingestion record

아래의 기존 날짜 범위 ingestion 기록은 이전 통합 작업의 배경이다.

## Completed

- `IngestGarminActivity`(신규, `application/ingest_activity.py`)를 canonical
  per-activity ingestion path로 도입했다. 기존 `SyncLatestGarminActivity.execute()`의
  activity별 로직(두 번의 activityId 일치 검사, RAW `preserve` → `normalize_activity` →
  lap_swimming일 때 `normalize_garmin_swim`으로 `swim_detail` 채우기, `repository.save`,
  기존 activity에 대한 Strength/Swim local RAW backfill)을 그대로 옮겼다 — 순서와 두
  검사 모두 원본과 동일하게 유지했다.
- `SyncLatestGarminActivity`는 이제 `latest_summary()` 호출과 `NoActivitiesError`만
  담당하는 thin wrapper이며, 나머지는 `IngestGarminActivity`에 위임한다. `SyncResult`,
  `NoActivitiesError`는 그대로 이 모듈에 남겨 `cli.py`/`terminal.py`의 기존 import를
  건드리지 않았다. `ActivitySyncError`만 `ingest_activity.py`로 옮기고 `cli.py`의 import
  한 줄을 그에 맞춰 갱신했다.
- `IngestGarminActivityRange`(신규, `application/ingest_activity_range.py`)를 추가했다.
  - `GarminConnector.list_activities(start, limit)`을 새로 추가하고 `latest_summary()`가
    내부적으로 이를 사용하도록 재구성했다(기존 wrapped/unwrapped 응답 처리 로직 그대로).
  - Garmin이 최신순으로 내려주는 목록을 페이지 단위로 순회하다가, 한 페이지에
    `from_date`보다 이전 activity가 나오면 그 페이지를 끝까지 처리한 뒤(같은 페이지의
    범위 내 activity를 놓치지 않기 위해) 조회를 멈춘다. 빈 페이지도 종료 조건이다.
  - `from_date`~`to_date`는 Garmin의 `startTimeLocal`(없으면 `startTimeGMT`)로 판단한다.
    이름 있는 timezone을 `zoneinfo`로 해석하지 않는다(이 머신의 tzdata 이슈와 무관하게,
    기존 domain 규칙대로 문자열을 있는 그대로 신뢰).
  - 페이지 간에 같은 activity가 중복으로 나타나도 한 번만 수집한다.
  - activity 하나의 실패(`ActivitySyncError`, `GarminConnectorError`,
    `NormalizationError`—`SwimNormalizationError` 포함—, `RawStoreError`,
    `sqlite3.Error`)는 해당 activity만 `failed`로 기록하고 나머지는 계속 처리한다.
    단, backfill 중 저장된 값과 로컬 RAW 재정규화 결과가 불일치할 때 발생하는 bare
    `RuntimeError`(`database.py`의 `_insert_strength_sets`/`_insert_swim_detail`,
    `ignore_existing=True`)는 의도적으로 잡지 않고 전체 범위 처리를 중단시킨다 — 이건
    로컬 데이터 정합성 버그이므로 조용히 "실패 1건"으로만 남기지 않기로 했다.
  - 50페이지(activity 1000건) 안전 상한에 도달하면 결과에 `page_limit_reached=True`로
    표시한다. 조용히 잘라내지 않는다.
- `muscle50 garmin activities --from YYYY-MM-DD --to YYYY-MM-DD` CLI를 추가했다.
  날짜 형식/범위 검증은 `garmin recovery`와 동일하게 Garmin 인증/네트워크 호출 전에
  실행한다.
- `terminal.py`에 `render_range_result`를 추가했다(기간, 발견/신규 저장/이미 저장됨/실패
  건수, 시작 시각 누락 건수, page limit 경고, 실패 activity ID/타입 목록). `garmin
  latest`의 출력은 변경하지 않았다.
- 새 RAW artifact나 migration은 추가하지 않았다: `normalize_garmin_swim`이 필요로 하는
  lap/length 계층은 이미 모든 activity에서 무조건 가져오는 `splits` RAW로 충분하고,
  Strength/Swim 스키마는 이미 migration 2/4에 있다.
- 실제 Garmin API는 호출하지 않았고 synthetic fixture(및 기존 `garmin_pool_swim.json`,
  `synthetic_strength_sets.json`)만 사용했다.

## Files changed

- `README.md`
- `docs/CURRENT_STATE.md`
- `docs/HANDOFF.md`
- `src/muscle50/application/ingest_activity.py` (신규)
- `src/muscle50/application/ingest_activity_range.py` (신규)
- `src/muscle50/application/sync_latest_garmin.py`
- `src/muscle50/cli.py`
- `src/muscle50/domain/normalization.py` (`local_date_from` 추가)
- `src/muscle50/infrastructure/garmin/client.py` (`list_activities` 추가)
- `src/muscle50/presentation/terminal.py`
- `tests/test_cli.py`
- `tests/test_garmin_connector.py`
- `tests/test_ingest_range.py` (신규, 21 tests)
- `tests/test_sync_latest.py` (swim normalizer monkeypatch 대상을 `ingest_activity`
  모듈로 재조정 — 추출로 인한 예상된 변경)

## Verification performed

```text
uv sync --extra dev                 passed
uv run pytest -q                    178 passed (151 pre-existing + 27 new)
uv run ruff check .                 passed
uv run mypy src tests               passed (47 files)
git diff --check                    passed
```

Pagination/range-stop 로직은 실제로 필터를 깨뜨려 관련 테스트 2개가 실패하는지 확인한
뒤 원복하는 방식으로 검증했다(sabotage test). `garmin latest`, Strength, Swim 관련
기존 회귀 테스트는 수정 없이 모두 통과했다(모니터패치 대상 재조정 제외).

## Remaining work

- 실제 Garmin 계정 live smoke: 완료(2026-09-28, activity 24481518495, 위 "Live E2E
  validation" 참고).
- Strength per-set / Swim per-lap 세부 데이터는 이미 존재하는 스키마와 정규화를 그대로
  재사용했을 뿐이며, 이번 작업에서 새로 만든 것은 없다.
- `sync_runs` 테이블은 여전히 미사용 상태다. command/error_code 값 체계가 정의되면
  range/latest 양쪽에서 사용할 수 있다.
  (2026-09-30) Recovery date coverage에는 날짜 column이 없어 부적합하다는 판단으로 보류 —
  `docs/garmin-analytics-prerequisites.md` E절.

## Known issues / risks

- pagination은 50페이지(activity 1000건) 상한이 있다. 결과의 `page_limit_reached`로
  드러나지만 더 깊은 재조회는 자동으로 하지 않는다.
- Garmin Connect는 비공식 API이므로 endpoint와 응답 형식이 바뀔 수 있다(기존 위험,
  변경 없음).
- 이 작업은 `client.py`, `cli.py`, `terminal.py`, `sync_latest_garmin.py`를 수정하므로
  main에 이후 병행 변경이 생기면 merge 전 재검증이 필요하다.

## Recommended next action

0. **(2026-09-30 갱신)** 최신 권장 순서는 위 "Garmin Analytics Prerequisites" 절의 Recommended next
   action을 따른다: historical import와 load-metric backfill은 완료됐고, 다음은 main 통합 결정 →
   Analytics Engine이다.
1. **다음 마일스톤: Analytics Engine.** Data collection layer는 2026-09-28에 VALIDATED,
   refresh safety gate는 2026-09-29에 SAFE로 닫혔다. InBody/Swim/Recovery/Strength canonical
   데이터가 실기기 기준으로 정상 저장·갱신됨이 확인됐으므로 읽기/집계 계층을 시작할 수 있다.
   현재 read layer가 전혀 없는 영역(예: swimming progression 기간 집계)이 첫 후보다.
   **아직 시작하지 않았다.**
