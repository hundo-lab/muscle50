# Garmin Analytics Prerequisites

Analytics(주간 부하, 회복 추세 등)를 시작하기 전에 필요한 canonical 데이터 기반을 정리한다.
Analytics 자체와 데이터 품질 판정은 이 문서 범위 밖이다.

## A. Activity-load metric contract

`src/muscle50/domain/activity_load.py`의 `ACTIVITY_LOAD_METRICS`가 유일한 정의다.
`activity_metrics`에 기존 schema 그대로 저장한다(migration 없음).

| metric_key | RAW source (`summary.json`, flat list shape) | unit | 의미 |
| --- | --- | --- | --- |
| `training_load` | `activityTrainingLoad` | `score` | Garmin training load, unitless |
| `aerobic_training_effect` | `aerobicTrainingEffect` | `score` | Garmin 0–5 scale, unitless |
| `anaerobic_training_effect` | `anaerobicTrainingEffect` | `score` | Garmin 0–5 scale, unitless |
| `hr_time_in_zone_1_seconds` … `hr_time_in_zone_5_seconds` | `hrTimeInZone_1` … `hrTimeInZone_5` | `s` | HR zone별 체류 시간(초) |
| `moderate_intensity_minutes` | `moderateIntensityMinutes` | `min` | 중강도 활동 시간(분) |
| `vigorous_intensity_minutes` | `vigorousIntensityMinutes` | `min` | 고강도 활동 시간(분, RAW 원값) |

`source_path`는 기존 metric 관례대로 RAW key 이름 그대로 기록한다.

Unit 검증(2026-09-29, production RAW 42건 전수): zone 합계가 모든 activity에서 `duration`(초)
이하, training effect는 모두 0–5 범위, intensity minutes 합계는 duration/60 이하였다. 42건
모두 10개 key를 JSON number로 가지고 있었다.

### 값 처리 규칙

- JSON number(int/float, finite)만 canonical 값으로 인정하고 값은 가공 없이 그대로 복사한다.
- key 없음 → `missing`, `null` → `null`: 둘 다 "skipped"로 보고하고 쓰지 않는다.
- bool, 문자열(숫자 문자열 포함), object, NaN/Infinity → `malformed`로 보고하고 쓰지 않는다.
- 범위/부호/생리학적 타당성 검사는 하지 않는다(예: TE 5.7, 음수 zone 시간도 그대로 복사).
  이는 향후 Analytics quality layer의 책임이다. 2026-09-17 swim anomaly도 여기서 수정하지 않는다.
- RAW 값이 missing/null/malformed여도 이미 저장된 canonical 값은 삭제하거나 덮어쓰지 않는다.

### Refresh와의 관계

이 metric들은 `normalize_activity`에 추가하지 않았다. 따라서 검증 완료된 `garmin refresh`
경로가 쓰는 값은 이전과 완전히 동일하다. Refresh는 `_preserve_missing_canonical_values()`로
자신이 생산하지 않는 기존 metric key를 그대로 유지하므로 backfill된 값은 refresh 후에도 변하지
않는다(`test_backfilled_metrics_survive_a_detail_shape_refresh_unchanged`). Detail endpoint의
`summaryDTO`에 같은 이름의 key가 있어도 읽지 않는다.

## B. RAW → canonical backfill

```powershell
uv run muscle50 garmin backfill-load-metrics --dry-run   # 변경 예정 건수만 보고
uv run muscle50 garmin backfill-load-metrics
```

- Garmin connector 의존성 자체가 없다. 인증/API 호출/refresh 경로를 절대 타지 않는다.
- DB의 activity 목록을 기준으로 각 activity의 초기 flat `summary.json`만 읽는다.
  `snapshots/`(refresh detail shape)는 읽지 않는다.
- `activity_metrics`의 위 10개 key만 insert/update한다(repository가 allow-list 밖 key를 거부).
  RAW, `activities`, `strength_sets`, swim 테이블, 다른 metric은 쓰지 않는다.
- activity 단위 transaction. 두 번째 실행은 inserted/updated 0(idempotent).
- 보고: activities examined, RAW summaries found, activities changed, inserted, updated,
  already identical, missing RAW, unreadable RAW, malformed values, skipped values.

