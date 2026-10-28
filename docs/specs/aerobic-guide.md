---
id: aerobic-guide
title: Aerobic Guide v1
status: integrated
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

- [x] AC1: 최근 7일 유산소 분 합계가 중강도·고강도별로 맞게 나오고, 값이 없는 활동은 unknown·하한으로 표시된다.
- [x] AC2: 150/300 기준선 문구에 "멈춘다/상한" 같은 표현이 없다(FATEX-02).
- [x] AC3: cut 모드에서 사용자 정체 조건을 만족할 때만 정체 알림과 네 선택지가 순위 없이 근거 ID와 함께 나온다.
- [x] AC4: 러닝 급증 알림이 지난 30일 최장 러닝보다 10% 초과일 때만 나오고, 30일 러닝이 없으면 나오지 않는다.
- [x] AC5: 운동 칼로리가 섭취 목표에 더해지지 않는다.
- [x] AC6: 아무 운동·식단 목표도 자동으로 바뀌지 않는다. 측정 kg은 recommend/daily에 나오지 않는다(D1).
- [x] AC7: 기존 출력은 설계에서 정한 조건에서 byte-identical이다.
- [x] AC8: 새 줄과 JSON 항목마다 근거 ID 또는 `[design]`이 붙는다.
- [x] AC9: 품질 게이트 4개가 통과한다.

AC8은 계획의 정의대로 확인했다: 항목별 줄과 이어지는 줄은 근거가 붙은 윗줄을 따른다.

## 설계 승인 결정 (2026-10-27)

사용자 답: 모두 추천안(D1-D9). 상세: `docs/aerobic-guide.md`.

- **D1**: 새 줄은 기존 goal 절 끝(수면 줄 뒤)에, JSON은 `goal_mode` 안 마지막 key `aerobic_minutes`, `run_length`, `plateau`로
  붙는다. 목표 파일이 있을 때만 보이고(정체는 cut만), 목표가 없으면 출력은 byte-identical이다. `goal_mode_version`과
  `recommendation_version`은 1 그대로다.
- **D2**: 정체 설정은 `goal set ... --plateau-weeks N`(cut + `--weekly-loss`만, 2-26 `[design]`). 기준 속도는 `--weekly-loss`의 MIN.
  설정했을 때만 목표 파일이 schema 2이고, 없으면 schema 1 그대로(byte 단위로 같다).
- **D3**: 최신 InBody부터 7일 이상 간격으로 짝지은 구간이 N주 이상이고 2개 이상이며 모든 구간의 감량이 MIN 미만이면 `met`.
  구간이 모자라면 "정체 아님"이 아니라 `insufficient_measurements`다(PLAT-02).
- **D4**: 유산소 분은 running과 swimming만 센다. **D5**: intensity minutes만 더하고, 없는 활동의 시간은 따로 보여 줄 뿐 더하지 않는다(하한).
- **D6**: vigorous는 두 배로 세지 않는다. 150은 `[EXL-03]`, 300은 `[FATEX-02]`. **D7**: 러닝 급증은 거리만, D-7..D의 러닝을 그 전
  30일 최장과 비교, 정확히 110 %는 알림 없음.
- **D8**: 150/300 줄에 stop/ceiling/limit/upper/max를 쓰지 않는다. **D9**: 100-150 kcal 단계는 `[design: goals.md step; PRO-04]`.

## 한계 / 후속 후보

- 지방 감소 운동 근거는 대부분 운동하지 않던 과체중 성인에서 나왔다. 이미 많이 뛰는 사람에게 효과 크기는 알 수 없다(FATEX-02, FATEX-04).
- 정체 판단은 인바디 측정 빈도에 기대므로 늦을 수 있다.
- 후속 후보: 주간 러닝 증가 상한을 사용자 설정으로(RUNPROG-01), v3 에이전트 도구로 열기.
- 구현자·검증자가 보고한 한계:
  - 목표가 있으면 `recommend`는 DB를 두 번 읽는다(계획용 창과 D-37..D). 두 읽기는 한 snapshot이 아니다.
  - 트레드밀 거리는 시계 추정값이라 러닝 길이 알림이 흔들릴 수 있다.
  - InBody를 한 달에 한 번 재면 2구간 규칙(PLAT-02) 때문에 정체는 약 6-8주 데이터가 쌓여야 판단된다. 유지 휴식 주(PLAT-05)는
    정체나 증가처럼 보일 수 있고 구분하지 못한다.
  - intensity minutes backfill 전에 저장된 활동이 있으면 합계는 하한이다. Garmin vigorous 분은 그대로 더하고 75분 환산은 이름만 적는다(D6).
  - 거리가 0 이하이거나 유한하지 않은 러닝은 "거리 없음"으로 보고 판단하지 않는다 `[design]`.
  - 정체 `note:` 줄은 주중 체중 변동(0.35 %, PLAT-02)과 사용자 목표 범위를 나란히 적을 뿐 둘을 비교하지 않는다(검증 1차 지적 후 수정).
  - `goal set`은 문서 전체를 바꾸므로 `--plateau-weeks` 없이 다시 설정하면 정체 설정이 지워진다. schema 2 목표 파일은 이전 빌드가 거부한다.
  - Telegram 코치 LLM은 `goal_mode`의 새 key(분, 거리, 속도, 선택지 코드; 측정 kg 없음)를 받는다.
- 후속 후보(추가): Telegram 요약에 목표·유산소 줄 넣기, 중강도 환산 분(moderate + 2 x vigorous), 목표 없이도 유산소 분 보여 주기(D1-C),
  코치가 정체 선택지 읽기.
- migration은 없고 Garmin 동기화를 바꾸지 않으므로 production migration(gate 3)과 live Garmin 확인(gate 4)은 없다.
