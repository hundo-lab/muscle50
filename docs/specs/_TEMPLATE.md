---
# 파일 이름: docs/specs/<id>.md. id는 branch 이름으로도 쓴다(feature/<id>). 소문자-kebab-case로 쓴다.
id: nutrition-example-feature
title: Nutrition Example Feature v1
# draft → (설계 승인) approved → in-progress → verified → integrated. 사람은 draft로만 작성하고, 이후는 /feature가 갱신한다.
status: draft
# none | reserved:NNN. 번호는 /feature(오케스트레이터)만 쓴다. 작성자는 none으로 두고 본문 "규칙"에 schema 필요성을 적는다.
migration: none
# none | additive | breaking. 기존 text/JSON 출력이 바뀌는 정도. additive는 JSON 끝에 key 추가, 새 명령 등이다.
output_change: none
# 이 기능에 필요한 사람 게이트: design(항상) / prod-migration / live-garmin / push(항상)
user_gates: [design, push]
---

# <title>

<!--
기존 기능 문서(docs/nutrition-targets.md, docs/training-recommendation.md 등)와 같은 구조다.
값 예시는 합성 값만 쓴다. 실제 건강 수치와 계정 정보는 쓰지 않는다.
-->

## 목적

- 사용자가 무엇을 할 수 있게 되는지 1~3줄로 쓴다.
- 왜 필요한지(지금 불편한 점, 이전 기능의 Known issue 등)와 근거 문서를 적는다.

## 범위 / Non-goals

- 범위: 이번 버전에 포함하는 것.
- Non-goals: 하지 않는 것을 명시한다. 기존 기능 문서의 "Not implemented"처럼 쓴다.
  - 예: migration 없음 / 기존 출력 변경 없음 / 자동 계산 없음 / LLM 없음

## 명령 예시

```powershell
# text
muscle50 <group> <command> <args>

# JSON
muscle50 <group> <command> <args> --json
```

예상 text 출력(합성 값):

```text
...
```

예상 JSON 출력(합성 값, key 순서 고정):

```json
{
}
```

## 규칙

- 입력 검증과 거부 조건(거부 시 아무것도 쓰지 않음).
- 결측과 unknown 처리. 0으로 채우지 않는다.
- 기존 use case나 reader의 재사용 여부, 기존 출력 불변 범위.
- 저장 방식: 기존 table / JSON 파일 / 새 table(이 경우 왜 기존 구조로 안 되는지).
- 날짜, 시간대, 기본값.

## 인수 조건

<!-- verifier가 하나씩 대조한다. 테스트나 smoke로 확인할 수 있게 구체적으로 쓴다. -->

- [ ] AC1: `<command>`가 <조건>에서 <결과>를 출력하고 exit 0이다.
- [ ] AC2: <거부 조건>이면 exit 1, `오류:` 메시지, DB/파일 변경 없음.
- [ ] AC3: `--json` 출력이 재실행 시 byte-identical이고 text는 ASCII다(사용자 입력 이름 제외).
- [ ] AC4: 기존 `<neighbour commands>` 출력이 byte-identical이다.
- [ ] AC5: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- 이번 버전에서 남기는 한계. 통합 시 CURRENT_STATE "Known issues"로 옮긴다.
- 다음 버전 후보.
