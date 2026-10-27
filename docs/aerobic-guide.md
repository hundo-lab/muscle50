# Aerobic Guide v1

스펙: `docs/specs/aerobic-guide.md`. 근거 ID: `docs/evidence/training-nutrition-evidence.md` 6절(PRO-04), 8.1절(EXL-03),
11절(CONC-04), 13-16절(PLAT, FATEX, CARD, RUNPROG; 2026-10-27 사용자 승인). 설계 결정 D1-D9: 2026-10-27 사용자 승인(모두 추천안).
목표 모드(`docs/training-goal-mode.md`) 위에 얹힌 표시 기능이다.

## 목적과 non-goal

- 목표 파일이 있을 때 `recommend`/`daily`의 goal 절 끝에 세 가지를 보여 준다.
  1. 지난 7일 유산소 분(중강도·고강도)과 지침 기준선 150/300분.
  2. 러닝 한 번이 그 전 30일 최장 러닝보다 10% 넘게 길면 알림(관찰 연구의 연관, 경고 아님).
  3. cut에서 사용자가 `--plateau-weeks`를 정했으면 감량 정체 확인. 정체면 순위 없는 네 선택지와 근거 ID, 숫자 제약.
- Non-goal:
  - 유산소를 처방하거나 운동 계획·진행 목표·영양 목표를 바꾸지 않는다. 모든 줄은 표시만 한다.
  - 러닝 페이스·거리 처방, 쉬운/힘든 러닝 배분 처방 없음(RUNPROG-06). ACWR 없음(RUNPROG-04). 주당 10% 규칙 없음(RUNPROG-01).
  - Garmin 동기화는 바뀌지 않는다(저장된 활동과 load metric만 읽는다). Migration 없음. LLM 없음.
  - 목표 파일이 없으면 아무것도 더하지 않는다(D1). 목표 없음 = byte-identical.

## 명령

```powershell
muscle50 goal set --mode cut --target-body-fat 18 --by 2027-02-28 --min-smm 41 --weekly-loss 0.3 0.5 --plateau-weeks 3
muscle50 goal show [--json]
muscle50 recommend --date 2026-11-20 [--json]
muscle50 daily [--json]
```

- `--plateau-weeks N`(선택): cut이고 `--weekly-loss`가 있을 때만, 2-26 정수(`[design]` 타당성 범위, 근거 없음). 기준 속도는
  `--weekly-loss`의 MIN이다(따로 정하는 flag 없음).
- 거절(exit 1, 파일은 그대로이고 없으면 계속 없다, 값은 출력하지 않는다):
  - `오류: --plateau-weeks는 --mode cut과 --weekly-loss가 있어야 합니다. 아무것도 바꾸지 않았습니다.`
  - `오류: --plateau-weeks는 2~26 사이의 정수여야 합니다. 아무것도 바꾸지 않았습니다.`
  - 정수가 아니면(`--plateau-weeks x`) argparse exit 2.
- `goal set`은 지금처럼 문서 전체를 바꾼다(training-goal-mode D7). `--plateau-weeks` 없이 다시 `goal set`하면 설정이 지워진다.

### `goal show`(cut, 설정 있음)

`weekly loss target` 줄 뒤에 한 줄이 붙는다.

```text
  plateau check: 3 weeks below 0.3 %/week loss, at least 2 InBody intervals (user setting [design]; no evidence-based definition [PLAT-01])
```

`--json`은 `weekly_loss_percent` 뒤에 `"plateau_weeks": 3`이 붙는다(설정했을 때만; `goal_version`은 1 그대로).

### 목표 파일 schema 2

`--plateau-weeks`를 줬을 때만 schema 2로 쓴다. 설정이 없는 목표는 지금의 schema 1 그대로(byte 단위로 같다).

```json
{
  "schema_version": 2,
  "goal": {
    "mode": "cut",
    "target_body_fat_percent": "18",
    "target_weight_kg": null,
    "target_date": "2027-02-28",
    "min_skeletal_muscle_mass_kg": "41",
    "weekly_loss_percent": {"minimum": "0.3", "maximum": "0.5"},
    "plateau_weeks": 3
  }
}
```

