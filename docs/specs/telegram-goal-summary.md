---
id: telegram-goal-summary
title: Telegram Goal Summary v1
status: draft
migration: none
output_change: additive
user_gates: [design, integration]
---

# Telegram Goal Summary v1

## 목적

- 목표 파일(`config\training_goal.json`)이 있으면 Telegram `/daily` 요약(휴대폰 화면) 끝에 목표 모드와 유산소 가이드의 짧은 줄
  몇 개를 붙인다: 체중 변화(%/주)·골격근량 하한·목표 진행, 지난 7일 유산소 분과 150/300 기준선, 표시된 러닝 길이 알림, 정체 확인
  상태(조건 충족이면 순위 없는 선택지 a-d).
- 왜: `recommend`/`daily`의 text와 JSON에는 goal 절(`goal_mode`: `weight_change`, `smm_floor`, `goal_progress`,
  `aerobic_minutes`, `run_length`, `plateau`)이 이미 있다. 하지만 사용자가 매일 보는 `/daily` 요약에는 그 내용이 없다.
  지금 보려면 `/daily full`(긴 영어 리포트, 보통 2개 메시지)을 열어야 한다.
  - 두 통합 스펙 모두 이것을 후속 후보로 남겼다: `docs/specs/aerobic-guide.md`("Telegram 요약에 목표·유산소 줄 넣기"),
    `docs/specs/training-goal-mode.md`("Telegram `/goal`과 코치가 목표 모드를 읽기").
  - `docs/aerobic-guide.md` Known issues에도 같은 내용이 있다: "Telegram 요약(`/today`, `/daily`)은 바뀌지 않는다".
- 새 계산은 없다. bot이 이미 받는 `daily --json`의 `recommendation.goal_mode` 값을 그대로 옮겨 적는다.
- `docs/goals.md`의 기여:
  - 3절 하루 흐름의 "아침: `daily`"와 "Telegram 채팅"을 2026-10-26 cut 목표(5절)에 연결한다.
  - 감량 진행과 유산소 양을 휴대폰에서 매일 보게 한다.

## 범위 / Non-goals

- 범위:
  1. **`/daily` 요약에만 붙인다**(성공한 `daily`의 계획 요약 뒤). 실패한 `daily`(`ok: false`)는 지금처럼 계획을 만들지 않으므로
     목표 줄도 없다.
  2. **켜지는 조건은 key가 있는지다.** `daily["recommendation"]`에 `goal_mode` key가 있을 때만 붙는다.
     - CLI는 목표가 없으면 `goal_mode`를 지운다(`presentation/terminal.py`). 그래서 key가 있다는 것은 목표 파일이 있다는 뜻이다.
     - `"catch_up" not in daily`, `"nutrition" not in recommendation`과 같은 방식이다.
     - key가 없으면 답장은 지금과 byte-identical이다.
  3. **줄 종류**(아래 "규칙"에 상태마다 정한 문구가 있다):
     - 목표 머리줄
     - 체중 변화(`weight_change`)와 flag
     - 골격근량 하한(`smm_floor`)
     - 목표 진행(`goal_progress`)
     - 유산소 분(`aerobic_minutes`)과 150/300 기준선
     - 러닝 길이 알림(`run_length`의 `longer_than_threshold`가 있을 때만)
     - 정체 확인(`plateau`; cut만, `met`이면 선택지 a-d)
  4. 모든 줄은 한국어이고 지금 Telegram 요약의 말투를 따른다. 근거 태그(`[MAINT-05; design]` 등)는 CLI 줄의 태그를 그대로 쓴다.
