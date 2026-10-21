# Daily Catch-up and Telegram Range Sync v1

Spec: [specs/daily-catch-up.md](specs/daily-catch-up.md). Coverage 기록: [sync-coverage.md](sync-coverage.md).
Bot: [telegram-bot.md](telegram-bot.md).

## 목적과 non-goal

- `daily`(CLI, Telegram `/daily`)는 늘 D-1..D만 받아서, `daily`를 며칠 안 돌리면 그 사이 운동과 회복이 `not synced`로
  남았다. 이제 **마지막으로 동기화된 날 다음 날부터** 받는다. 단 D-1보다 늦지 않고 D-7보다 이르지 않다.
- 상한(7일)보다 오래 빠진 날은 한 줄로 알리고, 받는 명령을 같이 보여 준다: CLI `muscle50 garmin sync --from --to`,
  Telegram `/sync`.
- Non-goal: Garmin 요청 방식, 정규화, RAW 저장, coverage 기록 규칙은 그대로다(기존 use case를 그대로 부른다).
  `garmin latest`, `garmin refresh`는 바뀌지 않는다. 자동 예약 실행은 없고, LLM은 동기화를 실행하지 않는다(안내만 한다).
  migration 없음.

## 이어 받기 규칙 (`daily`)

`daily`는 `migrate()` 뒤, Garmin 로그인 전에 coverage를 read-only로 읽는다(`PlanDailyCatchUp`, `mode=ro`).

1. D-31..D-1의 coverage row만 본다. full mode는 activities와 recovery, `--after-workout`은 activities만 본다.
2. 그 창에 row가 하나도 없으면(새 설치, coverage 이전 DB) 지금처럼 D-1부터 받는다.
3. 어떤 날이 **완료**이려면, 보는 종류마다 `synced` row가 있고 그 row가 **그 날이 끝난 뒤의 로컬 날짜에 기록**되어야 한다
   (`synced_at_utc`를 이 컴퓨터의 고정 UTC offset으로 바꿔 비교). 아침 `daily`는 오늘도 `synced`로 기록하지만 그건 그 시각까지의
   기록이라, 같은 날 기록된 row는 완료가 아니다. `partial`, `failed`, row 없음도 완료가 아니다. 시각을 읽을 수 없으면 완료가
   아니다(timezone 없는 시각은 UTC로 읽는다).
4. 마지막 완료일을 L이라 하면 빈 날의 시작 G = L+1. L이 없으면 G는 창에서 가장 이른 row의 날짜다.
5. 시작일 = max(min(G, D-1), D-7). 끝은 D.
6. G가 D-7보다 이르면 G..D-8을 "더 오래된 빠진 날"로 알린다(최대 24일, `/sync` 한 번에 들어간다).
7. L보다 앞의 빈 날은 알리지 않는다(`garmin coverage`로 본다).
8. coverage를 읽지 못하면 stderr에 경고를 쓰고 D-1부터 받는다.

시작일이 D-1이면 stdout, JSON, stderr가 이 기능 전과 byte-identical이다. 평소처럼 매일 아침 `daily`를 돌리면
(전날 아침에 D-2와 D-1이 기록됨) L = D-2라서 시작일은 D-1이다.

이어 받은 범위도 같은 순서(로그인 한 번, activities, load metrics, recovery, 추천)와 같은 실패 정책을 따른다.
`daily --date D`는 D를 기준으로 같은 규칙을 쓴다.

## 명령

### `muscle50 daily` (옵션은 그대로)

stderr의 진행 줄이 실제 범위를 보여 준다.

```text
muscle50 daily 2026-10-21: syncing 2026-10-14..2026-10-21
```

시작일이 D-1보다 이를 때만, daily 부분의 마지막(추천 리포트 앞)에 한두 줄이 붙는다(합성 값).

```text
Sync range: 2026-10-17..2026-10-21 (caught up after the last fully synced day 2026-10-16; limit 7 days)
```

```text
Sync range: 2026-10-14..2026-10-21 (caught up after the last fully synced day 2026-10-08; limit 7 days)
Older unsynced days: 2026-10-09..2026-10-13. Run: muscle50 garmin sync --from 2026-10-09 --to 2026-10-13 (Telegram: /sync 2026-10-09 2026-10-13)
```

- 완료일이 없으면 `(no fully synced day in the last 31 days; limit 7 days)`.
- `--after-workout`은 `(caught up after the last day with activities synced 2026-10-16; limit 7 days)`, 완료일이 없으면
  `(no day with activities synced in the last 31 days; limit 7 days)`.
