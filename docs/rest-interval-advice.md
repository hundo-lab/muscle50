# Rest Interval Advice v1: 같은 운동의 세트 사이 휴식(기록값)과 근거

`analytics snapshot`의 Strength 절 끝에 **같은 운동의 세트 사이 휴식**(기록된 REST 시간의 중앙값)을 그룹별(compound /
isolation / unclassified)과 운동별로 보여 주고, 승인된 휴식 근거(REST-01, 02, 04-08)를 고정 문장으로 옆에 적는다.
spec: `docs/specs/rest-interval-advice.md`. 근거: `docs/evidence/training-nutrition-evidence.md` 1절(2026-11-01 승인 행).

- **조언만**: 어떤 규칙도 이 값을 쓰지 않는다. 추천(`recommend`), 세트 수, 무게 진행, 회복 판단, Telegram 응답, 코치 LLM
  입력에 들어가지 않는다. 점수, 경고 등급, "부족/충분" 판정, 선택지 순위가 없다. 출력에 `advice only; used by no rule`(text),
  `"advice_only": true`(JSON)로 적는다.
- **기록값만**: 비교하는 값은 REST row의 `duration`뿐이고, 뒤 세트가 확인된 정상 세트일 때만 센다. 심박 추정 휴식은 쓰지
  않는다(설계 결정 D1-A). 추정은 `[design]` 상수에 기대고 신뢰도가 최고 medium이라, 근거 줄 옆에 놓지 않는다.
- **읽을 때 계산**: 저장하지 않는다. migration, 파생 table, 새 파일이 없다. snapshot은 지금처럼 read-only다.
- 근거 ID는 근거 문서의 것이고, `[design]`은 근거가 주지 않는 설계 값이다.

Non-goals: `recommend` 근력 절의 휴식 줄(후속 후보, D4-B), 목표 휴식 시간 설정, 세션 중 타이머, 운동별 휴식 처방, 나이나
목표 모드에 따른 다른 기준, 1.0 s/rep 기준 변경(set-timing의 상수), Garmin 동기화 변경, 심박 RAW 읽기, LLM.

## 명령

명령과 flag는 그대로다. 새 flag 없음, exit code 그대로(0 ok, 1 알려진 오류 `오류: ...`, 2 argparse, 130 Ctrl+C).
기본 window는 7일이라 표본이 작다. `--days 28`을 쓰면 4주를 본다.

```powershell
uv run muscle50 analytics snapshot --date 2026-03-14 --days 28
uv run muscle50 analytics snapshot --date 2026-03-14 --days 28 --json
```

### Text(합성 값)

taxonomy 줄과 (있으면) `Set timing` 블록 뒤, `Swimming:` 절 앞에 붙는다. 아래는 `tests/test_rest_interval_advice.py`의
`happy_rows()`(BENCH_PRESS 50·56 s, SQUAT 100 s, CURL 75·65·40 s, 제외 이유 하나씩)를 임시 `MUSCLE50_HOME`에 넣고 돌린
출력이다.

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

- 줄 순서는 고정이다: 머리 줄, 그룹 3줄(compound, isolation, unclassified), 제외 줄, 운동별 줄, 근거 머리 줄, 근거 7줄,
  선택지 줄(short 그룹마다 하나, 없으면 없음).
- 휴식 값은 `{:.0f} s`. 값이 없는 그룹은 `unavailable (0)`이고 0 s가 아니다. 개수는 늘 `from N rests`(고정 template이라
  `1 rests`도 그대로 쓴다).
- 운동별 줄은 센 휴식이 하나 이상인 label만, group 순서(compound, isolation, unclassified) 다음 `(category, name)` 사전순이다.
  label 표기는 set-timing과 같다(`CATEGORY/NAME`, 이름 없으면 `-`).
- ASCII만 쓴다. Garmin label은 이미 ASCII다.
- 같은 window의 기존 `Rest between sets` 줄(set-timing)은 그대로다. 그 줄은 추정값을 섞고 의심 세트 앞 REST를
  `not estimated`로 세지만, 이 블록은 기록값만 쓰고 그 REST를 `suspect set`으로 센다. 그래서 두 줄의 중앙값과 제외 개수가
  다를 수 있다(위 예: 기존 줄 median 60 s from 6 rests).

### `--json`(합성 값)

top-level 마지막 key `rest_interval_advice`다. `strength_set_timing`이 있으면 그 뒤, 없으면 `quality_issues` 뒤에 온다. 앞의
key는 byte 단위로 같다. `json.dumps(..., indent=2, ensure_ascii=True)`, 사람이 만든 payload(`dataclasses.asdict` 아님),
key 순서 고정. 아래는 위 text와 같은 데이터다(`exercises`는 첫 항목만 보임).

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

