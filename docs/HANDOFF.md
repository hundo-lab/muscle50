# Session Handoff

> **Frozen (2026-10-05).** 이 문서는 2026-10-05 시점의 이력이며 더 이상 갱신하지 않는다. 이후 기록은 통합된 스펙
> (`docs/specs/*.md`), 기능 문서(`docs/<feature>.md`), `README.md`, 통합 커밋 메시지에 있다(`CLAUDE.md` "Records").

Last updated: 2026-10-05

## Current task: Nutrition Meal Repeat v1 (2026-10-04)

Paseo worktree `nutrition-quick-log`(branch는 `feature/nutrition-quick-log`에서 `feature/nutrition-meal-repeat`으로 rename, base
`e13acfa` = main = origin/main). **local main으로 fast-forward 통합 완료(`e13acfa` → `42cf410`; commits `2d2ea84`, `42cf410`;
merge/rebase/squash/amend 없음, migration 없음).** 통합 후 main에서 pytest 917 passed, Ruff, mypy 118 files, `git diff --check`
통과, 임시 `MUSCLE50_HOME` smoke 통과, production DB/WAL/SHM/RAW untouched(evidence
`C:\temp\muscle50-evidence-20261004-nutrition-meal-repeat-integration\`). 이 integration docs commit 시점에 origin push는 하지
않았다(origin/main `e13acfa`). 개발 중 production DB/RAW/config 쓰기 없음(테스트·smoke는 모두 임시 `MUSCLE50_HOME`).

### What was attempted / completed

- Audit(2026-10-03~04): nutrition에 이전 식사 재사용/template/quick log/free-text/AI parser/unit conversion 모두 없음(`MealParser`는
  protocol뿐, alias는 중복 검사에만 쓰이고 `--item`은 food ID만). 비교(A repeat / B template / C 축약 문법·alias / D 자유 문장 /
  E AI / F meal void·unit 변환) 후 A를 승인받아 구현. "Nutrition status/guidance integration"과 "Nutrition Recommendation v1"은
  같은 작업(`8f267a2`/`caa7982`)이다.
- CLI `muscle50 nutrition repeat <meal_id> [--date] [--time] [--meal] [--additional] [--json]`, use case `RepeatMeal`: 원본 active
  item → `MealEntryItem`(food ID/quantity/unit) → `LogMeal.execute(..., repeated_from=<id>)`. 원본 snapshot을 복사하지 않고 현재
  catalog로 새로 snapshot. `catalog_fact_versions(item)` helper를 application으로 옮겨 `meal show` `facts:`와 fact-change note가
  공유(출력 불변). Text는 `render_repeated_meal`, JSON은 `render_logged_meal_json` 그대로.
- Stale docs 정리: CURRENT_STATE의 `caa7982` "origin push 안 함"(3곳, 실제로는 origin 포함), Known issues "음식당 CLI fact 1개",
  `nutrition-logging.md` Limitations "No recommendations", `nutrition-targets.md` "meal/food edit or delete" 미구현 문구.

### Files changed

신규 `tests/test_nutrition_meal_repeat.py`(17). 수정 `src/muscle50/application/nutrition_logging.py`, `src/muscle50/cli.py`,
`src/muscle50/presentation/nutrition_terminal.py`, `README.md`, `docs/nutrition-logging.md`, `docs/nutrition-targets.md`,
`docs/CURRENT_STATE.md`, 이 파일. Migration/schema 변경 없음.

### Checks run

- pytest 917 passed, `ruff check .`, `mypy src tests`(118 files), `git diff --check`; mutation 5종 검출; 임시 home CLI smoke.
- Production fingerprint before = after(CURRENT_STATE Verification, evidence `C:\temp\muscle50-evidence-20261004-nutrition-meal-repeat\`).
- `nutrition_terminal.py`의 기존 format 차이(`nutrition_context_payload` dict comprehension)는 base에도 있어 건드리지 않음. LF 유지.

### Known failures or risks

- Repeat은 원본과 숫자가 다를 수 있다(그 사이 fact version이 바뀌면 현재 fact 사용 — 의도된 동작, text note로 표시).
- Storage 오류(sqlite3.Error)는 `nutrition log`처럼 CLI traceback(rollback은 test로 검증).
- 원본 meal ID를 알아야 한다(`nutrition day --date <어제>`로 확인). 날짜/종류로 선택하는 기능은 없음.

### Recommended next action

main 통합은 완료됐다. origin push 여부 결정(별도 승인). 이후 후보: `--item`에서 이름/alias 조회(alias가 다른 food ID와 겹칠 수 있어 모호성 규칙 필요), meal void/merge.

## Previous task: Nutrition Meal Edit v1 (2026-10-03)

Paseo worktree `nutrition-meal-edit`(branch `feature/nutrition-meal-edit`, base `e1e66ed` = local main). Feature commit 하나
(`b234ac8`). 개발 중 production DB/RAW/config 쓰기 없음(테스트·smoke는 모두 임시 `MUSCLE50_HOME`).
**2026-10-03 local main으로 fast-forward 통합(`e1e66ed` → `b234ac8`, merge commit/rebase/squash 없음). Backup
`db_backup_20261003a_pre_migration8` 후 `uv run muscle50 nutrition food list`로 production에 migration 8을 적용했다. 기존 data는
backup과 동일했고 2026-10-02 day/status/recommend 출력도 byte 동일했다(CURRENT_STATE Verification). 이 docs commit과 함께
origin/main에 push.**

### What was attempted / completed

- Audit: 모든 meal 읽기(repository, `status`, read-only reader → `recommend`/`daily`)는 `_load_meal` 하나를 거치고 totals는
  매번 계산(cache 없음). Item은 snapshot fact를 소유하고 fact는 append-only(UPDATE/DELETE trigger) + item FK
  `ON DELETE RESTRICT` → item 삭제·재번호 불가. Migration 없이 제거하려면 trigger를 끄거나 기존 column을 숨은 flag로 써야
  해서 배제. **Migration 8**: append-only `nutrition_meal_item_removals`(PK `(meal_id, item_sequence)`, `removed_at`,
  `replaced_by_item_sequence`, update/delete trigger). 기존 table ALTER 없음.
- CLI `muscle50 nutrition meal show|add-item|remove-item|replace-item`(`food fact add`/`target set` 같은 nested group;
  `--item` 3-token은 `log`와 동일, `add-item`은 반복 가능·all-or-nothing). Repository `next_item_sequence`/`add_items`/
  `remove_item`/`replace_item`(각각 `BEGIN IMMEDIATE`, meal/item/번호/빈 식사 guard를 transaction 안에서 재확인).
  `LogMeal._snapshot_item` → 공용 `snapshot_item`(LogMeal 오류 메시지 불변).
- 결정: 빈 식사는 A(마지막 item 제거 거부). Item 번호 재사용 안 함(fact ID가 번호를 포함하고 global PK). `original_text`는
  log 시점 기록으로 유지. 같은 add 재실행은 item 2개(문서화). Metadata 수정·식사 삭제·병합·제거 취소는 범위 밖.
- `day` text/`_meal_lines` 기본 출력은 byte 불변; `facts:` 줄은 `meal show`/edit 출력에만.

### Files changed

신규 `src/muscle50/infrastructure/sqlite/migrations/008_nutrition_meal_item_removals.sql`, `tests/test_nutrition_meal_edit.py`(39).
수정 `src/muscle50/infrastructure/sqlite/nutrition_repository.py`, `src/muscle50/application/nutrition.py`(port),
`src/muscle50/application/nutrition_logging.py`, `src/muscle50/presentation/nutrition_terminal.py`, `src/muscle50/cli.py`,
`tests/test_database.py`/`tests/test_cli.py`(migration 1~8 기대값), `docs/nutrition-logging.md`, `README.md`,
`docs/CURRENT_STATE.md`, 이 파일.

### Checks run

- pytest 900 passed(861 + 39), `ruff check .`, `mypy src tests`(117 files), `git diff --check`. `ruff format`은 신규 test와
  `cli.py`/`nutrition_logging.py`/`nutrition.py`에만(`nutrition_repository.py`/`nutrition_terminal.py`의 기존 format 차이는 base에도
  있어 건드리지 않음). LF 유지.
- Mutation 8종 모두 검출(CURRENT_STATE Verification). 임시 home CLI smoke: 사용자 예시(닭가슴살 200 g → 햇반·바나나 추가 →
  1 meal 3 items, 제거/교체/오류 메시지).

### Known failures or risks

- Production DB는 이제 migration 8이다. 되돌리려면 `db_backup_20261003a_pre_migration8`(migration 1~7)을 쓴다. Read-only
  `recommend`는 migration 8 전 DB도 읽음(test 있음).
- 제거는 되돌릴 수 없음(append-only). Storage 오류(sqlite3.Error)는 기존처럼 CLI traceback(rollback은 검증됨).
- 이미 `--additional`로 쪼개진 2026-10-02 식사는 그대로(Meal Merge는 별도 feature). 원하면 add-item으로 한 식사를 완성할 수
  있지만 남은 별도 식사를 지울 방법은 없음(마지막 item 제거 거부).

### Recommended next action

필요하면 Meal Merge / meal metadata edit 설계.

## Previous task: Nutrition fact versioning (2026-10-03)

Paseo worktree `nutrition-food-facts`(branch `feature/nutrition-food-facts`, base `55364fc` = local main). 하나의 feature
commit만 만들었다. Production DB/RAW/config 쓰기 없음(테스트·smoke는 모두 임시 `MUSCLE50_HOME`).
**2026-10-03 local main으로 fast-forward 통합 완료(`55364fc` → `5e3a2c8`, merge commit/rebase/squash 없음). 이후 push되어
origin/main `e1e66ed`에 포함.** 통합 후 pytest 861 passed, `ruff check .`, `mypy src tests`, `git diff --check` 통과.

### What was attempted / completed

- Audit: food identity = `nutrition_food_profiles.profile_id`; nutrition = append-only `nutrition_facts`(UPDATE/DELETE trigger),
  `supersedes_fact_id`(같은 owner·unit trigger), 선택은 nutrient별 supersession 후 source priority > accuracy > confidence >
  created_at. `SqliteFoodNutritionRepository.append_nutrition_fact`(단일 `BEGIN IMMEDIATE`)가 이미 있었고 CLI만 없었다.
  `LogMeal`은 same-unit fact history를 item 소유 fact로 snapshot → 과거 식사는 catalog와 무관. **Migration 불필요.**
- CLI `muscle50 nutrition food fact add <food_id> ...`(`food add`와 같은 fact flag; `update`는 append-only와 맞지 않아 배제,
  `target set`처럼 nested group). Use case `AddFoodFact` + `NewFoodFact`/`AddedFoodFact`, `food add`와 validation 공유
  (`_check_catalog_fact`, CLI `_add_fact_arguments`/`_new_food_fact`).
- Activation 규칙과 거부 조건: `docs/nutrition-logging.md` "Add a new nutrition fact version". 핵심: v2(`food_database`
  300)가 v1(`user_provided` 500)을 이기는 건 supersession 덕분이고 supersession은 nutrient별이라, known → unknown은 거부하고
  추가 후 `select_preferred_fact` 결과가 nutrient마다 새 fact(또는 None)인지 검증한다(3-version gap 방지).
- Presentation: `food show` text에 `replaces <fact>` 표시, meal item `source:` 줄은 선택된 fact provenance만.

### Files changed

신규 `tests/test_nutrition_food_facts.py`(19 tests: A–G — B는 과거 날짜의 `nutrition day`/`status`/`recommend` text·JSON을 v2
추가 전후 byte 비교 —, storage-failure rollback, 3-version gap, ambiguous head).
수정 `src/muscle50/application/nutrition_logging.py`, `src/muscle50/cli.py`, `src/muscle50/presentation/nutrition_terminal.py`,
`docs/nutrition-logging.md`, `README.md`, `docs/CURRENT_STATE.md`, 이 파일.

### Checks run

- `uv run --extra dev pytest` 861 passed(기존 842 + 19), `ruff check .`, `mypy src tests`(116 files), `git diff --check` 통과.
  `ruff format`은 신규 test 파일에만(`nutrition_terminal.py`의 format 차이는 base `55364fc`에서도 동일하게 있는 기존 상태라 건드리지 않음). LF 유지.
- Mutation check: supersession을 빼면 A/C/E/guard test가 실패함을 확인.
- 임시 home CLI smoke: 사용자 예시 v1(per 200 g, P 36만) → 식사 → v2 추가 → 과거 `day` text byte 동일, 이후 식사 kcal 240 |
  P 36 | C 4 | F 8 (food_database/estimated), kcal `unknown` v3는 거부.

### Known failures or risks

- 현재 fact 확인과 append가 한 transaction이 아님: 동시에 두 번 실행하면 같은 fact를 둘 다 supersede할 수 있음(이후 추가는
  ambiguous로 거부). 단일 사용자 CLI라 문서화만.
- Storage 오류(sqlite3.Error)는 기존 `food add`처럼 CLI에서 traceback으로 나온다(rollback은 검증됨).
- 다른 unit의 fact 추가(예: per pack → per 210 g)와 이름/alias 변경은 범위 밖.

### Recommended next action

origin push 여부 결정(별도 승인). 실제 `chicken-breast`에 v2를 추가하기 전에 production DB 백업 권장.

## Previous task: Nutrition → Daily/Recommendation Integration v1 (2026-10-02)

Paseo worktree `nutrition-recommendation`(branch `feature/nutrition-recommendation`, base `f07f5a2` = local main = origin/main).
**2026-10-02 local main으로 fast-forward 통합 완료(`f07f5a2` → `caa7982`, merge commit/rebase/squash 없음). origin push 안
함(별도 승인).** 통합 검증은 CURRENT_STATE Verification 참고. 규칙·JSON 계약: `docs/nutrition-recommendation.md`.

### What was attempted / completed

- Audit: `recommend` = `BuildTrainingRecommendation`(read-only `SqliteAnalyticsReader`) → domain `build_training_recommendation`
  (모든 정책). `daily` = `RunDailySync`가 같은 use case를 조합하고 JSON에 standalone `recommend --json`을 그대로 넣는다.
  `SqliteMealRepository`는 읽기에도 mkdir/DB 생성/WAL 설정을 해 read-only `recommend`에 쓸 수 없음을 확인.
- 경계: 추천을 먼저 만들고(불변), `BuildNutritionContext`가 같은 날짜의 `ShowDailyNutritionStatus`(= `nutrition status`)를
  실행한 뒤 순수 정책 `build_nutrition_guidance`가 status + training fuel context로 행동을 고른다. Nutrition은 추천 입력이
  아니므로 운동을 바꾸거나 취소할 수 없다. Read-only `SqliteNutritionReader` 추가, `ShowDailyIntake`/
  `ShowDailyNutritionStatus` 파라미터를 좁은 `MealReader` protocol로 변경(기존 호출 그대로).
- 출력: text `== Nutrition ...` 절(목표 미설정이면 없음 → 기존 text와 byte 동일), JSON 끝 `nutrition` key(기존 필드 불변).
  `daily`는 추천이 만들어졌을 때만 붙이고 단계/`ok`에 영향 없음.

### Files changed

신규: `src/muscle50/domain/nutrition_guidance.py`, `src/muscle50/application/nutrition_recommendation.py`,
`src/muscle50/infrastructure/sqlite/nutrition_reader.py`, `tests/test_nutrition_guidance.py`, `tests/test_recommend_nutrition.py`,
`tests/test_nutrition_reader.py`, `docs/nutrition-recommendation.md`. 수정: `src/muscle50/cli.py`, `src/muscle50/application/daily_sync.py`,
`src/muscle50/application/nutrition.py`(`MealReader`), `src/muscle50/application/nutrition_logging.py`,
`src/muscle50/application/nutrition_targets.py`(파라미터 타입만), `src/muscle50/presentation/nutrition_terminal.py`
(`nutrient_status_line`/`nutrient_status_payload` 공개 + 추천용 renderer; `nutrition status` 출력 불변),
`src/muscle50/presentation/terminal.py`(optional `nutrition` 인자), `tests/test_daily_sync.py`(+4), `README.md`,
`docs/nutrition-targets.md`, `docs/training-recommendation.md`, `docs/CURRENT_STATE.md`, 이 파일. Migration 없음.

### Checks run

- `uv run --extra dev pytest` 842 passed, `ruff check .`, `mypy src tests`(115 files), `git diff --check` 통과. `ruff format`은
  신규 파일에만(기존 파일은 repo 전체가 format 미적용 상태라 건드리지 않음), 모든 파일 LF.
- Acceptance(임시 home, production DB의 read-only 복사 + 합성 nutrition): CURRENT_STATE Verification 참고.
- Production: read-only `recommend` text/JSON만 실행(`no_targets_configured`). Fingerprint before/after에서 DB/WAL/table/RAW/
  home 파일 동일, `config\` 생성 없음, `-shm` mtime만 변화(내용 동일, 기존 analytics reader도 동일 — `shm_control.txt`).
  Evidence `C:\temp\muscle50-evidence-20261002-nutrition-recommendation\`.

### Known failures or risks

- D 하루 섭취만 사용; 시각을 모르므로 아침엔 대부분 below(행동 문구는 "if meals remain today").
- `fuel_relevant`는 계획 기반(실제 운동 여부/시각 모름). Fat 행동 없음. 목표 history 없음(과거 날짜도 현재 목표).
- SQLite read-only WAL 열기가 `-shm` mtime을 갱신(기존 동작).

### Recommended next action

main 통합은 완료됐다. origin push 여부 결정(별도 승인). 실제 목표를 설정한 뒤(`nutrition target set`) 하루 동안
`recommend` 문구가 과하거나 부족하지 않은지 확인하는 것을 권장.

## Previous task: Nutrition Targets + Daily Nutrition Status v1 (2026-10-02)

Paseo worktree `nutrition-targets`(branch `feature/nutrition-targets`, base `7f4a4ef` = local main = local origin/main ref).
**2026-10-02 local main으로 fast-forward 통합 완료(`7f4a4ef` → `1549c4a`, merge commit/rebase/squash 없음). origin push 안
함(별도 승인).** 통합 후 main에서 pytest 789 passed, ruff/mypy/`git diff --check` 통과, production fingerprint before = after
(`C:\temp\muscle50-evidence-20261002-nutrition-targets-integration\`). 상세 규칙·JSON 계약: `docs/nutrition-targets.md`.

### What was attempted / completed

- Audit: Nutrition Core aggregate(`totals`/`known_subtotals`/`incomplete_fields`/`estimated_fields`, 빈 날 = 전부 incomplete),
  `ShowDailyIntake`/`ItemIntake.missing_fields`, migration 003(목표용 table 없음), 설정 관례(`TrainingGoals`는 code default,
  `AppPaths` 아래 local data). **Migration 불필요**: 목표는 fact history가 아닌 작은 사용자 설정 → `<home>\config\
  nutrition_targets.json`(schema_version 1, decimal 문자열, 원자적 write, strict read, 읽기는 파일 생성 안 함).
- Domain `ExactTarget`/`RangeTarget`/`NutritionTargets`(unset = None, 0 거부), `evaluate_nutrient`(aggregate 재사용, 재집계
  없음). Application `SetNutritionTarget`/`ShowNutritionTargets`/`ShowDailyNutritionStatus`(missing item provenance).
  Presentation text/JSON. CLI `nutrition target set|show`, `nutrition status`.
- 불완전 데이터: consumed/remaining/excess null, known subtotal + missing items 표시, known > 상한일 때만 `above_*` 확정.
- 기존 출력 변경은 `nutrition day` text scope 문장 1줄("Consumed intake only. Compare with targets: muscle50 nutrition
  status")과 `nutrition` help 문구뿐(day JSON 불변, `scope: intake_only` 유지).

### Exact commands

```powershell
uv run muscle50 nutrition target set protein --range 170 180   # 예시 값
uv run muscle50 nutrition target set fat --exact 80
uv run muscle50 nutrition target set kcal --unset
uv run muscle50 nutrition target show [--json]
uv run muscle50 nutrition status [--date D] [--json]
```

### Files changed

신규: `src/muscle50/domain/nutrition_targets.py`, `src/muscle50/application/nutrition_targets.py`,
`src/muscle50/infrastructure/nutrition_target_store.py`, `tests/test_nutrition_targets.py`, `tests/test_nutrition_target_store.py`,
`tests/test_nutrition_target_cli.py`, `docs/nutrition-targets.md`. 수정: `src/muscle50/cli.py`, `src/muscle50/config.py`
(`nutrition_targets_path`, `ensure_directories`는 불변), `src/muscle50/presentation/nutrition_terminal.py`,
`tests/test_nutrition_cli.py`(scope 문장), `README.md`, `docs/nutrition-logging.md`, `docs/nutrition-core.md`,
`docs/CURRENT_STATE.md`, 이 파일.

### Checks run

- `uv run --extra dev pytest` 789 passed, `ruff check .`, `mypy src tests`(109 files), `git diff --check` 통과. `ruff format`은
  새/수정한 파일에만 적용, 모든 파일 LF.
- CLI acceptance(합성 값, 임시 home `C:\temp\muscle50-evidence-20261002-nutrition-targets\acceptance-home`): exact/range 설정,
  0/역범위 거부, 합성 음식 3개(fat unknown 1개) + 식사 2개, status text/JSON(below, within range, indeterminate, known
  subtotal로 확정된 above_target, 식사 없는 날), JSON 2회 sha256 동일. 출력 `acceptance.txt`.
- Production fingerprint before = after(`before.json`/`after.json`, 같은 폴더). Production에서 nutrition 명령 실행 안 함.

### Known failures or risks

- 목표 history 없음: 목표를 바꾸면 과거 날짜 status도 새 목표로 비교된다(meal data는 불변).
- 식사 0개인 날은 `no_intake_logged`; "먹지 않음" 기록 방법 없음.
- Text는 0.1 반올림(0으로 반올림될 0보다 큰 gap은 `<0.1`로 표시), 정확한 값은 `--json`.
- Recommend/daily는 nutrition-aware 아님. 식사/음식 수정·삭제, 단위 변환은 여전히 없음.

### Recommended next action

1. origin push 여부 결정(별도 승인; local main은 origin/main보다 앞서 있다).
2. 사용자 본인 목표를 production에서 직접 설정(`nutrition target set ...`) — agent가 대신 설정하지 않는다.
3. 후속 후보: 식사 정정(void/replacement) 설계, 목표 history(effective date), 요일/운동일 목표, recommend 연동.

## Previous task: Nutrition Logging MVP (2026-10-02)

Paseo worktree `nutrition-logging`(branch `feature/nutrition-logging`, base `8845b41` = local main = origin/main).
**Feature commit 완료. main merge/rebase/push 안 함.** 상세 사용법·규칙: `docs/nutrition-logging.md`.

### What was attempted / completed

- Nutrition Core audit: `FoodNutritionProfile`/`NutritionFact`/`Meal`/`MealItem`, unit-equality scaling, `aggregate_meal`/
  `aggregate_day`, repository create-only `save`, append-only fact trigger, `003_nutrition.sql`. 새 model/migration 없이 구현.
- `application/nutrition_logging.py`: `AddFood`, `ListFoods`, `ShowFood`, `LogMeal`(logged unit의 catalog fact history를
  supersession link 재매핑과 함께 snapshot, unit 불일치 거부,
  같은 날짜·meal type 중복은 `--additional` 필요), `ShowDailyIntake`(item별 missing nutrient 계산 포함).
- `presentation/nutrition_terminal.py`: text(표시용 0.1 반올림, incomplete/estimated 명시, ASCII + 음식 이름)와 JSON(exact
  Decimal 문자열, 고정 순서).
- `cli.py`: `muscle50 nutrition food add|list|show`, `nutrition log`, `nutrition day`; `_local_timezone`(fixed offset).
- `FoodNutritionRepository.list_all()` port + SQLite 구현.
- Acceptance(합성 값): 닭가슴살 100 g / 계란 1 count / 햇반 1 pack / 바나나 1 piece → 2026-10-02 breakfast 200 g / 2 count /
  1 pack / 1 piece. `tests/test_nutrition_cli.py::test_acceptance_*`, `tests/test_nutrition_logging.py::
  test_breakfast_acceptance_scenario_persists_items_and_totals`.

### Exact commands

```powershell
uv run muscle50 nutrition food add --id chicken-breast --name 닭가슴살 --per 100 g --kcal N --protein N --carbs N --fat N|unknown --source nutrition_label --accuracy exact [--source-ref TEXT] [--alias NAME]
uv run muscle50 nutrition food list [--json]
uv run muscle50 nutrition food show chicken-breast [--json]
uv run muscle50 nutrition log [--date D] --meal breakfast [--time HH:MM] --item chicken-breast 200 g --item egg 2 count [--additional] [--json]
uv run muscle50 nutrition day [--date D] [--json]
```

### Files changed

`src/muscle50/application/nutrition_logging.py`(신규), `src/muscle50/presentation/nutrition_terminal.py`(신규),
`src/muscle50/cli.py`, `src/muscle50/application/nutrition.py`(`list_all` port), `src/muscle50/infrastructure/sqlite/
nutrition_repository.py`(`list_all`), `tests/test_nutrition_logging.py`(신규), `tests/test_nutrition_cli.py`(신규),
`tests/test_nutrition_repository.py`, `docs/nutrition-logging.md`(신규), `docs/nutrition-core.md`, `README.md`,
`docs/CURRENT_STATE.md`, 이 파일.

### Checks run

- `uv run --extra dev pytest` 682 passed, `ruff check .`, `mypy src tests`(103 files), `git diff --check` 통과. `ruff format`은
  새 파일과 `cli.py`에만 적용(`nutrition_repository.py`는 base부터 미포맷이라 건드리지 않음). 모든 파일 LF.
- Production DB/RAW fingerprint before = after(`C:\temp\muscle50-evidence-20261002-nutrition-logging\before.json`/`after.json`).
  Production에서 nutrition 명령을 실행하지 않았다.

### Known failures or risks

- 수정/삭제 없음(append-only fact + RESTRICT FK). 잘못 기록한 식사는 현재 CLI로 고칠 수 없다 — 중복 기록 guard만 있다.
- `--time` 없는 식사는 local 00:00로 저장되어 `--time 00:00`과 구분되지 않는다.
- 실제 production catalog는 비어 있다(사용자가 라벨 값으로 직접 입력해야 함). 실제 음식 값은 repo에 넣지 않았다.
- `docs/CURRENT_STATE.md`의 Daily orchestration "origin/main은 `c06a36c` 그대로" 문장은 stale이었다 — 2026-10-02
  `git ls-remote origin refs/heads/main` = `8845b41`로 확인해 정정했다.
- Snapshot은 처음에 nutrient별 winner fact만 supersession 없이 복사했는데, 일부 nutrient만 덮는 catalog 정정(예:
  protein-only user fact가 label fact를 supersede)에서 item 선택이 catalog와 달라질 수 있었다(CLI로는 도달 불가). 같은 unit의
  fact history 전체를 link 재매핑과 함께 복사하도록 follow-up commit에서 수정했고 회귀 테스트
  (`test_partial_correction_selects_per_nutrient_exactly_as_the_catalog_does`, 수정 전 코드에서 실패 확인)를 추가했다.

### Recommended next action

1. 사용자 검토 후 `feature/nutrition-logging`을 main으로 fast-forward 통합(별도 승인), push는 별도 승인.
2. 실제 라벨 값으로 production catalog 입력 후 하루 기록 사용해 보기.
3. 다음 기능: nutrition targets(별도 feature). 식사 정정(void/replacement) 설계는 그 전에 필요할 수 있다.

## Previous task: Daily orchestration `muscle50 daily` (2026-10-02)

Paseo worktree `daily-sync`(branch `feature/daily-sync`, base main = origin/main `c06a36c`).
**완료: 2026-10-02에 local main으로 fast-forward 통합(`c06a36c` → `8b08773`, merge commit/rebase/squash 없음). origin push
안 함(별도 승인).** Branch와 worktree는 유지한다.

### Production live verification (2026-10-02, 사용자 실행)

- 첫 실행: 모든 단계 ok. activities new 0, load_metrics 쓰기 0(unchanged 800), recovery created 1 / updated 1 →
  저장된 recovery가 2026-10-02까지, recommendation ok.
- 바로 이어 2회째: activities new 0, load_metrics 쓰기 0, recovery unchanged 2, recommendation ok. 실제 production에서
  idempotency 확인. 통합·gates 중에는 Garmin live 호출을 하지 않았다.

### What was attempted / completed

- 평소 4~5개 명령(`garmin activities`, `garmin backfill-load-metrics`, `garmin recovery --from/--to`, `recommend`)을
  `muscle50 daily` 하나로 대체. 기존 use case를 조합만 하는 `application/daily_sync.py`(`RunDailySync`): Garmin 로그인
  1회 → activities D-1~D → load metrics → recovery D-1~D → 오늘 추천. 규칙·저장·normalization 중복 없음.
- 운동 후: `muscle50 daily --after-workout`(activities + load metrics만, recovery·추천 `skipped`).
- 실패 규칙과 출력 형식은 `CURRENT_STATE.md` Implemented의 Daily orchestration 항목 참고. 요약: sync 단계는 서로 독립,
  하나라도 `failed`/`not_run`이면 추천을 만들지 않고 exit 1, 이미 저장된 작업은 유지, 같은 명령 재실행은 안전.
- `--json` 출력의 `"recommendation"`은 standalone `recommend --json`과 같은 문서. Text는 단계 블록 뒤에 기존 recommend
  text를 그대로 붙인다.

### Daily workflow (exact commands)

```powershell
uv run muscle50 daily                         # 운동 전(시계가 아침 데이터를 올린 뒤): sync + 오늘 자동 추천
uv run muscle50 daily --focus shoulders       # focus 지정; --avoid MUSCLE 반복 가능, --json 가능
uv run muscle50 daily --after-workout         # 운동 후(시계 sync 뒤): activity + load metric만
uv run muscle50 daily --date 2026-10-02       # 날짜 직접 지정
```

실패 시: 출력의 `FAILED stages:` 줄을 확인하고 같은 명령을 다시 실행한다(idempotent). 그 사이 저장된 데이터만으로 계획이
필요하면 `uv run muscle50 recommend --date <D>`(read-only).

### Files changed

`src/muscle50/application/daily_sync.py`(신규), `src/muscle50/cli.py`(`daily` parser/handler, `_today`, stderr prompt),
`src/muscle50/presentation/terminal.py`(`render_daily_sync`, `render_daily_sync_json`),
`src/muscle50/application/ingest_activity_range.py`(`RangeIngestOutcome.warnings` 기본값 `()` 추가 — 이미 있던 activity별
Garmin endpoint 경고를 버리지 않고 전달; `garmin activities` 출력 불변), `tests/test_daily_sync.py`(신규, 32), `README.md`,
`docs/CURRENT_STATE.md`, 이 파일.

### Checks run

- `uv run --extra dev pytest` 614 passed, `ruff check .`, `mypy src tests`(99 files), `git diff --check` 통과.
- Production DB/RAW fingerprint before = after(구현·테스트는 임시 home과 fake Garmin만 사용).

### Known failures or risks / still manual

- `garmin refresh`(Connect 수정 후), InBody import, Garmin 첫 로그인/재로그인(MFA), 예약 실행은 여전히 수동.
- Sync coverage 미기록, 기본 날짜는 이 컴퓨터 날짜, 오늘 recovery는 시계 아침 sync 전에는 partial.
- Activity endpoint 경고(예: exercise sets 없이 저장)는 처음 저장한 실행에서만 보이고 이후 실행은 그 activity를 건너뛴다 —
  경고에 나온 `garmin refresh <id>`로 복구.
- Live 검증은 2026-10-02에 완료됐다(위). Live 검증 날에는 새 activity가 없어서 실제 계정의 activity 가져오기와 load metric
  채우기는 아직 0건 경로만 확인됐다(fake Garmin 테스트로는 둘 다 검증).
- `CURRENT_STATE.md`의 daily 통합 표기는 통합 docs commit에서 갱신했다.

### Recommended next action

1. origin push 여부 결정(별도 승인; local main은 origin/main보다 앞서 있다).
2. 운동이 있는 날 `uv run muscle50 daily --after-workout` 결과로 실제 activity 가져오기 + load metric 경로 확인.
3. 다음 P0: Nutrition meal logging MVP(`feature/nutrition-logging`).

## Previous task: Progression Hardening v1 (2026-10-01)

Paseo worktree `progression-hardening`(branch `feature/progression-hardening`, base main = origin/main `4f26ec2`).
**완료: 2026-10-02에 main으로 fast-forward 통합(`4f26ec2` → `13d5ed2`)하고 origin에 일반 push했다. main = origin/main =
GitHub main `13d5ed2`.** Branch `feature/progression-hardening`(`13d5ed2`)과 worktree는 의도적으로 유지한다.

### Integration (2026-10-02)

- `git merge --ff-only feature/progression-hardening`(merge commit/rebase/cherry-pick/force 없음), 이후 `git push origin
  main`(일반 push). ahead/behind 0/0, working tree clean.
- 통합 후 main gates: pytest 582 passed, `ruff check .`, `mypy src tests`(97 files), `git diff --check` 통과.
- Production read-only 검증 통과(`garmin refresh` 미실행): progression smoke와 2026-10-01 auto/push/pull/legs/shoulders
  회귀 비교(`CURRENT_STATE.md` Verification 2026-10-02). Production DB/RAW fingerprint before = after.

### What was attempted / completed

1. Read-only audit(증량 위치, 모든 trigger의 production 결과)과 cap 보정 분석(연속 session 증량 분포) 후 사용자가
   15% 승인. Evidence `C:\temp\muscle50-evidence-20261001-progression-audit\`(`loads.*`, `increases.*`, `simulate.*`,
   `cap_analysis.py`, `cap.txt`, `cap_families.txt`).
2. `plan_progression`의 상한 분기 안에서만 step 결정: 애매한 label(`AMBIGUOUS_LOAD_LABELS`) → `load_kg` null +
   `smallest_available_direction_unknown` + 양방향 guidance; 2.5 kg ≤ 15% × work load → 기존 +2.5; 그 외 → null +
   `smallest_available`. 새 `ProgressionTarget` 필드 `load_increase_from_kg`, `load_step`(기본 None, 끝에 추가).
   Regression/recovery/rest rule override는 그대로 뒤에서 숫자 `maintain`으로 덮고 새 필드는 None. Low confidence
   판정은 숫자 유무와 무관하게 reference load 기준(동작 불변).
3. `terminal._prescription`: `@ next available step above 6 kg`, 애매한 label `@ one smallest available step from ~8 kg
   (less if assistance, more if added resistance)`. 숫자 목표 text는 byte 단위로 기존과 같다.
4. 테스트 8개(domain 7 + CLI 1). 문서: `training-recommendation.md` "증량 step" 절(schema, 15% 근거), 검증 절, 한계.

### Files changed

`src/muscle50/domain/strength_recommendation.py`, `src/muscle50/presentation/terminal.py`,
`tests/test_strength_recommendation.py`, `tests/test_recommend_cli.py`, `docs/training-recommendation.md`,
`docs/CURRENT_STATE.md`, 이 파일.

### Checks run

- `uv run --extra dev pytest` 582 passed, `ruff check .`, `mypy src tests`(97 files), `git diff --check` 통과.
  `ruff format`은 baseline에 무관한 drift(16 files, `terminal.py` 포함)가 있어 전체 적용하지 않았다.
- 신규 8개 테스트는 base src(`git archive HEAD`, 상수만 shim)에서 모두 실패.
- Production read-only 465 run before/after(`compare_impl.txt`): 불변식 위반 0, 바뀐 progression 54 항목(위
  CURRENT_STATE Verification). 재실행 byte-identical. Fingerprint before = after.

### Known failures or risks

- 15% 근거는 소수 사례(하한: 20 → 22.5 한 번, 상한: 10-19.9 kg 증량 5개). 16.7-20 kg trigger는 데이터에 없다.
- 증량 후 reps 재시작(상한 - 4)은 작은 무게에서도 그대로(6 kg × 20 → 다음 step × 16). 별도 검토 후보.
- `load_kg: null`을 숫자로 가정하던 외부 consumer가 있다면 `action`/`load_step`을 봐야 한다(repo 안 consumer는
  terminal뿐이며 갱신됨).
- 장비별 실제 증량 단위는 모른다. 15%를 넘는 증량은 숫자 없이 "next available step" 안내만 한다. 15%는 숫자 목표 신뢰
  기준이지 생리학적 최적값이 아니다.
- Progression v2(정확한 label별 장비 증량 단위 학습)는 충분한 데이터가 쌓인 뒤에만 검토할 향후 작업이다.

### Recommended next action

1. 통합·push는 완료됐다(위 Integration). 남은 결정 없음.
2. 이후 후보: 작은 무게 증량 후 reps 재시작 규칙 검토.

## Previous task: Recommendation Hardening v1 integration on local main (2026-10-01)

Paseo worktree `integration-recommendation-hardening`(branch `integration/recommendation-hardening`, base local main
`aba8cfe` = Taxonomy coverage; origin/main `8b259e7`). **통합 후보 commit 완료. main merge/fast-forward/push 안 함.**
원본 `feature/recommendation-hardening`(`272761a`)과 `feature/taxonomy-coverage`(`aba8cfe`)는 건드리지 않았다.

### What was attempted / completed

1. `5dd2af7`, `272761a`를 순서대로 cherry-pick(이 branch에서 `5fbdd56`, `38a23ae`). 충돌은 `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`뿐이었고 두 기능의
   상태/이력을 모두 남겨 해소했다(Hardening = 그 당시 current task, Taxonomy coverage = previous task).
2. 통합 수정 commit 1개:
   - 테스트 3개(`test_no_rule_sets_are_warned_about_but_never_counted`, `test_requested_focus_warns_when_no_rule_work_
     yesterday_may_hide_the_rest_rule`, `test_focus_names_no_rule_work_that_its_category_puts_in_the_focus`)가 쓰던 실제
     Garmin label(`PULL_UP/WIDE_GRIP_LAT_PULLDOWN`, `ROW/BENT_OVER_ROW_WITH_BARBELL`)이 `aba8cfe`로 매핑되어 실패 →
     test-only 미매핑 label `PULL_UP/TEST_ONLY_UNMAPPED_PULLDOWN`, `ROW/TEST_ONLY_UNMAPPED_ROW`(category rule이 있어
     힌트가 유지됨)로 교체. Taxonomy rule 변경 없음.
   - 조정 원인 표기 버그 수정(`strength_recommendation.py`, `terminal.py`): 48 h rest rule이 올린 reduce를 "recovery
     reduce"로 쓰던 문제. Recovery 줄은 recovery 자신의 level, set 감소/부족분/progression 문구는 실제 원인
     (`48 h rest rule reduce`, 둘 다면 둘 다), heading은 두 level이 다를 때만 `Recovery adjustment: hold; session
     adjustment: reduce`. 결정(level, set, load, focus, recovery, swim)은 불변. 규칙은
     `docs/training-recommendation.md` "조정 원인 표기".
   - 회귀 테스트 5개(요청 focus에서 recovery hold/normal/reduce + rest rule, 자동 경로 "every region" reduce, CLI heading).
   - Stale 문서: no-rule label 목록, shoulders 23분, 10-01 pull "yesterday 0" 예시, 제안 rule 상태.

### Files changed (통합 수정 commit)

`src/muscle50/domain/strength_recommendation.py`, `src/muscle50/presentation/terminal.py`,
`tests/test_strength_recommendation.py`, `tests/test_recommend_cli.py`, `docs/training-recommendation.md`,
`docs/CURRENT_STATE.md`, 이 파일.

### Checks run

- `uv run --extra dev pytest` 574 passed, `ruff check .`, `mypy src tests`(97 files), `git diff --check` 통과.
- 새 strength 회귀 테스트 3개(요청 focus + rest rule)는 수정 전 코드에서 실패함을 확인. 자동 경로 "every region"
  reduce는 62일 production에서 발생하지 않아 단위 테스트로만 확인된다.
- Production read-only(`garmin refresh` 미실행), evidence `C:\temp\muscle50-evidence-20261001-integration-hardening\`:
  10-01 auto/shoulders/push/pull/legs, 09-22 exit 0, JSON 재실행 byte-identical, ASCII. 수정 전/후 출력 차이는 10-01
  pull의 원인 문구뿐. 62일 × 5 = 310 run 비교 결과는 `docs/training-recommendation.md` 통합 검증 절과
  `CURRENT_STATE.md` Verification. Fingerprint before = after(DB/WAL, 28 table, RAW 954).

### Known failures or risks

- 사용자 지정 legs 09-17/09-18은 quad 3종목(reference와 동일, glutes 후보 없음으로 규칙상 허용). 자동 plan은 0.
- Lateral raise +2.5 kg step(6 → 8.5 kg) 미수정(progression 규칙 불변).
- 원인 표기 수정으로 rest rule reduce인 사용자 지정 focus 37 run(62일 중)의 text가 바뀐다(결정 불변).

### Recommended next action

1. 사용자: 이 branch로 local main fast-forward 여부 결정(main `aba8cfe`은 이 branch의 ancestor). Push는 별도 승인.
2. 이후 isolation 증량 step(+2.5 kg) 검토.

## Previous task: Recommendation Hardening v1 (2026-10-01)

Paseo worktree `recommendation-hardening`(branch `feature/recommendation-hardening`, base main = origin/main `8b259e7`).
**사용자 승인으로 commit `5dd2af7`(branch `feature/recommendation-hardening`, parent `8b259e7`), 구현·테스트·production read-only 검증 완료. main merge/push 안 함 — main과 origin/main은 `8b259e7` 그대로.** Final gates: pytest 555 passed, ruff clean, mypy clean,
`git diff --check` clean. 규칙 전체는 `docs/training-recommendation.md`(Hardening v1 표시 절).

### What was attempted / completed

1. Audit(read-only, `immutable=1`, 스크립트는 evidence 폴더): Garmin label 43종 + UNKNOWN 276 set(09-22 relabel 이전; 이후 46종 + UNKNOWN 271). Rear-delt 계열
   label 없음(REAR/FACE_PULL/REVERSE 0), UNKNOWN display name은 전부 "Unknown". Lateral raise 옆 UNKNOWN(09-17 seq 35,
   09-22 seq 29/33)은 rear-delt일 수 있지만 추측 안 함. 2026-10-01 recovery RAW: readiness `AFTER_WAKEUP_RESET`
   MODERATE 63이지만 `validSleep: false`, `sleepScore: null`, HRV `lastNightAvg: null`(수면 없이 계산된 값).
   Swim 간격 최대 8일(2026-07~09), 마지막 swim 09-17.
2. Strength(`strength_recommendation.py`): muscle balance slot 선택, `MAX_EXERCISES`=4, 한 primary muscle 3종목 금지,
   heavy hinge(category `DEADLIFT` + hinge pattern) 세션당 1개(사용자 요청 2026-10-01; 두 번째 hinge 대신 겹치지 않는
   익숙한 종목, 없으면 짧게 두고 이유),
   둘째 accessory 규칙, 완성도용 isolation, `focus_coverage`, 시간 부족분 reason(채우지 않음; 기존 "compound 1개 이하"
   조건 대체), low-confidence 부하 `recorded_load_range_kg`/`same_load_evidence`/`load_guidance`(progression 규칙 불변),
   `no_rule_notices`와 region 힌트(표시 전용), 요청 focus 어제 no-rule 힌트 경고, 날짜가 붙은 recovery 근거.
3. Recovery(`recovery_assessment.py`): D row 없음 또는 `sleep_seconds` NULL이면 D-1/D-2 아침 field 확인, D-1 reduce
   또는 둘 다 poor면 `hold` carry(최대 hold). `RecoveryAssessment.lookback`.
4. Swim(`swim_recommendation.py`): history D-28~D(off-by-one 수정), `return_easy`(마지막 swim ≥ 10일 전 또는 없음,
   0.8 × anchor easy, pace 없음), baseline `long_term_target_meters`/`days_since_last_swim`.
5. `training_recommendation.py`: `DataFreshness`, notice `recovery_row_partial`/`recovery_coverage_gap`/`swim_gap`/
   `strength_no_rule_exercise`, `recovery_row_missing` 문구 수정. Renderer: Focus coverage, load 안내, Lookback,
   Data freshness 절, low-confidence `@ ~X kg (low confidence: recorded A-B kg; ...)`.

### Proposed taxonomy rules (구현하지 않음, 사용자 결정 필요)

(이후 상태: 아래 6개와 보류한 `LYING_TRICEPS_EXTENSION_TO_CLOSE_GRIP_BENCH_PRESS`는 Taxonomy coverage `aba8cfe`에서 rule이
추가됐다. `PLYO/BOX_JUMP`는 의도적으로 rule 없음.)

같은 category의 기존 rule을 그대로 복제하는 mirror(모두 Garmin Connect confirmed label, probability 100):

| label | mirror of | 근거 |
| --- | --- | --- |
| `PULL_UP/CLOSE_GRIP_LAT_PULLDOWN` | `PULL_UP/LAT_PULLDOWN` | grip 변형, 09-30 5 set |
| `PULL_UP/WIDE_GRIP_LAT_PULLDOWN` | `PULL_UP/LAT_PULLDOWN` | grip 변형, 09-30 4 set |
| `ROW/BENT_OVER_ROW_WITH_BARBELL` | `ROW/-` | barbell row, 09-30 6 set |
| `SHOULDER_PRESS/SEATED_BARBELL_SHOULDER_PRESS` | `SHOULDER_PRESS/-` | 09-22 relabel, 8 set |
| `SHOULDER_PRESS/DUMBBELL_SHOULDER_PRESS` | `SHOULDER_PRESS/-` | 09-22 relabel, 6 set |
| `LATERAL_RAISE/ONE_ARM_CABLE_LATERAL_RAISE` | `LATERAL_RAISE/-` | 09-22 relabel, 3 set |

보류: `TRICEPS_EXTENSION/LYING_TRICEPS_EXTENSION_TO_CLOSE_GRIP_BENCH_PRESS`(triceps primary는 분명하지만 pattern이
extension+press 복합), `PLYO/BOX_JUMP`(category rule 없음). Rule 추가는 analytics snapshot 출력도 바꾸므로 별도 승인.
In-memory preview(`preview_rules.py`, repo 변경 없음): 10-01 shoulders = SEATED_BARBELL 40 kg + DUMBBELL 16 kg
(anterior) + ONE_ARM_CABLE_LATERAL_RAISE 6 kg(lateral), 32분, posterior 누락; pull은 어제 15 set → resting.

### Files changed (commit `5dd2af7`)

`src/muscle50/domain/{strength_recommendation,recovery_assessment,swim_recommendation,training_recommendation}.py`,
`src/muscle50/presentation/terminal.py`, `tests/test_{strength_recommendation,recovery_assessment,swim_recommendation,
recommend_cli}.py`, `docs/training-recommendation.md`, `docs/CURRENT_STATE.md`, 이 파일. Ingestion/normalization/
taxonomy/migration 변경 없음.

### Checks run

- `uv run --extra dev pytest` 555 passed(기존 524 중 4개 기대값을 의도적으로 갱신: shoulders 부족분 문구, 강한 swim
  shoulders 문구, full pull session fixture, CLI heading), `ruff check .`, `mypy src tests`, `git diff --check` 통과.
  수정 파일만 `ruff format`(terminal.py는 main부터 미포맷이라 기존 줄 유지).
- Production read-only: 10-01 auto/shoulders/legs, 09-28 `--focus legs`, 09-18, 09-21, 09-25, 09-13 exit 0, JSON 재실행
  byte-identical, ASCII. 62일 HEAD 대비 비교(`compare.txt`). Fingerprint 전후 동일(아래 위험 참고).

### Known failures or risks

- **작업 중 production 변경(이 세션이 한 것 아님)**: 16:12-16:23 KST에 다른 프로세스가 `garmin refresh`를 6회 실행했다
  (09-17 `24391187334`, 09-18 `24403245957`, 09-21 `24438715022`, 09-22 `24451010022` ×2, 09-23 `24464300822`), RAW
  912 → 954. 처음 fingerprint(`before.json`)와 다르다. 최종 검증은 그 이후 상태(`before_v5.json` = `after_v5.json`, v4 이후 외부 변경 없음)에서 했다.
  그 전 실행 결과는 `run1_mixed_state/`, `run2_pre_refine/`, `run3_v3/`, `run4_v4_prehinge/`에 보관(근거로 쓰지 않음).
- 09-22 relabel 때문에 사용자가 지적한 `SHOULDER_PRESS/- 16-30 kg`, `LATERAL_RAISE/- 6-10 kg` 사례는 production에서 더
  이상 재현되지 않는다(두 label 모두 28일 1 session). Low-confidence 표시는 단위 테스트(같은 16/30 kg 모양)와
  production LUNGE/- 20-40 kg, PULL_UP/- 등에서 확인.
- Shoulders는 posterior deltoid rule/label이 없어 23분이다. 위 rule 제안을 채택해도 32분이다.
- Heavy hinge 규칙 후 legs는 대개 3종목 32분이다(hamstrings 익숙한 종목이 SLDL뿐이고 leg extension은 quad 3번째라
  안 넣음). 62일: heavy hinge 2개 plan 17(규칙 전 초안) → 0, HEAD 2 → 0. `HIP_RAISE/BARBELL_HIP_THRUST_ON_FLOOR`는
  deadlift 변형이 아니라 SLDL과 같이 나올 수 있다(08-20~08-31 8일).
- Lookback은 8월(recovery row 없음)에도 평가되지만 발동하지 않는다. Carry는 09-13, 10-01 두 날.

### Recommended next action

1. `5dd2af7`의 main 통합/push 여부 결정(명시적 승인 필요). 이 branch는 main보다 앞서 있고 merge/push 하지 않았다.
2. Taxonomy mirror rule 6개 채택 여부 결정(별도 작은 변경 권장, analytics snapshot 영향 확인).
3. Rear-delt 운동을 한다면 Garmin Connect에서 지정 → `garmin refresh` → posterior-primary rule 추가 검토.

## Previous task: Exercise Taxonomy coverage update (2026-10-01)

Paseo worktree `taxonomy-coverage`(branch `feature/taxonomy-coverage`, base `8b259e7` = `--focus` commit).
**구현, 테스트, production read-only 검증 완료. 사용자 승인(2026-10-01)으로 이 branch에 commit했다.**
Merge/rebase/push 없음. Recommendation 로직 변경 없음.

### What was attempted / completed

- Read-only audit(`immutable=1`): ACTIVE label 47개(UNKNOWN 포함) 중 `no_rule` 8개 = Connect에서 지정한 7개
  (probability 100; 09-22 `24451010022`, 09-29 `24536298902`, 09-30 `24549434906`) + `PLYO/BOX_JUMP`.
  7개 이름 모두 Garmin FIT profile에 존재.
- `exercise_taxonomy.py`에 저장값 그대로의 label 7개 rule 추가(규칙과 이유: `docs/exercise-taxonomy.md` 결정 표).
  `PLYO/BOX_JUMP`는 계속 rule 없음. UNKNOWN 판정과 label identity는 변경 없음.
- Tests: `PRODUCTION_LABELS` 7개 추가, known-mapping 7건, variant 구분 test 6건, analytics `by_exercise`에서
  shoulder variant가 별개 group인지 확인하는 test.

### Decisions (사용자, 2026-10-01)

- `ROW/BENT_OVER_ROW_WITH_BARBELL`: posterior_deltoid secondary 추가(row family와 일치). 28일 posterior_deltoid
  secondary exposure 6 → 12. 추천 출력은 변화 없음(secondary는 추천에서 쓰지 않음).
- `LYING_TRICEPS_EXTENSION_TO_CLOSE_GRIP_BENCH_PRESS`: `elbow_extension`, triceps, chest/anterior_deltoid 유지.
- `PLYO/BOX_JUMP` 최종 결정(사용자, 2026-10-01): **의도적으로 rule 없음(`no_rule`)**. Plyometric은 taxonomy v1 범위 밖이며 `squat`으로 매핑하지 않고 새 `jump` pattern도 추가하지 않는다. 현재 근거는 watch가 자동 인식한 1 set(confidence 37.5%)뿐이다: 2026-09-10 `24304351575` 마지막 set, 3 reps, 10 kg, 1.9 s, 직전 rest 1548 s(상체 세션 종료 후). 유일한 non-UNKNOWN ACTIVE `no_rule` label로 계속 드러난다.

### Files changed

`src/muscle50/domain/exercise_taxonomy.py`, `tests/test_exercise_taxonomy.py`, `tests/test_analytics_taxonomy.py`,
`docs/exercise-taxonomy.md`, `docs/CURRENT_STATE.md`, 이 파일.

### Checks run

- `uv run --extra dev pytest` 538 passed, `ruff check .`, `mypy src tests`(97 files), `git diff --check` 통과.
- Production read-only 4개 명령 exit 0, snapshot JSON 재실행 byte-identical. DB/WAL/28 table/RAW 954 files
  fingerprint 전후 동일. Evidence: `C:\temp\muscle50-evidence-20261001-coverage\`
  (before/after/final fingerprint, snapshot/rec/sh `_before`/`_after`/`_final` text+JSON, labels.py, report.py).
  `_final` = posterior_deltoid 결정 반영본; `_after` 대비 snapshot taxonomy 절 2줄만 다르고 recommend JSON/text 동일.

### Known failures or risks

- 09-30 pull 15 set이 이제 집계돼 10-01에 pull이 `resting`(어제 ≥ 6 primary)으로 바뀌고 swim에 "no butterfly or
  paddles" 주의가 추가된다. 로직 변경이 아니라 데이터 반영이다. 자동 focus는 legs 그대로.
- UNKNOWN 271(전체) / 33(28일)은 그대로다.
- Recommendation hardening 별도 issue(여기서 수정하지 않음): `LATERAL_RAISE/ONE_ARM_CABLE_LATERAL_RAISE` progression이
  고정 +2.5 kg step으로 6 kg → 8.5 kg(약 42%)을 제안한다. 가벼운 one-arm cable isolation에는 과한 증가다.

### Recommended next action

1. main 통합 여부 결정(명시적 승인 필요).
2. 이후 recommendation hardening(별도 작업, lateral raise +2.5 kg step 포함).

## Previous task: user-selected focus override `--focus` (2026-10-01)

Paseo worktree `training-recommendation`(branch `feature/training-recommendation`, base main = origin/main `7740d7d`).
**구현, 테스트, production read-only 검증 완료. 사용자 승인(2026-10-01)으로 이 branch에 commit했다.** Merge/push 없음.

사용자 결정(2026-10-01): (1) 요청 focus가 전날 6+ primary set이어도 focus를 바꾸지 않고 reduce, (2) 자동 경로의
"세 region 모두 어제 heavy" 규칙은 요청 focus에 추가 적용하지 않음, (3) shoulders도 push/pull과 같은 swim 주의,
(4) "history is limited" 3개 조건 유지, (5) JSON `auto_focus` 유지, (6) 얇은 shoulders history는 taxonomy/종목을
임의 확장해 해결하지 않고 실제 Garmin 기록 기반으로 별도 개선.

### What was attempted / completed

- `muscle50 recommend --date D --focus push|pull|legs|shoulders`. 없으면 자동 focus 선택 그대로(순위 규칙 변경 없음).
  있으면 요청 focus로 세션을 만들고 다른 focus로 바꾸지 않는다. 자동 선택 결과는 `auto_focus`로 근거만 남긴다.
- 그대로 적용: recovery `normal`/`hold`/`reduce`, 강한 swim 후 overhead press를 key/accessory로 쓰지 않음과
  deltoid/lats 1 set 감소, `--avoid`, double progression, UNKNOWN/data-quality 안내.
- 결정(사용자 승인): 요청 focus의 어제 primary set ≥ 6이면 reduce. 자동 경로에서 그 region을 제외하는 48h 규칙과
  같은 기준이며, 요청은 바꾸지 않으므로 세션을 낮춘다. 자동 경로의 "세 region 모두 어제 heavy → reduce"는 요청 경로에서
  쓰지 않는다(push/pull/legs는 위 규칙이 같은 결과를 내고, shoulders만 다를 수 있음).
- `shoulders`: primary anterior/lateral/posterior deltoid 종목만(secondary 노출은 자격 아님). Posterior deltoid
  primary rule은 v1 taxonomy에 없어 출력에 "never counted"로 표시.
- "history is limited": 익숙한 종목 0개(추천 없음, 전환 없음), 계획 종목이 모두 1회 세션, 또는 compound 1개 이하로
  accessory slot이 비고 목표 시간보다 5분 넘게 짧을 때. 세션을 다른 종목으로 채우지 않는다.
- `swim_recommendation.py`: `shoulders` focus도 push/pull처럼 "no butterfly or paddles"와 "several hours" 주의를 받는다.
- 표시: text `[auto-selected]` / `[user-selected; automatic would be X]`, JSON `focus_source`, `auto_focus`.

### Files changed

`src/muscle50/domain/strength_recommendation.py`(StrengthFocus/FocusSource/FOCUS_MUSCLES, `_candidates`를 muscle 집합
기준으로 일반화, 자동 선택 loop를 `_auto_selection`으로 그대로 추출), `domain/training_recommendation.py`,
`domain/swim_recommendation.py`, `application/recommend_training.py`, `cli.py`, `presentation/terminal.py`,
`tests/test_strength_recommendation.py`, `tests/test_swim_recommendation.py`, `tests/test_recommend_cli.py`,
`docs/training-recommendation.md`, `README.md`, `docs/CURRENT_STATE.md`, 이 파일.

### Checks run

- `uv run --extra dev pytest` 524 passed(기존 509 수정 없이 통과 + 신규 15), `ruff check .`, `mypy src tests`(97 files),
  `git diff --check` 통과. 새로 건드린 파일의 `ruff format`은 main에서 깨끗했던 파일은 깨끗하게 유지했다
  (`presentation/terminal.py`는 main부터 미포맷이라 그대로 둠).
- Production read-only `recommend --date 2026-10-01`: `--focus` 없는 JSON은 main `7740d7d`와 새 field 2개 외 동일, text는
  Focus 줄 `[auto-selected]`만 다름. `--focus legs/push/pull/shoulders` exit 0. RAW 868 files, DB/WAL hash 전후 동일.

### Known failures or risks

- Recommendation strength/swim history window off-by-one(미수정, `CURRENT_STATE.md` Known issues).
- 데이터가 2026-09-28까지라 2026-10-01 결과의 neglect/swim 개수/recovery는 미동기화 영향을 받는다.

### Recommended next action

1. main 통합 여부 결정(명시적 승인 필요). push/merge 하지 않았다.
2. 그 다음 history window off-by-one을 별도 수정 후보로 둔다(이번 commit에서는 의도적으로 수정하지 않음).
3. Shoulders history 보강은 실제 Garmin 기록(종목 지정 후 `garmin refresh`) 기반으로 별도 진행.

## Previous task: Training Recommendation v1 (2026-10-01)

Branch `feature/training-recommendation` (Paseo worktree `training-recommendation`, base main = origin/main `a92404b`,
Analytics Engine v1 + Exercise Taxonomy v1 포함). 구현, 테스트, production read-only 검증 후 이 branch에 commit했고,
이후 main에 fast-forward되어 `7740d7d`로 origin/main까지 push됐다. 설계·규칙·한계 전체는
`docs/training-recommendation.md`.

### What was attempted / completed

1. Audit(read-only, `immutable=1`): 기존 primitive(`SqliteAnalyticsReader`, `build_training_snapshot` swim plausibility,
   taxonomy, `label_origin`) 재사용. Goal model 없음 → `TrainingGoals` code default. Recovery readiness/recovery time은
   Garmin 아침(`AFTER_WAKEUP_RESET`) 항목이라 D row 사용, training status는 하루 끝 값이라 D-1 사용, body battery/
   stress/RHR은 미사용. Lap `intensity_type` 전부 NULL, paddle/fin 기록 없음. 긴 lap 다수에 implausible length timing.
2. 순수 domain: recovery 규칙(`normal`/`hold`/`reduce`), region focus 선택, 익숙한 원본 label 종목 선택, label별 double
   progression(같은 무게 비교만 regression), swim overlap, UNKNOWN notice, swim 분석(연속 구간, plausible timing,
   pace)과 다음 수영 목표 4종.
3. Application `BuildTrainingRecommendation`, ASCII text/JSON renderer, CLI `muscle50 recommend --date [--json]
   [--avoid MUSCLE]`(read-only, migrate/mkdir/인증 없음).
4. Production 14개 날짜 검증, threshold 발동 빈도 calibration(butterfly 100 m → 200 m로 조정: 9/21 → 4/21 swim).
5. 사용자 요청으로 focus 선택 개선: 7일 session 수 floor/ceiling 규칙(legs 14일 중 10일)을 제거하고, region 자신의
   28일 주기 대비 due(경과일 / personal interval, 2~7일 clamp), 7일 이상 미훈련 neglected 보호(수영 불포함),
   swim overlap, recovery reduce 시 최근 2일 region 후순위, 자기 평균 대비 7일 volume 순으로 바꿨다. Session 판정
   기준(하루 ≥ 3 set)은 바꾸지 않았다. 결과 legs 10/push 3/pull 1 → legs 7/pull 5/push 2. 남은 legs 7일은 모두
   neglected(3), push/pull resting 또는 swim overlap(3), 자기 주기상 due(1)로 설명된다.

### Files changed

- 신규: `src/muscle50/domain/{training_goals,recovery_assessment,strength_recommendation,swim_recommendation,
  training_recommendation}.py`, `src/muscle50/application/recommend_training.py`,
  `tests/test_{strength_recommendation,swim_recommendation,recovery_assessment,recommend_cli}.py`,
  `docs/training-recommendation.md`
- 수정: `src/muscle50/cli.py`(recommend), `src/muscle50/presentation/terminal.py`(renderer), `README.md`,
  `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`
- Migration, ingestion/refresh/normalization, taxonomy, analytics 변경 없음.

### Tests / checks run

`uv run --extra dev pytest` 509 passed, `ruff check .`, `mypy src tests`(97 files), `git diff --check` 통과.
Production: 14개 날짜 exit 0, JSON byte-identical 재실행, text ASCII, before/after fingerprint 동일(`-shm` mtime 제외).
Evidence(repo 밖): `C:\temp\muscle50-evidence-20261001-recommend\`.

### Known risks / open decisions

- Focus는 매일 독립 계산이다. 62일 counterfactual에서 pull 26 / push 14 / legs 22(실제 session pull 24 / push 20 /
  legs 9): pull은 사용자 비율과 같고 push 몫이 하체 보호로 legs에 간다. Push가 실제보다 적게 추천되는 점은 관찰 대상.
- 대부분 load target이 `low` confidence: category-only 자동 인식 label(`BENCH_PRESS/-` 30-60 kg 등)에 장비가 섞임.
- 연속 수영 baseline은 plausible length timing 구간만 써서 보수적이다(28일 최장 650 m) → anchor는 설정 1000 m.
- 임계값은 이 계정 2026-07~09 데이터 기준(butterfly 임계값은 같은 데이터로 100 → 200 m 조정). HRV 규칙 0/28일,
  stagnation 대안 0/14일 발동. 통증은 `--avoid` 명시 입력으로만 반영.
- 아침 readiness: 28/28 날짜에 `AFTER_WAKEUP_RESET` 존재. 단 2026-09-12는 두 항목 중 23:17 값이 저장돼 있다(기존
  recovery normalizer가 첫 항목 선택; 이 작업에서 수정하지 않음). 후속 작업 후보.
- 기존 CURRENT_STATE/HANDOFF의 taxonomy evidence 경로에 있던 `\t`/`\b` 깨짐을 함께 고쳤다.

### Recommended next action

1. main 통합 여부 결정(명시적 승인 필요). push/merge 하지 않았다.
2. Garmin Connect에서 UNKNOWN/자동 인식 종목 수정 → `garmin refresh <id>`로 추천 정확도 향상.
3. 이후: sync coverage 기록(미동기화 vs 휴식), LLM 표현 계층(결정 변경 금지).

## Previous task: Exercise Taxonomy v1 (2026-10-01)

Branch `feature/exercise-taxonomy` (Paseo worktree `exercise-taxonomy`, base main = origin/main `2603b85`,
Analytics Engine v1 포함). **구현, 테스트, production read-only 검증 완료. 사용자 승인으로 이 branch에
commit했다. merge/push 하지 않았다.** 설계와 규칙 전체는 `docs/exercise-taxonomy.md`.

### What was attempted / completed

1. Read-only audit(`immutable=1`): ACTIVE 1054, label 39종 + UNKNOWN 276. UNKNOWN은 Garmin JSON 대체 후보,
   FIT 원본(category 65534/65535), velocity/ROM, `wktStepIndex` 어디에도 정보가 없어 해소 0건. Garmin probability
   < 100인 960 set은 FIT device 자동 인식과 100% 일치, probability 100인 94 set은 Connect 편집 activity 5개에만
   존재(위치 비교 가능한 4 activity 76 set 중 49 set이 device label과 다름; `24524226596`은 Connect에서 set
   1개 삭제로 비교 제외) → `LabelOrigin`(confirmed/auto_detected/unspecified)로 개수 보고.
2. 순수 domain `exercise_taxonomy.py`: production label 38개 explicit rule, pattern 15, muscle 13, basis
   (`exercise_name`/`category_only`/`category_override`), unmapped reason(`unknown_source_label`/`no_rule`).
   Category fallback/fuzzy/추론 없음, 정확한 label 일치. UNKNOWN predicate는 `derive_activity_review`와 동일.
3. 사용자 결정(2026-10-01)으로 초기 구현의 canonical exercise 이름/병합을 제거했다. 원본 Garmin
   `(category, name)`이 identity이고 taxonomy는 pattern/primary/secondary/provenance만 붙인다.
4. Analytics 연동(additive): `StrengthSummary.taxonomy`(`by_exercise` 원본 label별, pattern, primary, secondary
   exposure, UNKNOWN 수·영향 activity, no-rule 수), quality issue `strength_unmapped_exercise`, text renderer 절.
   `ExerciseAggregate`는 변경 없음. JSON은 기존 dataclass 직렬화로 자동 포함.
5. Production 검증과 문서화.

### Files changed

- 신규: `src/muscle50/domain/exercise_taxonomy.py`, `tests/test_exercise_taxonomy.py`,
  `tests/test_analytics_taxonomy.py`, `docs/exercise-taxonomy.md`
- 수정: `src/muscle50/domain/analytics.py`, `src/muscle50/presentation/terminal.py`, `tests/analytics_builders.py`
  (`probability` 인자), `docs/analytics-engine.md`, `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`, `README.md`
- Migration, ingestion/refresh/RAW/normalization 변경 없음. CLI 변경 없음(기존 `analytics snapshot`이 출력).

### Tests / checks run

`uv run --extra dev pytest` 445 passed, `uv run --extra dev ruff check .`, `uv run --extra dev mypy src tests`
(87 files), `git diff --check` 통과. Production: 90일 snapshot JSON/text exit 0, 재실행 byte-identical, 독립 SQL
cross-check 15/15(`crosscheck_v2.py`), before/after fingerprint 동일(`-shm` mtime 제외). Evidence(repo 밖):
`C:\temp\muscle50-evidence-20261001-taxonomy\`(fingerprint.py, before/after.json, audit*.py, fit_sets.py,
snapshot_v2_90d*.json/txt, crosscheck_v2.py/txt, after_v2.json, fit_profile.py = Garmin FIT SDK profile 사본).

### Known risks / open decisions

- Primary muscle 선택(close-grip bench → triceps, row → upper_back, deadlift → glutes, leg extension override)은
  headline 합계를 움직이는 판단값이다. 사용자 검토 권장.
- 매핑 777 set 중 683은 watch 자동 인식 label(SHRUG 55, 50 kg SIT_UP 등 오인식 포함). Taxonomy는 label 정확성을
  판단하지 않는다 — 해석 시 `label_origins`를 같이 봐야 한다.
- 새 Garmin label은 `no_rule`로 드러나며 rule을 추가해야 매핑된다.

### Recommended next action

1. main 통합 여부 결정(명시적 승인 필요). push 하지 않았다.
2. UNKNOWN 276을 줄이려면 Garmin Connect에서 종목 지정 → `garmin refresh <id>`(사용자 작업, 별도 승인).
3. 다음 slice 후보: 기간 비교(이번 주 vs 이전 주) by primary muscle/pattern. 추천, overload, 목표, 수영 목표,
   Daily Recommendation, Training Goals/Profile은 taxonomy 범위 밖이며 별도 기능/branch에서 다룬다.

## Previous task: Analytics Engine v1 (2026-09-30)

이 작업은 이후 `2603b85`로 main/origin에 포함됐다.

Branch `feature/analytics-engine` (worktree `C:\Users\hundo\Desktop\MyProjects\analytics-engine`, base
local main `dc2c99f`). **구현과 production read-only 검증 완료. 미커밋 상태이며 commit/merge/push 하지
않았다.** 설계와 규칙 전체는 `docs/analytics-engine.md`.

### What was attempted / completed

1. Repo/schema/production data audit(read-only, `immutable=1`). 기존 analytics primitive는 per-activity
   helper(`derive_summary`, `derive_lap_metrics`/`derive_length_metrics`, `derive_activity_review`,
   `strength_set_metrics`)뿐이고 window 집계와 read-only DB 경로가 없었다.
2. 순수 domain `build_training_snapshot()`: window(inclusive, 1~90일, 기본 7), activity overview,
   load metric 10종(명시적 sum/max, per-activity 값과 missing ID 포함), strength(active set/reps/
   volume/exercise, 제외 사유), swimming(summary vs detail, implausible lap 제외), recovery(daily/state/
   categorical, row 없음 vs null 구분), quality issue 목록.
3. `SqliteAnalyticsReader`(`mode=ro` + `query_only`, 단일 read transaction, 없으면 생성 안 함, schema
   version ≥ 7 확인), `BuildTrainingSnapshot`, text/JSON renderer, CLI `analytics snapshot`.
4. 2026-09-17 swim 판정: Garmin summary distance 3025 m 자체가 phantom lap(lap seq 1, 2500 m / 1.787 s)을
   포함한다. Summary는 그대로, plausible lap detail distance 525 m를 따로 보고, issue로 명시. 같은 규칙이
   2026-09-10 `24302653969`(75 m / 0.966 s)도 찾아냈다. Production 데이터는 수정하지 않았다.

### Files changed

- 신규: `src/muscle50/domain/analytics.py`, `src/muscle50/infrastructure/sqlite/analytics_reader.py`,
  `src/muscle50/application/training_snapshot.py`, `tests/analytics_builders.py`(synthetic builder),
  `tests/test_analytics_snapshot.py`, `tests/test_analytics_reader.py`, `docs/analytics-engine.md`
- 수정: `src/muscle50/cli.py`(`analytics snapshot`), `src/muscle50/presentation/terminal.py`(renderer 추가만),
  `README.md`(사용법 절), `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`
- 신규 파일은 untracked 상태다(index에 stage하지 않음).
- Migration 없음. Ingestion/refresh/RAW/normalization 코드는 수정하지 않았다. Reader는
  `database.py`의 private row mapper(`_activity_from_rows`, `_swim_detail_from_connection`,
  `_recovery_from_row`)를 import해 재사용한다.

### Tests / checks run

`uv run pytest -q` 390 passed, `uv run ruff check .`, `uv run mypy src tests`(84 files), `git diff --check`
통과. Production 검증과 fingerprint 비교는 `docs/CURRENT_STATE.md` "Verification" 2026-09-30 Analytics 절.
Evidence(repo 밖): `C:\temp\muscle50-evidence-20260930-analytics\`(fingerprint.py, before/after.json,
audit*.py, snapshot_*.txt/json, crosscheck.py/txt).

### Known risks / open decisions

- `MAX_PLAUSIBLE_SWIM_SPEED_MPS = 2.5`는 판단값이다. Lap 판정(distance 제외)은 threshold에 둔감하지만
  length 개수(counted only)는 민감하다.
- Muscle-group 집계는 mapping이 없어 구현하지 않았다. Garmin category → muscle group mapping을 만들지는
  사용자 결정이 필요하다.
- Read-only reader도 WAL DB의 `-shm`에 reader mark를 쓰고, `-wal`/`-shm`이 없으면 빈 파일을 만든다
  (SQLite 동작, main DB 파일은 불변).
- 새 activity import 후 `garmin backfill-load-metrics`를 돌리지 않으면 snapshot에서 해당 activity의
  load metric이 missing으로 보고된다(0으로 처리되지 않음).

### Recommended next action

1. 리뷰 후 `feature/analytics-engine` commit 여부 결정(명시적 승인 필요), 이어서 main 통합 여부 결정.
2. 다음 slice 후보: 기간 비교(이번 주 vs 이전 주), swim pace/SWOLF 추세(plausible length만), muscle-group
   mapping 설계(승인 시), 09-17/09-10 swim의 correction overlay(승인 시).

## Previous task: Garmin Analytics Prerequisites

Garmin Analytics Prerequisites (2026-09-29~30), branch `feature/garmin-analytics-prerequisites`
(Paseo worktree `strong-bat`, base main `65a929a`). Activity-load metric, recovery range sync,
recovery normalizer v2를 구현해 `4645f5f`로 커밋했고, 이어서 historical activity import
(2026-07-01~08-02)와 load-metric backfill을 production DB에서 검증했다(이 문서 갱신은 별도
docs-only 커밋). **Garmin Analytics Prerequisites는 이 feature branch에서 구현 및 실데이터 검증
완료 상태다. Merge/push 하지 않았다. Analytics Engine은 시작하지 않았다.**

## Garmin Analytics Prerequisites (2026-09-29~30)

### What was attempted / completed

1. **Activity-load metrics.** 10개 canonical key(`training_load`, `aerobic_training_effect`,
   `anaerobic_training_effect`, `hr_time_in_zone_1..5_seconds`, `moderate_intensity_minutes`,
   `vigorous_intensity_minutes`)를 `domain/activity_load.py`에 정의했다. 42개 production RAW 전수로
   source path와 unit(score/s/min)을 확인했다. Shared `normalize_activity`에는 넣지 않았다 — 검증된
   refresh 출력이 바뀌지 않게 하기 위해서다. `garmin backfill-load-metrics [--dry-run]`가 초기 flat
   `summary.json`만 읽어(refresh `snapshots/`는 읽지 않음) 이 10개 key만 upsert한다.
   Production: 42 activity, 420 insert, 420/420 RAW 일치, 두 번째 실행 변경 0. activity/strength/swim/
   기존 metric/RAW 불변.
2. **Recovery range sync.** `garmin recovery --from --to [--yes]`. Production
   `--from 2026-09-01 --to 2026-09-28 --yes`(Garmin 약 252회 호출, exit 0): 28/28 날짜, 26 created,
   1 updated(2026-09-14, 당일 저녁 partial capture였던 `stress_average` 21 → 26), 1 unchanged
   (2026-09-27). 신규 capture 27개 모두 9 endpoint, endpoint 실패 0. 2026-09-13은 Garmin 원본에
   sleep/overnight HRV가 없다.
3. **Recovery normalizer v2.** Range 검증에서 `training_status_key`와 `sleep_avg_hrv_ms`가 28일 모두
   NULL임을 발견했다. 원인: 실제 RAW는 `trainingStatus`가 numeric code(4/5/7)이고 key는
   `trainingStatusFeedbackPhrase` prefix에 있으며, sleep HRV는 `dailySleepDTO.avgSleepHRV`가 아니라
   top-level `avgOvernightHrv`에 있다. 정규화를 고치고 `normalizer_version`을 2로 올렸으며
   `garmin recovery-renormalize [--dry-run]`(RAW-only, Garmin 호출 0)으로 28행을 재정규화했다.
   결과: `training_status_key` 28/28(MAINTAINING 12, PRODUCTIVE 9, RECOVERY 7), `sleep_avg_hrv_ms`
   27/28(2026-09-13 RAW null). 두 번째 실행 변경 0.

### Files changed

- 신규: `src/muscle50/domain/activity_load.py`, `src/muscle50/application/backfill_activity_load_metrics.py`,
  `src/muscle50/application/renormalize_garmin_recovery.py`, `tests/test_activity_load_backfill.py`,
  `tests/test_recovery_range.py`, `tests/test_recovery_renormalize.py`,
  `docs/garmin-analytics-prerequisites.md`
- 수정: `src/muscle50/cli.py`, `src/muscle50/application/sync_garmin_recovery.py`(range use case),
  `src/muscle50/domain/recovery.py`(`RECOVERY_NORMALIZER_VERSION = 2`),
  `src/muscle50/domain/recovery_normalization.py`, `src/muscle50/infrastructure/garmin/client.py`
  (`GarminAuthenticationError` subclass), `src/muscle50/infrastructure/raw_store.py`
  (`load_initial_summary`, `load_capture_payloads`), `src/muscle50/infrastructure/sqlite/database.py`
  (`list_source_activity_ids`, `upsert_activity_metrics`, `list_calendar_dates`),
  `src/muscle50/presentation/terminal.py`, `tests/test_recovery_normalization.py`(추가만),
  `tests/test_sync_recovery.py`(normalizer version literal 1 → constant; 기존 테스트 중 유일한 수정),
  `docs/garmin-recovery-endpoint-discovery.md`, `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`
- Migration 없음. Refresh 코드(`refresh_garmin_activity.py`)는 수정하지 않았다.

### Tests / checks run

`uv run pytest -q` 345 passed(기존 285 → 319 → 345), `uv run ruff check .`, `uv run mypy src tests`
(78 files), `git diff --check`, `uv build` 통과. 모든 production 단계 후 `PRAGMA integrity_check` = ok,
`foreign_key_check` clean, 중복/orphan 0. 상세 evidence는 `docs/CURRENT_STATE.md` "Verification".
Evidence 파일(repo 밖): `C:\temp\muscle50-evidence-20260929\`, `C:\temp\muscle50-evidence-20260930\`,
`C:\temp\muscle50-evidence-20260930-hist\`.
Backups: `%LOCALAPPDATA%\muscle50\db_backup_20260929e_pre_load_metrics`,
`db_backup_20260930a_pre_recovery_range`, `db_backup_20260930b_pre_recovery_renormalize`,
`db_backup_20260930c_pre_historical_import`.

### Historical activity import (2026-09-30)

Commit `4645f5f` 코드 그대로 실행했다(코드 변경 없음).

- 명령: `uv run muscle50 garmin activities --from 2026-07-01 --to 2026-08-02` → exit 0.
  Garmin이 36건을 반환했고 36건 모두 신규 import(이미 저장됨 0, 실패 0, RAW manifest warning 0).
  실제 activity 날짜는 2026-07-01~2026-07-31이며 2026-08-01/08-02에는 activity가 없다.
  Strength 24, pool swim 12, training day 21. RAW 240 files 추가(모두 신규 activity 디렉터리).
- Strength: 신규 24건, canonical set 933(ACTIVE 471 / REST 462). 933 set 전부를 RAW 필드
  (messageIndex, setType, reps, weight g/1000, category, name, duration)와 직접 비교해 불일치 0.
  ACTIVE 중 UNKNOWN 분류 147/471, weight 0/누락 39, reps 0 20 — ingestion 실패가 아니라
  data-quality/review 이슈다.
- Swim: 신규 12 session, lap 286, length 645(수영 417 / rest 228). 모든 lap/length 값을 RAW
  `splits`와 비교해 불일치 0. 11 session은 50 m pool, 2026-07-23은 source와 일관된 20 m pool.
  Session별 수영 length 거리 합 = parent distance, 수영 length 수 = source active length count.
  누락된 swim child record 없음.
- Load metrics: `backfill-load-metrics --dry-run` 예측(36 changed, 360 insert, 420 identical)과 실제
  실행이 동일. 78 activity 모두 10개 metric 보유, 780/780 값이 각자의 RAW와 일치. 기존 420 load
  metric 불변. 두 번째 실행 canonical 변경 0.
- Regression: 기존 42 activity의 parent row, metric, strength set, swim/lap/length, refresh state,
  RAW 파일이 activity별 fingerprint로 모두 불변. `daily_recovery`와 recovery RAW 불변. 중복/orphan 0,
  `PRAGMA integrity_check` = ok, `foreign_key_check` clean, 기존 RAW 628 files 불변(최종 868 files).
  2026-09-17 swim anomaly 불변.
- Final Garmin activity coverage: 78 activities, 2026-07-01~2026-09-28, 54 distinct training days
  (strength 55, lap swimming 21, running 1, track running 1).

### Data-quality findings (future Analytics quality layer; 수정하지 않음)

- 신규 기간 수영 length 40/417이 42 s/100 m보다 빠르다(세계기록 페이스 미만, 12 session 중 9개).
  기존 swim 데이터에도 같은 현상(110 lengths)이 있어 import 실패가 아니라 systemic source/data-quality
  이슈다. 예: 2026-07-07 `23503867925` length 53, breaststroke 50 m 5.6 s.
- Strength UNKNOWN 분류 147/471, weight 0/누락 39, reps 0 20(신규 ACTIVE set 기준). 일부는 bodyweight
  운동으로 정당할 수 있다.
- 2026-07-20 swim 2건(`23659117397`, `23659117767`)은 27분 간격이며 split session일 수 있다. 자동으로
  합치지 않는다.
- 2026-07-23 20 m pool은 내부적으로 일관된다. 평소 pool 길이와 다르다는 이유만으로 오류로 취급하지 않는다.

### Known risks

- 새 activity import(`garmin latest`/`garmin activities`)는 load metric을 채우지 않는다 — import 후
  backfill을 다시 실행해야 한다. 자동 enrichment는 향후 설계 결정.
- `sync_runs` recovery coverage는 보류(schema에 날짜 column 없음, migration 필요).
- `mostRecentTrainingStatus`의 stale-date 가능성은 필터 없이 남겨 두었다(관측 28일은 모두 날짜 일치).
- Range 실행 중 repository integrity `RuntimeError`는 날짜별 요약 없이 traceback으로 멈춘다(완료된
  날짜는 유지, 재실행 안전 — activity range import와 동일).
- 2026-09-17 swim anomaly는 의도적으로 수정하지 않았다(향후 Analytics quality layer).

### Prerequisite status

- Garmin Analytics Prerequisites: 이 feature branch에서 구현 및 실데이터 검증 완료.
- 완료: historical activity import, recovery 28일 backfill, recovery normalizer v2 re-normalization,
  activity load-metric backfill.
- Strength refresh/review는 Analytics Engine 전에 필요하지 않다.
- 보류: `sync_runs` recovery coverage, 향후 import의 자동 load-metric enrichment.
- Analytics Engine은 시작하지 않았다.

### Recommended next action

1. 이 branch(`4645f5f` + docs-only 커밋)의 main 통합 여부 결정(명시적 승인 필요). main은 여전히
   `65a929a`이므로 fast-forward 가능하다. 통합 전 main에서 전체 게이트(pytest/Ruff/mypy/
   `git diff --check`/`uv build`) 재실행 권장.
2. 그 뒤 Analytics Engine(명시적 승인 필요).
3. 새 activity를 import할 때마다 `garmin backfill-load-metrics`를 이어서 실행한다.

## Previous task: Garmin refresh safety gate (2026-09-29)

Garmin refresh safety gate를 닫았다. `garmin refresh`가 기존 canonical activity metadata를 NULL로
덮어쓰던 버그를 hotfix하고, 실기기 activity 2건으로 실 DB 회귀 검증을 마쳤다. **판정: SAFE.**

Hotfix는 main에 커밋됐다: `c32cff3` — "fix: make Garmin activity refresh metadata-safe"
(부모 `4618df8`). 이 handoff 문서 갱신은 그 뒤 별도 docs-only 커밋이다. Push는 하지 않았다.

## Garmin refresh hotfix (2026-09-29)

### Root cause

`PythonGarminConnector.fetch_raw_activity()`는 단일 activity 조회라 list endpoint를 호출하지 않고
`summary={}`를 반환한다. `RefreshGarminActivity`는 그 자리를 `raw.activity`(= `get_activity()`
detail payload)로 채운 뒤 `normalize_activity(raw.activity, raw.activity, ...)`로 넘겼다.

그런데 detail payload는 list summary와 shape가 다르다. `startTimeGMT`, `startTimeLocal`,
`duration`, `elapsedDuration`, `movingDuration`, `distance`, `calories`, `averageHR`, `maxHR`가
top-level에 전혀 없고 전부 `summaryDTO` 안에 중첩돼 있다(실제 RAW로 swim/strength 양쪽 확인).
따라서 `normalize_activity`의 flat key 조회가 모두 None을 반환했고,
`ActivityRepository.refresh()`가 계약대로 전 컬럼을 무조건 UPDATE하면서 정상값이 NULL로 덮였다.

`timezone_name`(`timeZoneUnitDTO`)과 `name`(`activityName`)은 detail top-level에 있어 깨지지
않았다 — 실제 관측된 손상 필드 목록과 정확히 일치한다.

이 버그는 refresh 기능 도입 시점부터 있었고, 2026-09-28 "Live E2E validation"이 성공으로 기록된
strength `24481518495`도 실제로는 parent row가 NULL이 된 상태였다. 그 검증이 `strength_sets`만
확인하고 parent row를 보지 않아 놓쳤다.

### Code change

- `_detail_summary()`: `summaryDTO`를 top-level 위에 병합해 flat shape로 만든다. `summaryDTO`가
  없는 synthetic/legacy payload는 그대로 통과시킨다.
- `_preserve_missing_canonical_values()`: refresh가 값을 주지 못한 필드만 기존 DB 값을 유지한다
  (name/timezone 포함 11개 scalar, 기존 activity_metric, swim pool 관련 4개 필드). 새 값이 있으면
  항상 새 값이 이긴다.
- `normalize_garmin_swim(..., pool_length_factor_applies=)`: detail의 `summaryDTO.poolLength`는
  이미 factor가 적용된 값(25.0)이고 list의 `poolLength`는 적용 전 값(2500.0)이라, refresh 경로에서만
  factor 적용을 끈다. `swim_normalization.py`의 기존 factor 처리 자체는 그대로 둔다.
- `ActivityRepository.refresh()`의 전 컬럼 replace 계약은 변경하지 않았다.

### Regression tests

`tests/test_refresh_activity.py`에 3건 추가(전체 285 passed).

- `test_strength_refresh_reads_summary_dto_and_preserves_missing_parent_metadata`
- `test_swim_refresh_preserves_pool_metadata_when_detail_omits_pool_length`
- `test_swim_refresh_does_not_rescale_detail_summary_dto_pool_length`

### Real-device validation

`docs/CURRENT_STATE.md`의 "Verification" 2026-09-29 절 참고. 두 activity 모두 refresh 2회 실행 후
parent metadata drift 0, child row 수/내용 유지, 중복·orphan 0, 기존 RAW 불변, integrity ok.

### Known issue (데이터 안전성과 무관)

Refresh는 매번 새 capture를 append한다. `get_activity_details`가 호출마다 column 순서를 바꿔
돌려주고 `original.zip`이 타임스탬프를 포함하기 때문에 content-addressed dedup이 실제 응답에서는
절대 걸리지 않는다. 손상은 없고 저장공간만 증가한다.

## InBody integration rebase (2026-09-28)

- 이전 세션 대비 local main이 16 commits 전진했다(`85deeff` 날짜 범위 ingestion,
  `cba6a08` activity refresh 포함). `git branch -vv`로 local main을 직접 확인했다(origin과는
  별개로 diverge할 수 있다는 이전 경험 때문에 항상 local을 기준으로 삼는다).
- `git rebase main`으로 4개 feature commit(`8694abc` InBody foundation, `94fd37b` Samsung Health
  source, `68dee75` Samsung Health sync 통합, `774ca05` typing fix)을 순서대로 재적용했다.
  merge commit 없이 선형 history를 유지했다.
- 충돌은 매 커밋마다 `docs/HANDOFF.md`(세션별 로그라 매번 재작성하는 대신 main측 누적 내용을
  유지하고 이 파일에서 최종 정리), `docs/CURRENT_STATE.md`(durable state라 실제 내용을 비교해
  두 쪽을 모두 보존하도록 병합 — 특히 feature 쪽의 Galaxy live 검증 결과(`dataSource.appId=
  com.inbody2014.inbody` 확인)를 놓치지 않게 주의했다), `src/muscle50/cli.py`(양쪽이 각각 독립적인
  하위 명령을 추가한 것이라 실제 의미 충돌은 아니었고, import/`build_parser()`/`main()` dispatch/
  함수 목록을 전부 합쳐 하나의 완전한 파일로 재작성했다), `tests/test_cli.py`와
  `tests/test_database.py`(양쪽이 각자 추가한 테스트 함수를 모두 보존하고, `EXPECTED_TABLES`/
  `EXPECTED_VERSIONS`와 여러 개별 테스트에 흩어져 있던 하드코딩된 migration 버전 목록
  `[1,2,3,4,5,6]`을 전부 `[1,2,3,4,5,6,7]`로 업데이트)에서 발생했다. `ours`/`theirs`를 그대로 채택한
  곳은 로그성 `docs/HANDOFF.md`뿐이고, 나머지는 모두 두 내용을 직접 읽고 의미를 확인한 뒤 손으로
  재작성했다.
- Migration 충돌: `src/muscle50/infrastructure/sqlite/migrations/006_inbody.sql`을
  `007_inbody.sql`로 `git mv`하고 내부 `INSERT OR IGNORE INTO schema_migrations(...) VALUES (6, ...)`
  를 `VALUES (7, ...)`로 수정했다. `docs/CURRENT_STATE.md`, `docs/inbody-sync-design.md`,
  `tests/test_cli.py`, `tests/test_database.py`의 관련 참조를 모두 갱신했다. `tests/test_inbody_schema.py`
  등 shared loader(`ActivityRepository(...).migrate()`)만 쓰는 파일은 하드코딩된 파일명/버전이 없어
  수정이 필요 없었다.
- `android/inbody-diagnostic-companion/.gitignore`에 남아 있던 EOF 공백 줄(`git diff --check`가
  지적)을 제거했다.
- 재검증: `uv run pytest -q` 281 passed, `uv run ruff check .` 통과, `uv run mypy src tests` 통과
  (72 source files), `git diff --check` 통과. Migration 순서 001~007이 정확히 적용됨을
  `ls`와 `EXPECTED_VERSIONS`/`EXPECTED_TABLES` 테스트로 확인했다.
- Main merge/push는 이번 세션 범위 밖이다(명시적으로 지시받지 않음). Fast-forward는 가능한 상태다.

## Garmin Activity Refresh (2026-09-27)

- `RefreshGarminActivity`가 이미 local DB에 있는 activity만 대상으로 activity/details,
  splits, conditional strength exercise sets, original archive를 다시 가져온다.
- RAW는 기존 Recovery와 같은 content-addressed 방식으로
  `raw/garmin/activities/<id>/snapshots/<capture-id>/`에 보존한다. 초기 flat RAW와 이전
  refresh snapshot은 수정하지 않는다. 동일한 payload+warnings는 같은 capture를 재사용한다.
- RAW 파일 저장과 capture metadata 등록은 normalization보다 먼저 별도 commit한다.
  이후 normalization 또는 canonical persistence가 실패해도 새 RAW evidence는 남는다.
- Canonical update는 `activities` scalar fields/metrics, `strength_sets`, `swim_activities`
  (cascade로 laps/lengths 포함), accepted capture pointer를 하나의 `BEGIN IMMEDIATE`
  transaction에서 교체한다. 실패하면 이전 canonical 상태 전체가 rollback된다.
- Strength refresh에서 `exercise_sets`, pool swim refresh에서 `splits`가 없으면 불완전한
  refresh를 거부한다. 다른 sport의 optional split 실패와 original archive 실패는 warning만
  남기고 처리할 수 있다.
- `derive_activity_review()`는 ACTIVE set의 UNKNOWN/missing Garmin classification을
  `unknown_exercise_classification` reason과 set sequence 목록으로 반환한다. DB에 중복
  저장하지 않으며 종목을 추측하거나 자동 수정하지 않는다.
- Migration 6은 `activity_raw_captures`, `activity_raw_capture_artifacts`,
  `activity_refresh_state`를 추가한다. 기존 `activities.primary_raw_artifact_id`는 최초 import
  증거를 계속 가리키고, 최신 성공 refresh는 refresh state가 가리킨다.
- 테스트는 Strength UNKNOWN→corrected, child replacement, initial/previous/new RAW 보존,
  identical refresh, normalization/persistence rollback, required optional endpoint failure,
  Swim child replacement, normal range ingest의 non-refresh/idempotency를 synthetic data로 검증한다.

## Live E2E validation (2026-09-28)

사용자가 이 Paseo 세션 밖에서 실제 Garmin 계정으로 아래를 수행하고 결과를 보고했다:

- `MUSCLE50_HOME=C:\temp\muscle50-smoke`에서 activity 24481518495의 Garmin Connect 종목
  분류를 수동으로 수정한 뒤 이 feature worktree에서 다음을 실행했다.
  ```powershell
  uv run muscle50 garmin refresh 24481518495
  ```
- 출력:
  ```text
  Garmin activity refresh complete
  Garmin activity ID: 24481518495
  RAW snapshot:
  raw/garmin/activities/24481518495/snapshots/782859ca841d536670ef696f65e3959d1ed3a74b062e771542c6e2a04a595e75/manifest.json
  Strength sets replaced: 46
  Swim laps/lengths replaced: 0/0
  Review warnings remaining: none
  ```
- Canonical DB를 수동으로 확인한 결과, 이전에 `UNKNOWN`이거나 잘못 분류됐던 종목이
  사용자가 Garmin Connect에서 수정한 대로 정확히 교체됐다: `DUMBBELL_HAMMER_CURL`,
  `CLOSE_GRIP_EZ_BAR_BICEPS_CURL`, `INCLINE_SMITH_MACHINE_BENCH_PRESS`, `BENCH_PRESS`,
  `CLOSE_GRIP_BARBELL_BENCH_PRESS`.
- 이전에 의심스러웠던 `PUSH_UP` 40/50 kg 기록은 Garmin Connect 수정 후 `BENCH_PRESS`가
  됐다 — 이는 muscle50 정규화 버그가 아니라 Garmin 원본 분류 문제였음을 확인한다.
- 남은 관찰 사항: sequence 1은 `DUMBBELL_HAMMER_CURL` / 8 reps / 0.0 kg다. 지금은 별도
  휴리스틱을 추가하지 않는다 — 향후 data-quality/review 규칙 후보로만 기록한다(예:
  ACTIVE set의 weight가 0인 경우 review warning 후보로 검토).
- 이 live 실행은 수동 1회 smoke이며 자동 테스트 스위트에는 포함되지 않는다. 자동
  테스트는 여전히 synthetic fixture만 사용한다.

## Refresh files changed

- `README.md`, `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`
- `src/muscle50/application/refresh_garmin_activity.py` (신규)
- `src/muscle50/domain/activity_review.py` (신규)
- `src/muscle50/infrastructure/sqlite/migrations/006_activity_refresh.sql` (신규)
- `src/muscle50/infrastructure/raw_store.py`
- `src/muscle50/infrastructure/sqlite/database.py`
- `src/muscle50/infrastructure/garmin/client.py`
- `src/muscle50/cli.py`, `src/muscle50/presentation/terminal.py`
- `tests/test_refresh_activity.py` (신규)
- `tests/test_cli.py`, `tests/test_database.py`, `tests/test_garmin_connector.py`,
  `tests/test_ingest_range.py`

## Refresh verification

```text
uv run pytest -q                    191 passed
uv run ruff check .                 passed
uv run mypy src tests               passed (50 source files)
git diff --check                    passed
```

## Previous range-ingestion record

아래의 기존 날짜 범위 ingestion 기록은 이전 통합 작업의 배경이다.

## Completed

- `IngestGarminActivity`(신규, `application/ingest_activity.py`)를 canonical
  per-activity ingestion path로 도입했다. 기존 `SyncLatestGarminActivity.execute()`의
  activity별 로직(두 번의 activityId 일치 검사, RAW `preserve` → `normalize_activity` →
  lap_swimming일 때 `normalize_garmin_swim`으로 `swim_detail` 채우기, `repository.save`,
  기존 activity에 대한 Strength/Swim local RAW backfill)을 그대로 옮겼다 — 순서와 두
  검사 모두 원본과 동일하게 유지했다.
- `SyncLatestGarminActivity`는 이제 `latest_summary()` 호출과 `NoActivitiesError`만
  담당하는 thin wrapper이며, 나머지는 `IngestGarminActivity`에 위임한다. `SyncResult`,
  `NoActivitiesError`는 그대로 이 모듈에 남겨 `cli.py`/`terminal.py`의 기존 import를
  건드리지 않았다. `ActivitySyncError`만 `ingest_activity.py`로 옮기고 `cli.py`의 import
  한 줄을 그에 맞춰 갱신했다.
- `IngestGarminActivityRange`(신규, `application/ingest_activity_range.py`)를 추가했다.
  - `GarminConnector.list_activities(start, limit)`을 새로 추가하고 `latest_summary()`가
    내부적으로 이를 사용하도록 재구성했다(기존 wrapped/unwrapped 응답 처리 로직 그대로).
  - Garmin이 최신순으로 내려주는 목록을 페이지 단위로 순회하다가, 한 페이지에
    `from_date`보다 이전 activity가 나오면 그 페이지를 끝까지 처리한 뒤(같은 페이지의
    범위 내 activity를 놓치지 않기 위해) 조회를 멈춘다. 빈 페이지도 종료 조건이다.
  - `from_date`~`to_date`는 Garmin의 `startTimeLocal`(없으면 `startTimeGMT`)로 판단한다.
    이름 있는 timezone을 `zoneinfo`로 해석하지 않는다(이 머신의 tzdata 이슈와 무관하게,
    기존 domain 규칙대로 문자열을 있는 그대로 신뢰).
  - 페이지 간에 같은 activity가 중복으로 나타나도 한 번만 수집한다.
  - activity 하나의 실패(`ActivitySyncError`, `GarminConnectorError`,
    `NormalizationError`—`SwimNormalizationError` 포함—, `RawStoreError`,
    `sqlite3.Error`)는 해당 activity만 `failed`로 기록하고 나머지는 계속 처리한다.
    단, backfill 중 저장된 값과 로컬 RAW 재정규화 결과가 불일치할 때 발생하는 bare
    `RuntimeError`(`database.py`의 `_insert_strength_sets`/`_insert_swim_detail`,
    `ignore_existing=True`)는 의도적으로 잡지 않고 전체 범위 처리를 중단시킨다 — 이건
    로컬 데이터 정합성 버그이므로 조용히 "실패 1건"으로만 남기지 않기로 했다.
  - 50페이지(activity 1000건) 안전 상한에 도달하면 결과에 `page_limit_reached=True`로
    표시한다. 조용히 잘라내지 않는다.
- `muscle50 garmin activities --from YYYY-MM-DD --to YYYY-MM-DD` CLI를 추가했다.
  날짜 형식/범위 검증은 `garmin recovery`와 동일하게 Garmin 인증/네트워크 호출 전에
  실행한다.
- `terminal.py`에 `render_range_result`를 추가했다(기간, 발견/신규 저장/이미 저장됨/실패
  건수, 시작 시각 누락 건수, page limit 경고, 실패 activity ID/타입 목록). `garmin
  latest`의 출력은 변경하지 않았다.
- 새 RAW artifact나 migration은 추가하지 않았다: `normalize_garmin_swim`이 필요로 하는
  lap/length 계층은 이미 모든 activity에서 무조건 가져오는 `splits` RAW로 충분하고,
  Strength/Swim 스키마는 이미 migration 2/4에 있다.
- 실제 Garmin API는 호출하지 않았고 synthetic fixture(및 기존 `garmin_pool_swim.json`,
  `synthetic_strength_sets.json`)만 사용했다.

## Files changed

- `README.md`
- `docs/CURRENT_STATE.md`
- `docs/HANDOFF.md`
- `src/muscle50/application/ingest_activity.py` (신규)
- `src/muscle50/application/ingest_activity_range.py` (신규)
- `src/muscle50/application/sync_latest_garmin.py`
- `src/muscle50/cli.py`
- `src/muscle50/domain/normalization.py` (`local_date_from` 추가)
- `src/muscle50/infrastructure/garmin/client.py` (`list_activities` 추가)
- `src/muscle50/presentation/terminal.py`
- `tests/test_cli.py`
- `tests/test_garmin_connector.py`
- `tests/test_ingest_range.py` (신규, 21 tests)
- `tests/test_sync_latest.py` (swim normalizer monkeypatch 대상을 `ingest_activity`
  모듈로 재조정 — 추출로 인한 예상된 변경)

## Verification performed

```text
uv sync --extra dev                 passed
uv run pytest -q                    178 passed (151 pre-existing + 27 new)
uv run ruff check .                 passed
uv run mypy src tests               passed (47 files)
git diff --check                    passed
```

Pagination/range-stop 로직은 실제로 필터를 깨뜨려 관련 테스트 2개가 실패하는지 확인한
뒤 원복하는 방식으로 검증했다(sabotage test). `garmin latest`, Strength, Swim 관련
기존 회귀 테스트는 수정 없이 모두 통과했다(모니터패치 대상 재조정 제외).

## Remaining work

- 실제 Garmin 계정 live smoke: 완료(2026-09-28, activity 24481518495, 위 "Live E2E
  validation" 참고).
- Strength per-set / Swim per-lap 세부 데이터는 이미 존재하는 스키마와 정규화를 그대로
  재사용했을 뿐이며, 이번 작업에서 새로 만든 것은 없다.
- `sync_runs` 테이블은 여전히 미사용 상태다. command/error_code 값 체계가 정의되면
  range/latest 양쪽에서 사용할 수 있다.
  (2026-09-30) Recovery date coverage에는 날짜 column이 없어 부적합하다는 판단으로 보류 —
  `docs/garmin-analytics-prerequisites.md` E절.

## Known issues / risks

- pagination은 50페이지(activity 1000건) 상한이 있다. 결과의 `page_limit_reached`로
  드러나지만 더 깊은 재조회는 자동으로 하지 않는다.
- Garmin Connect는 비공식 API이므로 endpoint와 응답 형식이 바뀔 수 있다(기존 위험,
  변경 없음).
- 이 작업은 `client.py`, `cli.py`, `terminal.py`, `sync_latest_garmin.py`를 수정하므로
  main에 이후 병행 변경이 생기면 merge 전 재검증이 필요하다.

## Recommended next action

0. **(2026-09-30 갱신)** 최신 권장 순서는 위 "Garmin Analytics Prerequisites" 절의 Recommended next
   action을 따른다: historical import와 load-metric backfill은 완료됐고, 다음은 main 통합 결정 →
   Analytics Engine이다.
1. **다음 마일스톤: Analytics Engine.** Data collection layer는 2026-09-28에 VALIDATED,
   refresh safety gate는 2026-09-29에 SAFE로 닫혔다. InBody/Swim/Recovery/Strength canonical
   데이터가 실기기 기준으로 정상 저장·갱신됨이 확인됐으므로 읽기/집계 계층을 시작할 수 있다.
   현재 read layer가 전혀 없는 영역(예: swimming progression 기간 집계)이 첫 후보다.
   **아직 시작하지 않았다.**
