---
id: general-meal
title: Nutrition General Meal v1
status: draft
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
  - CLI: `nutrition log`, `nutrition meal add-item`, `nutrition meal replace-item`에서 쓸 수 있다.
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
```

Telegram:

```text
/log lunch 일반식
/log lunch 일반식 구내식당
/log dinner 일반식, 닭가슴살 100 g
```

`nutrition log` text 출력 예시(합성 값, 정확한 문구는 설계에서 정한다):

```text
Recorded meal 2026-10-08-lunch-1.

[lunch] 2026-10-08-lunch-1 (2026-10-08, time not recorded)
  1. 일반식 (general meal; note: 구내식당): nutrition unknown
  Meal total: kcal unknown | P unknown | C unknown | F unknown
```

`nutrition status`에서는 그날 합계가 incomplete로 나온다. 일반식이 있다는 사실이 보인다(합성 예시).

```text
  kcal          incomplete (known items only: 450); ... cannot tell yet (incomplete)
Incomplete: a general meal (2026-10-08-lunch-1 item 1) has no nutrition values.
```

## 규칙

- 일반식 item:
  - 영양값 4개는 모두 모름이다. 0이 아니다. 그 item이 있는 끼니와 날의 합계는 4개 영양소 모두 incomplete가 된다.
    기존 incomplete 규칙(`known_subtotals`, `incomplete_fields`, `missing_items`)을 그대로 따른다.
  - 양은 없다(또는 "1회"로 고정). 단위 변환이나 배수가 없다.
  - 메모는 선택이다. 앞뒤 공백을 지운다. 빈 메모는 메모 없음으로 본다. 길이 상한은 설계에서 정한다.
  - 한 끼에 일반식 item이 둘 이상이어도 된다. 예: 구내식당 + 배달 반찬.
- 저장:
  - 기존 append-only 원칙과 snapshot 원칙을 지킨다. 기존 meal/item/fact row를 UPDATE/DELETE하지 않는다.
  - 저장 방식은 설계에서 정한다. 예: 시스템이 관리하는 예약 카탈로그 음식(모든 값 unknown) + 그 음식만 예외 허용, 또는
    item 단위 표시. 가능하면 migration 없이 한다. migration이 필요하면 설계에서 이유를 적고 번호는 orchestrator가 예약한다.
  - 사용자가 `food add`로 같은 ID나 이름을 등록해 일반식과 헷갈리게 만들 수 없어야 한다.
- 영향 범위:
  - `nutrition day`, `status`, `meal show`, `recommend`/`daily`의 nutrition 절, Telegram 요약은 일반식을 기존 incomplete
    규칙대로 표시한다. 일반식 때문에 "부족/남음" 판단이나 행동 안내가 나오지 않는다(이미 incomplete면 판단하지 않는 기존
    규칙과 같다).
  - `meal void/edit/merge`, `repeat`, `add-item`/`remove-item`/`replace-item`이 일반식 item에도 동작한다.
  - 일반식이 없는 기존 기록과 기존 명령의 text·JSON 출력은 byte-identical이다.
- Telegram:
  - `/log <meal>[+] 일반식 [메모]`: 일반식 item 하나. 메모는 그 뒤의 나머지 글자다.
  - 쉼표로 카탈로그 음식과 섞는다: `/log dinner 일반식, 닭가슴살 100 g`.
  - "일반식"이라는 단어를 정확히 쓸 때만 일반식이다. 비슷한 말(일반, 밥, 식사)을 추측하지 않는다.
  - 답장 끝의 `취소: /void <meal_id>`는 그대로다.
- 거부:
  - 일반식에 양이나 단위를 붙이면(`일반식 1 serving`) 형식 오류로 거부할지, 무시할지는 설계에서 정한다. 추측해서 바꾸지 않는다.
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
- 후속 후보:
  - 일반식 메뉴 카탈로그(대표 메뉴 1인분 추정값, `estimated`).
  - Telegram v2: 자유 문장 + LLM 추정(`language_estimate`), 확인 후 저장.
  - 일반식 비율 통계(측정 사이 리뷰에서 "기록 중 일반식 N끼").
