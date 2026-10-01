# Training Recommendation v1

요청 날짜 하나에 대해 **오늘의 strength 계획**과 **다음 수영 목표**를 저장된 canonical 데이터만으로 결정적으로
계산한다. LLM, ML, 합성 readiness 점수 없음. Migration, ingestion/refresh/normalization 변경, production 쓰기 없음.

```powershell
uv run muscle50 recommend --date 2026-09-24            # text (ASCII only)
uv run muscle50 recommend --date 2026-09-24 --json     # 근거 전체 JSON
uv run muscle50 recommend --date 2026-09-24 --avoid triceps --avoid lats   # 통증 등으로 오늘 뺄 muscle group
```

## 계층

| 계층 | 파일 | 역할 |
| --- | --- | --- |
| domain | `domain/training_goals.py` | `TrainingGoals` frozen dataclass(code default, 저장 없음) |
| domain | `domain/recovery_assessment.py` | 필드별 투명 규칙 → `normal` / `hold` / `reduce` |
| domain | `domain/strength_recommendation.py` | focus 선택, 종목 선택, double progression, swim overlap, UNKNOWN 안내 |
| domain | `domain/swim_recommendation.py` | swim 분석(연속 구간, pace, 강도), 다음 수영 목표 |
| domain | `domain/training_recommendation.py` | 날짜 의미 정의, 위 모듈 조합, notice |
| application | `application/recommend_training.py` | `BuildTrainingRecommendation`: 기존 read-only reader로 한 번 읽고 domain 호출 |
| presentation | `presentation/terminal.py` | `render_training_recommendation`(ASCII, Garmin activity 이름 미출력), `_json` |
| CLI | `muscle50 recommend` | `analytics snapshot`과 동일: `ensure_directories()`/`migrate()`/Garmin 인증 없음 |

재사용한 기존 primitive: `SqliteAnalyticsReader`(`mode=ro` + `query_only`), `build_training_snapshot`의 swim
plausibility(implausible lap, summary 오염 판정), `classify_strength_set`/`classify_exercise`(taxonomy),
`label_origin`, `derive_lap_metrics`/`derive_length_metrics`, `activity_local_date`.

**Deterministic 규칙 계층과 이후 LLM/표현 계층의 경계**: 이 모듈이 모든 결정(focus, 종목, set/rep/load, 조정,
수영 목표)을 내리고 근거를 구조화해 낸다. 이후 LLM 계층이 생기더라도 이 JSON을 문장으로 바꾸는 역할만 해야 하며
결정을 바꾸거나 데이터에 없는 사실(RIR, 통증, 장비, 영법 강도)을 만들어내면 안 된다.

## 날짜 의미 (요청 날짜 D)

- 시계/zoneinfo 사용 없음. Activity 날짜는 Garmin `started_at_local`의 날짜 부분.
- Reader는 D-28 ~ D를 한 번 읽는다.
- **Strength history = D-28 ~ D-1.** D에 이미 저장된 strength activity는 history에서 빼고
  `same_day_strength_excluded` notice로 보고한다(backtest 시 이미 한 운동을 "추천"하지 않기 위해).
- **D와 D-1의 swim**은 strength overlap 입력. 다음 수영 목표는 D까지의 swim을 history로 쓴다(이미 한 수영).
- Recovery 필드별 출처는 아래 표. 가장 최근 activity가 D-2 이전이면 `activity_coverage_gap`(미동기화일 수 있음,
  휴식으로 간주하지 않음).

## Goal/Profile 모델

Goal model이 없었으므로 최소 `TrainingGoals`(code default)를 추가했다. 저장/migration 없음.

| field | 기본값 |
| --- | --- |
| strength_priority | hypertrophy |
| skeletal_muscle_mass_milestone_kg / long_term | 43 / 50 (v1 규칙에서 사용하지 않음, 기록용) |
| strength_sessions_per_week / strength_session_minutes | 5 / 40 |
| region_min/max_sessions_per_week | 1 / 2 |
| compound_rep_range / isolation_rep_range | 5-12 / 10-20 |
| reps_in_reserve_min/max | 1 / 3 (조언 문구만; 데이터에 RIR 없음) |
| swim_sessions_per_week | 3 |
| continuous_swim_baseline_meters / target | 1000 / 1500 |
| target_1500m_fastest/slowest_seconds | 24:00 / 27:30 (= 1:36-1:50/100 m) |

## Strength 규칙

### 종목 identity

- 저장된 Garmin `(category, name)` 그대로(`BENCH_PRESS/-`, `BENCH_PRESS/DUMBBELL_BENCH_PRESS`는 별개). 이름 변경·병합
  없음. Progression은 같은 label끼리만 비교한다.