- Non-goals:
  - **새 계산이나 판단 없음.** 숫자는 JSON 값 그대로다. 비율이나 분을 다시 반올림하지 않는다.
    - 150/300과 비교해 "달성/부족/초과" 같은 판정을 하지 않는다. 숫자를 나란히 적기만 한다.
    - 허용하는 것: 목록 항목 세기, CLI가 이미 쓰는 formatter(분의 `:g`, `goal_terminal._km`, `_month_day`) 재사용.
  - CLI 출력 변경 없음. `recommend`, `daily`, `goal`, `nutrition` 등 모든 명령의 text와 `--json`은 byte-identical이다.
    새 JSON key도 없다.
  - `/today`, `/today full`, `/daily full`, `/status`, `/unknown`, `/refresh` 답장은 바뀌지 않는다. `/today`는 열린 질문 Q1이다.
  - 코치 LLM은 바뀌지 않는다. 코치는 지금처럼 `recommend --json`을 그대로 받는다(`docs/telegram-llm.md`). 요약 문구를 코치에
    넘기지 않는다.
  - 다음 goal 절 항목은 요약에 넣지 않는다(`/daily full`에 있다):
    - 주당 set(`weekly_sets`)
    - 러닝/하체 간격(`run_legs`)
    - 수면(`sleep`)
    - 진행 목표 변경(`progression`, cut의 `maintain_load`)
  - `/goal` 명령, 예약 알림, 자동 처방, 운동·식단 목표 변경 없음. 측정 kg 없음(목표 모드 D1).
  - migration 없음. Garmin 동기화 변경 없음. LLM 없음.

## 명령 예시

```powershell
# 목표 설정(이미 있는 명령, 바뀌지 않음)
muscle50 goal set --mode cut --target-body-fat 18 --by 2027-02-28 --min-smm 41 --weekly-loss 0.3 0.5 --plateau-weeks 3

# bot이 /daily 때 실행하는 명령(바뀌지 않음, 한 번만 동기화)
muscle50 daily --json
```

Telegram에서 `/daily`를 보낸다. 지금 요약 형식은 `docs/telegram-bot.md` v1.1 절에 있다.

예상 `/daily` 답장(합성 값, cut, 정체 조건 충족). 정확한 문구는 설계에서 정한다. `<pre>` 안이 고정폭 본문이고, 목표 줄은
영양 줄 뒤 `<pre>` 안에 붙는다(위치는 Q2).

```text
<pre>daily 11-20: 동기화 완료 (새 운동 1, 회복 1일 갱신)

근력: legs · 약 32분 · 9세트
 1. SQUAT/BARBELL_BACK_SQUAT 3x10 @ 60 kg
회복: normal (readiness HIGH 82, HRV BALANCED, 수면 07:12:00)
수영: easy_continuous 약 800 m (마지막 수영 3일 전)
영양: 식사 2끼 · kcal 1450 / 목표 2500-2700 (below_range, 최소까지 1050)

목표: cut (내 설정) [design: user setting]
체중 변화 10-23 -> 11-20: -0.11 %/주 [MAINT-05; design]
  -> 내 목표 범위 밖 [design: user setting]
골격근량: 내 하한 41 kg 이상 (InBody 11-20) [design: user setting]
목표 진행: 체지방 18 %까지 -0.42 %/주 필요, 실제 -0.11 %/주 [design: fat-free mass assumed constant]
유산소 11-13..11-19: 200분 (중강도 140 + 고강도 60) [EXL-03; design]
  기준선: 150분 지침 최소 [EXL-03] · 300분 연구된 범위의 끝 [FATEX-02]
러닝 길이 11-19: 12.5 km, 지난 30일 최장보다 25.0 % 김 [RUNPROG-03: 관찰 연구의 연관, 알림만]
정체 확인: 조건 충족 (내 설정 3주, 0.3 %/주 미만 감량) [design: user setting; PLAT-01, PLAT-02]
  선택지, 순위 없음 (표시 순서일 뿐) [PLAT-06, FATEX-07]
  a) 식사 기록이 빠짐없는지 확인 [PLAT-04]
  b) 하루 100-150 kcal 덜 먹기, 결손은 약 500 kcal 이하 [design, PRO-04]
  c) 섭취는 두고 활동 늘리기 (더 먹으면 일부 상쇄될 수 있음; 러닝 길이·러닝/하체 3시간 간격 주의) [FATEX-05, FATEX-04, RUNPROG-03, CONC-04]
  d) 1주 유지 휴식 [PLAT-05]</pre>
확인 필요: Garmin UNKNOWN 세트      (지금과 같음)
...
기타 알림 6건 · 전체: /today full
```

