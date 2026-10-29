# Strength Set Timing Correction v1 — 늦게 누른 버튼으로 휴식에 묻힌 운동 시간 추정

근력 운동에서 시계 버튼을 늦게 누르면 실제 운동이 앞 REST로 기록되고, 뒤따르는 ACTIVE 세트는 1~2초에 4~5회처럼
불가능하게 짧다. `analytics snapshot`은 이런 세트를 찾아 보여 주고, 저장된 손목 심박으로 판단할 수 있으면 실제 운동
시작, 추정 운동 시간, 추정 휴식 시간을 범위와 신뢰도와 함께 보여 준다.

- **표시 전용**: 어떤 추천·휴식·영양 규칙도 이 값을 쓰지 않는다. 출력에도 `display only, used by no rule`(text),
  `"display_only": true`(JSON)로 적는다.
- **읽을 때 계산**: 저장하지 않는다. 파생 table, 보정 column, migration이 없다. 매번 canonical `strength_sets`와 저장된
  `details.json`에서 다시 계산한다. 정규화된 세트와 RAW는 바뀌지 않는다(수영 plausible lap detail과 같은 방식: 원본은
  그대로, 파생 값은 따로, 추측하지 않음).
- **소급**: 이미 저장된 활동도 RAW만 읽어 계산한다. Garmin을 부르지 않는다.
- 근거 ID는 `docs/evidence/training-nutrition-evidence.md`의 것이다. `[design]`은 근거가 숫자를 주지 않는 설계 값이다.

Non-goals: 횟수·무게·운동 종류 수정(사용자가 정확히 기록한다), 추천 규칙 변경, 휴식 시간 조언(근거 규칙집 뒤의 별도
기능), Garmin 동기화 변경, LLM. 심박 값(bpm)은 건강 값이라 text와 JSON 어디에도 출력하지 않는다(규칙 기준값 10 bpm만
`rules`에 있다).

## 명령

명령과 flag는 그대로다. 새 flag 없음, exit code 그대로(0 ok, 1 알려진 오류 `오류: ...`, 2 argparse, 130 Ctrl+C).

```powershell
uv run muscle50 analytics snapshot --date 2026-03-14
uv run muscle50 analytics snapshot --date 2026-03-14 --json
```

### Text(합성 값)

window에 의심 세트가 하나라도 있을 때만 Strength 절 끝, taxonomy 줄 다음에 붙는다.

```text
  Set timing [design; display only, used by no rule]: 7 ACTIVE sets, 6 checked, 2 too short for their reps (< 1.0 s/rep); 1 estimated from heart rate, 1 not estimated
    2026-03-12 9101 seq 1 PULL_UP/WIDE_GRIP_PULL_UP #1: 5 reps in 1.7 s -> not estimated (no_preceding_rest)
    2026-03-12 9101 seq 11 PULL_UP/WIDE_GRIP_PULL_UP #6: 4 reps in 1.6 s after REST 50.0 s -> estimated work 20 s (20-20) / rest 30 s (30-30) (heart_rate, low; wrist lag 8 s from 4 sets [HR-04])
  Rest between sets (same exercise; recorded, estimated where available) [design]: median 40 s from 5 rests (1 estimated), compound unavailable (0), isolation unavailable (0), unclassified 40 s (5); excluded: not estimated 0, missing duration 0, label change or UNKNOWN 0, unchecked 1
```

- `seq N`은 canonical `sequence`(REST row도 센다). `#k`는 그 활동에서 같은 Garmin label `(category, name)`의 k번째 ACTIVE
  세트다. 예: 2026-10-21 활동의 "풀업 세트 1·2"는 `seq 1 #1`, `seq 3 #2`.
- 기록 시간은 `{:.1f} s`, 추정과 중앙값은 `{:.0f} s`. 괄호 안은 범위(낮음-높음). 값이 없는 그룹은 `unavailable`이고 0이 아니다.
- ASCII만 쓴다.

### `--json`(합성 값)

