---
id: training-goal-mode
title: Training Goal Mode and Evidence-Linked Rules v1
status: integrated
migration: none
output_change: additive
user_gates: [design, integration]
---

# Training Goal Mode and Evidence-Linked Rules v1

## 목적

- 사용자가 목표를 **감량(근육 유지) / 유지 / 증가** 중 하나로 정하면, 추천과 표시가 그 목표에 맞게 바뀐다.
- 지금 근력 목표는 코드 기본값(골격근량 43 kg → 50 kg 증가)으로 고정되어 있고, 식단 목표(2,800~3,000 kcal)도 증가 쪽이다.
  사용자는 2026-10-24에 "근손실 최소화하면서 감량"을 목표로 말했다.
- 사용자 목표(2026-10-26 확정): cut, 체지방률 23.0 % → 18 %, 기한 2027-02-28, 골격근량 41 kg 이상, 목표 감량 속도
  주 0.3~0.5 %(근거 범위 0.5~1 %/주보다 느리게, 수면 부족과 간 수치 재검사 때문). 같은 날 식단 목표를 cut 출발점으로 바꿨다:
  2,500~2,700 kcal, 단백질 180~200 g, 지방 55~70 g, 탄수화물 270~330 g(`nutrition target set`). 4개월 뒤 다음 단계(유지 또는 증가)를
  다시 정한다.
- 이번 버전에 넣는 규칙은 모두 `docs/evidence/training-nutrition-evidence.md`(2026-10-25 사용자 승인)의 근거 ID를 단다.
  근거에 숫자가 없는 기준은 자동 규칙이 아니라 표시, 조언, 사용자 설정으로만 둔다(사용자 결정 2026-10-25).
- `docs/goals.md`의 근력 추천 루프와 영양 루프를 사용자의 실제 목표에 맞춘다.

## 범위 / Non-goals

- 범위:
  1. **목표 설정**: 모드(`cut` / `maintain` / `gain`), 선택 값(목표 체지방률 또는 체중, 목표 날짜, 골격근량 하한, 목표 주당 감량 속도).
     설정 파일과 CLI(예: `muscle50 goal set|show`)로 저장·조회한다. 설정이 없으면 지금과 같다(`gain`, 기존 코드 기본값).
  2. **cut 모드의 근력 진행**(MAINT-02, MAINT-05, MAINT-06, PROG-03): 무게(강도)를 유지하는 것이 기준이다. 진행 목표는 "같은 무게, 같은
     횟수 유지"이고, 무게 올리기는 선택으로 보여 준다. 근육당 주 세트 수는 줄이지 않는다(약 10세트 안팎, VOL-04).
  3. **부족한 부위 표시**(VOL-04, 세는 법 VOL-02): 근육(또는 부위)별 최근 7일 세트가 근거 기준(주 10세트) 아래면 표시한다. 기존 부위 선택
     규칙에는 설계에서 정한 만큼만 반영한다(정확히 어떻게 섞을지는 설계 판단으로 표시).
  4. **감량 속도 표시**(MAINT-05): 체중 측정 두 번 사이 변화를 주당 %로 보여 준다. cut 모드에서 사용자가 정한 목표 속도
     범위(예: 0.3~0.5 %/주)를 벗어나면 알리고, 근거 상한인 주 1 %를 넘으면 경고한다. 골격근량이 하한 아래로 내려가면 경고한다.
     체중 출처는 지금은 인바디뿐이다. 주 1~2회 체중만 기록하는 방법이 필요한지(새 입력 명령 또는 Garmin 체중) 설계에서 정한다.
  4-1. **목표 진행 표시**: 목표 체지방률과 기한으로 필요한 주당 속도를 계산해 실제 속도와 함께 보여 준다(제지방 유지 가정은
     `[design]`으로 표시).
  5. **러닝과 하체 근력 간격 표시**(CONC-03, CONC-04, CONC-05): 같은 날 러닝과 하체 근력이 짧은 간격(설계 판단 상수, 근거 범위
     2~6시간)으로 붙어 있으면 표시하고 "근력 먼저"를 조언한다. 자동으로 운동을 바꾸지 않는다. "쉬운 강도로" 같은 조언은 넣지 않는다
     (CONC-06: 근거 없음).
  6. **수면 표시**(SLEEP-05): 7시간 미만인 밤을 보여 준다. 지금 엔진의 수면 기준(5시간 미만 유지, 4시간 미만 감소, 점수 50 미만
     유지)은 근거가 없으므로(SLEEP-05) "사용자 설정" 값으로 옮기고 문서에 그렇게 적는다. 기본값과 동작은 지금과 같게 둔다.
  7. **식단 목표 연결**(PRO-04, PRO-05): cut 모드에서 영양 상태 표시가 결손 상한(하루 약 500 kcal 이하)과 감량기 단백질 범위
     (제지방량 kg당 2.3~3.1 g, 최근 인바디 기준)를 참고로 보여 준다. 실제 식단 목표 값은 `nutrition target set`이 그대로 정한다
     (자동으로 바꾸지 않는다).
  8. **근거 ID 출력**: 위 규칙이 만든 줄과 `--json` 항목에 근거 ID를 붙인다(예: `[MAINT-02]`, 설계 판단은 `[design]`).
