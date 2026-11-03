---
id: ldl-nutrients-lookup
title: LDL Nutrients B - Telegram Saturated Fat and Fiber Estimates v1
status: integrated
migration: none
output_change: additive
user_gates: [design, integration]
---

# LDL Nutrients B - Telegram Saturated Fat and Fiber Estimates v1

## 목적

- Telegram으로 기록하는 일반식에 **포화지방(g)**과 **식이섬유(g)**의 **추정 범위**를 붙인다. 값은 코치 LLM의 추정과,
  필요할 때 이미 있는 Claude 웹 검색(lookup)에서 온다. 사용자는 `/ok` 전에 제안에서 범위를 보고, `/ok` 뒤에는 `/day`에서
  `sat fat estimated 8-14 g`처럼 본다.
- 근거:
  - 사용자 요청(2026-11-02): "포화지방 값이 없으면 인터넷 검색으로 채우면 되지 않나?"라고 물은 뒤 "그래 검색으로 채우기로 해".
  - `docs/specs/ldl-nutrients.md` D7은 Telegram LLM 추정(단계 B)을 후속으로 미뤘다. 그 스펙의 규칙 11과 AC14가 이 단계의
    검토된 초안이다(nullable 범위 두 개, 라벨 규칙, `satfat_exceeds_fat`, 둘 다 null이면 답장 불변). **이 스펙은 그것을
    구현하고 아래처럼 넓힌다.**
  - 지금 production에서 포화지방·섬유 값이 들어오는 길은 카탈로그 음식(`--satfat`/`--fiber`)과 손으로 친
    `--general-estimate …,satfat=…`뿐이다. 실제 식사는 대부분 Telegram 일반식이라 처음 몇 주는 거의 모든 항목이 unknown이다
    (`docs/ldl-nutrients.md` Known issues).
- `docs/goals.md` 3절 하루 흐름 2단계(먹은 것 기록)와 "채팅으로 묻기"에 붙는 건강 보조 기능이다. 우선순위 4·5와 운동 계획은
  바뀌지 않는다(domain-principles 6).
- **먼저 알아야 할 점(열린 질문 1, 게이트 1에서 결정)**: 이 기능은 **보여 주는 값**을 채운다. `nutrition status`의 LDL 판정은
  바뀌지 않는다. ldl-nutrients 규칙 3·4는 점 값만 합계와 판정에 쓰고, 범위만 있는 항목은 값이 없는 항목이다
  (`application/nutrition_targets.py` `_missing_optional`: "a range alone is not a value"). 그래서 Telegram 일반식은 이 기능 뒤에도
  `Unknown, not 0:` 목록에 남고, 포화지방·섬유 상태는 계속 `incomplete`/`cannot tell yet`이다. 이 스펙은 LDL 상태 규칙을
  바꾸지 않는다(사용자 범위). 상태에 추정 합계를 정보로 보이는 일은 후속 후보다.

## 범위 / Non-goals

- 범위:
  1. **해석 schema**: 식사 기록 item의 `estimate`에 nullable 키 4개 `satfat_min`, `satfat_max`, `fiber_min`, `fiber_max`(기존 8개
     뒤). 글, 사진, 앨범, 여러 끼니, 열린 제안 고치기(전체를 다시 쓰는 `meal_log`), 기존 끼니에 더하기(`add_item`), 겹침의
     `/fix_`가 같은 item schema를 쓰므로 모두 따라온다. Claude lookup도 같은 schema로 같은 메시지를 다시 읽으므로 따라온다.
  2. **저장**: 일반식 추정으로 저장되는 item만. 기존 `--general-estimate`의 `satfat=`/`fiber=` 키(ldl-nutrients v1)로 보낸다.
     값은 언제나 범위이고 `estimated`, source type은 그 item의 추정과 같다(글 `language_estimate`, 사진 `visual_estimate`).
  3. **검사**: 숫자 재확인에 `satfat_exceeds_fat` 하나. CLI가 거부할 값은 `/ok` 전에 빼서 CLI 오류가 나지 않게 한다(규칙 6, 7).
  4. **보여 주기**: 제안의 item 아래 한 줄(규칙 9). 값이 둘 다 없으면 줄이 없고 답장은 byte-identical이다.
  5. **검색 시점**: D2에서 정한다(규칙 4).
- Non-goals:
  - LDL 상태 규칙, 목표(`nutrition target`), 목표 파일, 끼니 메모, 운동 계획, `recommend`/`daily`, 메뉴 순서 변경.
  - LLM 답장의 `오늘 누적`, 짧은 `/ok` 요약(`이 끼니`), Telegram `/status`·`/daily`·`/today` 요약에 포화지방·섬유 표시(ldl D6 그대로).
  - **식이 콜레스테롤**(LDL-07, ESC < 300 mg 참고값) 필드와 추정. 별도 후속 스펙이다. 트랜스지방, 수용성 섬유, 식물성 스테롤도 없다.
  - lookup 결과로 **카탈로그 음식이나 fact를 만드는 일**(v2.2 규칙 "카탈로그 fact는 만들지 않는다" 그대로). 카탈로그 음식은 지금처럼
    `nutrition food add/fact add --satfat`로 사용자가 등록한다.
  - 카탈로그에 연결된 item에 LLM 값을 붙이는 일(카탈로그 snapshot이 값 또는 unknown을 준다).
  - (D1-A일 때) 이미 기록한 식사 고치기 `edit.change_estimate`의 schema, 메뉴 캡처(`menu.items`), 메뉴 제안(suggest) schema.
  - 새 source type(예: `web_estimate`). migration 003이 `source_type`을 CHECK로 고정하므로 새 값은 migration이 필요하다. 웹에서
    온 값은 지금처럼 근거 문자열의 `출처: <site>`로만 구분한다(v2.2).
  - Codex 웹 검색, lookup 모델·횟수·시간 상한 변경, 새 설정 key.
  - CLI 출력 변경. `parse_general_estimate`의 오류 문구 갱신(ldl 후속 후보)도 이번에는 하지 않는다.
  - migration. 기존 끼니의 snapshot 갱신이나 과거 일반식에 값을 채우는 일.

## 명령 예시

모두 합성 값이다. 정확한 문구는 설계에서 정한다. 아래 숫자는 문법 예시이고 실제 음식의 영양값이 아니다.

### Telegram

1. 집밥(Codex 기본, 검색 없음):

