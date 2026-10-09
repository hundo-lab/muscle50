# Telegram Command Bot v1

Spec: `docs/specs/telegram-bot.md`. Migration 없음(설정과 상태는 JSON 파일, DB schema 변경 없음). Output change: additive
(새 `telegram` 명령 그룹. `muscle50 --help`에 한 줄이 늘어난다).

> v1.1(Telegram Mobile Replies, 아래 [v1.1](#v11-telegram-mobile-replies) 절)부터 `/today`, `/status`, `/daily`의 기본
> 답장은 짧은 요약이다. 이 문서의 v1 절에 있는 이 세 명령의 CLI 명령과 답장 설명은 이제 `full`을 붙였을 때(`/today full`
> 등)의 동작이다. `/unknown`, `/refresh`는 v1.1에서 추가됐다. 인자 없는 `/refresh`(UNKNOWN 운동 모두 다시 받기)는
> v1.2에서 추가됐다(아래 [v1.2](#v12-telegram-refresh-all-unknown) 절).

## 목적과 non-goal

- 휴대폰 Telegram에서 정해진 명령으로 muscle50을 쓴다. 오늘 운동 추천, 오늘 영양 상태, 식사 기록과 취소, InBody 추세,
  `daily`를 PC 터미널 없이 부른다.
- bot은 전달 통로일 뿐이다. 각 명령은 **CLI와 같은 코드 경로**(`muscle50.cli.main`)로 실행하고, 답장 본문은 그 CLI 명령의
  stdout(실패하면 `오류:` 줄) 그대로다. 새 계산·판단·추천은 없다. LLM도 없다.
- Non-goal: 자유 문장 해석, webhook·서버·클라우드 배포, 여러 사용자, 예약 알림, Windows 서비스 등록, 새 Python 의존성
  (표준 라이브러리 `urllib`/`json`만 쓴다).

## 설정

### 1. BotFather로 bot 만들기

1. Telegram에서 `@BotFather`를 열고 `/newbot`을 보낸다.
2. 표시 이름과 `bot`으로 끝나는 username(예: `my_muscle50_bot`)을 정한다.
3. BotFather가 준 token(`숫자:문자` 형식)을 복사한다. token은 비밀번호와 같다. 채팅, 스크린샷, repo에 남기지 않는다.

### 2. 설정 파일 만들기

`%LOCALAPPDATA%\muscle50\config\telegram.json`을 직접 만든다(muscle50은 이 파일을 만들지 않는다). repo 안에 두거나
commit하지 않는다. chat id는 아직 모르므로 우선 아무 정수를 넣는다.

```json
{
  "bot_token": "123456789:AAExampleOnlyNotARealToken",
  "allowed_chat_ids": [1]
}
```

- key는 정확히 `bot_token`과 `allowed_chat_ids` 두 개다. 메모장의 UTF-8 BOM은 괜찮다.
- `allowed_chat_ids`는 따옴표 없는 정수 목록이다(group chat id는 음수일 수 있다). 비어 있으면 안 된다.
- 환경 변수로 token을 덮어쓰는 방법은 없다(v1). 개발·smoke 실행은 `MUSCLE50_HOME`으로 설정 폴더 전체를 바꾼다.

### 3. 확인

```powershell
uv run muscle50 telegram check
```

```text
Telegram config: C:\Users\me\AppData\Local\muscle50\config\telegram.json
Bot: @muscle50_example_bot (id 1234567890)
Allowed chats: 1
Webhook: not set
Handled updates on record: none
No messages were read or answered.
```

`check`는 설정 파일을 검사하고, 상태 파일을 읽고(있으면), `getMe`와 `getWebhookInfo`만 부른다. 메시지를 읽거나 답하지
않고(`getUpdates` 없음), 파일과 DB를 만들거나 바꾸지 않는다. 상태 파일이 있으면 5번째 줄이
`Handled updates on record: 12 (latest 5501)`처럼 나온다. webhook이 걸려 있으면
`Webhook: set (telegram run cannot poll while a webhook is set; remove it with deleteWebhook)`이다.

### 4. 내 chat id 찾기

1. `uv run muscle50 telegram run`을 시작한다.
2. 휴대폰에서 만든 bot을 열고 `/start`를 보낸다.
3. 아직 허용 목록에 없으므로 bot은 답하지 않고, 콘솔에 `ignored message from chat 123456789 (not in allowed_chat_ids)`
   한 줄을 남긴다. 그 숫자가 내 chat id다.
4. Ctrl+C로 멈추고, `allowed_chat_ids`를 `[123456789]`로 고친 뒤 다시 시작한다.

다른 방법: chat id를 알려 주는 helper bot을 써도 된다. 브라우저에서 `https://api.telegram.org/bot<token>/getUpdates`를
열지 않는다. token이 브라우저 기록에 남는다.

## 명령

```powershell
muscle50 telegram check    # 설정·token 확인, bot 이름 표시. 메시지 처리 없음. exit 0 또는 1
muscle50 telegram run      # long polling. Ctrl+C까지 동작(exit 130). 설정·token 오류는 exit 1
```

두 명령 모두 옵션과 `--json`이 없다.

### bot 명령

| bot 명령 | 실행되는 CLI 명령 |
|---|---|
| `/today` | `recommend --date <오늘>` |
| `/status` | `nutrition status` |
| `/day [YYYY-MM-DD]` | `nutrition day [--date YYYY-MM-DD]` |
| `/log <meal>[+] <food> <qty> <unit>[, ...]` | `nutrition log --meal <meal> --item <food> <qty> <unit> ... [--additional]` |
| `/void <meal_id> [이유]` | `nutrition meal void <meal_id> [--reason=<이유>]` |
| `/show <meal_id>` | `nutrition meal show <meal_id>` |
| `/inbody` | `inbody trend` |
| `/daily` | `daily` |
| `/help`, `/start` | (bot의 명령 목록) |

`<오늘>`과 날짜 기본값은 CLI와 같다(이 컴퓨터의 오늘, `_today()`/`_local_timezone`).

`/log` 문법(합성 예):

```text
/log lunch 닭가슴살 150 g, 햇반 1 pack     -> --meal lunch --item 닭가슴살 150 g --item 햇반 1 pack
/log lunch+ 바나나 1 count                -> 같은 날 lunch가 있어도 하나 더 기록(--additional)
/log dinner 현미 햇반 1 pack               -> 이름에 공백이 있어도 된다: 마지막 두 단어가 수량과 단위
```

- meal은 `breakfast`, `lunch`, `dinner`, `snack`, `other` 중 하나(소문자). 끝의 `+`는 `--additional`이다.
- item은 쉼표로 나눈다. 각 item은 3단어 이상이고, 마지막 두 단어가 수량과 단위, 그 앞(공백 하나로 다시 이음)이 음식이다.
- 음식은 Food Name Lookup v1 규칙 그대로다(food ID, 또는 정확히 같은 이름/alias). 수량·단위·음식이 틀리면 CLI의
  `오류:` 줄이 그대로 답으로 오고 아무것도 저장되지 않는다(all-or-nothing).
- 시간(`--time`)은 v1 문법에 없다.

### 답장 예시(합성 값)

`/log lunch 닭가슴살 150 g, 햇반 1 pack`의 답. 마지막 `취소:` 줄만 bot이 붙이고, 그 위는 `nutrition log` stdout과 같다.

```text
Recorded meal 2026-10-06-lunch-1.

[lunch] 2026-10-06-lunch-1 (2026-10-06, time not recorded)
  1. 닭가슴살 (chicken-breast) 150 g: kcal 165 | P 34.5 g | C 0 g | F 1.5 g
...
Whole day: muscle50 nutrition day --date 2026-10-06
취소: /void 2026-10-06-lunch-1
```

거부된 `/log`의 답(CLI 오류 그대로): `오류: item 2: no food with id '없는음식' ...`

형식이 틀린 명령의 답:

```text
사용법: /show <meal_id>
예: /show 2026-10-06-lunch-1
```

모르는 명령은 `모르는 명령입니다: /foo`, 명령이 아닌 문장(사진 포함)은 `명령이 아닙니다.` 다음에 빈 줄과 `/help` 목록이 온다.

## 규칙

### 허용 목록

- `allowed_chat_ids`에 없는 chat의 메시지에는 답하지 않는다(sendMessage 없음). DB, 상태 파일, 어떤 파일도 바꾸지 않고
  콘솔에 `ignored message from chat <id> (not in allowed_chat_ids)` 한 줄만 남긴다.
- 개인 chat id만 넣는다. group id를 넣으면 그 group의 모든 사람이 bot에 명령할 수 있다.

### 같은 update는 한 번만(at most once)

- 허용 chat의 update는 **명령을 실행하기 전에** update id를 `config\telegram_state.json`에 저장한다. 그래서 재시작한 뒤
  Telegram이 같은 update를 다시 보내도 다시 실행하지 않는다(`/log`가 두 번 저장되지 않는다).
- 대가: 명령 도중 PC가 꺼지거나 Ctrl+C를 누르면 그 명령의 답장은 영영 오지 않을 수 있다. 쓰기는 use case transaction이라
  부분 기록은 없다. 기록됐는지는 `/day`로 확인한다.
- 상태 파일은 `telegram run`이 첫 허용 메시지를 처리할 때 만든다. 최근 100개 update id와 bot id만 담는다.

```json
{
  "schema_version": 1,
  "bot_id": 1234567890,
  "handled_update_ids": [
    5500,
    5501
  ]
}
```

- 임시 파일, fsync, `os.replace`로 원자적으로 쓴다. 읽을 때 형식이 하나라도 틀리면 `오류:`로 멈춘다. 지워도 된다(아래
  "bot 시작 전 메시지" 규칙 때문에 오래된 메시지가 다시 실행되지 않는다). 저장에 실패하면 명령을 실행하지 않고 `run`이
  `오류:`, exit 1로 멈춘다.
- 저장된 bot id가 지금 token의 bot과 다르면(token을 다른 bot으로 바꾼 경우) 기존 기록을 쓰지 않고 콘솔에 한 줄을 남긴다.

### bot 시작 전에 보낸 메시지는 실행하지 않는다

- Telegram은 bot이 꺼져 있는 동안 온 메시지를 약 24시간 보관한다. `run` 시작 시각보다 60초 넘게 앞서 보낸 메시지는
  실행하지 않고 다음처럼 답한다(밤 11시 50분에 보낸 `/log`가 다음 날짜로 기록되는 것을 막는다).

```text
실행하지 않음: 이 메시지는 bot이 시작되기 전(2026-10-06 07:12)에 보낸 것입니다. 아직 필요하면 다시 보내세요.
```

### 적용하지 않은 migration이 있으면 실행하지 않는다

- `migrate()`는 실행할 때마다 코드에 있는 migration 파일을 모두 적용한다. `telegram run`이 도는 동안 새 migration이
  main에 통합되면, 휴대폰에서 보낸 명령 하나가 백업 없이 production DB에 migration을 적용할 수 있다(human gate 3 우회).
- 그래서 CLI handler가 `migrate()`를 부르는 명령(`/status`, `/day`, `/show`, `/log`, `/void`, `/daily`, v1.1의 `/refresh`)을
  실행하기 전에 DB를 read-only(`mode=ro` + `PRAGMA query_only`)로 열어 `schema_migrations`와 코드의 migration 번호를
  비교한다. 빠진 번호가 있으면 실행하지 않고 다음처럼 답한다.

```text
오류: DB에 아직 적용하지 않은 migration 011이 있습니다. bot은 migration을 적용하지 않습니다. DB를 백업한 뒤 PC 터미널에서 muscle50 명령 하나로 적용하고 다시 보내세요.
```

- DB가 있는데 `schema_migrations`를 읽을 수 없으면 역시 실행하지 않는다(`오류: DB의 migration 상태를 읽을 수 없어 ...`).
- DB가 아직 없으면(새 home) 그대로 실행하고, CLI가 평소처럼 DB를 만든다.
- `/today`(`recommend`)와 `/inbody`(`inbody trend`)는 CLI에서도 read-only라 이 검사가 없다.

### `/daily`

- 먼저 `daily 실행 중: 어제와 오늘의 Garmin 동기화 후 오늘 계획을 만듭니다. 끝나면 결과를 보냅니다.`를 보내고, 끝나면
  `daily` stdout을 보낸다. 실행 중에 온 다른 메시지는 끝난 뒤 순서대로 처리한다.
- Garmin 로그인이 다시 필요하면(첫 로그인, token 만료, MFA) bot은 입력을 받을 수 없다. stdin이 빈 입력이라 로그인
  prompt가 바로 끝나고, 어떤 sync 단계도 쓰기 전에 멈춘 뒤 다음처럼 답한다.

```text
오류: Garmin에 다시 로그인해야 합니다. PC 터미널에서 muscle50 daily를 한 번 실행해 로그인한 뒤 /daily를 다시 보내세요.
```

### 답장 형식

- 답장 본문은 CLI stdout에서 마지막 줄바꿈 하나를 뺀 것이다. stdout이 비어 있으면 stderr(`오류:` 줄)를 보낸다
  (`muscle50 daily ` 진행 줄은 뺀다). 둘 다 비어 있으면 `오류: 명령이 아무것도 출력하지 않았습니다 (exit N).`
- `<pre>` + HTML escape(`<`, `>`, `&`) + `</pre>`, `parse_mode=HTML`로 보내 고정폭 정렬을 유지한다.
- Telegram 한도 4096자(UTF-16 단위, 이모지는 2)를 넘으면 줄 경계에서 여러 메시지로 나눈다. 한 줄이 한도보다 길면 줄
  안에서 자른다. 내용은 버리지 않는다. `/today full`은 보통 2개 메시지로 온다.
- 예상하지 못한 예외가 나면 `오류: 예상하지 못한 오류로 명령을 마치지 못했습니다 (<예외 종류>). telegram run 콘솔을
  확인하세요.`라고 답하고, 콘솔에 traceback을 남기고 계속 돈다.

### 네트워크 오류, Ctrl+C, 콘솔

- `getUpdates`나 `getMe`가 실패하면 5, 10, 20, 40, 60초(이후 60초) 간격으로 다시 시도한다. 성공하면 간격을 처음으로
  돌린다. HTTP 429의 `retry_after`는 그대로 따른다. HTTP 409(다른 `telegram run`이나 webhook이 같은 bot을 쓰는 중)는
  콘솔 줄에 그 힌트를 붙인다. 시작할 때 token이 거부되면(401/404) `오류:`, exit 1로 끝난다.
- 답장 전송이 실패하면 5초, 10초 뒤 최대 3번까지 시도하고, 그래도 안 되면 `reply to chat <id> was not delivered (...)`를
  남기고 다음 메시지로 넘어간다.
- Ctrl+C는 바로 멈춘다(exit 130). 진행 중이던 명령은 이미 "처리함"으로 저장되어 다시 실행되지 않고, 그 답장은 오지 않는다.
- 콘솔(stderr) 줄은 ASCII이고 timestamp가 없다. 메시지 본문과 답장 본문은 남기지 않는다. 마지막 `취소되었습니다.`만
  다른 명령과 같은 한국어다.

```text
telegram run: bot @muscle50_example_bot is polling for 1 allowed chat. Press Ctrl+C to stop.
chat 123456789: /status -> exit 0
chat 123456789: /log -> exit 1
chat 123456789: usage reply (malformed /show)
ignored message from chat 987654321 (not in allowed_chat_ids)
chat 123456789: message sent before start, not run
telegram: network error (<urlopen error [Errno 11001] getaddrinfo failed>); retrying in 5 s
chat 123456789: /daily interrupted by Ctrl+C; it will not be run again

취소되었습니다.
```

### token은 어디에도 나오지 않는다

- token을 가진 코드는 Bot API adapter(`infrastructure/telegram/bot_api.py`) 하나다. 그 adapter의 모든 오류 메시지에서
  token(그대로, URL 인코딩된 형태 모두)을 `<redacted>`로 바꾸고, 원래 예외를 연결하지 않는다(URL이 traceback에 남지 않음).
- 설정 오류 메시지는 token이나 값을 다시 보여 주지 않는다. `TelegramConfig`의 repr에도 token이 없다.
- `telegram run`/`check`의 모든 콘솔 출력은 한 번 더 token을 가린다.

### 이 기능이 쓰는 파일

| 파일 | 만드는 쪽 | 내용 |
|---|---|---|
| `config\telegram.json` | 사용자 | token, 허용 chat id |
| `config\telegram_state.json` | `telegram run`(첫 허용 메시지 때) | 처리한 update id 100개, bot id |

`telegram run` 자체는 `ensure_directories()`나 `migrate()`를 부르지 않는다. 각 bot 명령이 CLI 명령과 똑같이 DB를 연다.

## Known issues / limitations

- 이 PC에서 `telegram run`이 돌고 있을 때만 답한다. PC가 꺼져 있거나 잠자기면 답하지 않고, 그동안 보낸 메시지는 다음
  시작 때 "실행하지 않음"으로 답한다.
- **통합 뒤 `telegram run`을 다시 시작한다.** 코드는 실행 중에 바뀔 수 있다(editable 설치). 새 migration은 bot이 적용하지
  않으므로, 백업한 뒤 터미널에서 적용하고 bot을 다시 시작한다.
- at-most-once의 대가: 명령 도중 Ctrl+C나 꺼짐이 있으면 답장이 없다. `/log lunch`를 다시 보내면 기존 중복 식사 거부가
  막아 주지만 `/log lunch+`는 막지 못하므로 다시 보내기 전에 `/day`로 확인한다.
- 자정 경계: 23:59에 보낸 `/log`가 00:00 뒤에 처리되면 새 날짜로 기록된다(CLI의 "기본 날짜는 이 컴퓨터의 오늘"과 같다).
- `run`을 두 개 띄우거나 webhook이 걸려 있으면 Telegram이 409를 돌려준다. bot은 기록하고 재시도할 뿐 로컬 잠금은 없다.
- bot이 도는 동안 CLI를 같이 쓰면 SQLite 잠금(5초 timeout) 때문에 동시 쓰기 하나가 CLI의 평소 오류로 실패할 수 있다.
- Windows에서 Ctrl+C는 진행 중인 네트워크 읽기(long poll 최대 약 10초)나 긴 Garmin 호출이 끝날 때까지 늦게 반영될 수 있다.
- 개인정보: Telegram bot 대화는 종단간 암호화가 아니다. 식사 기록과 `/inbody` 체성분 값이 Telegram 서버를 지난다.
- 음식 이름: `-`로 시작하거나 쉼표가 들어간 이름은 bot으로 기록할 수 없다. 이름 안의 연속 공백은 공백 하나로 바뀌어 정확한
  이름 일치에 실패할 수 있다. 이럴 때는 food ID를 쓴다. 어떤 명령에서도 `-`로 시작하는 단어는 형식 오류다(CLI flag 주입 방지).
- `/log`의 `취소:` 줄은 `nutrition log` 첫 줄 `Recorded meal <id>.`에서 meal ID를 읽는다. 그 문구가 바뀌면 줄을 붙이지 않고
  콘솔에 남긴다(추측하지 않는다).
- stdout/stderr/stdin 교체는 process 전체에 적용된다. 메시지를 하나씩 처리하므로 안전하다. thread로 동시 처리를 넣으려면
  이 부분을 다시 설계해야 한다.
- v1에 없는 것: `/log` 시간 지정, `/edit`, `/merge`, `/repeat`, 음식 검색, 예약 알림, 자동 시작, 자유 문장(LLM).

# v1.1 Telegram Mobile Replies

Spec: `docs/specs/telegram-mobile.md`. Migration 없음. CLI 출력 변경 없음(모든 CLI 명령의 text와 JSON은 그대로다).
bot 답장만 바뀐다: `/today`, `/status`, `/daily`의 기본 답장이 요약이 되고, `/help`와 이 세 명령의 사용법 줄이 바뀌고,
`/unknown`과 `/refresh`가 생긴다. `/day`, `/show`, `/log`, `/void`, `/inbody`의 답장과 모든 `full` 답장은 v1과 byte 단위로
같다.

## 목적과 non-goal

- 휴대폰에서 바로 읽을 짧은 요약을 기본으로 보낸다. 전체 리포트는 `full`을 붙여서 본다.
- Garmin에서 운동 이름이 UNKNOWN인 세트를 짧게 알려 주고, Garmin Connect 링크와 `/refresh <id>`로 휴대폰에서 고칠 수 있게
  한다. UNKNOWN 세트는 근육별 세트 수와 진척 계산에서 빠지므로, 줄일수록 근육별 집계가 정확해진다.
- Non-goal: 자동 refresh(운동마다 Garmin 요청 4~5번), 운동 이름 추측, LLM, 새 계산이나 판단, CLI 출력 변경, 예약 알림.

## 명령

| bot 명령 | 실행되는 CLI 명령(한 메시지에 한 번) | 답장 | migration 검사 | 진행 안내 |
|---|---|---|---|---|
| `/today` | `recommend --date <오늘> --json` | 요약 | 없음 | - |
| `/today full` | `recommend --date <오늘>` | v1과 같은 CLI text | 없음 | - |
| `/status` | `nutrition status --json` | 요약 | 있음 | - |
| `/status full` | `nutrition status` | v1과 같은 CLI text | 있음 | - |
| `/daily` | `daily --json` | 요약 | 있음 | `daily 실행 중: ...` |
| `/daily full` | `daily` | v1과 같은 CLI text | 있음 | `daily 실행 중: ...` |
| `/unknown` | `recommend --date <오늘> --json` | UNKNOWN 목록 | 없음 | - |
| `/refresh <activity_id>` | `garmin refresh <activity_id>` | 전후 UNKNOWN 세트 수 | 있음 | `refresh 실행 중: ...` |

- `full`은 소문자 `full` 한 단어만 받는다. `/today 2026-10-05`, `/status now`, `/daily Full`, `/today full x`는 사용법 답장이다.
- `/unknown`은 인자가 없다.
- `/refresh`의 id는 ASCII 숫자 1~20자리이고 0으로 시작하지 않는다(`[1-9][0-9]{0,19}`). `/refresh abc`,
  `/refresh 0`, `/refresh 1 2`, `/refresh -5`, 다른 문자 체계의 숫자(예: `١٢٣`)는 모두 사용법 답장이다. 인자 없는
  `/refresh`는 v1.2부터 UNKNOWN 운동을 모두 다시 받는다(아래 v1.2 절).
- `/refresh_<id>` 같은 한 번 탭 별칭은 없다(gate 1 결정). 요약의 `/refresh <id>`는 `<code>`로 보내므로 탭하면 복사되고,
  붙여 넣어 보낸다.
- `/daily`는 `daily --json`을 **한 번** 실행한다. 한 메시지가 Garmin 동기화를 두 번 하는 일은 없다. `/daily full`은 따로 보내는
  메시지이고, 그것도 한 번만 동기화한다.

## 요약 형식(합성 값)

요약 본문은 `<pre>`(고정폭)이고, 링크·복사용 명령·마지막 줄은 `<pre>` 밖에 둔다. Telegram은 `<pre>`/`<code>` 안의 링크를
누를 수 없게 하기 때문이다. 아래에서 `<pre>`와 `</pre>` 사이가 고정폭 본문이다.

`/today`:

```text
<pre>오늘 추천 10-07
주의: 회복 hold - hrv_status LOW
주의: 세션 조정 reduce (회복이 아닌 규칙)

근력: legs · 약 32분 · 9세트
 1. SQUAT/BARBELL_BACK_SQUAT 3x12 @ ~40 kg (무게 불확실)
 2. DEADLIFT/BARBELL_DEADLIFT 3x12 @ 40 kg
 3. LUNGE/DUMBBELL_LUNGE 3x8-12 @ ~12 kg (무게 불확실, 지난 무게 확인)
회복: hold (readiness MODERATE 64, HRV LOW, 오늘 수면 기록 없음)
수영: easy_continuous 약 800 m (마지막 수영 20일 전)
영양: 오늘 기록 없음 (0 kcal이 아님)</pre>
확인 필요: Garmin UNKNOWN 세트
• 10-05 근력 11세트: https://connect.garmin.com/modern/activity/24610155225   (링크)
  고친 뒤: /refresh 24610155225                                                 (<code>, 탭하면 복사)
• 10-02 근력 16세트: https://connect.garmin.com/modern/activity/24576105658
  고친 뒤: /refresh 24576105658
모두 다시 받기: /refresh                                                        (v1.2, 탭하면 바로 보냄)
기타 알림 6건 · 전체: /today full
```

- 머리줄은 `오늘 추천 MM-DD`다(`as_of`의 월-일).
- **주의 줄**(머리줄 바로 아래):
  - 회복 level이 `normal`이 아니면 `주의: 회복 <level> - <근거>`. 근거는 규칙이 발동한(`fired_level`이 있는) 관측값
    `<field> <값>`이고, 이전 아침 기록 때문에 유지된 level이면 `이전 아침 기록으로 hold 유지`가 붙는다. 근거가 하나도 없으면
    `주의: 회복 <level>`만 쓴다.
  - 세션 조정 level이 회복 level과 다르면(어제 훈련량 같은 회복이 아닌 규칙) `주의: 세션 조정 <level> (회복이 아닌 규칙)`.
- **근력**: `근력: <focus> · 약 <분>분 · <세트>세트`. 사용자가 고른 focus면 `(직접 선택)`이 붙는다. 계획이 없으면
  `근력: 계획 없음 (사용할 근력 기록 없음)`.
- **운동 줄**은 CLI `recommend`의 처방과 같은 규칙이다. 반복 수는 목표 반복 수, 없으면 범위(`8-12`). 무게는 CLI와 같은
  `kg_text`(예: `50 kg`). 무게 신뢰도가 low이면 `~`를 붙이고 정확한 무게로 보이지 않게 한다. 그리고 `(무게 불확실)`을 붙이고,
  지난 무게와 같은 조건이라는 근거가 없으면 `(무게 불확실, 지난 무게 확인)`을 붙인다. 무게 목표가 없으면 `(무게 목표 없음)`,
  다음 단계 무게면 `@ 50 kg에서 다음 단계 위`, 보조/추가 방향을 모르면 `@ 50 kg에서 한 단계 (보조인지 추가 무게인지 확인)`,
  비교 기록이 없으면 `(무게 직접 선택: 비교 기록 없음)`이다.
- **회복**: `회복: <level> (readiness <level> <score>, HRV <상태>, <수면>)`. 값이 없으면 `알 수 없음`이다(0이 아님).
  오늘 회복 행에 수면이 없으면(partial) `오늘 수면 기록 없음`, 오늘 회복 행이 없으면 괄호 전체가
  `(오늘 회복 기록 없음 · 없음은 나쁜 회복이 아님)`이다. 수면 시간은 CLI와 같은 `HH:MM:SS`.
- **수영**: `수영: <session_type> 약 <m> m (마지막 수영 N일 전)`. 최근 28일에 수영이 없으면 `(최근 28일 수영 기록 없음)`.
  주의가 있으면 `· 주의 N건`.
- **영양**(recommend JSON의 `nutrition`): 목표 없음 → `영양: 목표 없음`, 읽을 수 없음 → `영양: 읽을 수 없음 (<이유>)`, 식사
  기록 없음 → `영양: 오늘 기록 없음 (0 kcal이 아님)`, 평가됨 → `영양: 식사 N끼 · <목표가 있는 영양소들> · 안내 N건`
  (영양소 형식은 아래 `/status`와 같다). key가 없으면 `영양: 알 수 없음`.
- **UNKNOWN 알림**: recommend JSON의 `strength.unknown_notices`(구조화된 값)를 쓴다. JSON 순서(최근 운동 먼저) 그대로
  최대 **3개**를 보이고, 더 있으면 `외 N개 · /unknown`. 대상 기간은 recommend가 이미 쓰는 기간(오늘 전 14일, 오늘 운동은
  제외)이다. 없으면 이 절 전체가 없다. 링크는 `https://connect.garmin.com/modern/activity/<id>`이고, id가 ASCII 숫자인지
  확인한 뒤에만 링크에 넣는다.
- **마지막 줄**은 항상 `기타 알림 N건 · 전체: /today full`이다. N은 notice 전체에서 요약이 이미 보여 준 것
  (`strength_unknown_exercise` 전부, 회복 줄이 보여 주는 `recovery_row_partial`, `recovery_row_missing`)을 뺀 수이고, 0이어도
  쓴다.

`/daily`(성공):

```text
<pre>daily 10-07: 동기화 완료 (새 운동 0, 회복 2일 갱신)
경고(activities): <단계 경고 그대로>

근력: ...                       (/today와 같은 본문)</pre>
확인 필요: Garmin UNKNOWN 세트
...
기타 알림 6건 · 전체: /today full
```

- 새 운동 수는 `activities.inserted`, 회복은 `recovery.outcomes` 중 `created`/`updated`인 날짜 수다. 값이 없으면
  `알 수 없음`. 모든 단계의 경고를 그대로 한 줄씩 쓴다.
- `전체: /today full`은 다시 동기화하지 않고 방금 저장된 데이터로 같은 계획 전체를 보여 준다.

`/daily`(실패한 단계가 있음, 추천 요약은 만들지 않는다):

```text
<pre>daily 10-07: 실패 (recovery 단계)
  recovery: <daily --json의 stages[].error 그대로>
  경고(load_metrics): <경고 그대로></pre>
추천은 만들지 않았습니다. 이미 받은 데이터는 저장되어 있습니다.
저장된 데이터로 본 계획: /today · 다시 동기화: /daily
```

- 오류 문구는 CLI `daily`가 `error:` 뒤에 출력하는 값과 같다(text를 파싱하지 않는다). 오류 문구가 없는 실패 단계는
  `오류 문구 없음`. spec 예시의 `/daily full` 대신 `/today`(저장된 데이터, 동기화 없음)와 `/daily`(다시 시도)를 안내한다
  (gate 1 결정).

`/status`:

```text
<pre>영양 10-07 (UTC+09:00): 식사 2끼, 3개
kcal 845 / 목표 2200-2500 (below_range, 최소까지 1355)
단백질 61.5 g 이상 (값 없는 항목 1개) / 목표 120 g (indeterminate)
탄수화물 140 g / 목표 없음 (no_target)
지방 알 수 없음 / 목표 없음 (no_target) (추정 포함)</pre>
전체: /status full
```

- 네 영양소를 항상 이 순서로 쓴다. kcal은 단위 없이, 나머지는 ` g`을 값·목표·남은 양에 모두 붙인다.
- 양: 완전하면 `consumed` 그대로. 값 없는 항목이 있으면 아는 항목의 합을 하한으로 `<합> 이상 (값 없는 항목 N개)`라고
  쓴다(합계라고 하지 않는다). 그 합도 없으면 `알 수 없음`.
- 목표: 정확값, `최소-최대`, 또는 `없음`. 괄호 안은 JSON의 상태 값 그대로이고, 상태에 따라 `, N 남음`, `, 최소까지 N`,
  `, 최대까지 N`, `, N 초과`(초과량을 모르면 `, 초과량 알 수 없음`)가 붙는다. 추정 source가 섞이면 `(추정 포함)`.
- 식사 기록이 없으면 머리줄이 `영양 MM-DD: 오늘 기록 없음 (0 kcal이 아님)`이다.

`/unknown`:

```text
<pre>Garmin UNKNOWN 세트가 있는 운동 2개 (최근 14일, 오늘 운동 제외)</pre>
• 10-05 근력 11세트 (세트 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13): https://connect.garmin.com/modern/activity/24610155225
  고친 뒤: /refresh 24610155225
• ...
Garmin Connect에서 운동 이름을 고친 뒤 /refresh로 다시 받습니다.
모두 다시 받기: /refresh                                                        (v1.2)
```

- 개수 제한 없이 모두 보인다. 없으면 `Garmin UNKNOWN 세트가 있는 운동 없음 (최근 14일, 오늘 운동 제외)`.

`/refresh 24610155225`:

```text
refresh 실행 중: Garmin에서 운동 24610155225를 다시 받습니다. 끝나면 결과를 보냅니다.
```

```text
refresh 24610155225 완료: 10-05 근력, UNKNOWN 11 → 0세트
```

- 아직 UNKNOWN이 남으면 `아직 UNKNOWN 2세트: Garmin Connect에서 고친 뒤 /refresh <id>를 다시 보내세요.`가 붙는다. 날짜를
  모르면 `날짜 알 수 없음`.
- 세트 수는 refresh 전과 후에 DB를 read-only(`mode=ro` + `PRAGMA query_only`, migrate 없음)로 읽어 센다. recommend의 UNKNOWN
  notice와 **같은 판정 함수**(`unknown_active_set_sequences`)를 쓰므로, 날짜와 상관없이 그 운동의 notice 세트 수와 같다.
- 전후 값을 구할 수 없거나(읽기 실패) 근력 운동이 아니면, 추측하지 않고 CLI 결과 첫 줄(`Garmin activity refresh complete`)만
  보낸다.
- 어느 경우든 CLI 결과의 `경고: ` 줄(Garmin endpoint 경고)을 그대로 붙인다.
- 거부와 실패:
  - 형식이 틀린 id → 사용법 답장. 아무것도 실행하지 않는다.
  - 적용 안 된 migration → v1과 같은 `오류: DB에 아직 적용하지 않은 migration ...`. 진행 안내도 없다.
  - 저장되지 않은 activity → 진행 안내 뒤 CLI 거부 그대로(`오류: local Garmin activity not found: <id>`). Garmin에 접속하지
    않는다.
  - Garmin 로그인이 필요함 → 진행 안내 뒤
    `오류: Garmin에 다시 로그인해야 합니다. PC 터미널에서 muscle50 garmin refresh <id>를 한 번 실행하세요(로그인한 뒤 그대로 refresh됩니다).`
    로그인 prompt가 빈 stdin에서 바로 끝나므로 RAW와 DB에 아무것도 쓰지 않는다.
  - 그 밖의 CLI 오류(exit 1)는 v1처럼 `오류:` 줄 그대로.

## 규칙

- 요약의 숫자, 무게, 상태 이름, 운동 label은 같은 명령의 JSON 값 그대로다. 다시 계산하거나 반올림을 바꾸지 않는다. JSON에
  없는 값은 `알 수 없음`이나 구체적인 상태(`오늘 수면 기록 없음`, `0 kcal이 아님`)로 쓰고 0으로 채우지 않는다.
- 같은 JSON이면 요약은 byte 단위로 같다.
- 메시지 나누기: `<pre>` 본문은 v1 규칙(줄 경계, 손실 없음)으로 나누고, 그 뒤 rich 묶음(UNKNOWN 한 항목 = 두 줄)을 순서대로
  4096 UTF-16 단위 안에 채운다. 한 묶음은 한 메시지 안에 둔다. 보통 요약은 메시지 하나다.
- 링크가 있는 메시지(`<a href=`가 있을 때만)는 `link_preview_options: {"is_disabled": true}`로 보내 Garmin Connect 미리보기
  카드가 붙지 않게 한다. 링크가 없는 메시지는 v1과 같은 요청이다.
- stdout이 JSON이면 exit 코드와 상관없이 요약한다(`daily`는 실패 단계가 있으면 JSON을 출력하고 exit 1). stdout이 비어 있으면
  v1처럼 stderr의 `오류:` 줄을 보낸다.
- stdout이 JSON이 아니면 v1처럼 text로 보내고, 콘솔에 `chat N: /today reply was not JSON; relayed as text`를 남긴다.
- JSON 모양이 예상과 다르면(key 없음, 타입이 다름, 모르는 상태 값, 숫자가 아닌 activity id) bot은 멈추지 않고
  `오류: 결과를 요약하지 못했습니다. 전체: /today full`(`/status`는 `/status full`, `/daily`는
  `오류: daily는 끝났지만 결과를 요약하지 못했습니다 (exit N). 저장된 데이터로 본 전체 계획: /today full`)로 답하고 콘솔에
  `chat N: /today summary failed (KeyError)`를 남긴다.
- 콘솔 줄은 v1과 같다(`chat N: /today -> exit 0`, `full`이어도 명령 이름만). `/refresh`의 전후 세트 수를 읽지 못하면
  `chat N: /refresh could not count UNKNOWN sets (<예외 종류>)`를 남긴다.
- bot이 쓰는 고정 문구는 `domain/telegram_commands.py`, 데이터로 만드는 요약 형식은 `presentation/telegram_summary.py`에 있다.

## Known issues / limitations (v1.1)

- **오늘 한 운동의 UNKNOWN은 다음 날부터 보인다.** recommend는 오늘 한 근력 운동을 계획에서 빼므로, `/today`, `/daily`,
  `/unknown`에도 오늘 운동의 UNKNOWN이 나오지 않는다. `/refresh <id>`는 오늘 운동에도 쓸 수 있다.
- UNKNOWN 목록은 recommend의 기간(오늘 전 14일)만 본다. 더 오래된 운동은 `/refresh <id>`로 직접 다시 받을 수 있다.
- 자동 refresh가 없다. Garmin에서 고친 운동은 `/refresh`를 보내야 반영된다.
- Garmin Connect 링크(`https://connect.garmin.com/modern/activity/<id>`)가 휴대폰에서 웹으로 열릴지 앱으로 열릴지는 기기
  설정에 따른다. URL 형식은 live 확인 전까지 검증되지 않았다.
- `<code>`를 탭해서 복사하는 동작은 Telegram 앱 버전에 따른다. 복사가 안 되면 길게 눌러 복사한다.
- 요약은 리포트의 일부만 보여 준다. 근거, region 순위, 진척 근거, 전체 notice는 `full`로 본다.
- 요약은 JSON key 이름에 의존한다. CLI JSON이 바뀌면 golden 기반 테스트가 잡고, 실행 중에는 bot이 멈추지 않고
  "요약하지 못했습니다"와 `full` 안내로 답한다.
- `/refresh`의 `경고: ` 줄은 `garmin refresh` text 출력의 접두어에 의존한다(`garmin refresh`에는 `--json`이 없다). v1의
  `Recorded meal` 줄과 같은 종류의 결합이다.
- `/daily`가 실패하면 요약에 계획이 없다. 저장된 데이터로 본 계획은 `/today`로 따로 본다.
- 이 절의 답장 형식은 live 확인(통합 후 사용자 게이트) 전까지 실제 Telegram 앱에서 보이는 모양을 확인하지 않았다.

# v1.2 Telegram Refresh All UNKNOWN

Spec: `docs/specs/telegram-refresh-unknown.md`. Migration 없음. CLI 출력 변경 없음(`cli.py`는 바뀌지 않았고, 모든 CLI
명령의 text와 JSON은 그대로다). bot 답장만 바뀐다.

- 인자 없는 `/refresh`가 v1.1의 사용법 답장 대신 UNKNOWN 운동을 모두 다시 받는다.
- `/refresh` 사용법 답장과 `/help`가 바뀐다.
- `/today`, `/daily`는 UNKNOWN 알림이 있을 때, `/unknown`은 목록이 비어 있지 않을 때 `모두 다시 받기: /refresh` 한 줄이
  붙는다.
- 그대로인 것: `/refresh <id>`, 모든 `full` 답장, `/status`, `/day`, `/log`, `/void`, `/show`, `/inbody`, UNKNOWN 알림이 없는
  `/today`와 `/daily`, 빈 `/unknown`.

## 목적과 non-goal

- Garmin Connect에서 여러 운동의 UNKNOWN 이름을 고친 뒤, 명령 하나로 모두 다시 받는다. v1.1에서는 운동마다
  `/refresh <id>`를 복사해서 보내야 했다.
- Non-goal: 자동 refresh(사용자가 보낼 때만 실행), 대상 확장(`/unknown` 목록만, UNKNOWN이 없는 운동과 수영은 대상이 아니다),
  운동 이름 추측, 새 CLI 명령(`garmin refresh`를 하나씩 실행한다), migration, CLI 출력 변경.

## 명령

| bot 명령 | 실행되는 CLI 명령 | 답장 | migration 검사 | 진행 안내 |
|---|---|---|---|---|
| `/refresh` | `recommend --date <오늘> --json`(목록), 운동마다 `garmin refresh <id>`, 다시 `recommend --date <오늘> --json`(남은 수) | 결과 요약 하나 | 있음(시작 전 한 번) | `refresh 실행 중: ...` |
| `/refresh <activity_id>` | `garmin refresh <activity_id>` | v1.1 그대로 | 있음 | v1.1 그대로 |

- `/refresh@<bot>`도 같다. `/refresh_<id>` 별칭은 여전히 없다.
- 사용법 답장:

```text
사용법: /refresh [activity_id]
Garmin Connect에서 운동 이름을 고친 뒤 보냅니다. 인자가 없으면 UNKNOWN 세트가 있는 최근 운동을 모두(한 번에 10개까지), activity_id(숫자)를 주면 그 운동 하나만 다시 받습니다.
예: /refresh 24610155225
```

- `/help`의 `/refresh` 줄은 두 줄이 된다: `/refresh - UNKNOWN 세트가 있는 최근 운동을 모두 다시 받기(한 번에 10개까지)`,
  `/refresh <activity_id> - Garmin에서 고친 운동 하나를 다시 받기`.

## 흐름

1. 적용 안 된 migration을 확인한다(v1 규칙). 있으면 v1의 `오류: DB에 아직 적용하지 않은 migration ...`만 답하고 아무것도
   실행하지 않는다. 목록도 읽지 않고 진행 안내도 없다.
2. **대상 목록**: `recommend --date <오늘> --json`을 한 번 실행하고 `strength.unknown_notices`를 JSON 순서(최근 운동 먼저)대로
   쓴다. `/unknown`과 같은 목록이다(오늘 전 14일, 오늘 운동 제외). 실행 중에 목록이 바뀌어도 다시 계산하지 않는다.
   - 목록이 비어 있으면 `UNKNOWN 세트가 있는 운동이 없습니다 (최근 14일, 오늘 운동 제외). 다시 받을 것이 없습니다.`만
     답한다. Garmin에 접속하지 않는다.
   - 목록을 읽지 못하면 Garmin에 접속하지 않는다. stdout이 없으면 CLI의 `오류:` 줄 그대로(예: DB 없음), JSON이 아니면 text
     그대로, JSON 모양이 다르면 `오류: UNKNOWN 목록을 읽지 못해 아무것도 다시 받지 않았습니다. 전체: /today full`.
3. **상한**: 한 번에 최근 **10개**까지 받는다(`REFRESH_ALL_CAP`). 진행 안내를 먼저 보낸다:
   - `refresh 실행 중: UNKNOWN이 있는 운동 3개를 Garmin에서 차례로 다시 받습니다. 끝나면 결과를 보냅니다.`
   - 상한을 넘으면 `refresh 실행 중: UNKNOWN이 있는 운동 12개 중 최근 10개를 Garmin에서 차례로 다시 받습니다(한 번에 10개까지). 끝나면 결과를 보냅니다.`
4. **운동마다**(차례로, 동시 실행 없음): v1.1 `/refresh <id>`와 같은 순서다. UNKNOWN 세트 수를 read-only로 읽고,
   `garmin refresh <id>`를 in-process로 실행하고(`cli.main`), 성공하면 다시 센다. 운동 사이에 **2초** 쉰다(첫 운동 앞과
   마지막 운동 뒤에는 쉬지 않는다).
   - Garmin 로그인은 v1.1과 같이 운동마다 한 번이다(`garmin refresh`가 저장된 token으로 `authenticate`). 운동 하나에 Garmin
     요청이 약 7번(profile 2번 + activity 5번)이므로 10개면 약 70번이다.
   - CLI 오류(exit 1, 예: Garmin 조회 실패, 저장되지 않은 activity)는 그 운동을 `실패`로 표시하고 다음 운동으로 넘어간다.
   - **연속 3번** 실패하면(`MAX_CONSECUTIVE_REFRESH_FAILURES`, `garmin recovery` 기간 동기화의 연속 실패 규칙과 같은 방식)
     Garmin 쪽 제한이나 장애로 보고 멈춘다. 성공 한 번이면 연속 수가 0으로 돌아간다.
   - **Garmin 로그인이 필요하면**(로그인 prompt가 bot의 빈 stdin에서 EOF) 바로 멈춘다. 그 운동은 아무것도 쓰지 않았으므로
     `받지 않음`이다.
   - **그 밖의 예상하지 못한 예외**가 나면 그 운동은 `실패`로 표시하고 멈춘다(같은 오류가 운동마다 되풀이될 수 있으므로).
     traceback은 콘솔에 남는다.
   - 멈추면 남은 운동은 모두 `받지 않음`이다.
5. **남은 수**: 같은 `recommend --date <처음 날짜> --json`을 한 번 더 실행해 `unknown_notices` 수를 센다. 멈춘 경우에도
   실행한다. 읽지 못하면 `알 수 없음`이다(0이 아니다).
6. 결과 답장 하나를 보낸다.

- 이 모든 단계가 **handled update 하나**다(v1 at-most-once). update id는 첫 CLI 실행 전에 저장된다.
- **Ctrl+C**: v1과 같이 바로 멈추고 exit 130. 결과 답장은 없다. 이미 받은 운동은 저장된 채로 남고(운동마다 RAW + transaction),
  다시 시작해도 다시 실행하지 않는다. 남은 것은 `/unknown`으로 보고 `/refresh`를 다시 보낸다.

## 결과 답장(합성 값)

```text
<pre>refresh 완료: 3개 중 3개 받음
• 10-05 24610155225: UNKNOWN 11 → 0세트
• 10-02 24576105658: UNKNOWN 16 → 4세트 (아직 남음)
  경고: original archive를 다운로드하지 못했습니다.
• 09-23 24400000001: UNKNOWN 3 → 3세트 (변화 없음)</pre>
남은 UNKNOWN: 2개 운동 · /unknown
```

멈춘 경우(연속 실패, 상한 초과):

```text
<pre>refresh 중단: 10개 중 1개 받음, 3개 실패, 6개 받지 않음 (연속 3번 실패)
• 10-05 24610155225: UNKNOWN 2 → 0세트
• 10-04 24600000002: 실패
  오류: Garmin activity 원본 조회에 실패했습니다.
• ...
• 10-01 24600000005: 받지 않음
...</pre>
Garmin 쪽 제한이나 장애일 수 있습니다. 잠시 뒤 다시 받기: /refresh
나머지 2개는 받지 않았습니다(한 번에 10개까지). 다시 받기: /refresh · 목록: /unknown
남은 UNKNOWN: 11개 운동 · /unknown
```

- **머리줄**: `refresh 완료` 또는 `refresh 중단`, `: N개 중 K개 받음`, 그리고 0이 아닐 때만 `, F개 실패`, `, R개 받지 않음`.
  멈췄으면 이유 `(연속 3번 실패)`, `(Garmin 로그인 필요)`, `(예상하지 못한 오류)`.
- **운동 줄**: `• MM-DD <activity_id>: ` 뒤에(날짜는 목록 JSON의 `local_date`, 같은 날 운동이 둘이어도 구별되도록 id를 쓴다)
  - 받음, 전후 수를 읽었고 근력 운동, 후 0: `UNKNOWN 11 → 0세트`
  - 받음, 후 = 전 > 0: `UNKNOWN 3 → 3세트 (변화 없음)`. 같은 수라고 Garmin에서 고치지 않았다고 단정하지 않는다.
  - 받음, 그 밖의 후 > 0: `UNKNOWN 16 → 4세트 (아직 남음)`
  - 받음, 전후 수를 읽지 못했거나 근력 운동이 아님: CLI 결과 첫 줄 그대로(`Garmin activity refresh complete`, v1.1 규칙)
  - 받음: CLI 결과의 `경고: ` 줄을 그 운동 밑에 두 칸 들여 그대로 붙인다.
  - 실패: `실패`, 그 밑에 CLI 오류의 모든 줄을 두 칸 들여 그대로. 예상하지 못한 예외로 멈춘 운동은 `실패`만 쓴다.
  - 받지 않음: `받지 않음`
- **`<pre>` 끝**: 로그인으로 멈췄으면 v1.1과 같은
  `오류: Garmin에 다시 로그인해야 합니다. PC 터미널에서 muscle50 garmin refresh <멈춘 id>를 한 번 실행하세요(로그인한 뒤 그대로 refresh됩니다).`,
  예상하지 못한 예외면 `오류: 예상하지 못한 오류로 명령을 마치지 못했습니다 (<예외 종류>). telegram run 콘솔을 확인하세요.`
- **`<pre>` 밖**(일반 text라 `/refresh`, `/unknown`을 탭하면 바로 보내진다), 이 순서로:
  1. 연속 실패로 멈춤: `Garmin 쪽 제한이나 장애일 수 있습니다. 잠시 뒤 다시 받기: /refresh`. 로그인으로 멈춤:
     `로그인한 뒤 나머지 다시 받기: /refresh`. 예상하지 못한 예외: 줄 없음.
  2. 상한을 넘었으면 `나머지 N개는 받지 않았습니다(한 번에 10개까지). 다시 받기: /refresh · 목록: /unknown`
  3. 항상 남은 수: `남은 UNKNOWN: M개 운동 · /unknown`, 0이면 `남은 UNKNOWN 운동 없음 (최근 14일, 오늘 운동 제외)`, 읽지
     못하면 `남은 UNKNOWN: 알 수 없음 · /unknown`.
- 메시지 나누기는 v1.1과 같다(손실 없는 4096 UTF-16 단위). 10개면 보통 메시지 하나다.
- 같은 데이터면 답장은 byte 단위로 같다.

## `모두 다시 받기` 줄

- `/today`, `/daily`: UNKNOWN 알림이 있을 때만, 항목과 `외 N개 · /unknown` 뒤, 마지막 `기타 알림 N건 · 전체: /today full`
  앞에 `모두 다시 받기: /refresh`.
- `/unknown`: 목록이 비어 있지 않을 때만 `Garmin Connect에서 운동 이름을 고친 뒤 /refresh로 다시 받습니다.` 뒤에 붙는다.
- `<code>`가 아니라 일반 text다. 탭하면 인자 없는 `/refresh`가 바로 보내진다.

## 콘솔 줄(ASCII, 메시지 내용 없음)

```text
chat 111: /refresh targets -> exit 0
chat 111: /refresh all: 3 activities (cap 10)                 (상한을 넘으면 10 of 12 activities, 없으면 no UNKNOWN activities)
chat 111: /refresh all 1/3 -> exit 0                          (운동마다)
chat 111: /refresh all stopped after 3 consecutive failures   (멈췄을 때, 또는 needs a Garmin login in a terminal,
                                                               또는 failed with <예외 종류> + traceback)
chat 111: /refresh remaining -> exit 0
```

- 남은 수를 읽지 못하면 `chat N: /refresh remaining count unknown (<이유>)` 또는
  `chat N: /refresh remaining failed with <예외 종류>`. 전후 세트 수를 읽지 못하면 v1.1과 같은
  `chat N: /refresh could not count UNKNOWN sets (<예외 종류>)`. Ctrl+C는 v1과 같은
  `chat N: /refresh interrupted by Ctrl+C; it will not be run again`.

## 코드 위치

- 고정 문구, 상한 10, 인자 없는 `/refresh` 문법: `domain/telegram_commands.py`.
- 실행 순서, 연속 실패 3번, 2초 간격: `application/telegram_bot.py`(`RunTelegramBot._refresh_all`).
- 목록 읽기와 결과 답장 형식: `presentation/telegram_summary.py`(`refresh_targets`, `refresh_all_reply`).
- 테스트: `tests/test_telegram_refresh_all.py`(가짜 Telegram API, 운동마다 가짜 Garmin connector, 임시 MUSCLE50_HOME),
  `tests/test_telegram_summary.py`(답장 형식).

## Known issues / limitations (v1.2)

- **상한 10개, 최근 것부터.** Garmin에서 아직 고치지 않은 최근 운동이 10개 이상 남아 있으면 `/refresh`를 다시 보내도 같은
  10개를 다시 받고, 더 오래된 운동에는 닿지 않는다. 그런 운동은 `/unknown`에서 `/refresh <id>`로 하나씩 받는다.
- 고치지 않은 운동도 목록에 있으면 다시 받는다(요청은 쓰지만 결과는 `(변화 없음)`).
- Garmin 요청은 운동마다 약 7번(로그인 확인 profile 2번 + activity 5번)이라 10개면 약 70번이다. v1.1 문서의 "운동마다 Garmin
  요청 4~5번"은 activity 요청만 센 값이다. Garmin의 실제 제한은 문서화되어 있지 않다. 로그인 제한
  (`Garmin 로그인 요청이 제한되었습니다`)은 운동마다 exit 1로 오므로 연속 3번에서 멈춘다.
- 실행 중(10개면 약 1~2분, 쉬는 시간 약 18초 포함) bot은 다른 메시지를 처리하지 않는다. 그 메시지는 Telegram에 쌓였다가
  끝난 뒤 처리된다(bot 시작 뒤에 보낸 것이므로 stale이 아니다). Windows에서 Garmin 요청 중의 Ctrl+C 지연은 v1과 같다.
- Ctrl+C나 crash로 중간에 멈추면 결과 답장이 없다. 이미 받은 운동은 저장되어 있고, `/unknown`으로 남은 것을 본다.
- 오늘 운동은 대상이 아니다(v1.1과 같은 목록). 오늘 운동은 `/refresh <id>`로 받는다.
- 인자 없는 `/refresh`는 이제 탭 한 번으로 Garmin 요청을 시작한다. v1.1 `/unknown`의 `... /refresh로 다시 받습니다.` 줄의
  `/refresh`도 탭하면 실행된다(v1.1에서는 사용법 답장이었다).
- 운동 줄의 `경고: ` 줄과 CLI 첫 줄 fallback은 `garmin refresh` text 출력에 의존한다(v1.1과 같은 결합).
- 이 절의 답장 형식은 live 확인(통합 후 사용자 게이트) 전까지 실제 Telegram 앱과 실제 Garmin에서 확인하지 않았다.

# Nutrition General Meal v1: `/log 일반식`

메뉴나 영양값을 모르는 식사(구내식당, 배달, 집밥 반찬)를 "일반식을 먹었다"는 기록만으로 남긴다. CLI의
`nutrition log --general [--general-note TEXT]`와 같다. 규칙과 출력은 [nutrition-general-meal.md](nutrition-general-meal.md).

## 문법

`/log <meal>[+] <item>[, <item> ...]`의 각 item 자리에 `일반식 [메모]`를 쓸 수 있다.

```text
/log lunch 일반식                       -> nutrition log --meal lunch --general
/log lunch 일반식 구내식당              -> ... --general --general-note=구내식당
/log dinner 일반식, 닭가슴살 100 g      -> ... --general --item 닭가슴살 100 g
/log lunch+ 일반식 구내식당, 일반식 배달 -> 일반식 두 개(메모 각각), 그리고 --additional
```

- item의 첫 단어가 정확히 `일반식`이면 일반식이다. 나머지 단어(공백 하나로 다시 이음)가 메모이고, 메모는 쉼표에서 끝난다.
- 메모는 `--general-note=<메모>` 한 argv로 넘긴다(`/void`의 `--reason=`과 같다). 메모 검사(100자 이하, 한 줄)는 CLI가 하고,
  어기면 CLI의 `오류:` 줄이 그대로 답으로 온다. 아무것도 저장되지 않는다.
- **거부(사용법 답장):** 메모의 마지막 두 단어가 숫자(`1`, `1.5`)와 단위(`g`, `ml`, `count`, `pack`, `piece`, `animal`,
  `serving`)이면 거부한다. 예: `일반식 1 serving`, `일반식 제육 2 pack`. 카탈로그 음식 "일반식"의 수량으로도 읽히기 때문이다.
  메모로 바꾸거나 무시하지 않는다.
- 비슷한 말(`일반`, `일반식사`, `밥`, `식사`, 붙여 쓴 `일반식구내식당`)은 일반식으로 추측하지 않는다. 기존 item 규칙(3단어
  이상, 마지막 두 단어가 수량과 단위)을 따르고, 그렇지 않으면 사용법 답장이다.
- `-`로 시작하는 단어는 메모에서도 형식 오류다(기존 규칙).
- 답장은 `nutrition log` stdout 그대로이고, 끝에 `취소: /void <meal_id>` 줄이 붙는다(변경 없음).

답장 예(합성 값):

```text
Recorded meal 2026-10-08-lunch-1.

[lunch] 2026-10-08-lunch-1 (2026-10-08, time not recorded)
  1. 일반식 (general meal; note: 구내식당): nutrition unknown
     source: no nutrition facts
     missing: kcal, protein, carbohydrate, fat
  Meal total: kcal incomplete (no item has a value) | P incomplete (no item has a value) | ...

Whole day: muscle50 nutrition day --date 2026-10-08
취소: /void 2026-10-08-lunch-1
```

## 요약

`/status`, `/today`, `/daily` 요약은 바뀌지 않았다. 일반식만 있는 날은 `kcal 알 수 없음 / 목표 2200-2500 (indeterminate)`,
카탈로그 음식과 섞인 날은 `단백질 23 g 이상 (값 없는 항목 1개) / 목표 120 g (indeterminate)`처럼 나온다. 남은 양(`남음`)이나
행동 안내는 나오지 않는다.

`/help` 목록의 `meal:` 줄 아래와 `/log` 사용법 답장에 `일반식 [메모]` 설명이 한 줄씩 추가되었다.

## Known issues / limitations (General Meal v1)

- 메모에는 쉼표를 쓸 수 없다(쉼표가 item을 나눈다). `-`로 시작하는 단어도 쓸 수 없다.
- 전에는 `/log lunch 일반식 도시락 1 pack`이 "일반식 도시락"이라는 카탈로그 음식으로 기록되었다. 이제는 거부된다(위 규칙).
  이름이 `일반식`으로 시작하는 음식은 food ID로 기록한다. (2026-10-08 production 카탈로그에는 그런 음식이 없다.)
- 일반식이 있는 날은 영양 판단이 "알 수 없음"으로 남는다. 의도된 동작이다. 요약에 "일반식 N끼"는 아직 없다(후속 후보).
- 이 절의 답장은 live 확인(통합 후 `telegram run` 재시작, 사용자 게이트) 전까지 실제 Telegram 앱에서 확인하지 않았다.