읽기는 schema마다 정확한 key 집합이다. schema 1에 `plateau_weeks`가 있거나 schema 2에 없으면 `goal must list exactly ...`,
schema 2의 값이 null/bool/문자열/소수/범위 밖이거나 cut + `weekly_loss_percent`가 아니면 `(plateau_weeks)`로 거절한다(값은
출력하지 않음). schema 3 이상은 `(schema_version)`. 수면 설정 파일은 schema 1만 읽는다.

### `recommend` / `daily`의 goal 절 끝(합성 값, cut, 정체 조건 충족)

수면 두 줄 뒤에 붙는다.

```text
  Aerobic minutes 2026-11-13..2026-11-19 (running, swimming): moderate 140 + vigorous 60 = 200 min [EXL-03; design: Garmin intensity minutes, vigorous not doubled]
    reference marks: 150 min/week, the guideline minimum (or 75 vigorous) [EXL-03]; 300 min/week, the end of the studied range [FATEX-02]
    lower bound: 1 activity without intensity minutes not counted (duration 45 min, intensity unknown) [design]
  Run length vs the longest run in the 30 days before it, 2026-11-13..2026-11-20 [RUNPROG-03: observational link with overuse injury; notice only]:
    2026-11-19 30001: 12.5 km, 25.0 % longer than 10 km (2026-11-02)
  Plateau check [design: user setting, 3 weeks below 0.3 %/week loss, >= 2 InBody intervals]: met
    InBody 2026-10-23 -> 2026-11-06 -> 2026-11-20 (28 d): -0.11, -0.05 %/week [PLAT-01, PLAT-02]
    note: weight moves about 0.35 % within a week [PLAT-02]; your target is 0.3-0.5 %/week (user setting); compare same-device, same-condition InBody only [PLAT-02]
    options, no ranking (fixed display order) [PLAT-06]; your preference and what you can keep up are valid reasons to choose [FATEX-07]:
      a) check that meals are logged completely (missed meals, general-meal estimates, weekends) [PLAT-04]
      b) eat 100-150 kcal/day less; keep the deficit at or under about 500 kcal/day (muscle50 cannot measure it) [design: goals.md step; PRO-04]
      c) keep intake, add activity: the same deficit gave the same fat loss, but extra eating can offset part of it [FATEX-05, FATEX-04]; watch run length and the 3 h run/legs gap [RUNPROG-03, CONC-04]
      d) one maintenance week: weight may rise from glycogen and water, and the deadline moves by a week [PLAT-05]
```

다른 상태:

- 하한 줄은 필요할 때만 나온다. 두 metric 중 하나만 있는 활동은
  `lower bound: 1 activity has only one of moderate and vigorous stored [design]`(저장된 쪽은 더한다). 어느 활동도 한 쪽 metric을
  저장하지 않았으면 그 칸은 0이 아니라 unknown이다(예: `moderate unknown + vigorous 5 = 5 min`, JSON은 null).
- 센 활동이 없으면 `...: none stored (may be unsynced, not a confirmed rest week) [EXL-03; design]`(0분이 아니다). 모든 활동에
  intensity minutes가 없으면 `...: unknown (no counted activity has intensity minutes) [EXL-03; design]`과 시간 줄.
- 러닝 알림이 없으면 `    none more than 10 % longer (2 runs compared; 1 skipped: no earlier run with a distance in its 30 days; 1 without a distance, not judged)`
  (해당하는 부분만), 창 안에 러닝이 없으면 `    no run stored in this window`.
- 이전 러닝 중 거리 없는 것이 있으면 `... 25.0 % longer than 10 km (2026-11-02; 1 earlier run had no distance, so the longest may be longer)`.
- 정체 `not met`: header와 InBody 구간 줄만. `insufficient`: `...: insufficient InBody data (2 weights cover 1 interval; the check needs 3 weeks and at least 2 intervals [PLAT-02])`.
  InBody를 읽을 수 없으면 `...: unknown (InBody data unavailable: ...)`이고 exit 0.
- cut인데 설정이 없으면 `  Plateau check: not set (goal set ... --plateau-weeks N; there is no evidence-based plateau definition) [design; PLAT-01]`.
- gain/maintain은 정체 줄이 없다(유산소 분과 러닝 알림은 나온다).

