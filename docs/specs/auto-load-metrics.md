---
id: auto-load-metrics
title: Auto Load Metrics on Garmin Sync v1
status: draft
migration: none
output_change: additive
user_gates: [design, integration, live-garmin, push]
---

# Auto Load Metrics on Garmin Sync v1

## 목적

- `garmin latest`와 `garmin activities --from/--to`로 새 activity를 가져오면 load metric 10종도 바로 채운다.
- 지금은 두 명령 뒤에 `garmin backfill-load-metrics`를 따로 실행해야 한다. `daily`만 이 작업을 자동으로 한다.
- 근거: docs/CURRENT_STATE.md(동결) Known issues("`garmin latest`/`garmin activities`는 activity-load metric을 채우지 않는다.
  ... 자동 enrichment 여부는 향후 설계 결정"), docs/garmin-analytics-prerequisites.md "보류: 향후 import의 자동 load-metric
  enrichment".

## 범위 / Non-goals

- 범위: `garmin latest`와 `garmin activities --from/--to`가 ingestion을 끝낸 뒤, 기존 `BackfillActivityLoadMetrics`를
  `daily`의 load_metrics 단계와 같은 방식으로 실행하고 결과를 출력한다.
- Non-goals:
  - load metric 추출 규칙 변경 없음.
  - shared normalizer에 load metric을 넣지 않음(기존 결정 유지).
  - `garmin refresh` 변경 없음.
  - `garmin backfill-load-metrics` 명령 제거 없음.
  - migration 없음.

## 명령 예시

```powershell
muscle50 garmin latest
muscle50 garmin activities --from 2026-10-01 --to 2026-10-05
```

기존 출력 뒤에 load metric 요약 블록이 붙는다(합성 예시, 정확한 문구는 설계에서 정한다).

```text
Load metrics: inserted 10, updated 0, unchanged 800
```

## 규칙

- 같은 use case(`BackfillActivityLoadMetrics`)를 재사용한다. RAW-only이고 idempotent하며 Garmin 호출이 없다.
  새 추출이나 정규화 로직을 만들지 않는다.
- 판정은 `daily`의 load_metrics 단계(`application/daily_sync.py` `_load_metrics`)와 같다.
  - 이번 실행에서 새로 저장한 activity의 RAW summary가 없거나 읽을 수 없으면 실패(exit 1)다. 이미 저장된 activity와 RAW는 그대로 둔다.
  - 이전부터 있던 activity의 RAW 문제와, 새 activity의 malformed 값은 경고 줄로 보여 준다.
- ingestion 자체가 실패하면(기존 exit 1 경로) load metric 단계를 실행하지 않는다. 기존 오류 출력은 변하지 않는다.
- 새 activity가 0건이어도 실행한다. idempotent해서 `unchanged`만 나온다.
- `daily`의 출력과 동작은 변하지 않는다(이미 load metric 단계가 있다).
- 테스트는 fake connector와 합성 RAW만 쓴다. 실제 계정 확인은 live Garmin 게이트에서 한다.

## 인수 조건

- [ ] AC1: fake connector로 새 activity 1건을 가져오는 `garmin latest`가 그 activity의 load metric을 저장하고 요약을 출력한다(exit 0).
- [ ] AC2: `garmin activities --from/--to`도 같다. 이미 저장된 activity만 있으면 `unchanged`만 나온다.
- [ ] AC3: 새 activity의 RAW summary가 없으면 exit 1이고 메시지가 나온다. activity row는 저장된 채로 남는다.
- [ ] AC4: ingestion 실패 시 load metric 단계가 실행되지 않고 기존 오류 출력이 그대로다.
- [ ] AC5: `daily`의 text와 JSON 출력이 변경 전과 byte-identical이다.
- [ ] AC6: 기존 sync 테스트는 출력 기대값에 load metric 블록을 추가하는 것 말고는 수정하지 않는다. 수정한 경우 이유를 보고한다.
- [ ] AC7: 품질 게이트 4개를 통과한다.

## 한계 / 후속 후보

- `garmin refresh` 뒤의 load metric 재계산(지금은 기존 값을 유지한다).
- 전체 activity를 매번 다시 확인하는 비용. 지금은 작지만 데이터가 늘면 대상을 새 activity로 좁히는 방안.
