---
id: rest-interval-advice
title: Rest Interval Advice v1
status: integrated
migration: none
output_change: additive
user_gates: [design, integration]
---

# Rest Interval Advice v1

## 목적

- `analytics snapshot`의 근력 절에 **같은 운동의 세트 사이 휴식**(기록값 중앙값)을 그룹별(compound / isolation /
  unclassified)과 운동별로 보여 주고, 승인된 휴식 근거(REST-01..08, `docs/evidence/training-nutrition-evidence.md` 1절)를
  옆에 적는다. **조언만**이다. 어떤 추천, 세트 수, 무게 진행, 경고 등급도 이 값을 쓰지 않는다.
- 왜 필요한가:
  - Strength Set Timing v1/v1.1(`docs/strength-set-timing.md`)은 늦게 누른 버튼을 찾고 휴식을 추정하지만, 휴식 조언은
    "근거 규칙집 뒤의 별도 기능"으로 남겨 두었다(그 문서의 Non-goals). 이 스펙이 그 기능이다.
  - 지금은 휴식 요약(`Rest between sets`)이 의심 세트가 있는 window에서만 나오고, 기록값과 `[design]` 추정값이 섞여 있다.
    근거와 나란히 놓으려면 근거에 기대지 않는 값(기록값)과 그 표본이 어떻게 걸러졌는지가 필요하다.
- 근거: REST-01(Singer 2024: > 60 s에서 작은, 불확실한 근비대 이득), REST-02(Schoenfeld 2016: 훈련자에서 3분 > 1분),
  REST-04(Longo 2022: 휴식보다 volume load), REST-05(Rosa 2023: 1분 vs 2–3분), REST-06(Simão 2022: 자율 휴식), REST-07
  (ACSM 2009), REST-08(ACSM 2026: 휴식 처방 없음). 이번에 원문으로 다시 확인한 결과는 아래 "근거 확인 결과"에 있다.
- `docs/goals.md` 기여: 측정 사이 리뷰(우선순위 4)의 "근력 진척, 근육별 주당 set" 옆에서 훈련 방식(휴식)을 본다. 2026-10-26
  cut 목표(골격근량 41 kg 이상 유지) 동안 세트의 질을 지키는 데 쓰는 정보다. 판단이나 처방은 하지 않는다.

## 범위 / Non-goals

- 범위:
  1. **세트 사이 휴식(기록값)**: window 안 근력 활동에서 `ACTIVE → REST → ACTIVE`이고 앞뒤 ACTIVE가 같은 **알려진**
     Garmin label `(category, name)`인 곳의 REST `duration`. 뒤 세트가 확인된 정상 세트(Strength Set Timing 규칙 1·2:
     `reps ≥ 1`, 시간 있음, `≥ 1.0 s/rep`)일 때만 센다.
  2. **그룹별·운동별 중앙값과 개수**: compound / isolation / unclassified(그룹 나누기는 기존 `rest_between_sets`와 같음,
     REST-07 + `[design]`), 그리고 label별.
  3. **구간(band) 표시**: 각 중앙값이 Singer 2024의 분석 구간 중 어디에 드는지(short ≤ 60 s / 60–120 s / 120–180 s /
     ≥ 180 s, REST-01). 판정이 아니라 위치 표시다.
  4. **고정 근거 줄**: REST-01, 02, 04, 05, 06, 07, 08을 한 줄씩. 중앙값과 무관하게 늘 같은 문장이다.
  5. **선택지 줄(조건부)**: 어떤 그룹의 중앙값이 short 구간(≤ 60 s)이면 "더 쉬는 것은 하나의 선택지, 짧게 쉬면서 volume
     load(sets x reps x load)를 맞추는 것도 선택지"를 순위 없이 한 줄로 보여 준다(REST-01, REST-04, 모든 그룹 같은 문장).
  6. **제외 개수**: 표본이 걸러졌으므로 왜 몇 개가 빠졌는지 늘 보여 준다.
  7. `--json` 끝에 key 하나(`rest_interval_advice`)를 더한다.
- Non-goals:
  - **규칙이 아니다**: 추천(`recommend`), 세트 수, 무게 진행, 회복 판단, Telegram 응답, 코치 LLM 입력 어디에도 쓰지 않는다.
    점수, 경고 등급, "부족/충분" 판정이 없다.
  - **`recommend` 근력 절에는 v1에서 넣지 않는다.** `recommend`의 text/JSON/golden은 그대로다(set-timing 문서의 "항상 같음"
    목록 유지). 오늘 계획 옆의 휴식 문장은 처방처럼 읽히고 Telegram `/daily`와 코치가 그 JSON을 읽는다. 후속 후보로 둔다.
  - 추정 휴식(심박 기반, `[design]` 상수, 신뢰도 최고 medium)은 조언의 비교값으로 쓰지 않는다. 기존 `Set timing` /
    `Rest between sets` 줄과 `strength_set_timing` JSON은 바뀌지 않는다.
  - 1.0 s/rep 기준(`MIN_MILLISECONDS_PER_REP`)은 바꾸지 않는다(set-timing의 상수다. 아래 근거 확인 결과와 근거 문서 TEMPO-01(2026-11-01 승인) 참고).
  - 목표 휴식 시간 설정, 세션 중 타이머, 운동별 휴식 처방, 나이·목표 모드에 따른 다른 기준 없음.
  - migration 없음(읽을 때 계산, 저장 없음). Garmin 동기화 변경 없음. 심박 RAW를 읽지 않는다. LLM 없음.

## 명령 예시

명령과 flag는 그대로다(설계 결정 D2-A: 새 flag 없음).

