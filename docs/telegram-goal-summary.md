# Telegram Goal Summary v1

스펙: `docs/specs/telegram-goal-summary.md`. 설계 결정 D1-D14: 2026-11-01 사용자 승인(모두 추천안, 스펙 예시와 다른 문구 표
포함). 근거 ID: `docs/evidence/training-nutrition-evidence.md`. 목표 모드(`docs/training-goal-mode.md`)와 유산소 가이드
(`docs/aerobic-guide.md`)의 goal 절을 Telegram `/daily` 요약(`docs/telegram-bot.md` v1.1)에 짧게 옮긴다.

## 목적과 non-goal

- 목표 파일(`config\training_goal.json`)이 있으면, 성공한 `/daily` 답장의 `<pre>` 본문 끝(영양 줄 뒤, 빈 줄 하나 다음)에 목표
  줄 몇 개가 붙는다.
  - 목표 머리줄
  - 체중 변화(%/주)와 flag
  - 골격근량 하한
  - 목표 진행
  - 지난 7일 러닝·수영 유산소 분과 150/300 기준선
  - 표시된 러닝 길이 알림
  - 정체 확인(cut만; 조건 충족이면 순위 없는 선택지 a-d)
- 값은 모두 bot이 이미 받는 `daily --json`의 `recommendation.goal_mode`에서 그대로 옮긴다. 새 계산, 새 반올림, 판정은 없다.
- Non-goal:
  - `/today`는 바뀌지 않는다(D1). 코치의 대체 답장이 `/today` 요약을 쓰기 때문이다(`application/telegram_llm.py`).
  - CLI 출력(`recommend`, `daily`, `goal`, `nutrition` 등의 text와 `--json`)은 바뀌지 않는다. 새 JSON key 없음.
  - 주당 set, 러닝/하체 간격, 수면, 진행 목표 변경은 요약에 넣지 않는다. `/daily full`에 있다.
  - `/goal` 명령, 예약 알림, 처방, 측정 kg 없음. Migration 없음. Garmin 동기화 변경 없음. LLM 없음.

## 켜지는 조건

- `daily["ok"]`가 true이고 `daily["recommendation"]`에 `goal_mode` key가 있을 때만 붙는다. CLI는 목표가 없으면 이 key를
  넣지 않는다.
- key가 없으면 답장은 이 기능 전과 byte-identical이다. 실패한 `daily`(`ok: false`)는 지금처럼 계획을 만들지 않으므로 목표 줄도
  없다.

## 예시 `/daily` 답장(합성 값, cut, 정체 조건 충족)

```text
<pre>daily 11-20: 동기화 완료 (새 운동 1, 회복 1일 갱신)

근력: legs · 약 32분 · 9세트
 1. SQUAT/BARBELL_BACK_SQUAT 3x10 @ 60 kg
회복: normal (readiness HIGH 82, HRV BALANCED, 수면 07:12:00)
수영: easy_continuous 약 800 m (마지막 수영 3일 전)
영양: 식사 2끼 · kcal 1450 / 목표 2500-2700 (below_range, 최소까지 1050)

목표: cut (내 설정) [design: user setting]
체중 변화 11-06 -> 11-20: -0.05 %/주 [MAINT-05; design]
  -> 내 목표 감량 0.3-0.5 %/주 밖 [design: user setting]
골격근량: 내 하한 41 kg 아래 (InBody 11-20) [design: user setting]
목표 진행: 체지방 18 %까지 -0.42 %/주 필요 (기한 2027-02-28), 실제 -0.05 %/주 [design: fat-free mass assumed constant]
유산소(러닝·수영) 11-13..11-19: 200분 이상 (중강도 140 + 고강도 60) [EXL-03; design]
  하한: intensity minutes 없는 활동 1개 빠짐 [design]
  기준선: 150분 지침 최소(고강도면 75분) [EXL-03] · 300분 연구된 범위의 끝 [FATEX-02]
러닝 길이 11-19: 12.5 km, 지난 30일 최장보다 25.0 % 김 [RUNPROG-03: 관찰 연구의 연관, 알림만]
정체 확인: 조건 충족 (내 설정 3주, 0.3 %/주 미만 감량, InBody 구간 2개 이상) [design: user setting; PLAT-01, PLAT-02]
  체중은 주 안에서 약 0.35 % 오르내림, 같은 기기·조건 InBody끼리 비교 [PLAT-02]
  선택지, 순위 없음 (표시 순서) [PLAT-06]; 내 선호·지킬 수 있는 것도 정당한 기준 [FATEX-07]
  a) 식사 기록이 빠짐없는지 확인 (빠진 끼니, 일반식, 주말) [PLAT-04]
  b) 하루 100-150 kcal 덜 먹기 [design]; 결손은 약 500 kcal/일 이하, muscle50은 결손을 잴 수 없음 [PRO-04]
  c) 섭취는 두고 활동 늘리기: 같은 결손이면 같은 지방 감소, 활동 뒤 더 먹으면 결손 일부가 상쇄될 수 있음(개인차 큼) [FATEX-05, FATEX-04]
     러닝 길이·러닝/하체 3시간 간격 주의 [RUNPROG-03, CONC-04]
  d) 1주 유지 휴식: 체중이 글리코겐·수분으로 오를 수 있고 기한이 1주 늦어짐 [PLAT-05]</pre>
기타 알림 6건 · 전체: /today full
```