```text
사용자: 점심에 제육볶음 정식 먹었어
bot:   이렇게 기록할까요? (점심, 11-05)
       1. 일반식 (메모: 제육볶음 정식 1인분)
          추정: kcal 750~1000, 단백질 30~45 g, 탄수화물 90~120 g, 지방 25~40 g (estimated)
          포화지방 8~14 g · 섬유 4~8 g (추정)
       기록: /ok_5d21   일반식만 기록(값 없이): /plain_5d21   취소: /no_5d21
```

2. 상표 음식(Codex가 `lookup_wanted` → Claude가 검색해 답을 바꿈):

```text
사용자: 점심 맥도날드 빅맥 세트 먹었어
bot:   이렇게 기록할까요? (점심, 11-05)
       1. 일반식 (메모: 맥도날드 빅맥 세트)
          추정: kcal 1050~1250, 단백질 30~36 g, 지방 45~60 g (estimated)
          포화지방 14~20 g · 섬유 모름 (추정)
          출처: 맥도날드
       웹 검색 2회 (Claude)
       기록: /ok_5c1d   일반식만 기록(값 없이): /plain_5c1d   취소: /no_5c1d
```

3. 라벨 사진(`from_label`, 모두 한 값):

```text
bot:   사진 추정으로 기록할까요? (간식, 11-05)
       1. 일반식 (메모: 깻잎닭갈비 삼각김밥 1개)
          라벨: kcal 185, 단백질 5 g, 탄수화물 37 g, 지방 2 g
          포화지방 0.5 g · 섬유 모름 (라벨)
```

4. 다시 물어도 포화지방이 지방보다 큼(규칙 6):

```text
       1. 일반식 (메모: 크림파스타 1접시)
          추정: kcal 800~1000, 단백질 20~30 g, 지방 10~15 g (estimated)
          포화지방: 지방 범위보다 커서 빼고 기록합니다(모름) · 섬유 3~5 g (추정)
```

5. 이미 기록한 식사의 지방을 저장된 포화지방보다 낮게 고침(규칙 7, ldl D10과의 충돌):

```text
사용자: 아까 삼각김밥 지방 2g 이네 라벨에 나와있어
bot:   이렇게 고칠까요?
       일반식 (메모: 삼각김밥 1개): kcal 180~220, 지방 4~8 g
         지방 4~8 g → 2 g (라벨)
         포화지방 3~5 g: 지방보다 커서 빼고 고칩니다(모름)
       고치기: /ok_7a4a   취소: /no_7a4a
```

6. 모델이 포화지방·섬유를 모두 null로 줌: 제안, `/ok` 답, argv, 근거 문자열이 이 기능 전과 byte-identical이다
   (`docs/telegram-llm.md`의 v2.2·v2.5 예시 그대로).

7. (D2-L3를 고르면) 사용자가 검색을 직접 부탁함:

```text
사용자: 저녁에 집에서 끓인 된장찌개 먹었어 포화지방은 검색해서 넣어줘
bot:   ... 포화지방 1~3 g · 섬유 2~4 g (추정)
       웹 검색 1회 (Claude)
```

### bot이 `/ok`에서 실행하는 명령(손으로 쳐도 같은 결과)

```powershell
muscle50 nutrition log --meal lunch --general "--general-note=제육볶음 정식 1인분" --general-estimate=language_estimate:kcal=750-1000,protein=30-45,carbs=90-120,fat=25-40,satfat=8-14,fiber=4-8 "--general-estimate-ref=telegram-llm text (codex gpt-6.1-sol)"
muscle50 nutrition day --date 2026-11-05
```

`nutrition day`의 item 줄(기존 ldl-nutrients 출력, 바뀌지 않음):

```text
  1. 일반식 (general meal; note: 제육볶음 정식 1인분): estimated kcal 750-1000 | P 30-45 g | C 90-120 g | F 25-40 g
     LDL: sat fat estimated 8-14 g | fiber estimated 4-8 g
```

`nutrition status`는 이 항목을 지금처럼 `Unknown, not 0: saturated fat: 2026-11-05-lunch-1 item 1 일반식 (general-meal)`에
둔다(목적의 "먼저 알아야 할 점").

### JSON: 해석 schema의 item `estimate`(합성, key 순서 고정)

```json
{
  "kcal_min": 750, "kcal_max": 1000,
  "protein_min": 30, "protein_max": 45,
  "carbs_min": 90, "carbs_max": 120,
  "fat_min": 25, "fat_max": 40,
  "satfat_min": 8, "satfat_max": 14,
  "fiber_min": null, "fiber_max": null
}
```

CLI JSON 출력은 바뀌지 않는다. `nutrition day --json`의 item `ldl_nutrients.saturated_fat_g`는 기존 모양
`{"value": null, "minimum": "8", "maximum": "14", "fact_id": "…:estimate", "source_type": "language_estimate", "accuracy": "estimated"}`이다.

## 규칙

1. **원칙과의 관계**(domain-principles 2): ldl-nutrients v1은 "포화지방·섬유 값을 이름이나 다른 영양소에서 추정하는 일"을
   Non-goal로 두었다. 이 기능은 LLM이 그 추정을 **제안**하는 길을 연다. 근거는 2026-11-02 사용자 결정과 원래 계획된 D7 단계 B다.
   그래서 다음을 지킨다.
   - 모델이 제안하고 사용자가 `/ok`로 확인한다. `/ok` 전에는 아무것도 쓰지 않는다(v2 그대로).
   - 값은 추정 범위로만 저장하고 판정에 쓰지 않는다(규칙 2, 목적).
   - **bot은 포화지방·섬유를 스스로 만들지 않는다.** 지방의 비율, 음식 이름, 다른 영양소에서 계산하지 않고, 모델이 준 범위만
     쓴다. 모델이 null이면 unknown이다.
2. **저장**: 일반식 추정 fact 하나(`<meal_id>:<item>:estimate`)에 기존 4개 범위와 함께 `satfat=`/`fiber=` 범위를 둔다. 점 값은
   저장하지 않는다(`value` NULL). 정확한 값(`--satfat` 점 값, 카탈로그 fact)으로는 절대 저장하지 않는다. null은 행이 없음(unknown)이고
   0이 아니다. 라벨 값은 기존 라벨 규칙대로 min = max 범위이고 `estimated`이며 근거 문자열의 `; 라벨`이 구분한다.
