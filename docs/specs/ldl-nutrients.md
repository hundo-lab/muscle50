---
id: ldl-nutrients
title: LDL Nutrients - Saturated Fat and Fiber v1
status: draft
migration: none
output_change: additive
user_gates: [design, integration, prod-migration]
---

# LDL Nutrients - Saturated Fat and Fiber v1

## 목적

- 식사 기록에 **포화지방(g)**과 **식이섬유(g)**를 선택 값으로 남기고, 하루 합계를 사용자가 정한 목표와 비교해 보여 준다.
  한 끼에 포화지방이 많으면 **조언으로만** 알린다.
- 근거:
  - 사용자 건강검진에서 LDL-C가 높게 나왔다(값은 적지 않는다). 승인된 근거 문서
    `docs/evidence/training-nutrition-evidence.md` 7절(LDL-01..11)의 적용 메모가 "포화지방 필드가 생기면 < 7 % 에너지를
    결정적으로 쓸 수 있다"(LDL-05), "식이섬유 필드가 생기면 ≥ 25 g/일을 결정적으로 쓸 수 있다"(LDL-08)고 적어 두었다.
    지금은 음식 영양값이 kcal·단백질·탄수·지방 4개뿐이라 둘 다 "조언만"에 머문다. 후속 B1(포화지방), B2(식이섬유)다.
  - 근거 문서 머리말: 지질 항목은 진단이 아니고 자동 판정·경고 등급을 만들지 않는다. 그래서 이 기능은 "내가 정한 목표 대비
    상태"만 보여 주고 위험도나 LDL-C 값은 다루지 않는다.
- `docs/goals.md` 3절 하루 흐름 2단계(먹은 것을 기록 → 남은 양 확인)에 붙는 건강 보조 기능이다. 우선순위 4·5(측정 사이 리뷰,
  조정 권고)를 바꾸지 않고, 운동 계획에는 아무 영향이 없다(domain-principles 6).

## 범위 / Non-goals

- 범위:
  1. **저장**: 포화지방 `saturated_fat_g`, 식이섬유 `fiber_g`를 nutrition fact의 **선택 영양소**로 저장한다. 점 값과 추정 범위
     (min/max) 모두. 값이 없으면 unknown이고 0이 아니다. 기존 fact·meal은 모두 unknown이 된다. migration이 필요하다(규칙 1).
  2. **값이 들어오는 길**:
     - 카탈로그 음식(`nutrition food add`, `nutrition food fact add`)에 선택 플래그 `--satfat`, `--fiber`(이름은 설계에서 확정).
       코드에 "food preset"이라는 별도 개념은 없다. 자주 먹는 음식을 등록한 카탈로그 음식이 preset 역할을 하며, 식사 기록 때
       기존 snapshot 규칙으로 값이 복사된다.
     - 일반식 추정 `--general-estimate SOURCE:...`에 `satfat=MIN-MAX`, `fiber=MIN-MAX` 키.
     - (단계 B, 설계에서 같은 기능에 넣을지 결정: D7) Telegram LLM 식사 추정과 라벨 값에 선택 범위 두 개.
  3. **보여 주기**: `nutrition day`, `nutrition meal show`, `food show/list`에 항목·끼니·하루 값(완전/불완전, known subtotal).
     `nutrition status`에 새 블록: 포화지방 상한·식이섬유 하한 대비 상태. 근거 ID와 함께.
  4. **목표**: `nutrition target set`에 포화지방(에너지 %로 상한)과 식이섬유(g 하한) 목표. **사용자가 정한 값만** 쓰고,
     출력에 근거 문서의 참고값(LDL-05 < 7 %, LDL-08 ≥ 25 g)을 나란히 적는다. 자동으로 목표를 만들지 않는다.
  5. **끼니 조언**: "이 끼니는 포화지방이 많다"는 한 줄 메모. 조언일 뿐이고 목표·운동·메뉴 순서를 바꾸지 않는다.