```powershell
# text
muscle50 analytics snapshot --date 2026-03-14 --days 28

# JSON
muscle50 analytics snapshot --date 2026-03-14 --days 28 --json
```

기본 window는 7일이라 표본이 작다. 예시는 `--days 28`을 쓴다.

예상 text 출력(합성 값, 통합 때 실제 출력으로 바꿈: `tests/test_rest_interval_advice.py`의 `happy_rows()`). Strength 절
끝, 기존 taxonomy 줄과 (있으면) `Set timing` 줄 뒤에 붙는다.

```text
  Rest advice [advice only; used by no rule]: recorded REST between two sets of the same Garmin exercise label; rests before a set under 1.0 s/rep are excluded [design]
    compound: median 56 s from 3 rests (band short <= 60 s) [REST-01; groups REST-07, design]
    isolation: median 65 s from 3 rests (band 60-120 s) [REST-01; groups REST-07, design]
    unclassified: unavailable (0)
    excluded: label change or UNKNOWN 2, unchecked 1, suspect set 1 [design], missing duration 1
    BENCH_PRESS/- (compound): median 53 s from 2 rests
    SQUAT/BARBELL_BACK_SQUAT (compound): median 100 s from 1 rests
    CURL/- (isolation): median 65 s from 3 rests
    evidence (fixed lines, the same for every median; REST-01 trials: 8 of 9 in adults 18-35, 1 in > 65; no trained-only analysis) [REST-01; design]:
      [REST-01] rest > 60 s: small, uncertain hypertrophy benefit (credible intervals include 0), possibly through volume load; whether > 90 s adds more is equivocal
      [REST-02] 3 min vs 1 min, trained men, whole-body routine, 8 weeks, n=21: larger squat and bench 1RM and front-thigh thickness gains with 3 min
      [REST-04] untrained adults, knee extension, 10 weeks, n=28: hypertrophy followed total volume load more than rest length (1 min with volume load matched to 3 min: 12.9 % vs 3 min: 13.1 %)
      [REST-05] acute, reps kept in later sets: the largest loss was between 1 min and 2-3 min, 2 vs 3 min differed trivially (lower body); heavy bench at 85 % 1RM kept reps over 4 sets only with 8 min
      [REST-06] self-selected vs fixed 75 s rest, trained men, 8 weeks, n=33: similar strength gains (6.8 % vs 7.4 %); fixed rest was 37 % more time-efficient
      [REST-07] ACSM 2009, replaced by REST-08: strength, at least 2-3 min for heavy core lifts such as squat and bench, 1-2 min for assistance lifts; hypertrophy, 1-2 min for novice and intermediate
      [REST-08] ACSM 2026 sets no rest time: strength was unaffected by < 1 vs > 1 min rests (2 reviews, n=982); for hypertrophy the data could not decide (4 reviews, n=265)
    option for compound (median in band short <= 60 s), no ranking: rest longer [REST-01] / keep short rests and match volume load (sets x reps x load) [REST-04]
```

- 휴식 값은 `{:.0f} s`. 값이 없는 그룹은 `unavailable (0)`이고 0 s가 아니다.
- `option` 줄은 중앙값이 short 구간인 그룹마다 한 줄이다. 그런 그룹이 없으면 없다.
- 운동별 줄은 센 휴식이 하나 이상인 label만, group(compound, isolation, unclassified) 순서, 그 안에서 `(category, name)` 사전순이다.
- 근거 줄은 REST-01, 02, 04, 05, 06, 07, 08 순서로 한 줄씩이다(REST-04와 REST-06도 따로).
- ASCII만 쓴다(label은 Garmin 값 그대로, 이미 ASCII).

예상 JSON 출력(합성 값, key 순서 고정). top-level 마지막 key다: `strength_set_timing`이 있으면 그 뒤, 없으면
`quality_issues` 뒤. 앞의 key는 byte 단위로 같다.

```json
  "rest_interval_advice": {
    "rest_advice_version": 1,
    "advice_only": true,
    "basis": "recorded_rest_before_normal_set",
    "band_edges_seconds": [60.0, 120.0, 180.0],
    "evidence": {
      "bands": ["REST-01"],
      "groups": ["REST-07", "design"],
      "suspect_exclusion": ["design"],
      "notes": ["REST-01", "REST-02", "REST-04", "REST-05", "REST-06", "REST-07", "REST-08"],
      "option_short_rest": ["REST-01", "REST-04"]
    },
    "groups": {
      "compound": {"median_seconds": 56.0, "rest_count": 3, "band": "short"},
      "isolation": {"median_seconds": 65.0, "rest_count": 3, "band": "intermediate"},
      "unclassified": {"median_seconds": null, "rest_count": 0, "band": null}
    },
    "excluded": {"label_change_or_unknown": 2, "unchecked": 1, "suspect_set": 1, "missing_duration": 1},
    "exercises": [
      {"exercise_category": "BENCH_PRESS", "exercise_name": null, "group": "compound",
       "median_seconds": 53.0, "rest_count": 2, "band": "short"}
    ],
    "options": [{"group": "compound", "code": "rest_longer_or_match_volume_load"}]
  }
```

- `band`: `"short"` / `"intermediate"` / `"long"` / `"very_long"` / `null`(값 없음). 구간 경계는 아래 규칙 4.
- `json.dumps(..., indent=2, ensure_ascii=True)`, 사람이 만든 payload(`dataclasses.asdict` 금지).

## 규칙