`quality_issues` 뒤에 top-level key `strength_set_timing` 하나만 붙는다. 앞의 key는 byte 단위로 같다.
`json.dumps(..., indent=2, ensure_ascii=True)`, key 순서 고정, 사람이 만든 payload(`dataclasses.asdict`를 쓰지 않아 심박
sample이 새어 나가지 않는다).

```json
  "strength_set_timing": {
    "set_timing_version": 1,
    "display_only": true,
    "rules": {"min_seconds_per_rep": 1.0, "min_heart_rate_rise_bpm": 10, "max_heart_rate_gap_seconds": 10.0,
              "wrist_lag_bounds_seconds": [0.0, 43.0], "min_lag_calibration_sets": 3,
              "medium_confidence_min_calibration_sets": 5, "medium_confidence_max_lag_spread_seconds": 10.0},
    "evidence": {"min_seconds_per_rep": ["design"], "min_heart_rate_rise_bpm": ["HR-01", "design"],
                 "max_heart_rate_gap_seconds": ["design"], "wrist_lag_bounds_seconds": ["HR-03", "design"],
                 "lag_calibration": ["HR-04", "design"], "confidence": ["HR-02", "design"],
                 "rest_groups": ["REST-07", "design"]},
    "active_set_count": 7, "checked_set_count": 6, "unchecked_set_count": 1,
    "suspect_set_count": 2, "estimated_set_count": 1, "not_estimated_set_count": 1,
    "sessions": [{"source_activity_id": "9101", "local_date": "2026-03-12", "suspect_set_sequences": [1, 11],
                  "heart_rate": {"status": "available", "artifact_relative_path": "raw/garmin/activities/9101/details.json", "sample_count": 483},
                  "lag": {"status": "calibrated", "median_seconds": 8.0, "min_seconds": 8.0, "max_seconds": 8.0,
                          "calibration_set_sequences": [3, 5, 7, 9]}}],
    "suspect_sets": [{"source_activity_id": "9101", "local_date": "2026-03-12", "sequence": 11,
                      "exercise_category": "PULL_UP", "exercise_name": "WIDE_GRIP_PULL_UP", "label_set_number": 6,
                      "reps": 4, "recorded_seconds": 1.629, "preceding_rest_sequence": 10, "recorded_rest_seconds": 50.0,
                      "method": "heart_rate", "not_estimated_reason": null,
                      "heart_rate_onset_at_utc": "2026-03-12T01:04:40.000+00:00",
                      "estimated_start_at_utc": "2026-03-12T01:04:32.000+00:00",
                      "estimated_work_seconds": 20.0, "estimated_work_range_seconds": [20.0, 20.0],
                      "estimated_rest_seconds": 30.0, "estimated_rest_range_seconds": [30.0, 30.0], "confidence": "low"}],
    "rest_between_sets": {"overall": {"median_seconds": 40.0, "rest_count": 5, "estimated_rest_count": 1},
                          "compound": {"median_seconds": null, "rest_count": 0, "estimated_rest_count": 0}, "...": "...",
                          "excluded_not_estimated": 0, "excluded_missing_duration": 0,
                          "excluded_label_change_or_unknown": 0, "excluded_unchecked": 1}
  }
```

- 추정하지 않은 세트: `method: "none"`, `not_estimated_reason`에 이유, 모든 `estimated_*`,
  `heart_rate_onset_at_utc`, `confidence`가 `null`.
- `sessions`에는 의심 세트가 있는 활동만 들어간다. `heart_rate`가 `null`이면 그 활동의 의심 세트 중 앞이 REST인 것이 없어
  심박을 읽지 않은 것이다. `lag`가 `null`이면 심박이 없거나(상태 참고) 세트 시계가 심박과 맞지 않는 것이다.
- 시각은 UTC, millisecond 고정 형식(`YYYY-MM-DDTHH:MM:SS.mmm+00:00`).

## 구조