3. **해석 schema**(`schemas/telegram_llm_interpret_v1.schema.json`의 item `estimate`):
   - 키 4개를 기존 8개 뒤에 더한다. Codex strict `--output-schema`는 모든 키가 `required`여야 하므로 4개 모두 required이고 type은
     `["number", "null"]`이다.
   - 검증은 기존 `_estimate`와 같다: min·max는 같이 있거나 같이 없음, min ≤ max, 0 이상, 상한 `GRAM_LIMIT`. 어기면 `bad_output`
     (기존 형식 재시도 규칙). 지금 `_estimate`는 item, `edit`, `menu.items`, suggest가 같이 쓰고 키 수 8을 검사하므로, 설계는
     item만 12개로 나누는 방법을 정한다(D1).
   - 내부 표현: `NutrientRanges`(4개 `NutrientField`)에 넣지 않는다. 기존 `OptionalNutrient`와 같은 별도 묶음(예:
     `optional_ranges`)으로 둔다. 그래서 숫자 재확인, `오늘 누적`, 메뉴 순서의 4개 영양소 루프는 바뀌지 않는다.
4. **검색 시점(D2, 게이트 1에서 고름)**. 지금: 기본 제공자 Codex는 검색하지 않고, item 하나라도 `lookup_wanted`이면 같은 메시지를
   Claude가 웹 검색으로 한 번 다시 읽어 답 전체를 바꾼다(v2.5 W3). 제공자가 Claude면 처음부터 검색 규칙이다.
   - **L2 "값이 없으면 검색"**(사용자가 한 말 그대로): Codex 답에서 일반식 item의 포화지방이나 섬유가 null이면(지방 범위는 있는데)
     lookup을 한다. 장점: 사용자 요청과 똑같다. 비용: 그런 메시지마다 Claude 호출 하나(최대 150 s, Codex 약 12~17 s 뒤)와
     Claude 사용량, 메시지·사진이 Anthropic으로도 간다. 완화: 프롬프트가 "추정할 수 있으면 범위를 적는다"를 요구하므로 null은
     드물 수 있다(빈도는 live 확인과 history로 본다). 집밥은 검색해도 일반 레시피 페이지라 모델 추정과 크게 다르지 않을 수 있다.
   - **L1 "지금 그대로"**: `lookup_wanted` 규칙을 바꾸지 않는다. 상표·식당·포장 제품은 검색한 Claude가, 집밥은 Codex가 지식으로
     채운다. 추가 호출과 지연 없음. 사용자의 "검색으로"를 상표 음식에서만 만족한다.
   - **L3 "부탁하면 검색"**: L1 + 프롬프트의 `lookup_wanted` 정의에 "사용자가 검색해 달라고 하면(예: `검색해서`, `찾아서`) 그
     item은 true"를 더한다. 프롬프트 한 줄 변경이다.
   - 추천: **L3**(추가 호출은 사용자가 원할 때와 상표 음식만). 사용자가 "없으면 자동으로 검색"을 원하면 L2를 고른다. 어느 쪽이든
     lookup의 횟수(1회), 모델, 시간 상한, 실패 처리(`(웹 검색은 하지 못했습니다: …)`, Codex 답 유지)는 v2.5 그대로다.
5. **프롬프트 규칙**(고정 규칙 6과 item 설명에 더한다. 기존 프롬프트처럼 한국어):
   - 포화지방·식이섬유는 말한 양 기준의 범위로, 알 수 있을 때만 적는다. 모르면 null이고 0으로 채우지 않는다.
   - 포화지방은 총지방의 일부다: 포화지방 범위를 적으면 지방 범위도 적고, 포화지방 최소는 지방 최대보다 크지 않게.
   - 라벨(`from_label`)에 인쇄된 값이면 한 값(min = max), 라벨에 없으면 null.
   - 웹 검색 변형에서는 찾은 페이지에 포화지방·식이섬유가 있으면 그 값을 쓴다(값을 지어내지 않는다, 기존 규칙 11~15 그대로).
     페이지 값이 한 숫자여도 라벨이 아니므로(`from_label` false) 그 값을 포함하는 범위로 적는다. 포화지방·섬유에는
     `range_is_a_point` 검사가 없으므로(규칙 6) 이 문장이 한 값을 막는 유일한 장치다(한계).
   - 카탈로그에 연결할 item의 값은 대체값일 뿐이다(기존 규칙).
6. **숫자 재확인**(`domain/telegram_llm_check.py`):
   - 새 코드 `satfat_exceeds_fat`: 같은 item에 포화지방과 지방 범위가 모두 있고 `satfat_min > fat_max`. 다시 묻기 note 줄 예:
     `- items[3]: satfat_exceeds_fat (fat 10-15, satfat 18-25)`. 이유 문구 `포화지방이 지방보다 큼`.
   - 실패하면 기존대로 **딱 한 번** 다시 묻는다(`fixed` / `still_inconsistent` / `reask_failed`).
   - **argv를 만들 때 언제나**(재확인 결과와 상관없이) 그 item의 `satfat_min > fat_max`이면 포화지방 범위를 빼고(unknown) 제안에
     예시 4의 줄을 보인다. 이유: CLI(ldl 규칙 2)가 그 SPEC을 exit 1로 거부하므로 `still_inconsistent`의 "사용자가 `/ok`에서
     결정"을 그대로 두면 `/ok`가 끼니 전체를 기록하지 못한다. 다른 영양소와 섬유는 그대로 기록한다.
   - 표시: 남은 실패 코드가 `satfat_exceeds_fat` 하나뿐이고 포화지방을 뺐으면, 저장되는 값끼리는 맞으므로 `(값 확인 필요)`
     표시와 근거 문자열의 `; 값 확인 필요`를 붙이지 않는다. history의 `recheck`에는 코드와 결과가 그대로 남는다. 다른 코드도 남아
     있으면 그 코드에 대해 기존 표시 규칙을 따른다(이유 줄에는 `satfat_exceeds_fat`를 넣지 않는다).
   - 지방이 null이면 비교하지 않고 포화지방을 그대로 둔다(CLI도 둘 다 있을 때만 비교한다). D5에서 확인.
   - 섬유와 탄수화물은 비교하지 않는다(ldl 열린 질문 4). 포화지방·섬유에 `range_too_wide`·`range_is_a_point`를 적용하지 않는다
     `[design]`(바닥값 근거가 없다). 기존 4개 영양소의 검사는 그대로다.