- 더 오래된 빠진 날이 7일을 넘으면 명령 끝에 ` --yes`가 붙는다.
- CLI 안내는 늘 `YYYY-MM-DD`다(CLI는 bot의 "올해"를 모른다).

`--json`은 시작일이 D-1보다 이를 때만 마지막 key `catch_up`이 붙는다(additive, 다른 key는 그대로).

```json
  "catch_up": {
    "from": "2026-10-14",
    "limit_days": 7,
    "last_synced": "2026-10-08",
    "older_unsynced": {
      "from": "2026-10-09",
      "to": "2026-10-13"
    }
  }
```

`last_synced`는 완료일이 없으면 `null`, `older_unsynced`는 상한 안이면 `null`이다. exit code는 그대로다(0, 단계 실패 1, Ctrl+C 130).

### `muscle50 garmin sync --from YYYY-MM-DD --to YYYY-MM-DD [--yes] [--json]` (새 명령)

`daily`의 동기화 단계(`RunDailySync`, `DailyMode.SYNC`)를 정한 범위에 돌린다: 로그인 한 번, activities, load metrics,
recovery. 추천은 만들지 않는다. coverage는 `garmin sync`라는 명령 이름으로 기록된다.

검사는 모두 디렉터리 생성, migration, 로그인 전에 한다. 거부하면 exit 1, stderr에 `오류:`, 아무것도 만들지 않는다.

```text
오류: --from/--to는 YYYY-MM-DD 형식이어야 합니다.
오류: --from은 --to보다 이후일 수 없습니다.
오류: --to는 오늘(2026-10-21) 이후일 수 없습니다.
오류: 범위는 최대 31일입니다 (요청: 40일).
오류: 10일 범위는 Garmin 요청 약 90회가 필요합니다. 계속하려면 --yes를 추가하세요.
```

통과하면 stderr에 `muscle50 garmin sync 2026-10-09..2026-10-18 (10 days, about 90 recovery requests)`를 쓰고 실행한다.
Text(합성 값):

```text
muscle50 garmin sync 2026-10-09..2026-10-18
Stages:
  garmin_login: ok
  activities: ok (2026-10-09..2026-10-18: found 10, new 10, already stored 0, failed 0)
  load_metrics: ok (metric rows inserted 40, updated 0, unchanged 0)
  recovery: ok (2026-10-09..2026-10-18: created 10, updated 0, unchanged 0, failed 0, not attempted 0)
  recommendation: skipped
Synced. No recommendation was built; plan today with: muscle50 daily
```

단계가 실패하면 마지막 줄 대신 `FAILED stages: recovery. Data already synced is kept; rerunning the same command is safe.`이고
exit 1이다. `--json`은 `daily --json`과 같은 문서이고 `"as_of"`는 끝 날짜, `"mode": "sync"`, `"sync_from"`은 시작 날짜,
`"recommendation": null`, `catch_up` key는 없다. 로그인 prompt가 입력을 못 받으면(EOF) `daily`처럼 그대로 올라간다
(bot이 로그인 안내로 바꾼다).

## Telegram

### `/sync <시작> <끝>`

- 날짜는 `YYYY-MM-DD` 또는 `MM-DD`(bot의 오늘이 속한 해). 정확히 두 개. 다른 모양이나 빈 `/sync`는 사용법 답장이다.
- 거부(Garmin 호출 없음, 아무것도 실행하지 않음):

```text
오류: 없는 날짜입니다: 02-30. 날짜는 YYYY-MM-DD 또는 MM-DD(올해)로 씁니다.
오류: 시작 날짜(2026-10-18)가 끝 날짜(2026-10-09)보다 늦습니다.
오류: 끝 날짜(2026-10-25)가 오늘(2026-10-21) 이후입니다. 작년 날짜는 YYYY-MM-DD로 쓰세요.
오류: 한 번에 최대 31일까지 받을 수 있습니다(요청: 40일). 기간을 나눠 보내세요.
```

- 7일 이하: migration 검사 뒤 `동기화 실행 중: 10-15 ~ 10-18 (4일, Garmin 요청 약 36회). 끝나면 결과를 보냅니다.`를 보내고
  `garmin sync --from .. --to .. --json`을 돌린다.
- 7일 초과: 먼저 확인을 받는다.

