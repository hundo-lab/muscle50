---
id: telegram-mobile
title: Telegram Mobile Replies v1.1
status: draft
migration: none
output_change: additive
user_gates: [design, integration, live-garmin, push]
---

# Telegram Mobile Replies v1.1

## 목적

- Telegram에서 `/daily`, `/today`, `/status`의 답장이 너무 길다. `/daily` 하나가 CLI 전체 리포트(100줄 이상)를 그대로 보낸다.
  휴대폰에서 바로 읽을 수 있는 짧은 요약을 기본으로 보내고, 전체 리포트는 `full`을 붙여서 본다.
- Garmin에서 운동 이름이 UNKNOWN인 세트는 근육별 세트 수와 진척 계산에서 빠진다. 지금은 사용자가 리포트 아래쪽의 긴
  notice를 읽고, Garmin Connect에서 고친 다음, PC에서 `muscle50 garmin refresh <id>`를 실행해야 한다.
  bot이 UNKNOWN을 짧게 알려 주고, Garmin Connect 링크와 `/refresh <id>` 명령으로 휴대폰에서 고칠 수 있게 한다.
- 근거: Telegram Command Bot v1 사용자 피드백(2026-10-07, `/daily` 답장이 너무 김; refresh를 매번 PC에서 해야 함).
  `docs/goals.md` 3절(채팅으로 묻기)과 1절(근육 증가 판단의 정확도)에 기여한다. UNKNOWN 세트가 줄수록 근육별 set
  집계가 정확해진다.
- 자동 refresh는 하지 않는다. 운동마다 Garmin 요청이 4~5번 필요해서, 매번 모든 운동을 다시 받으면 부하가 크다.
  사용자가 Garmin에서 고친 운동만 `/refresh`로 다시 받는다(2026-10-07 사용자 결정).

## 범위 / Non-goals

- 범위:
  - `/daily`, `/today`, `/status`의 **요약 답장**이 기본이 된다. 뒤에 `full`을 붙이면(`/daily full`, `/today full`,
    `/status full`) v1처럼 CLI text 전체를 보낸다.
  - **UNKNOWN 알림**: `/daily`와 `/today` 요약 끝에, 최근 UNKNOWN 세트가 있는 운동마다 한 줄씩 붙인다. 각 줄에는 Garmin
    Connect 링크와 `/refresh <id>`를 넣는다. 같은 내용만 따로 보는 `/unknown` 명령을 추가한다.
  - 새 bot 명령 `/refresh <activity_id>`: `muscle50 garmin refresh <activity_id>`와 같다. 끝나면 결과를 요약해 답한다.
- Non-goals:
  - 자동 refresh 없음. `daily`의 동작은 바꾸지 않는다.
  - 운동 이름 추측이나 자동 분류 없음. UNKNOWN은 사용자가 Garmin에서 고친다.
  - LLM 없음. 요약은 정해진 규칙으로 만든다.
  - 새 계산이나 판단 없음. 요약에 나오는 모든 숫자와 상태는 같은 명령의 JSON 결과에서 그대로 가져온다.
  - 기존 CLI 명령의 text·JSON 출력 변경 없음. 요약은 bot 답장에만 있다.
  - migration 없음. `/day`, `/show`, `/log`, `/void`, `/inbody`의 답장은 v1 그대로다.
  - 예약 알림(아침 자동 push) 없음. 후속 후보로 둔다.

## 명령 예시

Telegram(합성 값):

```text
/daily            → 동기화 후 요약 (기본)
/daily full       → v1과 같은 CLI 전체 text
/today            → 오늘 추천 요약
/today full       → recommend 전체 text
/status           → 영양 요약
/status full      → nutrition status 전체 text
/unknown          → 최근 UNKNOWN 세트가 있는 운동 목록 (Garmin 링크 + /refresh)
/refresh 24610155225 → garmin refresh 24610155225
```

`/daily` 요약 예시(합성 값, 정확한 문구와 줄 순서는 설계에서 정한다):

