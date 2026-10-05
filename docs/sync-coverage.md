# Garmin Sync Coverage v1

Spec: `docs/specs/sync-coverage.md`. Migration 010 (`010_sync_coverage.sql`, table `sync_coverage`).

## 목적과 non-goal

- 날짜별로 "동기화했고 Garmin에 데이터가 없었음"(`synced`, 0 stored)과 "동기화한 적 없음"(`not_synced`)을 구분해 기록한다.
- 기록 단위: (provider `garmin`, kind `activities`|`recovery`, calendar date). 날짜마다 **최신 결과 하나**(latest-state,
  `daily_recovery`와 같은 방식)와 그 결과의 시각(`synced_at_utc`), 실행 명령(`command`), 출처(`source`)를 둔다.
- Non-goal:
  - 추천 결정 변경 없음. focus, neglected, 수영 공백 규칙은 coverage를 읽지 않는다(표시만 추가).
  - 과거 activity coverage 추정 없음(과거 activity 날짜는 `not_synced`).
  - `garmin latest`, `garmin refresh`는 날짜 범위를 다루지 않으므로 coverage를 기록하지 않는다.
  - 자동 재동기화 없음. `sync_runs`는 계속 사용하지 않는다.

## 상태

| kind | status | 뜻 |
|---|---|---|
| activities | `synced` | 범위 탐색을 끝까지 마쳤고(discovery 성공, page limit 미도달, 날짜/ID를 읽을 수 없는 목록 항목 없음) 그 날짜의 activity가 모두 저장됨. activity 0개인 날도 `synced`. |
| activities | `failed` | 위 조건은 충족했지만 그 날짜의 activity 하나 이상이 저장에 실패함(`failed_activity_ids`). |
| recovery | `synced` | 9개 endpoint가 모두 응답함(Garmin의 "데이터 없음" null 응답도 성공). |
| recovery | `partial` | 일부 endpoint 호출이 실패함(`missing_endpoints`, connector 순서). 나머지는 저장됨. |
| recovery | `failed` | 그 날짜를 시도했지만 저장하지 못함(전 endpoint 실패, RAW/정규화/DB 오류). |
| 둘 다 | `not_synced` | 기록 없음. 저장되지 않는 상태다(row 부재). 인증 실패로 중단된 날짜, 시도하지 않은 날짜, 오늘 이후 날짜. |

`source`: `sync`(sync 명령이 기록) 또는 `raw_backfill`(recovery 전용, 아래 backfill이 기존 RAW capture에서 기록).

## 기록하는 명령

| 명령 | activities | recovery |
|---|---|---|
| `garmin activities --from --to` | 범위 전체 | - |
| `garmin recovery D` | - | D |
| `garmin recovery --from --to` | - | 시도한 날짜 |
| `daily` | D-1..D | D-1..D (full mode) |
| `garmin backfill-recovery-coverage` | - | 기록 없는 recovery 날짜(`raw_backfill`) |

- Coverage는 sync use case가 돌려준 결과 객체로 계산한다. Sync 자체의 동작, 출력, exit code는 바뀌지 않는다.
- 오늘(이 컴퓨터의 날짜, `cli._today()`) 이후 날짜는 기록하지 않는다. 예: `garmin activities --to 2026-12-31`이 미래 날짜를
  `synced`로 남기지 않는다.
- Discovery 실패(예외)나 page limit 도달, 날짜/ID를 읽을 수 없는 목록 항목(`undated_count > 0`)이 있으면 그 범위의
  activities는 하나도 기록하지 않는다. 그 항목이 범위의 어느 날짜든 될 수 있기 때문이다(추측하지 않음).
- Recovery 인증 실패 날짜와 그 뒤 `not_attempted` 날짜는 기록하지 않는다(`not_synced`).
- `daily`는 activities stage 직후, recovery stage 직후에 coverage를 기록하므로 같은 실행의 추천에 이미 반영된다.

### 기록 실패