7. **이미 기록한 식사 고치기와 D10의 충돌**: `change_estimate`는 저장된 포화지방·섬유 범위를 다시 보낸다(D10). 고친 지방 최대가
   저장된 포화지방 최소보다 작으면 지금은 `/ok` 뒤 CLI가 거부하고 아무것도 쓰지 않는다(ldl Known issue). Telegram 식사에 포화지방이
   흔해지면 이 경우도 흔해진다. 규칙: **고치기 제안을 만들 때** 그 경우 저장된 포화지방을 빼고(unknown) 예시 5의 줄을 보인다.
   `replace-item`은 옛 item과 fact를 남기므로 저장된 값이 지워지지는 않는다. 사용자는 `/no`로 거절할 수 있다. 다른 방법(고치기 자체를
   거절하는 답)은 D4에서 고른다. 어느 쪽이든 `/ok` 뒤 CLI 오류는 없어야 한다.
8. **적용되는 item과 아닌 item**:
   - 일반식 추정으로 저장되는 item만 값이 붙는다(글·사진 일반식, 카탈로그 대체 일반식, 라벨, 여러 끼니, `add_item`, `/fix_`의
     `replace-item`, 열린 제안 고치기의 새 제안).
   - 카탈로그에 연결된 item(`--item`)은 LLM 값을 버리고 카탈로그 snapshot을 쓴다. 최근 메뉴에서 이름으로 고른 item(`menu_ref`)은
     메뉴 값이라 포화지방·섬유가 없다. `/plain_`은 값을 저장하지 않는다(포화지방·섬유도). `nutrition repeat`은 지금처럼 추정을 버린다.
   - `<직전 기록>`·`<열린 제안>` 프롬프트 블록은 바꾸지 않는다 `[design: 프롬프트 길이]`(설계에서 확인).
9. **보여 주기**(좁은 화면):
   - 위치: 그 item의 `추정:`/`라벨:` 줄 바로 다음, `값 확인 필요:`·`양 가정:`·`가정:`·`출처:` 줄 앞.
   - 모양: `포화지방 8~14 g · 섬유 4~8 g (추정)`. 하나만 있으면 다른 쪽은 `모름`(0이 아님을 보인다). 둘 다 없으면 줄이 없다.
   - 표시: 추정은 `(추정)`, 라벨이면 `(라벨)`, 규칙 6으로 뺀 값은 `지방 범위보다 커서 빼고 기록합니다(모름)`. 범위 표기와 반올림은
     기존 `ranges_text`와 같다.
   - 출처: 따로 만들지 않는다. 그 item의 기존 `출처: <site>` 줄과 `웹 검색 N회 (Claude)` 줄이 item 전체에 대한 것이다. 어느
     영양소가 웹에서 왔는지는 구분하지 않는다(한계).
   - 정확도: 줄마다 "정확도 미확인"을 붙이지 않는다 `[design: 화면 폭]`. 대신 기능 문서가 "표시용 추정, 정확도 미확인(ldl 열린 연구
     질문 5)"으로 적는다. 줄에 붙일지는 열린 질문 3.
   - `/ok` 답(짧은 요약, `오늘 누적`)은 바꾸지 않는다. `/day`·`/show`는 CLI text를 그대로 전하므로 `LDL:` 줄이 보인다(ldl D6, 승인됨).
10. **byte-identical 범위**:
    - 모델이 모든 item에서 포화지방·섬유를 null로 주면 같아야 하는 것: 제안 답장, `/ok`·`/plain_`·`/new_`·`/add_`·`/fix_` 답,
      argv(`format_general_estimate`는 선택 범위가 없으면 v1 이전 SPEC), 근거 문자열, 상태 파일의 제안 항목(argv, outline), 콘솔 줄.
    - 같지 않은 것(output_change additive, 사용자에게 안 보임): 해석 schema, 해석 프롬프트, history 줄의 `llm_output.interpret`
      (item마다 null 키 4개가 더해진다. 옛 줄은 다시 쓰지 않는다).
    - LLM이 꺼진 bot, 모든 CLI 명령의 text·JSON, `telegram history`의 옛 줄은 바뀌지 않는다.
11. **migration 없음**(확인): 저장소는 migration 011 `nutrition_fact_optional_nutrients`이고, 범위만 있는 일반식 추정 행은 이미
    된다(ldl AC4 `--general-estimate`의 `satfat=`/`fiber=`, `tests/test_ldl_nutrients_telegram.py`의 D10 테스트). 새 source type이
    없으므로 migration 003의 `source_type` CHECK도 그대로다. 설계가 schema 변경이 필요하다고 판단하면 멈추고 묻는다.
12. **LDL 상태·목표 불변**: `nutrition status`의 판정 순서와 문구, `Unknown, not 0:` 목록, 목표 파일 schema 1/2, 끼니 메모는 그대로다.
    추정 범위는 합계와 판정에 쓰지 않는다(ldl 규칙 3·4).
13. **live 확인**:
    - implementer(AC로 확인, 합성 데이터, 임시 폴더, 프로젝트 격리 argv, 실제 로그인 파일은 바꾸지 않음): Codex(`gpt-6.1-sol`,
      strict `--output-schema`)와 Claude(haiku, `--json-schema`)가 새 schema를 받는지, 합성 문장 3~4개(집밥, 상표 음식 lookup,
      라벨 문장, 포화지방을 모르는 음식)의 결과. 결과 표를 기능 문서에 남긴다(v2.2·v2.5와 같은 방식).
    - 사용자 게이트 `live-llm`(통합 뒤): Claude가 main checkout에서 Telegram bot을 다시 시작하고, 사용자가 휴대폰 Telegram에서 합성
      메시지 3~4개를 보내 제안을 본다(`/no`로 취소하면 아무것도 쓰지 않는다). 사용자가 할지, 언제 할지 정한다. PC 앞에서 할 일은 없다.
14. 날짜, 끼니, 시간대, 합계 규칙은 v2.2~v2.5와 ldl-nutrients 그대로다.

### 설계에서 정할 것(게이트 1)

- **D1 입력 범위**: (A, 추천) 식사 기록 item의 `estimate`만. `edit.change_estimate`, `menu.items`, suggest는 8개 그대로.
  (B) A + `edit.estimate`에도 4개(이미 기록한 일반식의 포화지방을 말로 고치기: "포화지방 3 g이래"). B는 `change_estimate`의
  병합 규칙(바뀌는 영양소만)을 선택 영양소에 넓혀야 한다.
- **D2 검색 시점**: 규칙 4의 L1 / L2 / L3(추천 L3).
- **D3 표시 줄 모양**: 규칙 9 추천안. 대안: `추정:` 줄 끝에 붙이기(줄이 길어짐).
- **D4 고치기 충돌**: 규칙 7. (가, 추천) 저장된 포화지방을 빼고 줄로 알림. (나) 고치기를 거절하고 이유를 답함.
- **D5 지방 없는 포화지방**: (가, 추천) 그대로 저장(CLI와 같음). (나) 지방이 null이면 포화지방도 뺌.
- **D6 기능 문서 위치**: 추천: `docs/telegram-llm.md`에 새 절 "포화지방·섬유 추정 (LDL Nutrients B)"(Output change, live 확인 표,
  Known issues 포함)과 `docs/ldl-nutrients.md` Known issues의 "Telegram LLM은 아직 … 추정하지 않는다" 줄 갱신.