- maintain/gain: `plateau`가 null이고 flag도 없으므로 정체 줄과 `->` 줄이 없다. 머리줄은 `목표: maintain (내 설정) [design: user
  setting]` 또는 `목표: gain (내 설정) [design: user setting]`이다.
- UNKNOWN 운동 묶음과 `기타 알림` 마지막 줄은 지금처럼 `<pre>` 밖 맨 끝이다. 메시지 나누기(4096 UTF-16 단위)도 그대로다.

## 줄과 상태의 짝

`M`은 JSON 날짜의 `MM-DD`다. 값은 JSON 문자열 그대로이고, 분은 `:g`(`140.0`이 아니라 `140`), km는 CLI의 `goal_terminal._km`
(0.01 HALF_EVEN)이다. 표에 없는 값은 아래 "모양 검사"를 본다.

- **머리줄**: `목표: {goal.mode} (내 설정) [design: user setting]`. `mode`는 `cut`/`maintain`/`gain`.
- **`weight_change`**
  - `known`: `체중 변화 {from M} -> {to M}: {percent_per_week} %/주 [MAINT-05; design]`
  - `unknown`: `체중 변화: 알 수 없음 ({reason}) [MAINT-05; design]`
  - flag마다 한 줄(JSON 순서, 빼지 않음):
    - `faster_than_evidence`: `  -> 감량이 주 {evidence_range_percent_per_week.maximum} %보다 빠름: 근육 유지에 불리할 수 있음 [MAINT-05]`
    - `outside_user_target`: `  -> 내 목표 감량 {goal.weekly_loss_percent.minimum}-{maximum} %/주 밖 [design: user setting]`
    - `gaining`: `  -> 감량 중 체중 증가 [design]`
- **`smm_floor`**(모두 `[design: user setting]`; `floor_kg`는 사용자 설정이고 측정값이 아니다)
  - `at_or_above` / `below`: `골격근량: 내 하한 {floor_kg} kg 이상` / `아래` + ` (InBody {M})`
  - `unknown`: `골격근량: 내 하한 {floor_kg} kg 대비 알 수 없음 (InBody 골격근량 없음)`
  - `not_set`: `골격근량 하한: 설정 안 함`
- **`goal_progress`**(태그 T: `assumption`이 있으면 `[design: fat-free mass assumed constant]`, 없으면 `[design]`. 목표는
  `체지방 {pct} %` 또는 `체중 {kg} kg`, 둘 다 사용자 설정)
  - `known`: `목표 진행: {목표}까지 {required} %/주 필요 (기한 {target_date}), 실제 {actual} %/주 T`. `actual`이 null이면 `실제 알 수 없음`.
  - `reached`: `목표 진행: {목표} 도달 (InBody {M}) T`
  - `deadline_passed`: `목표 진행: 기한 {target_date} 지남 T`
  - `not_set`: `목표 진행: 계산 안 함 (목표와 기한이 둘 다 있어야 함) T`
  - `unknown`: `목표 진행: 알 수 없음 ({reason}) T`
- **`aerobic_minutes`**(P = `유산소({러닝·수영}) {from M}..{to M}`; `activity_types`의 `running`은 러닝, `swimming`은 수영)
  - `known`: `P: {total}분 (중강도 {m} + 고강도 {v}) [EXL-03; design]`
  - `lower_bound`: `P: {total}분 이상 (중강도 {m} + 고강도 {v}) [EXL-03; design]`, 다음 줄 `  하한: ... [design]`. 하한 이유는
    0이 아닌 것만 ` · `로 잇는다: `intensity minutes 없는 활동 N개 빠짐`, `중강도·고강도 중 하나만 있는 활동 N개`. 한 칸이
    null이면 그 칸은 `알 수 없음`이다.
  - `unknown`: `P: 알 수 없음 (활동 N개 모두 intensity minutes 없음) [EXL-03; design]`
  - `none_stored`: `P: 저장된 활동 없음 (동기화 안 됐을 수 있음, 0분이 아님) [EXL-03; design]`
  - 상태와 상관없이 마지막 줄: `  기준선: 150분 지침 최소(고강도면 75분) [EXL-03] · 300분 연구된 범위의 끝 [FATEX-02]`. 분과
    태그는 `reference_minutes_per_week[]`에서 JSON 순서로 읽는다(`meaning`: `guideline_minimum` / `end_of_studied_range`).
    `75`는 CLI 문구("or 75 vigorous")를 그대로 옮긴 고정 문구다.