- Non-goals:
  - LDL-C·총콜레스테롤 같은 검사값 입력, 지질 분류(LDL-01), 위험도 판정과 목표 LDL(LDL-02..04), 스타틴·의사 상담 판단.
  - 식이 콜레스테롤(LDL-07), 트랜스지방(LDL-05: 숫자 미확인), 수용성 섬유(LDL-08의 7–13 g), 식물성 스테롤(LDL-09) 필드.
  - 총지방 에너지 비율 목표(LDL-05 KSoLA ≤ 30 %)와 탄수 비율. 지방 g 목표는 이미 사용자 설정으로 있다.
  - 포화지방·섬유 값을 이름이나 다른 영양소에서 추정하거나 0으로 채우는 일. 이미 기록된 끼니의 snapshot 갱신.
  - 운동 추천·계획 변경, `recommend`/`daily`의 운동 부분 변경, 메뉴 순서 규칙(`domain/menu_ranking.py`) 변경.
  - 조언이 목표 파일을 바꾸는 일. 목표 이력.
  - `src/muscle50/schemas/nutrition_meal_v1.schema.json`(교환 schema) 변경. 이 schema는 `infrastructure/nutrition_serialization.py`와
    그 테스트만 쓰고 CLI JSON 출력의 계약이 아니다(설계에서 다시 확인). 공공 식품 DB 조회.

## 명령 예시

```powershell
# 카탈로그 음식: 선택 플래그. 빼면 unknown (아래 숫자는 문법 예시, 실제 라벨 값을 넣는다)
muscle50 nutrition food add --id syn-oats --name SynOats --per 40 g --kcal 150 --protein 5 --carbs 27 --fat 3 --satfat 0.5 --fiber 4 --source nutrition_label --accuracy exact
muscle50 nutrition food fact add syn-rice --per 1 pack --kcal 300 --protein 5 --carbs 66 --fat unknown --fiber 1.2 --source nutrition_label --accuracy exact

# 일반식 추정 범위
muscle50 nutrition log --meal dinner --general --general-note SynPorkBBQ --general-estimate language_estimate:kcal=800-1100,protein=35-50,fat=50-70,satfat=15-25

# 목표 (사용자 설정)
muscle50 nutrition target set satfat --max-energy-percent 7
muscle50 nutrition target set fiber --minimum 25

muscle50 nutrition status --date 2026-11-05
muscle50 nutrition status --date 2026-11-05 --json
```

예상 `nutrition status` text: 기존 줄은 그대로이고 끝에 블록이 붙는다(합성 값, kcal 목표 2400 exact, 정확한 문구는 설계에서 정한다):

```text
LDL-related nutrients (your targets; advice only, not a diagnosis):
  Saturated fat  incomplete (known items only: 19.4 g (estimated)); limit < 7 % of energy [user setting; LDL-05 reference < 7 %]
                 = under 18.7 g at your kcal target 2400 [design: 9 kcal/g]: above limit (the known items alone exceed it)
  Fiber          17.5 g (estimated); target >= 25 g/day [user setting; LDL-08 reference >= 25 g]: below target, 7.5 g to go
    foods that add fiber: oats, mixed grains, beans, tofu/soy, nuts [LDL-08, LDL-11; advice only]
  Unknown, not 0: saturated fat: 2026-11-05-lunch-1 item 2 SynRice (syn-rice)
  Meal note: 2026-11-05-dinner-1 is high in saturated fat: 13 g, 70 % of today's limit [design: user setting 50 %]
```

불완전한 날의 다른 경우(같은 목표):

```text
  Saturated fat  incomplete (known items only: 9.8 g); limit < 7 % of energy [...]: cannot tell yet (incomplete)
  Fiber          incomplete (known items only: 26 g); target >= 25 g/day [...]: target reached (the known items alone reach it)
```

`nutrition day`의 끼니에 붙는 줄(값이 하나라도 있는 끼니만):

```text
  Meal total: kcal 1050 (estimated) | P 42 g (estimated) | C 60 g | F 65 g (estimated)
  LDL nutrients: sat fat 13 g (estimated) | fiber incomplete (known items only: 2 g)
```

