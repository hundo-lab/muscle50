# Telegram Free Text, Photo and Coach v2 (telegram-llm)

Spec: `docs/specs/telegram-llm.md`. Migration 없음(추정값은 migration 003의 기존 열, 나머지는 DB 밖 파일).
Output change: additive(새 `telegram history` 명령, `nutrition log`/`meal add-item`/`food fact add`의 새 플래그, LLM이
켜졌을 때만 `/help`에 늘어나는 줄과 새 답장).

모델 선택과 재시도(Telegram LLM Model Routing v2.1, `docs/specs/telegram-llm-model-routing.md`)는 이 문서의 "모델 선택과
재시도" 절에 있다. Migration 없음. Output change: additive. 바이트가 바뀌는 곳은 그 절에 모두 적었다(`/llm` 첫 줄, 새
기록 줄의 두 key, 기본 Claude 글 모델과 그에 따른 추정 근거 문자열).

여러 끼니 한 문장, 모든 항목의 추정 범위, 카탈로그 음식 ID 제안, 웹 검색, 숫자 재확인(Telegram LLM Meal Estimates v2.2,
`docs/specs/telegram-llm-meal-estimates.md`)은 "식사 추정·여러 끼니·웹 검색 (v2.2)" 절에 있다. Migration 없음. Output
change: additive(LLM이 켜졌을 때만 바뀌는 곳은 그 절 끝의 목록에 모두 적었다).

이어지는 고치기, 라벨 값, 같은 끼니 겹침과 `/fix_`, 오늘 누적의 범위 표시와 기록한 날 누적, 양 가정, 최근 메뉴 이름으로 고르기(Telegram
LLM Corrections and Range Totals v2.3, `docs/specs/telegram-llm-corrections.md`)는 "이어지는 고치기·라벨·범위 누적 (v2.3)" 절에 있다.
Migration 없음. Output change: breaking(LLM이 켜졌을 때의 Telegram 답장 모양이 바뀐다. CLI는 `nutrition meal replace-item` 옵션만
더해졌다).

사진 여러 장(앨범), 사진을 읽지 못했을 때의 문구, 사진을 대화 기억에, bot이 멈추지 않게 하는 것과 실행 기록 파일, 메뉴 제안 4시간, 짧은 한국어 `/ok`
답장, 동기화 안내, 콘솔 오류 문구(Telegram LLM Reliability and Replies v2.4, `docs/specs/telegram-llm-reliability.md`)는 "신뢰성·앨범·짧은 답장 (v2.4)" 절에 있다.
Migration 없음. Output change: breaking(Telegram LLM 답장·콘솔 오류 문구·새 실행 기록 파일. CLI는 그대로).

실패 이유와 `/retry_`, 사용 한도 때 다른 제공자로, 기본 제공자 Codex, 기존 끼니에 더하기(`/new_`·`/add_`), 열린 제안 고치기의 앞선 요청,
코치가 bot 명령과 동기화 상태를 아는 것(Telegram LLM Failure Replies and Meal Merging v2.5,
`docs/specs/telegram-llm-failures-and-meals.md`)은 "실패 이유·다시 보내기·기존 끼니에 더하기 (v2.5)" 절에 있다. Migration 없음. Output change:
breaking(LLM이 켜졌을 때의 Telegram 답장·프롬프트·상태 파일·콘솔. CLI는 `telegram history`의 새 줄 꼬리만 바뀐다).

## 목적과 non-goal

- Telegram에서 명령어 대신 **문장과 사진**으로 식사를 기록하고, 질문하고, 메뉴를 고른다. 해석은 이 PC에 설치된
  `claude`(Claude Code) 또는 `codex`(Codex CLI)를 **사용자 본인 구독**으로, 도구 없이 실행해서 한다.
- LLM은 **읽고 JSON을 돌려줄 뿐**이다. 쓰기는 모두 사용자가 `/ok_…`로 확인한 뒤 기존 CLI 명령(`nutrition log`,
  `nutrition meal …`)으로만 한다. 운동 추천, 영양 판정, 메뉴 순서, 날짜, 숫자 계산은 muscle50 규칙이 한다.
- Non-goal: API 키 제공자, 음성, 그룹 채팅, 먼저 말 걸기, 여러 사용자, 회사 사이트(`grc.hd.com`)·HD Life 앱 접속
  (메뉴는 사용자가 보낸 캡처로만 읽는다), 단위 환산(팩 ↔ g).

## 켜기

`%LOCALAPPDATA%\muscle50\config\telegram_llm.json`을 직접 만든다. **파일이 없으면 기능이 꺼져 있고 bot은 v1.2와
byte 단위로 같다.** 모든 key는 선택이고 `{}`이면 아래 기본값이다. 모르는 key는 거절하고, 오류 문구에 값은 쓰지 않는다.
비밀값은 넣지 않는다(각 CLI의 로그인은 그 CLI가 관리한다).

```json
{
  "provider": "codex",
  "claude": {"model": "haiku", "photo_model": "sonnet", "retry_model": "sonnet", "executable": null},
  "codex": {"model": "gpt-6.1-sol", "photo_model": "gpt-6.1-sol", "retry_model": null, "executable": null},
  "persona": {"name": "머슬", "tone": "존댓말, 짧게, 담백하게"},
  "timeout_seconds": 90,
  "fallback_provider": null,
  "fallback_on_usage_limit": true,
  "keep_photos": true,
  "web_search": true,
  "web_search_max": 3,
  "web_search_timeout_seconds": 150
}
```

- `provider`: `claude` 또는 `codex`. `/llm codex`로 채팅에서 바꿀 수 있다(설정 파일은 바뀌지 않음). **v2.5부터 기본값은 `codex`다**(사용자 결정
  2026-10-21). 예전처럼 Claude를 쓰려면 `"provider": "claude"`를 적거나 `/llm claude`로 바꾼다. `provider`를 적지 않은 v2.4 파일은 재시작 뒤 Codex로
  간다.
- `model`: 글 메시지에 쓰는 모델. `null`이면 모델 옵션을 넘기지 않는다. Codex는 `--ignore-user-config`로 실행하므로 `null`은 **Codex 내장 기본
  모델**이지 `~/.codex/config.toml`에 적은 모델이 아니다.
- `photo_model`: 사진(식사 사진, 메뉴 캡처)이 붙은 요청에 쓰는 모델. `null`이면 `model`을 쓴다.
- `retry_model`: 답이 형식 실패일 때 같은 입력을 한 번 더 돌리는 모델. `null`이면 재시도하지 않는다. 방금 쓴 모델과
  같으면 재시도하지 않는다.
- 세 모델 key는 `null` 또는 `[A-Za-z0-9._:-]` 1~64자이고, 오류 문구는 key 이름만 쓰고 값은 쓰지 않는다.
- `executable`: 절대 경로 또는 `null`(PATH에서 찾음). Windows에서는 `.exe`만 실행한다(대소문자 무관). npm의
  `.cmd`/`.ps1` shim은 `executable_not_supported`로 거절한다. Python이 `cmd.exe`용으로 인자를 감싸지 않아
  `--tools ""`와 schema JSON이 깨지기 때문이다.
- `timeout_seconds`: 10~600. 넘으면 그 CLI의 프로세스 트리를 끝내고 실패로 처리한다.
- `fallback_provider`: `null`(기본) 또는 다른 제공자. 켜면 실패 시 한 번 더 시도하고, 메시지와 사진이 두 번째 회사로도
  간다.
- `fallback_on_usage_limit`(true/false, 기본 **true**, v2.5): 지금 제공자가 **사용 한도**에 걸렸을 때만 다른 제공자로 한 번 넘긴다(Codex → Claude,
  Claude → Codex). 다른 실패는 `fallback_provider`를 따른다. 넘어가면 메시지와 사진이 두 번째 회사로 가고 답장 끝에
  `(Codex 사용 한도라 이번에는 claude(Anthropic)로 처리했습니다.)`가 붙는다. 잘못된 값은 `fallback_on_usage_limit must be true or false`.
- `keep_photos`: 받은 사진을 `telegram\photos`에 보관할지.
- `web_search`(true/false, 기본 **true**), `web_search_max`(1~10, 기본 3), `web_search_timeout_seconds`(10~600, 기본 150):
  Claude에게 웹 검색을 허락하는 설정. 아래 "식사 추정·여러 끼니·웹 검색 (v2.2)"를 본다. 잘못된 형식·범위는 key 이름만
  말하고 값은 쓰지 않으며, 이 key가 없는 v2.1 파일은 기본값으로 읽는다(그래서 **재시작 뒤 검색이 켜진다**).
- 설정을 바꾸면 `telegram run`을 다시 시작한다. 시작할 때 콘솔에 한 줄이 늘어난다:
  `telegram llm: on, provider codex, fallback none, usage-limit fallback on, timeout 90 s, web search via claude when needed (max 3, 150 s); claude (C:\...\claude.exe); codex (C:\...\codex.exe)`
  (검색을 끄면 `web search off`, v2.5에서 `usage-limit fallback on|off`가 더해졌다). 제공자가 Claude면 v2.4처럼 `web search on (max 3, 150 s)`이다.
  Codex 호출은 검색하지 않고, 검색이 필요한 메시지만 Claude가 한 번 더 읽는다(아래 v2.5 "웹 검색은 Claude로만").

### 모델 선택과 재시도

| 제공자 | `model`(글) | `photo_model`(사진) | `retry_model`(형식 실패 뒤 한 번) |
|---|---|---|---|
| Claude 기본 | `haiku` | `sonnet` | `sonnet` |
| Codex 기본(v2.5) | `gpt-6.1-sol` | `gpt-6.1-sol` | `null`(재시도 없음) |

- v2.5: Codex 기본 모델은 `gpt-6.1-sol`(Codex의 Sonnet급 "workhorse" 모델, 글과 사진)이다. 그래서 기본 argv에 `-m gpt-6.1-sol`이 붙는다. 전에는 세 key가
  모두 `null`(Codex 내장 기본)이었다. 설정 파일의 `codex` 모델이 이긴다. Claude처럼 key마다 따로 기본값을 가지므로 `{"codex": {"model": "x"}}`는 글만
  `x`이고 사진은 `gpt-6.1-sol`이다. 모델 이름은 시간이 지나면 바뀐다(아래 Known issues).

- 글 메시지는 가벼운 모델로, 사진은 더 강한 모델로 돌린다. 한 메시지의 두 번째 호출(질문 답, 메뉴 제안)은 첫 호출과 같은
  규칙(글이면 `model`)을 따른다. 사진 메시지는 호출이 한 번뿐이다(v2.2의 숫자 재확인이 일어나면 한 번 더).
- 파일의 `claude`에 `model`만 있고 새 key가 없는 v2 파일은 새 key를 기본값으로 읽는다. 그래서
  `{"claude": {"model": "opus"}}`는 글은 opus, 사진은 **sonnet**, 재시도는 sonnet이다(사진이 opus에서 sonnet으로
  내려간다). 사진도 opus로 하려면 `photo_model`을 적는다. 이전 기본값(`sonnet`)에 기대던 파일은 글 모델이 `haiku`로
  바뀐다.
- **재시도 규칙**: 모델이 답했지만 쓸 수 없는 답일 때만 같은 입력을 `retry_model`로 한 번 더 돌린다.
  - 재시도하는 경우: Claude의 `result`가 JSON이 아님/문자열이 아님, 검증(스키마·범위)이 `ValueError`, Codex의 `last.json`이
    없거나 JSON이 아님.
  - 재시도하지 않는 경우: timeout, 실행 실패(`failed`), `not_found`, `executable_not_supported`, 그리고 Claude CLI가 낸
    오류 결과(`result` 이벤트 없음, `success`가 아닌 subtype, `is_error: true`; 사용 한도 메시지 등이 여기 올 수 있다).
    이 경우 한 번 더 돌려도 구독 사용량만 쓰기 때문이다.
  - 재시도가 또 실패하면 다시 재시도하지 않는다. 대체 제공자가 켜져 있으면 그 제공자가 같은 규칙으로(첫 호출 + 재시도)
    이어서 시도한다. 한 호출 단계의 CLI 실행은 최대 4번이다(v2.2: 식사 해석은 숫자 재확인의 다시 묻기까지 최대 5번).
- 매 실행은 새 임시 폴더, 전체 `timeout_seconds`, 같은 stdin·사진·정리된 환경·고정 argv로 돌고 `--model`/`-m`만 다르다.
  Codex 재시도에서도 사진은 새 `work\` 폴더에 다시 쓴다. 격리 argv는 바뀌지 않는다.
- `/llm`의 첫 줄은 실제로 쓰이는 모델을 보여 준다. `"provider": "claude"`이면
  `LLM: claude · 글 haiku · 사진 sonnet · 형식 실패 시 재시도: sonnet (글만) · 대체 제공자: 없음 · 시간 상한 90초`, v2.5 기본값(`{}`)이면
  `LLM: codex · 글 gpt-6.1-sol · 사진 gpt-6.1-sol · 형식 실패 시 재시도: 없음 · 대체 제공자: 없음 · 시간 상한 90초 · 웹 검색: Claude(필요할 때만)`
  (마지막 꼬리는 제공자가 Codex이고 `web_search`가 켜져 있을 때만).
  사진 모델이 재시도 모델과 같으면 사진은 재시도하지 않으므로 `(글만)`이 붙는다. 대체 제공자의 모델은 보여 주지 않는다.
- 콘솔(ASCII, 메시지 원문 없음): 재시도 실행은 괄호 안에 `, retry`가 붙는다.

```text
llm claude: bad output after 3.2 s (haiku)
llm claude: ok after 5.1 s (sonnet, retry)
llm claude: timeout after 90 s (sonnet, retry); trying fallback codex
```

- `telegram\history`의 새 줄은 맨 끝에 두 key를 더 가진다(`v`는 그대로 1): `retried`(`true`/`false`, LLM 호출이 없는 줄은
  `null`)와 `attempts`(`[{"provider","model","outcome","retry"}, ...]`, 호출이 없으면 `null`). 둘 다 그 메시지의
  **마지막 LLM 호출**을 설명한다(기존 `provider`/`model`/`provider_result`와 같다). 예전 16 key 줄은 다시 쓰지 않고,
  `telegram history --json`은 저장된 그대로 출력한다.
- `muscle50 telegram history`는 시도가 둘 이상이면 `provider/model`과 결과 자리에 사슬을 쓴다:
  `claude/haiku bad_output -> retry claude/sonnet ok`, `claude/sonnet timeout -> fallback codex/default ok`. 시도가 하나인
  줄과 예전 줄은 전과 같다. `/history`는 재시도한 줄의 모델 뒤에 `(재시도, 처음 haiku 형식 실패)`를 붙인다.
- 추정 일반식의 근거 문자열(`--general-estimate-ref`)은 실제로 답한 모델을 쓴다: 글은 `telegram-llm text (claude haiku)`,
  재시도했으면 재시도 모델. 이미 저장된 행은 바뀌지 않는다.

### 코치 가이드(선택)

`config\telegram_llm_coach.md`를 만들면 **매 호출마다 다시 읽어** 프롬프트에 넣는다(재시작 필요 없음). UTF-8, 4000자
이하. 너무 길거나 UTF-8이 아니면 그 호출에서 빼고 콘솔에 `coach guide ignored (<이유>)`만 남긴다. 순서는 페르소나 →
`[코치 가이드]` → `[고정 규칙]`이고, 고정 규칙이 이긴다고 프롬프트에 적혀 있다. 가이드의 숫자는 숫자 검사의 근거가
**아니다**(목표는 `nutrition_targets.json`, 제품 값은 카탈로그). 그래서 시작용 가이드에는 숫자를 넣지 않는다.

```markdown
# 코치 가이드

## 역할
- 나는 식단 코치다. 목표는 근육을 늘리면서 체지방은 최소로 늘리는 린게인이다.

## 내 생활
- 점심은 가볍게, 저녁은 든든하게 먹는다. 운동(웨이트)은 저녁에 한다.
- 수영 전에는 가벼운 탄수화물을 먹는다.

## 메뉴를 고를 때
- 2~3개만 제안한다. 단백질만 강조하지 않는다. 탄수화물을 제한하지 않는다.
- 같은 날 같은 음식을 반복하지 않게 다양하게 고른다. 외식, 배달, 편의점, 집밥을 섞는다.
- 오늘 충분히 먹었으면 억지로 더 먹으라고 하지 않는다.

## 말투
- 한국어로 짧게 답한다. 팩, 개, 마리, 공기 같은 생활 단위를 쓴다.
- 기록 결과와 누적량을 먼저, 추천은 메뉴를 먼저 말한다. 이미 말한 정보는 다시 묻지 않는다.
```

## 격리(도구 없음) — argv와 확인 결과

argv는 `src/muscle50/infrastructure/llm/argv.py`의 고정 tuple이고 테스트가 그대로 고정한다(`tests/test_telegram_llm_argv.py`).
메시지, 기억, 페르소나, 코치 가이드는 **argv에 들어가지 않고 stdin으로만** 간다. 매 호출은 새 임시 폴더
`%TEMP%\muscle50-llm-*`에서 실행하고(cwd는 그 안의 `work\`, schema·출력 파일은 cwd 밖 `io\`), 끝나면 지운다. repo나
MUSCLE50_HOME 안에서 실행하지 않는다. 자식 환경에서 `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`,
`CODEX_API_KEY`, `MUSCLE50_*`를 지운다(구독 로그인만 쓰게). shell을 거치지 않는다. stdout/stderr는 콘솔에도 기록에도
남기지 않고, 결과 종류(`ok`, `timeout`, `failed (exit N)`, `bad output`, `not found`, `executable not supported`)와 걸린
시간만 남긴다.

```text
claude -p --tools "" --safe-mode --strict-mcp-config --disable-slash-commands --no-session-persistence
       --input-format stream-json --output-format stream-json --verbose [--model <m>]
       --system-prompt <고정 ASCII 문장> --json-schema <schema JSON>
       (stdin: stream-json user 메시지 1개 = 프롬프트 text block + 사진이면 base64 image block)

