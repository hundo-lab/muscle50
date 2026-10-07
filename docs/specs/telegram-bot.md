---
id: telegram-bot
title: Telegram Command Bot v1
status: integrated
migration: none
output_change: additive
user_gates: [design, integration, push]
---

# Telegram Command Bot v1

## 목적

- 휴대폰의 Telegram에서 정해진 명령으로 muscle50을 쓴다. 예를 들어 오늘 운동 추천, 남은 단백질과 kcal,
  식사 기록과 취소, InBody 추세를 본다. PC 앞에 앉아 터미널을 열지 않아도 된다.
- 근거: `docs/goals.md` 3절 "나중에: Telegram 등 채팅으로 묻기. 기존 use case를 그대로 부르는 얇은 층". 사용자가
  2026-10-06에 우선순위를 앞당겼다. 매일 식사 기록의 마찰을 줄이는 것이 목적이다(우선순위 3과 같은 방향).
- v1은 **LLM 없이 명령어형**이다(2026-10-06 사용자 결정). 자유 문장(LLM)은 v2에서 이 명령 위에 얹는다.

## 범위 / Non-goals

- 범위:
  - 새 명령 `muscle50 telegram run`. 이 PC에서 Telegram Bot API long polling으로 메시지를 받는다. 허용된 chat에서 온
    명령만 기존 use case를 불러 처리하고, CLI와 같은 text 결과를 답장으로 보낸다.
  - 새 명령 `muscle50 telegram check`. 설정 파일과 token을 검사하고 bot 이름을 보여 준다. 메시지는 처리하지 않는다.
  - v1 bot 명령(아래 "명령 예시"): `/help`, `/today`, `/status`, `/day`, `/log`, `/void`, `/show`, `/inbody`, `/daily`.
- Non-goals:
  - LLM과 자유 문장 해석 없음. 명령 형식이 틀리면 사용법을 답한다. 뜻을 추측하지 않는다.
  - webhook, 공개 서버, 클라우드 배포 없음. 이 PC에서 실행하는 동안만 동작한다.
  - 여러 사용자 없음. 허용 목록의 chat만 받는다.
  - 예약 알림(아침 자동 추천 push 등) 없음. 후속 후보다.
  - Windows 서비스나 자동 시작 등록 없음.
  - migration 없음. 기존 CLI 명령의 동작과 출력 변경 없음.
  - 새 Python 의존성은 되도록 추가하지 않는다. 표준 라이브러리(`urllib`, `json`)로 Bot API를 부르는 것을 기본으로
    하고, 다르게 하려면 설계에서 이유를 적는다.
  - 메뉴 추천, 조정 권고 같은 새 판단 기능 없음. 이미 있는 기능만 부른다.

## 명령 예시

CLI:

```powershell
muscle50 telegram check                 # 설정·token 확인, bot 이름 출력, 메시지 처리 안 함
muscle50 telegram run                   # long polling 시작, Ctrl+C로 종료(exit 130)
```

설정 파일 `%LOCALAPPDATA%\muscle50\config\telegram.json`. 사용자가 직접 만든다. repo에 두지 않고 commit하지 않는다.

```json
{
  "bot_token": "<BotFather가 준 token>",
  "allowed_chat_ids": [123456789]
}
```

Telegram에서 보내는 명령(합성 예시):

```text
/help
/today                                   → recommend (오늘)
/status                                  → nutrition status (오늘)
/day                                     → nutrition day (오늘)
/day 2026-10-05                          → nutrition day --date 2026-10-05
/log lunch 닭가슴살 150 g, 햇반 1 pack     → nutrition log --meal lunch --item 닭가슴살 150 g --item 햇반 1 pack
/log lunch+ 바나나 1 count                → 같은 날 같은 종류가 있어도 기록(--additional)
/void 2026-10-06-snack-1 중복 기록         → nutrition meal void ... --reason "중복 기록"
/show 2026-10-06-lunch-1                 → nutrition meal show
/inbody                                  → inbody trend
/daily                                   → daily (Garmin 동기화 포함)
```

`/log` 답장 예시(합성 값, 본문은 CLI text 출력과 같다):

```text
Recorded meal 2026-10-06-lunch-1.
...
취소: /void 2026-10-06-lunch-1
```

허용되지 않은 chat에서 온 메시지에는 답하지 않는다. `telegram run` 콘솔에만 한 줄을 남긴다(합성 예시).

```text
ignored message from chat 987654321 (not in allowed_chat_ids)
```

## 규칙

- 설정:
  - token과 허용 chat 목록은 `config\telegram.json`에서만 읽는다. 환경 변수로 덮어쓸지는 설계에서 정한다.
  - 파일이 없거나 형식이 틀리거나 `allowed_chat_ids`가 비어 있으면 `오류:`와 exit 1로 끝낸다. 무엇이 틀렸는지 말하고,
    Telegram에 연결하지 않는다.
  - token은 어떤 출력, 로그, 오류 메시지, 예외 메시지에도 나오지 않는다. URL에 들어간 token도 가린다.
