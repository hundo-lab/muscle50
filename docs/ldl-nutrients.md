# LDL Nutrients - Saturated Fat and Fiber v1

스펙: `docs/specs/ldl-nutrients.md`. 설계 결정: 2026-11-01 사용자 승인(모두 추천안). D1 (b) 새 append-only 표 + nutrient
CHECK(D1.1), D2-A, D3 두 상한과 `between_limits`, D4 (가) 사용자가 정하는 끼니 메모 %(기본값 없음), D5, D6 추천안,
D7 후속으로 미룸, D8 사용자가 실행 때 고름(기본값 없음), D9 섬유 음식 줄 근거 분리, D10 Telegram `change_estimate`가 저장된
범위를 유지. 근거 ID: `docs/evidence/training-nutrition-evidence.md` 7절(LDL-05, LDL-08, LDL-11).

## 목적과 non-goal

- 음식 fact에 **포화지방(g)**과 **식이섬유(g)**를 선택 값으로 남긴다. 값이 없으면 unknown이고 0이 아니다. 기존 fact와 끼니는
  모두 unknown이다.
- `nutrition day`, `nutrition meal show`, `nutrition food show/list`가 항목·끼니·하루 값을 보인다(완전하면 합계, 아니면 known
  subtotal과 값이 없는 항목).
- `nutrition status`가 하루 값을 사용자가 정한 포화지방 상한(에너지 %)과 섬유 하한(g/일)에 비교하고, 근거 문서의 참고값을 옆에
  적는다. 한 끼의 포화지방이 많으면 사용자 설정에 따라 메모 한 줄을 단다. 모두 **조언**이다.
- Non-goal:
  - 검사값(LDL-C 등), 지질 분류, 위험도, 경고 등급, 스타틴·상담 판단. 출력에 개인 수치가 없다.
  - 식이 콜레스테롤, 트랜스지방, 수용성 섬유, 식물성 스테롤 필드. 총지방 에너지 비율 목표.
  - 값을 이름이나 다른 영양소에서 추정하거나 0으로 채우는 일. 이미 기록된 끼니의 snapshot 갱신.
  - 목표 자동 계산, 운동 계획·`recommend`/`daily`·메뉴 순서·Telegram 요약 변경(D6). 조언이 목표 파일을 바꾸는 일.
  - Telegram LLM이 포화지방·섬유를 추정하는 일(D7, 후속). `schemas/nutrition_meal_v1.schema.json`과
    `infrastructure/nutrition_serialization.py`(교환 형식, CLI 출력 계약 아님).

## 명령 예시(합성 값)

```powershell
# 카탈로그 음식: --satfat/--fiber는 선택. 빼거나 unknown이면 unknown(0이 아님). 기존 4개 플래그는 그대로 필수.
muscle50 nutrition food add --id syn-oats --name SynOats --per 40 g --kcal 150 --protein 5 --carbs 27 --fat 3 --satfat 0.5 --fiber 4 --source nutrition_label --accuracy exact
# 이미 있는 음식에 값을 채우려면 4개 값을 다시 적은 새 fact 버전을 더한다.
muscle50 nutrition food fact add syn-rice --per 1 pack --kcal 300 --protein 5 --carbs 66 --fat 1 --fiber 1.2 --satfat 0.3 --source nutrition_label --accuracy exact

# 일반식 추정: satfat=/fiber= 범위. 이 둘만으로는 거부된다(kcal/protein/carbs/fat 중 하나가 필요).
muscle50 nutrition log --meal dinner --general --general-note SynBBQ --general-estimate language_estimate:kcal=800-1100,fat=50-70,satfat=15-25

# 목표(사용자 설정만). 7 또는 10은 사용자가 고른다(D8, 기본값 없음).
muscle50 nutrition target set satfat --max-energy-percent 7 --meal-note-percent 50
muscle50 nutrition target set fiber --minimum 25
muscle50 nutrition target set satfat --unset

muscle50 nutrition status --date 2026-11-05
muscle50 nutrition status --date 2026-11-05 --json
```

### `nutrition day`의 줄(값이 하나라도 있는 항목·끼니·날만)