다른 상태의 예(합성 값, 해당 줄만):

```text
체중 변화: 알 수 없음 (only one InBody weight) [MAINT-05; design]
  -> 주 1.0 %보다 빠름: 근육 유지에 불리할 수 있음 [MAINT-05]
  -> 감량 중 체중 증가 [design]
골격근량: 내 하한 41 kg 아래 (InBody 11-20) [design: user setting]
골격근량: 내 하한 41 kg 대비 알 수 없음 (InBody 골격근량 없음) [design: user setting]
골격근량 하한: 설정 안 함 [design: user setting]
목표 진행: 체지방 18 % 도달 (InBody 11-20) [design: fat-free mass assumed constant]
목표 진행: 기한 2027-02-28 지남 [design]
목표 진행: 목표·기한 없음 [design]
목표 진행: 알 수 없음 (InBody data unavailable) [design]
유산소 11-13..11-19: 200분 이상 (중강도 140 + 고강도 60, intensity minutes 없는 활동 1개 빠짐) [EXL-03; design]
유산소 11-13..11-19: 중강도 알 수 없음 + 고강도 5 = 5분 이상 [EXL-03; design]
유산소 11-13..11-19: 알 수 없음 (센 활동에 intensity minutes 없음) [EXL-03; design]
유산소 11-13..11-19: 저장된 러닝·수영 없음 (동기화 안 됐을 수 있음, 0분이 아님) [EXL-03; design]
러닝 길이 11-19: 12.5 km, 지난 30일 최장보다 25.0 % 김 (이전 러닝 1개 거리 없음, 최장이 더 길 수 있음) [RUNPROG-03: 관찰 연구의 연관, 알림만]
정체 확인: 조건 미충족 (내 설정 3주, 0.3 %/주 미만 감량) [design: user setting; PLAT-01, PLAT-02]
정체 확인: InBody 측정이 모자라 판단 못 함, 정체 아님이 아님 (2 weights cover 1 interval) [design: user setting; PLAT-02]
정체 확인: 알 수 없음 (InBody data unavailable: ...) [design: user setting]
정체 확인: 설정 안 함 (goal set ... --plateau-weeks N) [design; PLAT-01]
```

maintain/gain 목표의 경우:

- `plateau`가 null이므로 정체 줄이 없다.
- 감량 flag도 없다. CLI에서 flag가 나오는 것은 cut뿐이다.
- 나머지 줄은 그대로 나온다.
- 머리줄은 `목표: maintain (내 설정) [design: user setting]` 또는 `목표: gain (내 설정) [design: user setting]`이다.

이 기능이 읽는 JSON(합성 값, `daily --json`의 `recommendation.goal_mode`에서 쓰는 key만; JSON은 바뀌지 않는다):

```json
{
  "goal_mode_version": 1,
  "goal": {"mode": "cut", "target_body_fat_percent": "18", "target_weight_kg": null, "target_date": "2027-02-28",
           "min_skeletal_muscle_mass_kg": "41", "weekly_loss_percent": {"minimum": "0.3", "maximum": "0.5"},
           "plateau_weeks": 3, "source": "user_setting", "evidence": ["design"]},
  "weight_change": {"status": "known", "from_date": "2026-10-23", "to_date": "2026-11-20", "percent_per_week": "-0.11",
                    "flags": ["outside_user_target"], "reason": null},
  "smm_floor": {"status": "at_or_above", "measurement_date": "2026-11-20", "floor_kg": "41"},
  "goal_progress": {"status": "known", "required_percent_per_week": "-0.42", "actual_percent_per_week": "-0.11",
                    "measurement_date": "2026-11-20", "assumption": "...", "reason": null},
  "aerobic_minutes": {"from": "2026-11-13", "to": "2026-11-19", "status": "known", "moderate_minutes": 140.0,
                      "vigorous_minutes": 60.0, "total_minutes": 200.0,
                      "without_intensity_minutes": {"activity_count": 0, "one_metric_only_count": 0},
                      "reference_minutes_per_week": [
                        {"minutes": 150, "meaning": "guideline_minimum", "evidence": ["EXL-03"]},
                        {"minutes": 300, "meaning": "end_of_studied_range", "evidence": ["FATEX-02"]}]},
  "run_length": {"runs": [{"date": "2026-11-19", "distance_meters": 12500.0, "increase_percent": "25.0",
                           "previous_without_distance": 0, "baseline_lower_bound": false,
                           "status": "longer_than_threshold"}]},
  "plateau": {"status": "met", "weeks": 3, "below_loss_percent_per_week": "0.3", "reason": null,
              "options_ranked": false, "choice_evidence": ["PLAT-06", "FATEX-07"],
              "options": [{"code": "check_meal_logging", "evidence": ["PLAT-04"]},
                          {"code": "eat_less", "step_kcal_per_day": {"minimum": 100, "maximum": 150},
                           "deficit_limit_kcal_per_day": 500, "evidence": ["design", "PRO-04"]},
                          {"code": "keep_intake_add_activity", "run_length_threshold_percent": 10, "run_legs_gap_hours": 3,
                           "evidence": ["FATEX-05", "FATEX-04", "RUNPROG-03", "CONC-04"]},
                          {"code": "maintenance_week", "weeks": 1, "evidence": ["PLAT-05"]}]}
}
```