웹 검색 변형(v2.2; 해석 호출에서 `web_search`가 켜져 있을 때만, Claude만):
claude -p --tools WebSearch --allowedTools WebSearch --safe-mode --strict-mcp-config --disable-slash-commands
       --no-session-persistence --input-format stream-json --output-format stream-json --verbose [--model <m>]
       --system-prompt <검색 변형 ASCII 문장> --json-schema <schema JSON>
       (`--tools WebSearch`만으로는 print 모드에서 권한이 거절돼서 `--allowedTools WebSearch`가 함께 필요하다)

codex exec --skip-git-repo-check --ephemeral -s read-only --ignore-user-config --ignore-rules -c web_search="disabled"
       --disable shell_tool --disable unified_exec --disable code_mode_host --disable computer_use --disable browser_use
       --disable browser_use_external --disable in_app_browser --disable apps --disable plugins --disable multi_agent
       --disable image_generation --disable hooks --disable tool_suggest --disable skill_search --disable goals
       --disable sleep_tool --disable view_image
       --output-schema <io\schema.json> -o <io\last.json> -C <work> [-m <m>] - [-i <work\photo.jpg>]
       (stdin: 프롬프트. `-`가 `-i`보다 앞이다. `-i`는 값을 여러 개 받아 `-`를 삼킬 수 있다)
```

### 설계 단계 확인(orchestrator, 2026-10-12)

`.git/muscle50-orchestration/reports/telegram-llm-isolation-check.md`에서 그대로 옮긴다.

> Claude Code 2.1.290 (`claude -p ... --model haiku --tools "" --no-session-persistence --output-format stream-json --verbose`, read `system/init`)
>
> | extra flags | tools | MCP servers | slash cmds | skills | auto-memory | result |
> |---|---|---|---|---|---|---|
> | none | **~150 claude.ai MCP tools (Gmail send/trash, Drive share/trash, Calendar, Notion, Canva, Claude Docs)** | 6 connected (claudeai) | 85 | 49 | loaded | OK |
> | `--strict-mcp-config` | 0 | 0 | 85 | 49 | loaded | OK |
> | `--safe-mode` | 0 | 0 | 53 | 17 | none | OK |
> | `--safe-mode --strict-mcp-config --disable-slash-commands` | 0 | 0 | 0 | 0 | none | OK (subscription login works) |
>
> Conclusion: `--tools ""` alone does NOT remove claude.ai connector tools. [...] Never `--bare`.
>
> Codex CLI 0.160.0: User config (~/.codex/config.toml) has MCP servers (cloudflare x5, node_repl) and plugins incl.
> computer-use; baseline run starts those MCP servers. `--ignore-user-config --ignore-rules` stops them; login still works.
> [...] + `-c web_search="disabled"` + `--disable code_mode_host sleep_tool`: functions.exec fails closed ("code-mode host
> is disabled"); no file read, no web search. Remaining declared tools: functions.wait, request_user_input(_async),
> collaboration.* (cannot be fully removed in 0.160.0).
> Residual risk: Codex has no single "no tools" switch; the feature list changes between versions.

### 구현 단계 확인(implementer, 2026-10-12, Claude Code 2.1.296, Codex CLI 0.160.0)

임시 폴더에서, 간단한 프롬프트와 합성 그림(빨간 32×32 PNG)으로 실행했다. 실제 사용자 데이터는 쓰지 않았다.

| # | 확인 | 결과 |
|---|---|---|
| 1 | `--input-format stream-json` + `--json-schema`: 결과 위치 | 통과. 마지막 `{"type":"result","subtype":"success"}` 줄의 `structured_output`에 객체가 있고 `result`에 같은 JSON 문자열이 있다. 코드는 `structured_output`을 먼저, 없으면 `result`를 JSON으로 읽는다. |
| 2 | `codex exec … -`가 stdin에서 프롬프트를 읽고 `-` 뒤의 `-i`를 받는지 | 통과. |
| 3 | `--disable view_image`에서도 `-i` 사진이 모델에 가는지 | 통과(모델이 색을 맞힘). 그래서 `--disable view_image`를 유지한다. |
| 4 | `--ignore-user-config`에서 `~/.codex/AGENTS.md`를 읽지 않는지 | **실패.** 모델이 사용자 전역 지시 파일의 첫 규칙(응답 언어)을 그대로 인용했다. 계획의 대안 `-c project_doc_max_bytes=0`도 결과가 같아 argv에 넣지 않았다. 아래 "한계" 참고. |
| 5 | `--system-prompt`와 stream-json을 함께 | 통과. `system/init`: tools는 `StructuredOutput` 하나(`--json-schema`가 답을 돌려주는 내장 도구이고 기능 도구가 아니다), MCP 서버 0, slash 명령 0, skill 0. |
| 6 | 두 실행 파일이 `.exe`인지 | 통과: `C:\Users\hundo\.local\bin\claude.EXE`, `...\OpenAI\Codex\bin\codex.EXE`(`shutil.which`는 대문자 `.EXE`를 돌려준다). |

이어서 이 코드(`CliLlmProvider` + `SubprocessRunner`, 실제 `subprocess.list2cmdline` 인용)로 두 CLI를 한 번씩 불렀다:
Claude(haiku)와 Codex(기본 모델) 모두 해석 schema를 받아 사진과 한국어를 맞게 읽었고(`food_text` "빨간 사과"), 임시
폴더는 남지 않았다. 처음에는 Claude가 schema의 `"$schema"` key를 거절해서(`no schema with key or ref
"https://json-schema.org/draft/2020-12/schema"`) schema 파일에서 그 key를 뺐다.

CLI를 업그레이드하면 이 확인을 다시 한다(Codex의 `--disable` 목록은 버전마다 바뀐다).

## 명령과 예(합성 값)

### 식사 기록(문장)

```text
나:   점심에 닭가슴살 한 팩이랑 햇반 먹었어
bot:  이렇게 기록할까요? (점심, 10-06)
      1. 닭가슴살 (chicken-breast) 1 pack
      2. 햇반 (hetbahn-210) 1 pack (수량 추정)
      기록: /ok_7f3a   취소: /no_7f3a
나:   /ok_7f3a
bot:  (typed /log 답장과 같은 본문)
      취소: /void 2026-10-06-lunch-1
      오늘 누적:
        kcal 480
        단백질 39 g
        탄수화물 70 g
        지방 3 g
```

- 카탈로그 음식은 먼저 Food Name Lookup 규칙(정확한 ID, 이름, alias)으로 잇는다. 아무것도 맞지 않을 때만 LLM이 고른
  카탈로그 ID를 쓴다(아래 "카탈로그 음식 ID 제안"). 연결하지 못하면 `일반식 (메모: …) - 카탈로그에 없음`, 여러 음식에
  맞으면 `- 이름이 여러 음식에 맞음`, 양을 말하지 않았으면 `- 수량·단위를 말하지 않음`으로 바꾸고, 모두 LLM의 추정 범위를
  붙인다.
- 양을 말하지 않으면 LLM이 흔한 양을 제안할 수 있지만 `(수량 추정)`이 붙고 확인을 받는다.
- 그 음식에 값이 없는 단위는 **빼지 않고** 일반식 추정으로 바꾸고 등록 방법을 보여 준다(v2.2; 이전에는 `빠짐:`으로
  뺐다): `일반식 (메모: 바나나 2 g) - 이 음식은 count 기준 값만 있습니다(단위 변환 없음)` 아래에
  `등록: muscle50 nutrition food fact add banana --per 1 g ... --new-unit`.
- 날짜는 bot이 정한다: 표현 없음·"오늘"은 오늘, "어제"는 어제, 그 밖은 `날짜를 정하지 못했습니다. /log로 보내 주세요`.
- 끼니를 말하지 않으면 지금 시각으로 정하고 `(끼니: 지금 시각 기준)`을 보여 준다: [00:00, 10:00) 아침,
  [10:00, 15:00) 점심, [15:00, 24:00) 저녁.
- 같은 날 같은 끼니가 이미 있으면 `--additional`을 붙이고 제안 **맨 위**에 `이미 기록된 점심(…)이 있어 하나 더 기록합니다.`를
  보여 준다(v2.3부터 맨 위. 같은 음식이 겹치면 고치기를 묻는다: 아래 "이어지는 고치기·라벨·범위 누적 (v2.3)").
- "먹을 예정"은 기록하지 않는다.
- 제안의 argv는 만들 때 고정해서 저장한다(자정을 넘겨 `/ok`해도 날짜가 바뀌지 않음). 유효 시간 60분(메뉴 제안만 4시간: v2.4).

### 사진

```text
나:   (제육볶음 정식 사진) 저녁
bot:  이렇게 기록할까요? (저녁, 10-06, 사진 추정)
      1. 일반식 (메모: 제육볶음 정식)
         추정: kcal 700~950, 단백질 30~45 g (estimated)
      기록: /ok_91c0   일반식만 기록(값 없이): /plain_91c0   취소: /no_91c0
```

- 4 MB 이하 중 가장 큰 크기를 받는다. 더 크면 `사진이 너무 큽니다`, 파일(document)로 보낸 이미지는 `사진으로 보내 주세요`.
- 사진인지 메뉴 캡처인지 모호하면 묻는다. 해석에 실패하면, 캡션에 먹었다는 말이 있고 메뉴 말이 없을 때만 `사진을 해석하지 못했습니다. 일반식으로만 기록할까요?`(값 없음)를
  묻고 아니면 캡션을 적어 다시 보내 달라고 한다(v2.4).

### 메뉴 캡처와 메뉴 제안

```text
나:   (구내식당 화면 캡처)
bot:  오늘 점심 메뉴예요. 남은 양: 단백질 51 g, kcal 1670 (/status)
      오늘 누적: …
      추천 순서 (메뉴 값은 사진 추정, estimated)
      1. 한식: 제육볶음, 잡곡밥   단백질 35~50 g, kcal 750~950
      2. 간편식: 닭가슴살 샐러드   단백질 25~35 g, kcal 400 (메뉴판 표기)
      3. 일품: 돈까스 카레   단백질 20~30 g, kcal 900~1150 (남은 kcal 초과 또는 알 수 없음)
      먹을 메뉴: /eat_c2e1_1 /eat_c2e1_2 /eat_c2e1_3
나:   /eat_c2e1_2      → 식사 기록 제안(일반식 + 메모 + 추정값). 확인 전에는 아무것도 쓰지 않는다.
```

"점심 뭐 먹지?"처럼 캡처 없이 물으면 bot이 오늘 영양 상태, `오늘 누적`, `recommend --json`, 오늘 먹은 것을 넘기고 LLM이
2~3개를 제안한다(`language_estimate`). 순서는 아래 규칙이 정하고, 제안 문장에 데이터에 없는 숫자가 있으면 그 문장만 뺀다.
메뉴와 제안 모두 `nutrition status`를 읽으므로 적용되지 않은 migration이 있으면 v1 문구로 거절한다.

**순서 규칙(E3, `domain/menu_ranking.py`)**

- K(남은 양을 앎): kcal 목표가 있고 오늘 kcal이 완전할 때. `B` = 범위 목표면 `remaining_to_maximum`, 정확한 목표면
  `remaining`. 0: `kmax ≤ B`, 1: `kmin ≤ B < kmax`(남은 kcal을 넘을 수 있음), 2: `kmin > B` 또는 kcal 모름. 정렬:
  (그룹, 단백질 모름, −단백질 중간값, kcal 중간값, 캡처 순서).
- R(남은 양이 범위): 목표가 있고, 모든 기록 항목에 값이나 추정 범위가 있고 추정이 하나 이상일 때.
  `B_low = max(0, 목표최대 − (확인 + 추정최대))`, `B_high = max(0, 목표최대 − (확인 + 추정최소))`; 0: `kmax ≤ B_low`,
  1: `kmin ≤ B_high`, 아니면 2. 머리줄 `남은 kcal 약 B_low~B_high (추정 포함)`.
- P(그 밖: 목표 없음, 오늘 기록 없음, 값 모르는 항목, 상태를 못 읽음): 단백질/kcal 비율 순, 값이 빠진 메뉴는 뒤로.
  머리줄에 이유를 모두 적는다. 기록이 없는 날을 "전부 남음"으로 보지 않는다.
- 목표 도달(`target_reached`, `above_*`, 남은 최대치 0인 `within_range`)이면 `오늘 kcal은 목표에 도달했습니다 (/status)`.
- 메뉴판에 적힌 값은 `[v, v]`, 중간값은 정확한 Decimal. 같은 입력이면 같은 순서다.

### 질문

```text
나:   단백질 얼마 남았어?
bot:  단백질은 120 g 목표예요.
      (근거: /status)
```

bot이 주제별로 `recommend --date <오늘> --json`, `nutrition status --json`(+ `오늘 누적`), `inbody trend --json`을 실행하고
두 번째 호출이 그 JSON만으로 답한다. **숫자 검사**: 답의 숫자(NFKC, `1,150`, `61.50`→61.5)는 넘긴 JSON의 숫자(문자열
속 숫자 포함, 정수·소수 첫째 자리 반올림 허용)여야 한다. 기억, 페르소나, 코치 가이드, 사용자 메시지는 근거가 아니다.
통과하지 못하면 LLM 답 대신 `/today`, `/status`, `/inbody`의 기존 답장을 보내고 콘솔에
`llm answer had N numbers outside the data; sent the existing replies`만 남긴다. 잡담 답에는 숫자가 하나도 없어야 한다.

### 식사 수정

```text
나:   아까 점심 닭가슴살 2팩 아니고 1팩
bot:  이렇게 고칠까요?
      점심 2026-10-06-lunch-1 item 1: 닭가슴살 2 pack → 닭가슴살 (chicken-breast) 1 pack
      고치기: /ok_7f3a   취소: /no_7f3a
```

대상 식사와 item은 그날의 활성 식사(읽기 전용)에서 끼니와 정확한 카탈로그 이름으로 찾는다. 하나로 정해지지 않으면
`/show <meal_id>` 후보만 보여 주고 아무것도 쓰지 않는다. 확인하면 `nutrition meal replace-item`/`remove-item`/`add-item`/
`void`/`edit` 중 하나를 한 번 실행하고, 답장은 그 명령의 출력, `확인: /show <id>`, `오늘 누적` 순이다.
(v2.3부터 일반식 item은 메모로도 찾고, "아침 1식"·"방금 거"를 풀며, 일반식의 추정값과 메모를 고칠 수 있다: 아래 새 절.)

### 그 밖의 명령(기능이 켜졌을 때만)

- `/llm` 지금 제공자, 글·사진 모델, 형식 실패 재시도, 대체 제공자, 시간 상한. `/llm codex|claude`는 채팅에서 바꾸고(상태 파일에 저장, 설정
  파일은 그대로) `다음 메시지부터 codex(OpenAI)로 보냅니다. 메시지와 사진이 OpenAI로 전송됩니다.`라고 답한다.
  `/llm default`는 설정 파일의 제공자로 되돌린다.
- `/memory` 다음 호출에 넘어갈 `[기억]` 블록을 그대로 보여 준다(같은 함수로 만든다). `/forget` 이 chat의 기억만 지운다
  (기록은 남는다).
- `/history [N|YYYY-MM-DD]` 최근 5개(N은 1~20) 또는 그날의 기록.
- `muscle50 telegram history [--last N | --date YYYY-MM-DD] [--json]` PC에서 같은 기록(기본 20개, N은 1~1000).
  읽기 전용이고 아무 파일도 만들지 않는다. 기록이 없으면 `No Telegram history yet.`

## 추정 일반식(estimated general meals)

사진·문장 추정은 일반식 item에 **범위만 있는 fact 하나**로 붙는다(설계 A2). CLI로도 쓸 수 있다.

```powershell
muscle50 nutrition log --meal dinner --general --general-note 제육볶음 --general-estimate visual_estimate:kcal=700-950,protein=30-45
muscle50 nutrition log --meal dinner --general --general-estimate language_estimate:fat=10-20 --general-estimate-ref "직접 입력"
```

- fact ID `<meal_id>:<item>:estimate`, 기준 1 serving(한 끼 전체), 값은 모두 NULL, 말한 영양소마다 min/max,
  `visual_estimate` 또는 `language_estimate`, `estimated`. migration 003의 기존 열과 CHECK를 그대로 쓴다.
- 값이 없으므로 합계는 계속 불완전하고, 목표 판정은 `indeterminate`, 부족·초과 행동 안내는 나오지 않는다. 범위는
  `estimated_fields`/`estimate_range`(JSON)와 텍스트 한 줄
  `1. 일반식 (general meal; note: 제육볶음): estimated kcal 700-950 | P 30-45 g | C unknown | F unknown`으로 보인다.
- `--general-estimate`는 그 `--general`(또는 그 `--general-note`) 바로 뒤, `--general-estimate-ref`는 그
  `--general-estimate` 바로 뒤에만 온다(아니면 exit 2). 잘못된 SPEC, min > max, 추정이 아닌 출처는 exit 1, 아무것도
  쓰지 않는다. ref 기본값 `nutrition log --general-estimate`, bot은 `telegram-llm photo sha256:<12자> (claude sonnet)` 또는
  `telegram-llm text (codex default)`(글 기본 모델은 `claude haiku`, 재시도했으면 재시도 모델).
- `nutrition repeat`은 추정을 버리고 일반식으로 반복한다(gate 1 D-J). `meal merge`는 추정을 그대로 옮긴다.
- 오늘 합계 줄(LLM 답장에서만): v2.3부터 영양소마다 하나의 범위 `단백질 150~165 g (값 모르는 항목 1개 빠짐)`이다(아래 새 절).
  확인 = `known_subtotal`, 추정 = 값 없는 항목 범위의 정확한 합, 모르는 값은 0으로 쓰지 않는다. 기록이 없으면 `오늘 기록 없음 (0이 아님)`.

## 식사 추정·여러 끼니·웹 검색 (v2.2)

한 문장에 여러 끼니("아침 …, 점심 …, 저녁 …")를 말해도 제안 하나로 나누고, 카탈로그에 없는 음식은 **항상 추정 범위가 붙은
일반식**으로 기록한다. 새 명령이나 migration은 없다. 아무것도 `/ok_…` 전에는 쓰지 않는다.

### 여러 끼니

```text
나:   오늘 아침 닭가슴살 2팩 즉석밥 1개, 점심 보돌미역 소고기활전복 미역국, 저녁 김밥 두줄 반 오뎅국 1개
bot:  이렇게 기록할까요? (10-13, 3끼)
      아침
        1. 닭가슴살 (chicken-breast) 2 pack
        2. CJ 햇반 백미밥 210g (hetbahn-white-210) 1 count ← "즉석밥"
      점심
        1. 일반식 (메모: 소고기활전복 미역국)
           추정: kcal 650~950, 단백질 35~55 g (estimated)
           가정: 보돌미역 메뉴를 못 찾아 일반 소고기전복미역국 정식으로 추정
           출처: namu.wiki
      저녁
        1. 일반식 (메모: 김밥 2.5줄)
           추정: kcal 800~1150, 단백질 25~40 g (estimated)
        2. 일반식 (메모: 오뎅국 1그릇)
           추정: kcal 150~300, 단백질 10~20 g (estimated)
      웹 검색 1회
      기록: /ok_5d21   값 없이 일반식만 기록: /plain_5d21   취소: /no_5d21