- UNKNOWN과 rule 없는 label은 추천 후보가 아니며 추측하지 않는다.

### Region과 focus 선택

Region(분할을 강요하는 것이 아니라 40분 세션을 묶는 단위): `legs`(quadriceps, hamstrings, glutes),
`pull`(lats, upper_back, posterior_deltoid, biceps, forearms), `push`(chest, anterior/lateral_deltoid, triceps).
Core는 focus 대상이 아님. Region별로 strength set만으로(수영은 절대 포함하지 않음) 다음을 계산한다:
7일/28일 primary-muscle set, 의미 있는 session(하루 ≥ 3 primary set), 마지막 session일, 어제 set,
muscle별 상세(`muscle_detail`: 7일/28일 set, 마지막 날짜), 그리고

- **personal interval** = 28 / 28일 session 수, 2일(약 48h)~7일(주 1회 goal)로 clamp
- **due** = 마지막 session 후 경과일 / personal interval (≥ 1이면 평소 주기에 도달/초과)
- **neglected** = 7일 이상 strength session 없음(주 1회 goal floor)

정렬 키(앞이 우선):

1. eligible: 어제 그 region primary set ≥ 6이면 제외(약 48h), `--avoid`로 region 전체가 빠지면 제외
2. neglected → 우선. 하체 보호 장치: 수영은 하체 strength를 대신하지 않는다. 선택되면 해소되므로 같은
   region을 반복해서 고르지 않는다.
3. 강한 swim overlap(아래)이면 push/pull 뒤로
4. recovery `reduce`면 최근 2일 안에 훈련한 region 뒤로(가장 회복된 region 우선)
5. due가 큰 region 우선 — 사용자 자신의 28일 패턴 기준. 어제 한 region은 due가 낮아 주간 횟수 휴리스틱만으로
   다시 뽑히지 않는다.
6. 7일 set / 자기 28일 주평균(낮을수록 우선) — 보편 "최적 set 수" 없음
7. 고정 순서 legs, pull, push

주 1-2회 goal은 계획 제약으로만 쓴다: 주 1회는 neglected floor와 interval 상한(7일), 주 2회 상한 같은
"7일 session 수" 규칙은 두지 않는다(v1 초안의 이 규칙이 legs를 14일 중 10일 고르게 만들었다).
첫 번째 reason은 runner-up region을 이긴 첫 정렬 기준을 명시하고, text 출력에 region별 due/interval/flag 표를 낸다.

Focus region에 28일 내 익숙한 종목이 없으면 다음 region으로 넘어가며 이유를 남긴다. UNKNOWN set은 region에
들어가지 않으므로 set 수는 하한값이라고 출력한다.

### 종목 선택 (약 40분)

- 후보: focus region에 primary muscle이 있는 매핑된 label 중 28일 안에 한 것. `--avoid` muscle이 primary나
  secondary면 제외.
- 익숙함 순서: session 수 → set 수 → 최근 날짜 → label 문자열.
- Key 1개: 가장 익숙한 compound(pattern: horizontal/vertical push/pull, squat, hinge, lunge).
- Accessory 1-2개: 첫째는 key와 다른 movement pattern 우선, 둘째는 남은 compound 중 가장 익숙하고 28일 ≥ 2 session.
- Isolation 1개: compound가 이미 primary로 다루지 않는 muscle 우선, 그다음 익숙함.
- 기본 3 set씩. 추정 시간 = 5분 + 3분 × working set. 목표 + 5분을 넘으면 둘째 accessory를 뺀다.
- 무작위 variety 없음. 선택적 대안은 아래 조건일 때만 최대 1개.

### Progression (double progression)

같은 label의 occurrence(한 activity 안의 모든 ACTIVE set)마다:

- 비교 가능한 set: reps > 0, weight ≥ 0(음수 sentinel 제외, `-0.0`은 0으로 출력).
- **Work load** = rep range 최소값 이상을 한 set 중 최대 양수 무게(없으면 최대 무게, `below_range`).
  Work set reps = 그 무게의 모든 set reps. 양수 무게가 없으면 `load_recorded = false`(reps만).
- 마지막 occurrence 기준:

| 조건 | action | 목표 |
| --- | --- | --- |
| 비교 가능한 set 없음 | `establish_baseline` | rep range, load 없음 |
| load 미기록(0 kg/없음) | `add_reps`(또는 상한이면 `maintain`) | best + 1 rep, load target 없음 |
| work set 2개 이상이 range 상한 도달 | `increase_load` | +2.5 kg(또는 다음 가능한 단위), reps = max(하한, 상한 - 4) |
| range 하한 미달 | `add_reps` | 같은 무게로 하한 rep |
| 1 set만 상한 도달 | `add_reps` | 같은 무게로 2 set 이상 상한 |
| 그 외 | `add_reps` | 같은 무게, best + 1 rep |

- **Performance 신호**: 같은 work load였던 직전 occurrence보다 best reps가 2 이상 줄면 `maintain`(마지막 수행 반복).
  무게가 낮아진 것만으로는 regression이 아니다(같은 label 안에 다른 장비가 섞일 수 있음).
- **Recovery hold/reduce**: `increase_load`/`add_reps`를 `maintain`으로. Maintain 목표 reps는 range 상한으로 자른다.
- **Load confidence**: 28일 work load의 최대/최소 > 1.5배이거나 `PULL_UP/-`, `PUSH_UP/-`,
  `TRICEPS_EXTENSION/BENCH_DIP`(추가 중량인지 assist인지 Garmin이 구분하지 않음)이면 `low` + 사유.
  마지막 occurrence label이 자동 인식만이면 "auto-detected" caveat.
- **Stagnation**: 최근 3번이 같은 work load이고 best reps가 늘지 않음 → 같은 movement pattern(없으면 같은 primary
  muscle)의 다른 익숙한 label을 **선택적 대안**으로 1개 제시(기본 계획은 바꾸지 않음).
- 근거(`basis`)에는 마지막 session, 판단 이유, 2-4주 trend(날짜별 work load × best reps)가 들어간다.

## Recovery 조정

합성 점수 없이 필드별 규칙. 가장 강한 규칙이 level을 정한다. **값이 없으면 규칙이 발동하지 않는다**(missing ≠ poor).
Row가 없으면 level `normal` + "no recovery adjustment" 표시와 `recovery_row_missing` notice.

| field (출처 row) | hold | reduce |
| --- | --- | --- |
| `sleep_seconds` (D) | < 5 h | < 4 h |
| `sleep_score` (D) | < 50 | |
| `hrv_status` (D) | LOW, UNBALANCED, POOR | |
| `training_readiness_level` (D, Garmin `AFTER_WAKEUP_RESET` 아침 값) | LOW | POOR |
| `recovery_time_minutes` (D, 같은 아침 readiness 항목) | ≥ 720 | ≥ 1440 |
| `training_status_key` (**D-1**, 하루 끝 값) | STRAINED, OVERREACHING, UNPRODUCTIVE | |

Body battery, stress, resting HR은 사용하지 않는다(저장 값이 D의 운동 이후 상태일 수 있음).
`training_readiness_score`는 표시만 한다(level이 Garmin의 banding).

아침 readiness 확인(production, 2026-09-01~28 accepted capture 28개): 모든 날짜에 `AFTER_WAKEUP_RESET` 항목이 있다.
단 2026-09-12는 그 항목이 두 개(23:17 MODERATE/448 min, 07:15 LOW/30 min)이고 기존 normalizer가 목록의 첫 항목인
23:17 값을 저장했다 → 그 날짜의 readiness/recovery time은 하루 끝 값이다(recovery normalizer는 이 작업 범위 밖이라
수정하지 않음). 2026-09-14도 두 개(09:57, 03:06)이며 09:57 값이 저장됐다.

효과: `hold` = 증량·증rep 없음(마지막 수행 반복). `reduce` = hold + 종목당 1 set 감소(최소 2).

## Swimming ↔ strength 간섭

- D 또는 D-1 swim → overlap으로 표시(shoulders/back/triceps). 약한 overlap이면 swim 관련 muscle 종목에
  "2-3 reps short of failure" 문구.
- **강한 overlap**: HR zone 5 ≥ 120 s, 또는 anaerobic TE ≥ 2.5, 또는 plausible butterfly ≥ 200 m.
  → push/pull region 후순위, vertical push(overhead press)는 key/accessory로 선택하지 않음,
  primary anterior/lateral deltoid·lats 종목 1 set 감소.
- Lap `intensity_type`은 production에서 전부 NULL이고 paddle/fin 기록은 없다 → 사용하지 않음(발명 안 함).

## UNKNOWN strength 안내

최근 14일 strength activity에 UNKNOWN ACTIVE set이 있으면 activity별 `strength_unknown_exercise` notice:
날짜, activity ID, set sequence, "Garmin Connect에서 종목 지정 후 `muscle50 garmin refresh <id>`". 추측하지 않고,
추천은 막지 않는다. 7일/28일 UNKNOWN set 수도 함께 보고한다.