```text
  1. SynOats (syn-oats) 80 g: kcal 300 | P 10 g | C 54 g | F 6 g
     source: nutrition_label/exact
     LDL: sat fat 1 g | fiber 8 g
  2. SynRice (syn-rice) 1 pack: kcal 300 | P 5 g | C 66 g | F 1 g
     source: nutrition_label/exact
     LDL: sat fat unknown | fiber 1.2 g
  Meal total: kcal 600 | P 15 g | C 120 g | F 7 g
  LDL nutrients: sat fat incomplete (known items only: 1 g) | fiber 9.2 g
...
LDL-related nutrients (consumed; compare: muscle50 nutrition status):
  Saturated fat incomplete (known items only: 21 g (estimated))
  Fiber         incomplete (known items only: 9.2 g)
  Unknown, not 0: saturated fat: 2026-11-05-breakfast-1 item 2 SynRice (syn-rice); 2026-11-05-dinner-1 item 1 일반식 (general-meal)
  Unknown, not 0: fiber: 2026-11-05-dinner-1 item 1 일반식 (general-meal)
```

- 추정 범위만 있는 항목(일반식 추정)은 `sat fat estimated 15-25 g`로 보이고, 합계에서는 값이 없는 항목이다(불완전).
- `(estimated)`는 기존 4개 영양소와 같은 규칙이다: 그 영양소에 estimated fact의 값이나 범위가 하나라도 있으면 붙는다.
- `food show/list`는 fact 줄 아래에 `LDL per 40 g: sat fat 0.5 g | fiber 4 g`를 붙인다(그 fact에 값이 있을 때만).

### `nutrition status`의 블록(LDL 목표가 있거나 그날 값이 있을 때만, 목표 참고 줄 뒤)

kcal 목표 2400 exact, `satfat --max-energy-percent 7 --meal-note-percent 50`, `fiber --minimum 25`:

```text
LDL-related nutrients (your targets; advice only, not a diagnosis):
  Saturated fat incomplete (known items only: 21 g (estimated)); limit < 7 % of energy [user setting; LDL-05 reference < 7 %]
                = under 18.7 g at your kcal target 2400 [design: 9 kcal/g]: above limit (the known items alone reach it)
  Fiber         incomplete (known items only: 9.2 g); target >= 25 g/day [user setting; LDL-08 reference >= 25 g]: cannot tell yet (incomplete)
    foods with fiber: oats, mixed grains, legumes [LDL-08; advice only]
    LDL diet pattern also uses soy/tofu protein and nuts [LDL-11; advice only]
  Unknown, not 0: saturated fat: 2026-11-05-breakfast-1 item 2 SynRice (syn-rice); 2026-11-05-dinner-1 item 1 일반식 (general-meal)
  Unknown, not 0: fiber: 2026-11-05-dinner-1 item 1 일반식 (general-meal)
  Meal note: 2026-11-05-lunch-1 saturated fat 20 g = 107.1 % of the day limit 18.7 g, at or above your setting 50 % [user setting; advice only]
```

다른 상태의 문구:

| 상태 | 문구 |
|---|---|
| 포화지방 `within_limit` | `within limit, 13 g below it` (+ 둘 다 완전하면 `logged energy share: 3 % (info only, not used for the status) [LDL-05; design: 9 kcal/g]`) |
| 포화지방 `above_limit`(완전) | `at or above limit, 1 g over` (기준이 "< P %"라서 같으면 넘은 것) |
| 포화지방 `above_limit`(불완전) | `above limit (the known items alone reach it)` |
| 포화지방 `between_limits` | `between the limits of your kcal range (14-21 g): depends on where in your kcal range you end` |
| 포화지방 `no_kcal_target` | `= no gram limit without a kcal target (muscle50 nutrition target set kcal ...): not judged` |
| `indeterminate` | `cannot tell yet (incomplete)` |
| 섬유 `target_reached` | `target reached` / 불완전이면 `target reached (the known items alone reach it)` |
| 섬유 `below_target` | `below target, 7.5 g to go` |
| `no_intake_logged` | `no meals logged` |
| 목표 없음 | `<값>; no target` |

