---
id: strength-set-timing-rest-start
title: Strength Set Timing - derived REST start v1.1
status: integrated
migration: none
output_change: additive
user_gates: [design, integration]
---

# Strength Set Timing - derived REST start v1.1

## 목적

- Strength Set Timing v1(`docs/specs/strength-set-timing.md`)은 의심 세트 앞 REST의 **시작 시각**이 있어야 추정한다. 그런데 일부
  Garmin 활동은 REST 행의 `startTime`이 모두 `null`이다(휴식 길이 `duration`은 있다). 그런 활동의 의심 세트는 전부
  `set_time_missing`으로 빠진다.
- 근거(2026-10-30, 운영 RAW 읽기만):
  - 근력 활동 67개 중 9개(2026-09-03 ~ 2026-10-28)가 REST `startTime`이 전부 null이다(REST 행 1363개 중 209개). 최근 활동에 몰려 있다.
  - 예: 2026-10-28 활동 24876655521의 `seq 11 PULL_UP`(5회 0.4 s)과 `seq 61 CURL`(12회 1.7 s)이 `set_time_missing`.
  - REST 앞뒤가 모두 ACTIVE인 1317곳에서 "다음 세트 시작 - REST 길이"와 "앞 세트 시작 + 앞 세트 길이"를 비교하면 1292곳(98.1 %)이
    1초 안에서 맞는다. 크게 어긋나는 몇 곳(최대 약 266 s)은 시계 일시정지 같은 경우로 보인다(확인 안 됨).
- 사용자 승인(2026-10-30 제안, 2026-10-31 "승인"): 기록된 값으로 REST 시작을 계산하고, 두 방법이 ±1초 안에서 맞을 때만 쓴다.

## 범위 / Non-goals

- 범위:
  1. REST `started_at`이 기록돼 있으면 지금처럼 그 값을 쓴다(동작·출력 그대로).
  2. 비어 있으면 **derived** REST 시작 = 의심 세트(다음 ACTIVE) 시작 - REST `duration`.
  3. 교차 확인: REST 바로 앞 행이 ACTIVE이고 그 시작과 길이가 있으면, 앞 세트 시작 + 앞 세트 길이와 derived 값의 차이가
     **1000 ms 이하**일 때만 쓴다(`[design]`, 근거 없음; Garmin 세트 시작은 1초 단위). 앞 행이 없거나 값이 없거나 차이가 크면
     추정하지 않고 새 이유 `rest_start_unverified`로 센다. REST `duration`이 없으면 지금처럼 `set_time_missing`.
  4. 출력: 의심 세트 JSON 행 끝에 `rest_start_source`(`"recorded"` / `"derived"` / `null`(추정 안 함으로 REST 시작을 쓰지 않은 경우))를
     더한다. text는 derived일 때만 괄호 안에 `rest start derived [design]`을 붙인다. `rules`에 허용 오차, `evidence`에 그 항목을 더한다.
  5. `docs/strength-set-timing.md`에 규칙, 상수, 이유, 알려진 한계를 적는다.
- Non-goals:
  - RAW, 정규화된 세트, 저장 방식은 바꾸지 않는다(계산은 읽을 때만, migration 없음). REST `started_at`을 저장하지 않는다.
  - 추정 규칙(심박 상승, 지연 보정, 신뢰도)과 다른 이유들은 바꾸지 않는다.
  - Garmin 동기화는 바꾸지 않는다.

## 규칙

- 원본 우선: 기록된 REST 시작이 있으면 늘 그것을 쓴다. derived는 기록이 없을 때만이고, 출력에 표시된다.
- 추측하지 않는다: 교차 확인을 못 하거나 어긋나면 추정하지 않는다.
- 같은 RAW에서는 같은 결과(byte-stable). 의심 세트가 없으면 `analytics snapshot` 출력은 지금과 byte-identical. 다른 명령은 늘 그대로.

## 인수 조건

- [x] AC1: REST `startTime`이 null이고 교차 확인이 1000 ms 안에서 맞는 합성 데이터에서, 의심 세트가 v1과 같은 방식으로 추정되고
  `rest_start_source: "derived"`와 text 표시가 붙는다. derived REST 시작 = 다음 세트 시작 - REST 길이다.