- Non-goals:
  - 식단 목표나 운동 계획을 목표 모드가 자동으로 바꾸지 않는다(표시와 진행 목표만 바뀐다). "영양은 운동 계획을 바꾸지 않는다" 원칙 유지.
  - 수면, 러닝을 이유로 세트나 무게를 자동으로 줄이는 새 규칙은 넣지 않는다(근거 없음).
  - 근력 세트 시간 보정(`strength-set-timing`)과 휴식 시간 조언은 별도 기능이다.
  - LLM 없음. migration은 목표를 DB에 저장해야 하면 설계에서 정한다(설정 파일이면 없음).

## 명령 예시

```powershell
muscle50 goal set --mode cut --target-body-fat 18 --by 2027-02-28 --min-smm 41
muscle50 goal show
muscle50 recommend --date 2026-10-26
```

예상 text 출력에 더해지는 줄(합성 값, 정확한 문구는 설계에서 정한다):

```text
Goal: cut (target body fat 18.0 % by 2027-02-28; keep SMM >= 41.0 kg)
  SQUAT/- [maintain_load, MAINT-02]: keep 40 kg x 12 (increase optional)
  Weekly sets below 10 [VOL-04; counting VOL-02]: quadriceps 6, hamstrings 5, glutes 1
  Weight change 2026-09-16 -> 2026-10-20: -0.6 %/week [MAINT-05]
    evidence 0.5-1.0 [MAINT-05]; your target 0.3-0.5 (user setting)
  Same-day run and legs 1 h apart on 2026-10-21 [CONC-04, gap threshold: design]: lift first next time [CONC-05]
  Nights under 7 h in the last 7 days: 5 [SLEEP-05, display only]
```

## 규칙

- 근거 ID가 없는 숫자 기준은 `[design]`으로 표시하고 상수 이름과 문서에 "근거 없음, 설계 판단"을 적는다.
- 모르는 값은 0이 아니다: 인바디가 하나뿐이거나 체중이 없으면 감량 속도는 "알 수 없음"이다.
- 목표 설정이 없으면 모든 기존 출력은 byte-identical이다(새 줄 없음, JSON key 없음).
- 목표 설정 파일의 검증: 모르는 key, 범위를 벗어난 값(체지방률 3~60 %, 날짜 형식 등)은 값을 출력하지 않고 거부한다.
- 결정적 출력(text ASCII, JSON 끝에 key 추가).

## 인수 조건

- [ ] AC1: `goal set/show`가 모드와 선택 값을 저장·출력하고, 잘못된 값은 exit 1로 거부되며 아무것도 쓰지 않는다.
- [ ] AC2: 목표가 없으면 `recommend`, `daily`, `analytics snapshot`, `nutrition status` 출력이 지금과 byte-identical이다.
- [ ] AC3: cut 모드에서 진행 목표가 "무게 유지"(`maintain_load`)이고 세트 수는 줄지 않는다. gain 모드는 지금과 같다.
- [ ] AC4: 근육별 7일 세트가 10 미만이면 근거 ID와 함께 표시된다.
- [ ] AC5: 인바디 두 번 사이 주당 체중 변화 %가 맞게 계산되고, cut 모드에서 1 %/주 초과와 골격근량 하한 미만이 경고된다. 값이 없으면 "unknown".
- [ ] AC6: 같은 날 러닝과 하체 근력의 간격 표시가 맞고, 아무 운동도 자동으로 바뀌지 않는다.
- [ ] AC7: 수면 7시간 미만 밤 수가 표시되고, 기존 수면 기준의 동작은 같으며 문서에 "근거 없음, 사용자 설정"이 적힌다.
- [ ] AC8: 새 줄과 JSON 항목마다 근거 ID 또는 `[design]`이 붙는다.
- [ ] AC9: 품질 게이트 4개가 통과한다.

## 설계 승인 결정 (2026-10-26)

사용자 답: "모두 추천".

- **D1 표시 범위는 (c) 상대값만**: `recommend`/`daily`는 속도(%/주), 하한 위/아래 flag, 필요한 속도만 보여 주고 측정 kg은
  보여 주지 않는다. `nutrition status`(cut만)는 행동에 필요한 PRO-05 단백질 g 범위를 보여 준다. 측정 kg은 `inbody trend`에만 있다.