## 다음 수영 목표

### Swim 분석

- Analytics Engine의 swim 규칙을 그대로 사용: implausible lap(> 2.5 m/s 또는 duration 없음)은 쓰지 않고,
  summary가 그런 lap을 포함하면 `swim_anomaly_excluded`(2026-09-17 `24391051389` summary 3025 m, 2026-09-10
  `24302653969` 1275 m). Distance는 plausible lap detail(없으면 `summary_only`로 표시).
- **연속 구간**: plausible lap 안에서 10 s 이상 idle length(거리 0)가 끊지 않는 swimming length 묶음.
  Garmin이 idle로 기록하지 않은 짧은 벽 휴식은 알 수 없다.
- **Baseline으로 쓰는 구간**: 모든 length에 duration이 있고 속도가 plausible(≤ 2.5 m/s)한 구간만. 그렇지 않은 더 긴
  구간은 "ignored as baseline"으로 보고한다(예: 2026-07-28 1900 m lap은 50 m를 14 s에 한 length가 있어 제외).
- **Pace baseline**: freestyle만으로 된 ≥ 200 m 구간 중 가장 빠른 것(length duration 합 기준).
- 강도: 위 strength 간섭과 같은 HR zone 5 / anaerobic TE 기준, butterfly 거리는 별도 보고.

### Goal 선택 (위에서부터 처음 맞는 것)

anchor = max(설정 baseline 1000 m, 28일 최장 연속 구간). Effort = 최장 연속 구간 ≥ 0.6 × anchor.

1. Recovery `reduce`, 또는 마지막 swim이 D/D-1이고 high intensity → `recovery_technique`(600 m 쉬운 혼합/드릴, no fly/paddles)
2. 14일 안에 effort 없음 → `distance_progression`: min(1500, anchor + 100 m, 2×pool 단위) 연속
3. 마지막 swim이 effort → `pace_intervals`(pace baseline이 있을 때): 8 × 100 m freestyle, 현재 pace보다
   4 s~1 s 빠르게(목표 하한 1:36/100 m 이상), 20-30 s 휴식. pace baseline이 없으면 `easy_continuous`
4. 마지막 effort가 7일 넘음 → `distance_progression`, 아니면 `easy_continuous`(0.8 × anchor)

목표 거리가 1500 m에 닿으면 distance progression은 "1500 m timed, 24:00-27:30"이 된다.
Strength 맥락: 어제 shoulder/back/triceps primary set ≥ 8이면 intervals → easy. 오늘 focus가 push/pull이면
"no butterfly/paddles, 몇 시간 간격" caution, legs면 "kick/fins easy".

## Production read-only 검증 (2026-10-01)

