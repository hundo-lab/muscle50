---
id: food-name-lookup
title: Nutrition Food Name Lookup v1
status: integrated
migration: none
output_change: none
user_gates: [design, integration, push]
---

# Nutrition Food Name Lookup v1

## 목적

- 식사를 기록할 때 food ID 대신 음식 이름이나 alias로 item을 지정할 수 있게 한다.
  예: `--item chicken-breast 200 g` 대신 `--item 닭가슴살 200 g`.
- 근거: docs/HANDOFF.md(동결) Meal Repeat v1 "Recommended next action"의 첫 후보("`--item`에서 이름/alias 조회,
  alias가 다른 food ID와 겹칠 수 있어 모호성 규칙 필요"). 지금 alias는 중복 검사에만 쓰이고 `--item`은 food ID만 받는다.
- `docs/goals.md` 우선순위 3: 매일 식사 기록의 마찰을 줄여 식단 데이터를 쌓는다. 후속 측정 사이 리뷰와 조정 권고에 그
  데이터가 필요하다.

## 범위 / Non-goals

- 범위: `--item <food> QTY UNIT`를 받는 세 명령 `nutrition log`, `nutrition meal add-item`, `nutrition meal replace-item`.
  `<food>`는 food ID, 음식 이름, alias 중 하나다.
- Non-goals:
  - migration 없음.
  - fuzzy·부분 일치·오타 보정·추천 없음(추측 금지).
  - `food show`/`food fact add`의 이름 조회 없음(후속 후보).
  - 자유 문장 parser 없음.
  - `nutrition repeat` 변경 없음(원본 food ID를 그대로 쓴다).

## 명령 예시

```powershell
muscle50 nutrition log --meal breakfast --item 닭가슴살 200 g --item egg 2 count
muscle50 nutrition meal add-item 2026-10-02-breakfast-1 --item "현미 햇반" 1 pack
muscle50 nutrition log --meal lunch --item 닭가슴살 150 g --json
```

text와 JSON 출력은 같은 food ID로 기록했을 때와 byte 단위로 같다. 저장되는 것은 해석된 food ID다.

모호할 때(합성 예시):

```text
오류: --item 1 'egg' is ambiguous: it is the ID of food egg and a name/alias of food quail-egg. Use the food ID. Nothing was changed.
```

## 규칙

- 해석 순서:
  1. `<food>`가 food ID와 정확히 같으면(대소문자 구분) 그 음식이다.
  2. 아니면 앞뒤 공백을 제거한 뒤, 이름이나 alias와 대소문자를 무시하고 정확히 같은 음식이다.
     기존 `FoodNutritionRepository.search`(SQLite `LOWER()`, ASCII 대소문자만 무시)를 그대로 재사용한다.
     카탈로그 규칙(`AddFood`가 같은 `search`로 중복을 거부)상 결과는 최대 1개다. CLI 밖에서 만든 데이터 때문에
     2개 이상이 나오면 모호한 입력으로 거부한다.
- 모호성: 한 `<food>`가 음식 A의 ID이면서 다른 음식 B(A≠B)의 이름이나 alias와도 같으면 거부한다. 두 음식을 모두 보여 주고
  ID로 지정하라고 안내한다.
- 일치하는 음식이 없으면 기존 "unknown food"와 같은 계열의 오류로 거부한다. 비슷한 이름을 제안하지 않는다.
- 거부는 all-or-nothing이다. `--item`이 여러 개일 때 하나라도 실패하면 아무것도 쓰지 않는다(기존 동작과 같다).
- 저장 결과(item의 `food_profile_id`, `food_name`, snapshot fact, `original_text`)는 해석된 ID를 직접 입력했을 때와 같다.
  기존 ID 입력의 출력과 저장 내용은 byte 단위로 그대로다.
- 이름에 공백이 있으면 셸에서 따옴표로 감싼다. 이 점을 help와 기능 문서에 적는다.

## 인수 조건

- [ ] AC1: 이름 입력과 alias 입력(대소문자를 다르게 써도)으로 기록한 식사가 food ID로 기록한 식사와 저장 row, text, JSON 모두
      같다. 세 명령(log, add-item, replace-item) 모두 해당한다.
- [ ] AC2: ID와 다른 음식의 이름/alias가 겹치면 exit 1이고, 메시지에 두 food ID가 나오며, DB가 변하지 않는다.
- [ ] AC3: 일치하는 음식이 없으면 exit 1이고 DB가 변하지 않는다. 부분 일치("닭가슴")는 거부된다.
- [ ] AC4: 기존 ID 입력 테스트가 수정 없이 통과하고, `nutrition day`/`status` 출력이 변하지 않는다.
- [ ] AC5: 품질 게이트 4개를 통과한다.

## 한계 / 후속 후보

- `food show <이름>`, `food fact add <이름>`의 이름 조회.
- `original_text`에 사용자가 입력한 원래 토큰을 남길지(지금은 해석된 ID 기준으로 같게 저장한다).
- 다른 음식의 이름/alias와 같은 food ID는 `--item`에서 ID로 쓸 수 없다(항상 모호성 거부). 이름/alias는 수정할 수 없어
  계속 그렇다. 후속 후보: `food add`가 새 ID와 기존 이름/alias, 새 이름/alias와 기존 ID의 충돌도 거부.
- 모호성 오류 문구는 위 예시의 "Use the food ID."를 빼고 "No food is chosen automatically."로 끝난다(승인된 plan D1:
  위 경우 ID 지정이 통하지 않으므로).
- 대소문자가 다르거나 앞뒤 공백이 있는 ID는 ID로 보지 않는다(이름/alias로만 비교). 대소문자 무시는 ASCII만(SQLite `LOWER()`).
- 모호한 토큰은 중복 식사/없는 식사/없는 item 검사보다 먼저 거부된다(일치 없는 토큰은 기존 순서 그대로).
- `--item` 하나마다 catalog 읽기가 두 번 늘어난다.
