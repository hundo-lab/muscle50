# Training Recommendation v1

요청 날짜 하나에 대해 **오늘의 strength 계획**과 **다음 수영 목표**를 저장된 canonical 데이터만으로 결정적으로
계산한다. LLM, ML, 합성 readiness 점수 없음. Migration, ingestion/refresh/normalization 변경, production 쓰기 없음.

```powershell
uv run muscle50 recommend --date 2026-09-24            # text (ASCII only)
uv run muscle50 recommend --date 2026-09-24 --json     # 근거 전체 JSON
uv run muscle50 recommend --date 2026-09-24 --avoid triceps --avoid lats   # 통증 등으로 오늘 뺄 muscle group
uv run muscle50 recommend --date 2026-09-24 --focus shoulders  # 오늘 할 focus를 직접 지정 (push/pull/legs/shoulders)
```

## 계층

| 계층 | 파일 | 역할 |
| --- | --- | --- |
| domain | `domain/training_goals.py` | `TrainingGoals` frozen dataclass(code default, 저장 없음) |
| domain | `domain/recovery_assessment.py` | 필드별 투명 규칙 → `normal` / `hold` / `reduce`, D-1/D-2 lookback |
| domain | `domain/strength_recommendation.py` | focus 선택, 종목 선택, double progression, swim overlap, UNKNOWN 안내 |
| domain | `domain/swim_recommendation.py` | swim 분석(연속 구간, pace, 강도), 다음 수영 목표 |
| domain | `domain/training_recommendation.py` | 날짜 의미 정의, 위 모듈 조합, notice |
| application | `application/recommend_training.py` | `BuildTrainingRecommendation`: 기존 read-only reader로 한 번 읽고 domain 호출 |
| presentation | `presentation/terminal.py` | `render_training_recommendation`(ASCII, Garmin activity 이름 미출력), `_json` |
| CLI | `muscle50 recommend` | `analytics snapshot`과 동일: `ensure_directories()`/`migrate()`/Garmin 인증 없음 |
| application | `application/nutrition_recommendation.py` | 추천이 **만들어진 뒤** 같은 날짜의 `nutrition status`와 guidance를 붙인다(추천 입력 아님) |

Nutrition(2026-10-02, `docs/nutrition-recommendation.md`): 추천 결정(focus, 종목, set/rep/load, recovery/수영 조정)은
nutrition을 입력으로 받지 않는다. Text의 `== Nutrition ...` 절(목표 미설정이면 없음)과 JSON 끝 `nutrition` key만 추가되고 기존
필드와 `recommendation_version`은 그대로다.

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
- **D와 D-1의 swim**은 strength overlap 입력. 다음 수영 목표의 swim history는 **D-28 ~ D**다(strength와 같은
  "D 이전 28일" + 이미 한 D의 수영). Hardening v1 이전에는 Analytics snapshot window(D-27 ~ D)를 그대로 써서
  D-28 swim이 빠지는 하루 차이가 있었다(`analyze_swims`가 snapshot에 29일을 넘겨 시작일을 D-28로 맞춤, 회귀 테스트).
- Recovery 필드별 출처는 아래 표. 가장 최근 activity가 D-2 이전이면 `activity_coverage_gap`(미동기화일 수 있음,
  휴식으로 간주하지 않음). 데이터 신선도 전체는 아래 "데이터 신선도" 절.

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

### 사용자 지정 focus (`--focus`)

`--focus push|pull|legs|shoulders`는 **선호이지 안전/회복 맥락을 무시하는 허가가 아니다.**

- 없으면 위의 자동 선택 그대로(순위 규칙 변경 없음). 출력은 `[auto-selected]`, JSON `focus_source: "auto"`.
- 있으면 요청한 focus로 세션을 만들고 **다른 focus로 바꾸지 않는다.** 출력은 `[user-selected; automatic would
  be X]`, JSON `focus_source: "user"`, `auto_focus`(자동 순위가 골랐을 region, 근거용). Region 순위 표는
  그대로 근거로 출력한다.
- 그대로 적용되는 규칙: recovery normal/hold/reduce, swim overlap(강한 swim 후 overhead press를 key/accessory로
  쓰지 않음, deltoid/lats 1 set 감소), `--avoid`, double progression, UNKNOWN/data-quality 안내.
- 48h 휴식 규칙: 요청한 focus의 primary set이 어제 ≥ 6이면(자동 선택에서는 그 region을 제외하는 규칙) focus는
  유지하고 세션을 reduce로 낮춘다.
- `shoulders`는 자동 region이 아니다(push/pull에 걸쳐 있음). Primary muscle이 anterior/lateral/posterior
  deltoid인 종목만 후보다. Secondary muscle로 deltoid가 있는 종목(bench press, row 등)은 shoulders 종목이 되지
  않는다. v1 taxonomy에는 posterior deltoid가 primary인 rule이 없으므로 출력에 "never counted"로 표시한다
  (0 set을 방치로 읽지 않도록).
