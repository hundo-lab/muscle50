# Session Handoff

Last updated: 2026-09-14

## Current task

clean 상태의 `feature/nutrition-core`를 최신 `main` 기반 별도 integration worktree에서
통합하고 provisional Nutrition schema를 global numbered migration chain에 편입하는 작업이다.

## Completed

- 최신 `main` `a856705` 기반 `integration/nutrition-core-20260914` worktree를 생성했다.
- clean 상태의 `feature/nutrition-core` `9d3f0ef`를 merge commit `a0fbe74`로 통합했다.
- `nutrition_schema.sql`을 정식 `003_nutrition.sql`로 승격하고 version 3 marker를 추가했다.
- 두 Nutrition repository의 `migrate()`가 기존 공용 numbered migration loader를 사용하도록
  연결했다.
- provisional `nutrition_schema.sql`을 제거해 SQLite schema source 중복을 없앴다.
- 새 DB, 기존 001+002 DB, 반복 migration 적용을 pytest와 별도 smoke check로 검증했다.
- Nutrition repository, supersession/append-only trigger, 전체 pytest, Ruff, mypy를 검증했다.
- 원본 feature branch/worktree와 InBody/Recovery migration은 수정하지 않았다.
- remote push는 수행하지 않았다.

## Files changed by integration follow-up

- `src/muscle50/infrastructure/sqlite/migrations/003_nutrition.sql`
- `src/muscle50/infrastructure/sqlite/nutrition_repository.py`
- `tests/test_database.py`
- `docs/nutrition-core.md`
- `docs/nutrition-core-handoff.md`
- `docs/CURRENT_STATE.md`
- `docs/HANDOFF.md`
- 제거: `src/muscle50/infrastructure/sqlite/nutrition_schema.sql`

Nutrition feature 자체의 신규 domain/application/infrastructure/schema/test 파일은 merge
commit `a0fbe74`에 포함된다.

## Verification performed

```text
uv sync --extra dev                                  passed
uv run pytest tests/test_database.py
  tests/test_nutrition_repository.py -q              26 passed
uv run pytest tests/test_nutrition_repository.py
  -k "supersession or append_only or cascaded_delete" -q
                                                     6 passed, 14 deselected
uv run pytest -q                                     116 passed
uv run ruff check .                                  passed
uv run mypy src                                      passed (25 source files)
git diff --check                                     passed
numbered migration smoke check                       passed, versions 1, 2, 3
```

Migration smoke check는 다음을 확인했다.

- 새 빈 DB에 `001_initial.sql` → `002_strength_sets.sql` → `003_nutrition.sql` 순서로 적용
- 기존 001+002 DB에 003만 추가하고 기존 version marker timestamp 보존
- 공용 loader를 두 번 실행해도 version marker 중복/변경 없음
- Nutrition trigger 3개가 정확히 생성됨

## Remaining work

- Nutrition 입력/use-case용 public CLI는 별도 product task로 남아 있다.
- InBody와 Garmin Recovery는 각 원본 worktree가 clean commit 상태가 된 뒤 최신 migration
  chain 다음 번호로 별도 통합해야 한다.

## Known issues / risks

- 실제 Garmin 계정 smoke test는 수행하지 않았다.
- feature-local provisional schema를 과거에 직접 적용한 외부 DB는 repository에 알려진 사용
  기록이 없으며, 그런 DB가 존재한다면 migration 3 marker 도입 전 별도 검토가 필요하다.
- Nutrition JSON Schema fixture는 pytest의 직접 파일 lookup으로 확인되지만, 이번 session에서
  별도 wheel artifact inspection은 수행하지 않았다.

## Recommended next action

검증된 integration tip을 `main`에 fast-forward한 뒤, clean status와 최종 migration 순서를
다시 확인한다. push는 명시적 요청 전까지 수행하지 않는다.
