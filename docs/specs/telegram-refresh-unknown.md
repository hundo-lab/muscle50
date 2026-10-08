---
id: telegram-refresh-unknown
title: Telegram Refresh All UNKNOWN v1.2
status: draft
migration: none
output_change: none
user_gates: [design, integration, live-garmin, push]
---

# Telegram Refresh All UNKNOWN v1.2

## 목적

- Telegram에서 명령 하나로 UNKNOWN 세트가 있는 운동을 모두 다시 받는다. 지금은 `/refresh <id>`를 운동마다 하나씩
  복사해서 보내야 한다.
- 근거: Telegram Mobile Replies v1.1 사용 피드백(2026-10-08, "refresh 명령어로 unknown들만 한번에 refresh되게").
  Garmin Connect에서 여러 운동의 이름을 고친 뒤 한 번에 반영하는 흐름을 만든다. `docs/goals.md` 1절(근육별 set
  집계 정확도)과 3절(채팅)에 기여한다.
- 자동 refresh는 여전히 하지 않는다(v1.1 결정). 사용자가 명령을 보낼 때만 한다.

## 범위 / Non-goals

- 범위:
  - bot 명령 `/refresh`(인자 없음): `/unknown`이 보여 주는 운동 목록 전체를 차례로 `garmin refresh`하고, 결과를 한
    답장으로 요약한다.
  - `/refresh <activity_id>`는 v1.1 그대로 둔다.
  - `/today`·`/daily`의 UNKNOWN 알림과 `/unknown` 답장 끝에 "모두 다시 받기: /refresh" 한 줄을 붙인다.
- Non-goals:
  - 자동 refresh 없음. `daily` 동작 변경 없음.
  - 대상 확장 없음. 대상은 `/unknown`과 같은 목록(recommend의 `strength.unknown_notices`: 최근 14일, 오늘 운동 제외)이다.
    UNKNOWN이 없는 운동이나 수영은 다시 받지 않는다.
  - 운동 이름 추측 없음. CLI 명령 추가 없음(`garmin refresh`는 그대로 하나씩 받는다). migration 없음.
  - 기존 CLI 출력 변경 없음.

## 명령 예시

```text
/refresh                  → UNKNOWN이 있는 최근 운동 모두 다시 받기
/refresh 24610155225      → 운동 하나만 (v1.1 그대로)
```

답장 예시(합성 값, 정확한 문구는 설계에서 정한다):

```text
refresh 실행 중: UNKNOWN이 있는 운동 3개를 Garmin에서 다시 받습니다. 끝나면 결과를 보냅니다.
```

```text
refresh 완료: 3개 중 3개 받음
• 10-05 근력: UNKNOWN 11 → 0세트
• 10-02 근력: UNKNOWN 16 → 4세트 (아직 남음)
• 09-23 근력: UNKNOWN 3 → 3세트 (Garmin에서 아직 안 고침)
남은 UNKNOWN: 2개 운동 · /unknown
```

대상이 없을 때:

```text
UNKNOWN 세트가 있는 운동이 없습니다 (최근 14일, 오늘 운동 제외). 다시 받을 것이 없습니다.
```

## 규칙

- 대상 목록:
  - `/unknown`과 같은 목록이다. `recommend --date <오늘> --json`의 `strength.unknown_notices`를 JSON 순서대로 쓴다.
  - 시작할 때 한 번 정한다. 실행 중에 목록이 바뀌어도 다시 계산하지 않는다.
  - 한 번에 다시 받는 수에 상한을 둔다(예: 10개). 넘는 운동은 받지 않고 답장에 "나머지 N개는 다시 /refresh"로
    알린다. 상한 값은 설계에서 정한다. Garmin 요청 수(운동당 약 4~5번)를 제한하기 위해서다.