- **`run_length`**: `status == longer_than_threshold`인 러닝마다 한 줄, 개수 제한 없음(주의 표시, D7):
  `러닝 길이 {M}: {km} km, 지난 {previous_days}일 최장보다 {increase_percent} % 김 [RUNPROG-03: 관찰 연구의 연관, 알림만]`.
  `baseline_lower_bound`가 true이면 태그 앞에 ` (이전 러닝 N개 거리 없음, 최장이 더 길 수 있음)`. `within`, `no_previous_run`,
  `no_distance`, 빈 목록은 줄이 없다.
- **`plateau`**(null이면 줄 없음. C = `내 설정 {weeks}주, {below_loss_percent_per_week} %/주 미만 감량, InBody 구간 {min_intervals}개 이상`)
  - `met`: `정체 확인: 조건 충족 (C) [design: user setting; PLAT-01, PLAT-02]`, 측정 잡음 줄(D5, `noise.within_week_weight_percent`),
    선택지 머리줄, 선택지(JSON 순서).
  - `not_met`: `정체 확인: 조건 미충족 (C) [design: user setting; PLAT-01, PLAT-02]`
  - `insufficient_measurements`: `정체 확인: 판단 못 함, 정체 여부 모름 ({reason}) [design: user setting; PLAT-02]`. "정체 아님"으로
    읽히지 않는다.
  - `unknown`: `정체 확인: 알 수 없음 ({reason}) [design: user setting]`
  - `not_set`: `정체 확인: 설정 안 함 (근거로 정한 기준 없음; goal set ... --plateau-weeks N) [design; PLAT-01]`
- **선택지**(글자는 code마다 고정, 순서는 JSON 순서이고 순위가 아니다)
  - `check_meal_logging` a, `eat_less` b(`step_kcal_per_day`, `deficit_limit_kcal_per_day`), `keep_intake_add_activity` c(두 줄,
    `run_legs_gap_hours`), `maintenance_week` d(`weeks`). 문구는 위 예시와 같다.

### 스펙 예시와 다른 문구(설계 3a절, 승인됨)

- 선택지 머리줄에 FATEX-07 내용(내 선호·지킬 수 있는 것도 정당한 기준)을 적는다.
- c에 FATEX-05 내용(같은 결손이면 같은 지방 감소)을 적고 두 줄로 나눠 각 줄이 자기 태그를 단다.
- b는 muscle50이 결손을 잴 수 없다고 적는다. d는 글리코겐·수분으로 체중이 오를 수 있고 기한이 늦어진다고 적는다(PLAT-05).
- 유산소 `unknown`은 "활동 N개 모두"라고 적는다. 머리줄에 세는 종류 `(러닝·수영)`를 적어, 사이클·걷기가 빠진 것이 0분으로 읽히지
  않게 한다.
- 정체 머리줄에 `InBody 구간 2개 이상`을 적어 PLAT-02 태그가 가리키는 내용이 있다. `insufficient`는 "정체 여부 모름"이다.
- 목표 진행 `not_set`은 "목표와 기한이 둘 다 있어야 함"이다(목표만 있고 기한이 없어도 not_set이다).
- 체중 변화 `outside_user_target`에 사용자 목표 범위를 적는다(D8).

## 규칙

- **근거 태그**: 모든 줄에 근거 ID나 `[design...]` 태그가 있다. 태그는 같은 내용을 보여 주는 CLI goal 절 줄
  (`presentation/goal_terminal.py`)의 태그를 따르고, ID는 근거 문서에 있는 것만 쓴다.
- **선택지 근거는 JSON과 맞아야 한다**(D12): 각 option의 `evidence`가 문구를 쓸 때의 ID 목록(`aerobic_guide.plateau_options()`
  순서)과 같아야 하고, `choice_evidence`는 `["PLAT-06", "FATEX-07"]`, `eat_less.deficit_measurable`은 `false`여야 한다. 다르면
  모양 오류다. 그래서 ID가 그 ID가 말하는 내용 옆에만 붙는다.