```

- 각 item이 자기 끼니(`meal_type`)를 갖는다. 끼니 낱말(아침, 점심, 저녁, 간식, 야식, `breakfast`…)은 음식이 아니고, 혹시
  item으로 오면 bot이 그 item을 빼고 콘솔에 개수만 남긴다(`chat N: 2 meal-word items left out`). 다 빠지면 `사용법` 답이다.
- 끼니를 하나도 말하지 않았으면 전처럼 한 끼이고 지금 시각으로 정한다. 일부 item만 끼니가 있고 맨 위 `meal_type`도 없으면
  어느 끼니인지 추측하지 않고 `bad_output`이다(재시도 규칙을 따른다). 같은 끼니의 item은 한 끼로 합치고(제안 시점에 중복을
  검사하므로 한 끼니가 두 번 나오면 둘째 `nutrition log`가 실패한다), 순서는 아침 → 점심 → 저녁 → 간식 → 기타다.
- 끼니가 하나면 v2와 똑같다(같은 문구, 같은 argv, 단일 `nutrition log`). 둘 이상이면 제안이 끼니별 argv 목록을 가진다
  (`config\telegram_llm_state.json`의 `meals`; 이 key가 없는 v2.1 파일도 읽는다). 끼니마다 `--additional`을 따로 정한다.
- **`/ok`**: 제안을 먼저 `used`로 표시한 뒤 끼니마다 `nutrition log`를 차례로 한 번씩 돌린다(손으로 같은 argv를 친 것과 같은
  행). 답은 한 메시지: 기록된 끼니마다 그 명령의 출력과 `취소: /void <id>`, 마지막에 `오늘 누적`.
- **중간에 실패하면** 첫 실패에서 멈춘다. 이미 기록된 끼니는 그대로 두고(각자 `/void`로 취소), 답에 `실패: 점심 - 오류: …`,
  `실행하지 않음: 저녁`, `남은 끼니는 다시 보내거나 /log로 기록하세요.`가 나온다. 제안은 이미 사용됨이라 `/ok`를 또 보내도
  `이미 처리한 제안입니다`이고 두 번 기록되지 않는다. 남은 끼니만 다시 제안하는 기능은 없다(후속 후보).
- 기록 줄(`/history`)은 하나이고 `result`가 `exit_code`(전부 성공이면 0, 아니면 실패한 명령의 코드), `meal_id`(처음 기록된
  끼니), `meal_ids`, `failed`(끼니 또는 null), `not_run`을 가진다.
- `/plain_`은 모든 끼니를 값 없이 기록한다(추정이 없는 끼니는 원래 argv 그대로). 어느 끼니에도 추정이 없으면 제안하지 않고
  `/plain_`도 거절한다.
- 마이그레이션이 적용되지 않았으면 전처럼 아무것도 쓰지 않고 제안도 사용하지 않는다.
- Ctrl+C: 명령 하나가 중단되면 bot이 멈추고 나머지 끼니는 돌지 않는다. 제안은 이미 사용됨이라 다시 시작해도 돌지 않는다.
  이미 기록된 끼니는 `/day`로 보인다.
- 날짜가 섞인 문장("어제 …, 오늘 …")은 `date_expression: other`라 `날짜를 정하지 못했습니다`다.

### 모든 항목에 추정 범위, 출처와 가정

- 모든 item은 `estimate`의 kcal과 protein 범위가 **필수**다(스키마와 검증 모두). 카탈로그 음식의 범위는 대체값이고, 연결되면
  카탈로그 값을 쓴다. 탄수화물·지방은 범위를 알 때만 적고 모르면 null이다(0으로 채우지 않는다). 점 값은 저장하지 않는다.
- 카탈로그에 없는 item은 `kind general`과 양을 담은 `memo`("김밥 2.5줄")를 갖는다. 저장은 전과 같은 `--general`,
  `--general-estimate=language_estimate:…`(사진은 `visual_estimate`)다. 새 source type은 없다.
- `assumption`(80자 이하, 숫자 없이)은 무엇을 가정했는지, `source`(30자 이하)는 웹 검색으로 찾았을 때 **사이트 이름만**이다.
  `://`나 `www.`가 있으면(주소·본문) `bad_output`이다. 제안에 `가정:` `출처:` 줄로 보이고, `--general-estimate-ref`에
  `…; 출처: <site>; 가정: <text>`로 붙는다. 근거 문자열은 100자(CLI 한도)로 자르는데 **출처·가정 쪽을 먼저** 자르고 10자도
  못 남으면 뺀다.
- `웹 검색 N회`는 LLM이 아니라 bot이 센 횟수(메시지의 해석 호출 전체)이고 0이면 나오지 않는다.

### 카탈로그 음식 ID 제안 (연결 규칙이 바뀐 곳)

v2에는 "정확한 ID·이름·alias로만 잇고 추측·제안 연결은 없다"고 적혀 있었다(`application/food_lookup.py`의 규칙은 그대로다).
v2.2는 LLM이 카탈로그 목록(`[카탈로그]`)에서 `food_id`를 **제안**하게 한다. 순서:

1. 사용자의 말(`food_text`)로 정확히 찾는다. 하나면 연결, 여러 음식에 맞으면 **LLM ID로 덮어쓰지 않고** 일반식
   (`이름이 여러 음식에 맞음`).
2. 아무것도 맞지 않을 때만 LLM의 `food_id`를 쓴다. 없는 ID, 예약 ID(`general-meal`, `일반식`)는 일반식
   (`고른 음식 ID가 카탈로그에 없음`). 있으면 연결하고 제안에 카탈로그 이름과 사용자의 말을 같이 보여 준다:
   `CJ 햇반 백미밥 210g (hetbahn-white-210) 1 count ← "즉석밥"`. 사용자가 `/ok`로 확인하는 것이 승인이다.
3. 연결됐지만 양이나 단위를 말하지 않았으면 일반식(`수량·단위를 말하지 않음`).
4. 연결됐지만 그 단위의 값이 등록돼 있지 않으면 일반식 추정 + `등록: …` 안내. **단위 환산은 하지 않는다.**

`nutrition log`는 언제나 정확한 ID를 받는다. 목록에는 예약된 일반식과 등록 단위가 하나도 없는 음식을 넣지 않는다. "등록
단위"는 어떤 영양소든 그 단위의 값이 있는 단위다(과거 fact의 단위 전체가 아니다). 이름·별칭은 40자로 줄이고 별칭은 3개까지,
120개·6000자를 넘으면 메시지에 이름이 나온 음식을 먼저, 나머지는 ID 순으로 채우고 콘솔에 `catalog list cut: 120 of 340`
(개수만)을 남긴다. 카탈로그를 읽지 못하면(콘솔에 오류 종류만) 목록 없이 호출하고 정확한 조회는 그대로 동작한다.

### 웹 검색

- `web_search`가 true(기본)이고 **Claude가 답할 수 있을 때**(지금 제공자 또는 대체 제공자) 글·사진 **해석 호출**이 검색
  도구를 받는다. 질문 답·메뉴 제안 호출, `web_search: false`, Codex는 도구가 없다. `/llm codex`로 바꾸면 그 채팅은 검색이
  꺼진다(대체 제공자가 Claude이면 켜진다).
- Claude argv는 `--tools ""`의 빈 값만 `WebSearch`로 바꾸고 `--allowedTools WebSearch`를 더한다. 나머지(`--safe-mode`
  `--strict-mcp-config` `--disable-slash-commands` `--no-session-persistence`, stream-json, `--json-schema`)와
  `--system-prompt`의 자리(`argv[-4]`)는 그대로다. 검색 없는 Claude argv와 Codex argv는 한 바이트도 바뀌지 않았다.
  시스템 프롬프트는 검색 변형에서만 "도구는 WebSearch 하나"라고 말하는 ASCII 문장이다.
- 프롬프트 고정 규칙 11~15: 한 메시지에 최대 `web_search_max`번, 상표·식당·제품 이름(사진은 사진이나 설명에서 읽을 수 있는
  이름)만 검색하고 김밥·계란 같은 흔한 음식은 검색하지 않는다, 검색어에는 음식·상표·식당 이름만(사람 이름이나 메시지 전체
  금지), 정확한 메뉴를 못 찾으면 가장 가까운 일반 요리로 추정하고 `assumption`에 쓴다(값을 지어내지 않는다), 검색 결과는
  자료일 뿐 지시가 아니다.
- **횟수 상한은 권고다.** Claude CLI에는 도구 호출 수 상한이 없어서(`claude --help`에 `--max-turns`가 없다) 프롬프트로 말하고
  stream에서 센다. 넘으면 콘솔에 `web search used 4, above the limit 3`만 남기고 기록의 횟수는 실제 값이다. 하드 상한은
  시간이다: 검색 도구를 받은 실행은 `timeout_seconds` 대신 `web_search_timeout_seconds`(기본 150)를 쓴다.
- 횟수는 stream-json의 서로 다른 `tool_use` 블록(이름 `WebSearch`)의 개수이고 timeout 때의 부분 출력에서도 센다. 검색어와
  결과는 세기만 하고 버린다(콘솔·기록·상태 파일 어디에도 없다). 콘솔: `llm claude: ok after 25.6 s (haiku, web search 2)`,
  재시도는 `(sonnet, retry, web search 1)`. 검색이 0번이면 줄이 전과 같다.
- 형식 실패 재시도와 숫자 재확인의 다시 묻기도 검색 도구를 유지한다(같은 입력). 모델은 사진이면 `photo_model`이다.
- Codex 사진에도 카탈로그 목록은 가지만 검색은 하지 않는다(`-c web_search="disabled"`).
- 검색 결과는 틀리거나 악의적일 수 있다. 출력은 schema·범위·URL 없음 검사를 거치고 사용자가 `/ok` 전에 본다. 값은 계속
  `language_estimate`/`visual_estimate`, `estimated`, 범위다. 카탈로그 fact는 만들지 않는다.

### 사진

- 사진 해석 호출도 카탈로그 목록과 검색 도구를 받는다(제품 라벨의 이름, 보이는 식당 이름, `햇반`·`닭가슴살` 같은 카탈로그 음식).
- 카탈로그에 연결된 item은 카탈로그 값(`--item`)을 쓰고 대개 `(수량 추정)`이다. 일반 item은 `visual_estimate`와 사진 근거
  문자열 `telegram-llm photo sha256:<12자> (claude sonnet)`(뒤에 출처·가정이 100자까지 붙는다)이다. 섞인 제안도 되고 머리줄은
  `사진 추정`을 유지한다.
- 연결·추정이 없고 가정·출처·검색·표시가 없는 사진 제안은 예전과 같은 바이트다. 메뉴 캡처 답과 해석 실패 답은 바뀌지 않는다
  (메뉴 캡처 호출은 검색할 수 있고 메뉴 item은 연결·재확인하지 않는다).

### 숫자 재확인 (`domain/telegram_llm_check.py`)

모델이 준 추정의 숫자가 서로 안 맞는지 bot이 `Decimal`로 정확히 검사한다(값을 고치지 않는다). 연결 뒤 **일반식 추정으로 저장될
항목**(글·사진 식사, 연결된 항목의 대체 범위는 제외)만 검사하고 메뉴 item은 검사하지 않는다.

| 코드 | 규칙(상수) |
|---|---|
| `range_too_wide` | kcal·단백질: 폭 `max-min`이 `max`의 0.7배를 넘고 바닥(kcal 150, 단백질 10 g)도 넘음. 650~950 통과, 100~900 실패, 0~0·0~5 g 통과 |
| `range_is_a_point` | kcal·단백질: `min == max`이고 `max > 0` |
| `macros_vs_kcal` | 단백질·탄수화물·지방 범위가 모두 있을 때 에너지 범위(4P+4C+9F의 최소~최대)가 kcal 범위(`Kmin×0.8-20` ~ `Kmax×1.2+20`)와 겹치지 않음 |
| `macros_exceed_kcal` | 탄수화물이나 지방이 없을 때, 있는 영양소의 최소 에너지 합이 넓힌 kcal 상한보다 큼(없는 영양소가 0이어도 불가능) |
| `assumption_number` | `assumption`의 숫자가 그 item의 수량·추정 범위 값에 없음(`source`는 숫자를 보지 않는다) |

- 실패하면 **딱 한 번** 다시 묻는다: 답한 제공자의 `retry_model`(없으면 답한 모델)로 한 번만 돈다(형식 재시도 없음, 대체
  제공자 없음, 검색 유지). 형식 재시도·대체 제공자는 내용 불일치가 아니라 형식 실패일 때만 쓴다.
- 프롬프트의 `[데이터]`와 `[메시지]` 사이에 `[재확인]` 구역이 더해진다. 고정 문장과, 실패마다 한 줄(최대 5줄)
  `- items[3]: macros_vs_kcal (kcal 650-950, 영양소 합 1200-1500)`이다. 음식 이름·메시지·기억은 넣지 않는다. 다시 묻기는
  이전 답을 보지 못하므로(상태 없음) 순서가 바뀔 수 있고, 그래서 모든 item을 다시 확인하라고 적는다.
- 결과: 새 답이 맞으면 `fixed`(새 답을 쓴다). 새 답도 안 맞으면 `still_inconsistent`(새 답을 표시와 함께 보여 줌).
  다시 묻기가 실패(timeout, 실패, `bad_output`)하거나 쓸 수 없는 답(식사 기록이 아니거나 날짜를 못 정함 등)이면
  `reask_failed`(첫 답을 표시와 함께 보여 줌). 두 번째 다시 묻기는 없다.
- 표시와 함께 보여 줄 때 사용자는 `/ok`에서 결정한다:

```text
점심
  1. 일반식 (메모: 소고기활전복 미역국)
     추정: kcal 650~950, 단백질 35~55 g, 탄수화물 20~30 g, 지방 5~10 g (estimated) (값 확인 필요)
     값 확인 필요: 열량과 영양소 합이 맞지 않음
     가정: 보돌미역 메뉴를 못 찾아 일반 소고기전복미역국 정식으로 추정
```

  가정은 그대로 보인다. `/ok`로 저장하는 근거 문자열에는 `; 값 확인 필요`가 출처·가정 앞에 붙는다. `/plain_`은 값을 저장하지
  않는다.
- 콘솔(ASCII, 코드와 횟수만): `llm interpret recheck: macros_vs_kcal x1; asking again (sonnet)`, `… recheck: fixed`,
  `… recheck: still inconsistent; shown with a marker`, `… recheck: re-ask failed (timeout); shown with a marker`.
- 기록: 맨 끝에 `web_searches`(그 메시지의 해석 호출 전체의 검색 횟수 합. 시도하지 않았으면 `null`, 시도했는데 안 썼으면
  `0`)와 `recheck`(`null` 또는 `{"reasons": [코드…], "outcome": "fixed"|"still_inconsistent"|"reask_failed"}`)가 붙는다.
  이제 줄은 16개(v2), 18개(v2.1), 20개(v2.2) key 중 하나이고 예전 줄은 다시 쓰지 않는다. 다시 묻기가 있었으면
  `provider`/`model`/`provider_result`/`retried`/`attempts`는 마지막 호출(다시 묻기)을 설명하고, `llm_output.interpret`는
  쓴 답, `llm_output.interpret_first`는 첫 답이다. `telegram history`는 값이 있을 때만 ` web=N`, ` recheck=<outcome>`을,
  `/history`는 ` · 웹 검색 N회`(N>0)와 ` · 재확인(고침|남음|실패)`을 붙인다. 기록 맨 끝의 `meal_ids`가 있으면 둘 다 그것을
  보여 준다(`meals=a,b` / `결과: 기록 a, b`, 일부만이면 `결과: 일부 기록 a (실패: 점심)`).

