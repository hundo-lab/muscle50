---
id: general-meal
title: Nutrition General Meal v1
status: integrated
migration: none
output_change: additive
user_gates: [design, integration]
---

# Nutrition General Meal v1

## 목적

- 구내식당, 배달, 집밥 반찬처럼 메뉴나 영양값을 모르는 식사를 **"일반식을 먹었다"는 기록만으로** 남긴다.
  메뉴 이름이나 숫자를 정하지 않아도 된다.
- 왜 필요한가:
  - 지금은 기록하는 모든 item이 영양값이 있는 카탈로그 음식이어야 한다. 영양값을 모두 `unknown`으로 둔 음식은 등록할
    수 없다("at least one of kcal/protein/carbohydrate/fat must be a number").
  - 그래서 일반식은 기록되지 않는다. 그러면 그날 합계가 실제보다 작게 보이고, `status`와 추천이 "단백질 부족" 같은
    **틀린 판단**을 낼 수 있다. 이는 결측을 0으로 보는 것과 같다(`domain-principles` 1절).
  - "일반식" 기록이 있으면 그날 합계가 incomplete로 표시되어, 모르는 값을 근거로 판단하지 않는다.
- 근거: 사용자 결정(2026-10-08). 일반식은 "먹었다는 기록만 있으면 된다. 메뉴가 꼭 정해져 있지 않아도 된다".
  `docs/goals.md` 하루 루프 2단계(먹은 것 기록)와 우선순위 4·5(측정 사이 리뷰, 조정 권고)에 필요한 식단 기록을 쌓는다.

## 범위 / Non-goals

- 범위:
  - 식사 기록에 **일반식 item**을 넣을 수 있다. 일반식 item은 영양값 4개가 모두 모름(unknown)이다.
  - 일반식 item은 혼자 쓸 수도 있고, 카탈로그 음식과 섞어 쓸 수도 있다. 예: 일반식 + 닭가슴살 100 g.
  - 메모를 붙일 수 있다. 예: "구내식당", "제육". 메모는 기록용이고 영양 계산에 쓰지 않는다.
  - CLI: `nutrition log`, `nutrition meal add-item`, `nutrition meal replace-item`에서 `--general [--general-note TEXT]`로
    쓴다. `--general`은 여러 번 쓸 수 있고, `--item`과 함께 명령줄 순서대로 item이 된다. `--general-note`는 그것이 붙는
    `--general` 바로 뒤에 쓴다. `replace-item`은 `--item`과 `--general` 중 정확히 하나를 받는다.
  - Telegram: `/log lunch 일반식`, `/log lunch 일반식 구내식당`, `/log dinner 일반식, 닭가슴살 100 g`.
- Non-goals:
  - 영양값 추정 없음. 메뉴 이름이나 메모로 kcal·단백질을 추측하지 않는다(LLM 추정은 Telegram v2 후보).
  - 일반식 메뉴 카탈로그(김치찌개 1인분 같은 추정값 목록) 없음. 후속 후보로 둔다.
  - 양(1인분, 반 공기 등) 입력 없음. 일반식은 "한 번 먹음"이다.
  - 기존 카탈로그 음식의 등록 규칙 변경 없음. `food add`는 지금처럼 최소 하나는 숫자를 요구한다.

## 명령 예시

```powershell
muscle50 nutrition log --meal lunch --general
muscle50 nutrition log --meal lunch --general --general-note 구내식당
muscle50 nutrition log --meal dinner --general --item chicken-breast 100 g
muscle50 nutrition meal add-item 2026-10-08-dinner-1 --general
muscle50 nutrition log --meal lunch --item chicken-breast 100 g --general --general-note 구내식당 --general
```

마지막 예는 item 1 닭가슴살, item 2 일반식(메모 구내식당), item 3 일반식(메모 없음)이다.

Telegram:

```text
/log lunch 일반식
/log lunch 일반식 구내식당
/log dinner 일반식, 닭가슴살 100 g
```

`nutrition log` text 출력 예시(합성 값, 승인된 설계의 문구. 전체 형식: `docs/nutrition-general-meal.md`):

```text
Recorded meal 2026-10-08-lunch-1.

[lunch] 2026-10-08-lunch-1 (2026-10-08, time not recorded)
  1. 일반식 (general meal; note: 구내식당): nutrition unknown
     source: no nutrition facts
     missing: kcal, protein, carbohydrate, fat
  Meal total: kcal incomplete (no item has a value) | P incomplete (no item has a value) | ...
```