```text
daily 10-07: 동기화 완료 (새 운동 0, 회복 2일 갱신)

오늘 근력: 하체 · 약 32분
 1. SQUAT 3x12 @ ~40 kg (무게 불확실)
 2. DEADLIFT/BARBELL_DEADLIFT 3x12 @ 40 kg
 3. LUNGE 3x12 @ ~40 kg (지난 무게 확인)
회복: normal (readiness MODERATE 64, HRV BALANCED, 오늘 수면 기록 없음)
수영: 800 m 가볍게 (마지막 수영 20일 전)
영양: 오늘 기록 없음

확인 필요: Garmin UNKNOWN 세트
• 10-05 근력 11세트: https://connect.garmin.com/modern/activity/24610155225
  고친 뒤: /refresh 24610155225
• 10-02 근력 16세트: https://connect.garmin.com/modern/activity/24576105658
  고친 뒤: /refresh 24576105658
기타 알림 6건 · 전체: /today full
```

`/daily`가 실패한 경우(합성 예시). 실패한 단계와 CLI 오류를 그대로 보여 주고 추천 요약은 만들지 않는다(daily 규칙과 같다).

```text
daily 10-07: 실패 (recovery 단계)
  recovery: <CLI가 출력한 오류 줄 그대로>
추천은 만들지 않았습니다. 전체: /daily full
```

`/refresh` 답장 예시(합성 값):

```text
refresh 24610155225 완료: 10-05 근력, UNKNOWN 11 → 0세트
```

## 규칙

- 데이터 출처:
  - 요약은 같은 명령의 **JSON 결과**를 in-process로 받아 만든다. `daily --json`, `recommend --json`,
    `nutrition status --json`을 v1과 같은 방식(`cli.main`)으로 부른다. text 리포트를 파싱하지 않는다.
  - 요약 안의 숫자, 무게, 상태 이름, 운동 label은 JSON 값을 그대로 쓴다. 다시 계산하거나 반올림을 바꾸지 않는다.
  - JSON에 없는 값은 `알 수 없음`으로 쓴다. 0으로 채우지 않는다.
- 요약에서 빠뜨리면 안 되는 것:
  - 무게 신뢰도가 low이거나 지난 무게를 확인해야 하는 운동 표시(`~` 또는 짧은 한국어 주의).
  - 회복 level과 그 근거. 오늘 수면 기록이 없음(partial row) 같은 결측 표시.
  - recovery level이 normal이 아니면 그 level을 맨 위 가까이에 둔다.
  - sync 단계 실패. 실패하면 추천 요약을 만들지 않는다.
  - notice 건수. 요약에 없는 notice는 "기타 알림 N건"으로 센다.
- UNKNOWN 알림:
  - 대상은 `recommend` JSON의 `strength_unknown_exercise` notice다. 운동(`source_activity_id`)마다 한 줄씩 쓴다.
    세트 수는 notice가 가리키는 값을 쓴다. 문장 파싱이 필요하면 설계에서 JSON에 구조화된 값을 추가할지 정한다
    (`recommend --json`에 key를 추가하면 output_change additive이고, 기존 key는 바꾸지 않는다).
  - 링크는 `https://connect.garmin.com/modern/activity/<id>`다. 이 URL 형식은 live 확인에서 실제로 열리는지 본다.
  - 기간은 recommend가 이미 보는 기간(history)을 그대로 쓴다. 새 기간 규칙을 만들지 않는다.
  - 운동이 많으면 최근 N개만 줄로 보이고 나머지는 "외 N개 · /unknown"으로 줄인다. N은 설계에서 정한다.
- `/refresh <activity_id>`:
  - id는 숫자만 받는다. 형식이 틀리면 사용법을 답한다.
  - `garmin refresh`와 같은 경로를 쓴다. Garmin 네트워크와 쓰기가 있으므로 v1의 쓰기 명령 규칙을 따른다: 적용 안 된
    migration이 있으면 거부, 처리 전 handled update 기록, 진행 안내 먼저, Garmin 로그인이 필요하면 v1과 같은 안내.
  - 결과 요약에는 refresh 전후의 UNKNOWN 세트 수를 넣는다. 전후 값을 구할 수 없으면 CLI 결과 첫 줄만 보낸다.
    추측하지 않는다.
  - 저장된 activity가 아니면 CLI의 거부 메시지를 그대로 답한다.
