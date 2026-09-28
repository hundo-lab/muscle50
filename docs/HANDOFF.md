# Session Handoff

Last updated: 2026-09-28

## Current task

`feature/inbody-connector`(HEAD `f205b20`)를 최신 local `main`(`cba6a08`, Garmin activity refresh까지
반영)에 rebase해 fast-forward 가능한 상태로 준비했다. Main과 feature가 각자 독립적으로 migration 6을
썼던 충돌(main `006_activity_refresh.sql` vs feature `006_inbody.sql`)을 InBody 쪽을
`007_inbody.sql`로 재배정해 해결했다. **Main merge는 아직 하지 않았다** — 이번 세션은 통합 준비까지만
수행한다.

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

## Known issues / risks

- pagination은 50페이지(activity 1000건) 상한이 있다. 결과의 `page_limit_reached`로
  드러나지만 더 깊은 재조회는 자동으로 하지 않는다.
- Garmin Connect는 비공식 API이므로 endpoint와 응답 형식이 바뀔 수 있다(기존 위험,
  변경 없음).
- 이 작업은 `client.py`, `cli.py`, `terminal.py`, `sync_latest_garmin.py`를 수정하므로
  main에 이후 병행 변경이 생기면 merge 전 재검증이 필요하다.

## Recommended next action

Live E2E validation(activity 24481518495)이 완료되고 quality gate가 모두 통과해
Garmin Activity Refresh 변경을 `feature/strength-sets`에 커밋했다. Main merge와 push는
아직 하지 않았다 — 다음 세션에서 별도 승인 후 진행한다.
