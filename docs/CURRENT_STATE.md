# Current State

Last updated: 2026-10-02

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
  append-only nutrition fact history를 제공한다. Nutrition Logging MVP(`application/nutrition_logging.py`,
  `presentation/nutrition_terminal.py`, CLI `muscle50 nutrition`)가 그 위의 food catalog / 구조화 식사 기록 / 하루 섭취
  계산 경로다(migration 없음, 목표·추천 없음). 상세는 `docs/nutrition-logging.md`.
- Nutrition Targets + Daily Status v1(`domain/nutrition_targets.py`, `application/nutrition_targets.py`,
  `infrastructure/nutrition_target_store.py`, CLI `muscle50 nutrition target set|show`, `muscle50 nutrition status`)은
  사용자가 직접 정한 하루 목표(exact/range/unset)를 `<home>\config\nutrition_targets.json`(versioned JSON, migration 없음)에
  두고, `ShowDailyIntake` 결과를 그대로 목표와 비교한다. 상세는 `docs/nutrition-targets.md`.
- (`8f267a2`/`caa7982`, 2026-10-02 local main으로 fast-forward 통합, origin push 안 함) Nutrition → Daily/Recommendation Integration v1: 추천이 먼저
  만들어진 뒤 `BuildNutritionContext`(`application/nutrition_recommendation.py`)가 같은 날짜의 `ShowDailyNutritionStatus`를
  그대로 실행하고, 순수 규칙 `domain/nutrition_guidance.py`가 status를 행동 안내로 바꾼다. 추천은 nutrition을 입력으로 받지
  않는다(운동 계획 불변). Read-only meal reader `infrastructure/sqlite/nutrition_reader.py`. 상세는
  `docs/nutrition-recommendation.md`.
- Activity-load metric(training load/effect, HR zone, intensity minutes)은 shared
  `normalize_activity`가 아니라 전용 RAW-only backfill(`garmin backfill-load-metrics`)이 초기 flat
  `summary.json`에서 `activity_metrics`로 쓴다. Refresh 출력은 변하지 않고, refresh는 자신이
  생산하지 않는 기존 metric key를 그대로 유지한다.
- Recovery canonical row는 accepted RAW capture에서 언제든 재생성할 수 있다
  (`garmin recovery-renormalize`, Garmin 호출 없음, capture 생성 없음).
- Analytics Engine v1은 canonical 데이터 위의 read-only computed read model이다(migration 없음).
  순수 domain(`domain/analytics.py`) + read-only reader(`mode=ro`, `query_only`, migrate/mkdir 없음)
  + CLI `muscle50 analytics snapshot`. 상세 규칙은 `docs/analytics-engine.md`.
- Exercise Taxonomy v1(`domain/exercise_taxonomy.py`)은 저장된 Garmin `(category, name)` label을 그대로
  identity로 두고 movement pattern / primary·secondary muscle만 붙이는 순수 lookup table이다(이름 변경·병합
  없음, migration 없음, 저장하지 않음). Analytics snapshot이 계산 시 적용한다. 상세는 `docs/exercise-taxonomy.md`.
- Training Recommendation v1(`domain/training_recommendation.py` + `recovery_assessment`, `strength_recommendation`,
  `swim_recommendation`, `training_goals`)은 read-only reader 위의 결정적 규칙 계층이다(LLM/ML/합성 점수 없음,
  migration 없음). CLI `muscle50 recommend --date`. 상세는 `docs/training-recommendation.md`.

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
- Analytics Engine v1 rolling training snapshot(`muscle50 analytics snapshot --date YYYY-MM-DD
  [--days 1..90, 기본 7] [--json]`): Garmin activity 수/type, load metric 10종(metric별 명시적
  sum/max), strength(session/active set/reps/volume/exercise별, 제외 사유별 count), swimming(summary
  distance와 lap-detail distance 분리, implausible lap 제외 plausible detail distance, pool length),
  recovery(daily field latest/mean/min/max, state field latest, categorical latest, row 없는 날짜와
  null field 구분), provenance(source activity ID/날짜), data-quality issue 목록.
  추천/생리학적 점수 없음.
- Exercise Taxonomy v1: 검토된 production label 45개(2026-10-01 coverage update로 Connect 지정 label 7개 추가)에 대한 명시적 rule(category fallback, fuzzy, 추론
  없음), movement pattern 15 / muscle group 13. Snapshot `strength.taxonomy`가 원본 Garmin label별,
  movement pattern별, primary muscle별 ACTIVE set(각 set 정확히 한 번), 별도 secondary muscle set exposure,
  명시적 unmapped(`unknown_source_label`/`no_rule`)와 UNKNOWN 영향 activity, Garmin label origin(confirmed/
  auto-detected) 개수, activity/set provenance를 보고한다. Rule 없는 label은 `strength_unmapped_exercise` issue.
- Training Recommendation v1(`muscle50 recommend --date YYYY-MM-DD [--json] [--avoid MUSCLE]`): region(push/pull/
  legs) focus를 어제 heavy work 제외, 7일+ 미훈련(neglected, 수영 불포함) 보호, 수영 overlap, recovery reduce 시
  최근 region 후순위, 자기 28일 주기 대비 due, 자기 평균 대비 7일 volume 순으로 선택; 28일 history의 익숙한
  원본 Garmin label로 key/accessory/isolation(약 40분); label별 double progression(같은 무게 rep 증가, work set 2개
  상한 도달 시 +2.5 kg(Progression Hardening v1부터 2.5 kg ≤ work load의 15%일 때만, 아니면 "next available step"),
  같은 무게 rep 감소 시 maintain, load 일관성 낮으면 `low` confidence); 필드별 recovery 규칙
  (`normal`/`hold`/`reduce`, missing ≠ poor); 강한 수영(zone 5 ≥ 120 s, anaerobic TE ≥ 2.5, butterfly ≥ 200 m) 후
  push/pull 후순위와 overhead press 제외; UNKNOWN activity별 Garmin Connect 수정 + `garmin refresh` 안내; 다음 수영
  목표(`distance_progression`/`pace_intervals`/`easy_continuous`/`recovery_technique`)는 plausible length timing
  구간만 baseline으로 사용하고 2026-09-17 3025 m summary는 제외. `TrainingGoals`는 code default.
- 사용자 지정 focus `muscle50 recommend --date D --focus push|pull|legs|shoulders`(`8b259e7`, main/origin 포함):
  자동 순위 대신 요청한 focus로 세션을 만들고 바꾸지 않는다. Recovery, swim overlap, `--avoid`, progression,
  UNKNOWN/data-quality 안내는 그대로 적용. 요청 focus의 어제 primary set ≥ 6이면 reduce. `shoulders`는 primary
  anterior/lateral/posterior deltoid 종목만. JSON `focus_source`(`auto`/`user`)와 `auto_focus`.
