# Analytics Engine v1 — rolling training snapshot

저장된 canonical 데이터만 읽어 요청 날짜 기준 rolling window(기본 7일)의 training snapshot을
결정적으로 계산한다. 추천, 생리학적 점수, 데이터 수정은 하지 않는다. Migration 없음.

```powershell
uv run muscle50 analytics snapshot --date 2026-09-28            # 7일, text
uv run muscle50 analytics snapshot --date 2026-09-28 --days 28  # 1~90일
uv run muscle50 analytics snapshot --date 2026-09-28 --json     # provenance 포함 전체 JSON
```

## 구조

| 계층 | 파일 | 역할 |
| --- | --- | --- |
| domain | `src/muscle50/domain/analytics.py` | 순수 함수 `build_training_snapshot(as_of, lookback_days, activities, recoveries)`. 입력은 기존 `NormalizedActivity`/`DailyRecovery` 그대로 |
| infrastructure | `src/muscle50/infrastructure/sqlite/analytics_reader.py` | `SqliteAnalyticsReader`: `mode=ro` + `PRAGMA query_only`, 단일 read transaction, migrate/mkdir/WAL pragma 없음, DB 없으면 생성하지 않고 오류, schema version < 7이면 오류 |
| application | `src/muscle50/application/training_snapshot.py` | `BuildTrainingSnapshot`: window 검증 → reader → domain |
| presentation | `src/muscle50/presentation/terminal.py` | `render_training_snapshot`(ASCII only, cp949 안전), `render_training_snapshot_json`(`ensure_ascii`, provenance 전체) |
| CLI | `muscle50 analytics snapshot` | `AppPaths.from_environment()`만 사용. `ensure_directories()`, `migrate()`, Garmin 인증 없음 |

## 공통 규칙

- **Window**: `--date`를 마지막 날로 하는 inclusive local calendar date `lookback_days`일.
  `--date`는 필수(암묵적 "오늘" 없음). Activity 날짜는 Garmin `started_at_local`의 날짜 부분을
  그대로 쓴다(zoneinfo 사용 없음 → Windows tzdata 문제 없음). local 시작 시각이 없는 activity는
  어느 window에도 넣지 않고 `undated_activity` issue로 보고한다.
- **Missing ≠ 0**: 모든 aggregate(`MetricAggregate`)는 `values`(source ID별 값)와
  `missing_source_ids`를 가진다. 기여 값이 하나도 없으면 `value = None`.
- **결정성**: activity는 (local date, local start, source ID)로 정렬, float 합은 `math.fsum`
  (순서 무관, exact rounding). 같은 DB 상태 → byte-identical JSON(실데이터로 확인).
- **Provenance**: activity aggregate는 source activity ID, recovery는 calendar date 단위로
  추적된다. JSON에는 per-activity 값, 세션별 요약, recovery 원본 row가 모두 포함된다.
- 활동이 없는 날과 sync하지 않은 날은 여전히 구분할 수 없다(`sync_runs` coverage 보류와 동일).

## Garmin load metric 10종의 aggregation semantics

| metric | rule | 이유 |
| --- | --- | --- |
| `training_load` | sum | activity별 부하 점수의 window 합계. **Garmin acute load(지수가중)가 아니다** |
| `aerobic_training_effect` | max | 0–5 bounded session score. 합/평균은 의미 없음 → 최고 session + per-activity 값 |
| `anaerobic_training_effect` | max | 동일 |
| `hr_time_in_zone_1..5_seconds` | sum | 가산 가능한 시간(초) |
| `moderate_intensity_minutes` | sum | 가산 가능한 분 |
| `vigorous_intensity_minutes` | sum | RAW 원값 합. Garmin 주간 목표식의 2배 가중은 적용하지 않음 |

평균(mean)은 어떤 load metric에도 쓰지 않는다. per-activity 값은 모든 metric에서 `values`로
항상 제공된다. 매핑은 `LOAD_METRIC_AGGREGATION`이 유일한 정의이며 테스트가 10개 key 전부를
정확히 한 번씩 덮는지 검사한다. 합계는 overview(전체), strength, swimming 각각 계산한다.

## Strength

