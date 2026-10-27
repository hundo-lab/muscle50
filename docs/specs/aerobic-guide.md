---
id: aerobic-guide
title: Aerobic Guide v1
status: draft
migration: none
output_change: additive
user_gates: [design, integration]
---

# Aerobic Guide v1

## 목적

- 주간 유산소 양을 보여 주고, 감량이 목표보다 느릴 때 **고를 수 있는 선택지**를 근거와 함께 보여 준다. 러닝 길이가 갑자기
  늘면 알린다.
- 근거:
  - 사용자 요청(2026-10-27): "감량이 잘 안되거나 체지방이 줄지 않으면 유산소를 늘리라는 처방이 필요" — 단, 근거상 유산소 추가와
    열량 감소 사이에 순위가 없으므로(PLAT-06, FATEX-05) 처방이 아니라 동등한 선택지로 보여 준다. "먹고 싶은 걸 먹으면서 유산소로
    결손 만들기"도 정당한 선택지다(FATEX-05, FATEX-07, 사용자 의견 2026-10-27).
  - 목표 모드(`docs/training-goal-mode.md`)는 감량 속도와 목표를 이미 계산한다. 이 기능은 그 값을 읽는다.
  - 근거 문서 `docs/evidence/training-nutrition-evidence.md` 13–16절(2026-10-27 사용자 승인).
- `docs/goals.md`의 감량 목표(2026-10-26 cut 목표)와 유산소 기록(러닝 주 3~5회, 수영)을 연결한다.

## 범위 / Non-goals

- 범위:
  1. **주간 유산소 분**: 최근 7일(설계에서 창을 정함) 유산소 활동의 중강도·고강도 분(Garmin intensity minutes, 없으면 활동 시간)을
     합쳐 지침 기준 **주 150분 / 300분**(EXL-03, FATEX-02)과 함께 보여 준다. 문구 규칙(FATEX-02 메모): "150분 이후 효과가 멈춘다"고
     쓰지 않는다. 기준선으로만 보여 준다.
  2. **감량 정체 알림(cut 모드만)**: 목표 모드의 감량 속도가 사용자가 정한 조건(예: N주 동안 목표 속도의 하한 미만)을 만족하면
     알린다. 조건 값은 **사용자 설정**이고 출력에 `[design: user setting]`으로 표시한다(PLAT-01, PLAT-02: 근거상 정체 기준 없음).
     측정 잡음(인바디, 주중 체중 변동)이 목표 속도와 비슷하다는 점을 함께 적는다(PLAT-01/02).
  3. **정체 때 선택지(순위 없음)**(PLAT-06): (가) 식단 기록 확인, (나) 섭취 줄이기, (다) 섭취는 두고 활동 늘리기, (라) 1주 유지
     휴식. 각 선택지에 근거 ID와 한 줄 설명을 붙인다. 숫자 제약만 함께 보여 준다: 섭취를 줄일 때 한 번에 100~150 kcal(`docs/goals.md`),
     하루 결손 약 500 kcal 이하(PRO-04), 활동을 늘릴 때 러닝 급증 알림(RUNPROG-03)과 하체 날 간격(CONC-04, CONC-05). 사용자의
     선호와 지속 가능성이 고르는 기준이 될 수 있다고 적는다(FATEX-07).
  4. **러닝 길이 급증 알림**(RUNPROG-03): 오늘(또는 최근) 러닝이 지난 30일 가장 긴 러닝보다 10% 넘게 길면 "과사용 부상과 연관된
     범위" 알림. 경고나 차단이 아니다. 지난 30일 러닝이 없으면 건너뛴다. 관찰연구 연관성이라는 점을 문서에 적는다.
  5. **운동 칼로리를 섭취 목표에 더하지 않는다**(FATEX-04): 영양 상태 표시에서 Garmin 운동 칼로리를 목표에 더하는 일은 하지 않는다
     (이미 그렇다면 그대로 유지하고 문서에 근거를 적는다).
  6. **보여 주는 곳**: `recommend`/`daily`의 목표 절(또는 새 유산소 절), `--json` 끝에 key. 목표 모드 D1(상대값만, 측정 kg 없음)을
     따른다. Telegram `/daily`와 코치는 같은 JSON을 읽는다.
