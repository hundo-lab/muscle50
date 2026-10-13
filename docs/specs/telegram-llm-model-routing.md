---
id: telegram-llm-model-routing
title: Telegram LLM Model Routing v2.1
status: integrated
migration: none
output_change: additive
user_gates: [design, integration]
---

# Telegram LLM Model Routing v2.1

## 목적

- 같은 제공자 안에서 **작업에 따라 모델을 고른다.** 글 메시지는 가볍고 빠른 모델(예: Claude Haiku), 사진(음식 사진,
  메뉴 캡처)은 더 강한 모델(예: Claude Sonnet)로 처리한다.
- 가벼운 모델의 결과가 형식 검사를 통과하지 못하면, 더 강한 모델로 **한 번만** 다시 시도한다.
- 근거:
  - Telegram v2(`docs/specs/telegram-llm.md`, `docs/telegram-llm.md`)는 모든 메시지에 구독 사용량을 쓴다. 2026-10-12~13에
    Claude 사용 한도에 걸린 일이 있었다. 대부분인 글 메시지를 가벼운 모델로 돌리면 사용량과 응답 시간이 줄어든다.
  - 가벼운 모델은 작은 한글 메뉴 글씨 읽기와 사진 양 추정이 약할 수 있다. 그 작업만 강한 모델에 맡긴다.
  - 사용자 결정(2026-10-13): "Haiku가 답하고 Sonnet이 검증"(매번 두 번 호출) 대신 작업별 모델 선택 + 형식 실패 시
    재시도로 한다.
- `docs/goals.md` 3절 "채팅으로 묻기"를 매일 쓸 수 있게 하는 운영 개선이다.

## 범위 / Non-goals

- 범위:
  - 제공자별 설정에 `photo_model`, `retry_model`을 더한다. 기존 `model`은 글 메시지용 모델이다.
  - 호출마다 쓸 모델을 정하는 결정적 규칙, 형식 실패 시 같은 제공자 안 재시도 한 번.
  - `/llm` 답장에 세 모델을 보여 준다. 대화 기록(history)에 실제로 답한 모델과 재시도 여부를 남긴다.
  - 기본값 변경: Claude는 `model: "haiku"`, `photo_model: "sonnet"`, `retry_model: "sonnet"`. Codex는 셋 다 `null`
    (Codex 기본 모델, 재시도 없음).
- Non-goals:
  - 두 모델이 같은 메시지를 모두 처리해 비교·검증하는 방식은 하지 않는다.
  - 재시도는 형식·검증 실패(`bad_output`)에만 한다. 시간 초과, 실행 파일 없음, 로그인 문제는 지금처럼 대체 제공자
    규칙(기본 꺼짐)을 따른다.
  - 답의 내용(숫자 검사 실패 등)을 이유로 다른 모델을 부르지 않는다. 숫자 검사 실패는 지금처럼 기존 명령 답장으로
    대신한다.
  - migration 없음. 다른 명령의 출력 변경 없음.

## 명령 예시

설정 `config\telegram_llm.json`(합성 예시):

```json
{
  "provider": "claude",
  "claude": {"model": "haiku", "photo_model": "sonnet", "retry_model": "sonnet"},
  "codex": {"model": null, "photo_model": null, "retry_model": null}
}
```

`{}`이면 위 기본값이다. `photo_model`이 `null`이면 사진도 `model`로, `retry_model`이 `null`이면 재시도하지 않는다.

Telegram(합성 값, 정확한 문구는 설계에서 정한다):

```text
/llm
LLM: claude · 글 haiku · 사진 sonnet · 형식 실패 시 sonnet으로 한 번 더 · 대체 제공자: 없음 · 시간 상한 90초
```

`muscle50 telegram history`(합성, 형식은 설계에서 정한다):

```text
2026-10-13 12:31 +09:00 chat 111 photo intent=menu claude/sonnet ok
2026-10-13 12:40 +09:00 chat 111 text intent=meal_log claude/haiku bad_output -> claude/sonnet ok
```

## 규칙

- 모델 선택(결정적, 테스트로 고정):
  - 사진이 붙은 호출(음식 사진, 메뉴 캡처 해석): `photo_model`, 없으면 `model`.
  - 그 밖의 모든 호출(글 해석, 질문 답변, 메뉴 제안, 식사 수정, 잡담): `model`.
  - 같은 메시지의 두 번째 호출(질문 답변, 메뉴 제안)은 첫 호출과 같은 규칙으로 정한다.
- 재시도:
  - 첫 호출 결과가 `bad_output`(JSON 아님, 스키마·범위 검증 실패)이고 `retry_model`이 있고 첫 호출 모델과 다르면,
    같은 제공자로 `retry_model`을 써서 같은 입력으로 **한 번** 다시 호출한다.
  - 재시도도 실패하면 지금의 실패 처리(대체 제공자가 켜져 있으면 한 번, 아니면 명령어 안내)를 따른다.
  - 대체 제공자로 넘어간 호출은 그 제공자의 모델 규칙(글/사진)을 쓰고, 그 제공자의 `retry_model` 재시도도 한 번까지
    할 수 있다. 한 메시지에서 한 호출 단계가 실제 CLI를 부르는 횟수는 최대 4번이다(주 2, 대체 2).
  - 재시도·대체 호출도 v2의 격리 옵션, 시간 상한, 임시 폴더 규칙을 그대로 따른다.