`garmin latest`, `garmin activities --from/--to`, `daily`는 ingestion이 끝난 뒤 이 backfill을 같은 판정으로
자동 실행한다(shared normalization은 그대로). 그래서 새 activity를 import한 뒤 backfill을 따로 실행할 필요가
없다. 이 명령은 수동 재확인과 과거 데이터용으로 남아 있다. 자세한 내용: `docs/auto-load-metrics.md`.

## C. Recovery range sync

```powershell
uv run muscle50 garmin recovery 2026-09-15                                  # 기존 단일 날짜(변경 없음)
uv run muscle50 garmin recovery --from 2026-09-01 --to 2026-09-03           # 7일 이하
uv run muscle50 garmin recovery --from 2026-09-01 --to 2026-09-28 --yes     # 8~31일은 --yes 필요
```

- 양 끝 포함(inclusive), 날짜 오름차순으로 하루씩 순차 호출. 동시성 없음.
- 날짜당 recovery endpoint 9회 호출. 범위 최대 31일. 7일 초과는 `--yes` 없이는 인증 전에 거부.
- 날짜 형식 오류, 역순 범위, `--from`/`--to` 한쪽 누락, 날짜 인자와 범위 혼용은 인증 전에 거부.
- 날짜별 RAW는 기존과 같이 `raw/garmin/recovery/<date>/<capture-id>/`에 저장되어 provenance가
  날짜 단위로 유지된다. 각 날짜는 기존 단일 날짜 use case(`SyncGarminRecovery.execute`)를 그대로 쓴다.
- 한 날짜의 실패는 다른 날짜를 되돌리지 않는다. 결과는 created/updated/unchanged/failed/
  not_attempted로 날짜별 보고하고, 하나라도 failed/not_attempted면 exit code 1.
- 인증 실패(`GarminAuthenticationError`) 시 즉시 중단하고 나머지는 not_attempted.
  연속 3개 날짜 실패(throttling/장애 추정)도 중단한다.
- 재실행은 결정적이다: 같은 응답이면 새 capture 없이 unchanged, 실패했던 날짜만 새로 저장된다.

Recovery normalizer가 바뀌면 저장된 accepted capture에서 Garmin 호출 없이 재생성한다:

```powershell
uv run muscle50 garmin recovery-renormalize --dry-run
uv run muscle50 garmin recovery-renormalize
```

## D. Historical activity import (미실행)

기존 range import는 그대로 사용한다(재작성하지 않음). 현재 이력을 앞쪽으로 확장하는 명령:

```powershell
uv run muscle50 garmin activities --from 2026-07-01 --to 2026-08-02
```

`garmin activities`가 load metric을 자동으로 채우므로 별도 `garmin backfill-load-metrics` 단계는 필요 없다.

실행 전 DB backup(WAL-safe: `sqlite3` backup API 또는 `VACUUM INTO`)을 만든다. 아직 실행하지
않았다 — 명시적 승인 후 실행한다.

## E. `sync_runs` 연동 — 보류

`sync_runs`(migration 1)는 `provider, command, status, source_activity_id, error_code,
started_at_utc, finished_at_utc`만 가진다. Recovery coverage에 쓰려면 다음을 구분해야 하는데
현재 schema로는 불가능하다.

- "날짜를 sync했고 Garmin에 데이터가 없었다" vs "그 날짜를 sync한 적이 없다":
  날짜 컬럼이 없어서 어떤 run이 어떤 calendar date를 다뤘는지 기록할 곳이 없다.
  `source_activity_id`에 날짜 문자열을 넣거나 `error_code`/`command`에 인코딩하는 것은 의미를
  오용하는 것이라 하지 않는다.
- 범위 run 하나가 여러 날짜를 포함하고 날짜별 결과가 다르다(created/unchanged/failed).
  run 단위 row 하나로는 날짜별 상태를 표현할 수 없다.

현재 대체 증거: `recovery_raw_captures.requested_date`는 "해당 날짜를 요청해 응답 일부라도
받았다"를 보여준다(no-data day도 null payload capture로 남는다). 그러나 전 endpoint 실패나
인증 실패로 capture가 없는 날짜와 한 번도 요청하지 않은 날짜는 여전히 구분되지 않는다.

향후 해결안(별도 migration 필요): 예) `sync_run_dates(run_id, calendar_date, status, capture_id,
error_code)` 같은 날짜 단위 coverage 테이블. 이번 feature에서는 migration을 추가하지 않는다.
