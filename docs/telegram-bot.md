# Telegram Command Bot v1

Spec: `docs/specs/telegram-bot.md`. Migration 없음(설정과 상태는 JSON 파일, DB schema 변경 없음). Output change: additive
(새 `telegram` 명령 그룹. `muscle50 --help`에 한 줄이 늘어난다).

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
- 그래서 CLI handler가 `migrate()`를 부르는 명령(`/status`, `/day`, `/show`, `/log`, `/void`, `/daily`)을 실행하기 전에
  DB를 read-only(`mode=ro` + `PRAGMA query_only`)로 열어 `schema_migrations`와 코드의 migration 번호를 비교한다.
  빠진 번호가 있으면 실행하지 않고 다음처럼 답한다.

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
  안에서 자른다. 내용은 버리지 않는다. `/today`는 보통 2개 메시지로 온다.
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