### 구현 단계 live 확인 (implementer, 2026-10-13~14, Claude Code 2.1.296, Codex CLI 0.160.0)

임시 폴더, stdin으로 합성 프롬프트, 같은 격리 argv로 실제 CLI를 몇 번만 돌렸다. 사용자 데이터는 쓰지 않았다.

| # | 확인 | 결과 |
|---|---|---|
| 1 | haiku + `--tools WebSearch --allowedTools WebSearch` + stream-json 입력 + `--json-schema`(새 interpret schema) | 통과(23 s). `system/init` tools는 `StructuredOutput`과 `WebSearch`, MCP 0. 최종 `result`에 `structured_output`이 있다. `--allowedTools`가 뒤 인자를 삼키지 않았다. |
| 2 | `tool_use` 블록 모양 | `assistant` 이벤트의 `message.content[]`에 `{"type":"tool_use","id":"toolu_…","name":"WebSearch","input":{"query":…,"mode":…},"caller":{"type":"direct"}}`. 같은 이벤트 줄에 `StructuredOutput` 호출이 따로 온다. 이름과 id로 센다. |
| 3 | 상한 장치 | `claude --help`에 호출 수 상한이 없다(`--max-budget-usd`만 있고 API 사용량용). 그래서 상한은 권고다. |
| 4 | 두 CLI가 바뀐 interpret schema를 받는지 | Claude(위 1)와 Codex(`--output-schema`, 기본 모델, 12 s) 모두 통과. Codex 결과는 새 key 4개와 끼니별 item을 맞게 채웠다. |
| 5 | haiku로 실제 새 프롬프트(웹 규칙 + 카탈로그 + 합성 3끼니 문장) | 27 s, 검색 1회. 끼니가 3개로 나뉘고 끼니 낱말 item 없음, 5개 item 모두 kcal·protein 범위, 닭가슴살·햇반은 카탈로그 ID로 연결, 숫자 검사 통과. `assumption`에 숫자가 들어오는 경우가 있어(수량과 같은 값이면 허용) 프롬프트만으로는 막지 못한다. |
| 6 | 검색 지연 | 검색 1회 haiku 27 s, 위 1의 1회 23 s. 기본 150 s에 여유가 있다. 검색 여러 번과 timeout 경로는 실제로는 확인하지 않았다(가짜 runner로만). |
| 7 | 고정된 다시 묻기: sonnet, `[재확인]` 구역 포함 | 통과(14.6 s, 검색 0회). 유효한 문서가 오고 첫 답과 다른 범위로 바뀌었다. |
| 8 | 사진: sonnet + 합성 PNG 이미지 블록 + 웹 도구 + schema | 통과(7.5 s). init tools `StructuredOutput`·`WebSearch`, `structured_output` 있음. 검색은 쓰지 않았다. |

CLI를 업그레이드하면 다시 확인한다. 검색 없는 대조 실행과 timeout·재시도 실제 실행은 하지 않았다.

### Output change(LLM이 켜졌을 때만)

- 문장 제안: 연결 방식이 `← "…"`로 보이는 항목, 일반식 대체 항목의 추정·이유·등록 안내(이전의 `빠짐:`은 없다), 여러 끼니
  제안과 `/ok` 답, `가정:` `출처:` `웹 검색 N회` `(값 확인 필요)` 줄, 사진 제안의 연결된 항목.
- 해석 프롬프트·스키마·요청(사용자에게 안 보임), 시작 콘솔 줄, 검색이 있는 콘솔 줄, 기록 줄의 새 key 두 개, 상태 파일의
  `meals`, `telegram history`/`/history` 꼬리.
- 바뀌지 않음: 모든 `muscle50` CLI 명령(`nutrition log`/`day`/`status`, `recommend`, `daily`, 예전 줄의 `telegram history`),
  `telegram_llm.json`이 없을 때의 bot, 손으로 친 `/log` 답, `/llm` 첫 줄, 질문·메뉴·수정 답장, 추정·연결·가정·검색·표시가
  없는 사진 제안, 검색·재확인이 없는 콘솔 줄, 검색 없는 Claude argv와 Codex argv.

## 이어지는 고치기·라벨·범위 누적 (v2.3)

Spec: `docs/specs/telegram-llm-corrections.md`(범위 1~5와 추가 문제 11, 12, 14, 17). migration 없음. CLI는 `nutrition meal replace-item`에
옵션 둘이 더해질 뿐이다(`docs/nutrition-general-meal.md`). 나머지는 모두 LLM이 켜졌을 때의 Telegram 답장과 흐름이다. 모든
쓰기는 지금처럼 제안 → `/ok` 뒤에만 한다.

### 라벨 값

영양정보 라벨(사진 속 표시, 또는 사용자가 문장으로 알려 준 라벨 값)에서 읽은 값은 한 값(min = max)이다.

- 항목에 `from_label`(boolean, 필수)이 있다. **효과가 있으려면** `from_label`이 true이고 준 범위가 모두 한 값이어야 한다.
  한 값과 범위가 섞여 있으면 보통 추정으로 취급하고 모든 검사를 한다. 라벨에 없는 영양소는 null이다.
- 라벨 항목은 `range_is_a_point`(숫자 재확인)만 건너뛴다. 범위 폭, 열량과 탄단지 합, 가정 숫자 검사는 그대로다. 라벨 표시가
  없는 한 값은 지금처럼 한 번 다시 묻는다.
- 저장은 기존 추정 fact다(`visual_estimate`: 사진, `language_estimate`: 글. min = max, `estimated`). 구분은 근거 문자열의
  `; 라벨`이 한다. 근거 문자열 순서는 `기본; 라벨; 값 확인 필요; 양; 출처; 가정`이고 100자를 넘으면 뒤(양·출처·가정)부터 자른다.
  라벨도 양 가정도 없으면 v2.2와 같은 바이트다.
- 제안에는 `추정: … (estimated)` 대신 `라벨: kcal 185, 단백질 5 g, 탄수화물 37 g`이 보인다. 다른 검사에 걸리면 `(값 확인 필요)`가
  붙는다. 이 값은 `nutrition day`에서 `estimated kcal 185-185`로 보인다.

### 방금 기록한 거와 열린 제안 고치기

글 메시지의 해석 호출에는 (있을 때) `[데이터]`에 블록이 더해진다(카탈로그 다음, 이 순서). 비면 그 블록은 없다.

| 블록 | 내용 |
|---|---|
| `<직전 기록>` | 이 chat이 **마지막으로 기록한 식사 둘**(아래)의 meal ID, 끼니, item 번호·이름 또는 메모·추정값 |
| `<열린 제안>` | 이 chat의 가장 새 열린(유효 시간 안, `/ok` 전) 식사 제안의 토큰과, 사용자가 본 item 줄 |
| `<최근 메뉴>` | 4시간 안에 만든 가장 새 메뉴 제안(열림 또는 사용됨, 취소 제외)의 선택지와 그 번호 |

- **"방금 거"** = 이 chat의 성공한 기록(confirm, plain, edit 기록 줄) 중 **가장 새 meal 둘**(같은 meal은 한 번), void된 것은
  빼고 활성인 것만. 시간 기준은 없다(3일 뒤에도, bot을 다시 켠 뒤에도). 기록 줄은 `telegram\history`에서 최근 200줄 안에서
  찾는다(매번 모든 월 파일을 읽어 마지막 200줄을 고른다. 읽을 수 없는 줄이 하나라도 있으면 "방금 거"는 없는 것으로 보고 콘솔에
  `recent meals not read`만 남는다). 손으로 친 `/log`는 이 기록에 들어가지 않는다.
- LLM은 말만 뽑는다(`refers_to`, 메모·음식 낱말, 끼니, 순서). 대상은 bot이 정한다.
  - `refers_to: last_recorded` + `meal_edit`: 위 둘 중에서 찾는다. 둘 중 **하나만** 낱말에 맞으면 그 식사, 둘 다 맞거나
    아무것도 안 맞으면 후보만 보여 주고 쓰지 않는다. 낱말이 없는 식사 전체 작업(취소, 끼니 바꾸기)은 둘 다에 맞으므로 후보를
    보여 준다. "가장 새 것"으로 넘어가지 않는다. 기록이 없으면 `방금 기록한 식사를 찾지 못했습니다…`.
  - 그 밖(`refers_to` 없음), 또는 `target_meal_ordinal`이 있을 때(`refers_to`가 `last_recorded`여도): 그날의 활성 식사
    (`meal_type`, `date_expression`). 순서는 늘 그날의 식사를 뜻한다. "아침 1식" = 그날 활성 아침의 N번째다. 순서는 ID 끝 번호(기록 순서)이고 문자 순서가 아니다(`-10`은 `-2` 뒤). 첫 아침을
    void했으면 1식은 둘째 아침이다. 끼니 없는 순서와 끝을 넘은 순서는 후보/`고칠 식사를 찾지 못했습니다`.
  - item: 낱말의 정확한 카탈로그 조회로 찾은 음식 ID의 item **과** 일반식 item(메모를 정규화해 같음. 같은 것이 없으면 메모에
    낱말이 들어 있음, 낱말은 정규화 뒤 2자 이상)의 합집합. 정확히 하나면 대상이다. 여럿이거나 없으면 같은 식사 안은
    `meal_id item N: …` 후보 줄, 여러 식사에 걸치면 기존 `/show <id>` 후보를 보여 주고 아무것도 쓰지 않는다. 메모 정규화는
    NFKC, 소문자, 공백과 문장부호 제거다.
- 일반식의 추정값과 메모는 `change_estimate`로 고친다(`edit.estimate`는 **바뀌는 영양소만**, 나머지는 저장된 범위 그대로,
  원래 모르던 영양소는 계속 모름). 새 값으로 일반식을 `replace-item … --general-estimate`로 갈아 끼우므로 옛 item과 옛 fact는
  지워지지 않고 그대로 남는다. 합친 추정은 같은 숫자 검사를 하고, 걸려도 **다시 묻지 않고** 제안에 `(값 확인 필요)`와 이유만
  붙인다(근거 문자열에 `; 값 확인 필요`). 메모만 고치면 저장된 추정과 근거 문자열을 그대로 다시 보낸다. 카탈로그 item의 값은
  고치지 않는다(`food fact add`를 안내).
- **열린 제안을 고치는 말**(`refers_to: open_proposal`, `meal_log`): 고친 **전체** 식사를 일반 경로(연결, 검사, 겹침)로 새
  제안으로 만들고, 이전 제안은 **같은 상태 저장에서** 취소한다(`이전 제안(/ok_7a4a)은 취소했습니다.`). 열린 제안이 없으면
  `고칠 열린 제안이 없습니다…`를 답하고 새 식사를 만들지 않는다. 사진 제안을 글로 고치면 글 제안이 되어 출처가
  `language_estimate`가 된다.
- 수정 제안은 그 식사의 날짜를 기억해, `/ok` 뒤 `오늘 누적`이 그날 것이다.

### 같은 끼니에 같은 음식 (겹침)과 `/fix_`

같은 날 같은 끼니가 이미 있을 때 bot이 결정적으로 겹침을 판단한다: 같은 카탈로그 food ID, 또는 정규화한 같은 일반식 메모.
`general-meal` ID는 겹침으로 세지 않고, 메모가 비면 겹치지 않는다.

```text
오늘 아침(2026-10-14-breakfast-1)에 이미 같은 음식이 있습니다: 깻잎닭갈비 삼각김밥 1개
이렇게 기록할까요? (아침, 10-14)
1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)
   추정: kcal 180~200, 단백질 5~6 g (estimated)
기존 아침 고치기: /fix_3b1e   하나 더 기록: /ok_3b1e   일반식만 기록(값 없이): /plain_3b1e   취소: /no_3b1e
```

- 겹치지 않으면 v2처럼 `--additional`이고 같은 문장을 **맨 위**에 둔다. 여러 끼니 제안은 끼니마다 맨 위 줄이고 블록 안의 줄은 없다.
- `/fix_`는 **명령 하나**로 기록된 식사를 제안과 같게 만들 수 있을 때만 나온다: 값이 다른 겹침 item 하나의 `replace-item`,
  또는 새 item 전부를 한꺼번에 `add-item`. 값이 같은 겹침 item은 할 일이 없고, 값 없는 제안은 기록된 값을 덮지 않는다. 할 일이 없으면
  `이미 같은 내용이 기록되어 있습니다…`, 둘 이상이면 `고칠 곳이 여러 개라 바로 고치기는 없습니다…`를 보여 주고 `/ok`(하나 더)와 `/no`만
  준다. 여러 식사를 한 번에 겹치거나(둘 이상의 기록된 식사) 여러 끼니 제안에는 `/fix_`가 없다.
- `/fix_<토큰>`은 아무것도 쓰지 않는다. 새 수정 제안(`고치기: /ok_… 취소: /no_…`)을 만들고(일반식이면 바뀌는 값을
  `kcal 185, 단백질 5 g → kcal 180~200, 단백질 5~6 g` 줄로 보여 주고 `(라벨)`, `(값 확인 필요)`와 그 이유도 붙인다) 겹침 제안을 같은 저장에서 취소한다(그 제안의
  `/ok_`·`/fix_`는 `취소한 제안입니다.`). 만료·사용·취소된 제안과 메뉴 제안은 고정 문구로 거절한다. 기록 종류 `fix`로 남는다.

### 오늘 누적을 하나의 범위로, 기록한 날, 반올림

```text
오늘 누적 (추정 포함):
  kcal 350
  단백질 39 g
  탄수화물 37 g (값 모르는 항목 1개 빠짐)
  지방 알 수 없음 (값 모르는 항목 2개 빠짐)
```

- 영양소마다 한 줄: 하한 = 확인 값 합 + 추정 하한 합, 상한 = 확인 값 합 + 추정 상한 합. 같으면 한 숫자, 아니면 `600~620`.
  값 모르는 항목은 더하지 않고 `(값 모르는 항목 N개 빠짐)`으로 센다. 값도 추정도 없으면 `알 수 없음`(0이 아님). 추정이 있는 영양소가 하나라도 있으면 머리에
  `(추정 포함)`. 기록이 없으면 `오늘 누적: 오늘 기록 없음 (0이 아님)`.
- 같은 줄을 `/ok` 답장, 질문·메뉴 제안 호출의 `오늘 누적` 데이터, 메뉴 머리에 쓴다. 숫자 검사는 그 문자열의 숫자를 허용하므로
  답이 `600`과 `620`을 쓰면 통과하고 지어낸 합은 걸린다. 범위를 근거로 한 판단(부족·초과 안내)은 하지 않는다. status·추천은 그대로다.
- **기록한 날**: 다른 날(예: 어제)을 기록하면 `/ok` 답장 끝이 그날의 누적이다: `10-14 누적 (추정 포함):`, 기록이 없으면 `10-14 기록 없음 (0이 아님)`.
  같은 날은 `오늘 누적` 그대로다. 수정 제안은 그 식사의 날짜, 여러 끼니 제안은 제안의 날짜를 쓴다. 질문과 메뉴는 늘 오늘이다.
- **반올림**: Telegram 답장의 합계·남은 양(단백질, 메뉴 머리의 남은 kcal)은 CLI와 같은 규칙(0.1, 반올림은 짝수 쪽, 끝 0 제거)으로 보인다:
  1.95 g은 `2 g`, 34.95 g은 `35 g`. 남은 양이 0보다 큰데 반올림하면 0이 되면 CLI의 status처럼 `<0.1`이다(`0 g`이 아님).
  인자(argv)와 수량은 정확한 값 그대로다.

### 양 가정(portions)과 메모에 음식 이름

- 사용자가 양을 말하지 않은 일반식은 항목의 `portions`(재료 최대 4개 `{name(20자), g_min, g_max}`, 0~3000 g)로 가정한 무게를 준다. 양을
  말했거나 카탈로그 음식이면 빈 배열이다. 제안에는 `양 가정: 닭 150~200 g, 감자 100~150 g`, 근거 문자열에는
  `양: 닭 150-200g, 감자 100-150g`(100자 한도로 뒤부터 잘림)이 남는다. 가정 숫자는 `assumption_number` 검사에 허용된다.
- 일반식 메모는 항상 사용자가 쓴 **음식 이름의 첫 낱말**로 시작한다(그 낱말이 2자 이상이고 메모에 없으면 앞에 붙인다. 정규화한 단순 포함 검사이고
  의미 검사가 아니다). `안동찜닭 닭 및 감자 위주` → 메모 `안동찜닭 닭 및 감자 위주`.

### 최근 메뉴 이름으로 고르기 (`menu_ref`)

"점심으로 위 사진에 있는 얼큰순살감자탕 먹었어"처럼 4시간 안에 본 메뉴의 항목을 이름으로 말하면 항목의 `menu_ref`(그 메뉴의 번호, 아니면
null)에 담긴다. bot이 확인한다: 번호가 범위 안이고, 사용자의 낱말과 메뉴 항목 이름이 서로 포함해야 한다(정규화 뒤 2자 이상). 맞으면 그
항목의 메모·값(메뉴판 표기 포함)·출처 종류로 제안하고(`추정: kcal 1022 … (estimated) (메뉴판 표기)`), 근거 문자열은
`<메뉴 근거>; 메뉴판 표기`(없으면 `; 메뉴 항목`)이다. 사용자가 이미 본 목록의 값이라 숫자 재확인은 건너뛴다. 맞지 않으면 쓰지 않고(콘솔에 개수만)
평소처럼 추정한다. (v2.3에서는 메뉴 제안의 확인 유효 시간이 60분이고 4시간은 이름으로 고르는 창일 뿐이었다. v2.4부터 메뉴 제안의 유효 시간도 4시간이다: 아래 "메뉴 제안은 4시간".)