### `--json`

`goal_mode`의 `sleep` 뒤에 세 key가 붙는다. `goal_mode_version`과 `recommendation_version`은 1 그대로다(영양·목표 모드 통합과
같은 선례). `daily --json`의 `recommendation`은 이 문서 그대로다.

- `aerobic_minutes`: `from`, `to`, `activity_types`, `status`(`known`/`lower_bound`/`unknown`/`none_stored`), `moderate_minutes`,
  `vigorous_minutes`, `total_minutes`(모르면 null), `vigorous_counted_as: "minutes"`, `activities[]{source_activity_id, date, type,
  moderate_minutes, vigorous_minutes, duration_minutes}`, `without_intensity_minutes{activity_count, duration_minutes,
  without_duration, one_metric_only_count}`, `reference_minutes_per_week[]{minutes, meaning(guideline_minimum/end_of_studied_range),
  evidence}`, `evidence`.
- `run_length`: `from`, `to`, `previous_days: 30`, `threshold_percent: 10`, `basis: "distance"`, `notice_only: true`, `evidence`,
  `runs[]{source_activity_id, date, distance_meters, longest_previous_meters, longest_previous_activity_id, longest_previous_date,
  previous_without_distance, baseline_lower_bound, increase_percent(문자열, 0.1 HALF_EVEN), status}`.
  `status`는 `longer_than_threshold`/`within`/`no_previous_run`/`no_distance`.
- `plateau`: gain/maintain이면 null. 아니면 `status`(`met`/`not_met`/`insufficient_measurements`/`unknown`/`not_set`), `weeks`,
  `below_loss_percent_per_week`, `source`, `min_intervals: 2`, `intervals[]`(최신 먼저, `{from_date, to_date, days,
  percent_per_week}`), `span_days`, `latest_measurement_date`, `days_since_latest_measurement`, `reason`, `evidence`,
  `noise{within_week_weight_percent: "0.35", evidence}`, `options_ranked: false`, `choice_evidence: ["PLAT-06", "FATEX-07"]`,
  `options[]`(`met`일 때만): `check_meal_logging`, `eat_less`(`step_kcal_per_day{minimum 100, maximum 150}`, `step_source:
  "docs/goals.md"`, `deficit_limit_kcal_per_day: 500`, `deficit_measurable: false`), `keep_intake_add_activity`
  (`run_length_threshold_percent: 10`, `run_legs_gap_hours: 3`), `maintenance_week`(`weeks: 1`). 선택지마다 `evidence`.
- `--plateau-weeks`가 있으면 `goal_mode.goal`에도 `plateau_weeks`가 붙는다(`source`, `evidence` 앞).

## 규칙과 근거