- 요청한 focus에서만 알리는 "history is limited" 두 경우(부하 목표는 항상 기록된 부하에서만 나오고 세션을 다른
  종목으로 채우지 않는다):
  1. 28일 내 익숙한 종목이 없음 → 종목/부하 추천 없음, 다른 focus로 넘어가지 않음.
  2. 계획한 종목이 모두 1회 세션뿐 → 목표가 그 한 세션에만 근거함.
- 세션이 목표 시간보다 짧은 경우는 자동/요청 focus 모두 아래 "시간 목표와 부족분 보고"로 알린다(Hardening v1에서
  기존 3번째 조건 "compound 1개 이하로 accessory slot이 빔"을 대체).

### 종목 선택 (약 40분, Hardening v1)

- 후보: focus의 primary muscle을 가진 매핑된 label 중 28일 안에 한 것(원본 Garmin label 그대로). `--avoid` muscle이
  primary나 secondary면 제외. 익숙함 순서: session 수 → set 수 → 최근 날짜 → label 문자열.
- 크기: key 1 + accessory 최대 2 + isolation 1 = 최대 4종목(3 set씩이면 41분). 세션 시간 목표(40분)는 이 구조를
  채우는 계획 목표이며, set을 늘려 시간을 채우지 않는다(종목별 세션당 set 수는 자동 인식 label 때문에 부풀려져 있어
  근거로 쓰지 않음).
- Key 1개: 가장 익숙한 compound(pattern: horizontal/vertical push/pull, squat, hinge, lunge). 강한 swim 후에는
  vertical push 제외(없으면 가장 익숙한 isolation).
- **Muscle balance**(taxonomy primary muscle과 실제 history만 사용, 보편 템플릿 없음): key 다음 모든 slot은
  (1) plan이 아직 다루지 않은 focus primary muscle → (2) plan에서 덜 다룬 muscle → (3) key와 다른 movement pattern →
  (4) 익숙함 순으로 고른다. 한 primary muscle은 다른 focus muscle의 익숙한 후보가 남아 있는 동안 세 번째 종목을 받지
  않는다(`MAX_EXERCISES_PER_PRIMARY_MUSCLE = 2`).
- **Heavy hinge 1개**: Garmin category `DEADLIFT`이면서 hinge pattern인 label(예: `DEADLIFT/BARBELL_DEADLIFT`,
  `DEADLIFT/STRAIGHT_LEG_DEADLIFT`)은 한 세션에 하나만 둔다(`HEAVY_HINGE_CATEGORIES`). 둘은 posterior chain/허리 부하가
  크게 겹치므로 muscle coverage나 시간 채우기를 위해 두 번째를 넣지 않는다. 어느 것을 둘지는 기존 순서(위 balance →
  익숙함)가 정하고, 다음 slot은 겹치지 않는 익숙한 종목을 고른다. 없으면 세션을 짧게 두고 "one heavy hinge per
  session (X is planned)"로 이유를 적는다. 일부러 좁은 규칙이다: `HIP_RAISE/BARBELL_HIP_THRUST_ON_FLOOR`(hinge
  pattern, category HIP_RAISE)는 deadlift 변형이 아니라서 대상이 아니며, label은 이름 변경/병합하지 않는다.
- Accessory 1: 남은 compound 중 위 순서 첫 번째(이미 heavy hinge가 있으면 다른 heavy hinge 제외).
- Accessory 2: 아직 다루지 않은 muscle의 compound(1 session이어도), 또는 28일 ≥ 2 session인 compound — 단 후자는
  익숙한 isolation이 있는 미커버 muscle이 2개 이상 남아 있으면 쓰지 않는다(남은 slot을 그 muscle들에 쓰기 위해).
- Isolation 1개: 위 순서 첫 번째. 그 뒤 4종목이 안 됐으면 아직 다루지 않은 focus muscle의 isolation을 1개 더 둘 수
  있다(완성도; 예: compound가 더 없는 focus).
- 결과(production 62일 counterfactual, HEAD `8b259e7` 대비): 같은 primary muscle 3종목 이상인 plan 6 → 0, heavy hinge
  2개인 plan 2 → 0(hinge 규칙 전 hardening 초안은 17), push는 chest 2개 대신 lateral deltoid 포함, legs는 quad 2 + hinge 1
  (+ hip thrust가 익숙하면 그것)로 3종목 32분이 많고 부족분을 보고한다. 자동 focus 선택은 62일 모두 동일.
- 목표 + 5분을 넘으면 둘째 accessory를 뺀다. 무작위 variety 없음. 선택적 대안은 아래 조건일 때만 최대 1개.

### Focus coverage와 시간 부족분 보고

- `focus_coverage`(JSON, text "Focus coverage"): focus의 primary muscle마다 `covered`(계획 종목), `avoided`,
  `no_taxonomy_rule`(어떤 rule도 그 muscle을 primary로 쓰지 않음; 예 posterior deltoid, forearms),
  `no_familiar_history`, `excluded_after_hard_swim`, `not_selected`.