- P = 10이면 `    LDL-05 also gives < 10 % for the general population (ESC) [LDL-05]` 한 줄이 붙는다. JSON `reference`는
  언제나 `7`이고 `reference_notes`에 `esc_general_population`이 들어간다.
- 섬유 음식 두 줄(D9)은 섬유 상태가 `below_target`이나 `indeterminate`일 때만 나온다.
- "No targets set" 줄은 4개 목표와 LDL 목표가 모두 없을 때만 나온다.

### `target show`

LDL 목표가 하나라도 있으면 4개 줄 뒤에 두 줄이 붙는다(없으면 이전과 byte-identical):

```text
  Saturated fat < 7 % of energy [user setting; LDL-05 reference < 7 %]; meal note at 50 % of the day limit [user setting]
  Fiber         >= 25 g/day [user setting; LDL-08 reference >= 25 g]
```

## 규칙

### 저장과 입력 검증

- 저장소는 migration 011의 `nutrition_fact_optional_nutrients`다(D1 (b)): fact와 영양소마다 한 행(`value`와/또는
  `minimum`/`maximum`). 행이 없으면 unknown이다. nutrient는 CHECK로 `saturated_fat_g`/`fiber_g`만 받는다(D1.1). min/max는 같이
  있거나 같이 없고, exact fact에는 범위가 없으며(트리거), update/delete는 트리거가 거부한다(append-only). 행은 fact와 같은
  transaction에서 쓴다. 기존 표는 바뀌지 않았다.
- 값은 기존과 같은 canonical decimal 또는 `unknown`(exit 1, `오류:`, 아무것도 쓰지 않음):
  - 음수·`1e3`·`NaN` 같은 비정규 숫자 거부.
  - 포화지방 > 총지방 거부(둘 다 점 값이면 그대로 비교, 범위면 satfat min > fat max) `[design: 포화지방은 총지방의 일부]`.
    섬유와 탄수는 비교하지 않는다.
  - 포화지방·섬유만 값이 있는 fact나 일반식 추정은 거부 `[design]`(4개 중 하나는 값이라는 기존 규칙 유지).
  - `food fact add`: 현재 fact가 아는 포화지방·섬유를 빼거나 `unknown`으로 주면 거부(기존 4개와 같은 이유: 영양소별
    supersession에서 옛 값이 계속 쓰인다). 같은 4개 값 + `--satfat`은 새 버전으로 받아들인다.
  - `satfat=`/`fiber=`의 min > max, 같은 키 두 번 거부.
- 기록 때 snapshot이 값도 그대로 복사한다. 나중의 카탈로그 새 버전은 기록된 끼니를 바꾸지 않고, `repeat`은 현재 카탈로그를,
  `meal merge`는 원래 snapshot을 쓴다. supersession은 영양소별이다(포화지방만 가진 새 fact는 포화지방만 대체).
  `meal merge`는 포화지방·섬유의 하루 합계가 바뀌면(항목 순서에 따른 Decimal 반올림) 4개 영양소처럼 거부한다.

### 합계(결측은 0이 아님)

- 항목·끼니·하루 합계는 모든 항목에 **점 값**이 있을 때만 `consumed`다. 아니면 `known_subtotal`(하한)과 값이 없는 항목.
- 추정 범위는 합계와 판정에 쓰지 않는다(기존 `nutrition-targets.md`와 같다).

### 판정(Decimal, 반올림 없이 판단, 표시만 0.1)

- 포화지방 상한 `L = kcal 목표 x P / 100 / 9`(D2-A). `9 kcal/g`는 `[design: 9 kcal/g]`(근거 문서의 행이 아니다).
- 비교는 모두 교차 곱셈이다(`g x 9 x 100 >= kcal x P`). L이 끝나지 않는 소수여도 "= L"을 정확히 판정한다.
- kcal 목표가 범위면 두 끝에서 `L_low`, `L_high`를 구하고(D3) 양쪽 끝에서 참인 결론만 낸다:
  - 완전 + `>= L_high`: `above_limit`. 완전 + `< L_low`: `within_limit`. 그 사이: `between_limits`.
  - 불완전 + known `>= L_high`: `above_limit`(excess null). 나머지 불완전: `indeterminate`. 불완전한 날에 "아래"라고 하지 않는다.
  - exact kcal 목표면 `L_low = L_high`이고 스펙 규칙 그대로다.