- (`5fbdd56`/`38a23ae`/`4f26ec2`, main/origin 포함 — `4f26ec2` 기준선부터; branch `integration/recommendation-hardening`
  = `aba8cfe` + `5dd2af7`/`272761a` cherry-pick + 통합 수정을 main으로 fast-forward) Recommendation Hardening v1: focus 안 muscle
  balance(미커버 primary muscle 우선, 한 muscle 3종목 금지, heavy hinge(`DEADLIFT` category) 세션당 1개), 1 key + 2 accessory + 1 isolation 구조로 40분 목표,
  `focus_coverage`와 시간 부족분 이유 보고(채우지 않음), low-confidence 부하 범위/확인 안내, `no_rule` label 경고
  (category 힌트는 표시 전용), recovery D-1/D-2 lookback(최대 hold), `data_freshness`와 stale/partial notice,
  swim history D-28~D 정렬, 10일 이상 swim 공백 후 `return_easy` 재진입. 상세는 `docs/training-recommendation.md`.
  통합 수정: 조정 원인 표기 분리 — 48 h rest rule이 올린 reduce는 "48 h rest rule reduce"로, recovery는 자기 level로만
  표기(결정 불변). Text heading은 두 level이 다를 때 `Recovery adjustment: hold; session adjustment: reduce`.
- (`13d5ed2`, main/origin 포함; 2026-10-02 fast-forward 통합·push 완료) Progression Hardening v1: 증량 시점(work
  set 2개 상한)은 그대로, 정확한 +2.5 kg 목표는 2.5 kg ≤ work load × 15%(`MAX_EXACT_LOAD_INCREASE_RATIO`)일 때만.
  초과하면 `increase_load` + `load_kg: null` + `load_increase_from_kg`(마지막 work load) + `load_step:
  "smallest_available"`, text `@ next available step above 6 kg`. `PULL_UP/-`, `PUSH_UP/-`,
  `TRICEPS_EXTENSION/BENCH_DIP`는 항상 숫자 없음 + `smallest_available_direction_unknown` + assistance/추가 저항 양방향
  안내. Regression, recovery hold/reduce, 48 h rest rule은 기존대로 숫자 `maintain`으로 덮는다. 15%는 사용자 history로
  보정한 숫자 목표 신뢰 기준(생리학적 최적값 아님). 상세는 `docs/training-recommendation.md` "증량 step".
- (`c3f5842`/`8b08773`, 2026-10-02 local main으로 fast-forward 통합, 이후 origin에 포함(`8845b41`, ls-remote 확인); production live 검증 완료 —
  아래 Verification) Daily orchestration
  `muscle50 daily [--date D] [--focus F] [--avoid M ...] [--json]`과 `muscle50 daily --after-workout [--date D] [--json]`.
  `application/daily_sync.py`의 `RunDailySync`가 기존 use case만 조합한다: Garmin 로그인 1회 → `IngestGarminActivityRange`
  (D-1~D) → `BackfillActivityLoadMetrics` → `SyncGarminRecovery.execute_range`(D-1~D) → `BuildTrainingRecommendation`(D).
  `--date` 기본값은 이 컴퓨터의 오늘(`date.today()`). `--after-workout`은 activities + load metrics만(recovery·추천
  `skipped`). Normalization/저장/recovery/추천 규칙은 새로 만들지 않았고 idempotency와 RAW snapshot 의미는 그대로다.
  실패 규칙: 세 sync 단계는 서로 독립이라 한 단계가 실패해도 나머지는 실행해 유효한 작업을 보존한다. Activity
  discovery 실패 시 load_metrics는 `not_run`. 개별 activity 실패, page limit, 이번 실행에서 저장한 activity의 RAW summary
  누락, recovery 날짜 실패/미시도는 해당 단계 `failed`. 이전부터 있던 activity의 RAW 누락, recovery endpoint 경고, 이번에
  저장한 activity의 선택 endpoint 경고(splits/exercise sets/original 실패; `RangeIngestOutcome.warnings`로 새로 전달,
  `garmin activities` 출력은 불변)는 `warning`이며 activity 경고에는 `muscle50 garmin refresh <id>` 복구 안내가 붙는다. 어느 단계든 `failed`/`not_run`이면 추천은 만들지 않고(`not_run`) exit 1이며, read-only
  `muscle50 recommend --date D` 명령을 안내한다. 알려진 오류 계열만 잡고 그 밖의 오류(예: range ingest가 일부러 전파하는
  local 무결성 오류)는 명령 전체를 중단한다. 출력: ASCII 단계 블록 + `Stored data now` freshness 줄 + 기존
  `recommend` text 그대로. `--json`은 단계 요약 + `"recommendation"`에 standalone `recommend --json` 문서를 그대로 넣고
  recovery row timestamp는 넣지 않아 같은 입력이면 byte-identical. 진행 안내와 Garmin 재로그인 prompt는 stderr.
- (`8f267a2`/`caa7982`, local main 통합) Nutrition → Daily/Recommendation Integration v1:
  `recommend`/`daily`가 추천 날짜의 nutrition status를 보여 준다. `availability`: `no_targets_configured`(목표 전부 unset —
  text 절 없음, 기존 text와 동일), `no_intake_logged`(식사 0개 — "0 kcal/0 g 아님" 한 줄, 행동 없음), `evaluated`, `unavailable`
  (목표 파일 손상/DB 읽기 불가 — 이유 한 줄, 추천 유지, exit 0). 행동은 complete total의 `below_*`에서만: protein
  `protein_below_target`, kcal `energy_below_target`(운동 있으면 fuel 문구 + "plan 불변"), carbohydrate는 `fuel_relevant`일
  때만 `carbohydrate_below_target_for_training`. `fuel_relevant` = strength 세션 계획 && adjustment != reduce, 또는 다음 수영
  `distance_progression`/`pace_intervals`. Above/reached/within은 status만(보상 조언 없음), `indeterminate`는 "N item 값 없음,
  known은 하한" 표시만, `no_target`은 표시·행동 없음, fat은 행동 없음. 숫자/임계값/목표값 하드코딩 없음 — 숫자는 status에서만.
  JSON: 기존 필드 불변 + 끝에 `nutrition`(`guidance_version` 1, `availability`, `unavailable_reason`, `meal_count`, `item_count`,
  `training_context`, `nutrients` = `nutrition status --json`의 `nutrients`와 동일, `actions`). `recommendation_version` 1 유지.
  `daily`는 추천이 만들어진 경우에만 nutrition을 붙이고 단계로 취급하지 않는다(`ok` 불변); daily JSON의 `recommendation`은
  계속 standalone `recommend --json`과 같다. Nutrition 쪽 변경은 `ShowDailyIntake`/`ShowDailyNutritionStatus`가 좁은
  `MealReader` protocol을 받게 한 것과 `nutrient_status_line`/`nutrient_status_payload` 공개(출력 불변)뿐.