### 전송되는 데이터 (v2.3)

글 해석 호출에는 위 블록이 더해진다: **최근 기록한 식사 둘의 이름·메모·추정값, 열린 제안의 항목 줄, 최근 메뉴의 항목 이름과 값**이 고른 제공자로 간다.
사진 해석 호출에는 가지 않는다(카탈로그만).

### live 확인 (implementer, 2026-10-16, Claude Code / Codex CLI, 합성 데이터)

임시 호출 8번(Haiku 6, Codex 2), 사용자 데이터 없음, 실제 해석 프롬프트(`build_prompt`)와 같은 격리 argv.

| # | 확인 | 결과 |
|---|---|---|
| 1 | 바뀐 interpret schema(항목 14 key, `portions` 배열, `edit.estimate`, `integer|null`)를 두 CLI가 받는가 | Claude(`--json-schema`, `$schema` key 없음)와 Codex(`--output-schema`)가 모두 받았다 |
| 2 | "삼각김밥 지방 2g 이네 사진에 나와있어" + `<직전 기록>` | Haiku와 Codex 모두 `meal_edit` + `last_recorded` + `change_estimate`(지방 2~2, `from_label` true, 대상은 그 메모) |
| 3 | "아침 1식 닭가슴살 2팩으로 바꿔줘" | Haiku: `meal_type breakfast`, `target_meal_ordinal 1`, `change_quantity` |
| 4 | `<열린 제안>` + "아니 닭가슴살 2팩 아니고 1팩" | Haiku: `meal_log` + `open_proposal`, 고친 item 1개 |
| 5 | 라벨 문장(열량 185, 단백질 5, 탄수화물 37, 지방 2) | Haiku: `from_label` true, 모두 min = max |
| 6 | "안동찜닭 닭 및 감자 위주" | Haiku와 Codex: `portions` 채움, 메모가 `안동찜닭`으로 시작 |
| 7 | `<최근 메뉴>` + "…얼큰순살감자탕 먹었어" | Haiku: `menu_ref` 1 |

각 종류 1~2번뿐이라 분류 누락률은 알 수 없다. 사진(라벨 이미지)과 Codex의 나머지 경우는 하지 않았다. CLI를 올리면 다시 확인한다.

### Output change(LLM이 켜졌을 때만, `breaking`)

- 바뀜: `오늘 누적` 줄의 모양(`/ok` 답장, 질문·메뉴 데이터, 메뉴 머리의 반올림), 다른 날 기록의 `MM-DD 누적`, 같은 끼니 안내의 위치(맨 위)와 겹침 시
  `/fix_` 줄, `라벨:`·`양 가정:`·`(메뉴판 표기)` 줄, 이전 제안 취소 줄, 일반식 item 후보 목록과 새 거절 문구, 남은 양이 0.1 미만이면
  CLI처럼 `<0.1`(0이 아님), 아무 제안에도 맞지 않는 손으로 친 `/fix_xxxx`(전에는 v1 답, 이제 `이 확인 명령을 찾지 못했습니다.`),
  해석 프롬프트·스키마·요청, 상태
  파일의 `outline`·`fix_argv`·`fix_change`, 기록 종류 `fix`와 `/history`의 `고치기 선택`.
- CLI는 `nutrition meal replace-item`의 `--general-estimate`/`--general-estimate-ref`(와 그 `--help`·오류 사용법 줄)만 더해졌다.
- 바뀌지 않음: 그 밖의 모든 CLI 출력, `telegram_llm.json`이 없을 때의 bot, 손으로 친 `/log`·`/void`·`/day`·`/status` 답, `/help`, `/llm`,
  기존 `/ok`·`/plain`·`/no` 답장 본문, 라벨·양 가정·메뉴 참조·겹침이 없는 제안의 항목 줄.

## 신뢰성·앨범·짧은 답장 (v2.4)

Telegram LLM Reliability and Replies v2.4, `docs/specs/telegram-llm-reliability.md`. Migration 없음. Output change: breaking(Telegram
LLM 답장과 콘솔 오류 문구, 새 실행 기록 파일만 바뀐다. CLI 출력은 그대로다). 2026-10-13~15 실사용에서 나온 문제 가운데 v2.3에서 떼어 낸 나머지다.

### 사진 여러 장(앨범)

- LLM이 켜져 있을 때만 모은다. 첫 사진의 `media_group_id`가 같은 사진을 같은 `getUpdates` 묶음에서 먼저 가져오고, 모자라면 2초짜리
  `getUpdates`를 이어서 한다. 새 멤버가 없는 poll, 6초(주입한 시계), 사진 4장 중 먼저 오는 것에서 멈춘다.
- 한 메시지가 된다: 캡션은 처음으로 글이 있는 사진의 것, 사진은 앞의 4장(update 순서). 프롬프트는 `(사진 2장 첨부)`(한 장이면 전과 같은 `(사진 첨부)`),
  Claude는 이미지 블록 하나씩, Codex는 `-i photo.jpg photo-2.png ...`(한 장이면 전과 같은 `-i photo.jpg`). 숫자 재확인도 같은 사진을 다시 보낸다.
- 읽지 못했거나 넘친 사진이 있으면 답장 본문(`<pre>` 안, 명령 줄 앞)과 기록에 `사진 5장 중 4장만 읽었습니다`가 붙는다. 큰 사진·파일 이미지·받지
  못한 사진도 앞의 숫자(보낸 장수)에는 들어가고 읽은 장수에는 들어가지 않는다. 하나도 못 읽으면 전과 같은 고정 문구(`사진이 너무 큽니다` 등)다.
- 허용 목록, 오래된 메시지, 이미 처리한 update ID 규칙은 멤버마다 그대로다. 앨범의 모든 update ID는 처리 전에 기억한다. 첫 멤버의 ID가 합친 메시지의 ID다.
- 같은 묶음에서 앨범과 함께 가져온 다른 메시지는 순서대로 앨범 뒤에 처리한다(앨범은 첫 멤버 자리에서 처리).
- LLM이 꺼져 있으면 옛 loop 그대로다(`getUpdates` 호출 수와 offset 포함).

### 사진을 읽지 못했을 때

- 캡션에 먹었다는 말(`먹었`, `먹음`, `먹은`, `드셨`, 단어로서의 영어 `ate`)이 있고 메뉴 말(`메뉴`, `menu`)이 없을 때만 값 없는 일반식 제안(`사진을
  해석하지 못했습니다. 일반식으로만 기록할까요?`)을 한다. 영어 `ate`는 단어일 때만 맞는다(`plate`, `chocolate`은 아님). NFKC·소문자로 맞춘 뒤 본다.
- 그 밖에는 `사진을 해석하지 못했습니다. 사진에 "메뉴" 또는 "먹음"이라고 적어 다시 보내 주세요.`만 보내고 제안·상태 파일·DB에 아무것도 쓰지 않는다.

### 사진도 대화 기억에

- 사진 뒤 기억에 `[사진 2장] 점심 → 메뉴 캡처로 읽음: 항목 5개`, `[사진 1장] → 식사 사진으로 읽음: 제육볶음 정식, 햇반 외 1개`, `[사진 1장] → 해석 못함`,
  `[사진 1장] → 사진 종류 불명` 같은 한 줄이 남는다(캡션 60자·결과 160자까지). 해석 결과에서 만들고 LLM을 더 부르지 않는다. `/memory`와 다음
  호출의 `[기억]`에 그대로 보인다. 해석·답 프롬프트에는 "`[사진 N장]`으로 시작하는 줄이 있으면 사진을 받은 것이니 사진이 없다고 답하지 않는다"는 규칙이 있다.
- 글 대화의 기억 줄은 그대로다. 너무 큰 사진·받지 못한 사진처럼 LLM을 부르지 않은 경우는 기억 줄이 없다.

### bot이 멈추지 않게

- Telegram 어댑터는 예상 못 한 예외도 `TelegramUnavailableError`(`unexpected error (<Type>)`, ASCII, token 없음, 연결된 예외 없음)로 바꾼다.
- 메시지 하나를 처리하다 예상 못 한 예외가 나면 콘솔과 실행 기록에 남기고 사용자에게 오류 문구를 보낸 뒤 다음 메시지로 넘어간다. 그 update는 이미 기억돼 있어
  다시 실행되지 않는다. 연속 5번이면(`getUpdates` 쪽도 같다) `오류: 예상하지 못한 오류가 연속 5번 …`으로 멈춘다(exit 1). 상태 파일 오류와 token 거절은
  전처럼 바로 멈춘다.
- 상태 파일(`telegram_state.json`, `telegram_llm_state.json`)을 저장할 때 Windows가 `os.replace`를 잠깐 막으면(`PermissionError`) 0.05, 0.1, 0.2, 0.4,
  0.8초 간격으로 다시 시도한다. 그래도 안 되면 전처럼 `TelegramStateError`로 멈춘다(문구는 `(EACCES)`처럼 오류 이름).
- 콘솔(stderr)에 쓰지 못해도(창을 닫음, 파이프 끊김) bot은 멈추지 않는다.

### 실행 기록 파일 `telegram\run-YYYY-MM.log`

- LLM이 꺼져 있어도 만든다. 콘솔에 찍은 줄(이미 token을 가린 ASCII)을 그대로 따라 쓰고, 파일에만 남는 줄이 있다: `run started pid=<n> llm=<on|off>`,
  30분마다 `alive`(루프가 돌 때 확인하므로 긴 LLM 호출 중에는 비어 있을 수 있음), `run stopped: ctrl_c`, `run stopped: error <TypeName>`,
  Windows 콘솔 이벤트(창 닫기·로그오프·종료)가 오면 `run stopped: console_event <n>`.
- 한 줄마다 열고 덧붙이고 닫는다(append만). 달은 쓸 때마다 주입한 시계로 정해 달이 바뀌면 다음 파일로 간다. 쓰기 실패는 무시한다. 메시지 원문과 token은
  넣지 않는다. muscle50은 이 파일을 지우거나 돌리지 않는다.
- 콘솔 이벤트 hook은 Windows에서만, 최선 노력이다(`SetConsoleCtrlHandler`). 항상 False를 돌려주므로 프로세스는 전과 똑같이 끝나고 Ctrl+C는 그대로
  KeyboardInterrupt다. 콘솔에는 파일 전용 줄이 나오지 않는다.

### 메뉴 제안은 4시간

- 메뉴 캡처·메뉴 제안(`/eat_<token>_<n>`)은 4시간 유효하다. 식사 기록·수정 제안은 60분 그대로다. 이름으로 고르는 창(`MENU_WINDOW_S`)과 같은 상수다.
- 만료 문구는 저장된 유효 시간을 따른다: `이 메뉴 제안은 유효 시간(4시간)이 지났습니다. 메뉴 사진을 다시 보내거나 다시 물어봐 주세요.`(v2.3 상태 파일의
  메뉴는 `(60분)`). 식사·수정 제안은 전과 같은 `이 제안은 유효 시간(60분)이 지났습니다. …`다. 상태 파일 모양은 바뀌지 않아 v2.3 파일이 그대로 읽힌다.
- 한계: 정확히 4시간이 되는 그 1초에는 메뉴가 이름으로는 아직 고를 수 있고(`<=`) `/eat_`는 이미 만료다(`now >= expires`). 테스트가 양쪽을 고정한다.

### 짧은 한국어 `/ok` 답장

`/ok`, `/plain`, 여러 끼니, 수정(`/fix_` 포함), void가 **성공**하면 CLI의 영어 출력 대신 저장된 식사를 다시 읽어(`nutrition meal show --json`) 만든 요약을 보낸다.

```text
기록했습니다: 아침 2026-10-14-breakfast-1 (10-14)
1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개) - 라벨 kcal 185, 단백질 5 g, 탄수화물 37 g
2. 닭가슴살 (chicken-breast) 1 pack - kcal 165, 단백질 34 g, 탄수화물 0 g, 지방 2 g
이 끼니 (추정 포함): kcal 350, 단백질 39 g, 탄수화물 37 g, 지방 2 g (값 모르는 항목 1개 빠짐)
취소: /void 2026-10-14-breakfast-1   전체 보기: /show 2026-10-14-breakfast-1
오늘 누적 (추정 포함):
  kcal 350
  …
```

- 첫 줄은 `기록했습니다`, 수정은 `수정했습니다`(끝 줄이 `확인: /show <id>`), void는 `취소(void)했습니다: <id>` + `확인: /show <id>`(식사를 읽지 않는다).
- item 번호는 `/show`·`nutrition day`와 같다. 값은 저장된 값이고 CLI처럼 0.1 단위 half-even으로 반올림해 보인다(34.95는 35). 라벨에서 읽은 값은 `라벨`,
  범위로만 저장된 값은 `추정`, 정확한 값은 접두 없음, 값이 하나도 없으면 `값 없음`(0이 아님). 모르는 영양소는 줄에서 빠진다.
- `이 끼니` 줄은 오늘 누적과 같은 규칙이다: 확인된 값 + 추정 범위, 값이 없는 item은 영양소마다 `(값 모르는 항목 N개 빠짐)`으로 센다. 아무 값도 없으면
  `이 끼니: 값 없음 (0이 아님)`. 여러 영양소가 모르면 줄이 길어진다.
- 여러 끼니는 끼니마다 한 블록이고 `실패:`·`실행하지 않음:` 줄은 그대로다. 실패 답장(`오류:`)과 손으로 친 `/log`의 답은 그대로다.
- 식사를 다시 읽지 못하거나 모양이 예상과 다르면 CLI 출력을 그대로 보낸다(콘솔에 `meal summary not built (<Type>)`). 기록(history)에는 실제로 보낸 답장이 남는다.

### 동기화 안내

- "동기화 해줘"는 새 의도 `sync_request`이고 고정 답장 `동기화는 /daily 로 합니다. 운동 하나만 다시 받으려면 /refresh 를 쓰세요.` + 누를 수 있는 `/daily`,
  `/refresh` 줄이다. 아무것도 실행하거나 저장하지 않는다(기록·기억 줄은 다른 교환처럼 남고 `/history`에는 `동기화 안내`). 확인 뒤 `/daily`를 돌려 주는 것은 후속 후보다.
- 질문 답 프롬프트에는 "운동을 묻는데 데이터에 그 날의 운동이 없거나 동기화가 안 된 것으로 보이면 숫자 없이 한 문장으로 `/daily`를 안내한다"는 규칙이 있다(프롬프트만).
  v2.5에서 이 규칙은 `<동기화 상태>`를 쓰는 규칙으로 바뀌었다(아래).

### 콘솔 오류 문구

- 네트워크 오류는 오류 번호와 짧은 영어 설명이다: `telegram: network error (WinError 10054 connection reset by remote host); retrying in 5 s`. 표에 있는
  번호는 10013, 10051, 10053, 10054, 10060, 10061, 10065, 11001이고, 그 밖에는 `WinError <n>`, 오류 이름(`ECONNRESET`), 형 이름 순이다. Windows의 한국어 메시지는
  쓰지 않는다. 번호는 `winerror`, 없으면 `errno`로 찾아 OS와 상관없이 같은 문구다.

### live 확인 (implementer, 2026-10-19, Claude Code / Codex CLI, 합성 데이터)

임시 호출 7번(Claude Haiku 5, Codex 2), 사용자 데이터 없음, 실제 `build_prompt`와 같은 격리 argv, 임시 폴더.

| 확인 | 결과 |
|---|---|
| 두 CLI가 `sync_request`가 든 interpret schema를 받는다 | 받음(Claude, Codex 모두 `ok`) |
| Haiku: "동기화 해줘" / "어제 운동 확인해봐" | `sync_request` / `question` |
| Claude: 합성 PNG 2장(빨강, 파랑)을 이미지 블록 2개로 | `ok`. 요약에 "1번 사진은 단색 빨강, 2번 사진은 단색 파랑"(둘 다 보고 순서도 맞음) |
| Codex: 같은 2장을 `-i photo.jpg photo-2.png`로(열려 있던 확인) | `ok`. 요약에 "순서대로 빨간색, 파란색"(둘 다 읽음) |
| 기억에 `[사진 2장] 점심 → 메뉴 캡처로 읽음: 항목 5개`가 있을 때 "두개는 해석 못해?" | "사진은 못 읽는 게 아니에요. 보내주신 두 사진은 점심 메뉴 캡처로 읽어서 …"(사진이 없다고 하지 않음) |

실제 Telegram 앨범 두 장, Windows 창 닫기 때의 `console_event` 줄, 30분 뒤 `alive` 줄은 자동으로 확인할 수 없어 사용자가 한 번 확인한다.

### Output change(LLM이 켜졌을 때 + 콘솔과 새 파일, `breaking`)

- 바뀜: `/ok`·`/plain`·여러 끼니·수정·`/fix_`·void 성공 답장(짧은 한국어 요약), 읽지 못한 사진의 답장, 앨범의 `사진 N장 중 M장만 읽었습니다` 줄, 메뉴 제안의
  만료 문구와 유효 시간, 동기화 안내, 해석 프롬프트·스키마(`sync_request`)·요청(`extra_photos`), 기억 파일의 사진 줄, 콘솔의 네트워크·상태 파일 오류 문구
  (LLM이 꺼져 있어도), 새 파일 `telegram\run-YYYY-MM.log`(LLM이 꺼져 있어도), 예상 못 한 오류 뒤에도 bot이 계속 도는 것.
- 바뀌지 않음: 모든 CLI 출력, 손으로 친 `/log`·`/void`·`/day`·`/status`·`/show`·`/help`·`/llm` 답, 실패 답장, 한 장짜리 사진의 프롬프트와 argv, 식사·수정 제안과 그 만료 문구,
  `telegram_llm.json`이 없을 때 bot의 답장·DB·상태 파일·`getUpdates` 호출(새 실행 기록 파일과 콘솔 오류 문구만 더해졌다).