- Session = `canonical_type = strength` activity. set detail이 없으면 `strength_set_detail_missing`.
- Active set = `set_type = 'ACTIVE'`. REST row는 개수만 보고.
- Reps = ACTIVE set의 non-null reps 합. reps NULL set 수와 reps 0 set 수를 따로 보고.
- Volume = `normalized_weight_kg × reps`, **weight > 0 이고 reps > 0인 set만**. 제외 사유
  (첫 번째 실패 사유 하나): `missing_reps`, `zero_reps`, `missing_weight`, `negative_weight`
  (Garmin `-1 g` sentinel), `zero_weight`(bodyweight 또는 미기록 — 외부 부하 volume은 "0"이 아니라
  "모름"). 기여 set이 없으면 volume `None`.
- Exercise aggregation key = (`source_exercise_key`, `source_exercise_category`). UNKNOWN/missing
  분류는 기존 `derive_activity_review()` 기준으로 `classified = false`로 따로 모으고
  `strength_unclassified_exercise` issue(set sequence 포함)를 낸다. 종목을 추측하지 않는다.
- **Exercise taxonomy v1**(`docs/exercise-taxonomy.md`): `strength.taxonomy`가 ACTIVE set을 원본 Garmin
  `(category, name)` label별(`by_exercise`, 이름 변경/병합 없음), movement pattern별, primary muscle별로 각각
  정확히 한 번 센다(pattern/primary 합계 + unmapped = active set). Primary-muscle active set이 muscle-group
  headline이고, secondary muscle은 별도 `secondary_muscle_set_exposures`로만 보고하며 primary 합계에 더하지
  않는다. UNKNOWN set 수와 영향 activity, rule 없는 label 수를 따로 보고하고, rule 없는 label은
  `strength_unmapped_exercise` issue를 낸다. 모든 group은 Garmin label origin(confirmed/auto-detected/
  unspecified) 개수와 activity/set provenance를 가진다. 가중치·fractional set 없음.

## Swimming — summary vs detail, malformed detail 처리

Summary-level(Garmin `activities` row, `swim_activities.pool_length_meters`, load metric)과
lap/length detail-level 값을 항상 별도 필드로 둔다.

| field | level | 의미 |
| --- | --- | --- |
| `summary_distance_meters`, `elapsed_seconds`, `moving_seconds`, load metrics | summary | 저장된 값 그대로. 절대 수정하지 않음 |
| `pool_length_meters` | summary | `swim_activities`의 정규화 값(`pool_length` metric은 unit이 NULL이라 쓰지 않음) |
| `detail_distance_meters` | detail | lap effective distance 합(`COALESCE(corrected, garmin)`, 현재 correction 0건) |
| `plausible_detail_distance_meters` | detail | implausible lap을 제외한 lap distance 합 |
| `swimming_length_count` | detail | distance > 0 length 수(`length_type`이 production 1112건 모두 NULL이라 idle 판별은 distance로만 가능) |

**Plausibility 규칙** (`MAX_PLAUSIBLE_SWIM_SPEED_MPS = 2.5`): distance > 0인 lap/length가
duration 없음/≤0이거나 평균 속도가 2.5 m/s(= 40 s/100 m, 50 m 자유형 세계기록 평균 약 2.39 m/s보다
빠름)를 넘으면 implausible. 이것은 생리학 모델이 아니라 장비 segmentation/timing artifact 판정용
data-quality bound다.

- **Lap 단위가 distance 제외를 결정한다.** Implausible lap의 distance만 plausible detail distance에서
  빠진다. Production에서 lap 속도는 1399 m/s, 77.6 m/s 다음이 2.45 m/s로 크게 벌어져 있어
  lap 판정은 threshold 선택에 민감하지 않다.
- **Plausible lap 안의 빠른 length는 개수만 센다**(`swim_length_implausible_speed`). distance는 그대로
  둔다 — length 경계 timing 오류일 가능성이 높고 lap distance는 정상이기 때문. (Length 개수는
  threshold에 민감하다. Production 전체 length 기준 — phantom lap 안의 102건 포함 — 2.38 m/s 151건,
  2.5 m/s 143건, 5 m/s 104건. Snapshot이 보고하는 plausible lap 안의 개수는 2.5 m/s에서 41건.)