예상 JSON(합성 값, 기존 key 뒤 마지막 key로 추가, key 이름은 설계에서 확정):

```json
{
  "...": "existing keys unchanged",
  "ldl_nutrients": {
    "advice_only": true,
    "saturated_fat_g": {
      "target": {"kind": "max_energy_percent", "value": "7", "reference": {"id": "LDL-05", "value": "7"}},
      "limit_g": "18.66666666666666666666666667",
      "limit_basis": {"calories_kcal_target": "2400", "kcal_per_g": "9"},
      "status": "above_limit",
      "complete": false,
      "estimated": true,
      "consumed": null,
      "known_subtotal": "19.4",
      "remaining_to_limit": null,
      "excess": null,
      "missing_items": [{"meal_id": "2026-11-05-lunch-1", "sequence": 2, "food_id": "syn-rice", "food_name": "SynRice"}]
    },
    "fiber_g": {
      "target": {"kind": "minimum", "value": "25", "reference": {"id": "LDL-08", "value": "25"}},
      "status": "below_target",
      "complete": true,
      "estimated": true,
      "consumed": "17.5",
      "known_subtotal": "17.5",
      "remaining": "7.5",
      "missing_items": []
    },
    "meal_notes": [
      {"meal_id": "2026-11-05-dinner-1", "code": "high_saturated_fat", "saturated_fat_g": "13", "share_of_day_limit": "0.6964285714285714285714285714", "threshold": {"kind": "user_setting", "value": "50"}}
    ]
  }
}
```

## 규칙

1. **저장과 migration** — **migration: reserve needed.** 번호는 오케스트레이터가 예약한다(`feature_state.py reserve-migration`).
   작성자는 고르지 않는다.
   - 이유: `nutrition_facts`(migration 003)는 영양소마다 고정 열(점 값 + min/max)을 갖고, 트리거로 append-only다. 새 영양소를
     담을 곳이 없다. 목표 파일은 JSON이라 migration이 필요 없다.
   - 저장 방식은 설계에서 고른다(D1):
     - (a) `nutrition_facts`에 `ALTER TABLE ADD COLUMN`으로 `saturated_fat_g`, `fiber_g`, `min_/max_` 쌍(6열, 모두 NULL 허용).
       옛 행은 NULL = unknown. 기존 table CHECK("4개 영양소 중 하나는 값")은 그대로 남는다.
     - (b) 새 append-only 표(예: fact_id별 영양소 행). 기존 표를 바꾸지 않는 008/009의 방식이다. 콜레스테롤 같은 후속 영양소도
       같은 표에 넣을 수 있다.
   - 어느 쪽이든: append-only(update/delete 트리거), 점 값과 범위 쌍 규칙(min과 max는 같이 있거나 같이 없음, min ≤ max,
     `exact`면 범위 없음)은 기존 4개 영양소와 같다. `add-migration` skill의 템플릿을 따른다.
   - 기록 시점 snapshot은 새 값도 그대로 복사하고, supersession은 영양소별로 판단한다(포화지방만 고친 fact는 포화지방만 대체).
2. **입력 검증**(거부하면 exit 1, `오류:`, 아무것도 쓰지 않음):
   - 값은 기존과 같은 canonical decimal 또는 `unknown`. 플래그를 빼면 `unknown`이다(기존 4개 플래그는 계속 필수).
   - 한 fact 안에서 포화지방이 총지방보다 크면 거부(둘 다 값이 있을 때. 범위면 satfat min > fat max) `[design: 포화지방은
     총지방의 일부]`. 섬유와 탄수는 비교하지 않는다(라벨마다 탄수에 섬유가 포함되는지가 다를 수 있다: 열린 질문 4).
   - 포화지방·섬유만 값이 있는 fact나 일반식 추정은 거부 `[design]`(기존 "4개 중 하나는 값" 규칙을 그대로 둔다).
   - `food fact add`: 현재 fact가 아는 포화지방·섬유를 `unknown`(또는 생략)으로 주면 기존 4개 영양소와 같은 이유로 거부한다.
     그래서 이미 있는 음식에 포화지방을 채우려면 4개 값을 다시 적은 새 버전을 더한다(한계).