- `band`: `"short"` / `"intermediate"` / `"long"` / `"very_long"` / `null`(값 없음).
- `evidence.notes`는 text 근거 줄의 순서와 같다.
- `options`: short 그룹마다 하나, 그룹 순서. 코드는 모든 그룹에 같다. 없으면 `[]`.

## 구조

| 층 | 파일 | 역할 |
| --- | --- | --- |
| domain | `src/muscle50/domain/rest_interval_advice.py` | 상수(근거 주석), `RestBand`, dataclass, 순수 함수 `rest_band`, `summarize_rest_intervals`. I/O·시계 없음, 정수 ms |
| domain | `src/muscle50/domain/strength_set_timing.py` | D6-A로 꺼낸 공개 helper `rest_triples(activity)`, `rest_group(before, after)`, `RestGroupName`. 기존 `rest_between_sets`가 같은 helper를 부르고 동작은 그대로다 |
| application | `src/muscle50/application/strength_set_timing.py` | `BuildSnapshotWithSetTiming`이 이미 읽은 `sessions`로 `summarize_rest_intervals`를 부른다. `SnapshotWithSetTiming.rest_advice`(없으면 None). DB·RAW를 더 읽지 않는다 |
| presentation | `src/muscle50/presentation/rest_advice_terminal.py` | 고정 문장 상수, `rest_advice_lines`, `rest_advice_payload` |
| presentation | `src/muscle50/presentation/terminal.py` | `render_training_snapshot(_json)`에 keyword `rest_advice=None`. 둘 다 None이면 기존 호출 그대로 |
| cli | `src/muscle50/cli.py` | `_analytics_snapshot`에서 `rest_advice=result.rest_advice`를 넘기는 것뿐. parser 변경 없음 |

## 규칙

1. **세는 곳**: window 안 근력 활동마다 canonical `sequence` 순서에서 연속한 `(before, rest, after)`가 `ACTIVE, REST, ACTIVE`인
   곳(`rest_triples`). 활동 경계를 넘지 않는다.
2. **제외(처음 해당하는 이유 하나)**, 이 순서로:
   1. 앞이나 뒤 label이 UNKNOWN이거나(category 없음 포함, taxonomy와 같은 판정) 둘의 `(category, name)`이 다르다 →
      `label_change_or_unknown`. superset·circuit은 여기로 빠진다.
   2. 뒤 세트가 확인 대상이 아니다(`reps` 없음 또는 0, 시간 없음) → `unchecked`.
   3. 뒤 세트가 의심 세트다(`duration_ms < reps x 1000`, 추정됐든 아니든) → `suspect_set`. 기록된 REST에 운동이 섞였을 수 있다.
      정확히 1.0 s/rep는 정상이다. 기준은 set-timing의 `MIN_MILLISECONDS_PER_REP`(`[design]`)를 그대로 쓴다.
   4. REST `duration`이 없다 → `missing_duration`.
   - 남은 것만 값(REST `duration`의 `round(x 1000)` ms)이 된다. 결측은 0이 아니다.