## 인수 조건

아래 테스트 이름에서 P는 `tests/test_ldl_nutrients_lookup.py`(순수 테스트), B는 `tests/test_ldl_nutrients_lookup_bot.py`(가짜 Bot API와
가짜 제공자로 끝까지)다.

- [x] AC1: 해석 schema의 item `estimate`가 12개 키이고 새 4개는 required + `number|null`이다. 파서는 null 쌍, 범위, 라벨 한 값을
      받고, 한쪽만 있음·min > max·음수·`GRAM_LIMIT` 초과를 `bad_output`으로 거부한다. (D1-A면) `edit`, `menu.items`, suggest의
      estimate는 8개 그대로이고 기존 테스트가 고침 없이 통과한다.
      근거: P `test_the_item_estimate_has_twelve_required_keys_...`, `test_broken_optional_ranges_are_a_format_failure`(6경우),
      `test_an_item_estimate_needs_exactly_twelve_keys`, `test_edit_menu_and_suggestion_estimates_refuse_twelve_keys`. 기존 테스트의 변경은
      계획한 fixture 두 곳(null 키 4개)뿐이다.
- [x] AC2: 포화지방·섬유 범위가 있는 일반식 제안을 `/ok`하면 `nutrition log`(또는 `add-item`/`replace-item`) argv의
      `--general-estimate`에 4개 뒤 `satfat=`/`fiber=`가 붙고, 임시 `MUSCLE50_HOME`의 `nutrition day --json` item에
      `value` null, min/max, 글은 `language_estimate`, 사진은 `visual_estimate`, `estimated`로 보인다. null인 영양소는 행이 없고 0이 아니다.
      근거: B `test_a_text_meal_shows_the_line_and_ok_stores_language_estimate_ranges`, `test_a_photo_meal_stores_visual_estimate_ranges`,
      `test_an_unknown_fiber_has_no_row_and_is_not_zero`.
- [x] AC3: 카탈로그에 연결된 item, `menu_ref` item, `/plain_`은 LLM의 포화지방·섬유를 저장하지 않는다. bot이 포화지방·섬유를
      스스로 계산하는 코드 경로가 없다(모델 값이 null이면 argv에 키가 없다).
      근거: B `test_a_catalog_linked_item_drops_the_models_satfat_and_fiber`, `test_a_menu_pick_keeps_the_menus_values_without_satfat_or_fiber`,
      `test_plain_stores_no_satfat_or_fiber`. 검증자 확인: 값은 일반식 item에서만 실리고 `format_general_estimate` 범위로만 나간다.
- [x] AC4: `from_label`이고 모두 한 값인 item은 포화지방도 min = max로 저장되고 제안에 `(라벨)`로 보인다. 라벨이 아닌 한 값의
      포화지방·섬유는 다시 묻기를 일으키지 않는다.
      근거: B `test_a_label_photo_stores_single_values_and_shows_the_label_tag`, `test_a_label_with_a_ranged_saturated_fat_is_an_ordinary_estimate`(D8),
      `test_a_non_label_single_saturated_fat_or_fiber_value_is_not_re_asked`.
- [x] AC5: `satfat_min > fat_max`면 `satfat_exceeds_fat`로 한 번 다시 묻는다. `fixed`면 새 답을 쓰고, `still_inconsistent`·
      `reask_failed`면 그 item의 포화지방만 빼고 규칙 9의 줄을 보이며(다른 코드가 없으면 `(값 확인 필요)`와 근거 문자열 표시 없음,
      history `recheck`에는 남음), `/ok`가 나머지를 exit 0으로 기록한다. 어떤 경로에서도 CLI가
      포화지방 > 지방으로 거부하는 argv가 만들어지지 않는다(가짜 runner 테스트). 지방이 null이면 검사하지 않는다(D5-가).
      근거: B `test_satfat_above_fat_is_re_asked_once_and_a_fixed_answer_is_used`, `test_satfat_still_above_fat_is_left_out_and_the_rest_is_recorded`
      (still_inconsistent, reask_failed), `test_satfat_with_another_failure_marks_only_that_failure`, `test_satfat_without_a_fat_range_is_kept_and_not_re_asked`,
      `test_a_history_line_with_the_new_code_is_rendered_by_history_and_telegram_history`. 검증자가 손으로 친 `fat=10-15,satfat=18-25`가 CLI에서
      exit 1("Nothing was changed")임을 확인했다(막아야 할 위험이 실제다).
- [x] AC6: (D4-가) 저장된 포화지방보다 지방을 낮추는 `change_estimate`는 제안에서 포화지방을 빼는 줄을 보이고 `/ok`가 exit 0이다.
      그 밖의 `change_estimate`는 ldl D10 테스트(`tests/test_ldl_nutrients_telegram.py`)대로 저장된 범위를 유지한다.
      근거: B `test_lowering_fat_below_the_stored_satfat_drops_it_with_a_line_and_ok_succeeds`, `test_an_edit_that_keeps_fat_at_or_above_the_stored_satfat_keeps_it`.
      기존 D10 테스트는 고치지 않았다.
- [x] AC7: Codex 답에 `lookup_wanted`가 있으면 Claude lookup 답의 포화지방·섬유가 Codex 답을 통째로 바꾸고, lookup이 실패하면
      Codex의 값을 그대로 쓴다. D2에서 고른 시점 규칙(L2면 null 조건, L3면 프롬프트 줄)이 가짜 runner 테스트로 확인된다. 그 밖의
      lookup 규칙(1회, 모델, 150 s, 실패 안내 줄)은 기존 테스트가 고침 없이 통과한다.
      근거: B `test_the_lookup_answers_satfat_replace_codexs`(L3 문장 두 개도 확인), `test_a_failed_lookup_keeps_codexs_satfat_and_says_why`,
      `test_a_home_meal_the_user_asks_to_search_is_looked_up`. lookup 코드(`_lookup`)는 바뀌지 않았고 기존 lookup 테스트도 그대로다.