3. **결측은 0이 아니다**: 하루·끼니 합계는 모든 항목에 값이 있을 때만 `consumed`이고, 아니면 `known_subtotal`(하한)과
   `missing_items`를 보여 준다. 기존 데이터는 모두 unknown이므로 처음에는 거의 모든 날이 불완전하다.
4. **상태 판정**(Decimal, 반올림 없이 판단하고 표시만 0.1):
   - 포화지방 상한 `L`: 판정은 `consumed < L`이면 `within_limit`, `consumed ≥ L`이면 `above_limit`(기준이 "< 7 %"라서 같으면
     넘은 것). 불완전하면 `known_subtotal ≥ L`일 때만 `above_limit`(complete false, excess null), 나머지는 `indeterminate`.
     불완전한 날에 "아래"라고 말하지 않는다.
   - 식이섬유 하한 `M`: `consumed ≥ M`이면 `target_reached`, 작으면 `below_target`과 `remaining`. 불완전하면
     `known_subtotal ≥ M`일 때만 `target_reached`(missing은 더할 뿐이라 확실), 나머지는 `indeterminate`.
   - 끼니가 없는 날은 `no_intake_logged`, 목표가 없으면 `no_target`(값은 보여 줌).
   - 상태는 기존처럼 점 값으로만 판단하고 추정 범위는 판정에 쓰지 않는다(`nutrition-targets.md`와 같다).
5. **기준과 근거 ID**(사용자 원칙: 모든 기준에 근거 ID 또는 `[design]`/사용자 설정):
   - 포화지방 `< 7 %` 에너지: `[LDL-05]`(KSoLA, ESC 고콜레스테롤혈증 공통). 충돌: ESC 일반 `< 10 %`도 LDL-05이고, 사용자가
     10을 고르면 규칙 6대로 한 줄 덧붙인다. ACC/AHA는 숫자 없이 "대체"다.
   - 식이섬유 `≥ 25 g/일`: `[LDL-08]`(KSoLA, ESC 25–40 g의 아래 끝). 40은 상한이 아니므로 상한으로 쓰지 않는다.
   - 섬유를 늘리는 음식 예(귀리, 잡곡, 콩류, 두부·콩, 견과): `[LDL-08, LDL-11]`, 조언만.
   - g ↔ kcal 환산 `9 kcal/g`: 근거 문서의 행이 아니다. LDL-05 메모의 계산 예(2,400 kcal → 18.7 g)와 기존 상수
     `ATWATER_FAT`(`domain/telegram_llm_check.py`)에만 있다. `[design: 9 kcal/g]`로 적는다(열린 질문 2).
   - 근거 문서에서 확인 못 한 숫자(AHA < 5–6 %, 트랜스지방 < 1 %: "확인 못 한 것" 11·12)는 쓰지 않는다.
   - 효과 크기(LDL-06의 "5 %p 줄이면 약 8–10 mg/dL")는 출력에 넣지 않는다 `[design]`. 개인 수치처럼 읽힐 수 있다.