| 규칙 | 숫자 | 근거 | 성격 |
| --- | --- | --- | --- |
| 유산소 분 창: D-7..D-1(주당 set 창과 같음) | 7일 | design(근거 없음) | 표시 |
| 세는 종류: running, swimming(walking, cycling, strength, other 제외) | — | design, EXL-03/FATEX-01 적용 메모("달리기+수영") | 표시 |
| 합계 = 저장된 Garmin moderate + vigorous intensity minutes, vigorous는 두 배로 세지 않음 | — | design(D6); 기준선 문구에 EXL-03의 "75 vigorous" | 표시 |
| 기준선 150분/주 = 지침 최소 | 150 | EXL-03 | 기준선(목표 아님) |
| 기준선 300분/주 = 연구된 범위의 끝 | 300 | FATEX-02 | 기준선(연구된 범위의 끝) |
| intensity minutes 없는 활동: 합계에 넣지 않고 시간(moving, 없으면 elapsed)을 따로 표시, 합계는 하한 | — | design(D5) | 표시 |
| 러닝 알림: 한 번의 거리 > 그 날짜 전 30일 최장 거리 × 1.1 | 30일, 10% | RUNPROG-03 | 알림만(관찰 연관) |
| 알림 대상 창: D-7..D 날짜의 러닝 | 7일 | design | 표시 |
| 같은 날 다른 러닝은 기준에 넣지 않음; 거리 0 이하는 "거리 없음" | — | design | 표시 |
| 정체 기준 주 수 | 사용자 값 2-26 | design: user setting(PLAT-01: 근거 기반 정의 없음) | 사용자 설정 |
| 정체 = N주를 덮는 InBody 구간 ≥ 2개가 모두 MIN보다 적게 감량 | 2개 | PLAT-02(한 번 측정·한 구간으로 판단하지 않음) + design | 표시 |
| 구간 짝짓기: 최근 체중 vs 7일 이상 앞선 마지막 체중(목표 모드 체중 변화와 같음) | 7일 | design | 표시 |
| 측정 잡음 문구: 주중 체중 변동 0.35%와 사용자 목표 속도를 나란히 적기만 하고 둘을 비교하지 않음 | 0.35% | PLAT-02 | 문구 |
| (가) 기록 확인 | — | PLAT-04 | 선택지 |
| (나) 하루 100-150 kcal 덜 먹기, 결손 약 500 kcal 이하 | 100-150, 500 | design(goals.md 조정 폭) + PRO-04 | 선택지 |
| (다) 섭취 유지 + 활동 추가(같은 결손이면 같은 지방 감소, 보상 섭취 가능), 러닝 길이·러닝/하체 3 h 간격 | 10%, 3 h | FATEX-05, FATEX-04, RUNPROG-03, CONC-04 | 선택지 |
| (라) 1주 유지 휴식 | 1주 | PLAT-05 | 선택지 |
| 선택지 순서는 고정 표시 순서이며 순위가 아님; 선호와 지속 가능성은 고르는 정당한 기준 | — | PLAT-06, FATEX-07 | 문구 |

- `[design]` 상수(창 길이, 2-26 범위, D-7..D 알림 창, 같은 날 제외, 거리 0 처리)는 근거 ID가 없다. 코드 상수 주석에도 같게 적었다
  (`src/muscle50/domain/aerobic_guide.py`).
- **RUNPROG-03은 관찰 연구의 연관**이다(Frandsen 2025, 5,205명). 급증을 10% 안으로 줄이면 부상이 준다는 개입 연구는 없다. 그래서
  경고나 차단이 아니라 알림이고, 문구에 "observational link"와 "notice only"를 적는다.
- **150/300 문구**(FATEX-02 메모, 사용자 지적): 150 이후 효과가 멈춘다거나 300이 상한이라고 쓰지 않는다. 줄에는 "stop",
  "ceiling", "limit", "upper", "max"가 없다(테스트로 고정).
- **선택지는 대등하다**(PLAT-06, FATEX-05): 활동을 늘리는 쪽을 더 약한 선택지로 쓰지 않는다. 먹고 싶은 것을 먹으면서 활동으로
  결손을 만드는 것도 정당한 선택지다(FATEX-07, 사용자 의견 2026-10-27). 다만 보상 섭취가 일부를 상쇄할 수 있다는 사실(FATEX-04)은
  함께 적는다.
- 비교는 반올림 전 값: 러닝은 저장된 거리의 decimal repr로 `거리 × 10 > 최장 × 11`(정확히 110%는 알림 없음), 정체는 반올림 전
  Decimal 비율로 `-비율 < MIN`(정확히 MIN이면 정체 아님, 체중 증가는 MIN보다 적은 감량으로 센다). 표시는 km 0.01, % 0.1,
  %/주 0.01(HALF_EVEN).
- 모르는 값은 0이 아니다: intensity minutes가 없는 활동은 unknown이고 합계는 하한이다. 저장된 0은 진짜 0이다. 센 활동이
  없으면 "none stored"(동기화되지 않았을 수 있음). 거리가 없는 러닝은 판단하지 않는다. InBody 구간이 모자라면 "insufficient"이고
  "정체 아님"이 아니다.
- **D1(측정 kg 없음)**: 체중 값은 비율 계산에만 쓰고 출력하지 않는다. 러닝 거리는 체성분이 아니다.
- 읽기 전용: `recommend`는 목표가 있을 때만 활동을 한 번 더 읽는다(D-37..D, 각 러닝의 30일 기준). 계획 입력(D-28..D)을 읽는
  기존 호출은 그대로다.