- [x] AC8: 포화지방·섬유가 있는 item에 규칙 9의 줄이 정해진 위치·모양으로 보이고(하나만 있으면 `모름`), 여러 끼니 제안,
      기존 끼니에 더하기, `/fix_`, 열린 제안 고치기에서도 argv와 줄이 맞다.
      근거: P `test_the_line_shapes`(8경우); B `test_a_multi_meal_proposal_has_the_line_per_item_and_the_ranges_per_meal`,
      `test_joining_a_recorded_meal_adds_the_item_with_its_ranges`, `test_add_offers_the_recorded_meal_with_the_same_ranges`,
      `test_fix_replaces_the_recorded_item_with_the_ranges_and_shows_the_line`, `test_fix_adds_new_items_with_the_line_in_the_change_text`,
      `test_correcting_an_open_proposal_carries_the_new_ranges`.
- [x] AC9: 모델이 모든 item에서 포화지방·섬유를 null로 주면 규칙 10의 첫 묶음(답장, argv, 근거 문자열, 상태 파일 제안 항목,
      콘솔 줄)이 이 기능 전과 byte-identical이다. 기존 Telegram LLM 테스트는 schema·프롬프트 고정값과 null 키 4개를 더한 fixture
      말고는 고치지 않는다.
      근거: 기존 exact-reply 테스트가 fixture 두 곳만 고쳐 통과한다. 검증자가 main(d852b65)과 branch를 `git archive`로 따로 꺼내 같은
      가짜 제공자 시나리오 17개(글, 사진, 라벨, 여러 끼니, 카탈로그, 다시 묻기, `/plain_`, `/add_`, `/new_`, 더하기, `/fix_`, lookup, 고치기,
      열린 제안 고치기, 메뉴 고르기, LLM 꺼짐)를 돌렸다: 답장, 상태 파일 제안, 콘솔 줄, 식사 표가 같고 history는 `llm_output`의 null 키 4개만 다르다.
- [x] AC10: LLM이 꺼진 bot, 모든 CLI 명령(`nutrition day/status/meal show/target show`, `recommend`, `daily`)의 text와 JSON,
      목표 파일, LDL 상태 판정이 바뀌지 않는다. 추정 범위가 `nutrition status`의 합계와 판정에 들어가지 않는다.
      근거: CLI·terminal 코드는 diff에 없다. B `test_stored_ranges_do_not_change_the_status_verdict`, 검증자 smoke의 LLM 꺼짐 시나리오.
      **검증자 정정**: 구현 보고의 "status text 전체가 byte-identical"은 틀렸다. 저장된 범위가 생기면 ldl v1 규칙대로 status text의
      `(estimated)` 꼬리표와 JSON `estimated`, `nutrition day`의 `LDL:` 줄이 바뀐다(아래 "한계"). 판정, `known_subtotal`, `missing_items`는 같다.
- [x] AC11: 해석 프롬프트에 규칙 5의 문장(모르면 null·0 아님, 포화지방 ≤ 지방, 라벨 한 값, 검색 페이지 값)이 있고 프롬프트 고정
      테스트가 갱신된다.
      근거: P `test_the_interpret_task_has_every_new_sentence`, `test_web_rule_twelve_allows_a_search_the_user_asked_for`,
      `test_the_shared_fixed_rules_and_the_other_tasks_are_unchanged`. 검증자 확인: `FIXED_RULE_LINES`, 질문 답·메뉴 제안 프롬프트는 같다.
- [x] AC12: implementer live 확인(규칙 13): Codex strict schema와 Claude haiku가 새 schema로 `ok`이고, 합성 문장 3~4개의 결과
      (포화지방·섬유를 채웠는지, null을 0으로 쓰지 않았는지, `satfat_exceeds_fat` 발생 여부)가 기능 문서의 표에 있다.
      근거: `docs/telegram-llm.md` "live 확인" 표(2026-11-03, 합성 문장 5개 x Codex·Haiku·Haiku 웹 = 15번 모두 `ok`, 0으로 쓴 값 없음,
      `satfat_exceeds_fat` 없음). 검증자는 다시 돌리지 않고 내용이 맞는지만 확인했다.
- [x] AC13: 기능 문서(D6)가 값을 "표시용 추정 범위, 정확도 미확인(ldl 열린 연구 질문 5), LDL 상태 판정에 쓰지 않음"으로 적고,
      Output change(규칙 10의 두 묶음)와 Known issues를 적는다.
      근거: `docs/telegram-llm.md` 새 절 "포화지방·섬유 추정 (LDL Nutrients B)"과 Known issues, `docs/ldl-nutrients.md` Known issues.
      Output change 목록이 CLI text의 변화를 다 적지 않은 점은 "한계"에 있다.
- [x] AC14: 품질 게이트 4개가 통과한다(`uv run --extra dev pytest`, `uv run ruff check .`, `uv run mypy src tests`, `git diff --check`).
      근거: 통합 때 main(d852b65) 위에서 다시 돌렸다: pytest 3393 passed(기준 3326에서 +67: P 37, B 30), ruff clean, mypy 274 files,
      `git diff --check` clean, 바뀐 파일 모두 LF.

## 설계 승인 결정 (2026-11-03)

사용자 답: L3와 모든 추천안(열린 질문 1~5). 상세: `docs/telegram-llm.md` "포화지방·섬유 추정 (LDL Nutrients B)".

- **D0-A**(열린 질문 1): 값은 보여 주기만 한다. `nutrition status`의 LDL 판정은 그대로이고 Telegram 일반식은 `Unknown, not 0:`에 남는다.
  상태에 추정 합계를 정보로 보이는 일은 후속 스펙이다.
- **D1-A**: 새 값은 식사 기록 item의 `estimate`에만 들어온다. `edit`, `menu.items`, suggest의 estimate는 8개 키 그대로다. 이미 기록한 식사의
  포화지방·섬유만 고치는 말은 프롬프트 한 줄로 `edit.action: null`이 되어 기존 `EDIT_UNCLEAR_TEXT`를 받는다.
- **D1.1 엄격**: item estimate는 정확히 12개 키다. 8개나 13개는 `bad_output`이다.
- **D2 = L3**(열린 질문 2): `lookup_wanted` 규칙은 지금 그대로(상표·식당·포장 제품만 Claude가 검색)이고, 두 문장을 더했다.
  해석 프롬프트의 `lookup_wanted` 설명에 "사용자가 그 음식을 검색해 달라고 하면('검색해서', '찾아서', '찾아봐') 흔한 음식이어도 true",
  웹 고정 규칙 12 끝에 "사용자가 검색해 달라고 한 음식은 흔한 음식이어도 검색할 수 있습니다". 값이 없다고 자동으로 검색하지 않는다(L2 아님).
  lookup 횟수(1회), 모델, 150 s, 실패 처리는 v2.5 그대로다.