## 실패 이유·다시 보내기·기존 끼니에 더하기 (v2.5)

Telegram LLM Failure Replies and Meal Merging v2.5, `docs/specs/telegram-llm-failures-and-meals.md`. Migration 없음. Output change: breaking
(LLM이 켜졌을 때만). 근거는 v2.4 뒤 2026-10-16~20 실사용이다(실패 이유를 알 수 없던 23:27 실패 3개, "하나에 같이"를 무시한 `breakfast-2`, 두 번
말해야 반영된 고치기, 명령 목록을 모르는 코치, 동기화 안 된 날을 "기록 없음"이라고 한 답).

### 기본 제공자 Codex (사용자 결정 2026-10-21)

- `DEFAULT_SETTINGS.provider`가 `codex`이고 Codex 모델 기본값은 글·사진 `gpt-6.1-sol`, 재시도 모델 없음이다(위 "모델 선택과 재시도"). `{}` 설정이면 모든
  호출(글, 사진, 질문 답, 메뉴 제안, 고치기)이 Codex로 간다. Claude는 다른 제공자로 남는다: 사용 한도 때 넘어가는 곳(기본 켜짐)이고 `/llm claude`로 바꿀 수
  있다. Claude 모델 기본값(haiku/sonnet/sonnet)은 그대로다.
- `"provider": "claude"`를 적은 설정은 v2.4와 똑같이 동작한다(이번에 바뀐 답장·프롬프트 규칙은 제외). 기존 테스트는 이 명시 설정으로 고정한다.
- 추정 근거 문자열은 실제로 답한 모델을 쓰므로 `telegram-llm text (codex gpt-6.1-sol)`처럼 된다.

### 실패 이유와 답장

LLM 호출이 실패하면 이유를 고정 목록에서 정한다(`infrastructure/llm/failure_reason.py`, 순수 함수). 입력은 종료 코드·시간 초과, Claude의 마지막 `result`
이벤트(오류일 때의 문구와 `api_error_status`; 종료 코드가 0이 아니어도 이제 읽는다, 결과 종류는 그대로), Claude의 `system/api_retry` 이벤트, stderr의
마지막 4096자(실패한 Codex는 stdout도)다. Codex는 stderr에 프롬프트를 다시 찍으므로 보낸 프롬프트를 지우고 `error`가 든 줄만 본다. 문구는 소문자로
맞춰 표와 비교하고 **이유 값만 함수 밖으로 나온다**. CLI 문구는 콘솔·기록·상태 파일·답장 어디에도 남지 않는다(테스트가 표식 문자열로 확인한다).

| 이유 | 표(일부) | 답장 본문 |
|---|---|---|
| `network` | `connection error`, `getaddrinfo`, `error sending request`, `workspace routing discovery failed`, `os error 10054` 같은 번호, HTTP 상태 없는 `api_retry`로 끝난 시간 초과 | `인터넷 연결이 끊긴 것 같아 해석하지 못했습니다. 연결되면 아래 명령으로 다시 보내세요.` |
| `usage_limit` | `usage limit`, `hit your limit`, `limit reached`, `rate limit`, `quota`, 상태 429 | `Codex 사용 한도에 걸려 해석하지 못했습니다. 잠시 뒤 다시 보내거나 /llm claude 로 바꾸세요.`(다른 제공자도 이미 해 봤으면 `… 한도가 풀린 뒤 다시 보내세요.`) |
| `login` | `not logged in`, `/login`, `401 unauthorized`, `missing bearer`, 상태 401/403 | Claude: `… PC 터미널에서 claude 를 실행해 /login 한 뒤 다시 보내세요.` Codex: `… PC 터미널에서 codex login 을 실행한 뒤 다시 보내세요.` |
| `timeout` | 시간 초과 | `Codex가 시간 안에 답하지 않아 해석하지 못했습니다. 다시 보내거나 /log 로 보내세요.` |
| `not_found` | 실행 파일 없음·`.exe` 아님 | `Codex 실행 파일을 찾지 못해 해석하지 못했습니다. PC에서 설치와 telegram_llm.json의 executable을 확인하고 bot을 다시 시작하세요.` |
| `other` | 그 밖(모르는 문구, 형식 실패) | v2.4 문구 그대로(`지금 해석하지 못했습니다. …`, 사진은 캡션 규칙) |

- 우선순위: 시간 초과 → 사용 한도 → 로그인 → 네트워크 → 기타. 그래서 Codex가 `error sending request … retrying` 뒤에 사용 한도로 끝나면 사용 한도다.
- 답장의 이유와 제공자는 **마지막 시도**의 것이다. 짧은 평문 사용 한도 답(500자 이하)은 이제 형식 실패가 아니어서 Sonnet으로 다시 돌리지 않는다.
- 사진: 이유를 알면 그 문구가 v2.4 캡션 규칙을 대신한다. `other`면 v2.4 그대로(먹었다는 캡션이면 값 없는 일반식 제안, 아니면 사진 문구 + 다시 보내기 줄).
  질문 답이 실패하면 전처럼 기존 답장이다.
- 콘솔: `llm codex: failed (exit 1) after 2.1 s (gpt-6.1-sol); reason usage_limit; trying fallback claude`(`other`·`timeout`이면 꼬리 없음),
  `chat 111: retry 3f2a offered (network)`, `chat 111: retry 3f2a used`.
- 기록 줄은 맨 끝에 두 key가 늘어난다(22 key, `v`는 1): `failure_reason`(마지막 LLM 호출이 실패했을 때의 이유, 아니면 `null`)과 `retry_of`(`/retry_`로
  다시 처리한 메시지의 token). 16/18/20 key 줄은 그대로 읽힌다. `telegram history`: `… text codex/gpt-6.1-sol failed reason=network`, 다시 처리한 줄은
  끝에 `retry_of=3f2a`. `/history`: 머리 줄 끝에 ` · 실패 이유: 네트워크`.

### `/retry_<id>` 다시 보내기

```text
사용자: 오늘 아침 밥한공기 굴비 작은거 두마리 미역국 건더기만 먹었어
bot:   인터넷 연결이 끊긴 것 같아 해석하지 못했습니다. 연결되면 아래 명령으로 다시 보내세요.
       다시 보내기(60분 유효): /retry_3f2a
```

- 글 해석 실패, 사진 해석 실패(값 없는 일반식 제안은 제외), 메뉴 제안 호출 실패, 사진을 한 장도 받지 못했을 때(일부만 받은 앨범은 v2.4 줄 그대로)에 붙는다.
- 누르면 그 메시지를 **처음 받은 것처럼** 다시 처리한다: 사진은 같은 file id로 다시 받고(`PHOTO_MAX_BYTES`, 앨범 장수 규칙 그대로), LLM을 부르고, 제안을
  만든다. `/ok` 전에는 아무것도 쓰지 않으므로 같은 끼니가 두 번 기록되지 않는다. 날짜와 끼니 시각은 **처음 받은 시각**으로 정한다(23:27 메시지를 00:10에
  다시 보내도 전날 저녁). 유효 시간은 실제 시계다.
- 한 번만 쓰인다: 쓰는 순간 `used`로 바꾸고 원문을 지운 뒤(한 번의 저장) 처리한다. 거절: 모르는 token과 다른 chat의 token은 `이 다시 보내기 명령을 찾지
  못했습니다.`(같은 문구), 쓴 것은 `이미 다시 보낸 메시지입니다. /history로 확인하세요.`, 60분 지난 것은 `다시 보내기 유효 시간(60분)이 지났습니다. 메시지를
  다시 보내 주세요.` 거절은 아무것도 쓰지 않는다(기록 줄 종류 `retry`, `/history`의 `다시 보내기`). `/ok_`·`/no_`를 다시 보내기 token에 쓰면 `이 명령은 이
  제안에 쓸 수 없습니다.`
- 원문(글, 캡션, 사진 file id)은 상태 파일의 `kind: "retry"` 제안에 **60분만** 있다. bot이 시작할 때와 쉬는 poll마다 만료된 원문을 지운다(콘솔
  `llm retry: expired messages removed`). 기록과 기억에는 v2와 같이 원문이 남는다.
- 허용 목록·오래된 메시지 규칙은 `/retry_` update 자신에 그대로 적용되고, 저장된 chat이 보낸 사람과 같아야 한다.
- LLM이 꺼진 bot에서 `/retry_x`·`/new_x`·`/add_x`는 v1의 모르는 명령 답 그대로다.

### 사용 한도 때 다른 제공자로

- 순서는 `[지금 제공자]`, 그다음 `fallback_provider`(설정돼 있고 다르면)다. 지금 제공자가 `usage_limit`로 끝났고 `fallback_on_usage_limit`가 켜져 있고
  아직 두 번째 제공자가 없으면 다른 제공자를 붙인다. 그래서 양쪽 방향으로 되고, 세 번째 제공자 실행은 생기지 않는다(한 단계 최대 4번 그대로).
- 숫자 재확인의 다시 묻기(`RunPin`)는 넘어가지 않는다.
- 넘어가서 답을 받으면 답장 본문 끝에 `(Codex 사용 한도라 이번에는 claude(Anthropic)로 처리했습니다.)`가 붙는다.

### 기존 끼니에 더하기 (`join_existing`, `/new_`, `/add_`)

해석 schema의 item에 `join_existing`(boolean, 필수)이 생겼다(아래 `lookup_wanted`까지 item key 16개). 사용자가 "같이", "하나에", "기존 ~에 추가", "~에 더해"라고 하면 그 끼니의
item마다 true다.

```text
기존 아침 2026-10-16-breakfast-1(바나나 (banana) 1 count)에 추가할까요? (10-16)
1. 일반식 (메모: 고구마 1개)
   추정: kcal 180~220, 단백질 2~3 g (estimated)
추가: /ok_9b1e   일반식만 추가(값 없이): /plain_9b1e   새 아침으로 따로: /new_9b1e   취소: /no_9b1e
```

- 한 끼니의 **모든** item이 true이고 그날 그 끼니의 기록(활성)이 **정확히 하나**일 때만 더한다. `/ok_`·`/plain_`은 `nutrition meal add-item <id> …`(값
  있음/없음)이고 끼니 ID가 그대로다. 답장은 짧은 `수정했습니다` 요약이고 undo 줄(`/void`)은 없다(기존 끼니 전체를 지우게 되므로). `/new_`는 따로 새 끼니
  (`nutrition log … --additional`)다. 기존 item은 앞의 3개까지 보이고 나머지는 ` 외 N개`. 같은 음식이 이미 있으면 겹침 안내 줄은 남고 `/fix_`는 없다.
- 그 끼니 기록이 없으면 첫 줄 `기존 아침이 없어 새로 기록합니다.`, 둘 이상이면 `같은 날 아침이 여러 개(a, b)라 어디에 더할지 정하지 않았습니다. 하나 더
  기록합니다.`(어느 쪽인지 추측하지 않는다)이고 새 끼니 제안이다. item 중 일부만 true면 더하지 않는다.
- 말이 없어도 그 끼니 기록이 정확히 하나이고 겹치는 음식이 없으면 새 끼니 제안에 `기존 아침에 추가: /add_9b1e`가 붙는다(D6 J-B):
  `기록: /ok_9b1e   일반식만 기록(값 없이): /plain_9b1e   기존 아침에 추가: /add_9b1e   취소: /no_9b1e`. 값 없는 사진 일반식 제안에는 붙지 않는다.
- 여러 끼니 제안은 끼니마다 정한다: 더하는 끼니의 블록 머리는 `아침: 기존 2026-10-16-breakfast-1에 추가`이고 명령 줄은
  `기록: /ok_X   값 없이 일반식만 기록: /plain_X   새 끼니로 따로: /new_X   취소: /no_X`다. `/new_`는 모든 끼니를 새로 기록한다. `/add_`는 없다.
- `/ok_`·`/plain_`·`/add_` 때 더할 끼니를 `get_active`로 **다시 읽는다**. 없거나 void되었으면 `오류: 기존 아침 2026-10-16-breakfast-1이 없거나 취소(void)되어
  추가하지 않았습니다. 새 끼니로 기록하려면 /new_9b1e`(`/add_`면 `하나 더 기록하려면 /ok_9b1e`)이고 아무것도 쓰지 않으며 제안은 열린 채로 남는다.
  `nutrition meal add-item`도 void된 끼니를 거절한다. 기록 줄은 `confirm`이고 결과의 meal ID는 더한 끼니다(그래서 "방금 거"에도 들어간다).

### 열린 제안 고치기

- 식사 제안이 열려 있는 동안 오는 **글 메시지**는 제공자의 `retry_model`로 처음부터 돈다(`LlmRequest.strong_model`, D4 E1; Claude 기본은 sonnet). 재시도·
  대체 규칙은 그대로이고 sonnet → sonnet 재시도는 없다. Codex는 재시도 모델이 없어 같은 `gpt-6.1-sol`이다.
- 고친 제안은 앞선 고치기 메시지를 들고 간다(최대 5개, 공백을 줄이고 120자까지, 오래된 것부터). 다음 고치기의 `<열린 제안>`에 `앞선 수정 요청(오래된
  것부터):`과 `- …` 줄로 들어가고, 해석 규칙은 "그 요청(양, 추가, 삭제)을 모두 둔 채 이번 수정을 더하고 되돌리지 않는다"이다.
- **spec 범위 6의 "앞선 수정을 되돌리면 형식 실패로 보고 한 번 더" 검사는 하지 않는다**(D5 R0, 사용자 결정 2026-10-21). outline이 같은지 비교하는 방법은
  실제 사례(두 번째 수정이 다른 item도 바꿈)를 잡지 못하고, 이름으로 맞추는 방법은 거짓 양성마다 Sonnet 실행을 더 쓴다. 대신 위의 모델과 요청 사슬로
  원인을 줄이고, 고친 제안 전체가 `/ok` 전에 보인다.

### 웹 검색은 Claude로만 (사용자 결정 W3, 2026-10-21)

Codex는 격리 argv(`-c web_search="disabled"`, `--disable code_mode_host`)에서 검색할 수 없다(아래 Known issues). 그래서 Codex 격리는 main 그대로 두고,
검색이 필요한 메시지만 Claude가 한 번 더 읽는다.

- 해석 schema의 item에 `lookup_wanted`(boolean, 필수)가 생겼다. 상표·식당·체인·포장 제품처럼 웹에서 찾은 값이 추정을 크게 바꿀 item만 true다
  (`맥도날드 빅맥 세트`, `스타벅스 카페라떼`). 밥, 김치, 계란말이 같은 집밥은 false다.
- Codex가 먼저 **검색 없이** 읽는다. 답이 `meal_log`이고 item 하나라도 `lookup_wanted`이고 `web_search`가 켜져 있고 Claude 실행 파일이 있으면, 같은
  메시지(사진이면 같은 사진, 앨범이면 같은 장들)를 Claude에 **한 번** 보낸다: 웹 검색 규칙, 검색 최대 3회, 150 s, 모델은 Claude의 글/사진 모델
  (기본 haiku/sonnet), 재시도·대체 없음. 그 답이 Codex 답을 **통째로** 바꾼다(item, 값, 출처, 근거 문자열의 `(claude haiku)`). 숫자 재확인은 그 뒤의
  답에 대해 돌고, 다시 묻기도 웹 규칙으로 Claude에 간다.
- Claude 확인이 실패하면 Codex 답을 그대로 쓰고 본문 끝에 `(웹 검색은 하지 못했습니다: 사용 한도)`처럼 이유 이름을 붙인다. 세 번째 호출은 없다.
  사용 한도 대체 안내 줄은 붙지 않는다(답은 Codex의 것이다).
- 질문, 메뉴 제안, 고치기, 그 밖의 intent는 확인하지 않는다. 제공자가 Claude면 v2.4 그대로(처음부터 검색 규칙, `lookup_wanted`는 무시).
  Claude가 사용 한도나 실패로 끝나 Codex가 대신 답한 경우도 확인하지 않는다(Claude를 바로 다시 부르지 않는다). 새 설정 key는 없다: `"web_search": false`면 확인도 없다.
- 보이는 곳: 제안의 `웹 검색 2회 (Claude)`(확인한 메시지는 0회여도 나온다), 콘솔 `chat 111: llm lookup on claude (haiku)`와 실패 때
  `chat 111: llm lookup failed (usage_limit); kept the codex answer`, `telegram history`의 사슬
  `codex/gpt-6.1-sol ok -> lookup claude/haiku ok web=2`, 기록 줄의 시도(`attempts`)에 `"lookup": true`(그 시도만 key 5개), `/llm` 꼬리, 시작 줄.
  기록 줄의 `provider`/`model`/`web_searches`는 답을 낸 쪽(확인이 성공하면 Claude)이다.

```text
사용자: 점심 맥도날드 빅맥 세트 먹었어
bot:   이렇게 기록할까요? (점심, 10-21)
       1. 일반식 (메모: 맥도날드 빅맥 세트)
          추정: kcal 1050~1250, 단백질 30~36 g (estimated)
          출처: 맥도날드
       웹 검색 2회 (Claude)
       기록: /ok_5c1d   일반식만 기록(값 없이): /plain_5c1d   취소: /no_5c1d
```

### 코치가 bot 명령과 동기화 상태를 안다

- 질문 답 프롬프트에는 과제 뒤에 `[bot 명령]` 절로 `help_text(True)`가 들어간다(`[데이터]` 밖이라 그 안의 숫자는 답에 쓸 수 있는 숫자가 아니다). 해석·메뉴 제안
  프롬프트에는 없다. 해석의 `question_topics`에 `bot`이 생겼다("동기화 명령어 뭐야?"; "동기화 해줘"는 그대로 `sync_request`).