## 규칙

- **근거 태그**
  - 새 줄마다 근거 ID나 `[design]`(또는 `[design: user setting]`)이 붙는다.
  - 들여쓴 이어지는 줄(flag의 `->`, 기준선, 선택지 머리줄)은 바로 위의 태그 붙은 줄을 따른다. Aerobic Guide v1의 AC8과 같은
    정의다. 단, 선택지 a-d와 기준선 줄에는 각각 자기 태그를 단다.
  - 근거 ID는 `docs/evidence/training-nutrition-evidence.md`에 있는 것만 쓰고, 그 ID가 말하는 내용에만 쓴다. 그래서 각 줄의
    태그는 같은 내용을 보여 주는 CLI goal 절 줄(`presentation/goal_terminal.py`)의 태그를 그대로 쓰고, 새로 짝짓지 않는다.
  - 선택지 a-d의 태그는 JSON `plateau.options[].evidence`를 그대로 옮긴다(JSON에는 `design`이라고만 있다; 예시 b의
    `[design, PRO-04]`). 선택지 머리줄의 태그는 `plateau.choice_evidence`를 옮긴다.
- **줄과 상태의 짝**(JSON 값 → 줄). 표에 없는 status, flag, option code, `meaning`이 오면 `ValueError`를 낸다. 그러면 지금 bot이
  하는 대로 `SummaryUnavailableError` 대체 답장(`오류: daily는 끝났지만 결과를 요약하지 못했습니다 (exit N). ...`)이 나간다. 줄을
  조용히 빼지 않는다(`docs/telegram-bot.md` v1.1 "모르는 상태 값" 규칙).

  - **머리줄**: `목표: <mode> (내 설정) [design: user setting]`. `mode`는 `goal.mode` 그대로(`cut`/`maintain`/`gain`).
  - **`weight_change`**
    - `known`: `체중 변화 <from MM-DD> -> <to MM-DD>: <percent_per_week> %/주 [MAINT-05; design]`.
    - `unknown`: `체중 변화: 알 수 없음 (<reason>) [MAINT-05; design]`.
    - flag 한 개마다 `  -> ...` 한 줄. 주의 표시이므로 빼지 않는다.
      - `faster_than_evidence`: `주 1.0 %보다 빠름: 근육 유지에 불리할 수 있음 [MAINT-05]`
      - `outside_user_target`: `내 목표 범위 밖 [design: user setting]`
      - `gaining`: `감량 중 체중 증가 [design]`
  - **`smm_floor`**(모든 줄에 `[design: user setting]`)
    - `at_or_above`: `골격근량: 내 하한 <floor_kg> kg 이상 (InBody MM-DD)`
    - `below`: `골격근량: 내 하한 <floor_kg> kg 아래 (InBody MM-DD)`
    - `unknown`: `골격근량: 내 하한 <floor_kg> kg 대비 알 수 없음 (InBody 골격근량 없음)`
    - `not_set`: `골격근량 하한: 설정 안 함`. 이 줄을 아예 뺄지는 Q4.
    - `floor_kg`는 사용자가 입력한 값이고 측정값이 아니다(D1이 허용).
  - **`goal_progress`**(태그: `assumption`이 있으면 `[design: fat-free mass assumed constant]`, 없으면 `[design]`, CLI와 같음)
    - `known`: `목표 진행: <목표>까지 <required> %/주 필요, 실제 <actual> %/주`. `actual`이 null이면 `실제 알 수 없음`.
    - `reached`: `목표 진행: <목표> 도달 (InBody MM-DD)`
    - `deadline_passed`: `목표 진행: 기한 <target_date> 지남`
    - `not_set`: `목표 진행: 목표·기한 없음`
    - `unknown`: `목표 진행: 알 수 없음 (<reason>)`
    - `<목표>`는 `goal.target_body_fat_percent`(`체지방 18 %`)나 `goal.target_weight_kg`(`체중 75 kg`, 사용자 입력)다.
  - **`aerobic_minutes`**(첫 줄 태그 `[EXL-03; design]`)
    - `known`: `유산소 <from>..<to>: <total>분 (중강도 <m> + 고강도 <v>)`
    - `lower_bound`: `... <total>분 이상 (...)`. 하한이라는 표시는 `/status`의 `이상 (값 없는 항목 N개)`과 같은 방식이다.
      - 빠진 이유를 `without_intensity_minutes.activity_count`, `one_metric_only_count`로 짧게 적는다.
      - 한 칸이 null이면 그 칸은 `알 수 없음`이고 0이 아니다.
    - `unknown`: `유산소 <from>..<to>: 알 수 없음 (센 활동에 intensity minutes 없음)`
    - `none_stored`: `유산소 <from>..<to>: 저장된 러닝·수영 없음 (동기화 안 됐을 수 있음, 0분이 아님)`
    - 분은 JSON float이므로 CLI `_minutes`와 같은 `:g` 형식으로 쓴다(`140.0`이 아니라 `140`).
    - 상태와 상관없이 기준선 줄이 따라온다: `  기준선: <minutes>분 지침 최소 [<evidence>] · <minutes>분 연구된 범위의 끝 [<evidence>]`.
      `minutes`와 `evidence`는 `reference_minutes_per_week[]`에서 읽는다(`meaning`이 `guideline_minimum` /
      `end_of_studied_range`).
  - **`run_length`**
    - `runs[]` 중 `status == "longer_than_threshold"`인 것마다 한 줄:
      `러닝 길이 MM-DD: <km> km, 지난 30일 최장보다 <increase_percent> % 김 [RUNPROG-03: 관찰 연구의 연관, 알림만]`.
    - km는 CLI의 `goal_terminal._km`(0.01 HALF_EVEN)을 재사용한다. 새 반올림은 없다.
    - `baseline_lower_bound`가 true이면 `(이전 러닝 N개 거리 없음, 최장이 더 길 수 있음)`을 붙인다. N은
      `previous_without_distance`이고, 주의 표시이므로 빼지 않는다.
    - 표시된 러닝이 없으면 러닝 줄이 없다(`within`, `no_previous_run`, `no_distance`, 빈 목록).
  - **`plateau`**(null이면, 즉 gain/maintain이면 줄이 없다)
    - 머리줄 태그는 `[design: user setting; ...]`이다. `...`에는 CLI 정체 줄과 같은 근거 ID를 넣는다.
    - `met`: `정체 확인: 조건 충족 (내 설정 <weeks>주, <below_loss_percent_per_week> %/주 미만 감량)`.
      그 뒤에 선택지 머리줄(`선택지, 순위 없음 (표시 순서일 뿐) [PLAT-06, FATEX-07]`)과 `options[]`를 JSON 순서대로 한 줄씩 붙인다.
      - b의 kcal 숫자는 `step_kcal_per_day`, `deficit_limit_kcal_per_day`에서 읽는다.
      - c의 3시간은 `run_legs_gap_hours`에서 읽는다.
    - `not_met`: `정체 확인: 조건 미충족 (...)`
    - `insufficient_measurements`: `정체 확인: InBody 측정이 모자라 판단 못 함, 정체 아님이 아님 (<reason>)`. 정체가 아니라고
      읽히면 안 된다(PLAT-02, 결측은 0이 아님).
    - `unknown`: `정체 확인: 알 수 없음 (<reason>)`
    - `not_set`(cut인데 `--plateau-weeks` 없음): `정체 확인: 설정 안 함 (goal set ... --plateau-weeks N) [design; PLAT-01]`.
      아예 뺄지는 Q4.
    - PLAT-02 측정 잡음 문구(`note:`)는 요약에 넣지 않는다(`/daily full`에 있다). 넣을지는 Q5.
