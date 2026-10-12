# Telegram Free Text, Photo and Coach v2 (telegram-llm)

Spec: `docs/specs/telegram-llm.md`. Migration 없음(추정값은 migration 003의 기존 열, 나머지는 DB 밖 파일).
Output change: additive(새 `telegram history` 명령, `nutrition log`/`meal add-item`/`food fact add`의 새 플래그, LLM이
켜졌을 때만 `/help`에 늘어나는 줄과 새 답장).

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
  "provider": "claude",
  "claude": {"model": "sonnet", "executable": null},
  "codex": {"model": null, "executable": null},
  "persona": {"name": "머슬", "tone": "존댓말, 짧게, 담백하게"},
  "timeout_seconds": 90,
  "fallback_provider": null,
  "keep_photos": true
}
```

- `provider`: `claude` 또는 `codex`. `/llm codex`로 채팅에서 바꿀 수 있다(설정 파일은 바뀌지 않음).
- `model`: `null`이면 모델 옵션을 넘기지 않는다. Codex는 `--ignore-user-config`로 실행하므로 `null`은 **Codex 내장 기본
  모델**이지 `~/.codex/config.toml`에 적은 모델이 아니다.
- `executable`: 절대 경로 또는 `null`(PATH에서 찾음). Windows에서는 `.exe`만 실행한다(대소문자 무관). npm의
  `.cmd`/`.ps1` shim은 `executable_not_supported`로 거절한다. Python이 `cmd.exe`용으로 인자를 감싸지 않아
  `--tools ""`와 schema JSON이 깨지기 때문이다.
- `timeout_seconds`: 10~600. 넘으면 그 CLI의 프로세스 트리를 끝내고 실패로 처리한다.
- `fallback_provider`: `null`(기본) 또는 다른 제공자. 켜면 실패 시 한 번 더 시도하고, 메시지와 사진이 두 번째 회사로도
  간다.
- `keep_photos`: 받은 사진을 `telegram\photos`에 보관할지.
- 설정을 바꾸면 `telegram run`을 다시 시작한다. 시작할 때 콘솔에 한 줄이 늘어난다:
  `telegram llm: on, provider claude, fallback none, timeout 90 s; claude (C:\...\claude.exe); codex (C:\...\codex.exe)`.

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
        kcal 확인 480
        단백질 확인 39 g
        탄수화물 확인 70 g
        지방 확인 3 g
```

- 카탈로그 음식은 Food Name Lookup 규칙(정확한 ID, 이름, alias)으로만 잇는다. 없으면 `일반식 (메모: …) - 카탈로그에
  없음`, 여러 음식에 맞으면 `- 이름이 여러 음식에 맞음`, 양을 말하지 않았으면 `- 수량·단위를 말하지 않음`으로 바꾼다.
- 양을 말하지 않으면 LLM이 흔한 양을 제안할 수 있지만 `(수량 추정)`이 붙고 확인을 받는다.
- 그 음식에 없는 단위는 빼고 이유를 보여 준다:
  `빠짐: 바나나 2 g - 이 음식은 count 기준 값만 있습니다(단위 변환 없음). 1 g 값을 등록: muscle50 nutrition food fact add banana --per 1 g ... --new-unit`.
- 날짜는 bot이 정한다: 표현 없음·"오늘"은 오늘, "어제"는 어제, 그 밖은 `날짜를 정하지 못했습니다. /log로 보내 주세요`.
- 끼니를 말하지 않으면 지금 시각으로 정하고 `(끼니: 지금 시각 기준)`을 보여 준다: [00:00, 10:00) 아침,
  [10:00, 15:00) 점심, [15:00, 24:00) 저녁.
- 같은 날 같은 끼니가 이미 있으면 `--additional`을 붙이고 `이미 기록된 점심(…)이 있어 하나 더 기록합니다.`를 보여 준다.
- "먹을 예정"은 기록하지 않는다.
- 제안의 argv는 만들 때 고정해서 저장한다(자정을 넘겨 `/ok`해도 날짜가 바뀌지 않음). 유효 시간 60분.