6. **목표 모델**(사용자 설정만, domain-principles 6 "목표는 사용자가 정한다"):
   - 새 kind: 포화지방 `max_energy_percent`(0 < 값 < 100), 섬유 `minimum`(값 > 0). 0과 음수는 거부, `--unset`으로 지운다.
   - 플래그 조합: `satfat`은 `--max-energy-percent | --unset`만, `fiber`는 `--minimum | --unset`만 받는다. 기존 4개 영양소는 새
     kind를 거부하고(`--exact`/`--range`/`--unset` 그대로), 새 두 영양소는 `--exact`/`--range`를 거부한다(exit 1, 아무것도 쓰지
     않음). `target show [--json]`은 새 목표를 기존 4개 뒤에 보인다.
   - 출력은 언제나 사용자 값과 근거 참고값을 함께 적는다. 사용자 값이 참고값과 달라도 그대로 쓴다(경고 없음). 포화지방
     참고값은 언제나 LDL-05의 `7`(KSoLA·ESC 고콜레스테롤혈증)이고, 사용자 값이 `10`이면 ESC 일반 `< 10 %`도 LDL-05라는 문구를
     한 줄 덧붙인다(JSON `reference`는 `7` 그대로). 섬유 참고값은 LDL-08의 `25`다.
   - `nutrition_targets.json`: 새 목표를 하나라도 정했을 때만 schema 2, 아니면 schema 1 그대로(byte 단위로 같다. aerobic-guide D2와
     같은 방식). schema 2 파일은 이전 빌드가 거부한다(한계).
   - 포화지방 g 상한 `L`의 분모는 설계에서 정한다(D2). 추천: **kcal 목표 기준** `L = kcal 목표 × % / 100 / 9`(불완전한 날에도
     계산된다). kcal 목표가 없으면 상태는 `no_kcal_target`이고 known subtotal만 보인다. kcal 목표가 범위이면 어느 끝을 쓸지 D3.
     kcal과 포화지방이 모두 완전한 날에는 "기록된 열량의 X %"를 정보로만 덧붙일 수 있다(판정에는 쓰지 않음).
7. **끼니 조언**: 근거 문서에 끼니 단위 포화지방 기준이 **없다**(열린 질문 1). 그래서 기준은 `[design: user setting]`이다(D4).
   추천: "그 끼니의 포화지방이 오늘 상한 `L`의 N % 이상"(N은 사용자가 정하고 기본값 없음, 설정하지 않으면 메모 없음). 그 끼니의
   포화지방이 완전할 때만 판단한다. 메모는 텍스트 한 줄과 JSON `meal_notes`뿐이고, 목표 파일·메뉴 순서·운동 계획을 바꾸지 않는다.
8. **기존 출력 불변**: `NutrientField`(4개)의 순회, `nutrients`의 4개 key, 기존 text 줄, `Incomplete:`/`Estimated:` 줄,
   `incomplete_fields`/`estimated_fields`는 바뀌지 않는다. 새 값은 별도 묶음(새 마지막 JSON key, 새 text 줄)으로만 나온다.
   새 줄은 포화지방·섬유 목표가 있거나 그날(그 끼니·항목)에 값이 하나라도 있을 때만 보인다(D5). 둘 다 없으면 모든 명령의
   출력이 byte-identical이다.
9. **읽기 전용 경로**: `recommend`, `daily`, `nutrition status` 등 읽기 전용 reader는 새 migration 전의 DB도 읽고(열·표가 있는지
   확인), 그때 새 값은 모두 unknown이다. `mode=ro`, migrate/mkdir 없음.
10. **표시 위치**: v1은 `nutrition` 명령 그룹만. `recommend`/`daily`의 영양 절, Telegram `/status`·`/day`, LLM 답장의 `오늘 누적`에
    넣을지는 D6(추천: v1에서는 넣지 않고 후속).
11. **단계 B — Telegram LLM 추정(D7)**: 넣는다면 해석 schema에 선택(nullable) 범위 `saturated_fat_g`, `fiber_g`. 모르면 null이고
    0으로 채우지 않는다. 라벨 사진·문장의 값은 기존 라벨 규칙(min = max, `; 라벨`). 숫자 재확인에 `satfat_exceeds_fat`(satfat min >
    fat max) 코드 하나를 더한다 `[design]`. 저장은 `--general-estimate`의 새 키다. 두 CLI(Claude, Codex)로 바뀐 schema를 live로
    확인한다(합성 데이터). 두 값이 모두 null인 제안의 답장은 바뀌지 않는다.
12. 날짜·시간대·기본 날짜는 `nutrition day`/`status`와 같다. text는 ASCII(사용자 음식 이름 제외), JSON은 고정 key 순서와 정확한
    Decimal 문자열.

## 인수 조건