- (`c77de0d`/`1549c4a`, main/origin 포함) Nutrition Targets + Daily Status v1:
  `muscle50 nutrition target set {kcal,protein,carbs,fat} (--exact N | --range MIN MAX | --unset)`,
  `muscle50 nutrition target show [--json]`, `muscle50 nutrition status [--date D] [--json]`. 목표는 Decimal, > 0,
  range는 inclusive(min <= max, 같아도 됨), unset ≠ 0, 자동 계산 없음. 저장: `<home>\config\nutrition_targets.json`
  (`schema_version` 1, 값은 decimal 문자열만 — JSON number 거부, 모든 nutrient에 명시적 kind, 원자적 write, 읽기는
  파일을 만들지 않음, 손상된 파일은 오류). 목표 history 없음 — 과거 날짜도 현재 목표와 비교(출력에 사용한 목표 표시).
  Status: `no_target`, `no_intake_logged`(식사 0개 = core 규칙대로 incomplete, 0 아님), exact `below_target`/
  `target_reached`(Decimal 동등, tolerance 없음)/`above_target`, range `below_range`/`within_range`/`above_range`,
  `indeterminate`. 값이 없는 item이 있으면 `consumed`/`remaining`/`excess`는 null, `known_subtotal`과 `missing_items`
  (meal/sequence/food) 표시. Known subtotal은 하한(nutrient 값은 non-negative 검증)이므로 known > exact 값 또는 range
  상한일 때만 `above_*` 확정. `remaining`/`remaining_to_maximum`/`excess`는 음수 없음. `nutrition day` 출력은 scope 안내
  문장만 바뀜(JSON 불변).
- (main `7f4a4ef`에 포함) Nutrition Logging MVP — intake only:
  `muscle50 nutrition food add|list|show`, `muscle50 nutrition log`, `muscle50 nutrition day [--date D] [--json]`.
  Food = 기존 `FoodNutritionProfile` + fact 1개(`food:<id>:1`, 사용자/라벨이 준 값, source/accuracy/reference 필수 보존).
  `--kcal/--protein/--carbs/--fat` 모두 필수, 모르면 `unknown`(None, 0 아님). Source는 `nutrition_label`/`user_provided`/
  `known_product`/`food_database`만(추정 source 거부). 중복 food ID와 이미 쓰인 name/alias(대소문자 무시)는 거부.
  식사 기록 시 음식의 logged unit fact history 전체를 meal item 소유 fact로 snapshot(`<meal_id>:<seq>:<catalog fact_id>`,
  provenance 그대로, supersession link도 snapshot ID로 재매핑 — nutrient별 supersession이라 winner만 복사하면 선택이 달라질
  수 있음) → item의 nutrient별 선택 = catalog 선택, 이후 catalog 수정이 과거 식사를 바꾸지 않는다. 단위 변환 없음(맞는 unit fact가 없으면
  거부). 같은 날짜·같은 meal type 두 번째 기록은 `--additional` 없으면 거부(삭제 경로가 없어 이중 기록 방지). `--time`
  없으면 local 00:00 저장, 기본 날짜는 이 컴퓨터 오늘, 하루 경계는 이 컴퓨터 UTC offset(fixed offset, tzdata 불필요).
  집계는 `aggregate_meal`/`aggregate_day` 그대로: 한 item이라도 값이 없으면 해당 nutrient total은 incomplete(known
  subtotal 별도 표기, item별 missing 표시), estimated fact 포함 total은 `(estimated)`. JSON은 exact Decimal 문자열,
  고정 순서, byte-stable.

## Pending merge

- 현재 pending merge 없음.
- `feature/nutrition-recommendation`(Nutrition → Daily/Recommendation Integration v1, `8f267a2`, `caa7982`)는 2026-10-02
  local main으로 fast-forward 통합됐다(`f07f5a2` → `caa7982`, merge commit/rebase/squash 없음). 통합 전 `git fetch` +
  `git ls-remote`로 origin/main = `f07f5a2` 확인. origin push 안 함(별도 승인). Branch와 Paseo worktree
  `nutrition-recommendation`은 유지한다.

- `feature/nutrition-targets`(Nutrition Targets + Daily Status v1, `c77de0d`, `1549c4a`)는 2026-10-02 local main으로
  fast-forward 통합됐다(`7f4a4ef` → `1549c4a`, merge commit/rebase/squash 없음). 통합 전 `git fetch` + `git ls-remote`로
  origin/main = `7f4a4ef` 확인. 당시 origin push는 하지 않았으나 이후 push되어 origin/main `f07f5a2`에 포함됐다
  (2026-10-02 `git merge-base --is-ancestor`로 `c77de0d`, `1549c4a` 확인). Branch와 Paseo worktree `nutrition-targets`는
  유지한다.
- Nutrition Logging MVP(`9ec54d1`, `7f4a4ef`)는 main에 포함됐다(2026-10-02 local `main` = `origin/main` = `7f4a4ef`).
- Daily orchestration(`c3f5842`, `8b08773`)은 2026-10-02에 local main으로 fast-forward(`c06a36c` → `8b08773`, merge
  commit/rebase/squash 없음)됐다. 당시 origin/main은 `c06a36c`였으나 이후 push되어 2026-10-02 `git ls-remote origin
  refs/heads/main` = `8845b41`(= local main)로 확인했다. Branch `feature/daily-sync`와 Paseo
  worktree `daily-sync`는 유지한다.
- Progression Hardening v1(`13d5ed2`)은 2026-10-02에 main으로 fast-forward(`4f26ec2` → `13d5ed2`, merge commit/rebase/
  cherry-pick 없음)되고 origin에 일반 push됐다. main = origin/main = GitHub main `13d5ed2`(`git ls-remote` 확인).
  Branch `feature/progression-hardening`(`13d5ed2`)과 Paseo worktree `progression-hardening`은 의도적으로 유지한다.

- Recommendation Hardening v1 통합(`5fbdd56`/`38a23ae`/`4f26ec2`)과 Taxonomy coverage(`aba8cfe`)는 main = origin/main
  `4f26ec2`에 포함됐다(2026-10-01 `git rev-parse` 확인). 원본 `feature/recommendation-hardening`(`272761a`)은 reference로
  그대로 둔다.