1. **비교 기준은 기록된 휴식이다(v1).** 값은 REST row의 `duration_seconds`를 `round(× 1000)` ms로 쓴다. 심박 추정 휴식
   (`estimated_rest_ms`)은 쓰지 않는다. 이유: 추정은 `[design]` 상수(1.0 s/rep, 10 bpm, 10 s 공백, 보정 세트 3·5개)에 기대고
   신뢰도가 최고 medium이다(HR-02). 근거 줄 옆에 놓는 값은 근거 없는 상수에 기대지 않아야 한다.
   - **REST-01 메모와의 관계(게이트 1 결정 D1-A, 2026-11-01)**: 초안 때의 REST-01 메모("보정된 휴식이 있을 때만 판정한다")는
     2026-11-01 승인된 근거 수정(P1)으로 바뀌었다. 지금 메모는 조언만, 90 s를 이득이 멈추는 값으로 쓰지 않음, 판정·자동 규칙에
     쓰지 않음이다. 이 스펙은 판정을 하지 않고(구간 위치와 선택지만), 보정값 대신 **늦게 누른 흔적이 없는 세트 앞의
     기록값**만 쓴다. set-timing 문서 Known issues의 "기록된 휴식만 쓰거나"를 고른 것이고, 사용자가 D1-A로 정했다.
2. **세는 곳**: 활동마다 canonical `sequence` 순서에서 연속한 `(before, rest, after)`가 `ACTIVE, REST, ACTIVE`인 곳. 다음
   순서로 처음 해당하는 이유 하나로 제외하고 센다(기존 `rest_between_sets`와 같은 순서, 이유 하나만 다름):
   1. 앞이나 뒤 label이 UNKNOWN이거나 둘이 다르다 → `label_change_or_unknown`(superset·circuit은 여기로 빠진다).
   2. 뒤 세트가 확인 대상이 아니다(`reps` 없음/0, 시간 없음) → `unchecked`.
   3. 뒤 세트가 의심 세트다(`duration_ms < reps × 1000`, 추정됐든 아니든) → `suspect_set`. 기록된 REST에 운동이 섞였을 수
      있다. 기준 1.0 s/rep은 `[design]`이다.
   4. REST `duration`이 없다 → `missing_duration`.
   - 남은 것만 값이 된다. 결측은 0이 아니다. 값이 하나도 없는 그룹은 `median_seconds: null`, `band: null`.
3. **그룹**: 뒤 세트 label의 taxonomy rule이 없으면 unclassified, `movement_pattern`이 `COMPOUND_PATTERNS`이면 compound,
   그 밖은 isolation. 기존 그룹과 같다(REST-07 + `[design]`). `COMPOUND_PATTERNS`(밀기·당기기·스쿼트·힌지·런지)를 ACSM
   2009의 "core exercise(squat, bench press 같은 고중량 핵심 종목)"와 같다고 보는 것은 `[design]`이다. 그래서 REST-07 줄은
   "heavy core lifts such as squat and bench"라고 원문 표현으로만 쓰고 "compound = 2-3 min"이라고 쓰지 않는다.
4. **구간(REST-01, Singer 2024의 분석 범주를 그대로)**: 중앙값 `m`(ms)에 대해 short `m ≤ 60000`, intermediate
   `60000 < m < 120000`, long `120000 ≤ m < 180000`, very_long `m ≥ 180000`. text 표기는 `short <= 60 s`, `60-120 s`,
   `120-180 s`, `>= 180 s`. **90 s는 경계로 쓰지 않는다**(Singer의 범주가 아니고 저자들도 > 90 s의 추가 이득을 "equivocal"이라
   했다).
5. **중앙값**: `statistics.median`(ms 정수 목록), 출력은 `/ 1000` 초. 표본 수 하한은 두지 않는다(하한은 근거 없는 상수가
   된다). 대신 개수를 늘 함께 쓴다.
6. **문장 규칙**(조언이 규칙처럼 읽히지 않게):
   - 근거 줄 7개는 고정 문장이다. 중앙값에 따라 바뀌는 것은 구간 이름과 `option` 줄뿐이다.
   - `option` 줄은 그룹 중앙값이 short 구간일 때만 나오고, **늘 두 선택지를 함께, 순위 없이** 쓴다: 더 쉬기
     (REST-01) / 짧게 쉬면서 volume load(sets x reps x load) 맞추기(REST-04). 모든 그룹에 같은 문장이고 한쪽만 쓰지 않는다.
     REST-02는 그룹별 선택지에 붙이지 않는다(1분 vs 3분 전신 루틴 비교라 종목 종류별 근거가 아님). 고정 근거 줄에만 있다.
     "세트를 더한다"고 쓰지 않는다(Longo 2022 초록은 volume load를 맞췄다고만 하고 방법을 적지 않았다).
     근거상 방향이 엇갈린다(REST-08은 휴식 처방이 없고, 근력은 1분 기준으로 차이 없음).
   - 출력에 쓰지 않는 말(대소문자 무시): `enough`, `sufficient`, `optimal`, `must`, `should`, `too short`, `too long`,
     `stops`, `no benefit`, `ceiling`, `plateau`, `warning`, `recommended rest`. 의심 세트는 `suspect set`으로만 부른다.
   - text의 모든 줄(첫 줄, 그룹 줄, 제외 줄, 근거 줄, 선택지 줄)은 승인된 근거 ID(REST-01..08) 또는 `[design]`을 가진다.
     운동별 줄과 `unavailable` 줄은 위 그룹 줄의 근거를 따른다(aerobic-guide AC8과 같은 정의). REST-09(고령자)와 TEMPO-01은
     2026-11-01 승인됐지만 출력에 쓰지 않는다(REST-09는 > 65세 근거라 나이 문구를 REST-01 사실로 한정한 이 규칙에 맞지 않고,
     TEMPO-01은 휴식이 아니라 set-timing의 1.0 s/rep 기준에 관한 근거다. 기능 문서 Known issues에만 있다). REST-03도 쓰지 않는다.
   - 나이 문구는 REST-01 원문 사실("REST-01 trials: 8 of 9 in adults 18-35, 1 in > 65; no trained-only analysis", 근거 머리 줄)
     뿐이다. 사용자 나이에 기대는 문장(예: "40-60세 근거 없음")은 출력하지 않는다(사용자 나이는 34세, 사용자 확인
     2026-11-01). 나이별 다른 기준이나 문장은 없다.