- **D3**: 표시는 `추정:`/`라벨:` 줄 바로 다음의 따로 한 줄이다.
- **Q3**(열린 질문 3): 줄 끝 꼬리표는 `(추정, 정확도 미확인)`이고 라벨 값은 `(라벨)`이다. 위 규칙 9와 명령 예시의 `(추정)`은 이 결정으로 바뀌었다.
- **D4**(열린 질문 4): 포화지방 최소가 지방 최대보다 크면 포화지방만 빼고(unknown) 줄로 알린다. 새 끼니와 lookup은 `_settle_ldl`이 제안을
  저장하기 직전에(재확인 결과와 상관없이), 이미 기록한 식사의 `change_estimate`(D4-가)는 고치기 제안을 만들 때 뺀다. 줄 문구는
  `포화지방 모름(지방보다 커서 뺌)`, 고치기는 `포화지방 3~5 g → 모름(지방보다 커서 뺌)`이다(위 예시 4·5의 문구 대신). 지방에 맞춰 깎지 않는다
  (값을 지어내는 일). 이것이 ldl-nutrients D10(고치기가 저장된 포화지방·섬유를 다시 보냄)과 CLI 규칙 2(포화지방 ≤ 지방)의 충돌을 Telegram
  쪽에서 푼다.
- **D5-가**: 지방이 null이면 비교하지 않고 포화지방을 그대로 저장한다(CLI와 같다).
- **D6**: 기능 문서는 `docs/telegram-llm.md`의 새 절과 `docs/ldl-nutrients.md` Known issues 갱신이다.
- **D7**: `<열린 제안>`·`<직전 기록>` 프롬프트 블록은 바꾸지 않는다.
- **D8**: `from_label`이고 기존 4개와 포화지방·섬유가 모두 한 값일 때만 라벨 값이다. 섞이면 보통 추정이다.
- **D9**: 새 문장은 해석 할 일(INTERPRET)에만 넣었다. 공유하는 `[고정 규칙]`은 그대로다(위 규칙 5의 "고정 규칙 6에 더한다" 대신).
- **Q5**(열린 질문 5): 새 사람 게이트는 없다(`user_gates: [design, integration]`). implementer의 AC12 live 표가 live 확인이고, 통합 뒤 Claude가
  main checkout에서 bot을 다시 시작한다. 사용자의 휴대폰 Telegram 확인은 선택이다. 위 규칙 13의 `live-llm` 게이트는 이 결정으로 없어졌다.
- 숫자 재확인 코드 `satfat_exceeds_fat`: 포화지방 최소 > 지방 최대(CLI와 같은 비교), 실패 목록의 마지막, note 줄
  `- items[1]: satfat_exceeds_fat (fat 10-15, satfat 18-25)`, 이유 문구 `포화지방이 지방보다 큼`. `RECHECK_CODES`에도 넣어 history 줄이 버려지지
  않는다. 포화지방·섬유에는 범위 넓이·한 값 검사가 없고 섬유와 탄수화물은 비교하지 않는다.

**`output_change: additive`(통합 때 판단)**: 같은 저장 데이터는 이 기능 전과 같은 출력을 낸다. CLI·terminal 코드는 diff에 없고, 검증자의
같은 데이터 CLI 실행은 byte-identical이었다. 바뀌어 보이는 것은 모두 새 데이터가 있을 때만 나온다: Telegram 제안의 새 줄과 `/fix_` 변경 글,
`/ok` argv의 `satfat=`/`fiber=`, history의 null 키 4개, 그리고 새 범위 행을 이미 승인된 ldl v1 렌더링이 보여 주는 CLI의 `(estimated)` 꼬리표,
JSON `estimated: true`, `LDL:`·`LDL nutrients:` 줄. 기존 key나 줄의 모양이 바뀌거나 사라진 것은 없으므로 `breaking`이 아니다. 다만 같은 날에
정확한 카탈로그 소계가 있으면 그 소계가 `(estimated)`로 보이는 변화가 사용자에게 보인다(아래 "한계"의 검증자 판단 1).

### 승인된 구현 차이(검증자가 모두 받아들임)

1. AC12 live 확인은 손으로 만든 argv 대신 bot과 같은 길(`CliLlmProvider` + `RunPin`)로 돌렸다. 기능 문서에 그렇게 적었다.
2. AC10: 저장된 범위가 있으면 ldl v1의 `estimated` 꼬리표가 켜진다. 기존 v1 동작이고 코드 변경이 아니다. 테스트는 `estimated`를 고정하고
   나머지를 비교한다. 검증자가 text도 바뀐다고 정정했다(AC10, "한계").
3. 계획에 없던 테스트 하나: 새 코드가 든 history 줄을 `/history`와 `telegram history`가 보여 준다.
4. 문구: `/fix_`의 더하기 변경 글에서는 줄이 `(라벨)`·확인 표시 뒤 ` / ` 다음에 붙는다. D4 줄은 영양소 변경 줄 다음, 메모·이유 줄 앞이다.
   고치기 머리 줄은 기존 renderer의 `저녁 <meal_id> item 1: 일반식 (메모: …)`이다.

## 한계 / 후속 후보