- 순서: `no_target`, `no_kcal_target`(포화지방만), `no_intake_logged`, 규칙.
- 섬유 하한 M: 완전 + `>= M` `target_reached`, 완전 + `< M` `below_target`과 `remaining`, 불완전 + known `>= M`
  `target_reached`(complete false), 나머지 불완전 `indeterminate`.
- `logged energy share`: kcal과 포화지방이 모두 완전하고 kcal > 0인 날만, 정보로만 보인다(판정에 쓰지 않음).
- 끼니 메모(D4 가): `--meal-note-percent N`이 있고, kcal 목표가 있고, 그 끼니의 포화지방이 완전하며, `끼니 g >= N % x L_high`일
  때만. `share_of_day_limit`는 정확한 성분(`g x 900 / (kcal_max x P)`)에서 계산한다. 메모는 텍스트 한 줄과 JSON `meal_notes`뿐이다.

### 근거 ID

| 숫자 | 출처 |
|---|---|
| 포화지방 `< 7 %` 에너지(참고값) | `[LDL-05]` KSoLA, ESC 고콜레스테롤혈증 |
| 포화지방 `< 10 %`(P = 10일 때만 문구) | `[LDL-05]` ESC 일반 |
| 섬유 `>= 25 g/일`(참고값) | `[LDL-08]` |
| 귀리, 잡곡, 콩류 | `[LDL-08; advice only]` |
| 두부·콩 단백, 견과(식단 패턴) | `[LDL-11; advice only]` |
| `9 kcal/g` | `[design: 9 kcal/g]` |
| 사용자 P, M, N | `[user setting]` |

근거 문서에서 확인하지 못한 숫자(AHA < 5-6 %, 트랜스지방 < 1 %)와 효과 크기(LDL-06)는 출력에 없다.

### 언제 보이는가(D5)

- `nutrition day`, `meal show`, `food show/list`(text와 JSON): 그 fact·항목·끼니·날에 포화지방·섬유 값이나 범위가 있을 때만.
  이 명령들은 목표 파일을 읽지 않는다(목표 파일이 깨져도 `day`는 지금처럼 동작한다).
- `nutrition status`: LDL 목표가 하나라도 있거나 그날 값이 있을 때만.
- 둘 다 없으면 모든 명령의 text와 JSON이 이 기능 전과 byte-identical이다.

## JSON(추가 key, 언제나 그 객체의 마지막 key)

- fact 항목(`food show/list --json`의 `facts[]`는 `active` 뒤, 항목의 `facts[]`는 마지막): `"ldl_nutrients": {"saturated_fat_g":
  {"value", "minimum", "maximum"} | null, "fiber_g": ... }`.
- 항목: `"ldl_nutrients": {"saturated_fat_g": {"value", "minimum", "maximum", "fact_id", "source_type", "accuracy"} | null, ...}`.
- 끼니(`revisions` 등 수정 key 뒤)와 `day --json`(`total` 뒤): `"ldl_nutrients": {"saturated_fat_g": {"complete", "estimated",
  "consumed", "known_subtotal", "missing_items"}, "fiber_g": ...}`.
- `status --json`(`goal_reference` 뒤): `ldl_nutrients`에 `advice_only: true`, `saturated_fat_g`(`target`, `limit_g {low, high}`,
  `limit_basis {calories_kcal_target, kcal_per_g: "9", evidence: ["design"]}`, `status`, `complete`, `estimated`, `consumed`,
  `known_subtotal`, `remaining_to_limit`, `excess`, `logged_energy_percent`, `missing_items`), `fiber_g`(`target`, `status`,
  `complete`, `estimated`, `consumed`, `known_subtotal`, `remaining`, `missing_items`, `advice`), `meal_notes`.
  `target`은 `{"kind", "value", ..., "source": "user_setting", "reference": {"id", "value"}}`이고 목표가 없으면 null이다.
- `target show --json`: LDL 목표가 있을 때만 `targets`에 `saturated_fat_g`, `fiber_g`가 4개 뒤에 붙는다.
- 모든 값은 정확한 Decimal 문자열이고 같은 데이터는 같은 bytes다.