- **150/300 문구**(FATEX-02 메모, `docs/aerobic-guide.md` D8)
  - 150은 "지침 최소"(EXL-03), 300은 "연구된 범위의 끝"(FATEX-02)이다.
  - 유산소 줄과 기준선 줄에 다음 표현을 쓰지 않는다.
    - 영어: `stop`, `ceiling`, `limit`, `upper`, `max`
    - 한국어: `상한`, `최대`, `최고`, `한계`, `한도`, `제한`, `멈`, `그만`, `충분`, `목표`
    - 판정어: `달성`, `부족`, `초과`, `미달`
  - "N분 이상"의 `이상`은 하한 표시이므로 허용한다.
- **선택지는 대등하다**(PLAT-06, FATEX-05, FATEX-07).
  - 순서는 JSON의 고정 표시 순서이고 순위가 아니라고 줄에 적는다.
  - "추천", "먼저", "가장", "권장", 번호 매긴 순위 문구를 쓰지 않는다.
  - c를 더 약한 선택지로 쓰지 않는다.
  - 각 선택지의 문구는 그 줄에 붙인 모든 근거 ID의 내용을 담는다. 특히 c는 "더 먹으면 결손 일부가 상쇄될 수 있음"(FATEX-04)을
    줄이지 않고 적는다(`docs/aerobic-guide.md`의 선택지 규칙과 같음).