- `full`:
  - `/daily full`, `/today full`, `/status full`의 답장은 v1과 byte 단위로 같다(CLI text 그대로).
  - `full` 외의 다른 인자는 사용법 답장이다.
- 언어와 형식:
  - 요약과 알림 문구는 한국어다(v1 D4와 같다). 운동 label, 상태 값(normal, MODERATE 등), 숫자는 JSON 값을 그대로 쓴다.
  - 고정폭 `<pre>`는 그대로 쓴다. 링크가 Telegram에서 눌리게 하는 방법(`<pre>` 밖에 두기, `<a>` 사용 등)은 설계에서
    정한다.
  - 요약은 한 메시지(4096자) 안에 들어가는 것을 목표로 하되, 넘으면 v1의 손실 없는 분할 규칙을 따른다.
- 같은 입력이면 요약은 byte 단위로 같다.
- 테스트는 v1처럼 가짜 Telegram API와 가짜 Garmin connector만 쓴다. 실제 계정 확인은 live-garmin 게이트에서 한다.

## 인수 조건

- [ ] AC1: `/daily`, `/today`, `/status`의 기본 답장이 요약이다. 요약의 모든 숫자·무게·상태·label이 같은 날짜와 데이터의
      `daily --json`, `recommend --json`, `nutrition status --json` 값과 일치한다(테스트가 JSON에서 기대값을 만든다).
- [ ] AC2: `/daily full`, `/today full`, `/status full`의 답장이 v1 답장과 byte-identical이다.
- [ ] AC3: 무게 신뢰도 low, recovery partial(수면 없음), recovery level이 normal이 아닌 경우, 결측 값이 각각 요약에
      표시된다. 어떤 결측도 0으로 나오지 않는다.
- [ ] AC4: `daily` 단계가 실패하면 요약이 실패한 단계와 CLI 오류를 보여 주고 추천 요약을 만들지 않는다.
- [ ] AC5: UNKNOWN notice가 있는 운동마다 `/daily`·`/today` 요약과 `/unknown`에 한 줄이 나오고, 각 줄에 Garmin Connect
      링크와 `/refresh <id>`가 있다. UNKNOWN이 없으면 알림 절이 없다(`/unknown`은 "없음"을 답한다).
- [ ] AC6: `/refresh <id>`가 가짜 connector로 `garmin refresh <id>`와 같은 행을 저장하고, 전후 UNKNOWN 세트 수를 담은
      요약을 답한다. 형식이 틀린 id, 저장 안 된 id, 적용 안 된 migration, Garmin 로그인 필요는 각각 정해진 답장과 함께
      DB를 바꾸지 않는다.
- [ ] AC7: 같은 입력으로 요약을 두 번 만들면 byte-identical이다.
- [ ] AC8: 기존 CLI 명령(`recommend`, `daily`, `nutrition *`, `garmin *`, `inbody *`)의 text와 JSON 출력이 이 기능 전과
      byte-identical이다. `recommend --json`에 key를 추가한다면 끝쪽 추가만 있고 기존 key와 값은 같다.
- [ ] AC9: v1의 `/day`, `/show`, `/log`, `/void`, `/inbody`, `/help` 동작과 v1 테스트가 그대로 통과한다
      (`/help` 목록에 새 명령이 추가되는 것은 예외).
- [ ] AC10: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- 자동 refresh가 없으므로 Garmin에서 고친 운동은 사용자가 `/refresh`를 보내야 반영된다.
- Garmin Connect 링크가 휴대폰에서 웹으로 열릴지 앱으로 열릴지는 기기 설정에 따른다.
- 요약은 추천 리포트의 일부만 보여 준다. 근거와 전체 notice는 `full`로 본다.
- 후속 후보:
  - 최근 며칠의 UNKNOWN 운동만 자동 refresh(요청 수 상한 포함).
  - 아침 자동 요약 push.
  - 수영 UNKNOWN·이상 lap 알림, PLYO 같은 taxonomy 없는 운동 알림.
  - 자유 문장(LLM) v2.