```text
사용자: /sync 10-09 10-18
bot:   10일(10-09 ~ 10-18), Garmin 요청 약 90회입니다. 받아오려면 누르세요(10분 유효):
       /sync_ok_a41c
사용자: /sync_ok_a41c
bot:   동기화 실행 중: 10-09 ~ 10-18 (10일, Garmin 요청 약 90회). 끝나면 결과를 보냅니다.
bot:   동기화했습니다: 10-09 ~ 10-18
       운동 새로 저장 10건 · 회복 새로 저장 10일 · 실패 없음
       오늘 추천: /daily
```

- `/sync_ok_<id>`는 그 id가 있고, 같은 chat이고, 10분이 지나지 않았고, 아직 쓰지 않았을 때만 실행한다(`--yes --json`).
  같은 chat의 새 `/sync`는 이전 제안을 바꾼다. migration이 대기 중이면 거부하고 id는 남긴다(적용 뒤 같은 id가 된다).
  실행 직전에 id를 지우므로 한 번만 돈다. 나머지는 모두
  `오류: 이 확인 명령은 없거나, 10분이 지났거나, 이미 쓰였습니다. 다시 받으려면 /sync 시작 끝을 보내세요.`
- 단계 실패 요약(합성 값):

```text
동기화 일부 실패: 10-09 ~ 10-18 (recovery 단계)
운동 새로 저장 10건 · 회복 새로 저장 7일 · 실패: 10-12, 10-13, 10-14(받지 않음)
  recovery: <CLI의 오류 문구 그대로>
이미 받은 데이터는 저장되어 있습니다. 다시 받기: <code>/sync 10-09 10-18</code>
```

  실패한 운동은 `운동 <id>`로 적는다(JSON에 운동 날짜가 없어서 날짜를 만들지 않는다). 운동·회복 결과가 없으면
  `알 수 없음`이다(0이 아님). 갱신된 회복 날이 있으면 `회복 새로 저장 N일 (갱신 M일)`. 단계 경고는 `경고(stage): ...`.
- Garmin 로그인이 필요하면: `오류: Garmin에 다시 로그인해야 합니다. PC 터미널에서 muscle50 garmin sync --from 2026-10-09
  --to 2026-10-18 --yes를 한 번 실행하세요(로그인한 뒤 그대로 받습니다).` (7일 이하면 `--yes` 없음)

### `/daily`와 LLM 동기화 안내

- `/daily` 요약은 `daily`가 D-1보다 이르게 시작했을 때만 머리 줄 다음에 `이어 받기: 10-14부터 (마지막 동기화 10-08)`
  (완료일이 없으면 `(최근 31일에 모두 동기화된 날 없음)`)를 붙인다. 더 오래된 빠진 날이 있으면 tail 첫 묶음이
  `아직 동기화되지 않은 날: 10-09 ~ 10-13 (daily는 7일 전까지만 받습니다). 받기: <code>/sync 10-09 10-13</code>`이다.
  인자가 있는 명령은 눌러도 빈 `/sync`가 가므로 `<code>`(눌러서 복사)로 보낸다. 성공·실패 요약 모두 같다.
- LLM `sync_request` 안내(LLM이 켜져 있을 때)는 다음 `daily`가 남길 빠진 날이 있을 때만 한 줄을 더한다.
  버튼은 그대로 `/daily`, `/refresh`다.

```text
동기화는 /daily 로 합니다. 운동 하나만 다시 받으려면 /refresh 를 쓰세요.
아직 동기화되지 않은 날: 10-09 ~ 10-13 (/daily는 7일 전까지만 받습니다). 받기: /sync 10-09 10-13
```

  coverage는 read-only로 읽고(파일을 만들지 않음), 읽지 못하면 이 줄 없이 원래 안내만 보낸다.
- `MM-DD`는 두 날짜가 모두 오늘의 해일 때만 쓰고, 아니면 `YYYY-MM-DD`다.
- `/daily` 진행 문구는 이제 `daily 실행 중: Garmin 동기화 후 오늘 계획을 만듭니다. 끝나면 결과를 보냅니다.`다
  ("어제와 오늘의"를 뺐다).

## 코드 위치