합계 문구는 새 "unknown"이 아니라 기존 문구(`incomplete (no item has a value)` / `incomplete (known items only: N)`)를
그대로 쓴다. `nutrition day`/`status`의 incomplete 목록도 기존 형식으로 일반식을 다른 item처럼 보여 준다. 일반식만을
위한 새 줄은 없다(합성 예시).

```text
  kcal: 2026-10-08-lunch-1 item 1 일반식 (general-meal)
```

JSON에서는 일반식 item에만 마지막 두 key `"general_meal": true`, `"note": <메모 또는 null>`이 붙고, `food_id`는
`"general-meal"`이다.

## 규칙

- 일반식 item:
  - 영양값 4개는 모두 모름이다. 0이 아니다. 그 item이 있는 끼니와 날의 합계는 4개 영양소 모두 incomplete가 된다.
    기존 incomplete 규칙(`known_subtotals`, `incomplete_fields`, `missing_items`)을 그대로 따른다.
  - 양, 단위, fact가 없다(quantity·unit은 NULL, fact row 0개). 단위 변환이나 배수가 없다.
  - 메모는 선택이다. 앞뒤 공백을 지운다. 빈 메모는 메모 없음으로 본다. 최대 100자, 한 줄(줄바꿈·탭 같은 제어 문자
    없음)이다. 어떤 쓰기보다 먼저 검사한다.
  - 한 끼에 일반식 item이 둘 이상이어도 된다. 예: 구내식당 + 배달 반찬.
- 저장:
  - 기존 append-only 원칙과 snapshot 원칙을 지킨다. 기존 meal/item/fact row를 UPDATE/DELETE하지 않는다.
  - 저장 방식(승인된 설계): 시스템이 관리하는 **예약 profile** `general-meal`/`일반식`이다. 이 profile에는 fact도 alias도
    없다("모든 값 unknown인 fact"가 아니다). 일반식 item은 이 profile을 가리키고, 양·단위·fact가 없으며, 메모는
    `serving_description`에 둔다. profile row는 첫 일반식을 쓰는 같은 transaction 안에서 `INSERT OR IGNORE`로 만든다.
    migration은 없다.
  - 사용자가 `food add`로 같은 ID나 이름/alias(`general-meal`, `일반식`, 대소문자 무관)를 등록해 일반식과 헷갈리게 만들 수
    없다. `food show general-meal`/`food fact add general-meal`과 `--item 일반식`도 거부한다. `food list`에는 예약 profile이
    나오지 않는다.
- 영향 범위:
  - `nutrition day`, `status`, `meal show`, `recommend`/`daily`의 nutrition 절, Telegram 요약은 일반식을 기존 incomplete
    규칙대로 표시한다. 일반식 때문에 "부족/남음" 판단이나 행동 안내가 나오지 않는다(이미 incomplete면 판단하지 않는 기존
    규칙과 같다).
  - `meal void/edit/merge`, `repeat`, `add-item`/`remove-item`/`replace-item`이 일반식 item에도 동작한다.
  - 일반식이 없는 기존 기록과 기존 명령의 text·JSON 출력은 byte-identical이다.
- Telegram:
  - `/log <meal>[+] 일반식 [메모]`: 일반식 item 하나. 메모는 그 뒤의 나머지 단어(쉼표 전까지)다.
    CLI로는 `--general [--general-note=<메모>]`가 된다.
  - 쉼표로 카탈로그 음식과 섞는다: `/log dinner 일반식, 닭가슴살 100 g`.
  - "일반식"이라는 단어를 정확히 쓸 때만 일반식이다. 비슷한 말(일반, 밥, 식사)을 추측하지 않는다.
  - 답장 끝의 `취소: /void <meal_id>`는 그대로다.
- 거부:
  - 일반식에 양이나 단위를 붙이면 거부한다(승인된 설계). Telegram `일반식 <num> <unit>`(메모 마지막 두 단어가 숫자와
    단위, 예: `일반식 1 serving`, `일반식 제육 2 pack`)은 `/log` 사용법 답장으로 거부한다. 카탈로그 음식 "일반식"으로도 읽힐
    수 있어 모호하기 때문이다. 추측해서 바꾸지 않는다.
  - 오류가 나면 아무것도 쓰지 않는다.