- **선택지는 대등하다**(PLAT-06, FATEX-05, FATEX-07): "순위 없음 (표시 순서)"라고 적고, 추천/먼저/가장/권장 같은 말을 쓰지 않는다.
  c의 보상 섭취 문구("상쇄", FATEX-04)를 줄이지 않는다.
- **150/300은 기준선이다**(FATEX-02, `docs/aerobic-guide.md` D8): 유산소·기준선 줄에 stop, ceiling, limit, upper, max, 상한, 최대,
  최고, 한계, 한도, 제한, 멈, 그만, 충분, 목표, 달성, 부족, 초과, 미달을 쓰지 않는다. 숫자를 나란히 적기만 한다.
- **측정 kg 없음**(목표 모드 D1): kg은 `goal.min_skeletal_muscle_mass_kg`(= `smm_floor.floor_kg`)과 `goal.target_weight_kg`뿐이다.
- **결측은 0이 아니다**: null과 unknown은 `알 수 없음`이나 상태 문구다.
- **결정적**: 같은 JSON이면 같은 byte. 요약은 시계, 환경 변수, 파일을 읽지 않는다.
- **모양 검사**(D6, D12): `goal_mode_version`이 1이 아니거나, `goal_mode`가 object가 아니거나, 모르는 status·flag·option
  code·`meaning`·활동 종류, 타입이 틀린 값(예: 문자열 분, 숫자 %), `met`이 아닌데 선택지가 있음, 이유 없는 `lower_bound`이면
  `ValueError`/`TypeError` → `SummaryUnavailableError`. bot은 지금의 대체 답장(`오류: daily는 끝났지만 결과를 요약하지
  못했습니다 (exit N). 저장된 데이터로 본 전체 계획: /today full`)을 보낸다. 줄을 조용히 빼지 않는다.
- 코드: `presentation/telegram_summary.py`의 `_goal_lines`와 `_goal_*` 도우미, 한국어 표(`_OPTION_EVIDENCE`,
  `_REFERENCE_MEANINGS`, `_AEROBIC_TYPE_NAMES`)는 데이터로 만드는 줄이라 이 파일에 둔다(D14). `daily_summary`의 성공 경로만
  부른다.

## 바뀌지 않는 출력

- 목표 없는 `/daily`, 실패한 `/daily`.
- `/today`, `/today full`, `/daily full`, `/status`, `/status full`, `/unknown`, `/refresh`, `/sync`, `/help`.
- 코치 LLM 입력(`recommend --json` 그대로)과 코치의 대체 답장.
- 모든 CLI 명령의 text와 `--json`, golden 파일.

## 테스트

`tests/test_telegram_goal_summary.py`: 유산소 가이드 시나리오(`aerobic_builders`, 임시 `MUSCLE50_HOME`, 합성 값)의 실제
`recommend --json`을 `daily_2026-10-02.json` golden 봉투에 넣고, 상태마다 바꾼 사본을 쓴다. 실제 `daily --json`(가짜 Garmin
계정) 하나도 요약한다. 네트워크 없음.

## Known issues / limitations

- **status 값에 강하게 결합된다.** CLI가 `goal_mode`에 새 status, flag, option code, `meaning`을 더하면 이 요약을 고칠 때까지
  목표가 있는 모든 `/daily`가 대체 답장이 된다(새 key는 무해하다). option code는 테스트가 `plateau_options()`와 비교하지만,
  status 문자열은 enum이 없어 테스트가 모두 셀 수 없다.
- **`telegram run`을 다시 시작해야 한다.** 실행 중인 bot은 통합 전 코드를 계속 쓴다.
- **휴대폰 화면 폭**: 영어 `reason`과 태그가 길다. Telegram 앱에서 `<pre>` 줄이 어떻게 접히는지는 확인하지 않았다. bot을 다시
  시작한 뒤 눈으로 확인하기를 권한다.
- **영어 `reason`**: `weight_change`, `goal_progress`, `plateau`의 이유는 CLI의 영어 문장 그대로다(D3).
- **`MM-DD`**: 연도 경계에서 모호하다(기존 요약과 같음). 목표 기한은 전체 날짜로 적는다.
- **일부만 보인다**: 주당 set, 러닝/하체 간격, 수면, 진행 목표 변경, 정체 구간별 속도는 `/daily full`로 본다. 감량 속도와 정체는
  InBody를 잰 뒤에야 바뀐다.
- 후속 후보: `/today` 요약에도 붙이기, Telegram `/goal`, 코치가 정체 선택지를 읽어 대답하기, 아침 예약 요약.