- 한계:
  - **LDL 상태는 거의 그대로다**(목적, 열린 질문 1). 범위만 있는 Telegram 일반식은 `Unknown, not 0:`에 남고 포화지방·섬유 상태는
    `cannot tell yet`이 흔하다. 값은 `/day`와 제안에서만 보인다.
  - **정확도는 모른다**(ldl 열린 연구 질문 5). LLM·사진 추정과 웹 페이지 값 모두 검증되지 않았다. 사진 kcal 추정도 흔히 ±30~50 %다.
    값은 표시용 추정 범위이고 LDL 판정에 쓰지 않는다. 제안 줄에는 `(추정, 정확도 미확인)`이 붙지만 CLI `/day`의 `LDL:` 줄은
    `estimated`라고만 한다(CLI 출력 그대로).
  - 기본 제공자 Codex는 검색하지 못한다(v2.5). L3에서 집밥의 값은 모델 지식에서 오고, 사용자가 "검색해서"라고 할 때만 Claude가 찾는다.
    `출처:` 줄은 item 전체에 대한 것이고 어느 영양소가 웹에서 왔는지는 모른다. 사이트 이름은 모델이 적은 것이다(v2.2 한계 그대로).
  - 라벨이 아닌 한 값(min = max)의 포화지방·섬유는 프롬프트 문장으로만 막는다. 모델이 한 값을 주면 그대로 범위로 저장된다.
  - 한국 영양 라벨에 식이섬유가 없는 경우가 많아 라벨 사진에서도 섬유는 `모름`이 흔할 수 있다(확인하지 않음).
  - 포화지방을 규칙 6·7(D4)로 빼면 그 item은 unknown이다. 사용자는 CLI `replace-item --general-estimate …,satfat=…`로 다시 넣을 수 있다.
    Telegram에서 포화지방·섬유만 고치는 말은 받지 않는다(D1-A).
  - 프롬프트와 schema가 길어져 형식 실패가 아주 조금 늘 수 있다(기존 재시도 규칙).
  - 통합 뒤 Telegram bot을 다시 시작해야 새 schema를 쓴다. 다시 시작하기 전에 만든 열린 제안은 옛 argv로 기록된다. 과거 일반식은 채우지 않는다.
  - history 줄이 item마다 null 키 4개만큼 길어진다.
  - 구현자·검증자가 보고한 한계(상세: `docs/telegram-llm.md` Known issues "포화지방·섬유 추정 (LDL Nutrients B)"):
    - **CLI 출력이 바뀌어 보인다(검증자 판단 1).** CLI 코드는 그대로지만 저장된 Telegram 범위가 생기면 ldl v1 규칙대로 보인다.
      `nutrition status` text의 포화지방·섬유 소계에 `(estimated)` 꼬리표가 붙고 JSON `estimated`가 true가 된다. 아는 소계가 정확한 카탈로그
      음식에서만 왔어도 그렇다(예: 정확한 라벨 음식 0.5 g과 Telegram 일반식이 같은 날이면 `known items only: 0.5 g (estimated)`).
      `nutrition day` text에는 item의 `LDL:` 줄과 끼니의 `LDL nutrients: ...` 줄이 생긴다. 승인된 v1 규칙대로이고 판정, `known_subtotal`,
      `missing_items`는 같다. 다만 `docs/telegram-llm.md`의 Output change 목록은 status JSON의 `estimated`만 적어 **완전하지 않다**.
    - **Claude 웹 lookup이 Codex의 포화지방을 지울 수 있다.** lookup 답이 Codex 답을 통째로 바꾸므로(v2.5) Claude가 null로 주면 Codex가
      채운 값은 unknown이 된다(live: 상표 음식). 두 답을 합치지 않는 것은 의도다.
    - **사진은 live로 확인하지 않았다**(합성 문장만). 사진 추정·라벨 사진은 가짜 제공자 테스트로만 확인했다.
    - **Haiku는 대부분 `모름`이다.** live에서 Haiku는 라벨 말고는 포화지방·섬유를 채우지 않았다(검색한 뒤에도). Codex도 같은 문장에 채우기도
      하고 비우기도 한다. `"provider": "claude"`로 쓰면 대부분 `모름`일 수 있다.
    - 겹침 판단과 맥락 블록은 기존 4개 영양소만 본다(D7). 4개 값이 같고 포화지방만 다른 같은 메모의 식사는 "이미 기록"으로 나온다.
    - 되돌릴 때: 이전 빌드는 `satfat_exceeds_fat`가 든 history 줄을 읽지 못한다(`/history`, `telegram history`가 `HistoryReadError`).
    - 고치기(`change_estimate`)는 언제나 `language_estimate`다(기존 동작).
- 후속 후보:
  - `docs/telegram-llm.md` Output change 목록 보완: 저장된 범위가 있을 때의 status text `(estimated)` 꼬리표와 `nutrition day`의 `LDL:`·
    `LDL nutrients:` 줄(검증자 판단 1).
  - 정확한 소계와 추정이 섞인 날의 `(estimated)` 표시를 더 정확히 하기(ldl v1 규칙 변경이라 별도 스펙과 사용자 결정).
  - `nutrition status`에 추정 범위 합계를 정보로만 보이기(판정에는 쓰지 않음, 별도 스펙과 사용자 결정).
  - `edit.change_estimate`로 포화지방·섬유 고치기(D1-B).
  - lookup 답이 null인 영양소에 Codex 값을 남길지(지금은 통째로 바꿈, 사용자 결정).
  - 식이 콜레스테롤 필드와 추정(LDL-07), `오늘 누적`·짧은 요약에 표시(ldl D6), lookup 값을 카탈로그 음식으로 등록하는 안내.
  - `--general-estimate` 오류 문구에 `satfat`, `fiber` 넣기(ldl 후속 그대로).
  - Codex 검색이 가능해지면 lookup 없이 Codex가 검색(v2.5 후속).

### 열린 질문 (모두 게이트 1에서 정함, 2026-11-03)

1. **상태 판정이 바뀌지 않아도 괜찮은가?** 사용자가 원한 "빈 값 채우기"가 `/status`의 판정까지 뜻한다면, 이 스펙만으로는
   부족하다. 후속(추정 합계를 정보로 보이기)을 함께 계획할지 게이트 1에서 정한다.
   → 결정: D0-A. 판정은 그대로, 추정 합계 정보 줄은 후속 후보.
2. **D2 검색 시점**: 사용자의 말은 "없으면 검색"(L2)이다. 추가 호출 비용을 받아들일지, L3(부탁할 때와 상표 음식만)로 할지.
   → 결정: L3.
3. **정확도 표시**: 줄마다 `(추정)`만 둘지, `(추정, 정확도 미확인)`처럼 더 적을지(폭 약 6자 증가). 근거 문서에 LLM·웹 추정의
   포화지방·섬유 정확도 연구가 없다(ldl 열린 연구 질문 5). 필요하면 근거 문서를 갱신하고 다시 승인받는다.
   → 결정: `(추정, 정확도 미확인)`(Q3). 근거 문서는 갱신하지 않았다.
4. **D4·D5**: 규칙 6·7의 "빼고 알림"이 맞는지, 지방 없는 포화지방을 받을지.
   → 결정: D4 빼고 알림(고치기는 D4-가), D5-가 그대로 저장.
5. **`live-llm` 게이트 이름**: 템플릿과 `docs/specs/README.md`의 게이트 목록에 없다. 오케스트레이터가 이 이름을 받아들일지,
   기존처럼 implementer live 확인만 두고 실제 Telegram 확인을 "필수 아님"으로 둘지 정한다.
   → 결정: 새 게이트 없음(Q5). implementer live 확인(AC12)만 두고 휴대폰 확인은 선택이다.