## 목표 파일 schema 2

- LDL 목표가 하나라도 있을 때만 `schema_version: 2`로 쓴다. 둘 다 없으면 schema 1 그대로(byte 단위로 같다). 둘 다 지우면 다시
  schema 1이 된다.

```json
{
  "schema_version": 2,
  "targets": {
    "calories_kcal": {"kind": "exact", "value": "2400"},
    "protein_g": {"kind": "unset"},
    "carbohydrate_g": {"kind": "unset"},
    "fat_g": {"kind": "unset"},
    "saturated_fat_g": {"kind": "max_energy_percent", "value": "7", "meal_note_percent": "50"},
    "fiber_g": {"kind": "minimum", "value": "25"}
  }
}
```

- 읽기는 schema마다 정확한 key 집합이다. schema 1에 LDL key가 있거나 schema 2에 둘 중 하나가 없으면 거부, schema 2인데 둘 다
  unset이어도 거부한다. `meal_note_percent`는 문자열 또는 null.

## 읽기 전용 경로와 migration 전 DB

- `nutrition` 명령은 지금처럼 시작할 때 migrate한다(읽기 명령도 011을 적용한다).
- 읽기 전용 reader(`recommend`, `daily`, Telegram의 읽기, `SqliteNutritionReader`, `SqliteFoodCatalogReader`)는 공유
  `_load_meal`/`_load_profile`을 쓰고, 표가 없으면 모든 선택 영양소를 unknown으로 읽는다. `MINIMUM_SCHEMA_VERSION`은 3 그대로.
- Telegram bot의 기존 `pending_migrations` 거절이 migration 대기 중에 식사 기록·`/status`·`/day` 등을 막는다(새 코드 없음).

## 바뀌지 않는 출력

- 포화지방·섬유 값과 LDL 목표가 없으면: `nutrition food add/fact add/list/show`, `log`, `repeat`, `meal show/add-item/
  remove-item/replace-item/void/edit/merge`, `day`, `target set/show`, `status`, `recommend`, `daily`, 목표 파일.
- 값이나 목표가 있어도: `recommend`/`daily`(운동 계획과 영양 절 모두), Telegram `/status`·`/daily`·`/today` 요약, LLM 답장의
  `오늘 누적`(D6).
- 바뀌는 것(D6, 승인됨): Telegram `/day`, `/show`, `/log`, `/status full`은 CLI text를 그대로 전하므로 값이 있으면 새 줄이 보인다.
  코치는 `nutrition status --json`을 그대로 받으므로 새 `ldl_nutrients` key(advice_only, 검사값 없음)를 본다.
- `--help`와 argparse usage 줄: `food add`, `food fact add`, `target set`, `log`/`add-item`/`replace-item`의 `--general-estimate` 도움말.

## 테스트

- `tests/test_ldl_nutrients_domain.py`: 값 검증, 영양소별 supersession, 합계, AC7/AC8의 상태 표, 교차 곱셈, kcal 범위, 끼니 메모.
- `tests/test_ldl_nutrients_storage.py`: 010 DB 위의 011, append-only·CHECK·exact 트리거, round trip, snapshot·repeat·merge,
  merge 거부, 실패한 쓰기의 rollback, 011 전 DB의 reader와 `recommend --json`.
- `tests/test_ldl_nutrients_cli.py`: CLI text/JSON, 거부 표(아무것도 쓰지 않음), 목표 파일 schema 1/2, 근거 tag와 금지어, 결정성,
  이웃 명령 byte-identical.
- `tests/test_ldl_nutrients_telegram.py`: D10(메모만 고치기, 추정 고치기, 이전과 같은 SPEC).
- 갱신한 기존 테스트: migration 버전 목록(`test_database.py`, `test_cli.py`, `test_telegram_bot.py`),
  `test_nutrition_target_cli.py`의 `fiber --exact 30`(이제 exit 1, invalid choice 예는 `sodium`).

## Production migration 011 (gate 3)

통합 뒤 사용자 게이트다. main에 011이 들어가면 hook이 production `muscle50` 실행을 막으므로 1단계를 먼저 한다.