Evidence(repo 밖): `C:\temp\muscle50-evidence-20261001-recommend\`(`rec_<date>.txt/json`, `_rerun.json`,
`summarize.py`, `calibration.py/txt`, `fingerprint.py`, `before.json`/`after.json`, `audit*.py/txt`).

- 14개 날짜 text/JSON exit 0, JSON 재실행 byte-identical, text 전부 ASCII.
- Fingerprint: `muscle50.sqlite3` sha256/size/mtime 동일, `-wal` 0 bytes 동일, 28 table digest 동일, RAW 868 files
  동일. `-shm` mtime만 변경(SQLite WAL reader mark).
- 규칙 발동 빈도(calibration): recovery 2026-09-01~28 → normal 18 / hold 4 / reduce 6. Swim 21개 중 high intensity
  5(07-07, 07-28, 07-30, 07-31, 08-28), butterfly ≥ 200 m 4.

Focus 선택 개선 후(최종) 결과. 이전 초안 → 최종 focus 분포: legs 10 / push 3 / pull 1 → legs 7 / pull 5 / push 2.

| date | 상황 | focus(이전 → 최종)와 결정 기준 | recovery | 다음 수영 |
| --- | --- | --- | --- | --- |
| 07-08 | 강한 swim 다음 날 | legs → legs: push resting(어제 11 set), pull swim overlap 후순위 | row 없음 | recovery 600 m |
| 07-29 | 강한 swim 다음 날 | legs → legs: push/pull 모두 어제 ≥ 9 set으로 resting | row 없음 | recovery 600 m |
| 07-31 | 같은 날 강한 swim | legs → legs: 8일간 strength session 없음(neglected) | row 없음 | recovery 600 m |
| 08-25 | recovery row 없음 | legs → legs: legs due 0.71(4일/주기 5.6일) > pull 0.46(어제 5 set), push resting | normal(no adjustment) | distance 1100 m |
| 08-29 | 강한 swim 다음 날, row 없음 | legs → legs: neglected(8일) | normal | recovery 600 m |
| 09-11 | 수영 다음 날 | legs → pull: pull due 0.43 > legs 0.29, push resting | normal | pace 8×100 @1:49-1:52 |
| 09-13 | sleep NULL | legs → pull: pull due 1.29 > push 1.07 > legs 0.57 | normal(missing 표시) | pace intervals |
| 09-17 | 같은 날 수영(11:00) 후 | push → pull: pull due 0.86 > push 0.71; legs resting | normal | easy 800 m |
| 09-18 | 09-17 anomaly window | pull → pull: due 1.18 | normal | distance 1100 m |
| 09-21 | 수면 3h01m, readiness POOR | push → push: due 1.43, 종목당 2 set maintain | reduce | recovery 600 m |
| 09-24 | 일반 | push → push: BENCH_PRESS/- 3×12 @30, SHOULDER_PRESS/-, TRICEPS_EXTENSION/- | normal | distance 1100 m |
| 09-25 | readiness POOR, recovery 1500 min | legs → legs: push/pull 어제 ≥ 11 set으로 resting, 2 set maintain | reduce | recovery 600 m |
| 09-28 | 일반 | legs → pull: pull due 1.71 > push 1.43 > legs 0.89 | normal | distance 1100 m |
| 10-01 | recovery row 없음, coverage gap | legs → legs: neglected(8일) | normal(no adjustment) | distance 1100 m |

모든 날짜에서 09-17 swim의 3025 m summary는 baseline이 아니며 plausible 525 m를 쓴다.

Bias 확인(counterfactual, 2026-08-01~10-01 62일 매일 실행, `distribution.py/txt`): pull 26 / push 14 / legs 22.
같은 기간 실제 session(하루 ≥ 3 primary set) pull 24 / push 20 / legs 9. Pull 비율(42% vs 실제 45%)은 사용자 패턴과
같고, push 몫이 legs로 간 것은 하체 보호(neglected 9회, push/pull resting 6회, recovery reduce 2회, due 5회) 때문이다.
주 5회 strength 기준 legs 약 1.75회/주로 1-2회 goal 안이다.

## 알려진 한계

- 매핑 set의 대부분이 watch 자동 인식 label이고 category-only label(`BENCH_PRESS/-` 등)에 장비가 섞여 load가 30-60 kg로
  흔들린다 → 많은 load target이 `low` confidence. 정확도를 높이려면 Garmin Connect에서 종목/변형을 확인해야 한다.
- UNKNOWN set(약 26%)은 region 집계에서 빠진다 → region set 수는 하한, focus 선택이 치우칠 수 있다.
- RIR, 통증, 장비 가용성, paddle/fin, lap intensity는 데이터에 없다. 통증은 `--avoid` 명시 입력으로만 반영한다.
- Garmin이 idle length로 기록하지 않은 벽 휴식은 감지할 수 없고, length timing이 이상한 lap이 많아(예: 09-03
  600 m lap) 연속 거리 baseline이 보수적으로 낮게 나온다. 그래서 anchor는 설정 baseline(1000 m)과의 max다.
- Activity/recovery sync coverage가 기록되지 않아 "활동 없음"과 "미동기화"를 구분할 수 없다(notice로만 표시).
- 2.5 kg 증량 단위와 시간 추정(3분/set)은 고정 상수다.
- Focus 정렬은 매일 독립적으로 계산된다(사용자가 실제로 무엇을 했는지만 반영; 이전 추천을 기억하지 않음).
  사용자가 upper body를 거의 매일 무겁게 하므로 push/pull이 "resting"이 되는 날이 많고, 그날은 legs가 된다.
  Push는 실제 비율보다 적게 추천된다(23% vs 38%).
- 실데이터에서 HRV 규칙은 0/28일 발동(항상 BALANCED), 선택적 대안(stagnation)은 검증 14일 중 0회.
  Butterfly 임계값은 100 m에서 9/21 swim이 발동해 200 m로 올렸다 → 발동 빈도는 보정에 쓴 같은 데이터 기준이다.
- 2026-09-12 readiness는 하루 끝 값이 저장돼 있다(위 recovery 절).
- 임계값(HR zone 5 120 s, anaerobic TE 2.5, butterfly 200 m, sleep 4/5 h 등)은 이 계정의 2026-07~09 데이터로
  보정했다. 데이터가 늘면 발동 빈도를 다시 확인한다.