- 추정 시간 + 5분 < 목표면 reason 한 줄: 몇 분/몇 종목인지, 빠진 component와 이유, 고려했지만 넣지 않은 익숙한
  종목과 이유(이미 다룬 muscle이고 1 session뿐 / 이미 2종목 / 세션 크기 한도 / 강한 swim 후 overhead press), 다른
  익숙한 종목이 없음, reduce의 set 감소(원인별 표기, 아래), 강한 swim set 감소. 끝은 항상 "nothing was added to fill
  the time". History 원인이 있으면 "history is limited:"로 시작한다. 4종목을 다 채웠는데 짧은 경우(reduce)는 종목 목록
  없이 set 감소만 원인으로 적는다.

### 조정 원인 표기 (통합 수정, 2026-10-01)

세션 level(`adjustment_level`)은 recovery level과 48 h rest rule(요청 focus의 어제 primary set ≥ 6, 또는 자동 경로에서
모든 region이 어제 heavy) 중 강한 쪽이다. 결정은 그대로이고 설명만 원인을 나눈다.

- Recovery 줄(`adjustments` 첫 줄)은 recovery 자신의 level로만 쓴다(`recovery hold: ...`). Recovery가 normal이면
  recovery 줄이 없고(row가 없으면 "no recovery data ... no recovery adjustment"), rest rule 줄이 reduce를 설명한다.
- Set 감소: recovery만 → `recovery reduce: one set fewer`(기존 문구), rest rule만 → `48 h rest rule reduce: one set
  fewer`, 둘 다 reduce → `recovery reduce and 48 h rest rule reduce: one set fewer`. 시간 부족분 reason도 같은 원인.
- Progression "no load or rep increase": rest rule이 관여하면 증량을 막는 원인을 모두 적는다(예 recovery hold +
  rest rule → `recovery hold, 48 h rest rule reduce: ...`). Recovery만이면 기존 `recovery <level>: ...`.
- Text heading: 두 level이 같으면 `== Recovery adjustment: <level> ==`(기존과 동일), 다르면
  `== Recovery adjustment: hold; session adjustment: reduce ==`.
- 예: 2026-10-01 `--focus pull`은 recovery hold(09-30 lookback carry)이고 09-30 pull 15 set 때문에 rest rule로 reduce다.
  이전 출력은 이것을 "recovery reduce"로 표기했다.

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
| work set 2개 이상이 range 상한 도달 | `increase_load` | +2.5 kg(아래 "증량 step" 조건일 때만) 또는 "next available step", reps = max(하한, 상한 - 4) |
| range 하한 미달 | `add_reps` | 같은 무게로 하한 rep |
| 1 set만 상한 도달 | `add_reps` | 같은 무게로 2 set 이상 상한 |
| 그 외 | `add_reps` | 같은 무게, best + 1 rep |

- **Performance 신호**: 같은 work load였던 직전 occurrence보다 best reps가 2 이상 줄면 `maintain`(마지막 수행 반복).
  무게가 낮아진 것만으로는 regression이 아니다(같은 label 안에 다른 장비가 섞일 수 있음).
- **Recovery hold/reduce**: `increase_load`/`add_reps`를 `maintain`으로. Maintain 목표 reps는 range 상한으로 자른다.
- **Load confidence**: 28일 work load의 최대/최소 > 1.5배이거나 `PULL_UP/-`, `PUSH_UP/-`,
  `TRICEPS_EXTENSION/BENCH_DIP`(추가 중량인지 assist인지 Garmin이 구분하지 않음)이면 `low` + 사유.
  마지막 occurrence label이 자동 인식만이면 "auto-detected" caveat.