| 계층 | 파일 | 역할 |
| --- | --- | --- |
| domain | `src/muscle50/domain/strength_set_timing.py` | 상수(근거 주석), 순수 함수 `parse_direct_heart_rate`, `is_suspect`, `find_rise_onset`, `calibrate_lag`, `estimate_session`, `summarize_set_timing`. I/O·시계 없음, 모든 계산은 정수 ms |
| application | `src/muscle50/application/strength_set_timing.py` | `BuildSnapshotWithSetTiming`: window 검증 → reader 한 번 → 기존 snapshot(`snapshot_from_data`) → 필요한 활동만 심박 읽기 → 요약 |
| infrastructure | `src/muscle50/infrastructure/sqlite/analytics_reader.py` | `details_artifact(id)`: 받아들인 capture의 `details` artifact |
| infrastructure | `src/muscle50/infrastructure/heart_rate_raw.py` | `RawHeartRateSource`: 경로 확인, 크기·sha256 확인, JSON 파싱. 쓰기·mkdir 없음, RAW 문제는 상태로 돌려줌 |
| presentation | `src/muscle50/presentation/set_timing_terminal.py` | `set_timing_lines`, `set_timing_payload` |
| CLI | `muscle50 analytics snapshot` | 위를 연결. parser 변경 없음, `ensure_directories()`/`migrate()`/Garmin 없음 |

`BuildTrainingSnapshot`과 `build_training_snapshot`은 그대로다(`recommend`의 수영 계획이 쓰는 경로).

## 규칙

1. **확인 대상**: ACTIVE 세트 중 `reps ≥ 1`이고 `duration_seconds`가 있는 것만 확인한다. 나머지 ACTIVE는 "unchecked"로
   따로 센다(정상으로 치지 않는다). REST는 확인하지 않는다. `duration_ms = round(duration_seconds × 1000)`.
2. **의심 세트**: `duration_ms < reps × 1000`(정수 비교). 정확히 1.0 s/rep는 의심이 아니다.
3. **시간축**: 세트 `started_at`(Garmin `startTime`, 1초 해상도)은 naive면 UTC로 읽는다(zoneinfo 없음). 의심 세트 A와 바로
   앞 REST R에 대해 `r0 = R 시작`, `r1 = A 시작`(늦게 누른 시점), `a_end = A 시작 + A 기록 시간`. 바로 앞 row가 REST가
   아니면(활동 첫 row 포함) `no_preceding_rest`.
4. **심박 series**: `metricDescriptors`에서 `directTimestamp`와 `directHeartRate`의 `metricsIndex`를 **key로** 찾는다(Garmin이
   호출마다 열 순서를 바꾼다). null·bool·숫자 아닌 칸은 건너뛴다(0으로 채우지 않음). 같은 timestamp에 다른 값이 있으면
   series 전체를 `raw_unreadable`로 둔다. 의심 세트 중 앞이 REST인 것이 있는 활동만 읽는다.
5. **시계 확인**: 활동의 첫 세트 시작이 `[첫 sample − 10 s, 마지막 sample + 10 s]` 안에 있어야 한다. 아니면 그 활동의 모든
   의심 세트가 `clock_unverified`(시간대 오독 방지, 새 상수 없음).
6. **상승 시작점** `find_rise_onset(search_start, search_end, rise_end)`:
   - `[search_start, rise_end]`를 sample이 덮어야 한다: 첫 sample ≤ 시작 + 10 s, 마지막 sample ≥ 끝 − 10 s, 이웃 sample
     간격 ≤ 10 s. 아니면 `heart_rate_gap`.
   - 최저점 = `[search_start, search_end]` 안의 최솟값, 같으면 **가장 늦은** sample.
   - 최저점이 검색 구간의 첫 sample이면 `rise_unclear`(이미 오르던 심박, 예: 앞 세트의 여파, HR-05).
   - 최저점 뒤 `rise_end`까지 최고값 − 최저값 < 10 bpm이면 `rise_unclear`.
7. **손목 지연 보정(활동별, `--days`와 무관)**: REST 바로 뒤의 확인된 정상(의심 아님) ACTIVE 세트 N마다
   `find_rise_onset(N 시작, min(N 시작 + 43 s, N 끝), N 끝 + 43 s)`로 `lag = 최저점 − N 시작`을 잰다(0 < lag ≤ 43 s). 3개
   미만이면 `lag_uncalibrated`. 아니면 `L = median_low(lags)`(정수 ms), 범위 `[min, max]`.
