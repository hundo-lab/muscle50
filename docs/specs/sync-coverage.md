---
id: sync-coverage
title: Garmin Sync Coverage v1
status: draft
migration: none
output_change: additive
user_gates: [design, integration, prod-migration, live-garmin, push]
---

# Garmin Sync Coverage v1

## 목적

- 날짜별로 "동기화했고 데이터가 없었음"과 "동기화한 적 없음"을 구분해 기록한다.
- 지금은 `sync_runs`에 날짜 column이 없어 둘을 구분할 수 없다. 그래서 추천이 "활동 없음"을 휴식으로 확정하지 못하고 notice만 낸다.
  근거:
  - docs/garmin-analytics-prerequisites.md "E. `sync_runs` 연동 — 보류"(날짜 단위 coverage table 제안)
  - docs/training-recommendation.md "데이터 신선도"(`sync_coverage_recorded = false`)
  - CURRENT_STATE(동결) Known issues

## 범위 / Non-goals

- 범위:
  - activity와 recovery sync가 다룬 날짜마다 coverage를 기록한다.
  - 조회 명령 `muscle50 garmin coverage --from D --to D [--json]`을 추가한다.
  - `recommend`/`daily`의 `data_freshness`에 coverage 정보를 추가(additive)한다.
- Non-goals:
  - 추천 결정 규칙 변경 없음. focus, neglected 판정, 수영 공백 처리는 그대로이고 표시만 정확해진다(v2 후보).
  - 과거 activity coverage 추정 없음.
  - `garmin refresh` coverage 없음.
  - 자동 재동기화 없음.

## 명령 예시

```powershell
muscle50 garmin coverage --from 2026-10-01 --to 2026-10-05
muscle50 garmin coverage --from 2026-10-01 --to 2026-10-05 --json
```

```text
date        activities              recovery
2026-10-01  synced (0 stored)       synced
2026-10-02  synced (1 stored)       partial (1 endpoint failed)
2026-10-03  not synced              synced (backfilled from RAW)
2026-10-04  failed                  not synced
2026-10-05  not synced              not synced
```

(합성 예시. 정확한 표현과 JSON 구조는 설계에서 정한다. 상태 이름 예: `synced`/`partial`/`failed`/`not_synced`.)

## 규칙

- 기록 단위는 (provider, kind=`activities`|`recovery`, calendar_date)다. 각 기록에는 최신 결과, 시각, 실행 명령을 둔다.
  날짜별 이력은 append-only로 남길지, 최신 상태만 둘지 설계에서 정한다. 어느 쪽이든 기존 table은 ALTER하지 않는다.
- **activities:**
  - `garmin activities --from/--to`와 `daily`(D-1~D)가 범위 탐색을 끝까지 마쳤다면 범위 안 모든 날짜를 `synced`로 기록한다.
    마친 조건은 discovery 성공, page limit 미도달이다. activity가 0개인 날도 `synced`다.
  - activity별 실패가 있었던 날짜는 `failed`로 기록한다.
  - discovery 실패나 page limit 도달이면 날짜를 `synced`로 기록하지 않는다.
  - `garmin latest`는 날짜 범위를 다루지 않으므로 coverage를 기록하지 않는다.
- **recovery:**
  - 날짜별 결과를 기록한다: 모든 endpoint 성공은 `synced`, 일부 실패는 `partial`, 전부 실패는 `failed`.
  - 인증 실패 등으로 시도하지 않은 날짜는 기록하지 않는다(= `not_synced`).
- **과거 데이터:**
  - recovery는 `recovery_raw_captures`(요청 날짜)로부터 "RAW에서 backfill됨"으로 채울 수 있다. 출처를 구분해 표시한다.
  - activity는 과거 기록이 없으므로 `not_synced`로 둔다. 문서에 한계로 적는다.
- 기록 실패가 sync 자체를 실패시키지 않는다. 설계에서 정하되, sync 결과를 잃지 않는 쪽으로 한다.
- `recommend`/`daily`:
  - `data_freshness`에 coverage가 있으면 `sync_coverage_recorded: true`로 하고, 창 안의 날짜별 상태를 추가한다(JSON 끝쪽 key).
  - text에는 "synced, no activity"와 "not synced"를 구분하는 줄을 붙인다.
  - coverage row가 하나도 없으면 기존 출력과 byte-identical이다.
- read-only reader는 migration 이전 DB도 읽는다.
- 테스트는 fake connector만 쓴다. 실제 계정 확인은 live Garmin 게이트에서 한다.

## 인수 조건

- [ ] AC1: fake connector로 `garmin activities --from/--to`(activity 0개인 날 포함)를 실행한 뒤 `garmin coverage`가 범위 전체를
      `synced`로 보여 준다.
- [ ] AC2: discovery 실패나 page limit 도달 시 그 범위가 `synced`로 기록되지 않는다.
- [ ] AC3: recovery 일부 endpoint 실패는 `partial`, 전체 실패는 `failed`, 시도하지 않은 날짜는 `not_synced`다.
- [ ] AC4: 기존 recovery capture로부터 backfill된 날짜가 출처와 함께 표시된다.
- [ ] AC5: coverage row가 없는 DB에서 `recommend`/`daily`의 text와 JSON이 기존과 byte-identical이다.
      coverage가 있으면 추가 key와 줄만 생긴다.
- [ ] AC6: 이번 migration 이전 DB에서 read-only 명령이 동작한다.
- [ ] AC7: 추천 결정(JSON의 strength/swim 계획 부분)은 coverage 유무와 상관없이 같다.
- [ ] AC8: 품질 게이트 4개를 통과한다.

## 한계 / 후속 후보

- coverage를 추천 결정에 반영(v2): 예를 들어 `synced`이고 활동이 없으면 실제 휴식으로 확정.
- `garmin latest` coverage, refresh coverage.
- 남는 `sync_runs` 정리 여부.