1. **통합 fast-forward 전에** 오케스트레이터가 main checkout에서 다음을 실행해 `C:\Users\hundo\muscle50-backups\pre011\`에 저장한다
   (D는 최근 기록이 있는 날):
   `nutrition day --date D --json`, `nutrition status --date D --json`, `nutrition food list --json`,
   `nutrition target show --json`, `recommend --date D --json`.
2. 통합하고 push한다. Telegram bot은 계속 돌며 migrating 명령을 거절한다.
3. Claude가 `muscle50.sqlite3`를 sqlite backup API로(읽기 전용 원본) `C:\Users\hundo\muscle50-backups\db_backup_<YYYYMMDD>_pre_migration011`에
   복사하고 SHA-256을 적는다. `config\nutrition_targets.json`도 복사한다.
4. 사용자가 쓰기 명령 하나를 실행한다(PowerShell 한 줄):
   `cd C:\Users\hundo\Desktop\MyProjects\muscle50; uv run muscle50 nutrition food list`
5. Claude가 읽기 전용으로 확인한다:
   - `schema_migrations`에 1..11이 한 번씩.
   - `sqlite_master`가 백업과 비교해 새 표, 그 autoindex, 트리거 3개만 다르다.
   - 기존 표의 행이 모두 백업과 같다(ATTACH read-only, 표마다 비교). 새 표는 0행.
   - `PRAGMA integrity_check`가 ok이고 `foreign_key_check`가 비어 있다.
   - 1단계 명령의 출력이 byte-identical이다(production에는 아직 LDL 값과 목표가 없다).
6. Telegram bot을 다시 시작해 D10 코드를 쓰게 한다. 확인이 실패하면 멈추고, 사용자 결정에 따라 백업에서 복원한다.

Live Garmin 확인은 필요 없다(Garmin 동기화 변경 없음). D7을 미뤘으므로 live LLM 확인도 없다.

## Known issues / limitations

- 이미 기록된 끼니는 snapshot을 유지하므로 카탈로그를 채워도 과거 날은 계속 unknown이다. 처음 몇 주는 대부분 불완전하고,
  `Unknown, not 0:` 목록이 길다(Telegram `/day`에도 그대로 보인다). 목록 길이 제한은 없다.
- 기존 음식에 포화지방·섬유를 채우려면 4개 값을 다시 적은 새 fact 버전이 필요하다.
- 포화지방 상한은 kcal **목표**에서 계산한다(D2-A). 실제 섭취 열량의 %와 다르다. 완전한 날에만 정보 줄이 실제 %를 보인다.
- 목표는 하나뿐이고 이력이 없다. `target set satfat --max-energy-percent P`는 끼니 메모 설정도 함께 바꾼다(`--meal-note-percent`를
  빼면 메모 없음).
- 판정은 점 값만 쓴다. 일반식 추정의 `satfat=`/`fiber=` 범위는 보이기만 하고 합계를 불완전하게 둔다.
- `meal show`의 `facts:` 줄은 4개 영양소의 fact 버전만 적는다. 선택 영양소를 옛 fact 버전에서 가져온 경우는 JSON `fact_id`에만 보인다.
- schema 2 목표 파일은 이전 빌드가 `unsupported schema_version 2`로 거부한다(되돌릴 때 한계). 되돌리려면 LDL 목표를 둘 다 지운다.
- 저장소는 선택 영양소 행이 그 fact와 같은 transaction에서 쓰였는지 schema로 증명하지 못한다. repository가 유일한 writer다.
- 포화지방 > 총지방 검사는 저장소가 아니라 domain 규칙이다(003의 나머지 Decimal 규칙과 같다).
- `nutrition_serialization.py`(교환 형식)는 선택 영양소를 싣지 않는다. 그 형식을 쓰면 포화지방·섬유가 빠진다.
- Telegram LLM은 아직 포화지방·섬유를 추정하지 않는다(D7). 카탈로그 음식으로 `/log`하거나 LLM 제안이 카탈로그 음식을 고르면
  snapshot에 값이 따라온다.
- 끼니 메모·섬유 음식 줄의 문구는 고정이고 순위나 처방이 아니다.