8. **추정**: `find_rise_onset(r0 + L, r1 + L, a_end + L)`의 최저점에서 `L`을 빼 추정 시작으로 한다. 구성상 `[r0, r1]` 안에
   있다(점 추정은 clamp하지 않는다). 추정 운동 = `r1 − 추정 시작`(REST 구간 이하), 추정 휴식 = `추정 시작 − r0`(0 이상).
   범위는 `[최저점 − L_max, 최저점 − L_min]`이고 양 끝만 `[r0, r1]`로 자른다. 기록된 ACTIVE 시간은 그대로 보여 주고
   운동 시간에 더하지 않는다(운동은 버튼을 누른 `r1`에 끝났다). `startTime`이 1초 해상도라 운동 + 휴식은 기록된 REST
   길이와 ±1 s 다를 수 있다.
9. **신뢰도**: 보정 세트 ≥ 5개이고 `L_max − L_min ≤ 10 s`이면 `medium`, 아니면 `low`. `high`는 없다(HR-02).
10. **세트 사이 휴식**: 같은 **알려진** Garmin label `(category, name)`의 두 ACTIVE 세트 사이 REST만 센다. 값은 뒤 세트가
    추정됐으면 추정 휴식, 뒤 세트가 확인된 정상 세트면 기록된 REST 길이. 제외하고 세는 것: label이 바뀜 또는 UNKNOWN,
    뒤 세트가 unchecked, 뒤 세트가 의심인데 추정 안 됨, REST 길이 없음(이 순서로 판단). 중앙값은 전체와 그룹별:
    compound(`movement_pattern`이 `COMPOUND_PATTERNS`), isolation(그 밖의 매핑된 pattern), unclassified(taxonomy rule 없는
    label). 빈 그룹은 `unavailable`/`null`이다.
11. window에 의심 세트가 없으면 요약 자체가 없다(text 줄도 JSON key도 없음).

### 추정하지 않는 이유(이 순서로, 처음 해당하는 하나)

| 이유 | 뜻 |
| --- | --- |
| `no_preceding_rest` | 바로 앞 row가 REST가 아니다(활동 첫 row 포함). 첫 세트의 운동은 기록 시작 전에 일어났다 |
| `set_time_missing` | 의심 세트나 앞 REST의 시작 시각을 읽을 수 없다 |
| `heart_rate_raw_missing` | `details` artifact 또는 파일이 없다 |
| `heart_rate_raw_unreadable` | 경로가 활동 디렉터리 밖, 크기·sha256 불일치, JSON 오류, 구조 오류, 충돌하는 중복 timestamp |
| `heart_rate_not_in_raw` | `directTimestamp`/`directHeartRate` descriptor가 없거나 쓸 수 있는 sample이 없다 |
| `clock_unverified` | 세트 시계가 심박 series 구간과 맞지 않는다 |
| `lag_uncalibrated` | 지연을 잴 수 있는 정상 세트가 3개 미만이다 |
| `heart_rate_gap` | 필요한 구간에 10 s 넘는 공백이 있다 |
| `rise_unclear` | 최저점이 검색 구간 처음이거나 상승이 10 bpm 미만이다 |

## 상수와 근거

코드 상수 주석에도 같게 적었다(`src/muscle50/domain/strength_set_timing.py`). 모두 표시 전용이다.

