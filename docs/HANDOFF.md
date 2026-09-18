# Session Handoff

Last updated: 2026-09-19

## Current task

`feature/garmin-activity-ingestion`에서 Garmin activity를 날짜 범위로 수집하는 공통
ingestion pipeline을 추가하는 작업이다. `garmin latest`가 단일 activity만 처리하던
기존 구조를 그대로 유지하면서, 여러 activity를 한 번에 수집하는 `garmin activities
--from/--to`가 같은 canonical per-activity 경로를 재사용하도록 했다.

이 feature 브랜치는 원래 `origin/main`(commit `560a5d3`, Strength/Swim/Nutrition/
Recovery가 아직 없던 시점)에서 분기되어 있었다. 작업을 시작하기 전에 local `main`이
그 시점보다 14 commit 앞서 있다는 것을 발견해(Strength sets, Swim details, Nutrition
Core, Garmin Recovery가 이미 통합된 상태), 코드를 작성하기 전에 `feature/garmin-
activity-ingestion`을 `git merge --ff-only main`으로 local main(`7e2cd53`)까지
fast-forward한 뒤 다시 감사하고 구현했다. main은 이 과정에서 전혀 수정하지 않았다.
(fast-forward 전 stale base에서 만든 첫 구현은 `backup/garmin-activity-ingestion-
stale-audit-20260918` 브랜치에 참고용으로만 보존했다.)

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

- 실제 Garmin 계정 live smoke는 별도 승인 후 진행한다(아래 명령 참고). 아직 수행하지
  않았다.
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

로컬 review 후 `feature/garmin-activity-ingestion`을 main에 통합한다. Live Garmin
smoke는 별도 승인 후 아래 명령으로 진행하고, 이번 작업에서는 main merge와 remote
push를 하지 않는다.

```powershell
$env:MUSCLE50_HOME = "C:\temp\muscle50-smoke"   # Git worktree 바깥 경로
muscle50 garmin activities --from 2026-09-15 --to 2026-09-18
muscle50 garmin activities --from 2026-09-15 --to 2026-09-18   # 재실행 시 전부 skip 확인
```
