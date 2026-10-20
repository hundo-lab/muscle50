---
id: daily-catch-up
title: Daily Catch-up and Telegram Range Sync v1
status: draft
migration: none
output_change: additive
user_gates: [design, integration, live-garmin]
---

# Daily Catch-up and Telegram Range Sync v1

## 목적

- `daily`(CLI, Telegram `/daily`)가 **마지막으로 동기화된 날 다음부터** 받아오게 한다. 며칠 `daily`를 안 돌려도 빠진 날이
  남지 않는다.
- 상한보다 오래 빠진 날은 Telegram에서 기간을 정해 받아올 수 있게 한다(`/sync`).
- 근거: 2026-10-20에 확인해 보니 10-09~10-18 열흘이 운동·회복 모두 `not synced`였다. `daily`는 늘 D-1..D만 받아서 그 사이
  운동(러닝 4회, 근력 2회 등)이 없었고, bot은 "마지막 운동 10-07", "회복 기록 없음"이라고 답했다. 2026-10-21에 CLI
  `garmin activities --from/--to`, `garmin recovery --from/--to --yes`로 직접 채웠다(운동 10건, 회복 10일). Telegram에는 이런
  명령이 없다. `docs/sync-coverage.md`의 날짜별 기록이 이미 있다.
- `docs/goals.md`의 매일 루프(동기화 → 추천)가 빠진 날 없이 돌게 한다.

## 범위 / Non-goals

- 범위:
  1. **`daily` 이어 받기**: 시작일을 "운동·회복이 모두 `synced`인 마지막 날의 다음 날"로 정한다. 단 D-1보다 늦지 않고(지금과
     같은 최소 범위), D-7보다 이르지 않다(상한 7일, 회복 요청 약 9회/일). 기록이 하나도 없으면 지금처럼 D-1이다.
  2. 상한에 걸려 더 오래된 빠진 날이 남으면 `daily` 출력 끝에 한 줄로 알린다: 빠진 기간과 받아오는 방법(CLI `garmin activities`
     /`garmin recovery --from --to`, Telegram `/sync`).
  3. **Telegram `/sync FROM TO`**: 날짜(`YYYY-MM-DD` 또는 `MM-DD`, 올해 기준) 기간의 운동, load metrics, 회복을 받는다.
     추천은 만들지 않는다. 최대 31일. 7일을 넘으면 바로 실행하지 않고 "N일, Garmin 요청 약 M회" 답장과 누를 수 있는 확인
     명령(예: `/sync_ok_<짧은 id>`, 10분 유효)을 보낸다.
  4. `/sync` 답장은 짧은 한국어 요약이다: 기간, 운동 새로 저장 N건, 회복 새로 저장 N일, 실패 날짜.
  5. `/daily` 답장과 LLM 동기화 안내(`sync_request`)는 남은 빠진 날이 있으면 `/sync` 명령을 같이 보여 준다.
- Non-goals:
  - Garmin 요청 방식, 정규화, RAW 저장, coverage 기록 규칙은 바꾸지 않는다(기존 use case를 그대로 부른다).
  - `garmin latest`, `garmin refresh`는 바꾸지 않는다.
  - 자동 예약 실행(스케줄러) 없음. LLM이 동기화를 실행하지 않는다(LLM은 명령을 안내만 한다).
  - migration 없음.

## 명령 예시

```powershell
muscle50 daily
muscle50 daily --json
```

예상 text 출력에 더해지는 줄(합성 값, 정확한 문구는 설계에서 정한다):

```text
Sync range: 2026-10-14..2026-10-21 (caught up from last synced day 2026-10-13; limit 7 days)
Older unsynced days: 2026-10-09..2026-10-12. Run: muscle50 garmin activities --from 2026-10-09 --to 2026-10-12
  and muscle50 garmin recovery --from 2026-10-09 --to 2026-10-12 (Telegram: /sync 10-09 10-12)
```