7. **보여 주는 조건(게이트 1 결정 D2-A)**: window에 값이 된 휴식이 하나라도 있거나 제외된 휴식이 하나라도 있을 때
   (즉 `ACTIVE, REST, ACTIVE` 세 줄이 하나라도 있을 때) 블록을 보여 준다. 그런 곳이 없으면 text 줄도 JSON key도 없다(기존 출력
   byte-identical).
8. **계산 위치**: 순수 domain 함수(I/O·시계 없음, 정수 ms). Strength Set Timing의 `is_checked`, `is_suspect`,
   `set_duration_ms`, `classify_strength_set`, `COMPOUND_PATTERNS`를 재사용하고, 세트 순서 walk와 그룹 나누기는 set-timing에서
   꺼낸 공개 helper `rest_triples`, `rest_group`을 같이 쓴다(D6-A). **기존 `rest_between_sets`와 그 출력은 바꾸지 않는다**. 이 함수는 `analytics snapshot` 경로에서만 부른다. 심박 RAW(`details.json`)를 읽지 않는다.
   snapshot은 지금처럼 read-only다(`ensure_directories()`/`migrate()`/mkdir 없음).
9. 날짜와 window는 기존 `analytics snapshot`(`--date`, `--days` 1–90, 기본 7)과 같다. 시간대 처리 추가 없음.

### 설계 결정 후보(게이트 1, 2026-11-01: 모두 추천안 A. 아래 "설계 승인 결정")

| ID | 질문 | 추천안 | 대안 |
| --- | --- | --- | --- |
| D1 | 비교 기준 | A. 정상 세트 앞의 기록값만(규칙 1, 2) | B. A + 추정 휴식 중 `confidence: medium`인 것 / C. 기존 `rest_between_sets` 값(기록 + 모든 추정) |
| D2 | 언제 보이나 | A. `ACTIVE, REST, ACTIVE`가 하나라도 있으면(규칙 7) | B. 새 opt-in flag `--rest-advice`일 때만(기존 출력 늘 byte-identical) |
| D3 | 운동별 줄 | A. 넣는다(label별 중앙값과 개수) | B. 그룹 줄만 |
| D4 | 위치 | A. `analytics snapshot`만 | B. A + `recommend` 근력 절 한 줄(golden 변경, Telegram/코치 JSON 영향) |

- D1-B/C를 고르면 추정값은 `[design]` 근거라 "근거 줄 옆의 비교값은 근거 없는 상수에 기대지 않는다"는 원칙과 부딪친다.
  고르면 추정값이 `option` 줄을 켜지 않게 한다(추정값만으로 short 구간이 된 그룹은 option 없음).
- D2-A: 골든 `tests/fixtures/inbody_trend_golden/analytics_snapshot_2026-03-16.json`의 근력 세트는 활동마다 sequence 1–3이
  연속 ACTIVE라 REST row가 없어 보인다(설계자가 확인). REST row가 있는 다른 snapshot 테스트는 출력이 늘어날 수 있다.

## 인수 조건

- [x] AC1: 합성 DB(같은 label `ACTIVE, REST, ACTIVE`가 compound와 isolation에 있음)에서 `analytics snapshot --days 28`이 위
      모양의 `Rest advice` 블록을 Strength 절 끝(taxonomy 줄, 있으면 `Set timing` 블록 뒤)에 출력하고 exit 0이다. 그룹·운동별
      중앙값과 개수가 손으로 계산한 값과 같다.
- [x] AC2: 값은 기록된 REST `duration`뿐이다. 심박으로 추정된 의심 세트가 있는 DB에서 그 세트 앞 REST는 `suspect_set`으로
      세고 값에 들어가지 않으며, 추정이 바뀌어도(심박 RAW를 바꾸거나 지워도) `rest_interval_advice` payload가 byte 단위로 같다.
- [x] AC3: 제외 이유가 규칙 2의 순서로 하나만 붙는다: label 바뀜/UNKNOWN, unchecked, suspect set(정확히 1.0 s/rep는 정상),
      REST 시간 없음. 각 경우 테스트가 있고 개수가 text와 JSON에서 같다. 값이 없는 그룹은 `unavailable (0)` / `null`이다.
- [x] AC4: 구간 경계 테스트: 60000 ms → short, 60001 → intermediate, 119999 → intermediate, 120000 → long, 179999 → long,
      180000 → very_long. 구간 이름·표기와 `band_edges_seconds`에 90이 없다(90 s는 REST-01 근거 줄의 "equivocal" 문장에만 나온다).
- [x] AC5: `option` 줄(JSON `options`)은 그룹 중앙값이 short일 때만 그 그룹에 하나 나오고, 늘 두 선택지(더 쉬기 [REST-01] /
      volume load 맞추기 [REST-04])를 함께 쓴다. 문장은 그룹과 무관하게 같고 REST-02가 붙지 않는다. short 그룹이 없으면 `options: []`이고 text 줄이 없다.