| 상수 | 값 | 근거 | 역할 |
| --- | --- | --- | --- |
| `MIN_MILLISECONDS_PER_REP` | 1000 (1.0 s/rep) | `[design]`, 근거 없음. 근거 문서에 tempo·반복 시간 수치가 없다. **반복 시간에 관한 1차 문헌 조사 뒤 다시 본다** | 의심 세트 분류 |
| `MIN_HEART_RATE_RISE_BPM` | 10 | 형태(직전 최저점 대비 상대 상승, 손목 PPG가 저항 운동에서 과소 측정하므로 작게)는 HR-01, 숫자는 `[design]` | "상승 분명" 판단 |
| `MAX_HEART_RATE_GAP_MILLISECONDS` | 10 000 | `[design]`, 근거 없음. 실데이터는 5-7 s 공백이 흔하고 최대 약 12 s | 공백이 길면 추정 안 함 |
| `MAX_WRIST_LAG_MILLISECONDS` | 43 000 | HR-03: PPG-ECG 어긋남 0-43 s의 상한(Bent 2020, 근력 운동 측정 아님, 고정 아님). 보정 지연의 경계로 쓰는 것은 `[design]` | 보정 경계 (0, 43 s] |
| `MIN_LAG_CALIBRATION_SETS` | 3 | 방법은 HR-04(근거 문서의 설계 제안), 숫자는 `[design]` | 미만이면 `lag_uncalibrated` |
| `MEDIUM_CONFIDENCE_MIN_CALIBRATION_SETS` | 5 | `[design]`, 근거 없음 | 신뢰도 |
| `MEDIUM_CONFIDENCE_MAX_LAG_SPREAD_MILLISECONDS` | 10 000 | `[design]`, 근거 없음 | 신뢰도 |
| `high` 없음 | — | HR-02: Garmin 손목 심박의 근력 운동 MAPE 약 28-82 %. 신뢰도 단계와 "추정 안 함" 경로 필요 | 최고 `medium` |
| compound/isolation | `COMPOUND_PATTERNS` | REST-07(다관절 vs 보조 종목 휴식), movement pattern으로 나누는 것은 `[design]` | 휴식 그룹 |

JSON `evidence`: `min_seconds_per_rep ["design"]`, `min_heart_rate_rise_bpm ["HR-01", "design"]`,
`max_heart_rate_gap_seconds ["design"]`, `wrist_lag_bounds_seconds ["HR-03", "design"]`, `lag_calibration ["HR-04", "design"]`,
`confidence ["HR-02", "design"]`, `rest_groups ["REST-07", "design"]`.

## RAW 선택(D9)

- `SqliteAnalyticsReader.details_artifact(id)`: 현재 refresh capture(`activity_refresh_state` →
  `activity_raw_capture_artifacts`, kind `details`)가 있으면 그것, 없으면 처음 저장된 `raw_artifacts` row(kind `details`,
  `ORDER BY id LIMIT 1`). migration 001, 006의 table만 쓰므로 `MINIMUM_SCHEMA_VERSION = 7` 그대로 오래된 DB도 읽는다.
- `RawHeartRateSource`: `relative_path`를 data root 아래로 풀고, 결과가 `raw/garmin/activities/<id>/` 안(refresh snapshot
  포함)이어야 한다. 기록된 크기와 sha256을 확인한다. FIT(`original.zip`)는 읽지 않는다.
- DB 오류(`AnalyticsDatabaseError`)만 전파된다(exit 1, 기존과 같음). RAW 문제는 상태라 snapshot은 exit 0이다.

## 바뀌지 않는 출력

- `analytics snapshot` text와 `--json`: window에 의심 세트가 없으면 byte 단위로 같다(기존 analytics 테스트 DB와
  `tests/fixtures/inbody_trend_golden/analytics_snapshot_2026-03-16.json` 포함. 그 세트는 30 s에 10회라 RAW도 읽지 않는다).
- 의심 세트가 있으면 text는 Strength 절 안에 줄이 더해지고, JSON은 끝에 key 하나만 더해진다(앞의 key는 같음).
- 항상 같음: `recommend`(text/JSON, golden 전부), `daily`, `garmin *`, `goal *`, `inbody *`, 모든 `nutrition` 명령, Telegram 응답,
  기존 `analytics snapshot` 거절(잘못된 날짜, `--days`, DB 없음).

## AC7 확인 절차(실데이터, 읽기 전용 임시 복사본)

운영 데이터(`%LOCALAPPDATA%\muscle50`)에 쓰거나 지우지 않는다. 결과는 상태만 보고하고 심박이나 추정 값은 적지 않는다.