## FATEX-04: 운동 칼로리는 섭취 목표에 더하지 않는다(확인, 코드 변경 없음)

- Garmin 활동의 `calories_kcal`을 읽는 출력은 단일 활동 표시(`src/muscle50/presentation/terminal.py:81-82`, `칼로리: ... kcal`)뿐이다.
- `ShowDailyNutritionStatus`는 끼니와 목표 파일만 읽는다. `BuildNutritionContext`(`application/nutrition_recommendation.py`)와
  `domain/nutrition_guidance.py`는 활동이나 운동 kcal을 읽지 않는다.
- 회귀 테스트(`tests/test_recommend_aerobic_guide.py::test_exercise_calories_are_never_added_to_intake_targets`): 목표와 cut 목표를
  정한 뒤 그날 900 kcal 러닝이 있든 없든 `nutrition status`(text, JSON)와 `recommend --json`의 `nutrition`이 byte 단위로 같다.

## 바뀌지 않는 출력

- 목표 파일이 없을 때의 모든 출력(`recommend`, `daily`, text/JSON, golden 6개, Telegram 요약).
- `analytics snapshot`, `nutrition ...`(모든 목표 모드), `inbody *`, `garmin *`, `daily --after-workout`, `settings sleep *`.
- `--plateau-weeks` 없는 목표의 `goal show/set/unset`(text, JSON)과 목표 파일.
- 목표가 있을 때 goal 절의 기존 줄과 `goal_mode`의 기존 key는 그대로이고, 새 줄과 key는 끝에만 붙는다.

## Known issues / limitations

- **근거의 대상**: 지방 감소 운동 근거는 대부분 운동하지 않던 과체중 성인에서 나왔다. 이미 주 3-5회 달리는 사람에게 효과 크기는
  알 수 없다(FATEX-02, FATEX-04).
- **정체 확인은 늦다.** InBody가 3-4주 간격이면 N과 상관없이 구간 2개(PLAT-02)가 쌓이는 6-8주 뒤에야 판단할 수 있다. 1주 유지 휴식
  (PLAT-05) 뒤에는 글리코겐·수분으로 체중이 올라 정체나 증가처럼 보일 수 있고, 이 확인은 그것을 구별하지 못한다. 같은 날 InBody
  행이 충돌하면 그 날짜는 빠진다(목표 모드와 같음).
- **intensity minutes는 activity-list summary backfill에서 온다.** backfill 전에 저장됐거나 backfill 없이 refresh된 활동은 metric이
  없어 합계가 하한이 된다. `daily`는 backfill을 실행한다.
- **vigorous는 그대로 더한다.** 지침의 "75분 고강도" 동등성은 문구로만 이름을 대고 계산하지 않는다(moderate-equivalent는 후속 후보).
- **나뉜 수영 기록은 합치지 않는다**(기존 known issue). intensity minutes는 저장된 활동마다 더한다.
- **트레드밀 거리**는 시계 추정이다. RUNPROG-03 코호트는 대부분 실외 러닝이라 트레드밀에서는 알림이 시끄러울 수 있다.
- **(가) 기록 확인의 근거 수치**(기록한 날 수, 일반식 비율)는 계산하지 않는다(후속 후보).
- **두 번 읽기**: 목표가 있으면 `recommend`가 DB를 두 번 읽는다(각각 read-only transaction). 한 사용자에게는 무해하지만 하나의
  snapshot은 아니다.
- **목표 파일 두 형태**: schema 1(설정 없음)과 schema 2(설정 있음). 이전 버전의 muscle50은 schema 2 파일을 `(schema_version)`으로
  거절한다.
- **외부 LLM 노출**: Telegram 코치는 `recommend --json`을 그대로 받으므로 새 `goal_mode` key(분, 거리, 비율, 선택지 code)도 받는다.
  측정 kg은 없다. Telegram 요약(`/today`, `/daily`)은 바뀌지 않는다.
- 후속 후보: Telegram 요약 줄(러닝 알림, 정체), 주간 러닝 증가 상한을 사용자 설정으로(RUNPROG-01), moderate-equivalent 분, 목표 없이도
  유산소 분 보이기(D1-C), 코치가 정체 선택지를 읽기, v3 에이전트 도구로 열기.