Coverage는 sync가 끝난 뒤 **별도 transaction**으로 쓴다(activity ingest는 activity마다, recovery는 날짜마다 commit하므로
같은 transaction은 불가능). `sqlite3.Error`만 잡는다.

- stdout과 exit code는 sync 그대로다.
- stderr에 한 줄: `경고: sync coverage를 기록하지 못했습니다 (동기화된 데이터는 저장됨): <error>`.
- `daily`에서는 같은 내용(`경고: ` 접두사 없이)이 해당 stage(`activities`/`recovery`)의 warning이 되고 stage status는 그대로다.
- 한 번의 기록은 all-or-nothing이다. 실패하면 그 날짜들은 이전 상태(대개 `not_synced`)로 남는다. 실패한 기록이
  `synced`를 주장하는 일은 없다.

## 명령

```powershell
muscle50 garmin coverage --from 2026-10-01 --to 2026-10-05
muscle50 garmin coverage --from 2026-10-01 --to 2026-10-05 --json
muscle50 garmin backfill-recovery-coverage --dry-run
muscle50 garmin backfill-recovery-coverage
```

### `garmin coverage` (read-only)

- `mode=ro` + `query_only`. migrate, 디렉터리 생성, Garmin 호출 없음. `--from`/`--to` 둘 다 필요, 최대 366일.
- 날짜 형식, 역순 범위, 366일 초과는 DB를 열기 전에 `오류:`로 거부(exit 1, home 디렉터리도 만들지 않음). DB가 없으면
  `오류: muscle50 database not found: ...`(exit 1).
- Migration 010 이전 DB도 읽는다. 그때는 모두 `not synced`이고 마지막 줄에
  `Sync coverage is not recorded in this database yet (the next Garmin sync command creates it).`를 붙인다.

Text(합성 예시). activities 열 폭은 30, `(N stored)`는 그 local date에 지금 저장된 Garmin activity 수다(`synced`/`failed`는
항상, `not synced`는 N > 0일 때만).

```text
Garmin sync coverage 2026-10-01..2026-10-05 (latest recorded result per date)
date        activities                    recovery
2026-10-01  synced (0 stored)             synced
2026-10-02  synced (1 stored)             partial (1 endpoint failed)
2026-10-03  not synced (1 stored)         synced (backfilled from RAW)
2026-10-04  failed (1 failed, 0 stored)   not synced
2026-10-05  not synced                    not synced
activities: synced 2, failed 1, not synced 2; recovery: synced 2 (1 backfilled from RAW), partial 1, failed 0, not synced 2
Recorded by: garmin activities --from/--to, garmin recovery, daily. Not recorded: garmin latest, garmin refresh.
```

JSON(`indent=2`, ASCII, 고정 key 순서). 범위의 모든 날짜가 나온다. `not_synced`이면 `source`/`command`/`synced_at_utc`는
`null`, 목록은 빈 배열이다.

```json
{
  "from": "2026-10-02",
  "to": "2026-10-02",
  "coverage_table_present": true,
  "days": [
    {
      "date": "2026-10-02",
      "activities": {
        "status": "synced",
        "stored_activities": 1,
        "failed_activity_ids": [],
        "source": "sync",
        "command": "daily",
        "synced_at_utc": "2026-10-02T22:01:02.000000+00:00"
      },
      "recovery": {
        "status": "partial",
        "missing_endpoints": ["hrv"],
        "source": "sync",
        "command": "daily",
        "synced_at_utc": "2026-10-02T22:01:09.000000+00:00"
      }
    }
  ]
}
```

### `garmin backfill-recovery-coverage [--dry-run]`

- 이 feature 이전에 저장된 recovery 날짜를 채운다. `daily_recovery` row마다 그 row가 가리키는 accepted capture
  (`primary_raw_capture_id`)의 artifact kind를 보고, 9개 kind가 모두 있으면 `synced`, 빠진 kind가 있으면 `partial`로 기록한다.
  `source = raw_backfill`, `command = garmin backfill-recovery-coverage`, `synced_at_utc` = capture의 `captured_at_utc`.
