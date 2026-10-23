---
id: strength-set-timing
title: Strength Set Timing Correction v1
status: draft
migration: none
output_change: additive
user_gates: [design, integration]
---

# Strength Set Timing Correction v1

## 목적

- 근력 운동에서 시계 버튼을 늦게 눌러 **운동한 시간이 휴식(REST)으로 기록된 세트**를 찾아, 실제 운동 시작 시각과 실제 휴식
  시간을 추정한다. 기록한 횟수와 무게는 정확하다는 전제다(사용자 확인 2026-10-23).
- 예: 원래 휴식 1분인데 버튼을 안 눌러 휴식이 3분으로 남고, 그 안에 30회를 한 뒤 다음 세트(운동 10초 안)에 횟수를 적는다.
  그러면 ACTIVE 세트는 1~2초에 4~5회처럼 불가능하게 짧고, 앞의 REST는 실제보다 길다.
- 근거(2026-10-23, 운영 RAW 읽기만):
  - 저장된 근력 활동 66개의 ACTIVE 세트 1282개 중 150개(약 12%)가 1회당 1초 미만이다. 예: 2026-10-21 활동
    24797858737의 풀업 세트가 1.7초에 5회, 1.6초에 4회.
  - 같은 활동의 `details.json`에 심박(`directHeartRate`)이 약 1초 간격(최대 12초 공백)으로 있다. `original.zip`(FIT)도 있다.
- 이 보정이 먼저 있어야 휴식 시간 조언(근거 규칙집), 세트 시간, 운동량 비교가 의미 있다. 수영의 비현실적 lap 표시(plausible lap
  detail)와 같은 방식으로 원본은 그대로 두고 파생 값을 따로 보여 준다.
- `docs/goals.md`의 근력 추천 루프 정확도에 기여한다.

## 범위 / Non-goals

- 범위:
  1. **의심 세트 찾기**: ACTIVE 세트 중 1회당 시간이 기준(설계에서 정함, 예: 1초) 미만인 것. 바로 앞이 REST인지 확인한다.
  2. **실제 시작 추정**: 앞 REST 구간의 심박 곡선에서 운동이 시작된 시점(심박이 오르기 시작한 곳)을 찾는다. 손목 심박은 운동보다
     늦게 오르므로 지연을 고려한다(설계에서 근거와 함께 정함). 심박으로 판단할 수 없으면 "의심, 추정 안 함"으로 둔다.
  3. **파생 값**: 세트마다 추정 운동 시간, 추정 휴식 시간, 추정 방법(`heart_rate` / `none`), 신뢰도. 원본 세트 기록(RAW, 정규화된
     세트)은 바꾸지 않는다.
  4. **보여 주기**: `analytics snapshot`(또는 설계에서 정한 명령)의 근력 절에 "보정된 휴식" 요약과 의심 세트 수를 더한다.
     `--json`에는 끝에 key를 더한다.
  5. **기존 RAW로 소급**: 이미 저장된 활동은 RAW만 읽어 다시 계산한다. Garmin을 다시 부르지 않는다.
- Non-goals:
  - 횟수, 무게, 운동 종류는 고치지 않는다(사용자가 정확히 기록한다).
  - 추천 규칙(세트 수, 무게 진행)은 이번에 바꾸지 않는다. 휴식 시간 조언은 근거 규칙집 뒤의 별도 기능이다.
  - Garmin 동기화 방식은 바꾸지 않는다(새 요청 없음).
  - LLM 없음. 결정적 규칙만.
  - migration: 파생 값을 저장해야 하면 설계에서 정한다(필요하면 `/feature`가 번호를 예약하고 운영 migration 게이트가 붙는다).

## 명령 예시

```powershell
muscle50 analytics snapshot --date 2026-10-23
muscle50 analytics snapshot --date 2026-10-23 --json
```

예상 text 출력에 더해지는 줄(합성 값, 정확한 문구는 설계에서 정한다):

```text
  Set timing: 38 ACTIVE sets, 4 too short for their reps (< 1.0 s/rep); 3 corrected from heart rate, 1 not estimated
    2026-10-21 24797858737 set 1 PULL_UP: recorded 1.7 s / rest 50 s -> estimated work 14 s / rest 37 s (heart_rate, medium)
  Rest between sets (corrected where estimated): median 52 s, compound 61 s, isolation 44 s
```

## 규칙

- 원본 우선: RAW와 정규화된 세트는 그대로다. 보정은 파생 값이고, 출력에 "estimated"와 방법이 붙는다.
- 추측하지 않는다: 심박이 없거나, 구간에 공백이 길거나, 오르는 지점이 분명하지 않으면 추정하지 않고 "not estimated"로 센다.
- 추정 운동 시간은 앞 REST 길이를 넘지 않는다. 추정 휴식은 0보다 작아지지 않는다.
- 기준값(1회당 최소 시간, 심박 상승 판단, 손목 심박 지연)은 상수로 두고 문서에 근거를 적는다.
- 같은 RAW에서는 언제나 같은 결과(byte-stable text/JSON). 읽기 전용 경로는 mkdir/migrate 하지 않는다.
- 의심 세트가 없으면 기존 출력은 byte-identical이다(새 줄은 요약 한 줄만, 설계에서 확정).

## 인수 조건

- [ ] AC1: 1회당 1초 미만인 ACTIVE 세트가 의심 세트로 잡히고, 정상 세트(예: 60초에 20회)는 잡히지 않는다.
- [ ] AC2: 앞 REST에서 심박이 분명히 오른 합성 데이터는 그 시점(지연 보정 포함)으로 추정 운동·휴식 시간이 나온다.
- [ ] AC3: 심박이 없거나 공백이 길거나 상승이 불분명하면 "not estimated"이고 값을 만들지 않는다.
- [ ] AC4: RAW, 정규화된 세트, 기존 추천 출력은 바뀌지 않는다(byte-identical).
- [ ] AC5: 저장된 RAW만으로 소급 계산되고 Garmin 호출이 없다.
- [ ] AC6: text와 `--json`이 결정적이고 JSON은 끝에 key만 더한다.
- [ ] AC7: 실제 RAW(읽기 전용, 임시 복사본)에서 2026-10-21 활동 24797858737의 풀업 세트 1·2가 의심 세트로 잡힌다.
- [ ] AC8: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- 손목 심박은 근력 운동에서 부정확하고 늦다. 추정은 범위와 신뢰도로만 보여 준다.
- 후속 후보: 근거 규칙집 기반 휴식 시간 조언(운동별 권장 휴식과 실제 비교), 세트 시간·TUT(긴장 시간) 지표, v3 에이전트 도구로 열기.