- [ ] AC1: `food add`/`food fact add`가 `--satfat`/`--fiber`(숫자 또는 `unknown`)를 저장하고 `food show`/`--json`에 보인다.
      플래그를 빼면 unknown이다. 새 플래그 없는 기존 명령의 저장 값과 출력은 byte-identical이다.
- [ ] AC2: 음수·비정규 숫자, 포화지방 > 총지방, 포화지방·섬유만 있는 fact, 현재 fact가 아는 값을 unknown으로 주는 새 버전,
      `satfat=`/`fiber=`의 min > max는 exit 1, `오류:`, DB 변경 없음.
- [ ] AC3: 식사 기록 때 새 값이 snapshot으로 복사된다. 나중의 카탈로그 새 버전은 이미 기록된 끼니를 바꾸지 않고, `repeat`은
      현재 카탈로그 값을, `meal merge`는 원래 값을 쓴다. supersession은 영양소별이다.
- [ ] AC4: `--general-estimate`가 `satfat=`/`fiber=` 범위를 받고, 추정만 있는 항목은 합계를 불완전하게 둔다(0이 아님).
- [ ] AC5: `nutrition day`/`meal show`가 항목·끼니·하루 값을 보이고, 값이 빠진 항목이 있으면 "incomplete (known items only: …)"와
      항목 목록을 보인다. 어디에도 unknown을 0으로 쓴 값이 없다.
- [ ] AC6: `target set satfat --max-energy-percent`/`fiber --minimum`이 동작하고 0·음수·100 이상은 거부된다. 규칙 6의 플래그
      조합 밖(예: `fiber --exact 25`, `protein --minimum 100`)은 exit 1이고 파일이 바뀌지 않는다. `target show`가 새 목표를 보인다.
      새 목표가 없으면 목표 파일은 schema 1 그대로 byte-identical이다.
- [ ] AC7: 포화지방 판정이 규칙 4대로다: 완전 + `< L` within, 완전 + `= L` above, 불완전 + known `≥ L` above(excess null),
      불완전 + known `< L` indeterminate, kcal 목표 없음 `no_kcal_target`. 테스트가 각 경우를 하나씩 확인한다.
- [ ] AC8: 섬유 판정이 규칙 4대로다: 완전 + `≥ M` reached, 완전 + `< M` below와 remaining, 불완전 + known `≥ M` reached
      (complete false), 불완전 + known `< M` indeterminate.
- [ ] AC9: 새 text 줄과 JSON 목표 객체마다 근거 ID(`LDL-05`, `LDL-08`, `LDL-11`) 또는 `[design]`/`[user setting]`이 붙고, 그 밖의
      숫자 기준은 없다. 출력에 LDL-C 같은 검사값, 위험도, "warning" 등급이 없다.
- [ ] AC10: 끼니 메모는 사용자 설정이 있고 그 끼니의 포화지방이 완전하며 기준 이상일 때만 나온다. 어떤 명령도(`target set` 제외)
      목표 파일을 바꾸지 않는다.
- [ ] AC11: 포화지방·섬유 목표와 값이 없는 데이터에서 `nutrition day/status/meal show/food list/food show`, `recommend`, `daily`의
      text와 JSON이 이 기능 전과 byte-identical이다. 값이 있어도 `recommend`/`daily`의 운동 계획 부분은 byte-identical이다.
- [ ] AC12: migration이 임시 `MUSCLE50_HOME`의 이전 DB에 적용되고, 새 저장소가 append-only(update/delete 거부)이며, migration
      버전 기대값 테스트가 갱신된다. 읽기 전용 reader는 migration 전 DB에서 새 값을 unknown으로 보이고 오류 없이 끝난다.
- [ ] AC13: `--json` 출력이 재실행 시 byte-identical이고 새 key는 기존 key 뒤 마지막에 있다. text는 ASCII다(사용자 입력 이름 제외).
- [ ] AC14(단계 B를 넣을 때만): LLM 추정의 null은 unknown으로 저장되고, `satfat_exceeds_fat`가 한 번 다시 묻기를 일으키며,
      두 값이 모두 null인 제안의 답장은 바뀌지 않는다. live 확인 기록이 기능 문서에 있다.