- [x] AC2: 차이가 1000 ms를 넘거나(1001 ms), REST 앞 행이 없거나 ACTIVE가 아니거나, 앞 세트 시작·길이가 없으면 `rest_start_unverified`로
  추정하지 않는다. 경계 1000 ms는 쓴다.
- [x] AC3: REST `startTime`이 기록된 경우의 결과는 v1과 같고 `rest_start_source: "recorded"`다(기록값이 derived와 달라도 기록값을 쓴다).
- [x] AC4: RAW, 정규화된 세트, `recommend`/`daily` 출력은 바뀌지 않는다. 의심 세트가 없는 창의 `analytics snapshot`은 byte-identical.
- [x] AC5: 실제 RAW 확인(읽기 전용): 통합 후 main checkout에서 `analytics snapshot --date 2026-10-28 --days 1 --json`을 실행해
  활동 24876655521의 `seq 11`, `seq 61`이 더 이상 `set_time_missing`이 아니다(`heart_rate` 또는 다른 이유). 상태만 기록한다.
  확인(2026-11-01, main daf27a5, 운영 DB 읽기 전용, 상태만): heart rate `available`, lag `calibrated`. `seq 61 CURL #1`은
  `heart_rate`(low), `rest_start_source: "derived"`로 추정됐다. `seq 11 PULL_UP #1`은 derived REST 시작을 지나 심박 단계에서
  `heart_rate_gap`으로 추정하지 않았다(REST 198 s). 두 세트 모두 `set_time_missing`이 아니다.
- [x] AC6: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- 시계 일시정지가 REST 안에 있으면 derived 시작이 틀릴 수 있다. 교차 확인이 대부분을 걸러 내지만, 일시정지가 앞 세트 쪽이면 못 잡을 수 있다.
- REST 시작이 기록된 활동에서 기록값과 derived 값이 어긋나는 곳(최대 약 266 s)의 원인은 확인하지 않았다.
- 구현자·검증자가 보고한 한계:
  - `rest_start_source`는 추정하지 않은 세트에서는 늘 null이다. 그래서 REST 시작을 derived로 얻었지만 `heart_rate_gap` 등으로
    빠진 세트는 그 사실이 출력에 보이지 않는다.
  - REST 시작이 null인 활동에서 이제 추정되는 세트가 `rest_between_sets`에 추정 휴식으로 들어간다. 그런 기간은
    `excluded_not_estimated`가 줄고 중앙값·개수가 바뀔 수 있다(규칙 10은 그대로).
  - REST 시작이 null인 활동에서 활동의 첫 REST와 REST 바로 뒤 REST는 교차 확인을 못 해 `rest_start_unverified`다.
  - 앞 행을 끝에서 되돌아 읽지 않게 하는 `index >= 2` 조건은 코드로만 확인했고 이를 고정하는 테스트는 없다.
  - 허용 오차 1000 ms는 `[design]` 값이다(근거 없음).
- migration은 없고 Garmin 동기화를 바꾸지 않으므로 production migration(gate 3)과 live Garmin 확인(gate 4)은 없다.

## 구현 결정 (검증자 승인, 2026-11-01)

설계는 이 spec 자체다(별도 계획 없음). 구현에서 정한 해석, 상세: `docs/strength-set-timing.md`.

- 확인 순서: `no_preceding_rest` -> `set_time_missing`(의심 세트 시작·길이) -> REST 시작 결정(`rest_start_unverified`) -> v1 심박 이유.
- derived는 `startTime`이 비어 있을 때(null 또는 "")만이다. 기록됐지만 읽을 수 없는 시작은 바꾸지 않고 v1처럼 `set_time_missing`.
- 앞 행은 ACTIVE이고 시작·길이만 있으면 된다(`is_checked`는 따지지 않는다).
- `rest_start_source`는 추정한 세트에서만 값이 있다(`estimated_*`, `confidence`와 같다). text 표시도 추정한 줄에만 붙는다.
- 새 공개 이름: `RestStartSource`(`recorded`/`derived`), `NotEstimatedReason.REST_START_UNVERIFIED`,
  `MAX_REST_START_DISAGREEMENT_MILLISECONDS = 1000`, `REST_START_DISAGREEMENT_EVIDENCE = ("design",)`.
  `rules`·`evidence` key는 `max_rest_start_disagreement_seconds`.
- `SET_TIMING_VERSION`은 1 그대로다(추가만 하는 변경).