- DB metadata만 읽는다. Garmin 호출 없음, RAW 파일을 읽거나 쓰지 않음.
- 이미 coverage row가 있는 날짜는 건드리지 않는다(쓰기 transaction 안에서 `ON CONFLICT DO NOTHING`으로 다시 확인).
  그래서 다시 실행해도 안전하다(두 번째 실행은 0건 추가). 이후의 sync는 backfill row를 최신 결과로 덮어쓴다.
- Activity는 backfill하지 않는다(과거 discovery 기록이 없다).

```text
Recovery coverage backfill from stored RAW (dry run, nothing written)
Recovery dates with an accepted RAW capture: 28
Already recorded (left unchanged): 2
Added as synced (backfilled from RAW): 25
Added as partial (backfilled from RAW): 1
Partial: 2026-09-03 (missing: respiration)
```

`--dry-run` 없이 실행하면 첫 줄은 `Recovery coverage backfill from stored RAW complete`이다.

## `recommend` / `daily` 표시

- 추천 창 D-28..D에 coverage row가 하나라도 있을 때만 바뀐다. 없으면(마이그레이션 이전 DB 포함) 기존과 byte-identical이다.
- JSON: `data_freshness.sync_coverage_recorded = true`, 그리고 `data_freshness` 마지막 key로 `sync_coverage`
  (`from`, `to`, 날짜별 `activities`, `stored_activities`, `recovery`, `recovery_source`). 시각과 명령 이름은 넣지 않으므로
  같은 데이터의 반복 실행 결과가 같다. `recommendation_version`은 1 그대로다.
- Text: `== Data freshness ==`의 statement 줄 뒤에 두 줄.

```text
  sync coverage 2026-09-07..2026-10-05: activities synced 3, failed 1, not synced 25 days; recovery synced 2 (1 backfilled from RAW), partial 1, failed 0, not synced 26 days
  days with no stored activity: synced, no activity: 2026-10-04; sync failed: 2026-10-02; not synced: 2026-09-07..2026-09-12, 2026-09-14..2026-10-01
```

  연속 날짜는 `A..B`로 묶고, 빈 구간은 `none`이다.
- 기존 statement("sync completeness is not recorded: ...")와 `activity_coverage_gap` notice 문구는 그대로 둔다(v2에서 정리).

## Known issues / limitations

- **Latest-state.** 날짜마다 최신 결과만 남는다. 나중에 실패한 재시도가 이전 `synced`를 `failed`로 덮어쓴다. 이력은 없다.
- **오늘의 `synced`**는 "`synced_at_utc` 시점까지 완료"라는 뜻이다. 그 뒤 같은 날 한 운동은 다음 sync 전까지 반영되지 않는다.
- Discovery 날짜는 Garmin 목록의 `startTimeLocal`(없으면 GMT)이고, 추천은 저장된 `started_at_local`을 쓴다.
  startTimeLocal이 없는 activity에서만 다를 수 있다.
- 날짜/ID를 읽을 수 없는 목록 항목이 최신 페이지에 계속 있으면 activities coverage가 계속 기록되지 않는다
  (`daily` JSON `activities.undated`로 확인).
- **Backfill 정확도.** 초기 capture에 어떤 endpoint kind가 실패가 아닌 이유(예: 나중에 추가된 endpoint)로 없으면
  `partial`로 backfill된다. Live Garmin 게이트에서 capture별 artifact kind 수를 확인한다.
- 과거 activity 날짜는 `not_synced`로 남는다(추정하지 않음). `garmin activities --from --to`로 다시 sync하면 기록된다.
- `garmin latest`, `garmin refresh`는 coverage를 기록하지 않는다(v2 후보).
- Coverage는 추천 결정에 쓰이지 않는다. 예: `synced`이고 activity가 없는 날을 실제 휴식으로 확정하는 것은 v2 후보다.
- `garmin coverage` 범위 최대 366일, text activities 열 폭 30은 기본값이다.