- [ ] AC15: 품질 게이트 4개가 통과한다(`uv run --extra dev pytest`, `uv run ruff check .`, `uv run mypy src tests`, `git diff --check`).

## 한계 / 후속 후보

- 한계:
  - 이미 기록된 끼니는 snapshot을 유지하므로 카탈로그를 채워도 과거 날은 계속 unknown이다(원칙대로). 처음 몇 주는 대부분 불완전하다.
  - 기존 음식에 포화지방을 채우려면 4개 값을 다시 적은 새 fact 버전이 필요하다.
  - 상한 `L`은 kcal 목표에서 계산한 값이다(D2 추천안일 때). 실제 섭취 열량의 %와는 다르다.
  - LLM·사진 추정의 포화지방·섬유는 정확도가 알려지지 않았다. 추정은 계속 `estimated`이고 판정은 점 값만 쓴다.
  - schema 2 목표 파일은 이전 빌드가 읽지 못한다. production에 적용하려면 gate 3(백업 → 적용 → 확인)이 필요하다.
  - 통합 뒤 gate 3을 끝낼 때까지 hook이 production `muscle50` 실행을 막고, Telegram bot도 migration이 적용되지 않았으면 식사를
    기록하지 않는다. 그 사이에는 식사 기록이 멈추므로 통합 직후 바로 적용하는 것이 좋다.
- 후속 후보: `recommend`/`daily`와 Telegram `/status`·`오늘 누적`에 표시(D6), 메뉴 제안이 섬유·포화지방을 보조 기준으로 쓰기,
  식이 콜레스테롤 필드(LDL-07, ESC < 300 mg 참고값), 수용성 섬유(LDL-08), 코치가 새 JSON 읽기.
- 설계 결정 질문(게이트 1에서 답):
  - D1: 저장 (a) `nutrition_facts`에 열 추가 / (b) 새 append-only 표.
  - D2: 포화지방 상한의 분모: (A, 추천) kcal 목표 기준 g 상한 / (B) 그날 기록된 kcal 기준 %(kcal이 완전한 날만 판정) /
    (C) 사용자가 g 상한을 직접 입력하고 LDL-05는 참고 문구만.
  - D3: kcal 목표가 범위일 때 최소·최대 중 어느 끝으로 `L`을 계산할지.
  - D4: 끼니 메모 기준: (가, 추천) 오늘 상한의 N % 이상(사용자 설정) / (나) 그 끼니 열량의 7 % 이상(LDL-05의 하루 비율을 끼니에
    적용, `[design]`) / (다) v1에서는 끼니 메모 없음.
  - D5: 새 줄을 언제 보일지: 목표가 있거나 값이 있을 때(추천) / 목표가 있을 때만.
  - D6: `recommend`/`daily`/Telegram 표시를 v1에 넣을지(추천: 후속).
  - D7: Telegram LLM 추정(단계 B)을 이 기능에 넣을지, 다음 버전으로 나눌지.
  - D8: 사용자가 고를 포화지방 값: 7(LDL-05 KSoLA·ESC 고콜레스테롤혈증, 근거 문서 메모의 추천) 또는 10(ESC 일반).
- 열린 연구 질문(근거 문서에 없음, 이 스펙에서 조사하지 않았다. 필요하면 근거 문서를 갱신하고 다시 승인받는다):
  1. 끼니 단위 포화지방 "많음"의 기준. 근거 문서의 기준은 모두 하루 단위다.
  2. 지방 9 kcal/g 환산 계수의 출처(Atwater). 지금은 LDL-05 계산 예와 기존 코드 상수에만 있다.
  3. 수용성 섬유를 따로 기록할 가치와 일반 식품 라벨에서 얻을 수 있는지(LDL-08: ESC ≥ 7–13 g).
  4. 한국 영양 라벨의 탄수화물에 식이섬유가 포함되는지. 포함된다면 섬유 ≤ 탄수 검사를 더할 수 있다.
  5. LLM·사진 추정으로 얻은 포화지방·섬유 값의 정확도.