- 수신과 권한:
  - long polling(`getUpdates`)만 쓴다. 허용 목록에 없는 chat의 메시지에는 답하지 않고 아무것도 쓰지 않는다.
  - 메시지는 받은 순서대로 하나씩 처리한다(동시 처리 없음).
  - 처리한 update는 다시 처리하지 않는다. 재시작 뒤 이전 update를 다시 받아 `/log`가 중복 기록되지 않게 한다.
    update offset을 어디에 저장할지는 설계에서 정한다(예: `config\telegram_state.json`). DB schema는 바꾸지 않는다.
- 명령 처리:
  - 각 bot 명령은 해당 CLI 명령과 **같은 use case와 같은 renderer**를 쓴다. 결과 text는 CLI의 stdout text와 같다.
    오류는 CLI의 `오류:` 메시지와 같다. bot 안에 새 계산이나 판단을 만들지 않는다.
  - 날짜 기본값은 CLI와 같다(`_today()`, `_local_timezone`).
  - `/log` 문법은 `/log <meal>[+] <food> <qty> <unit>[, <food> <qty> <unit> ...]`이다.
    - `<meal>`은 breakfast, lunch, dinner, snack, other 중 하나다. 끝에 `+`가 있으면 `--additional`이다.
    - 쉼표로 item을 나누고, 각 item은 마지막 두 토큰을 수량과 단위로, 그 앞을 음식으로 읽는다. 그래서 이름에
      공백이 있어도 된다.
    - 음식은 Food Name Lookup v1 규칙(ID, 또는 정확히 같은 이름/alias)을 그대로 따른다.
    - 하나라도 틀리면 아무것도 쓰지 않는다(CLI와 같은 all-or-nothing).
    - 시간(`--time`)은 v1 문법에 없다. 쓸 수 있게 할지는 설계에서 정한다.
  - `/log` 성공 답장 끝에 취소 명령 한 줄(`취소: /void <meal_id>`)을 붙인다. 이것은 bot 답장에만 붙는다.
  - 형식이 틀린 명령과 모르는 명령에는 그 명령의 사용법을 답하고 아무것도 쓰지 않는다. 비슷한 명령을 추측해 실행하지
    않는다.
  - `/daily`는 Garmin 네트워크를 쓰므로 시작할 때 짧은 한국어 진행 답("daily 실행 중: 어제와 오늘의 Garmin 동기화 후 오늘
    계획을 만듭니다. 끝나면 결과를 보냅니다.")을 먼저 보낸다. 결과는 끝난 뒤 보낸다.
    실행 중에 온 다른 메시지는 끝난 뒤 순서대로 처리한다.
- 답장 형식:
  - CLI text를 그대로 보낸다. 줄 정렬이 유지되도록 고정폭 형식으로 보내는 것을 기본으로 하고, 방법(HTML `<pre>` +
    escape 등)은 설계에서 정한다.
  - Telegram 메시지 길이 제한(4096자)을 넘으면 줄 경계에서 여러 메시지로 나눈다. 내용을 잘라 버리지 않는다.
- 실패와 복구:
  - 네트워크 오류나 Telegram API 오류가 나도 `run`은 죽지 않는다. 짧게 기다렸다가 다시 시도한다. 콘솔에 token 없이
    한 줄을 남긴다.
  - 한 명령의 처리 중 예외가 나도 bot은 계속 돈다. 그 chat에 `오류:` 답을 보낸다. 쓰기 명령이면 use case의
    transaction 규칙에 따라 부분 기록이 남지 않는다.
  - Ctrl+C는 진행 중인 명령을 끝까지 처리하고 멈출지 바로 멈출지를 설계에서 정한다. exit 130이다.
- 데이터 경로:
  - bot은 CLI와 같은 `AppPaths`(production 또는 `MUSCLE50_HOME`)를 쓴다. 각 명령은 CLI와 같은 migrate와
    ensure_directories 경로를 탄다.
  - CLI의 nutrition handler는 모든 nutrition 하위 명령에서 migrate를 부른다. 그래서 적용하지 않은 migration이 있으면
    `/log`, `/void`, `/daily`뿐 아니라 `/status`, `/day`, `/show`도 실행하지 않고 `오류:`로 답한다(DB를 read-only로 열어
    확인한다. bot은 migration을 적용하지 않는다). read-only라 이 검사가 없는 명령은 `/today`와 `/inbody`뿐이다.
- 테스트:
  - 실제 Telegram이나 네트워크를 쓰지 않는다. Bot API client를 가짜로 바꿔 넣는다. 모든 데이터는 합성 값이다.
  - 실제 bot 확인은 통합 뒤 사용자가 자기 token으로 한다(아래 한계 참고).

## 인수 조건

- [ ] AC1: 가짜 API로 허용 chat에서 온 `/today`, `/status`, `/day`, `/show`, `/inbody`의 답장 본문이 같은 날짜와
      데이터의 CLI stdout text와 byte 단위로 같다.
- [ ] AC2: `/log lunch 닭가슴살 150 g, 햇반 1 pack`이 `nutrition log --meal lunch --item 닭가슴살 150 g --item 햇반 1 pack`과
      같은 행을 저장하고, 같은 text에 `취소: /void <meal_id>` 줄을 붙여 답한다. `lunch+`는 `--additional`과 같다.
      item 하나가 틀리면(모르는 음식, 잘못된 수량) `오류:` 답과 함께 DB가 변하지 않는다.
- [ ] AC3: `/void <meal_id> <reason>`이 `nutrition meal void`와 같은 결과를 저장하고 답한다. 없는 meal이나 이미 void된
      meal이면 `오류:` 답과 함께 DB가 변하지 않는다.
- [ ] AC4: 허용 목록에 없는 chat의 메시지에는 sendMessage를 부르지 않고, DB와 파일이 변하지 않으며, 콘솔에 chat id
      한 줄을 남긴다.
- [ ] AC5: 모르는 명령, 형식이 틀린 명령, 일반 문장에는 사용법을 답하고 아무것도 쓰지 않는다.
- [ ] AC6: 같은 update를 두 번 받아도(재시작 시뮬레이션 포함) 한 번만 처리된다. `/log`가 두 번 저장되지 않는다.
- [ ] AC7: 설정 파일이 없거나, 형식이 틀리거나, 허용 목록이 비어 있으면 `telegram run`과 `telegram check`가
      `오류:`와 exit 1로 끝난다. 네트워크 호출이 없다.
- [ ] AC8: token 문자열이 stdout, stderr, 답장, 예외 메시지 어디에도 나오지 않는다. 네트워크 오류 메시지 안의 URL
      포함이다.
- [ ] AC9: 가짜 API가 네트워크 오류나 HTTP 오류를 내도 `run`이 계속 돌고, 다음 update를 처리한다. 4096자를 넘는 답장은
      내용 손실 없이 여러 메시지로 나뉜다.
- [ ] AC10: 기존 CLI 명령(`recommend`, `nutrition *`, `inbody *`, `daily`, `garmin *`)의 text와 JSON 출력이 이 기능 전과
      byte-identical이다.
- [ ] AC11: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- 이 PC에서 `telegram run`이 실행 중일 때만 답한다. PC가 꺼져 있거나 잠자기 상태면 답하지 않는다.
- 실제 Telegram 동작(token, chat id, 휴대폰 표시)은 테스트가 아닌 사용자의 수동 확인이다. 통합 뒤
  `telegram check` → `telegram run` → 휴대폰에서 `/help`, `/status` 순서로 확인한다.
- 구현·검증에서 확인한 한계(상세: `docs/telegram-bot.md` "Known issues / limitations"):
  - Windows에서 Ctrl+C는 진행 중인 long poll(최대 약 10초)이나 긴 Garmin 호출이 끝날 때까지 늦게 반영될 수 있다.
  - at-most-once의 대가: 명령 도중 꺼지거나 Ctrl+C면 답장이 없다. 그 뒤 `/log lunch+`를 다시 보내면 식사가 중복
    기록된다(`/log lunch`는 기존 중복 거부가 막는다). 다시 보내기 전에 `/day`로 확인한다.
  - Telegram bot 대화는 종단간 암호화가 아니다. 식사와 체성분 값이 Telegram 서버를 지난다. 허용 목록에는 개인 chat id만
    넣는다(group id를 넣으면 그 group의 모든 사람이 명령할 수 있다).
  - 쉼표가 들어가거나 `-`로 시작하는 음식 이름은 bot으로 기록할 수 없다(food ID를 쓴다). `-`로 시작하는 단어는 어떤
    명령에서도 형식 오류이며, `/void` 사유도 마찬가지다(CLI flag 주입 방지).
  - 새 migration을 통합한 뒤에는 백업하고 PC 터미널에서 먼저 적용한 다음 `telegram run`을 다시 시작한다. bot은
    migration을 적용하지 않고, 그 전까지 migrate하는 명령을 거부한다.
  - 실제 Telegram의 `<pre>` 표시와 Windows 콘솔의 한국어 줄 표시는 테스트가 아닌 수동 확인 대상이다.
- 후속 후보:
  - v2: 자유 문장을 LLM(Claude API)으로 해석한다. 해석 결과를 "이렇게 기록할까요?"로 확인받은 뒤 위 명령을 부른다.
    숫자와 판단은 계속 muscle50 규칙이 한다.
  - 아침 자동 알림(예약 `/daily` 결과 push), 식사 시간 알림.
  - `/log`의 시간 지정, `/edit`, `/merge`, 음식 검색(`/food`).
  - Windows 작업 스케줄러 등록, 실행 상태 확인 명령.