- Lap distance ≠ 그 lap length distance 합이면 `swim_lap_length_distance_mismatch`.
- Garmin summary distance가 lap 합계와 같고 implausible lap distance를 포함하면
  `swim_summary_distance_includes_implausible_laps`(activity ID와 m 수 명시). **Summary 값은 그대로
  보고한다** — 조용히 빼지 않고, 하나의 "보정된" 합계를 canonical처럼 내놓지도 않는다.

### 2026-09-17 swim (`24391051389`)

- Garmin summary distance 3025 m는 **이미 phantom lap을 포함한다**(summary = lap 합 = length 합).
  즉 "malformed detail이 summary를 오염시키지 않게" 하는 것만으로는 부족하고, summary 자체가
  오염돼 있다는 사실을 표시해야 한다.
- Lap seq 1(`lapIndex` 3): 2500 m / 1.787 s(1399 m/s), 101 length 중 distance 25 m인 100개가
  모두 1초 미만. 사용자 보고의 "1초 미만 length 102개" = 이 100개 + lap 6, 19의 distance 없는
  idle length 2개(0.824 s, 0.594 s).
- Snapshot 결과: summary 3025 m(그대로), plausible detail 525 m(100+100+125+200), issue 2건.
  HR 기반 load metric(training load, TE, zone, intensity minutes)은 distance 파생이 아니므로 영향 없음.
- 같은 규칙으로 2026-09-10 `24302653969`도 발견: lap seq 2가 75 m / 0.966 s, lap 2(75 m vs length 50 m)와
  lap 3(0 m vs length 25 m)이 불일치. summary 1275 m, plausible detail 1200 m.
- Production 데이터는 수정하지 않았다. 수정이 필요하면 기존 `corrected_distance_meters` overlay 또는
  `activity_corrections` 경로로 별도 승인 후 진행한다.

## Recovery

- Window 날짜 중 row가 없는 날(`dates_without_row`)과 row는 있으나 field가 NULL인 날(field별
  `null_dates`, 예: 2026-09-13 sleep)을 구분한다.
- Daily 측정값(sleep/stage seconds, sleep score, sleep HRV, overnight HRV, resting HR, body battery
  high/low, stress, readiness score, respiration): latest(+날짜), mean, min, max, available dates.
- State 값(`hrv_weekly_avg_ms`, `recovery_time_minutes`): 이미 rolling/전망 값이므로 latest(+날짜)만.
- Categorical(`training_status_key`, `hrv_status`, `training_readiness_level`,
  `recovery_time_change_phrase`): latest(+날짜)와 날짜별 값.
- 같은 날짜 row가 두 개면 오류(UNIQUE 제약상 발생하지 않아야 함).

## Gaps (v1 범위 밖, 발명하지 않음)

- UNKNOWN 분류 ACTIVE set 276/1054는 저장된 DB/RAW/FIT로 해소 불가(`docs/exercise-taxonomy.md`).
  매핑된 777 set 중 683은 watch 자동 인식 label이다.
- `swim_lengths.length_type` 전부 NULL → active/idle 구분은 distance 기준.
- `pool_length` activity metric unit NULL(21건) → `swim_activities.pool_length_meters` 사용.
- Activity/recovery sync coverage 기록 없음 → "활동 없음"과 "미동기화" 구분 불가.
- Lap duration과 length duration 합의 불일치(예: 09-17 lap 1: 1.787 s vs 2.849 s)는 v1에서
  별도 issue로 내지 않는다(정상 데이터에서도 잡음이 많을 수 있어 규칙 미정).

## Read-only 보장

- `mode=ro` + `query_only`: 테스트가 write 시도가 실패함을 확인한다.
- DB 파일이 없으면 `AnalyticsDatabaseError`, 디렉터리/파일을 만들지 않는다(테스트).
- Main DB 파일 bytes/mtime 불변(테스트 + production fingerprint). WAL 모드 SQLite reader는 `-shm`
  index에 reader mark를 쓰고, 없으면 빈 `-wal`/`-shm`을 만든다. 이는 SQLite WAL reader의 본질적 동작이며
  데이터 내용과 무관하다(`immutable=1`은 동시 writer가 있을 때 안전하지 않아 쓰지 않는다).