1. `$H = "$env:TEMP\muscle50-strength-set-timing-ac7"`.
2. DB를 일관되게 복사한다: Python으로 `file:<운영>\db\muscle50.sqlite3?mode=ro`를 열고 `Connection.backup()`으로
   `$H\db\muscle50.sqlite3`에 쓴다(Telegram bot이 쓰고 있어도 일관됨). WAL reader가 운영 DB 옆에 빈 `-wal`/`-shm`을 남길 수
   있다(기록된, 받아들인 reader 동작).
3. `raw\garmin\activities\24797858737\`만 `$H\raw\garmin\activities\24797858737\`로 복사한다.
4. feature worktree에서 `MUSCLE50_HOME=$H`로 `analytics snapshot --date 2026-10-21 --days 1`과 `--json`을 실행한다. 출력은
   임시 파일로 보내고(Recovery 절에 건강 값이 있다), 작은 filter로 그 활동의 seq, label, reps/기록 시간, 의심 여부, method,
   이유만 본다.
5. 기대: seq 1 의심 + `no_preceding_rest`, seq 3 의심, seq 5 의심 아님.
6. `$H`를 지운다.

합성 테스트 `tests/test_strength_set_timing.py::test_ac7_shape_marks_both_short_pull_up_sets_and_not_the_normal_one`이 같은
모양을 고정한다. 운영에서 뽑은 fixture는 커밋하지 않는다(심박은 건강 데이터).

## Known issues / limitations

- **손목 심박은 근력 운동에서 부정확하고 늦다**(HR-01, HR-02). 추정은 범위와 신뢰도(최고 medium)로만 보여 주고 어떤 규칙도
  쓰지 않는다.
- **1.0 s/rep 기준은 `[design]`이다.** 반복 시간에 관한 1차 문헌 조사 뒤 다시 본다(빠른 반복의 오탐 가능).
- **보정은 일부 순환적이다.** "정상" 세트는 `[design]` 기준으로 정한다. 정상처럼 보이지만 늦게 누른 세트가 섞이면 지연이
  커진다. median이 줄이고 범위가 드러낸다.
- **세트보다 긴 지연은 잴 수 없다.** 보정 검색 구간이 `min(시작 + 43 s, 세트 끝)`이라 세트가 지연보다 짧으면 지연이 세트
  길이로 짧게 잡힌다.
- **다른 버튼 패턴은 다루지 않는다(D2).** 시작에서 두 번 누르면 운동은 **뒤** REST에 있다. v1은 앞 REST만 본다.
- **활동 첫 세트는 추정할 수 없다**(`no_preceding_rest`). 그 운동은 기록 시작 전에 일어났다.
- **시간 해상도**: `startTime`이 1초 단위라 지연 범위 위에 ±1 s가 더해진다.
- **sampling**: Garmin smart recording은 5-7 s 공백을 남기고, 긴 세션은 `get_activity_details`의 `maxChartSize=2000` 때문에
  down-sampling될 수 있다. `heart_rate_gap`이 많을 수 있다.
- **휴식 중 다른 심박 상승**(걷기, 기구 준비)은 운동으로 보일 수 있어 추정 운동이 길어질 수 있다.
- **이후 규칙에 쓰려면**: REST-01 메모대로 휴식 조언은 "보정된 휴식"으로만 판단해야 하지만, 이 값은 `[design]` 상수에 기대므로
  규칙이 쓰기 전에 근거를 먼저 확인하거나, 기록된 휴식만 쓰거나, 세트별 `method`/`confidence`로 걸러야 한다.
- **UTC 정렬**은 실제 활동 하나에서만 확인했다. 나머지는 시계 확인(규칙 5)이 지킨다.
- **성능**: `--days 90`이면 의심 세트가 있는 활동의 `details.json`을 수십 개 읽을 수 있다.
- **두 번 읽기**: DB는 snapshot 한 번, `details_artifact`를 활동마다 한 번 읽는다(각각 read-only transaction). 하나의 DB
  snapshot은 아니지만 한 사용자에게는 무해하다.