- **측정 kg 없음**(목표 모드 D1)
  - 새 줄에 나오는 kg은 사용자 설정(`min_skeletal_muscle_mass_kg`, `target_weight_kg`)뿐이다.
  - km는 러닝 거리다.
  - `goal_mode` 밖의 체성분 값은 읽지 않는다.
- **결측은 0이 아니다**: null과 unknown 상태는 `알 수 없음`이나 구체적인 상태 문구로 쓰고 0으로 채우지 않는다.
- **결정적 출력**: 같은 JSON이면 답장은 byte 단위로 같다. 시계, 환경, 파일을 읽지 않는다. 입력은 `daily --json` stdout뿐이다.
- **모양 검사**: 지금 요약처럼 `_object`/`_list`/`_text`/`_int`/`_number`/`_bool`로 타입을 검사한다. 타입이 틀리면 대체 답장이다.
  `goal_mode_version`이 1이 아닐 때 어떻게 할지는 Q6이다.
- **바뀌지 않는 동작**
  - 목표 파일이 깨졌으면 `daily`는 지금처럼 Garmin 전에 `오류:`로 exit 1이고 stdout이 비어 있다. bot은 v1처럼 stderr를 보낸다.
    이 기능은 이 경로를 바꾸지 않는다.
  - 메시지 나누기(4096 UTF-16 단위, 줄 경계)도 지금 규칙 그대로다.
- **코드 위치**(설계에서 확정): 데이터로 만드는 줄은 `presentation/telegram_summary.py`(예: `_goal_lines(recommendation)`)에
  두고, `daily_summary`의 성공 경로만 부른다. bot 고정 문구는 `domain/telegram_commands.py`에 둔다. CLI presenter는 바꾸지
  않는다(formatter import만).

## 인수 조건

- [ ] AC1: `recommendation`에 `goal_mode` key가 없는 `daily --json` 문서의 `/daily` 요약이 지금과 byte-identical이다. 기존
  golden 테스트(`test_daily_summary_of_the_daily_golden_matches_its_json` 등)가 수정 없이 통과한다.