- **Low confidence 부하 표시**(Hardening v1, progression 규칙/목표값은 그대로): `recorded_load_range_kg`(window의
  work load 최소-최대), `same_load_evidence`(마지막 work load를 쓴 이전 session이 있음), `load_guidance`. 범위가 넓고
  마지막 부하가 반복된 적 있으면 "그 부하가 비교 가능한 시작점", 아니면 "한 label 아래 X-Y kg가 기록됐고 마지막
  부하가 반복되지 않음: 지난번 장비/부하를 확인, 모르면 낮은 쪽에서 시작". Text는 `@ ~16 kg (low confidence:
  recorded 16-30 kg; confirm equipment/load used last time)`처럼 정확한 값으로 보이지 않게 쓴다. Label은 병합/
  이름 변경하지 않는다.
- **Stagnation**: 최근 3번이 같은 work load이고 best reps가 늘지 않음 → 같은 movement pattern(없으면 같은 primary
  muscle)의 다른 익숙한 label을 **선택적 대안**으로 1개 제시(기본 계획은 바꾸지 않음).
- 근거(`basis`)에는 마지막 session, 판단 이유, 2-4주 trend(날짜별 work load × best reps)가 들어간다.

### 증량 step (Progression Hardening v1, 2026-10-01)

**언제** 증량하는지(work set 2개 이상 상한)는 그대로다. **얼마나**만 바뀐다. `increase_load`가 나왔을 때:

| 조건 | `load_kg` | `load_increase_from_kg` | `load_step` | Text |
| --- | --- | --- | --- | --- |
| label이 `PULL_UP/-`, `PUSH_UP/-`, `TRICEPS_EXTENSION/BENCH_DIP`(`AMBIGUOUS_LOAD_LABELS`) | `null` | 마지막 work load | `smallest_available_direction_unknown` | `@ one smallest available step from ~8 kg (less if assistance, more if added resistance)` |
| 2.5 kg ≤ 15% × work load(`MAX_EXACT_LOAD_INCREASE_RATIO`, 즉 work load ≥ 약 16.7 kg) | work load + 2.5 | `null` | `null` | `@ 22.5 kg`(기존과 동일) |
| 그 외(2.5 kg > 15%) | `null` | 마지막 work load | `smallest_available` | `@ next available step above 6 kg` |

- 더 작은 숫자 step(예 +1 kg)을 만들지 않는다. 장비별 증량 단위는 데이터에 없으므로 추론하지 않는다.
- 애매한 label은 15% 이하여도 숫자 증량이 없다. `load_guidance`에 "if the recorded weight is assistance, reduce
  assistance by the smallest available step; if it is added resistance, increase by the smallest available step"을
  더한다(어느 쪽인지 추정하지 않음). Confidence는 기존대로 `low`.
- 순서: step은 상한 분기 안에서만 정해지고, 이후 same-load regression, recovery hold/reduce, 48 h rest rule이
  기존대로 `maintain`(마지막 work load/reps, 숫자)으로 덮는다. 덮인 `maintain`에는 `null` 목표나 step 필드가 남지
  않는다. Basis 첫 판단 문장은 상한 도달과 step 이유를 그대로 설명한다.
- Low confidence 판정(1.5배 spread, 애매한 label)은 숫자 목표 유무와 무관하게 같은 work load를 기준으로 한다.
- Reps 재시작(상한 - 4), rep range, trigger, regression, recovery, focus/종목/set 수는 바뀌지 않는다.

JSON schema(`strength.exercises[].progression`, 추가 필드는 모든 exercise에 항상 있음 — `dataclasses.asdict`):

- `load_kg`: 숫자 목표 또는 `null`. `null`이면 `action`으로 의미를 구분한다: `increase_load`면 숫자 없는 증량,
  `establish_baseline`/load 미기록이면 load 목표 없음.
- `load_increase_from_kg`(신규): `increase_load`이고 `load_kg`가 `null`일 때만 마지막 recorded work load. 그 외 `null`.
- `load_step`(신규): 같은 경우에만 `smallest_available` 또는 `smallest_available_direction_unknown`. 그 외 `null`.
- 숫자 목표 recommendation은 기존 key 값이 모두 같고 새 key 두 개가 `null`로 추가될 뿐이다(하위 호환).

**15%를 고른 이유**(2026-10-01 production audit, evidence `C:\temp\muscle50-evidence-20261001-progression-audit\`
`cap_analysis.py`/`cap.txt`): 생리학적 최적값이 아니라 **정확한 +2.5 kg 숫자를 낼 만큼 믿을 수 있는지의 기준**이다.
이 사용자의 2026-07~09 history에서 (1) 애매하지 않은 label의 실제 증량은 한 번도 10% 이하가 아니었고, 2.5 kg
step이 실제로 쓰이고 추천과 일치한 유일한 경우가 20 → 22.5 kg(12.5%)였다 → cap ≥ 12.5%. (2) 10-19.9 kg 구간의
실제 증량(장비 전환 제외)은 모두 +4-5 kg(33%) 이상이었고 16.5/17.5 kg는 기록된 적 없다 → 14 → 16.5, 15 → 17.5는
만든 숫자 → cap < 16.7%. 15%는 그 사이다. 근거가 얇다(각 경계가 소수 사례). 16.7-20 kg trigger는 데이터에 없다.

## Recovery 조정

합성 점수 없이 필드별 규칙. 가장 강한 규칙이 level을 정한다. **값이 없으면 규칙이 발동하지 않는다**(missing ≠ poor).
Row가 없고 아래 lookback도 발동하지 않으면 level `normal` + "no recovery adjustment" 표시와 `recovery_row_missing` notice.

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

### Recovery lookback (Hardening v1)

D의 부분 row가 최근의 분명히 나쁜 회복을 지우지 않게 하는 투명한 규칙. 합성 점수 없음.

- **발동 조건**: D row가 없거나 D의 `sleep_seconds`가 NULL(밤 측정이 없음). D의 readiness 값이 있어도 그것은 수면
  측정 없이 저장된 값이다(2026-10-01 RAW: readiness `validSleep: false`, `sleepScore: null` — 이 field는 저장되지
  않으므로 규칙은 저장된 `sleep_seconds` NULL만 본다).
- **확인 대상**: D-1, D-2 row의 아침 field(`sleep_seconds`, `sleep_score`, `training_readiness_level`,
  `recovery_time_minutes`)를 위 표와 같은 임계값으로. HRV status는 주간 rolling 값이라 제외. 값이 없으면 발동 안 함.
- **Carry**: D-1에서 reduce 수준 규칙이 발동했거나, D-1과 D-2 둘 다 어떤 규칙이 발동했으면 `hold`를 가져온다.
  가져온 근거는 D의 측정이 아니므로 **최대 `hold`**(reduce로 올리지 않음; region 순위는 reduce에만 반응하므로 자동
  focus도 바뀌지 않는다). D 자신의 발동 규칙(예: D readiness POOR → reduce)은 그대로 더 강하게 적용된다.
- D-1 하나만 hold 수준이면 근거로 보고만 하고 carry하지 않는다.
- 출력: `recovery.lookback`(reason, D-1/D-2 observation, poor_dates, carried_level, explanation). Text에 "Lookback"
  절, 조정 줄에 날짜가 붙은 근거("2026-09-30 fired a reduce-level rule (sleep_seconds 3h49m ...)"). D의
  observation/`missing_fields`/`fired`에는 D-1/D-2 값이 섞이지 않는다.
- Calibration(2026-08-01~10-01): lookback 평가는 8월 전체(recovery row 없음, 발동 0)와 09-13, 10-01. Carry는 2일:
  09-13(D-1 09-12 sleep 1h41m, score 29)과 10-01(D-1 09-30 sleep 3h49m + LOW 39, D-2 09-29 LOW 44). 둘 다 이전에는
  `normal`이었다.

## Swimming ↔ strength 간섭

- D 또는 D-1 swim → overlap으로 표시(shoulders/back/triceps). 약한 overlap이면 swim 관련 muscle 종목에
  "2-3 reps short of failure" 문구.
- **강한 overlap**: HR zone 5 ≥ 120 s, 또는 anaerobic TE ≥ 2.5, 또는 plausible butterfly ≥ 200 m.
  → push/pull region 후순위, vertical push(overhead press)는 key/accessory로 선택하지 않음,
  primary anterior/lateral deltoid·lats 종목 1 set 감소.
- 오늘 focus가 push/pull/`--focus shoulders`이면 다음 수영에 "no butterfly or paddles"와 "several hours" 주의를
  붙인다(shoulders도 수영과 같은 근육을 쓴다).
- Lap `intensity_type`은 production에서 전부 NULL이고 paddle/fin 기록은 없다 → 사용하지 않음(발명 안 함).

## UNKNOWN strength 안내

최근 14일 strength activity에 UNKNOWN ACTIVE set이 있으면 activity별 `strength_unknown_exercise` notice:
날짜, activity ID, set sequence, "Garmin Connect에서 종목 지정 후 `muscle50 garmin refresh <id>`". 추측하지 않고,
추천은 막지 않는다. 7일/28일 UNKNOWN set 수도 함께 보고한다.

## Taxonomy rule 없는(`no_rule`) 종목 안내 (Hardening v1)

UNKNOWN과 별개다. 알려진 Garmin label인데 taxonomy rule이 없으면 그 set은 어떤 muscle에도 세지 않는다.

- 28일 history의 activity × label마다 `strength_no_rule_exercise` notice: 날짜, activity ID, label, set 수/sequence,
  "그 muscle/region이 focus·volume에서 과소평가될 수 있음". 7일 합계는 strength reason에도 나온다.
- 같은 Garmin category에 category-only rule이 있으면 그 primary muscle/region을 **경고 문구용 힌트로만** 보여준다
  (`category_hint_muscle`/`category_hint_region`, region별 `no_rule_hint_sets_last_7_days/previous_day`). 힌트는
  set 수, 순위, eligibility, 48 h rest 판단에 절대 쓰지 않는다(매핑이 아님). Category rule도 없으면(`PLYO/BOX_JUMP`)
  "region unknown".
- 요청 focus의 어제 no-rule 힌트 set이 있으면 "48 h rest 판단이 놓쳤을 수 있음" 조정 줄(Hardening v1 작성 당시 예:
  2026-09-30 pull 15 set이 모두 no-rule이라 10-01 pull이 "yesterday 0"으로 보였다. Taxonomy coverage `aba8cfe` 이후 그
  label들은 매핑되어 10-01 pull은 어제 15 set → 48 h rest rule reduce다).
- Rule은 이 기능에서 자동으로 만들지 않는다. Hardening v1이 제안한 label 6개와 보류했던 `TRICEPS_EXTENSION/
  LYING_TRICEPS_EXTENSION_TO_CLOSE_GRIP_BENCH_PRESS`는 Taxonomy coverage `aba8cfe`에서 rule이 추가됐다
  (`docs/exercise-taxonomy.md`). 2026-10-01 28일 기준 남은 non-UNKNOWN no-rule label은 `PLYO/BOX_JUMP`뿐이다.

## 데이터 신선도 (Hardening v1)

`data_freshness`(JSON)와 text "Data freshness" 절: 최신 저장 activity/strength/swim/recovery 날짜, D recovery row
존재와 수면 기록 여부, `sync_coverage_recorded = false`와 문장 "sync completeness is not recorded: a day without a
stored activity is 'no recorded activity', not a confirmed rest day ...". 스키마가 sync coverage를 기록하지 않으므로
"활동 없음"을 휴식으로 확정하지 않는다. Notice:

- `activity_coverage_gap`(기존): 최신 activity가 D-2 이전.
- `recovery_row_missing`: D row 없음(아직 미동기화일 수 있음) + lookback 결과.
- `recovery_row_partial`: D row에 수면 없음 — 기록 안 됨인지 미동기화인지 알 수 없음, readiness는 수면 측정 없이
  저장됨 + lookback 결과.
- `recovery_coverage_gap`: 최신 recovery row가 D-2 이전.
- `swim_gap`: 최신 swim이 10일 이상 전이거나 28일 내 없음 — 실제 휴식과 미동기화를 구분할 수 없음.

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
2. (Hardening v1) 마지막 저장 swim이 10일 이상 전이거나 28일 내 swim 없음 → `return_easy`: 0.8 × anchor(현재 800 m)
   "easy in total, continuous or with short rests as needed; no pace target". 거리도 강도도 올리지 않는다
   (anchor 아래, pace 목표 없음, warm-up/cool-down 추가 없음, 영법/paddle/fin 언급 없음). 다음 swim부터 아래 규칙이
   다시 적용되며(distance와 pace는 한 번에 하나씩), 1500 m 장기 목표와 anomaly-safe baseline은 그대로다. 공백이
   미동기화일 수도 있다고 명시한다(어느 쪽이든 쉬운 재진입은 안전). 임계값 10일: 2026-07~09 swim 간격 최대 8일
   이라 과거에는 한 번도 발동하지 않았고, 2026-09-27~10-01(09-17 이후 10-14일) 중 recovery reduce가 아닌 날
   (09-27, 09-28, 09-29, 10-01)에 발동한다.
3. 14일 안에 effort 없음 → `distance_progression`: min(1500, anchor + 100 m, 2×pool 단위) 연속
4. 마지막 swim이 effort → `pace_intervals`(pace baseline이 있을 때): 8 × 100 m freestyle, 현재 pace보다
   4 s~1 s 빠르게(목표 하한 1:36/100 m 이상), 20-30 s 휴식. pace baseline이 없으면 `easy_continuous`
5. 마지막 effort가 7일 넘음 → `distance_progression`, 아니면 `easy_continuous`(0.8 × anchor)

목표 거리가 1500 m에 닿으면 distance progression은 "1500 m timed, 24:00-27:30"이 된다.
Strength 맥락: 어제 shoulder/back/triceps primary set ≥ 8이면 intervals → easy. 오늘 focus가 push/pull이면
"no butterfly/paddles, 몇 시간 간격" caution, legs면 "kick/fins easy".

## Production read-only 검증 — Progression Hardening v1 (2026-10-01)

Evidence(repo 밖): `C:\temp\muscle50-evidence-20261001-progression-audit\`(`sweep_full.py`, `sweep_baseline.json`
(base `4f26ec2`), `sweep_impl.json`(+ `_rerun` byte-identical), `compare_impl.py/txt`, `sweep_increases.py`,
`increases.json`/`increases_impl.json`, `cap_analysis.py/txt`, `fingerprint.py`, `impl_before.json`/`impl_after.json`).

- 93일(07-02~10-02) × (auto + focus 4) = 465 run. Focus, 종목 label/role/set 수, recovery/session level과
  adjustments, heavy hinge, focus coverage, UNKNOWN/no-rule notice, 모든 notice, swim 전체, regions/reasons/
  alternative/minutes 차이 0. Progression 밖 payload 차이 0.
- 바뀐 progression 54 항목(54 run), 바뀐 field는 `load_kg`, `basis`, `load_guidance`와 새 필드뿐:
  - `LATERAL_RAISE/ONE_ARM_CABLE_LATERAL_RAISE` 6 → 8.5 kg 9 run(09-24 auto/push/shoulders, 09-26/28, 10-02
    push/shoulders) → next available step above 6 kg.
  - `SHOULDER_PRESS/-` 14 → 16.5 kg 13 run(07-09~07-16) → next available step above 14 kg.
  - `PULL_UP/-` 8 → 10.5 kg 8 run(07-21~09-07 pull, 09-05 auto) → `smallest_available_direction_unknown`.
  - 위 label의 덮인 `maintain` 24 run(lateral 12, shoulder press 2, pull-up 9, push-up 1): load/reps 동일, basis의
    상한 도달 문장만 바뀜.
- `increase_load` 152 → 숫자 122(LEG_CURL 61.5, ROW 22.5/32.5/42.5/52.5, LAT_PULLDOWN 25/42.5/82.5, SQUAT 32.5/42.5,
  BENCH 22.5, LUNGE 22.5, SHOULDER_PRESS 22.5) + step 안내 30. 새 text에 "8.5 kg", "16.5 kg", "10.5 kg" 없음.
- Label 단위(선택/recovery 무시) trigger 32개: 숫자 18, step 14(애매한 label 11 + lateral 6, shoulder press 14,
  lying triceps 15 kg). 20 → 22.5(6 label)와 50 → 52.5(ROW/-, BENCH_PRESS/-)는 숫자 유지. Trigger 자체(210 day-label)는 동일.
- Fingerprint before = after(DB/WAL, 28 table, RAW 954). `garmin refresh` 미실행.

## Production read-only 검증 — Hardening v1 + Taxonomy coverage 통합 (2026-10-01)

Evidence(repo 밖): `C:\temp\muscle50-evidence-20261001-integration-hardening\`(`compare62.py`, `c62_reference.json`
(승인 reference `272761a`), `c62_combined_prefix.json`(cherry-pick 직후 `38a23ae`), `c62_integration.json`,
`analyze62.py/txt`, `analyze_fix.py/txt`, `pre_fix_*`/`post_fix_*` text/JSON, `check0922.py/txt`, `fingerprint.py`,
`before.json`/`after.json`). `garmin refresh`는 실행하지 않았다.

- 62일(08-01~10-01) × (auto + focus 4) 310 run, reference 대비: 자동 focus 62/62 동일, heavy hinge 2개 plan 0, recovery
  level/carry 변경 0. 결정 차이 26 run은 모두 Taxonomy coverage로 세지는 label 효과다: shoulders/push의
  `LATERAL_RAISE/-` → `LATERAL_RAISE/ONE_ARM_CABLE_LATERAL_RAISE`, `SHOULDER_PRESS/SEATED_BARBELL_SHOULDER_PRESS`
  등 추가(shoulders 23 → 32분), 09-24 auto의 lateral raise 교체, 10-01 pull hold → reduce(09-30 15 set), 09-23/09-30/
  10-01 auto·legs swim에 "no butterfly or paddles" caution 추가(session type/main set 불변).
- 한 primary muscle 3종목: 자동 plan 0. 사용자 지정 legs 09-17/09-18(SQUAT, LUNGE, LEG_EXTENSIONS = quad 3)은 reference와
  동일하며 glutes에 익숙한 후보가 없어 규칙상 허용된다.
- 원인 표기 수정은 `38a23ae` 대비 결정 차이 0, text 차이는 rest rule이 reduce를 만든 사용자 지정 focus 37 run의 원인
  문구뿐이다(자동 run 0). 수정 후 recovery가 reduce가 아닌데 "recovery reduce"를 쓰는 run은 0(reference 30).
- 10-01: auto legs(LUNGE/BARBELL_DEADLIFT/SQUAT), shoulders = SEATED_BARBELL 40 kg + DUMBBELL 16 kg + ONE_ARM_CABLE 6 kg
  약 32분, posterior_deltoid `no_taxonomy_rule`(대체 없음), push = BENCH/SEATED_BARBELL/CLOSE_GRIP/ONE_ARM_CABLE,
  pull = ROW/LAT_PULLDOWN/PULL_UP/CURL 2 set씩 29분(48 h rest rule reduce, recovery hold). 09-22 `24451010022`의
  shoulder 17 set(8 + 6 + 3)은 저장 label 그대로 매핑된다.

## Production read-only 검증 — Recommendation Hardening v1 (2026-10-01)

(Taxonomy coverage 이전 tree의 기록. 통합 tree 결과는 위 절.)

Evidence(repo 밖): `C:\temp\muscle50-evidence-20261001-hardening\`(`audit_*.py/txt`, `calibrate.py`, `compare.py/txt`,
`calib_old.json`(HEAD `8b259e7`)/`calib_new.json`, `rec_<case>.txt/json/_rerun.json`, `preview_rules.py`,
`preview_1001_*.txt`, `fingerprint.py`, `before_v5.json`/`after_v5.json`/`after_preview.json`, `hinge_compare.py/txt`).

- 작업 중 production DB가 **다른 프로세스의 `garmin refresh` 6회**(2026-10-01 16:12-16:23 KST, 09-17/09-18/09-21/09-22×2/
  09-23 activity)로 바뀌었다. 09-22 `24451010022`는 Garmin Connect에서 종목이 지정되어 `SHOULDER_PRESS/
  SEATED_BARBELL_SHOULDER_PRESS` 8, `SHOULDER_PRESS/DUMBBELL_SHOULDER_PRESS` 6, `LATERAL_RAISE/
  ONE_ARM_CABLE_LATERAL_RAISE` 3 set이 됐다(당시 모두 no-rule; `aba8cfe`에서 rule 추가). 이 작업은 refresh를 실행하지 않았다(reader는 `mode=ro`).
  최종 검증은 그 이후 상태에서 before/after fingerprint 동일(DB sha/size/mtime, `-wal` 0 bytes, 28 table, RAW 954)로
  다시 했다.
- 8개 실행(10-01 auto/`--focus shoulders`/`--focus legs`, 09-28 `--focus legs`, 09-18, 09-21, 09-25, 09-13) text/JSON
  exit 0, JSON 재실행 byte-identical, text ASCII.
- 62일(08-01~10-01) HEAD 대비: 자동 focus 62/62 동일(pull 26/legs 22/push 14), 같은 primary muscle 3종목 이상 plan 6 → 0,
  heavy hinge 2개 plan 2 → 0, 4종목 plan 39 → 39(push는 늘고 legs는 줄었다), recovery level 변경 2일(09-13, 10-01: normal → hold, lookback), swim goal 변경 4일
  (09-27/28/29, 10-01: distance_progression → return_easy).

| case | strength | recovery | 다음 수영 |
| --- | --- | --- | --- |
| 10-01 auto (legs) | LUNGE/- (quad), BARBELL_DEADLIFT (glutes), SQUAT/- (quad), 32분; hamstrings는 SLDL뿐이라 not_selected(one heavy hinge), leg extension은 quad 3번째라 미추가; 이전: LUNGE/SQUAT/LEG_EXTENSIONS 3 quad 32분 | hold(lookback: 09-30 sleep 3h49m + LOW, 09-29 LOW) | return_easy 800 m |
| 10-01 shoulders | SHOULDER_PRESS/- 30 kg (anterior), LATERAL_RAISE/- 10 kg (lateral), 23분, posterior 누락 명시, UPRIGHT_ROW 고려·미추가 | hold | return_easy 800 m |
| 09-28 `--focus legs` | SQUAT/-, STRAIGHT_LEG_DEADLIFT, LUNGE/- 32분(BARBELL_DEADLIFT는 one heavy hinge로 미추가) | normal | return_easy 800 m |
| 09-18 (09-17 swim 다음 날) | pull 4종목 41분, swim overlap 표시 | normal | distance 1100 m(09-17 phantom summary 제외) |
| 09-21 (sleep 3h01m, POOR) | push: BENCH/OHP/TRICEPS_EXT/LATERAL_RAISE 2 set씩 29분(이전: chest 2개) | reduce | recovery 600 m |
| 09-25 (POOR, 1500 min) | legs SQUAT/SLDL/LUNGE 2 set씩 23분 | reduce | recovery 600 m |
| 09-13 (sleep NULL) | pull 41분, 증량 없음 | hold(lookback: 09-12 sleep 1h41m) | pace intervals |

## Production read-only 검증 (2026-10-01, v1)

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
- Activity/recovery sync coverage가 기록되지 않아 "활동 없음"과 "미동기화"를 구분할 수 없다(Data freshness 절과
  notice로만 표시).
- Posterior deltoid를 primary로 쓰는 taxonomy rule도, 그런 저장 label도 없다(2026-10-01 audit: label 이름에 REAR/
  FACE_PULL/REVERSE 없음, UNKNOWN 276 set은 display name도 "Unknown"). Lateral raise 옆 UNKNOWN set(09-17 seq 35,
  09-22 seq 33 — 09-22는 이후 relabel)은 rear-delt일 수도 있지만 추측하지 않는다. Garmin Connect에서 지정해도
  posterior-primary rule을 추가해야 세진다. 그래서 shoulders 세션은 posterior 없이 짧을 수 있고 그렇게 보고한다.
- Garmin Connect에서 새로 지정한 구체적 label은 rule 추가 전까지 no-rule로 빠져 그 muscle이 과소평가된다(notice로
  표시). 2026-10-01 지정 label 7개는 `aba8cfe`에서 rule이 추가됐고, 남은 no-rule은 `PLYO/BOX_JUMP`(의도적)뿐이다.
- Recovery lookback은 저장 field만 본다(`validSleep` 등 RAW 전용 field는 미사용). D-1 하나만 hold 수준이면 carry 안 함.
- 2.5 kg 증량 단위, 15% 숫자 목표 한계, 시간 추정(3분/set)은 고정 상수다. 장비별 실제 증량 단위(cable stack,
  dumbbell 간격)는 데이터에 없어 "next available step"으로만 안내한다. 증량 후 reps 재시작(상한 - 4)은 작은 무게
  isolation에서도 그대로다(예 6 kg × 20 → 다음 step × 16).
- Focus 정렬은 매일 독립적으로 계산된다(사용자가 실제로 무엇을 했는지만 반영; 이전 추천을 기억하지 않음).
  사용자가 upper body를 거의 매일 무겁게 하므로 push/pull이 "resting"이 되는 날이 많고, 그날은 legs가 된다.
  Push는 실제 비율보다 적게 추천된다(23% vs 38%).
- 실데이터에서 HRV 규칙은 0/28일 발동(항상 BALANCED), 선택적 대안(stagnation)은 검증 14일 중 0회.
  Butterfly 임계값은 100 m에서 9/21 swim이 발동해 200 m로 올렸다 → 발동 빈도는 보정에 쓴 같은 데이터 기준이다.
- 2026-09-12 readiness는 하루 끝 값이 저장돼 있다(위 recovery 절).
- 임계값(HR zone 5 120 s, anaerobic TE 2.5, butterfly 200 m, sleep 4/5 h 등)은 이 계정의 2026-07~09 데이터로
  보정했다. 데이터가 늘면 발동 빈도를 다시 확인한다.