### 사진

```text
나:   (제육볶음 정식 사진) 저녁
bot:  이렇게 기록할까요? (저녁, 10-06, 사진 추정)
      1. 일반식 (메모: 제육볶음 정식)
         추정: kcal 700~950, 단백질 30~45 g (estimated)
      기록: /ok_91c0   일반식만 기록(값 없이): /plain_91c0   취소: /no_91c0
```

- 4 MB 이하 중 가장 큰 크기를 받는다. 더 크면 `사진이 너무 큽니다`, 파일(document)로 보낸 이미지는 `사진으로 보내 주세요`.
- 사진인지 메뉴 캡처인지 모호하면 묻는다. 해석에 실패하면 `사진을 해석하지 못했습니다. 일반식으로만 기록할까요?`(값 없음).

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

### 그 밖의 명령(기능이 켜졌을 때만)

- `/llm` 지금 제공자, 모델, 대체 제공자, 시간 상한. `/llm codex|claude`는 채팅에서 바꾸고(상태 파일에 저장, 설정
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
  `telegram-llm text (codex default)`.
- `nutrition repeat`은 추정을 버리고 일반식으로 반복한다(gate 1 D-J). `meal merge`는 추정을 그대로 옮긴다.
- 오늘 합계 줄(LLM 답장에서만): `단백질 확인 120 g + 추정 30~45 g (값 모르는 항목 1개)`. 확인 = `known_subtotal`,
  추정 = 값 없는 항목 범위의 정확한 합, 모르는 값은 0으로 쓰지 않는다. 기록이 없으면 `오늘 기록 없음 (0이 아님)`.

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
| `config\telegram_llm_state.json` | `telegram run` | `/llm` 선택, 열린 제안(정확한 argv). 손상되면 bot이 멈춘다(지우고 다시 시작 가능) |
| `config\telegram_llm_memory.json` | `telegram run` | chat별 요약(300자)과 최근 8턴(각 300자, 24시간) — **메시지 원문 포함** |
| `telegram\history\YYYY-MM.jsonl` | `telegram run` | 대화마다 한 줄, 추가만. 시각, chat, 메시지, 사진 위치, 의도, 제공자·모델, 검증된 LLM 출력, 답장, 제안, 결과(meal ID) — **식단과 대화 원문 포함** |
| `telegram\photos\YYYY-MM\<sha256>.jpg` | `telegram run` | 받은 사진(`keep_photos`) |

- 기록과 사진은 muscle50이 지우지 않는다. 필요하면 직접 지운다. `/forget`과 기억 상한은 기록을 지우지 않는다.
- 콘솔 로그에는 메시지 원문, LLM 답, 사진 URL(bot token 포함)을 남기지 않는다(ASCII, chat ID와 결과 종류만).
- **전송되는 데이터**: 메시지, 사진(캡처 포함), 기억, 코치 가이드, 필요한 muscle50 JSON(질문 주제에 따라 운동 추천,
  영양 상태, InBody 추세; 메뉴 제안에는 오늘 먹은 음식 이름)이 고른 제공자(Anthropic 또는 OpenAI)로 간다. 대체
  제공자를 켜면 두 회사 모두로 갈 수 있다.
- 메뉴 캡처에는 이름이나 사번이 보일 수 있다. **메뉴 부분만 잘라서** 보낸다.

## 코드 위치

- `domain/telegram_llm.py`(LLM 출력 검증·경계, 날짜 표현, 끼니 시각표, 명령 문법, 기억, 기록 줄),
  `domain/telegram_llm_prompt.py`(프롬프트, 고정 규칙, bot 문구), `domain/llm_number_guard.py`, `domain/llm_today_totals.py`,
  `domain/menu_ranking.py`, `domain/llm_settings.py`.
- `application/telegram_llm.py`(`TelegramLlmHandler`), `application/llm_provider.py`(포트), `application/telegram_bot.py`
  (`llm` hook, `_run_command(on_outcome=…)`).
- `infrastructure/llm/`(argv, 프로세스, 실행 파일, 제공자), `infrastructure/telegram/`(설정, 상태, 기억, 기록, 사진, 코치
  가이드, Bot API 사진), `infrastructure/sqlite/food_catalog_reader.py`(읽기 전용 카탈로그).
- `presentation/telegram_llm_replies.py`, `cli.py`(`telegram history`, `_telegram_llm` 연결, A2 플래그, `--new-unit`).

## Known issues / limitations

- **Codex는 `~/.codex/AGENTS.md`(사용자 전역 지시)를 읽는다.** `--ignore-user-config`와 `-c project_doc_max_bytes=0`으로도
  막히지 않았다(구현 단계 확인 4). 그 파일은 사용자 자신의 텍스트 지시일 뿐 도구나 MCP를 켜지 않지만, 응답 언어 같은
  지시가 끼어들 수 있다. 완화: 고정 규칙이 프롬프트에서 그 뒤에 오고 이긴다고 적혀 있으며, 답은 schema와 bot 검증을
  거치고, 모든 쓰기는 확인을 받는다. 기본 제공자는 Claude이고 Codex는 `/llm`이나 설정으로 직접 고른다. `CODEX_HOME`을
  바꾸는 우회는 로그인 파일을 옮기게 되므로 쓰지 않았다. 사용자 결정이 필요하면 후속으로 다룬다.
- Codex에는 "도구 없음" 스위치가 없다. 0.160.0에서 `functions.wait`, `request_user_input`, `collaboration.*`이 남는다.
  cwd에는 사진만 있고, 출력은 검증되고, 쓰기는 확인을 거친다. `--disable` 목록은 버전마다 바뀌므로 업그레이드 뒤 확인을
  다시 한다.
- 한 번에 한 메시지: LLM 호출(최대 timeout, 질문·메뉴 제안은 두 번) 동안 다른 메시지는 기다린다. 응답이 수 초~수십 초.
- 구독 사용량을 쓴다(코딩 한도와 나눠 씀). 개인 자동화가 각 약관의 일반적인 개인 사용인지는 회색지대다.
- 사진 칼로리 추정은 오차가 크다(흔히 ±30~50%). 추정은 범위로만 저장되고 판정에 쓰이지 않는다.
- 숫자 검사의 한계: 작은 정수는 거의 항상 데이터에 있다. 단위를 바꿔 쓴 답(g ↔ kg)은 통과할 수 있다. 한국어 수사
  (`오십`)는 숫자로 보지 않는다.
- 메뉴 순서는 자주 P 모드다: 첫 식사 전, 값 없는 일반식이 있는 날, kcal 목표가 없을 때.
- 식사 수정은 정확한 카탈로그 이름이나 식사의 유일한 item일 때만 대상을 정한다. 그 밖에는 후보만 보여 준다.
  `replace-item`으로는 추정값을 옮길 수 없다. 일반식의 양은 고칠 수 없다(양이 없다).
- 기록 완전성은 best-effort다: 처리 중 강제 종료나 기록 쓰기 실패(콘솔에 `history write failed`)면 그 줄이 빠질 수 있다.
  확인 명령이 예외로 끝나면(드묾) 그 확인 줄도 빠진다. 기억 파일이 손상되면 기억 없이 호출하고 그 파일은 쓰지 않는다.
- `/ok` 뒤의 `오늘 누적`은 `nutrition status/day --json`을 한 번 더 읽어 만든다. 읽지 못하면 그 줄만 빠진다.
- 제안은 만들 때의 중복 확인(`--additional`)을 저장한다. 제안과 확인 사이에 같은 끼니가 기록되면 `nutrition log`의
  기존 거절 문구가 그대로 온다(두 번 기록되지 않는다).
- 날짜는 오늘과 어제만 문장으로 정한다. 그 밖의 날짜는 `/log`로 보낸다.
- 회사 사이트 자동 수집·예약(`cafeteria-auto`)은 v3 이후 후보이고, 회사 IT·보안 허용이 먼저다.