- [ ] AC2: `goal_mode`가 있는 성공 문서(cut, 정체 `met`)에서 `/daily` 요약이 위 예시의 줄을 이 순서로 담는다. 순서는 영양 줄
  뒤의 머리줄, 체중 변화와 flag, 골격근량, 목표 진행, 유산소와 기준선, 러닝 알림, 정체와 선택지 a-d다. 숫자는 JSON 문자열을
  그대로 옮긴 것이다(`-0.11`, `25.0`). 분은 `:g`, km는 `_km` 형식이다.
- [ ] AC3: `weight_change`, `smm_floor`, `goal_progress`, `aerobic_minutes`, `plateau`의 각 status와 각 flag가 "규칙"의 문구를
  만든다(상태마다 테스트 한 개 이상). null 값은 `알 수 없음`으로 나오고 0으로 나오지 않는다. `insufficient_measurements`
  줄에는 "조건 미충족"이 없다.
- [ ] AC4: 러닝 줄은 `longer_than_threshold`인 러닝마다 하나씩만 나온다. 그런 러닝이 없으면 러닝 줄이 없다.
  `baseline_lower_bound`가 true이면 거리 없는 이전 러닝 표시가 붙는다.
- [ ] AC5: 정체 줄은 `plateau`가 null이 아닐 때만 나오고, 선택지는 `met`일 때만 JSON 순서대로 나온다. 선택지 머리줄에
  "순위 없음"이 있고, 새 줄에 "추천/먼저/가장/권장"이 없다. 선택지 c에 보상 섭취 문구("상쇄")가 있다(FATEX-04).
  gain/maintain 문서에는 정체 줄과 선택지가 없다.
- [ ] AC6: 유산소 줄과 기준선 줄에 영어(`stop`, `ceiling`, `limit`, `upper`, `max`)와 한국어(`상한`, `최대`, `최고`, `한계`,
  `한도`, `제한`, `멈`, `그만`, `충분`, `목표`, `달성`, `부족`, `초과`, `미달`) 금지어가 하나도 없다(테스트로 고정). 150/300과
  그 근거 ID는 `reference_minutes_per_week[]`에서 읽는다.
- [ ] AC7: 새 줄마다(머리줄 포함) 근거 ID나 `[design...]` 태그가 있다. 들여쓴 이어지는 줄은 위 줄을 따른다(선택지
  a-d와 기준선 줄은 자기 태그가 있다). 쓰는 ID는 모두 `docs/evidence/training-nutrition-evidence.md`에 있다.
- [ ] AC8: 새 줄에 측정 kg이 없다. kg은 `goal.min_skeletal_muscle_mass_kg`, `goal.target_weight_kg` 값으로만 나온다.
- [ ] AC9: 모르는 status, flag, option code, `meaning`이나 타입이 틀린 값이 오면 `SummaryUnavailableError`가 나고, bot은
  지금 대체 답장을 보낸다(bot이 멈추지 않음).
- [ ] AC10: `ok: false`인 `daily` 문서에는 `goal_mode`가 있어도 목표 줄이 없다(지금 실패 답장과 byte-identical).
- [ ] AC11: 다음은 목표가 있어도 byte-identical이다.
  - `/today`, `/today full`, `/daily full`, `/status` 답장
  - 모든 CLI 명령의 text와 `--json`(`recommend`, `daily`의 golden 포함)
  - 코치 LLM에 넘기는 입력(`recommend --json` 그대로)
- [ ] AC12: 같은 JSON으로 두 번 만든 요약이 byte-identical이다. 요약 함수는 시계, 환경 변수, 파일을 읽지 않는다.
- [ ] AC13: 품질 게이트 4개가 통과한다: `uv run --extra dev pytest`, `uv run ruff check .`, `uv run mypy src tests`,
  `git diff --check`.

## 설계에서 정할 것(열린 질문)

- **Q1 `/today`에도 붙일까?** `/today`와 `/daily`는 같은 본문 함수(`_plan_lines`)를 쓰고, `docs/telegram-bot.md`는
  `/daily` 본문을 "/today와 같은 본문"이라고 적는다. 이 스펙은 요청대로 `/daily`만 바꾸고 `/today`를 그대로 둔다(AC11).
  - 붙이면 `/today`에서도 보이고 두 본문이 같게 남는다.
  - 대신 AC11의 `/today` 항목이 바뀌고 output 범위가 넓어진다.