| 무엇 | 어디 |
|---|---|
| 이어 받기 규칙(순수) | `src/muscle50/domain/sync_catch_up.py` (`plan_catch_up`, `DailyCatchUp`) |
| coverage 읽기 | `src/muscle50/application/daily_catch_up.py` (`PlanDailyCatchUp`) |
| 범위와 sync mode | `src/muscle50/application/daily_sync.py` (`RunDailySync.execute(..., sync_from=, catch_up=)`, `DailyMode.SYNC`) |
| CLI | `src/muscle50/cli.py` (`_daily`, `_daily_catch_up`, `_garmin_sync`, `_older_unsynced`) |
| text/JSON | `src/muscle50/presentation/terminal.py` (`_catch_up_lines`, `render_garmin_sync`) |
| `/sync` 문법과 문구 | `src/muscle50/domain/telegram_sync.py`, `domain/telegram_commands.py` |
| bot 흐름 | `src/muscle50/application/telegram_bot.py` (`_offer_sync`, `_confirm_sync`) |
| 요약 | `src/muscle50/presentation/telegram_summary.py` (`sync_summary`, `daily_summary`) |
| LLM 안내 | `src/muscle50/application/telegram_llm.py` (`sync_gap`) |

테스트: `tests/test_daily_catch_up.py`, `tests/test_garmin_sync_cli.py`, `tests/test_telegram_sync.py`,
`tests/test_telegram_sync_llm_hint.py`. 모두 가짜 Garmin, 임시 MUSCLE50_HOME, 합성 값이다.

## Known issues / limitations

- **L보다 앞의 빈 날은 알리지 않는다.** 예: 10-03이 빠졌어도 10-05가 완료면 `daily`는 10-06부터 본다. `garmin coverage`로 확인한다.
- **31일보다 긴 공백**(창에 row가 하나도 없음)은 "기록 없음"과 같아서 D-1부터 받고 아무것도 알리지 않는다.
- **같은 날 기록은 완료가 아니다(R2).** 하루에 `daily`를 한 번만 아침에 돌리면, 그 날(D)은 다음 날 기록될 때 완료가 된다.
  평소 흐름(매일 아침)에서는 시작일이 D-1 그대로다. 저녁에 한 번 더 돌려도 같은 날 기록이라 완료가 아니다.
- **recovery가 늘 `partial`이면**(한 endpoint가 매번 실패) 어떤 날도 완료가 아니어서 `daily`가 매번 8일(회복 요청 약 72회)을
  받는다. gate 1 시점 운영 DB(2026-09-21..2026-10-21)에는 `partial`이 없었다. 생기면 `garmin coverage`로 원인 endpoint를 본다.
- **확인 명령은 bot 메모리에만 있다.** bot을 다시 시작하면 열린 제안이 사라진다. `/sync`를 다시 보낸다.
- **`MM-DD`는 늘 올해다.** 1월에 작년 12월을 받으려면 `YYYY-MM-DD`로 쓴다(미래 날짜 거부 문구가 안내한다).
  `/sync` 실패 요약의 다시 받기 명령은 끝 날짜의 해를 기준으로 `MM-DD`를 쓴다. 작년 범위를 올해 다시 보낼 때는
  `YYYY-MM-DD`로 고쳐 보낸다.
- **요청 수 안내는 회복만 센다**(하루 9회). activity 목록 page와 새 운동의 상세 요청이 더해진다.
- **`garmin coverage`의 `Recorded by:` 줄**은 `garmin sync`를 적지 않는다(그 출력을 바꾸지 않으려고 그대로 뒀다).
- `garmin sync`의 stderr 진행 줄은 bot의 stdout 없는 답장에서 걸러지지 않는다. 진행 줄은 검사가 모두 끝난 뒤에만 쓰고
  그 뒤 오류는 JSON으로 나오므로 실제로는 보이지 않는다.
- Live Garmin(AC7)은 사람 게이트다. 아래 "사람 확인"을 따른다.

## 사람 확인 (live Garmin, AC7)

main checkout에서, 통합 뒤:

1. 읽기만: `uv run muscle50 garmin coverage --from 2026-09-21 --to <오늘> --json`. `partial`/`failed` 날과 빈 날을 본다.
2. 아침 `daily` 뒤 하루 이상 `daily`를 건너뛴다. 그 다음 `uv run muscle50 daily`:
   stderr `syncing X..D`(X = 끝난 뒤 기록된 마지막 날의 다음 날), text의 `Sync range:` 줄, `--json`이면 `catch_up.from == X`.
   이어서 `garmin coverage --from X --to D`에서 X..D-1의 activities가 `synced`, recovery가 `synced`(또는 endpoint가 적힌 `partial`).
3. Telegram: `/sync <4일>`은 바로 실행되고 요약이 온다(콘솔 로그에 로그인 한 번, 추천 없음). `/sync <10일>`은 제안이 오고
   `/sync_ok_…`를 누르면 실행되며, 같은 명령을 다시 누르면 거부된다. 10분 지난 제안은 거부된다. 미래 끝 날짜는 Garmin
   호출 없이 거부된다.