3. **그룹**: 뒤 세트 label의 taxonomy rule이 없으면 unclassified, `movement_pattern`이 `COMPOUND_PATTERNS`이면 compound,
   그 밖은 isolation(`rest_group`, 기존 `Rest between sets`와 같음, REST-07 + `[design]`). `COMPOUND_PATTERNS`(밀기·당기기·
   스쿼트·힌지·런지)를 ACSM 2009의 "core exercise"와 같다고 보는 것은 `[design]`이다. 그래서 REST-07 줄은 원문 표현("heavy
   core lifts such as squat and bench")만 쓰고 "compound = 2-3 min"이라고 쓰지 않는다.
4. **중앙값**: `statistics.median`(ms 정수 목록), 출력은 `/ 1000` 초. 표본 수 하한과 휴식 상한은 두지 않는다(근거 없는 상수가
   된다). 대신 개수를 늘 함께 쓴다.
5. **보여 주는 조건(D2-A)**: window에 triple이 하나라도 있으면(센 것이든 제외된 것이든) 블록과 key가 나온다. 모두 제외되면
   그룹은 `unavailable (0)` / `null`, 운동별 줄과 선택지는 없고 제외 개수만 보인다. triple이 없으면 text 줄도 JSON key도 없다
   (기존 출력과 byte 단위로 같음).
6. 계산은 snapshot 경로에서만 한다. 새 모듈은 `application/strength_set_timing.py`, `presentation/terminal.py`,
   `presentation/rest_advice_terminal.py`만 import한다(테스트로 고정). 심박 RAW(`details.json`)를 읽지 않는다.

## 구간(band)과 근거

| 상수 | 값 | 근거 |
| --- | --- | --- |
| `SHORT_MAX_MS` / `LONG_MIN_MS` / `VERY_LONG_MIN_MS` | 60000 / 120000 / 180000 ms | REST-01: Singer 2024의 분석 범주 그대로. short `m <= 60000`, intermediate `60000 < m < 120000`, long `120000 <= m < 180000`, very_long `m >= 180000`. 위치 표시이고 효과의 문턱이 아니다 |
| 90 s | 경계 아님 | Singer의 범주가 아니고, 저자들은 > 90 s의 추가 이득을 "equivocal"이라 했다. 90은 REST-01 근거 줄의 "equivocal" 문장에만 나온다 |
| 그룹 나누기 | `REST_GROUP_EVIDENCE` 재사용 | REST-07 + `[design]` |
| 의심 세트 제외 | `SUSPECT_EVIDENCE` 재사용, 1.0 s/rep | `[design]`(set-timing 상수) |
| 근거 줄 | `NOTE_EVIDENCE` | REST-01, 02, 04, 05, 06, 07, 08 한 줄씩. REST-03(근력 저반복 세트, 다른 목표), REST-09(> 65세), TEMPO-01(반복 시간)은 출력하지 않는다 |
| 선택지 줄 | `OPTION_EVIDENCE`, `OPTION_CODE` | REST-01(더 쉬기) + REST-04(짧게 쉬면서 volume load 맞추기). 조건(short 구간)은 REST-01 경계 + `[design]`(문장 조건) |

근거 줄은 승인된 행(2026-11-01)에서 옮겼다. 행에 있지만 일부러 뺀 표현:
- REST-02 적용 메모의 "젊은 훈련자": spec 규칙 6은 나이 문구를 REST-01의 연구 대상 사실 하나로만 둔다.
- REST-04 적용 메모의 "세트가 더 필요하다": spec 규칙 6은 "세트를 더한다"고 쓰지 않는다(Longo 2022 초록은 volume load를
  맞췄다고만 하고 방법을 적지 않았다). 그래서 선택지는 "match volume load (sets x reps x load)"다.

## 문장 규칙

- 근거 줄은 고정 문장이다. 중앙값에 따라 바뀌는 것은 구간 이름과 선택지 줄뿐이다.
- 선택지 줄은 short 그룹에만 나오고, 늘 두 선택지를 함께, 순위 없이(`no ranking`) 같은 문장으로 쓴다. REST-02는 붙이지 않는다
  (1분 vs 3분 전신 루틴 비교라 종목 종류별 근거가 아님).
- 출력에 쓰지 않는 말(대소문자 무시, 단어 경계, `_`는 공백으로 보고 검사): `enough`, `sufficient`, `optimal`, `must`, `should`,
  `too short`, `too long`, `stops`, `no benefit`, `ceiling`, `plateau`, `warning`, `recommended rest`. 의심 세트는 `suspect set`으로만
  부른다. 단어 경계 때문에 `SHOULDER_PRESS` label은 `should`에 걸리지 않는다. text 블록, JSON의 모든 key와 문자열, 상수를 검사한다.
- text의 모든 줄(머리 줄, 그룹 줄, 제외 줄, 근거 줄, 선택지 줄)은 REST-01..08 중 하나 또는 `design`을 가진다. 운동별 줄과
  `unavailable` 줄은 위 그룹 줄의 근거를 따른다. 승인되지 않았거나 쓰지 않기로 한 ID(REST-09, TEMPO-01)는 나오지 않는다.
- 나이 문구는 REST-01의 연구 대상 사실("8 of 9 in adults 18-35, 1 in > 65; no trained-only analysis")뿐이다. 사용자 나이(34세,
  사용자 확인 2026-11-01)에 기대는 문장은 없고, 나이별 다른 기준도 없다.

## 설계 결정(게이트 1, 2026-11-01 사용자 승인: 모두 추천안)

| ID | 결정 | 이유 |
| --- | --- | --- |
| D1-A | 정상 세트 앞의 기록값만 | 추정은 `[design]` 상수에 기대고 신뢰도 최고 medium. 심박이 바뀌어도 payload가 같다(AC2) |
| D2-A | triple이 하나라도 있으면 자동으로 보임 | 따로 flag를 기억할 필요가 없다. 소비자는 CLI를 읽는 사람뿐이다. 대가로 `tests/test_strength_set_timing_cli.py`의 계약 테스트 3개와 `docs/strength-set-timing.md` "바뀌지 않는 출력"의 한 문장을 고쳤다 |
| D3-A | 운동별 줄 넣음 | AC1의 운동별 중앙값 |
| D4-A | `analytics snapshot`만 | `recommend` golden, Telegram `/daily`, 코치 JSON이 그대로다 |
| D5-A | 선택지 줄은 short 그룹에만 | spec AC5. 60 s는 REST-01 범주 경계이고, 60 s 위 값에 대해서는 아무 말도 하지 않는다 |
| D6-A | set-timing에서 공개 helper를 꺼냄 | private 이름에 묶이거나 walk를 복제하지 않는다. 기존 테스트가 동작이 같음을 고정한다 |

계획이 spec 예시를 고친 것(통합 때 spec 본문 반영 대상):
- 선택지 코드 `short_rest_longer_or_more_sets`는 "세트를 더한다" 금지와 부딪쳐 `rest_longer_or_match_volume_load`로 바꿨다.
- spec 예시의 label(`PULL_UP/WIDE_GRIP_PULL_UP`, `BENCH_PRESS/BARBELL_BENCH_PRESS`, `CURL/DUMBBELL_BICEPS_CURL`)은 taxonomy rule이
  없어 compound/isolation이 아니다. 예시는 rule이 있는 label을 쓴다.
- REST-04와 REST-06은 한 줄씩(spec 범위 4), `evidence.notes`는 출력 순서를 따른다.
- 제외 줄과 JSON `excluded`는 규칙 2의 순서(label, unchecked, suspect, missing)다.
- 근거 문구: "young" 삭제, "may suffice"는 "1-2 min"으로(금지어 "sufficient"와 같은 주장), "Smith squat"는 "lower body"로(행에 없음).

## 근거 확인 결과(요약)

spec "근거 확인 결과"(2026-11-01, Europe PMC 초록·본문, ACSM 2009 PDF 사본)의 요약이다. 수정·추가 제안은 사용자가 같은 날
승인했고 근거 문서에 반영됐다.

- REST-01(Singer 2024, 본문): > 60 s의 작은 이득, 대조 SMD는 모두 0을 포함. 분석 범주 short <= 60 / 60-120 / 120-180 / >= 180 s.
  > 90 s의 추가 이득은 "equivocal". 기존 메모의 "'충분' 기준 90초", "결정적 규칙 가능"은 과장이라 고쳤다(P1). 훈련자 하위분석 없음,
  9편 중 8편 18-35세.
- REST-02(Schoenfeld 2016, 초록): 훈련자 남성 21명, 1분 vs 3분, 8주. "compound 종목은 >= 2분" 같은 주장은 어느 행도 뒷받침하지
  않는다(refuted).
- REST-04(Longo 2022, 초록): volume load가 근비대를 결정, 참가자는 비훈련 남녀. REST-05(Rosa 2023, Hernandez 2021, 초록),
  REST-06(Simao 2022, 초록), REST-07(ACSM 2009, PDF 사본), REST-08(ACSM 2026, 본문: 휴식 처방 없음, 나이로 나누지 않음).
- 40-60세 훈련자의 휴식 길이 장기 시험은 찾지 못했다. 고령자 자료(REST-09)는 "길수록 좋다"를 지지하지 않는다. 그래서 출력은
  나이 문구 하나만 쓰고 선택지는 늘 두 방향을 함께 쓴다.
- 반복 시간(TEMPO-01): 0.5-8 s 반복에서 근비대가 비슷했다. 1.0 s/rep이 "불가능한 최소값"이라는 근거는 없다(refuted). 상수는
  `[design]` 그대로다.

## 바뀌지 않는 출력

- `analytics snapshot` text와 `--json`: window에 `ACTIVE, REST, ACTIVE`가 없으면 byte 단위로 같다(골든
  `tests/fixtures/inbody_trend_golden/analytics_snapshot_2026-03-16.json` 포함). 있으면 text는 블록 줄만 더해지고 JSON은 끝에
  key 하나만 더해진다.
- 기존 `Set timing` / `Rest between sets` 줄과 `strength_set_timing` payload.
- 항상 같음: `recommend`(text/JSON, golden 전부), `daily`, `garmin *`, `goal *`, `inbody *`, 모든 `nutrition` 명령, Telegram 응답,
  기존 `analytics snapshot` 거절(잘못된 날짜, `--days`, DB 없음).

## Known issues / limitations

- **근거가 사용자와 다른 조건에서 나왔다.** Singer 2024의 9편 중 8편이 18-35세, 1편이 > 65세이고, 훈련자만 따로 본 분석은
  자료가 모자라 하지 못했다. cut(에너지 결핍) 중 휴식 길이를 비교한 연구는 찾지 않았다. 사용자는 2026-10-26부터 cut 모드다.
- **진짜 빠른 세트가 의심으로 빠질 수 있다(TEMPO-01).** 연구 프로토콜에는 0.5 s 반복도 있었다(Schoenfeld 2015, ACSM 2026의
  "fast (0.5 s)"). 1.0 s/rep 기준은 `[design]`이라 빠르게 하는 정상 세트 앞 휴식이 `suspect set`으로 빠질 수 있다. 기준을
  바꾸거나 사용자 설정으로 하는 것은 set-timing의 후속 기능이다.
- **표본이 선택된다.** 의심 세트 앞 휴식을 빼므로 버튼을 자주 늦게 누르는 운동은 개수가 작다. 모든 휴식이 빠진 label은
  운동별 줄이 없고 window 전체 제외 개수에만 보인다.
- **기록값도 틀릴 수 있다.** 세트 끝에서 버튼을 늦게 누르면 휴식이 ACTIVE에 묻혀 기록된 REST가 짧아지고, 시작에서 두 번 누르는
  패턴은 운동이 뒤 REST에 들어간다. 둘 다 1.0 s/rep 검사로 잡히지 않는다. 시계 일시정지나 긴 잡담 휴식도 그대로 들어간다(상한
  없음, 중앙값이 영향을 줄일 뿐).
- **표시 반올림과 구간이 어긋나 보일 수 있다.** 구간은 ms 중앙값으로 정하고 표시는 `{:.0f} s`라, 60.4 s는 `60 s (band 60-120 s)`로
  보인다. `{:.0f}`는 짝수 쪽 반올림이라 52.5 s는 `52 s`로 보인다(기존 `Rest between sets`와 같다).
- **warm-up 세트를 구분하지 못한다.** Garmin 기록에 warm-up 표시가 없다. superset·circuit 휴식은 label이 바뀌어 빠진다.
- **compound/isolation은 taxonomy 매핑이다.** 다관절과 단관절의 장기 근비대 휴식을 직접 비교한 시험은 찾지 못했다. label에
  taxonomy rule이 없으면 unclassified다(예: `PULL_UP/WIDE_GRIP_PULL_UP`).
- **선택지 줄은 구간으로 켜진다(D5-A).** 표시 선택일 뿐이고 두 선택지를 늘 함께 쓴다. 규칙처럼 읽힌다면 조건 없이 고정 줄을
  쓰는 D5-B로 바꿀 수 있다.
- REST-07 줄은 원문 표현 "at least 2-3 min"을 그대로 쓴다(REST-08이 대체했다고 같은 줄에 적음). 처방처럼 읽힌다면 "2-3 min for
  heavy core lifts"로 줄일 수 있다.
- 기본 7일 window는 표본이 작다. 필요하면 `--days 28`.
- 후속 후보: `recommend` 근력 절의 한 줄(D4-B, golden과 Telegram/코치 영향을 따로 설계), 사용자가 정한 목표 휴식 범위와
  나란히 보여 주기, 1.0 s/rep 기준을 TEMPO-01로 다시 보기.

## 테스트

- `tests/test_rest_interval_advice.py`: 구간 경계(AC4), 제외 순서와 우선순위(AC3), 손계산 중앙값(AC1), triple 없음 → None,
  선택지(AC5), 입력 순서 무관(AC10), 정확한 text 줄과 payload, ASCII 상수, 금지어(AC7), 근거 태그(AC6), 판정 key 없음(AC8),
  D6 helper.
- `tests/test_rest_interval_advice_cli.py`: 블록 위치와 옛 text 복원(AC1, AC9), key 위치 두 경우(AC9), triple 없는 window의
  byte-identical(AC9), text/JSON 개수 일치(AC3), 심박 세 변형에서 payload byte-equal(AC2), CLI 출력의 근거 태그·금지어(AC6, AC7),
  import grep과 `recommend` 무관(AC8), 재실행 동일·ASCII(AC10), 파일·WAL 변화 없음과 심박 읽기 0회(AC11).
- `tests/test_strength_set_timing_cli.py`: D2-A로 바뀐 계약 테스트 3개.