- **Q2 위치와 구분**: 목표 줄을 영양 줄 바로 뒤 `<pre>` 안에 빈 줄 하나를 두고 붙일지, 다른 곳(예: 주의 줄 근처)에 둘지
  정한다. UNKNOWN 묶음과 `기타 알림` 마지막 줄은 지금처럼 `<pre>` 밖 맨 끝이다.
- **Q3 영어 `reason`**: `weight_change`, `goal_progress`, `plateau`의 `reason`은 CLI의 영어 문장이다.
  - 지금 요약도 단계 오류와 `unavailable_reason`을 그대로 옮긴다.
  - 고를 것: 그대로 옮기기 / 줄에서 빼기(`알 수 없음`만) / 알려진 reason만 한국어로 짝짓기. 마지막은 문구가 바뀌면 깨지기 쉽다.
- **Q4 `not_set` 줄**: 골격근량 하한 `not_set`과 정체 확인 `not_set`을 한 줄로 보일지 뺄지 정한다. 휴대폰에서는 짧을수록 좋다.
  보이면 기능이 있다는 것을 알 수 있다.
- **Q5 PLAT-02 잡음 문구**: 정체 `met`일 때 "체중은 주 안에서 약 0.35 % 오르내림 [PLAT-02]" 한 줄을 넣을지 정한다. CLI는
  넣는다. 이 스펙의 기본안은 빼는 것이다(`/daily full`에 있음).
- **Q6 `goal_mode_version`**: 1이 아니면 대체 답장(모양 오류)으로 할지, 무시하고 key만 읽을지 정한다.
- **Q7 러닝 줄 개수**: 창(D-7..D)에서 표시된 러닝이 여러 개면 모두 보일지, `UNKNOWN_SUMMARY_CAP`처럼 3개 뒤에
  `외 N건 · /daily full`로 줄일지 정한다.
- **Q8 체중 변화 줄의 목표 범위**: `내 목표 0.3-0.5 · 근거 0.5-1.0 [MAINT-05]`을 함께 보일지 정한다(CLI에는 있음). 기본안은 flag만
  보이는 것이다.
- **Q9 문서 위치**: 기능 문서를 `docs/telegram-bot.md`의 새 절("v1.3 Telegram Goal Summary")로 할지, 새 `docs/telegram-goal-summary.md`로
  할지 정한다. `docs/aerobic-guide.md` Known issues의 "Telegram 요약(`/today`, `/daily`)은 바뀌지 않는다"를 고칠지(implementer는
  기능 문서만 고친다)도 정한다.
- **Q10 테스트 입력**: `goal_mode`가 있는 요약 테스트의 입력을 정한다. 기존 aerobic-guide 테스트처럼 임시 `MUSCLE50_HOME`에서
  만든 실제 `daily --json`/`recommend --json`을 쓸지, 합성 dict를 쓸지 고른다. 실제 CLI JSON이 key 이름 결합을 잡아 준다.

## 한계 / 후속 후보

- 요약은 goal 절의 일부만 보인다. 주당 set, 러닝/하체 간격, 수면, 진행 목표 변경, 측정 잡음 문구는 `/daily full`로 본다.
- 감량 속도와 정체는 InBody 측정 간격에 기대므로 `/daily`에서도 측정 뒤에야 바뀐다(목표 모드·유산소 가이드의 known issue와 같음).
- 요약은 `goal_mode` key 이름과 status 값에 결합된다. CLI JSON이 바뀌면 테스트가 잡고, 실행 중에는 대체 답장으로 낮아진다.
- 후속 후보:
  - `/today` 요약(Q1이 아니면)
  - Telegram `/goal`(목표와 goal 절만 짧게)
  - 코치가 정체 선택지를 읽어 대답하기
  - 아침 예약 요약
- migration이 없고 Garmin 동기화를 바꾸지 않으므로 production migration(gate 3)과 live Garmin 확인(gate 4)은 없다.