- 사용자 지정 focus override(`--focus`)는 `8b259e7`로 main/origin에 포함됐다(2026-10-01 `git branch -vv` 확인).
- Training Recommendation v1은 `7740d7d`로 main/origin에 포함됐다(push 완료).
- Exercise Taxonomy v1은 `a92404b`로 main/origin에 포함됐다.
- Analytics Engine v1은 `2603b85`로 main/origin에 포함됐다.
- `feature/garmin-analytics-prerequisites`는 main `dc2c99f`에 통합 완료.

## Garmin Analytics Prerequisites status

- 구현, 실데이터 검증, main 통합 완료(`dc2c99f`).
- 완료: historical activity import(2026-07-01~08-02), recovery 28일 backfill(2026-09-01~28), recovery
  normalizer v2 re-normalization, activity load-metric backfill(78/78 activity).
- 보류: `sync_runs` recovery coverage, 향후 import의 자동 load-metric enrichment.
- Analytics Engine v1(rolling snapshot)은 `2603b85`로 main에 포함됐다.

## Data coverage (production, 2026-09-30)

- Garmin activities: 78건, 2026-07-01~2026-09-28, 54 distinct training days.
  Strength 55, lap swimming 21, running 1, track running 1. 78건 모두 10개 load metric 보유(780 rows).
- Garmin recovery: 2026-09-01~2026-09-28, 28/28 날짜, recovery normalizer version 2.
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

2026-10-02 Nutrition → Daily/Recommendation Integration v1 main 통합(`f07f5a2` → `caa7982` fast-forward, push 안 함):

- 통합 후 main: `uv run --extra dev pytest` 842 passed, `ruff check .`, `mypy src tests`(115 files), `git diff --check` 통과.
- 임시 home(production DB 파일 복사본 + 합성 nutrition) acceptance 26/26: 목표 없음/목표만/평가/unavailable(non-UTF-8, 디렉터리,
  byte-range lock) 모두 training JSON이 통합 전 `f07f5a2`의 `recommend --json`과 동일(nutrition 절을 뺀 text도 동일),
  `daily`가 standalone `recommend` 문서를 그대로 포함, sync 실패/`--after-workout`이면 추천과 nutrition 없음.