- [x] AC6: 블록의 모든 text 줄이 규칙 6의 정의대로 REST-01..08 중 하나 또는 `[design]`을 가진다. 다른 ID가 없다.
- [x] AC7: 규칙 6의 금지어가 블록 text와 JSON 문자열 어디에도 없다(대소문자 무시, 테스트로 고정).
- [x] AC8: `"advice_only": true`이고 점수, 등급, 경고, 판정 key가 없다. 새 domain 함수는 snapshot 경로에서만 import된다(grep).
      `recommend`(text/JSON, golden 전부), `daily`, `goal *`, `inbody *`, `nutrition *`, Telegram 응답이 byte-identical이다.
- [x] AC9: `ACTIVE, REST, ACTIVE`가 없는 window에서 `analytics snapshot` text와 `--json`이 기능 전과 byte-identical이다(골든
      `analytics_snapshot_2026-03-16.json` 포함). 있으면 text는 블록 줄만 더해지고 JSON은 끝에 `rest_interval_advice` key 하나만
      더해진다. `strength_set_timing`이 있는 경우와 없는 경우 key 위치를 각각 테스트한다. 기존 `Set timing`/`Rest between sets`
      줄과 `strength_set_timing` payload는 그대로다.
- [x] AC10: `--json` 출력이 재실행 시 byte-identical이고 text는 ASCII다. key 순서가 위 예시와 같다.
- [x] AC11: 블록 계산은 심박 RAW를 읽지 않는다(의심 세트 없는 window에서 `details.json` 읽기 0회, 기존과 같음). snapshot은 DB와
      파일에 쓰지 않고 mkdir·migrate를 하지 않는다(임시 `MUSCLE50_HOME` smoke).
- [x] AC12: 기능 문서 `docs/rest-interval-advice.md`에 규칙, 구간과 근거, 금지어, 제외 이유, 설계 결정, Known issues, 아래
      "근거 확인 결과" 요약이 있다. 코드 상수 옆에 근거 ID 또는 `[design]` 주석이 있다.
- [x] AC13: 품질 게이트 4개가 통과한다: `uv run --extra dev pytest`, `uv run ruff check .`, `uv run mypy src tests`,
      `git diff --check`.

AC8의 `daily`와 Telegram 항목은 구조로 확인했다: 새 모듈은 `analytics snapshot` 경로에서만 import되고(grep 테스트),
`recommend` text/JSON은 smoke에서 main과 byte-identical이며, `daily`와 Telegram은 그 `recommend` 출력을 읽는다.

## 설계 승인 결정 (2026-11-01)

사용자 답: 모두 추천안(D1-D6). 상세: `docs/rest-interval-advice.md` "설계 결정".

- **D1-A**: 비교값은 확인된 정상 세트 앞의 기록된 REST `duration`뿐이다. 심박 추정값은 쓰지 않는다(AC2).
- **D2-A**: 새 flag 없이, window에 `ACTIVE, REST, ACTIVE`가 하나라도 있으면 블록과 JSON key가 나온다. 대가로
  `tests/test_strength_set_timing_cli.py`의 계약 테스트 3개와 `docs/strength-set-timing.md` "바뀌지 않는 출력" 한 문장을 고쳤다.
- **D3-A**: 운동별 줄을 넣는다(센 휴식이 하나 이상인 label만).
- **D4-A**: `analytics snapshot`만. `recommend`, `daily`, Telegram, 코치 입력은 그대로다.
- **D5-A**: 선택지 줄은 중앙값이 short 구간(<= 60 s)인 그룹에만, 두 선택지를 늘 함께 순위 없이 쓴다(AC5).
- **D6-A**: `domain/strength_set_timing.py`에서 공개 helper `rest_triples`, `rest_group`(그리고 `RestGroupName`)을 꺼내고
  `rest_between_sets`가 그것을 쓴다. 동작은 같고 기존 테스트는 고치지 않았다.

### 계획이 고친 스펙 내용(위 본문에 반영함)

- JSON 선택지 코드 `short_rest_longer_or_more_sets`는 "세트를 더한다" 금지(규칙 6)와 부딪쳐 `rest_longer_or_match_volume_load`가 됐다.
- 초안 예시의 label(`PULL_UP/WIDE_GRIP_PULL_UP`, `BENCH_PRESS/BARBELL_BENCH_PRESS`, `CURL/DUMBBELL_BICEPS_CURL`)은 taxonomy rule이
  없어 unclassified다. 예시는 rule이 있는 label(`BENCH_PRESS/-`, `SQUAT/BARBELL_BACK_SQUAT`, `CURL/-`)로 바꿨다.
- 근거 줄은 REST ID마다 한 줄이다(REST-04와 REST-06도 따로, 범위 4). `evidence.notes`는 출력 순서(01, 02, 04, 05, 06, 07, 08)다.
- 제외 줄과 JSON `excluded`는 규칙 2의 순서(label, unchecked, suspect, missing)다.
- 머리 줄은 "same Garmin exercise label; rests before a set under 1.0 s/rep are excluded"로, 근거 머리 줄은 고정 줄임과 REST-01
  연구 대상 사실을 적는 문장으로 바뀌었다.
- 근거 문구: "young" 삭제, "may suffice"는 "1-2 min"으로(금지어 "sufficient"와 같은 주장), "Smith squat"는 "lower body"로.

## 한계 / 후속 후보