- `training`과 `bot` 질문의 `[데이터]`에는 `<동기화 상태>`가 들어간다: `garmin coverage --from D-13 --to D --json`(읽기 전용)을 요약한 것이다.

```text
기간 10-08~10-21 (14일, 오늘 포함)
운동 동기화 안 됨: 10-09~10-18
회복 동기화 안 됨: 10-09~10-18 · 회복 일부만: 10-20
동기화했고 운동 없음: 10-19
오늘: 운동 동기화 안 됨, 회복 동기화 안 됨
```

- 빠진 날은 오늘 앞의 13일로 정한다(오늘은 마지막 줄). 빠진 날이 없으면 둘째 줄이 정확히 `빠진 날 없음`이다. coverage 표가 없는 DB는 `동기화 기록이 이 DB에
  아직 없습니다(알 수 없음).`이고(`빠진 날 없음`이 아니다), 읽지 못하면 블록을 빼고 콘솔에만 남긴다. 결과에 없는 날은 `동기화 안 됨`이다.
- 답 규칙: `[bot 명령]`이 유일한 명령 목록이고 지어내지 않는다. `동기화 안 됨`과 `동기화했고 운동 없음`은 다르고, 동기화 안 된 날은 적힌 날짜 그대로 말하고
  `/daily`를 안내한다. v2.4의 `/daily` 규칙은 이 규칙으로 바뀌었다. `daily-catch-up`이 `/sync`를 더하면 도움말을 통해 자동으로 목록에 들어간다.
- `bot` 질문의 데이터는 동기화 상태뿐이다. 답이 숫자 검사를 통과하면 답이 말한 도움말 명령(나온 순서, 중복 없이 최대 4개)이 누를 수 있는 줄로 붙는다. 실패하면
  도움말 전체가 답이다. 운동 질문의 답에는 명령 줄을 붙이지 않는다(v2.4 답 모양 그대로).

### live 확인 (implementer, 2026-10-21, Claude Code / Codex CLI 0.160.0, 합성 데이터)

임시 폴더, 합성 프롬프트, 프로젝트의 격리 argv. 실제 로그인은 바꾸지 않았다(빈 `CODEX_HOME`/`CLAUDE_CONFIG_DIR`는 임시 폴더).

| 확인 | 결과 |
|---|---|
| `-m gpt-6.1-sol` + strict `--output-schema` | 통과 |
| v2.5 해석 schema(`join_existing` 필수, `bot` 주제) | Codex(`gpt-6.1-sol`)와 Claude(haiku) 모두 `ok`. Haiku는 "아침은 하나에 같이"에 `join_existing: true`, Codex는 "동기화 명령어 뭐야?"에 `question`/`bot` |
| 로그인 없음 | Claude: exit 1, `result` 오류 `Not logged in · Please run /login` → `login`. Codex: `401 Unauthorized … Missing bearer` → `login` |
| 연결 안 됨(`HTTPS_PROXY=http://127.0.0.1:9`) | Claude: 상태 없는 `system/api_retry`만 반복하다 시간 초과 → `network`. Codex: `workspace routing discovery failed`, exit 1 → `network` |
| Codex stderr | 매 실행 프롬프트를 그대로 다시 찍는다 → 분류 전에 지우고 `error` 줄만 본다 |
| Codex 웹 검색(W3) | **켜지 못함**(아래 Known issues). 사용자 결정으로 Claude 확인으로 바꿈 |
| `lookup_wanted`(16 key schema) | Codex(`gpt-6.1-sol`): `점심에 맥도날드 빅맥 세트 먹었어` → true, `점심에 밥 한공기 계란말이 먹었어` → 두 item 모두 false. Claude(haiku)도 같은 schema로 `ok`, 빅맥 true |

사용 한도는 일부러 만들 수 없어 실제 문구로 확인하지 못했다(CLI가 알려진 문구를 쓴다고 가정).

### Output change(LLM이 켜졌을 때, `breaking`)

- 바뀜: 기본 제공자와 Codex 모델(`{}` 설정), 실패 답장과 사진 받기 실패 답장의 `/retry_` 줄, `PHOTO_FAILED_TEXT` 뒤의 줄, 사용 한도 안내 줄, 기존 끼니에
  더하기·`/new_`·`/add_` 제안과 답장, 질문 답 프롬프트(`[bot 명령]`, `<동기화 상태>`, 바뀐 규칙)와 `bot` 주제 답, 해석 프롬프트·schema, 열린 제안 고치기의
  모델과 근거 문자열(`(claude sonnet)`), `lookup_wanted`와 Claude 확인(`웹 검색 N회 (Claude)`, 실패 안내 줄, 시도의 `lookup`, `/llm` 꼬리), 상태 파일의 새 key, 기록의 두 key, `telegram history`·`/history`의 새 줄 꼬리, 시작 줄과 실패 콘솔 줄, LLM이 켜졌을 때
  손으로 친 `/new_x`·`/add_x`·`/retry_x`(전에는 v1의 모르는 명령 답, 이제 고정 거절 문구).
- 바뀌지 않음: 모든 `muscle50` CLI 명령의 출력(`telegram history`의 옛 줄 포함), `telegram_llm.json`이 없을 때의 bot(답장·DB·상태 파일·`getUpdates`), 손으로 친
  `/log /void /day /status /show /help /llm` 답, `/llm` 첫 줄의 모양, 새 규칙 외의 해석·메뉴 제안 프롬프트, Claude argv와 `-m` 외의 Codex argv.

## 생활 단위(팩·개·마리): `food fact add --new-unit`

단위는 환산하지 않는다. 대신 카탈로그 음식에 그 단위의 값을 **따로** 등록한다.

```powershell
muscle50 nutrition food fact add chicken-breast --per 1 pack --kcal 165 --protein 34 --carbs 0 --fat 2 --source nutrition_label --accuracy exact --new-unit
```

`Added fact food:chicken-breast:2 to chicken-breast as its first fact per pack; facts per other units are unchanged.`
그 단위의 첫 fact(아무것도 대체하지 않음)이고 다른 단위의 fact는 그대로다. 이미 있는 단위에 `--new-unit`을 주면
`food 'x' already has nutrition per pack; run without --new-unit to add a new version. Nothing was changed.` 플래그가
없으면 동작과 거절 문구는 전과 같다. 단위를 잘못 넣었으면(예: g 대신 ml) 지우지 않고 `food fact add`로 새 버전을 쌓는다.

## 파일과 개인정보

| 파일 | 만드는 것 | 내용 |
|---|---|---|
| `config\telegram_llm.json` | 사용자 | 설정(비밀값 없음) |
| `config\telegram_llm_coach.md` | 사용자 | 코치 가이드 |
| `config\telegram_llm_state.json` | `telegram run` | `/llm` 선택, 열린 제안(정확한 argv. v2.3부터 보인 item 줄 `outline`과 `/fix_` 명령 `fix_argv`·`fix_change`도. v2.5부터 고치기 요청 `edit_requests`, 더할 끼니 `join_meal_id`·`argv_alt`·`alt_action`, 그리고 `/retry_`의 **실패한 메시지 원문·캡션·사진 file id를 60분만**). 손상되면 bot이 멈춘다(지우고 다시 시작 가능) |
| `config\telegram_llm_memory.json` | `telegram run` | chat별 요약(300자)과 최근 8턴(각 300자, 24시간) — **메시지 원문 포함** |
| `telegram\history\YYYY-MM.jsonl` | `telegram run` | 대화마다 한 줄, 추가만. 시각, chat, 메시지, 사진 위치, 의도, 제공자·모델, 검증된 LLM 출력, 답장, 제안, 결과(meal ID), 재시도 여부와 시도 목록 — **식단과 대화 원문 포함** |
| `telegram\photos\YYYY-MM\<sha256>.jpg` | `telegram run` | 받은 사진(`keep_photos`) |
| `telegram\run-YYYY-MM.log` | `telegram run`(LLM이 꺼져 있어도) | 콘솔 줄(token을 가린 ASCII)과 `run started`·`alive`·`run stopped` 줄. 메시지 원문 없음. 추가만, muscle50이 지우지 않음 |

- 기록과 사진은 muscle50이 지우지 않는다. 필요하면 직접 지운다. `/forget`과 기억 상한은 기록을 지우지 않는다.
- 콘솔 로그에는 메시지 원문, LLM 답, 사진 URL(bot token 포함)을 남기지 않는다(ASCII, chat ID와 결과 종류만).
- **전송되는 데이터**: 메시지, 사진(캡처 포함), 기억, 코치 가이드, 필요한 muscle50 JSON(질문 주제에 따라 운동 추천,
  영양 상태, InBody 추세; 메뉴 제안에는 오늘 먹은 음식 이름)이 고른 제공자(Anthropic 또는 OpenAI)로 간다. 대체
  제공자를 켜면 두 회사 모두로 갈 수 있다.
  - v2.2부터 **글과 사진 해석 호출마다** 카탈로그 목록(음식 ID, 이름, 별칭 최대 3개, 등록 단위; 최대 120개·6000자)이
    같이 간다. 질문 답과 메뉴 제안 호출에는 가지 않는다.
  - v2.5 기본(Codex)에서는 `lookup_wanted`인 메시지만 Claude 확인으로 Anthropic에도 간다(메시지, 사진, 같은 데이터 블록).
  - 웹 검색이 켜져 있으면 Claude가 만든 **검색어**(상표·식당·제품 이름)가 Anthropic의 검색으로 간다. 사진에서 읽은
    제품명·식당 이름도 같다(사진 자체는 이미 Anthropic으로 간다). 검색어와 결과는 muscle50이 저장하거나 기록하지 않는다.
- v2.3부터 글 해석 호출에는 최근에 기록한 식사 둘, 열린 제안, 최근 메뉴의 이름·메모·값도 같이 간다(위 "전송되는 데이터 (v2.3)").
- 메뉴 캡처에는 이름이나 사번이 보일 수 있다. **메뉴 부분만 잘라서** 보낸다.

## 코드 위치

- `domain/telegram_llm.py`(LLM 출력 검증·경계, 날짜 표현, 끼니 시각표, 명령 문법, 기억, 기록 줄),
  `domain/telegram_llm_prompt.py`(프롬프트, 고정 규칙, bot 문구), `domain/llm_number_guard.py`, `domain/llm_today_totals.py`,
  `domain/menu_ranking.py`, `domain/llm_settings.py`.
- v2.3: `domain/telegram_llm_corrections.py`(최근 기록 식사, 대상 식사·item 찾기, 추정 합치기, 겹침과 `/fix_` 계획, 열린 제안·최근 메뉴 블록),
  `infrastructure/sqlite/nutrition_reader.py`의 `get_active`, `tests/test_telegram_llm_corrections.py`·`tests/test_telegram_llm_corrections_bot.py`·
  `tests/test_nutrition_replace_item_estimate.py`.
- v2.2: `domain/telegram_llm_meals.py`(끼니 묶음, 끼니 낱말, 카탈로그 목록, 근거 문자열), `domain/telegram_llm_check.py`(숫자
  검사와 다시 묻기 note), `application/telegram_bot.py`의 `RunConfirmedSequence`/`_run_sequence`,
  `infrastructure/llm/argv.py`의 검색 변형, `infrastructure/llm/provider.py`의 검색 횟수와 고정 실행(`RunPin`).
- `application/telegram_llm.py`(`TelegramLlmHandler`), `application/llm_provider.py`(포트), `application/telegram_bot.py`
  (`llm` hook, `_run_command(on_outcome=…)`).
- `infrastructure/llm/`(argv, 프로세스, 실행 파일, 제공자), `infrastructure/telegram/`(설정, 상태, 기억, 기록, 사진, 코치
  가이드, Bot API 사진), `infrastructure/sqlite/food_catalog_reader.py`(읽기 전용 카탈로그).
- `presentation/telegram_llm_replies.py`, `cli.py`(`telegram history`, `_telegram_llm` 연결, A2 플래그, `--new-unit`).
- v2.4: `domain/telegram_llm_photo.py`(캡션 규칙, 사진 기억 문구, 앨범 안내 줄), `domain/telegram_llm_summary.py`와
  `presentation/telegram_llm_summary.py`(짧은 답장), `domain/llm_today_totals.py`의 `nutrient_totals`(하루와 한 끼니가 같이 씀),
  `application/telegram_bot.py`(앨범 모으기, 한 update 보호, `TelegramRunStoppedError`), `infrastructure/telegram/network_error.py`,
  `infrastructure/telegram/run_log.py`, `infrastructure/telegram/state_store.py`의 `replace_with_retry`,
  `infrastructure/llm/argv.py`·`provider.py`(여러 사진), `tests/test_telegram_llm_albums_bot.py`·`test_telegram_llm_reliability*.py`·
  `test_telegram_bot_resilience.py`·`test_telegram_run_log.py`·`test_telegram_network_error.py`.
- v2.5: `domain/llm_failure.py`(이유 목록과 문구), `infrastructure/llm/failure_reason.py`(분류), `domain/telegram_llm_context.py`(동기화 상태 요약,
  도움말 명령), `infrastructure/llm/provider.py`(이유, 사용 한도 대체, `strong_model`), `application/telegram_llm.py`(`/retry_`, `purge_expired`, 더하기,
  고치기 사슬, 질문 맥락), `tests/test_llm_failure_reason.py`·`test_telegram_llm_failures*.py`·`test_telegram_llm_join_bot.py`·
  `test_telegram_llm_edit_chain_bot.py`·`test_telegram_llm_context.py`.

## Known issues / limitations

- **모델 선택과 재시도**
  - 최악의 경우 한 호출 단계에 CLI가 4번(제공자 2 x 첫 실행 + 재시도) 돈다. 질문·메뉴 제안은 호출이 두 번이라 최대 8번이고,
    90초 상한이면 약 12분이다. 그동안 다른 메시지는 기다린다(한 번에 한 메시지). 대체 제공자는 기본으로 꺼져 있다.
  - 기록 줄은 마지막 LLM 호출만 설명한다. 질문처럼 호출이 둘일 때 첫 호출이 재시도되고 두 번째는 아니면 기록에는
    `retried: false`로 보이고, 재시도는 콘솔 로그에만 남는다.
  - `/llm`은 대체 제공자의 모델을 보여 주지 않는다.
  - 형식은 맞지만 내용이 틀린 답(잘못 읽은 메뉴, 틀린 양)은 재시도하지 않는다.
  - 재시도는 구독 사용량을 한 번 더 쓴다. Haiku가 형식을 자주 틀리면 Sonnet 실행이 늘 수 있다(사용 통계는 아직 없다).
  - Claude CLI의 사용 한도 메시지가 오류 결과로 오면 재시도하지 않지만, 평범한 결과 문장으로 오면 형식 실패로 보여 한 번
    재시도한다. 실제 CLI의 한도 출력은 이 기능에서 확인하지 않았다(가짜 runner로만 검증).
  - 이 기능을 켠 뒤 저장되는 추정 근거 문자열이 `claude sonnet` 대신 `claude haiku`로 바뀐다(글 메시지).

- **식사 추정·여러 끼니·웹 검색 (v2.2)**
  - **최악의 경우가 늘었다.** 해석 호출 한 단계는 CLI가 최대 **5번** 돈다(제공자 2 x 첫 실행 + 재시도 = 4, 숫자 재확인의
    다시 묻기 1). 검색 도구를 받은 실행은 각각 150 s까지 쓸 수 있어 한 메시지가 최대 약 12.5분(5 x 150 s)이다(이전 4 x 90 s =
    6분, 검색 설정 후 4 x 150 s = 10분). 질문·메뉴 제안은 식사 item이 없어 다시 묻지 않으므로 8번 그대로다. 대체 제공자는 기본으로
    꺼져 있고 다시 묻기는 형식 재시도·대체와 달리 숫자 검사가 실패할 때만 돈다.
  - **검색 켜짐이 기본이다.** 재시작하면 v2.1 `telegram_llm.json`도 검색을 시작해 시간과 구독 사용량이 늘고 검색어가
    Anthropic으로 간다. 끄려면 `"web_search": false`. 설정 파일이 없으면 bot은 그대로다.
  - 횟수 상한은 프롬프트 규칙이라 모델이 넘길 수 있다(콘솔에 `above the limit`). 하드 상한은 시간뿐이고, timeout이 나면 그
    메시지의 답과 사용량은 버려진다. 검색 지연의 실제 분포는 확인하지 못했다(live 확인은 1회짜리 둘뿐).
  - 검색 결과는 틀릴 수 있다. 값은 범위 추정으로만 저장되고, 사이트 이름은 모델이 적은 것이라 실제 출처와 다를 수 있다.
    웹을 쓰지 못했을 때(Codex, 검색 끔) `source`는 비어 있어야 하지만 모델이 적어도 막지는 못한다(주소 형태만 거절한다).
  - 대체 제공자만 Claude인 설정(`provider: codex`, `fallback_provider: claude`)에서는 첫 실행이 Codex라 검색할 수 없지만
    프롬프트에는 검색 규칙이 들어간다.
  - 숫자 재확인은 거짓 양성이 있다(섬유질, 알코올, 당알코올이 든 음식). 한 번 더 Sonnet 실행을 쓴다. 허용 오차는 20%와 20 kcal이고
    기록의 `recheck`로 실제 빈도를 볼 수 있다. 표시가 항상 `/ok`로 받아들여지면 소음이 된다(`값 확인 필요`가 근거 문자열에
    남으므로 나중에 찾을 수 있다). 다시 묻기는 이전 답을 보지 못해 순서가 바뀔 수 있다.
  - `assumption`에 숫자를 쓰지 말라고 프롬프트에 적었지만 모델이 쓰는 경우가 있다(live 확인 5). 수량·추정값과 같은 숫자는
    허용하고 다른 숫자는 다시 묻기 사유다.
  - 여러 끼니 `/ok` 도중 프로세스가 죽거나 Ctrl+C면 남은 끼니는 돌지 않고 답/기록 줄이 빠질 수 있다. 이미 기록된 끼니는 `/day`로
    보인다. 일부만 기록됐을 때 남은 끼니만 다시 제안하는 기능은 없다.
  - 끼니 낱말 필터는 끼니 낱말과 똑같은 이름의 실제 음식을 빼 버린다(드묾). 한 문장에 끼니 둘이 같은 끼니로 합쳐지는 것은
    의도다. 날짜가 섞이면 처리하지 않는다.
  - 카탈로그 목록은 최대 120개·6000자이고, 넘으면 메시지에 이름이 나온 음식이 먼저다. 이름이 비슷한 음식은 모델이 잘못 고를
    수 있다(제안에 카탈로그 이름이 보이고 사용자가 확인한다).
  - 근거 문자열의 출처·가정 부분은 100자 한도 때문에 잘릴 수 있다(사진은 약 45자만 남는다).
  - 이미 저장된 제안(v2.1)은 `meals` 없이 읽히지만 제안 문구는 만들 때 정해져 있다.