Telegram(합성 값):

```text
사용자: /sync 10-09 10-18
bot:   10일(10-09 ~ 10-18), Garmin 요청 약 90회입니다. 받아오려면 누르세요(10분 유효):
       /sync_ok_a41c
사용자: /sync_ok_a41c
bot:   동기화했습니다: 10-09 ~ 10-18
       운동 새로 저장 10건 · 회복 새로 저장 10일 · 실패 없음
       오늘 추천: /daily
```

JSON(`daily --json`, additive, 끝에 key 추가):

```json
{
  "catch_up": {"from": "2026-10-14", "limit_days": 7, "older_unsynced": {"from": "2026-10-09", "to": "2026-10-12"}}
}
```

## 규칙

- 이어 받기 시작일은 coverage 기록(`docs/sync-coverage.md`)만 읽어 결정적으로 정한다. `partial`, `failed`, `not_synced`는
  "동기화 안 됨"으로 본다. 기록이 없는 아주 오래된 날(설치 전)은 빠진 날로 보지 않는다: 이어 받기는 D-7 안에서만 본다.
- 이어 받은 기간도 지금 `daily`와 같은 순서(로그인 한 번, 운동, load metrics, 회복, 추천)와 실패 정책을 따른다.
- `daily --after-workout`도 운동만 같은 규칙으로 이어 받을지는 설계에서 정한다(추천: 운동 coverage만 보고 이어 받기).
  `daily --date D`는 그 D를 기준으로 같은 규칙을 쓴다.
- `/sync` 날짜 검증: 시작 ≤ 끝, 끝 ≤ 오늘, 31일 이하. 거부하면 `오류:` 답장이고 Garmin을 부르지 않는다.
  확인 명령은 한 번만 쓰이고, 만료되거나 다른 chat에서 오면 거부한다.
- `/sync`는 허용된 chat에서만, bot이 이미 쓰는 Garmin 로그인으로 돈다. 비밀번호나 token을 묻거나 출력하지 않는다.
- 빠진 날이 없으면 `daily` 출력은 지금과 byte-identical이다(D-1..D, 새 줄 없음).

## 인수 조건

- [ ] AC1: coverage에 D-4..D-2가 `not synced`이고 D-5가 `synced`면 `daily`는 D-4..D를 받는다(가짜 Garmin 호출 범위로 확인).
- [ ] AC2: 빠진 날이 D-7보다 오래되면 D-7..D만 받고, 더 오래된 빠진 기간과 명령을 한 줄로 알린다(text, JSON).
- [ ] AC3: 빠진 날이 없거나 기록이 하나도 없으면 범위와 출력이 지금과 byte-identical이다.
- [ ] AC4: `/sync`는 7일 이하면 바로, 넘으면 확인 명령 뒤에 운동, load metrics, 회복을 받고 짧은 요약을 보낸다. 추천은 만들지 않는다.
- [ ] AC5: 잘못된 날짜, 31일 초과, 미래 날짜, 만료·재사용된 확인 명령은 Garmin을 부르지 않고 거부된다.
- [ ] AC6: `/daily` 답장과 `sync_request` 안내는 빠진 날이 남아 있을 때만 `/sync` 명령을 더한다.
- [ ] AC7: 실제 Garmin으로 한 번 확인한다(live-garmin 게이트): 빠진 날이 있는 상태에서 `daily`가 그 날들을 채우고 coverage가 `synced`가 된다.
- [ ] AC8: `garmin latest`, `garmin refresh`, 다른 CLI 출력은 byte-identical이다.
- [ ] AC9: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- 상한 7일은 회복 요청 수(약 9회/일)를 기준으로 정했다. 더 긴 공백은 `/sync`로 나눠 받는다.
- 후속 후보: 아침 요약을 bot이 먼저 보내기, 빠진 날을 `garmin coverage`처럼 Telegram에서 보기(`/coverage`).