- **근거가 사용자와 다른 조건에서 나왔다.** Singer 2024의 9편 중 8편이 18–35세, 1편이 > 65세이고, 훈련자만 따로 본 분석은
  자료가 모자라 하지 못했다(REST-01 원문). 40–60세 훈련자 연구는 찾지 못했다. 65세 이상 연구는 방향이 엇갈린다(근거 확인 결과).
- **cut 중의 근거가 아니다.** 휴식 연구는 에너지 결핍을 다루지 않았다(확인하지 않음). 사용자는 2026-10-26부터 cut 모드다.
- **기록값도 틀릴 수 있다.** 세트 끝에서 버튼을 늦게 누르면 휴식이 ACTIVE에 묻혀 기록된 REST가 실제보다 짧고, 시작에서 두 번
  누르는 패턴(set-timing D2)은 운동이 뒤 REST에 들어간다. 둘 다 1.0 s/rep 검사로 잡히지 않는다. 시계 일시정지나 긴 잡담 휴식도
  그대로 들어간다(상한을 두지 않음, 중앙값이 줄일 뿐).
- **표본이 선택된다.** 의심 세트 앞 휴식을 빼므로 버튼을 자주 늦게 누르는 운동(예: 풀업)은 개수가 작다. 제외 개수를 늘 보여 준다.
  1.0 s/rep은 `[design]`이고, 반복 시간 연구에서 0.5 s 반복도 쓰였으므로(근거 확인 결과) 진짜 빠른 세트가 의심으로 빠질 수 있다.
- **warm-up 세트를 구분하지 못한다.** Garmin 기록에 warm-up 표시가 없다. superset·circuit 휴식은 label이 바뀌어 빠진다.
- **compound/isolation은 taxonomy 매핑이다.** 다관절과 단관절의 장기 근비대 휴식을 직접 비교한 시험은 찾지 못했다(근거 문서 1절
  충돌 메모).
- 기본 7일 window는 표본이 작다. 필요하면 `--days 28`.
- 구현자·검증자가 보고한 한계:
  - **표시 반올림과 구간이 어긋나 보일 수 있다.** 구간은 ms 중앙값으로 정하고 표시는 `{:.0f} s`라, 60.4 s는
    `60 s (band 60-120 s)`로 보이고 선택지 줄이 없다(검증 smoke에서 60.25 s 확인, JSON은 60.25).
  - **선택지 줄은 구간으로 켜진다(D5-A).** 규칙에 가장 가까운 부분이다. 표시 선택일 뿐이고 두 선택지를 늘 함께 쓰지만, 규칙처럼
    읽히면 조건 없이 고정 줄을 쓰는 D5-B로 바꿀 수 있다.
  - **REST-07 줄은 원문 표현 "at least 2-3 min"을 쓴다**(같은 줄에 REST-08이 대체했다고 적음). 처방처럼 읽히면 "2-3 min for heavy
    core lifts"로 줄일 수 있다.
  - **운동별 줄은 센 휴식이 있는 label만 나온다.** 모든 휴식이 빠진 label(예: 늘 늦게 누르는 운동)은 window 전체 제외 개수에만 보인다.
  - 기존 `Rest between sets` 줄(추정값 포함, 의심 세트 앞 REST는 `not estimated`)과 이 블록(기록값만, 그 REST는 `suspect set`)은
    같은 window에서 중앙값과 제외 개수가 다를 수 있다.
  - **중간 commit 하나가 mypy에서 실패한다(bisect 주의).** `91fa370`(feat: add the Rest advice block to analytics snapshot)만 꺼내면
    `tests/test_rest_interval_advice_cli.py`에 테스트 전용 arg-type 오류 12개가 있고, 바로 다음 `2b85bad`(fix: type the PULL_UP
    label kwargs ...)가 한 줄로 고친다. 실행 동작 차이는 없다. squash와 history 재작성 금지 규칙 때문에 그대로 두었다. bisect가 이
    commit에 서면 `git bisect skip`한다.
- 후속 후보:
  - `recommend` 근력 절의 한 줄(D4-B). golden과 Telegram/코치 영향을 따로 설계한다.
  - 사용자가 정한 목표 휴식 범위(`[design: user setting]`)와 나란히 보여 주기.
  - 1.0 s/rep 기준을 반복 시간 근거(TEMPO-01, 2026-11-01 승인)로 다시 보거나 사용자 설정으로 바꾸기(set-timing 쪽 기능).
  - REST-09(고령자)와 TEMPO-01은 2026-11-01 승인됐고 v1은 출력에 쓰지 않기로 했다(규칙 6). 사용자 조건이 바뀌면 나이 문구와
    근거 줄을 다시 본다.

## 근거 확인 결과

2026-11-01, 원문 확인(Europe PMC REST API로 초록·PMC 본문, ACSM 2009는 대학 강의 사이트에 올라온 PDF 사본). 표기:
`verified (full text)` 본문에서 숫자 확인 / `verified (abstract)` 초록에서 확인 / `verified (PDF copy)` 제3자 사이트 PDF로 확인 /
`unverified` 확인 못 함 / `design` 근거 없는 설계 값 / `refuted` 원문이 그 주장을 뒷받침하지 않음. 수정·추가 제안
(`docs/evidence/proposals/rest-interval-advice-evidence.md`)은 사용자가 2026-11-01 승인했고 근거 문서에 반영했다(REST-01·02·04·07·08
수정, REST-09, TEMPO-01 추가). 제안 파일은 반영 뒤 지웠다.

### 1. 반복 시간 "약 0.5–8 s"(1.0 s/rep 기준과의 관계)