## 인수 조건

- [ ] AC1: `nutrition log --meal lunch --general`이 일반식 item 하나인 식사를 저장하고, 영양값이 unknown으로 나오며 exit 0이다.
      Telegram `/log lunch 일반식`도 같은 행을 저장한다.
- [ ] AC2: 일반식이 있는 날의 `nutrition day`/`status` 합계는 4개 영양소 모두 incomplete이고, 어떤 값도 0으로 나오지
      않는다. `status`의 행동 안내가 나오지 않는다.
- [ ] AC3: 일반식과 카탈로그 음식을 섞으면, 카탈로그 음식의 값은 `known_subtotals`에 들어가고 합계는 incomplete다.
- [ ] AC4: 메모가 저장되고 `meal show`(text·JSON)에 나온다. 메모는 영양 계산에 영향이 없다.
- [ ] AC5: `meal void/edit/merge`, `repeat`, `add-item`/`remove-item`/`replace-item`이 일반식 item에도 동작한다.
- [ ] AC6: `food add`로 일반식과 같은 ID/이름/alias를 만들 수 없다. 기존 `food add`의 "최소 하나는 숫자" 규칙은 그대로다.
- [ ] AC7: 일반식이 없는 DB에서 기존 nutrition·recommend·daily·Telegram 출력이 byte-identical이다.
- [ ] AC8: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- 일반식은 숫자를 쌓지 않는다. 일반식이 많은 날은 영양 판단이 "알 수 없음"으로 남는다. 이것은 의도된 동작이다.
- 구현·검증에서 확인한 한계(상세: `docs/nutrition-general-meal.md`, `docs/telegram-bot.md` "Known issues / limitations
  (General Meal v1)"):
  - 일반식이 있는 날은 목표가 있는 영양소마다 `indeterminate`(`status`는 `cannot tell yet (incomplete)`, Telegram 요약은
    `알 수 없음`)이고, 부족 판단이나 영양 행동 안내(`recommend` actions)가 나오지 않는다.
  - 메모: 최대 100자, 한 줄. Telegram에서는 쉼표(item 구분자)와 `-`로 시작하는 단어를 메모에 쓸 수 없다.
  - Telegram 회귀: 전에는 `/log lunch 일반식 도시락 1 pack`이 카탈로그 음식 "일반식 도시락"으로 기록되었지만, 이제는
    사용법 답장으로 거부된다. 이름이 `일반식`으로 시작하는 음식은 food ID로 기록한다(2026-10-08 production 카탈로그에는
    없다).
  - `일반식`은 ASCII text 출력 안의 한국어 시스템 이름이다(사용자 음식 이름과 같은 취급).
  - live Telegram 확인은 통합 후 `telegram run` 재시작 뒤 사용자가 한다.
- 이 spec과 달라진 점(gate 2에서 확인, 7개):
  1. 오류 label의 item 번호는 `--item`과 `--general` entry를 함께 센다.
  2. `replace-item`의 메모 오류(E4/E5)에는 `item N:` 접두어가 없다.
  3. `food show`/`food fact add`의 일반식 거부(E2)는 정확한 ID `general-meal`에만 적용된다(`food show 일반식`은 기존
     "no food with id" 오류).
  4. `food list`는 정확히 시스템 모양(이름 `일반식`, fact·alias 없음)인 profile만 숨긴다.
  5. "`--general` 바로 뒤"는 바로 앞 entry 기준이다(token 기준 아님). `--general --json --general-note x`도 받는다.
  6. `--general 구내식당`은 최상위 "unrecognized arguments" 오류(exit 2)다.
  7. entry가 없을 때의 argparse 메시지(`one of the arguments --item --general is required`, exit 2는 같음)와 `--help`가
     바뀌었다.
- 후속 후보:
  - Telegram v2 사진·자유 문장 추정이 일반식 item에 추정 영양값(`estimated`, `language_estimate`)을 붙인다. 확인 후 저장.
  - 일반식 메뉴 카탈로그(대표 메뉴 1인분 추정값, `estimated`).
  - "일반식 N끼" 통계(요약과 측정 사이 리뷰에서 "기록 중 일반식 N끼"). JSON의 `food_id == "general-meal"`로 셀 수 있다.