- 설정 검증:
  - `photo_model`, `retry_model`은 `model`과 같은 규칙(`null` 또는 `[A-Za-z0-9._:-]{1,64}`)이다. 모르는 key는 거부한다.
  - 기존 v2 설정 파일(`model`만 있는 것)은 그대로 읽힌다. 이때 빠진 key는 위 기본값을 쓴다. 기본값 변경으로 Claude 글
    메시지 모델이 `sonnet`에서 `haiku`로 바뀌는 점을 문서에 적는다.
  - `/llm claude|codex|default`의 동작은 그대로다(제공자만 바꾼다).
- 기록:
  - history 항목에 실제로 답한 모델(재시도 뒤 모델 포함)과 재시도 여부를 남긴다. 기존 항목은 그대로 읽힌다. 새 key는
    JSON 끝에 더한다(additive).
  - 콘솔에는 제공자, 모델, 결과 종류, 걸린 시간만 남긴다(v1·v2 규칙 그대로, 메시지 원문 없음).
- 테스트:
  - 가짜 제공자 실행기로 argv의 `--model`/`-m` 값을 확인한다. 실제 CLI를 부르지 않는다.

## 인수 조건

- [ ] AC1: 설정이 `{}`이면 Claude 글 메시지는 `--model haiku`, 사진 메시지는 `--model sonnet`으로 실행된다.
- [ ] AC2: `photo_model: null`이면 사진도 `model`로, `retry_model: null`이면 `bad_output`에서 재시도하지 않는다.
- [ ] AC3: 첫 호출이 `bad_output`이면 `retry_model`로 한 번만 다시 호출하고, 성공하면 그 결과로 기존 흐름(제안, 답변 등)이
      그대로 이어진다. 재시도도 실패하면 기존 실패 처리와 같은 답장이 가고 아무것도 쓰지 않는다.
- [ ] AC4: 시간 초과, 실행 파일 없음 같은 실패에서는 같은 제공자 재시도를 하지 않는다(대체 제공자 규칙만 적용).
- [ ] AC5: `retry_model`이 첫 호출 모델과 같으면 재시도하지 않는다.
- [ ] AC6: Codex 설정에도 같은 규칙이 적용된다(`-m` 값 확인, `null`이면 `-m` 없음).
- [ ] AC7: `/llm` 답장이 글·사진·재시도 모델을 보여 준다. history와 `muscle50 telegram history`(text, `--json`)에 실제 모델과
      재시도 여부가 나오고, 이 기능 전에 쓰인 history 항목도 오류 없이 읽힌다.
- [ ] AC8: 기존 v2 설정 파일(`model`만 있음)이 그대로 읽히고, 잘못된 `photo_model`/`retry_model` 값과 모르는 key는 값을
      출력하지 않고 거부된다.
- [ ] AC9: v2의 격리 argv(Claude `--tools "" --safe-mode --strict-mcp-config --disable-slash-commands
      --no-session-persistence`, Codex `--ignore-user-config` 등)가 재시도 호출에도 그대로다.
- [ ] AC10: LLM이 꺼져 있을 때와 기존 명령 답장, 기존 CLI 출력은 byte-identical이다(`/llm` 답장과 history 출력은 예외).
- [ ] AC11: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- 사진 메시지는 강한 모델을 쓰므로 그만큼 사용량을 쓴다.
- 재시도는 형식 실패만 잡는다. 형식은 맞지만 내용이 틀린 답(메뉴를 잘못 읽음 등)은 사용자가 확인 단계에서 고친다.
- 대화 기록(history)은 메시지의 마지막 LLM 호출만 설명한다. 질문·메뉴 추천처럼 호출이 둘인 메시지에서 첫 호출의 재시도는
  콘솔 로그에만 보인다.
- 최악의 경우 호출 단계마다 CLI를 최대 4번 돌린다. 호출이 둘인 메시지는 최대 8번(90초 제한 기준 약 12분)이고 그동안 다른
  메시지는 기다린다. 대체 제공자는 기본 꺼짐이다.
- 재시도가 실패한 뒤 대체 제공자가 답하면 봇 `/history` 머리말이 `codex 기본 (재시도, 처음 haiku 형식 실패)`처럼 어색하게
  읽힌다. `telegram history` 텍스트는 실제 사슬을 보여 준다.
- `/llm`은 대체 제공자의 모델을 보여 주지 않는다.
- 저장되는 추정 근거(`--general-estimate-ref`)는 이제 답한 모델 이름이다(글은 `claude haiku`). 기존 행은 바뀌지 않는다.
- Claude 사용 한도 문구가 일반 결과 텍스트로 오면 형식 실패로 세어 한 번 재시도한다(가짜 실행기로만 확인).
- `model`만 적은 v2 파일은 사진을 sonnet으로 돌린다(예: `model: "opus"`면 사진도 opus가 아니다). 사용자의 실제
  `config	elegram_llm.json`은 읽지 않았다.
- 후속 후보: 사용 한도에 걸렸을 때 자동으로 다른 제공자로 넘기기, 작업별 모델 사용량 통계.