| 주장 | 판정 | 출처와 원문 수치 |
| --- | --- | --- |
| 메타분석이 반복 시간 0.5–8 s에서 근비대가 비슷하다고 했다 | verified (abstract) | Schoenfeld BJ, Ogborn DI, Krieger JW. 2015. *Sports Med* 45(4):577-585. doi:10.1007/s40279-015-0304-0, PMID 25601394. "hypertrophic outcomes are similar when training with repetition durations ranging from 0.5 to 8 s". 8편, 실패 지점까지 한 훈련만 포함 |
| 여기서 "반복 시간"은 한 반복 전체(단축+신장+등척)다 | verified (abstract) | 같은 초록: "Duration amounts to the sum total of the concentric, eccentric, and isometric components of a repetition" |
| 아주 느린 반복(> 10 s)은 근비대에 불리해 보인다 | verified (abstract) | 같은 초록: "volitionally very slow durations (>10s per repetition) is inferior", 단 "lack of controlled studies" |
| 0.5 s가 어느 포함 연구의 것이고 처방값인지 측정값인지 | unverified | 본문 유료(Springer 로그인 요구). 포함 연구 목록 확인 못 함 |
| ACSM 2026도 빠른(0.5 s) vs 느린(8 s) 반복이 근비대에 영향 없다고 정리 | verified (full text) | Currier 2026(REST-08 출처) 본문: "fast (0.5 s) versus slow (8 s) repetitions" |
| 스스로 고른 속도의 실측 s/rep | verified (full text) | Chaves TS, et al. 2020. *PeerJ* 8:e8697. doi:10.7717/peerj.8697. 비훈련 남성 레그 익스텐션, 세트 시간(스톱워치) ÷ 반복 수(muscle50과 같은 계산): SELF 1.8 ± 0.3 s, SELF-EV 1.7 ± 0.4 s, 통제 4.0 s |
| ACSM 2009의 속도 권고 | verified (PDF copy) | 중급 이상 "moderate contraction velocity (1-2 s CON; 1-2 s ECC)", 빠른 속도 예 "fast (1:1)" |
| 1.0 s/rep이 "불가능한" 최소값이라는 근거 | refuted(근거 없음) | 위 연구들은 0.5 s 전체 반복도 훈련 프로토콜에 있었음을 보인다. 생리적 최소 반복 시간을 정한 연구는 찾지 못했다. 1.0 s/rep은 `design` 그대로이고, 진짜 빠른 세트가 의심으로 잡힐 수 있다 |

### 2. REST-01..08 재확인(조언이 출력할 숫자)

| ID / 주장 | 판정 | 원문 수치와 메모 |
| --- | --- | --- |
| REST-01: > 60 s에서 작은 근비대 이득 | verified (full text) | Singer 2024, PMID 39205815, PMC11349676. "a small hypertrophic benefit to employing inter-set rest interval durations >60 s". 대조 SMD 팔 0.13 [−0.27, 0.51], 허벅지 0.17 [−0.13, 0.43], 전신 −0.08 [−0.45, 0.29](모두 0 포함) |
| REST-01: 분석 구간 | verified (full text) | short ≤ 60 s, intermediate 60 < d < 120 s, long 120 ≤ d < 180 s, very long ≥ 180 s(이 스펙의 band) |
| REST-01: "> 90 s부터 차이를 찾지 못했다" | verified (full text), 단 해석 주의 | 초록 "did not detect appreciable differences in hypertrophy when resting >90 s"; 결론 "The current evidence remains equivocal as to whether resting more than 90 s ... further enhances". 90 s는 분석 구간이 아니다. network 추정(short 대비) 허벅지 very long 0.32 [−0.10, 0.68] |
| REST-01 메모 "'충분' 기준 90초", "결정적 규칙 가능" | refuted(과장) | 저자는 "equivocal"이라 했고 이득이 90 s에서 멈춘다고 하지 않았다. 이 스펙은 90 s를 쓰지 않는다. 제안 문서 P1(2026-11-01 승인·반영) |
| REST-01: 훈련자·나이 | verified (full text) | "Insufficient data were available to subanalyze results in trained individuals". 9편 중 8편 18–35세, 1편 > 65세(Villanueva 2015) |
| REST-02: 3분 > 1분(훈련자) | verified (abstract) | Schoenfeld 2016, PMID 26605807. 젊은 훈련자 남성 21명, 1분 vs 3분, 8주, 주 3회 전신 7종목 3세트 8–12RM. 3분 군이 스쿼트·벤치 1RM, 대퇴 전면 근두께에서 유의하게 큼, 삼두 경향 p = 0.06. 효과 크기·최종 분석 수는 이번에도 다시 읽지 않음(unverified, 근거 문서 확인 못 함 3) |
| 과제 예시 "compound 종목은 근비대에 ≥ 2분이 유리 [REST-xx]" | refuted | 어느 REST 행도 이것을 보이지 않는다. Schoenfeld 2016은 1분 vs 3분 비교이고 루틴에 단관절(레그 익스텐션 등)이 섞였다. ACSM 2009의 2–3분은 고중량 핵심 종목(근력 B, 근비대 상급 C)이고 2026 판이 대체했다. 출력에서는 규칙 6의 고정 문장으로 바꿨다 |
| REST-03: 훈련자 근력 > 2분, 비훈련자 60–120 s | verified (abstract) | Grgic 2018, PMID 28933024. 23편 491명 |
| REST-01 이전 SR(Grgic 2017) | verified (abstract) | PMID 28641044. 6편. 훈련자 민감 측정에서 긴 휴식 "possible advantage" |
| REST-04: volume load가 근비대를 결정 | verified (abstract) | Longo 2022, PMID 35622106. QCSA 13.1 % / 12.9 % vs 6.8 % / 6.6 %, 1RM 26.5–31.2 % 차이 없음. 참가자는 비훈련 남녀(Singer 표) |
| REST-05: 1분 vs 2–3분, 2 vs 3분 사소 | verified (abstract) | Rosa 2023, PMID 37347940. "trivial differences in repetition performance between 2 and 3 minutes rest for both the BS and LE". Hernandez 2021(PMID 32108720): 훈련자 15명, 85 % 1RM 벤치 4세트, 8분만 반복 유지. Yamazaki 2025는 이번에 다시 읽지 않음 |
| REST-06: 자율 vs 고정 75 s | verified (abstract) | Simão 2022, PMID 32826830. 체스트 프레스 26.1 vs 21.5회, 근력 6.8 % vs 7.4 %, 고정이 37 % 시간 효율 |
| REST-07: ACSM 2009 | verified (PDF copy) | 근력: "rest periods of at least 2-3 min be used for core exercises using heavier loads (... such as the squat and bench press)"(category B), 보조 종목 "1-2 min may suffice"(C). 근비대: "1- to 2-min rest periods ... novice and intermediate"; 상급 "2- to 3-min ... heavy loading for core exercises and 1-2 min ... other exercises"(C). PMID 19204579 |
| REST-08: ACSM 2026 | verified (full text) | PMID 41843416, PMC12965823. 표 4 inter-set rest: 근력 "✖ 2 reviews; n = 982 QoE = 63%", 근비대 "? 4 reviews; n = 265 QoE = 44%". 본문의 "2–3 min rest between sets"는 **이전 지침을 요약한 문장**이고 2026 권고가 아니다 |