- 실행:
  - 운동마다 v1.1의 `/refresh <id>`와 같은 경로를 쓴다(`garmin refresh <id>`를 in-process로 실행, 전후 UNKNOWN 수를
    read-only로 읽음).
  - 차례로 하나씩 실행한다(동시 실행 없음).
  - 쓰기 명령이므로 v1 규칙을 따른다: 시작 전 적용 안 된 migration 확인(있으면 아무것도 하지 않고 거부), handled update
    기록, 진행 안내 먼저.
  - 운동 하나가 실패하면(Garmin 오류, 저장 안 됨 등) 그 운동은 실패로 표시하고 다음 운동으로 넘어간다.
  - Garmin 로그인이 필요하면(EOF) 바로 멈추고, 남은 운동은 받지 않았다고 알린다. 로그인 안내는 v1.1과 같다.
  - 연속으로 여러 번(예: 3번) 실패하면 Garmin 쪽 문제(제한·장애)로 보고 멈춘다. 이 규칙은 기존 recovery 기간 동기화의
    "연속 실패 시 중단"과 같은 방식이다. 숫자는 설계에서 정한다.
  - Ctrl+C는 v1과 같다(바로 멈춤, exit 130). 이미 받은 운동은 저장된 상태로 남는다.
- 결과 답장:
  - 운동마다 한 줄: 날짜, 전후 UNKNOWN 수, 상태(받음 / 아직 남음 / 변화 없음 / 실패 + CLI 오류 그대로).
  - 전후 수를 읽지 못한 운동은 CLI 결과 첫 줄을 쓴다(v1.1과 같음). 추측하지 않는다.
  - 마지막 줄에 남은 UNKNOWN 운동 수와 `/unknown`.
  - Garmin 경고(`경고:`) 줄은 운동별로 그대로 붙인다.
  - 한국어, 고정폭 `<pre>`; 링크가 있으면 v1.1 형식을 따른다.
- 답장 형식과 분할은 v1.1과 같다(손실 없는 4096 분할).
- 테스트는 가짜 Telegram API와 가짜 Garmin connector만 쓴다.

## 인수 조건

- [ ] AC1: UNKNOWN 운동 3개가 있으면 `/refresh`가 3개를 차례로 다시 받고, 각 운동의 행이 `garmin refresh <id>`를
      하나씩 실행한 결과와 같으며, 답장에 운동마다 전후 UNKNOWN 수가 맞게 나온다.
- [ ] AC2: 대상이 없으면 Garmin을 부르지 않고 "다시 받을 것이 없습니다"를 답한다.
- [ ] AC3: 대상이 상한보다 많으면 상한만큼만 받고, 나머지 수를 답장에 알린다.
- [ ] AC4: 운동 하나가 실패해도 나머지는 계속 받고, 실패한 운동은 CLI 오류와 함께 표시된다. 연속 실패가 기준에 닿으면
      멈추고 남은 운동을 받지 않았다고 알린다.
- [ ] AC5: Garmin 로그인이 필요하면 첫 운동에서 멈추고, 로그인 안내를 답하며, DB와 RAW가 변하지 않는다.
- [ ] AC6: 적용 안 된 migration이 있으면 아무것도 받지 않고 v1의 migration 거부를 답한다.
- [ ] AC7: `/refresh <id>`, `/unknown`, `/today`, `/daily`의 기존 동작이 그대로이고(알림 끝 "모두 다시 받기" 한 줄 추가는
      예외), v1·v1.1 테스트가 통과한다.
- [ ] AC8: 기존 CLI 명령의 text·JSON 출력이 byte-identical이다.
- [ ] AC9: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- Garmin에서 아직 고치지 않은 운동도 목록에 있으면 다시 받는다(요청은 쓰지만 결과는 변화 없음으로 표시).
- 오늘 운동의 UNKNOWN은 다음 날부터 대상이다(v1.1과 같음). 오늘 운동은 `/refresh <id>`로 받는다.
- 후속 후보: 대상 범위 지정(`/refresh 7d` 등), 수영 이상 lap 재수신.