- **Codex는 `~/.codex/AGENTS.md`(사용자 전역 지시)를 읽는다.** `--ignore-user-config`와 `-c project_doc_max_bytes=0`으로도
  막히지 않았다(구현 단계 확인 4). 그 파일은 사용자 자신의 텍스트 지시일 뿐 도구나 MCP를 켜지 않지만, 응답 언어 같은
  지시가 끼어들 수 있다. 완화: 고정 규칙이 프롬프트에서 그 뒤에 오고 이긴다고 적혀 있으며, 답은 schema와 bot 검증을
  거치고, 모든 쓰기는 확인을 받는다. 기본 제공자는 Claude이고 Codex는 `/llm`이나 설정으로 직접 고른다. `CODEX_HOME`을
  바꾸는 우회는 로그인 파일을 옮기게 되므로 쓰지 않았다. **그래서 AC7(사용자 설정을 불러오지 않음)은 Claude에서는
  충족하고 Codex에서는 일부만 충족한다.** 사용자가 이 남는 위험을 2026-10-13에 받아들였다(spec AC7). 그래서 Codex는
  계속 고를 수 있다(설정의 `provider`/`fallback_provider`, `/llm codex`). 기본값은 그대로 `claude`이고 fallback은
  꺼져 있다. 쓰고 싶지 않으면 `codex`를 고르지 않으면 된다.
  - **2026-10-21 갱신(v2.5):** 사용자 결정("그냥 클로드가 하던 모든일을 코덱스로 바꿔")으로 **기본 제공자가 `codex`가 되었다.** 그래서 위의 근거였던
    "기본값은 그대로 `claude`"는 더 이상 맞지 않고, 이 남는 위험(`~/.codex/AGENTS.md`의 지시가 끼어들 수 있음)은 이제 **모든 메시지**에 해당한다. 사용자가
    2026-10-21에 이를 받아들였다. 완화는 위와 같다(고정 규칙이 이김, schema와 bot 검증, 모든 쓰기는 확인). 피하려면 `"provider": "claude"`를 적는다.
    사용 한도 대체가 기본으로 켜져 있어 Claude로 넘어가면 메시지가 Anthropic으로도 간다(답장에 표시된다).
- Codex에는 "도구 없음" 스위치가 없다. 0.160.0에서 `functions.wait`, `request_user_input`, `collaboration.*`이 남는다.
  cwd에는 사진만 있고, 출력은 검증되고, 쓰기는 확인을 거친다. `--disable` 목록은 버전마다 바뀌므로 업그레이드 뒤 확인을
  다시 한다.
- 한 번에 한 메시지: LLM 호출(최대 timeout, 질문·메뉴 제안은 두 번) 동안 다른 메시지는 기다린다. 응답이 수 초~수십 초.
- 구독 사용량을 쓴다(코딩 한도와 나눠 씀). 개인 자동화가 각 약관의 일반적인 개인 사용인지는 회색지대다.
- 사진 칼로리 추정은 오차가 크다(흔히 ±30~50%). 추정은 범위로만 저장되고 판정에 쓰이지 않는다.
- 숫자 검사의 한계: 작은 정수는 거의 항상 데이터에 있다. 단위를 바꿔 쓴 답(g ↔ kg)은 통과할 수 있다. 한국어 수사
  (`오십`)는 숫자로 보지 않는다.
- 메뉴 순서는 자주 P 모드다: 첫 식사 전, 값 없는 일반식이 있는 날, kcal 목표가 없을 때.
- 식사 수정은 하나로 정해질 때만 대상을 정한다(카탈로그 이름, 일반식 메모, 식사의 유일한 item, "아침 1식", 방금 기록한 둘 중 하나).
  그 밖에는 후보만 보여 준다. 일반식의 양은 고칠 수 없다(양이 없다). 일반식의 추정값과 메모는 v2.3부터 고칠 수 있다(아래).

- **이어지는 고치기·라벨·범위 누적 (v2.3)**
  - **"방금 거"는 최근 기록 둘이다.** 낱말 없이 "방금 거 취소해"처럼 식사 전체를 고치려 하면 둘 다에 맞아 후보만 보여 준다("가장 새 것"으로
    넘어가지 않는다). 둘 다 맞거나 둘 다 안 맞는 말도 후보만 나온다. 의도한 동작이다.
  - **최근 기록은 history에서 읽는다.** 손으로 친 `/log`로 기록한 식사는 들어가지 않는다. 기록 쓰기가 실패해 줄이 빠지면 그 식사는 "방금 거"에 없다
    ("아침 1식"은 DB에서 푼다). 읽는 범위는 최근 200줄이라 그 사이에 기록 줄이 200개를 넘게 쌓이면 못 찾는다. 사진을 보내 라벨을 고치는 후속
    메시지는 사진이라 수정이 아니다(글만 고치기로 다룬다).
  - **열린 제안을 고치면 전체를 다시 쓴다.** 모델이 바뀌지 않은 item을 다르게 적을 수 있다(제안 전체가 `/ok` 전에 보인다). 사진 제안을 글로
    고치면 글 제안이 되어 출처가 `language_estimate`로 바뀐다. 열린 제안 블록에는 가장 새 제안 하나만 간다.
  - **겹침은 같은 메모일 때만이다.** "삼각김밥 1개"와 "깻잎닭갈비 삼각김밥 1개"처럼 메모가 다르면 겹치지 않아 하나 더로 기록한다(포함 판단은
    하지 않는다). `/fix_`는 명령 하나로 끝나는 경우만이고, 여러 군데를 고쳐야 하면 `/ok`(하나 더)와 `/no`뿐이다.
  - **수정한 일반식의 번호가 바뀐다.** `replace-item`은 새 item을 끝에 붙이므로 고친 item은 새 번호이고 옛 번호는 `nutrition day`에서 사라진다.
    옛 item과 fact는 감사용으로 남는다(`meal show`는 숨긴다).
  - **`nutrition day`는 라벨 값도 `estimated kcal 185-185`로 보인다.** DB는 라벨과 추정을 근거 문자열(`; 라벨`)로만 구분한다.
  - **메모 맞춤은 정확/포함 일치뿐이다.** 철자가 다르거나 띄어쓰기만 같은 이름은 후보가 된다. 정규화는 공백·문장부호만 지운다.
  - **`menu_ref`는 모델이 번호를 맞게 골라야 한다.** 이름 포함 검사가 막지만, 검사를 통과한 잘못된 선택은 제안에서 사용자가 보고 거른다. 가장 새
    메뉴 하나만 쓴다.
  - 합친 수정 추정의 숫자 검사는 걸려도 표시만 한다(다시 묻지 않음). 카탈로그 item의 값은 bot이 고치지 않는다.
  - live 확인은 합성 문장 몇 번뿐이다(분류 누락률 미확인, 라벨 이미지 미확인).
- 기록 완전성은 best-effort다: 처리 중 강제 종료나 기록 쓰기 실패(콘솔에 `history write failed`)면 그 줄이 빠질 수 있다.
  확인 명령이 예외로 끝나면(드묾) 그 확인 줄도 빠진다. 기억 파일이 손상되면 기억 없이 호출하고 그 파일은 쓰지 않는다.
- `/ok` 뒤의 `오늘 누적`은 `nutrition status/day --json`을 한 번 더 읽어 만든다. 읽지 못하면 그 줄만 빠진다.
- **신뢰성·앨범·짧은 답장 (v2.4)**
  - **앨범은 2초 안에 모인 것만이다.** 그보다 늦게 오거나 4장을 넘어 오는 사진은 따로 한 장씩 해석된다. 앨범이 나뉘어 도착하면 그 만큼 지연(최대 약 6초)이 생긴다.
  - **앨범을 모으는 동안 가져온 다른 메시지는 미리 확인(acknowledge)된다.** 앨범을 처리하기 전에 bot이 꺼지면 그 메시지들은 잃는다(두 번 실행되지는 않는다).
    같은 이유로 앨범 모으기 중에 Ctrl+C를 누르면 그 앨범은 처리되지 않는다.
  - **사진 앨범의 캡션은 앨범 전체에 쓴다.** 사진마다 다른 설명은 지원하지 않는다. 상한(4장)을 넘거나 받지 못한 사진은 `사진 N장 중 M장만 읽었습니다`로만 알린다.
  - **읽지 못한 사진도 `keep_photos`가 켜져 있으면 저장된다**(전과 같다: 저장은 해석 전에 한다). 아무것도 쓰지 않는다는 말은 DB와 제안·상태 파일에 대한 것이다.
  - **사진 기억 줄은 LLM을 부른 교환에만 있다.** 너무 큰 사진·받지 못한 사진은 줄이 없다. 사진 안의 글자나 값은 요약으로만 남고 사진 자체를 다시 보지는 않는다.
  - **`ate` 같은 짧은 영어 낱말은 단어일 때만 맞는다.** 한국어 낱말(`먹었` 등)과 `메뉴`·`menu`는 부분 문자열 검사라서, 애매하면 아무것도 쓰지 않는 쪽으로 기운다.
  - **실행 기록 파일은 돌리지 않는다.** 달마다 하나(작다). `alive`는 루프가 돌 때만 쓰므로 긴 LLM 호출 중에는 비어 있고, 창 닫기 기록은 최선 노력이라 PC가 꺼지거나
    강제 종료되면 마지막 `alive` 시각으로만 알 수 있다. 예상 못 한 오류의 traceback 마지막 줄에는 예외 문구가 들어갈 수 있다(콘솔에도 이미 나오는 내용).
  - **한 update를 건너뛰는 보호는 상태 파일을 쓰지 못하는 오류에는 적용하지 않는다.** 그때는 전처럼 멈춘다.
  - **메뉴 제안이 4시간이라 오래된 `/eat_` 버튼도 4시간 동안 눌린다.** 정확히 4시간째 1초는 이름으로는 고를 수 있고 `/eat_`는 만료다(위).
  - **짧은 답장의 `이 끼니` 줄은 길 수 있다.** 값이 없는 item이 있으면 영양소마다 `(값 모르는 항목 N개 빠짐)`이 붙는다. 라벨 표시는 근거 문자열의 `; 라벨`을 읽는 것이라 근거
    문자열 형식이 바뀌면 `추정`으로 보인다. 요약은 저장 뒤 한 번 더 읽는 것이라 그 사이 다른 쓰기가 있으면 그 값이 보일 수 있다(드묾).
  - **동기화 안내는 문구만이다.** 질문 답의 `/daily` 안내는 프롬프트 규칙이라 모델이 빠뜨릴 수 있다. `sync_request` 분류는 Haiku live 확인 두 문장뿐이다(누락률 미확인).
  - **프롬프트가 조금 길어져 Haiku가 형식을 틀릴 확률이 아주 조금 늘 수 있다**(틀리면 기존 재시도 규칙이 돈다).
- **실패 이유·다시 보내기·기존 끼니에 더하기 (v2.5)**
  - **Codex 웹 검색(사용자 결정 W3)은 켜지 못했다.** codex-cli 0.160.0은 웹 검색을 code mode 안에서만 한다(검색 item id가 `exec-…`). 격리 argv의
    `--disable code_mode_host`가 있으면 `-c web_search="live"`도, 최상위 `--search`도 검색하지 않았다(모델은 "검색하겠습니다"라고 하고 빈 값을 돌려줌).
    `code_mode_host`를 켜면 검색은 되지만 `functions.exec`, `tools.apply_patch`, `tools.web__run`이 생긴다(합성 확인: `-s read-only`에서
    `apply_patch` 쓰기는 거절됨, `file://` 열기는 실패). 이것은 격리 argv를 바꾸는 일이라 사용자 결정이 필요하다. 그때까지 Codex 호출은 모두
    `web_search="disabled"`이고 `_web_search_on()`도 그대로다(기본 설정에서는 검색 없음, `source`는 비고 `웹 검색 N회`도 없다). 켜게 되면 검색 횟수는
    `--json` 이벤트의 `item.completed`/`type: web_search`/`action.type: "search"`를 id마다 한 번 센다(`open_page`는 검색이 아니다).
    사용자 결정("검색은 Claude로만")으로 Codex는 그대로 두고, 필요한 메시지만 Claude가 검색한다(위 "웹 검색은 Claude로만").
  - **Claude 확인은 호출이 둘이다.** 확인하는 메시지는 Codex 답(약 12~17 s) 뒤에 Claude 검색 실행(최대 150 s)을 기다려서 늦다. Claude 구독 사용량도
    그만큼 생기고, 메시지(사진 포함)와 검색어가 OpenAI와 Anthropic **둘 다**로 간다. Claude 확인의 실패는 Codex 답으로 덮는다(안내 줄만).
  - **확인할지는 Codex의 `lookup_wanted`가 정한다.** 표시를 놓치면 검색 없이 Codex 추정만 남고(`출처` 없음), 집밥에 잘못 켜면 쓸데없이 Claude를
    부른다. live 확인은 위 두 문장뿐이다(누락률 미확인). Claude가 확인한 답의 `lookup_wanted`는 쓰지 않는다(한 번만 확인).
  - **Codex 사용 한도로 Claude가 대신 답하면 검색하지 않는다.** `fallback_provider`가 없으면 그 대체 실행은 v2.4의 사용 한도 대체 그대로(검색 규칙 없음)라서 상표 음식도 `출처` 없이
    추정만 나온다. 반대로 `"provider": "claude"`에서 Claude가 막혀 Codex가 답하면 확인을 건너뛴다(위).
  - **모델 이름은 바뀐다.** `gpt-6.1-sol`은 2026-10-21 기준 Codex의 Sonnet급 모델이다. 없어지면 Codex 호출이 실패하므로 `telegram_llm.json`의
    `codex.model`/`photo_model`로 바꾼다. `{"codex": {"model": "x"}}`만 적으면 사진은 여전히 `gpt-6.1-sol`이다.
  - **실패 이유는 CLI 문구에 기댄다.** 문구가 바뀌면 `other`(v2.4 문구 + 다시 보내기)로 떨어진다. 사용 한도는 live로 만들 수 없어 알려진 문구로만
    맞췄다. `rate limit`·`quota`·`dns` 같은 낱말은 넓어서, Claude의 오류 결과나 stderr에 다른 뜻으로 나오면 잘못 분류될 수 있다(답장 문구만 달라진다).
  - **Claude 네트워크 끊김은 시간 초과까지 기다린다.** CLI가 스스로 다시 시도하므로 `timeout_seconds`(기본 90 s, 검색 실행 150 s)가 지나야 답한다.
  - **다시 보내기 원문은 bot이 도는 동안만 지운다.** bot이 꺼져 있으면 다음 시작 때 지운다. 메시지 원문은 v2처럼 기록과 기억에도 있다.
  - **열린 제안이 있는 동안의 모든 글 메시지가 Sonnet으로 돈다**(Claude일 때, E1). 관계없는 질문도 그 60분 동안은 Sonnet이라 구독 사용량이 는다.
  - **더하기 판단은 LLM의 `join_existing`에 기댄다.** 놓치면 `/add_`(같은 끼니가 하나일 때)와 기존 끼니 표시로 사용자가 고른다. Codex는 "하나에 같이"를
    직전 기록의 `add_item` 수정으로 읽기도 한다(live 확인; 결과는 같다: 기존 끼니에 item이 더해지는 제안).
  - **사용 한도 대체는 따로 동의 없이 두 번째 회사로 보낸다**(기본 켜짐, 사용자 결정 D2). 답장의 안내 줄로만 보인다. 끄려면 `"fallback_on_usage_limit": false`.
  - `bot` 질문의 숫자 검사는 도움말의 숫자를 허용하지 않는다. `/refresh`의 "10개"처럼 도움말 숫자를 말한 답은 도움말 전체로 바뀐다.
  - 동기화 상태는 coverage 기록에 기댄다. `garmin latest`·`garmin refresh`는 coverage를 남기지 않아 그것만 쓴 날은 `동기화 안 됨`으로 보인다.
- 제안은 만들 때의 중복 확인(`--additional`)을 저장한다. 제안과 확인 사이에 같은 끼니가 기록되면 `nutrition log`의
  기존 거절 문구가 그대로 온다(두 번 기록되지 않는다).
- 날짜는 오늘과 어제만 문장으로 정한다. 그 밖의 날짜는 `/log`로 보낸다.
- 회사 사이트 자동 수집·예약(`cafeteria-auto`)은 v3 이후 후보이고, 회사 IT·보안 허용이 먼저다.