- Production fingerprint 통합 전후 완전 동일(DB/WAL/SHM sha·size·mtime, 28 table, migration 1~7, RAW 974, 그 밖의 home
  파일 27개, `config\` 없음). Production에 `daily`/Garmin/nutrition 명령 실행 안 함. Evidence
  `C:\temp\muscle50-evidence-20261002-nutrition-recommendation-integration\`.

2026-10-02 Nutrition → Daily/Recommendation Integration v1(`feature/nutrition-recommendation`, base `f07f5a2`):

- `uv run --extra dev pytest` 842 passed(기존 789 + 신규 `tests/test_nutrition_guidance.py` 27, `tests/test_recommend_nutrition.py`
  18, `tests/test_nutrition_reader.py` 4, `tests/test_daily_sync.py` +4), `ruff check .`, `mypy src tests`(115 files),
  `git diff --check` 통과. 기존 테스트는 수정 없이 통과.
- Acceptance: 임시 home `C:\temp\muscle50-evidence-20261002-nutrition-recommendation\acceptance-home`(production DB를
  `mode=ro&immutable=1` backup으로 복사한 training data + 합성 음식/식사/목표). 2026-10-02: 목표 없음(text 절 없음,
  `no_targets_configured`) → 목표만(`no_intake_logged`) → 합성 식사(protein/kcal/carbs below, 행동 3개, strength `hold` 세션 =
  fuel relevant) → protein 값 없는 item 추가(`indeterminate`, known 40 하한, remaining null). JSON 재실행 byte-identical,
  `nutrients` = `nutrition status --json`, 네 경우의 training 부분 JSON 동일, 출력 전부 ASCII.
- Production: read-only `recommend --date 2026-10-02` text/JSON 1회씩(production은 목표 없음 → `no_targets_configured`,
  text 절 없음). Fingerprint before/after: DB 파일 sha/size/mtime, `-wal`(빈 파일), 28 table, RAW 974, 그 밖의 home 파일 24개
  모두 동일, `config\` 생성 없음. 유일한 차이는 `-shm` mtime(sha/size 동일) — 기존 `SqliteAnalyticsReader`만 단독 실행한
  대조 실험에서도 같은 mtime 변화(`shm_control.txt`)라 SQLite read-only WAL 열기의 기존 동작이다. Evidence:
  `C:\temp\muscle50-evidence-20261002-nutrition-recommendation\`.
- Migration 없음(`schema_migrations` 7 그대로). Production에 nutrition 명령, `daily`, Garmin 호출 실행 안 함.

2026-10-02 Nutrition Targets + Daily Status v1(`feature/nutrition-targets`, base `7f4a4ef`):

- `uv run --extra dev pytest` 789 passed(신규 `tests/test_nutrition_targets.py` 45, `tests/test_nutrition_target_store.py` 30,
  `tests/test_nutrition_target_cli.py` 32; `tests/test_nutrition_cli.py`는 바뀐 `day` scope 문장만 갱신), `ruff check .`,
  `mypy src tests`(109 files), `git diff --check` 통과.
- 테스트와 CLI acceptance는 임시 home만 사용(acceptance: `C:\temp\muscle50-evidence-20261002-nutrition-targets\acceptance-home`,
  합성 값). Production에 nutrition 명령을 실행하지 않았다. Production DB/WAL/SHM, 28 table, RAW 974 files, 그 밖의 home
  파일(`config\` 생성 여부 포함) fingerprint before = after. Evidence `C:\temp\muscle50-evidence-20261002-nutrition-targets\`.
- Migration 없음(`schema_migrations` 7 그대로).

2026-10-02 Nutrition Logging MVP(`feature/nutrition-logging`, base `8845b41`):

- `uv run --extra dev pytest` 682 passed(신규 `tests/test_nutrition_logging.py` 42, `tests/test_nutrition_cli.py` 25,
  `tests/test_nutrition_repository.py` +1), `ruff check .`, `mypy src tests`(103 files), `git diff --check` 통과.
- 테스트는 임시 DB/`MUSCLE50_HOME`(`tmp_path`)만 사용. Production에 nutrition 명령을 실행하지 않았다(read 명령도
  `_connect`가 WAL/디렉터리를 만들 수 있어 금지). Production DB/WAL/SHM sha256·size·mtime, 28 table, RAW 974 files
  fingerprint before = after, nutrition table 5개 모두 0 rows 유지. Evidence `C:\temp\muscle50-evidence-20261002-nutrition-logging\`.
- Migration 없음(`schema_migrations` 7 그대로).

2026-10-02 Daily orchestration production live 검증(사용자 실행, 실제 Garmin 계정, `feature/daily-sync` `8b08773`):

- 첫 실행: garmin_login ok, activities found 0 / new 0 / already stored 0 / failed 0, load_metrics inserted 0 /
  updated 0 / unchanged 800, recovery created 1 / updated 1 / failed 0, recommendation ok. 저장된 최신 recovery가
  2026-10-02가 됐다.
- 바로 이어 2회째: activities found 0 / new 0, load_metrics inserted 0 / updated 0 / unchanged 800, recovery created 0 /
  updated 0 / unchanged 2 / failed 0, recommendation ok. 실제 계정에서 daily 흐름과 production idempotency 확인.

2026-10-02 Daily orchestration main 통합(`c06a36c` → `8b08773` fast-forward, push 안 함):

- 통합 전 feature gates와 통합 후 main gates 모두 `uv run --extra dev pytest` 614 passed, `ruff check .`,
  `mypy src tests`(99 files), `git diff --check` 통과. 통합·gates 중 Garmin live 호출 없음.
- Production DB/RAW fingerprint 통합 전후 동일(DB/WAL, 28 table, RAW 974 files — live 검증 이후 상태), evidence
  `C:\temp\muscle50-evidence-20261002-daily-integration\`.

2026-10-02 Daily orchestration(worktree `daily-sync`, base `c06a36c`, feature branch commit):

- Gates: `uv run --extra dev pytest` 614 passed(582 + 신규 32, `tests/test_daily_sync.py`), `ruff check .`,
  `mypy src tests`(99 files), `git diff --check` 통과. 새 파일은 `ruff format` clean, `cli.py`도 clean 유지
  (`terminal.py`는 main부터 미포맷이라 전체 reformat 하지 않음).
- 테스트는 stub collaborator(단계별 실패 규칙)와 fake Garmin 하나(activity + recovery) + 임시 `MUSCLE50_HOME`의 CLI
  end-to-end로 나눴다: 기본 날짜(오늘)와 D-1~D 범위, 명시 날짜, load metric 채움, `--focus`/`--avoid` 전달,
  `--after-workout`, activity endpoint 경고 + refresh 안내, 같은 날 2회 실행 시 row 수·RAW 파일 동일(신규 0, metric
  unchanged, recovery unchanged), 단계별 실패와
  exit 1, 로그인 실패, 인증 전 입력 거부, standalone `recommend`와 JSON/text 동일, 같은 입력 JSON byte-identical.
- 구현 당시 실제 Garmin 계정은 호출하지 않았다(live 검증은 이후 사용자가 수행, 위 항목). Production DB/RAW는
  구현·테스트 중 사용하지 않았고
  fingerprint 전후 동일(DB/WAL, 28 table, RAW 954 files), evidence `C:\temp\muscle50-evidence-20261002-daily-sync\`.

2026-10-02 Progression Hardening v1 main 통합(`4f26ec2` → `13d5ed2` fast-forward, push 완료):

- 통합 후 main gates: `uv run --extra dev pytest` 582 passed, `ruff check .`, `mypy src tests`(97 files),
  `git diff --check 4f26ec2..HEAD` 통과.
- Production read-only 검증 통과(`garmin refresh` 미실행), evidence `C:\temp\muscle50-evidence-20261002-progression-integration\`:
  progression smoke(6/14/15 kg → 숫자 없는 step, 20 → 22.5, 50 → 52.5, `PULL_UP/-` direction-unknown, hold/reduce/
  48 h rest rule/regression → 숫자 maintain, 재실행 동일)와 2026-10-01 auto/push/pull/legs/shoulders를 `4f26ec2` 출력과
  비교 — focus/label/role/set/recovery·session level/hinge/coverage/notice/swim 차이 0. 바뀐 것은 push/shoulders의
  `LATERAL_RAISE/ONE_ARM_CABLE_LATERAL_RAISE` basis 한 줄뿐(recovery hold라 처방은 6 kg maintain 그대로).
  JSON 재실행 byte-identical.
- Production DB/RAW 불변: fingerprint before = after(DB/WAL, 28 table, RAW 954 files).

2026-10-01 Progression Hardening v1(worktree `progression-hardening`, base `4f26ec2`):

- Gates: `uv run --extra dev pytest` 582 passed(574 + 신규 8), `ruff check .`, `mypy src tests`(97 files),
  `git diff --check` 통과. 신규 8개는 base src에서 모두 실패(override 3개는 새 필드 assert 때문).
- Production read-only(`garmin refresh` 미실행), evidence `C:\temp\muscle50-evidence-20261001-progression-audit\`:
  93일 × 5 = 465 run을 base `4f26ec2`와 비교 — focus/label/role/set/recovery·session level/hinge/coverage/notice/swim
  차이 0. 바뀐 progression 54 항목: lateral raise 6 → 8.5(9 run), `SHOULDER_PRESS/-` 14 → 16.5(13), `PULL_UP/-`
  8 → 10.5(8)가 숫자 없는 step으로, 덮인 maintain 24개는 basis 문장만. 숫자 증량 122 유지(20 → 22.5, 50 → 52.5 포함).
  JSON/text 재실행 byte-identical. Fingerprint before = after(DB/WAL, 28 table, RAW 954).

2026-10-01 Recommendation Hardening v1 통합(worktree `integration-recommendation-hardening`, base local main `aba8cfe`):

- Gates: `uv run --extra dev pytest` 574 passed(538 + hardening 31 + 통합 회귀 5), `ruff check .`, `mypy src tests`
  (97 files), `git diff --check` 통과.
- Production read-only(`garmin refresh` 미실행): 10-01 auto/`--focus shoulders|push|pull|legs`, 09-22 text/JSON exit 0,
  JSON 재실행 byte-identical, text ASCII. 62일(08-01~10-01) × (auto + focus 4) 310 run을 승인 reference(`272761a`
  src)와 비교: 자동 focus 62/62 동일, heavy hinge 2개 plan 0, 자동 plan 중 한 primary muscle 3종목 0(사용자 지정 legs
  09-17/09-18의 quad 3종목은 reference와 동일 — glutes에 익숙한 후보가 없어 규칙상 허용), recovery level/carry 변경 0.
  결정 차이 26 run은 모두 Taxonomy coverage 데이터 효과(shoulder/lateral raise label 교체, 10-01 pull hold → reduce,
  09-23/09-30/10-01 auto·legs swim caution 추가; swim session type/main set 변경 0). 원인 표기 수정은 pre-fix 통합
  tree(`38a23ae`) 대비 결정 차이 0, text 차이는 사용자 지정 focus 37 run의 원인 문구뿐(자동 run 0).
- Fingerprint(`C:\temp\muscle50-evidence-20261001-integration-hardening\before.json`/`after.json`): DB/WAL sha256/size/
  mtime, 28 table digest, RAW 954 files 동일(coverage `final.json`과도 동일).

2026-10-01 Taxonomy coverage update(worktree `taxonomy-coverage`, base `8b259e7`, feature branch commit):

- Gates: `uv run --extra dev pytest` 538 passed(기존 524 + 신규 14), `ruff check .`, `mypy src tests`(97 files),
  `git diff --check` 통과.
- Production read-only: `analytics snapshot --date 2026-10-01 --days 28`(text/JSON, JSON 재실행 byte-identical),
  `recommend --date 2026-10-01`, `--focus shoulders`, `--focus shoulders --json` 모두 exit 0. 28일 mapped 205 → 243,
  no_rule 39 → 1(BOX_JUMP), UNKNOWN 33 그대로. Shoulders 세션 SEATED_BARBELL / DUMBBELL shoulder press +
  ONE_ARM_CABLE_LATERAL_RAISE 약 32분. 자동 focus는 legs 그대로.
- Fingerprint(`C:\temp\muscle50-evidence-20261001-coverage\before.json`/`after.json`/`final.json`/`precommit.json`): DB/WAL sha256/size/mtime,
  28 table digest, RAW 954 files 동일.

2026-10-01 Recommendation Hardening v1(worktree `recommendation-hardening`, commit `5dd2af7`, parent `8b259e7`, 검증 당시
main 미통합/미push; 이후 `5fbdd56`으로 cherry-pick되어 `4f26ec2`로 main/origin에 포함):

- Gates: `uv run --extra dev pytest` 555 passed, `ruff check .`, `mypy src tests`(97 files), `git diff --check` 통과.
- Production read-only: 8개 실행 exit 0, JSON 재실행 byte-identical, text ASCII. 작업 중 다른 프로세스의 `garmin
  refresh` 6회(16:12-16:23 KST)로 DB/RAW가 바뀌어(RAW 912 → 954, 09-22 activity가 shoulder label로 relabel) 그 이후
  상태에서 다시 검증했고 before/after fingerprint 동일(DB, 28 table, RAW 954). 62일 counterfactual: 자동 focus 62/62
  동일, 같은 muscle 3종목 plan 6 → 0, heavy hinge 2개 plan 2 → 0. Evidence `C:\temp\muscle50-evidence-20261001-hardening\`.

2026-10-01 사용자 지정 focus override(`--focus`, worktree `training-recommendation`, base `7740d7d`, feature branch commit):

- Gates: `uv run --extra dev pytest` 524 passed(기존 509 + 신규 15), `ruff check .`, `mypy src tests`(97 files),
  `git diff --check` 통과. 기존 509개 test는 수정 없이 통과(자동 focus 동작 불변).
- Production read-only `recommend --date 2026-10-01`: `--focus` 없는 JSON이 main `7740d7d` 출력과 새 field
  2개(`focus_source`, `auto_focus`)를 빼면 동일, text는 Focus 줄의 `[auto-selected]`만 다름. `--focus legs/push/
  pull/shoulders` 모두 exit 0, 요청 focus 유지. Shoulders는 SHOULDER_PRESS + LATERAL_RAISE 약 23분이며
  "history is limited"로 보고. RAW 868 files와 DB/WAL hash 전후 동일.

2026-10-01 Training Recommendation v1(`feature/training-recommendation`, base `a92404b`). Production DB/RAW는
`mode=ro&immutable=1` audit와 read-only CLI로만 사용했다.

- Gates: `uv run --extra dev pytest` 509 passed(기존 445 + 신규 64), `ruff check .`, `mypy src tests`(97 files),
  `git diff --check` 통과.
- `muscle50 recommend` 14개 날짜(07-08, 07-29, 07-31, 08-25, 08-29, 09-11, 09-13, 09-17, 09-18, 09-21, 09-24,
  09-25, 09-28, 10-01) text/JSON exit 0, JSON 재실행 byte-identical, text ASCII. 결과 표는
  `docs/training-recommendation.md`.
- Calibration: recovery 09-01~28 normal 18 / hold 4 / reduce 6; swim 21개 중 high intensity 5, butterfly ≥ 200 m 4.
- Fingerprint(`C:\temp\muscle50-evidence-20261001-recommend\before.json`/`after.json`): `muscle50.sqlite3`
  sha256/size/mtime 동일, `-wal` 0 bytes 동일, 28 table digest 동일, RAW 868 files 동일. `-shm` mtime만 변경.

2026-10-01 Exercise Taxonomy v1(`feature/exercise-taxonomy`, base `2603b85`). Production DB/RAW는
`mode=ro&immutable=1` audit와 read-only CLI로만 사용했다.

- Gates: `uv run --extra dev pytest` 445 passed(기존 390 + 신규 55), `ruff check .`, `mypy src tests`(87 files),
  `git diff --check` 통과.
- `muscle50 analytics snapshot --date 2026-09-28 --days 90 --json`(전체 데이터) exit 0, 재실행 byte-identical.
  ACTIVE 1054, 매핑 777(73.7%; confirmed 94, auto-detected 683), unmapped 277(UNKNOWN 276, PLYO/BOX_JUMP 1).
  독립 SQL 집계와 15/15 일치(total, mapped+unmapped, UNKNOWN 수와 50 activity, no-rule, 원본 label 40개 identity·
  set 수·속성, pattern, primary, secondary, 각 합계 reconciliation, canonical 필드 없음).
- UNKNOWN 276: Garmin JSON 대체 후보 없음, FIT category 65534(260)/65535(16), velocity/ROM/wktStepIndex 없음 →
  해소 0건(276 → 276). Correction/overlay 추가 없음.
- Fingerprint(`C:\temp\muscle50-evidence-20261001-taxonomy\before.json`/`after.json`): `muscle50.sqlite3`
  sha256/size/mtime 동일, `-wal` 0 bytes 동일, 28 table digest 동일, RAW 868 files 동일. `-shm` mtime만 변경
  (SQLite WAL reader mark).

2026-09-30 Analytics Engine v1(`feature/analytics-engine`, base `dc2c99f`, 미커밋). Production DB/RAW는
read-only로만 사용했다.

- Gates: `uv run pytest -q` 390 passed(기존 345 + 신규 45), `uv run ruff check .`, `uv run mypy src tests`
  (84 files), `git diff --check` 통과.
- `muscle50 analytics snapshot`을 production home에서 as-of 2026-09-17/09-10/09-03/09-28(7일)과
  2026-09-28 `--days 90`(= 2026-07-01~09-28 전체)로 text/JSON 실행, 모두 exit 0.
- 90일 JSON을 직접 SQL 재계산과 대조: 58/58 일치(activity 78, training day 54, set row 2088/ACTIVE
  1054/REST 1034, reps, volume, 제외 사유 count, UNKNOWN 276, lap 408, length 1112, swimming length,
  summary/detail/plausible distance, pool length, load metric 10종 값과 78/78 coverage, recovery row 28,
  recovery mean, latest training status). 같은 명령 재실행 JSON byte-identical.
- 2026-09-17 `24391051389`: summary 3025 m 그대로, plausible lap detail 525 m, issue 2건(phantom lap
  2500 m). 2026-09-10 `24302653969`: summary 1275 m, plausible 1200 m(phantom lap 75 m, lap/length
  distance 불일치 2 lap). 전체 swim summary 30460 m, plausible detail 27885 m, plausible lap 안의 빠른
  length 41건(개수만 보고).
- 검증 전후 fingerprint(`C:\temp\muscle50-evidence-20260930-analytics\before.json`/`after.json`):
  `muscle50.sqlite3` sha256/size/mtime 동일, `-wal` 0 bytes 동일, 28개 table 전체 row digest 동일,
  RAW 868 files sha256 동일, 새 디렉터리 없음. `-shm` mtime만 바뀌었다(SQLite WAL reader mark, 데이터와 무관).

2026-09-30 Historical Garmin activity import(commit `4645f5f` 코드, 코드 변경 없음). WAL-safe backup
`db_backup_20260930c_pre_historical_import`과 activity별 fingerprint evidence
(`C:\temp\muscle50-evidence-20260930-hist\`)로 before/after를 비교했다.

- `uv run muscle50 garmin activities --from 2026-07-01 --to 2026-08-02` → exit 0. 요청 범위는
  2026-07-01~08-02이며 Garmin이 36건을 반환했고 모두 신규 import(skip 0, 실패 0, RAW warning 0).
  실제 activity 날짜는 2026-07-01~2026-07-31이고 2026-08-01/08-02에는 activity가 없다.
  Strength 24, pool swim 12, training day 21.
- Strength: 신규 24건, canonical set 933(ACTIVE 471 / REST 462), 933 set 전부 RAW와 비교해 불일치 0.
  ACTIVE 중 UNKNOWN 147/471, weight 0/누락 39, reps 0 20 — ingestion 실패가 아닌 data-quality/review
  이슈.
- Swim: 신규 12 session, lap 286, length 645, 모든 lap/length 값 RAW 비교 불일치 0. 11 session은
  50 m pool, 2026-07-23은 source와 일관된 20 m pool. 누락된 swim child record 없음.
- Load metrics: backfill이 360 metric을 insert했고 기존 420 load metric은 불변. 78 activity 모두 10개
  metric, 780/780 값이 저장된 RAW와 일치. 두 번째 backfill canonical 변경 0.
- Regression/integrity: 기존 42 activity의 parent row, metric, strength set, swim data, refresh state,
  RAW 모두 불변. `daily_recovery`와 recovery RAW 불변. 중복/orphan 0, `PRAGMA integrity_check` = ok,
  `foreign_key_check` clean, RAW immutable(기존 628 files 불변, 신규 240 files 추가). 2026-09-17 swim
  anomaly 불변.

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

- (Daily orchestration, local main `8b08773`) `muscle50 daily` 이후에도 수동인 것: Garmin Connect에서
  종목을 고친 뒤 `garmin refresh <id>`, InBody import(`inbody sync --file`), Garmin 첫 로그인과 token 만료 시 재로그인(MFA,
  terminal 필요), 자동 예약 실행(scheduler 없음). Sync coverage는 여전히 기록하지 않는다(`sync_runs` 미사용) — "운동 없음"과
  "미동기화"를 구분하지 못한다. 기본 날짜는 이 컴퓨터의 날짜라 자정 직후 실행이나 다른 시간대 기록은 `--date`로 지정해야
  한다. 오늘 recovery row는 시계가 아침 데이터를 올린 뒤에야 sleep/readiness가 채워진다(partial row는 실패가 아니라
  데이터로 보고). `--json`은 저장된 Garmin 로그인이 유효할 때 stdout이 JSON만이다(재로그인 prompt는 stderr). Load metric
  backfill은 기존 use case 그대로 저장된 전체 activity를 다시 확인한다(idempotent, Garmin 호출 없음). Activity endpoint
  경고(예: exercise sets 없이 저장)는 그 activity를 처음 저장한 실행에서만 보인다 — 이후 실행은 이미 저장된 activity를
  건너뛰므로 `garmin refresh <id>`로 직접 복구해야 한다. PowerShell 5.1에서 `*>`/`2>&1`로 출력을 돌리면 stderr 진행 줄이
  빨간 NativeCommandError로 보이지만 표시 문제일 뿐이고 결과는 exit code로 판단한다.
- (Progression Hardening v1 `13d5ed2`에서 수정, main/origin 포함) 고정 +2.5 kg step이 가벼운
  isolation에 과했다(`LATERAL_RAISE/ONE_ARM_CABLE_LATERAL_RAISE` 6 → 8.5 kg, 42%). 이제 15% 초과면 숫자 없이 "next
  available step above 6 kg". 남은 한계: 장비별 실제 증량 단위는 모름(추론 안 함), 증량 후 reps 재시작(상한 - 4)은
  작은 무게에서도 그대로, 15%는 숫자 목표 신뢰 기준이지 생리학적 최적값이 아니며 근거는 소수 사례이고 16.7-20 kg
  trigger는 production에 없다. Progression v2(정확한 label별 장비 증량 단위 학습)는 충분한 데이터가 쌓인 뒤의 향후
  작업이다.
- `PLYO/BOX_JUMP`(1 set, 자동 인식 37.5%)는 의도적으로 rule 없음(사용자 결정 2026-10-01; plyometric은 v1 범위
  밖). 유일한 non-UNKNOWN ACTIVE `no_rule` label.
- (Hardening v1 `5dd2af7`에서 수정, 통합 commit `5fbdd56`으로 `4f26ec2`부터 main/origin 포함) Recommendation swim history가 D-27~D로 strength(D-28~D-1)보다 하루 짧았다. 이제
  D-28~D. 2026-10-01에는 09-03 swim이 다시 포함되어 best freestyle pace baseline이 200 m 2:22/100 m에서 550 m
  1:53/100 m(09-03 lap 2)로 바뀐다(이전 기록의 "영향 없음"은 연속 거리만 본 판단이었다).
- `--focus shoulders`는 posterior deltoid primary rule/label이 없어 여전히 짧다. Taxonomy coverage(`aba8cfe`) 이후
  09-22 relabel 3종(SEATED_BARBELL/DUMBBELL_SHOULDER_PRESS, ONE_ARM_CABLE_LATERAL_RAISE, 17 set)이 매핑되어 통합
  tree의 10-01 shoulders는 그 3종목 약 32분이다. Posterior는 `no_taxonomy_rule`로 누락을 명시하고 채우지 않는다.
- No-rule label(2026-10-01, 28일, 통합 tree): `PLYO/BOX_JUMP`(09-10, 1 set)뿐. Hardening v1 작성 당시의 나머지 7개
  (`PULL_UP/CLOSE_GRIP_LAT_PULLDOWN`, `PULL_UP/WIDE_GRIP_LAT_PULLDOWN`, `ROW/BENT_OVER_ROW_WITH_BARBELL`,
  `TRICEPS_EXTENSION/LYING_TRICEPS_EXTENSION_TO_CLOSE_GRIP_BENCH_PRESS`, 09-22 shoulder 3종)는 `aba8cfe`에서 rule이
  추가됐다. 그래서 10-01 pull은 09-30 15 set이 세져 48 h rest rule로 reduce된다(recovery 자체는 hold). 추천은 no-rule
  label을 경고만 하고 세지 않는다.
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
- Data-quality findings(future Analytics quality layer, 수정하지 않음):
  - 2026-07 신규 기간 수영 length 40/417이 42 s/100 m보다 빠르다(12 session 중 9개). 기존 swim
    데이터에도 같은 현상이 있어 import 실패가 아닌 systemic source/data-quality 이슈다.
  - 신규 ACTIVE strength set 중 UNKNOWN 분류 147/471, weight 0/누락 39, reps 0 20.
  - 2026-07-20 swim 2건(`23659117397`, `23659117767`)은 27분 간격으로 split session일 수 있다.
    자동으로 합치지 않는다.
  - 2026-07-23 20 m pool은 내부적으로 일관되며, 평소와 다른 pool 길이라는 이유만으로 오류로 취급하지
    않는다.
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
- Analytics v1 data-quality 판정(수정하지 않음, `docs/analytics-engine.md`): 2026-09-17 `24391051389`와
  2026-09-10 `24302653969`의 Garmin summary distance가 phantom lap(2500 m, 75 m)을 이미 포함한다.
  Snapshot은 summary를 그대로 보고하고 plausible lap detail distance를 따로 제공한다.
- Analytics v1 gap: muscle-group mapping 없음, `swim_lengths.length_type` 전부 NULL, `pool_length`
  activity metric unit NULL, lap duration vs length duration 불일치 규칙 미정, swim pace/SWOLF
  progression과 기간 비교(trend)는 아직 없다.
- (Nutrition Recommendation v1, `feature/nutrition-recommendation`) 추천 날짜 D의 섭취만 본다(어제 완료된 섭취 미사용).
  시각을 모르므로 아침에는 대부분 below로 보고된다("Logged so far" 표기). `fuel_relevant`는 계획(strength 세션/조정,
  다음 수영 종류)만 보고 실제 운동 시각을 모른다. Fat 행동 없음. SQLite가 read-only 열기에서 빈 `-wal`/`-shm`을 만들거나
  `-shm` mtime을 갱신하는 것은 기존 analytics reader와 같은 동작이다.
- (Nutrition Targets v1) 목표 history 없음(과거 날짜도 현재 목표로 비교), 요일/운동일별 목표 없음, 목표 자동 계산 없음. 식사 0개인 날은 `no_intake_logged`이며 "기록했고 먹지 않음"을 표시할 방법이
  없다. Estimated total은 point 값으로 비교한다. Text는 0.1 반올림(정확한 값은 `--json`).
- (Nutrition Logging MVP) 계산된 nutrition target, 메뉴·운동 전후 식사 추천, 자유 문장
  meal parser(`MealParser` 구현), 외부 food DB/barcode/사진, 주간 분석은 아직 없다. 식사/음식 수정·삭제 CLI 없음 —
  nutrition fact는 append-only trigger, meal item → fact는 `ON DELETE RESTRICT`라 기록된 식사를 schema 변경 없이 지울 수
  없다(정정 설계는 보류; catalog는 code에서 `append_nutrition_fact` superseding fact로만 정정 가능). 음식당 CLI fact 1개,
  unit 간 변환(예: 1 pack = 210 g) 없음. `--time` 없는 식사와 `--time 00:00`은 구분되지 않는다.
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
- Nutrition 목표는 SQLite table이 아니라 `<home>\config\nutrition_targets.json`에 둔다 — fact history가 아닌 작은 사용자
  설정이라 migration이 필요 없고, 식사 data와 분리돼 목표 변경이 기록을 바꾸지 않는다. `config\`는 `ensure_directories`가
  아니라 첫 `target set`에서만 만든다(모든 명령이 production에 디렉터리를 만들지 않도록).
- `feature/garmin-recovery`의 provisional migration 2는 가져오지 않고 최신 global chain의
  `005_daily_recovery.sql`로 재통합했다.
- Recovery endpoint는 개별 실패를 warning으로 격리하되 인증 오류와 전 endpoint 실패는 전체
  sync 실패로 처리한다.
- `SyncLatestGarminActivity.execute()`의 activity별 로직(RAW capture, normalize, Strength/Swim
  local backfill 포함)을 `IngestGarminActivity`로 추출해 `garmin latest`와 `garmin activities
  --from/--to`가 같은 코드를 공유하도록 했다. Swim이 필요로 하는 lap/length 계층은 이미
  모든 activity에서 무조건 가져오는 `splits` RAW로 충분해 새 RAW endpoint나 migration을
  추가하지 않았다.
- Exercise taxonomy는 원본 Garmin label을 identity로 유지하고(이름 변경·canonical 병합 없음) 속성만 붙이는
  명시적 rule table이다. UNKNOWN은 추측하지 않고, 이름이
  없는 새 variant를 category rule로 떨어뜨리지 않으며, primary muscle만 headline set 수로 센다(secondary는
  별도 exposure, 가중치 없음). `CRUNCH/LEG_EXTENSIONS`는 `category_override`로 knee extension에 매핑했다
  (Garmin catalogue에 machine leg extension 없음, 사용자 지정 label).
- Analytics는 schema를 추가하지 않는 computed read model이다. Garmin summary 값은 절대 보정하지 않고,
  swim detail은 lap 평균 속도 > 2.5 m/s(또는 distance가 있는데 duration 없음)이면 detail-derived distance
  에서만 제외하고 quality issue로 보고한다. Load metric은 metric별 명시적 rule(sum/max)만 쓰고 평균은
  쓰지 않는다. `training_load` 합은 Garmin acute load가 아니다.
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