- Non-goals:
  - 유산소를 자동으로 처방하거나 운동·식단 목표를 자동으로 바꾸지 않는다.
  - 러닝 페이스·거리 처방, 쉬운/힘든 러닝 배분 처방은 하지 않는다(RUNPROG-06: 근거 없음).
  - ACWR은 쓰지 않는다(RUNPROG-04). "주 10% 규칙"은 넣지 않는다(RUNPROG-01: 사용자 설정 후보로만 후속).
  - Garmin 동기화 방식은 바꾸지 않는다(저장된 활동과 load metrics만 읽음). LLM 없음. migration 없음(설계에서 확인).

## 명령 예시

```powershell
muscle50 goal set --mode cut --target-body-fat 18 --by 2027-02-28 --min-smm 41 --weekly-loss 0.3 0.5 --plateau-weeks 3
muscle50 recommend --date 2026-11-20
```

예상 text 출력에 더해지는 줄(합성 값, 정확한 문구는 설계에서 정한다):

```text
  Aerobic minutes 2026-11-13..2026-11-19: moderate 140 + vigorous 60 = 200 min [EXL-03, FATEX-02]
    guideline marks 150 / 300 min/week (a minimum and a reference, not a ceiling)
  Plateau [design: user setting 3 weeks below 0.3 %/week]: loss -0.10 %/week over 3 weeks
    options (no ranking, PLAT-06; choose by preference and what you can keep up, FATEX-07):
      a) check that meals are logged completely [PLAT-04]
      b) eat 100-150 kcal/day less (keep the deficit at or under about 500 kcal/day) [goals.md, PRO-04]
      c) keep intake, add activity (watch run length and leg-day spacing) [FATEX-05, RUNPROG-03, CONC-04]
      d) one maintenance week [PLAT-05]
    note: InBody and day-to-day weight noise is about the size of your target rate [PLAT-01, PLAT-02]
  Run length 2026-11-19: 12.5 km, 25 % longer than your longest run in the last 30 days (10.0 km) [RUNPROG-03, notice only]
```

## 규칙

- 근거 ID가 없는 기준은 `[design]` 또는 `[design: user setting]`이다. 정체 기준, 창 길이 같은 값은 상수와 문서에 "근거 없음"을 적는다.
- 모르는 값은 0이 아니다: intensity minutes가 없는 활동은 "unknown"으로 세고 합계는 하한(lower bound)이라고 쓴다.
- 목표 모드가 없거나 cut이 아니면 정체 알림과 선택지는 나오지 않는다. 유산소 분과 러닝 급증 알림을 목표 없이도 보여 줄지는 설계에서
  정한다(목표 없음 = byte-identical 원칙과의 관계 포함).
- 결정적 출력(text ASCII, JSON 끝에 key 추가). 선택지 순서는 고정 표시 순서일 뿐 순위가 아니라고 문서에 적는다.

## 인수 조건

- [ ] AC1: 최근 7일 유산소 분 합계가 중강도·고강도별로 맞게 나오고, 값이 없는 활동은 unknown·하한으로 표시된다.
- [ ] AC2: 150/300 기준선 문구에 "멈춘다/상한" 같은 표현이 없다(FATEX-02).
- [ ] AC3: cut 모드에서 사용자 정체 조건을 만족할 때만 정체 알림과 네 선택지가 순위 없이 근거 ID와 함께 나온다.
- [ ] AC4: 러닝 급증 알림이 지난 30일 최장 러닝보다 10% 초과일 때만 나오고, 30일 러닝이 없으면 나오지 않는다.
- [ ] AC5: 운동 칼로리가 섭취 목표에 더해지지 않는다.
- [ ] AC6: 아무 운동·식단 목표도 자동으로 바뀌지 않는다. 측정 kg은 recommend/daily에 나오지 않는다(D1).
- [ ] AC7: 기존 출력은 설계에서 정한 조건에서 byte-identical이다.
- [ ] AC8: 새 줄과 JSON 항목마다 근거 ID 또는 `[design]`이 붙는다.
- [ ] AC9: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- 지방 감소 운동 근거는 대부분 운동하지 않던 과체중 성인에서 나왔다. 이미 많이 뛰는 사람에게 효과 크기는 알 수 없다(FATEX-02, FATEX-04).
- 정체 판단은 인바디 측정 빈도에 기대므로 늦을 수 있다.
- 후속 후보: 주간 러닝 증가 상한을 사용자 설정으로(RUNPROG-01), v3 에이전트 도구로 열기.