- **D2 체중 출처는 InBody뿐**: 체중 입력 명령과 migration을 만들지 않는다(`docs/goals.md` §2 유지).
- **D3 `maintain_load` 범위**: cut에서 최종 `increase_load`와 `add_reps`가 마지막 session에 load가 있을 때만 `maintain_load`가
  된다(마지막 work load, reps = min(best, 상한), 원래 목표는 optional). regression·recovery·rest의 `maintain`, `establish_baseline`,
  load 없는 label은 그대로이고 set 수는 바뀌지 않는다.
- **D4 maintain 모드는 표시만**: 진행은 gain과 같고 감량 속도 경고가 없다.
- **D5 주 10세트 미만은 표시만**: 부위 순위와 자동 계획을 바꾸지 않는다. 10의 근거는 VOL-04(ACSM 2026 ≥ 10)이고 세는 법은
  VOL-02다. 위 예시의 `[VOL-01]`은 `[VOL-04; counting VOL-02]`로 고쳤다(VOL-01은 5/10 구간이 확정되지 않았다고 함).
- **D6 수면 기준은 `config\sleep_thresholds.json` + `muscle50 settings sleep show|set|reset`**: 파일이 없으면 지금 기본값이고
  동작도 같다.
- **D7 작은 기본값**:
  - 목표 파일이 깨졌으면 `recommend`/`daily`는 Garmin 호출 전에 `오류:`로 exit 1, `nutrition status`는 "goal reference
    unavailable" 한 줄로 낮춘다(Telegram `/status` 유지).
  - `goal set`은 문서 전체를 바꾼다(병합 없음).
  - 제지방량 = 같은 InBody 날짜의 체중 - 체지방량 `[design]`.
  - 러닝/하체 간격 기준 3시간 `[design]`(근거 범위 2~6시간, CONC-03/04).
  - 감량 속도는 최신 체중과 그보다 7일 이상 앞선 최신 체중을 짝짓는다 `[design]`.
  - 속도 줄은 "(cut target 0.5-1.0 %/week)" 대신 "evidence 0.5-1.0 [MAINT-05]; your target 0.3-0.5 (user setting)"로 근거와
    사용자 설정을 나눈다(위 예시도 고쳤다).
- `docs/goals.md`에 2026-10-26 cut 목표 한 줄을 더했다. 기능은 하나로 묶었다(v1a/v1b 분리 없음).

## 한계 / 후속 후보

- 감량 속도는 인바디(또는 체중) 측정 간격에 기대므로 측정이 드물면 늦게 보인다.
- 후속 후보: Telegram `/goal`과 코치가 목표 모드를 읽기, v3 에이전트 도구로 열기, 근거 규칙집 기반 휴식 시간 조언(`strength-set-timing` 뒤).
- 구현자·검증자가 보고한 한계:
  - InBody 측정이 드물면 속도가 늦게 보이고, 같은 날짜에 값이 다른 측정(conflict)이 있으면 그 날은 빼서 unknown이 될 수 있다.
  - 제지방량은 체중 - 체지방량으로 계산한다 `[design]`. RAW metadata의 FFM은 읽지 않는다.
  - `inbody trend`와 `docs/goals.md`는 아직 SMM 목표 43/50 kg을 보여 준다(cut 하한 41 kg과 다름).
  - 러닝/하체 간격은 지난 기록만 본다(`started_at_utc` 기준). "오늘 러닝이 이미 있고 하체 계획" 같은 미리 알림은 없다.
  - 모호한 label(`PULL_UP/-` 등)은 `maintain_load`로 바뀐 뒤에도 기존 step 방향 `load_guidance` 문구가 남는다.
  - maintain 모드는 감량 속도 경고가 없다(D4).
  - 열량 결손은 측정할 수 없어(유지 kcal 모름) PRO-04 줄은 고정 문구다.
  - Telegram 코치 LLM은 `recommend --json`의 `goal_mode`와 `nutrition status --json`의 `goal_reference`를 받는다(상대값과
    단백질 g 범위; 측정 kg 없음).
  - 수면 설정 파일이 깨졌으면 `settings sleep reset` 전까지 `settings sleep set`이 거부된다(`recommend`/`daily`도 exit 1).
  - 새 줄 중 태그 없는 줄 두 개(절 header, 목표 파일이 깨졌을 때의 "Goal reference: unavailable")는 규칙 출력이 아니라 상태
    줄로 보고 받아들였다(AC8).
  - `recommendation_version`은 1 그대로다(영양 통합 선례).
- **후속 후보: 유산소 가이드(정체 감지, 주간 유산소 총량, 열량 vs 유산소 선택지) — 근거 조사 진행 중.**
- migration은 없고 Garmin 동기화를 바꾸지 않으므로 production migration(gate 3)과 live Garmin 확인(gate 4)은 없다.