### 3. 40–50대 훈련자의 휴식

| 주장 | 판정 | 출처와 원문 수치 |
| --- | --- | --- |
| 40–60세 훈련자에서 휴식 길이를 비교한 장기 시험 | unverified(찾지 못함) | Europe PMC 제목 검색과 웹 검색에서 찾지 못했다 |
| ACSM 2026은 나이로 나누지 않았다 | verified (full text) | "not separated by participant age ... younger and older than the cutoff of 55-yr old. Thus, our recommendations are evidence-based across all ages" |
| 고령 남성(65.6 / 70.3세)에서 60 s가 4분보다 제지방·근력 증가가 컸다 | verified (abstract), REST-09(2026-11-01 승인) | Villanueva MG, Lane CJ, Schroeder ET. 2015. *Eur J Appl Physiol* 115(2):295-308. doi:10.1007/s00421-014-3014-7. n = 22, 4주 근비대 훈련 뒤 8주 근력 훈련(Singer 표: 4–6회). LBM p = 0.001, 벤치·레그프레스 1RM p < 0.001. 두 군 평균 나이가 4.7세 다르다 |
| 훈련된 고령 여성(66.4세)에서 1분 vs 3분 차이 없음 | verified (abstract), REST-09(2026-11-01 승인) | Jambassi Filho JC, et al. 2017. *Am J Phys Med Rehabil* 96(9):627-633. doi:10.1097/PHM.0000000000000701. n = 21, 레그프레스 3×15, 8주. 집단 간 차이 없음(15RM 증가는 3분 군만 유의, 3.6 %) |
| 급성: 고령 남성은 2분 휴식으로 최대 토크가 회복, 젊은 남성은 아님 | verified (abstract), REST-09(2026-11-01 승인) | Bottaro M, et al. 2010. *Int J Sports Med* 31(1):22-25. doi:10.1055/s-0029-1239497. 비훈련, 등속성 무릎 신전 |
| 급성: 훈련된 고령 여성은 3분이 1분보다 총 볼륨 29.4 % 많음 | verified (abstract), REST-09(2026-11-01 승인) | Jambassi Filho JC, et al. 2013. *J Sports Sci Med* 12(1):138-143. PMID 24149737 |
| ACSM 2009 고령자 1–3분 | verified (PDF copy), 해석 주의 | "1-3 min of rest in between sets"는 category A 권고 묶음(운동 종류, 속도, 1–3세트, 60–80 % 1RM, 8–12회, 주 2–3회)의 일부다. 휴식 하나만의 근거 등급이 아니다. "older adults"의 나이 정의는 확인 못 함 |
| 결론 | unverified | 사용자 나이는 34세다(사용자 확인 2026-11-01). Singer 2024의 9편 중 8편이 18–35세라 나이 범위는 사용자를 포함하지만, 훈련자만 따로 본 분석은 없다. 40–60세 훈련자 장기 시험은 찾지 못했다. 고령자 자료는 "길수록 좋다"를 지지하지 않는다(Villanueva는 반대 방향). 그래서 출력은 나이 문구 하나만 쓰고 선택지는 늘 두 방향을 함께 쓴다 |

### 4. 이 스펙의 설계 값

| 값 | 판정 |
| --- | --- |
| 정상 세트 앞의 기록값만 쓴다(D1-A) | design(근거 없음, 추정의 `[design]` 의존을 피하려는 선택) |
| 의심 세트 제외 기준 1.0 s/rep | design(set-timing 상수 재사용) |
| compound/isolation = `COMPOUND_PATTERNS` | REST-07 + design |
| 구간 경계 60 / 120 / 180 s | REST-01(Singer 분석 범주, 효과의 문턱이 아님) |
| option 줄의 조건(short 구간) | REST-01 경계 + design(문장 조건) |
| 표본 수 하한 없음, 휴식 상한 없음 | design(근거 없는 상수를 만들지 않으려는 선택) |
