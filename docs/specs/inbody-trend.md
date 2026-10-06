---
id: inbody-trend
title: InBody Body Composition Trend v1
status: draft
migration: none
output_change: additive
user_gates: [design, integration, push]
---

# InBody Body Composition Trend v1

## 목적

- 저장된 InBody 측정을 시간순으로 보여 주고, 측정 사이의 체중·골격근량(SMM)·체지방량 변화와
  1차 목표(SMM 43 kg)·장기 목표(50 kg)까지 남은 양을 한 명령으로 확인한다.
- 근거: InBody 측정은 `inbody sync`로 저장만 되고 읽는 코드가 없다(docs/PROJECT_CONTEXT.md 14-2 "체성분 미활용").
  `TrainingGoals.skeletal_muscle_mass_milestone_kg`/`_long_term_kg`는 정의만 있고 쓰이지 않는다
  (docs/training-recommendation.md "v1 규칙에서 사용하지 않음, 기록용").
- `docs/goals.md` 우선순위 2: 체성분 판단을 "InBody 측정과 측정 사이" 단위로 하는 루프의 토대다. 후속
  "측정 사이 리뷰"와 조정 권고가 이 결과를 쓴다. 사용자는 매일 체중을 재지 않고 InBody를 한 달에 1~2회 잰다.

## 범위 / Non-goals

- 범위:
  - 새 read-only 명령 `muscle50 inbody trend [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--json]`.
  - 지표 4개: 체중(kg), 골격근량(kg), 체지방량(kg), 체지방률(%).
  - 측정 목록, 지표별 측정 사이 변화, 기간 처음→마지막 변화, 목표까지 남은 양, 마지막 측정 후 경과 일수.
- Non-goals:
  - migration 없음. 저장 데이터 변경 없음.
  - 체중 수동 입력 기능 없음(사용자가 매일 체중을 재지 않는다).
  - `recommend`, `daily`, `nutrition` 출력 변경 없음(체성분을 추천에 넣는 것은 후속 리뷰 기능).
  - 판단·권고 문구 없음(좋다/나쁘다, 칼로리 조정 등). 사실 수치만.
  - 목표 도달 시점 예측 없음.
  - 같은 측정으로 보이는 행의 자동 병합 없음. DB의 행은 그대로 둔다.
  - 부위별(segmental), 기초대사량, 체수분, InBody 점수 등 나머지 지표 없음(후속 후보).
  - `inbody sync` 동작·출력 변경 없음(`--show-values` 정책 포함).

## 명령 예시

```powershell
muscle50 inbody trend
muscle50 inbody trend --from 2026-07-01 --to 2026-10-05
muscle50 inbody trend --json
```

예상 text 출력(합성 값):

```text
InBody body composition trend: 3 measurements on 3 dates (2026-07-02 to 2026-09-16)
Values are stored InBody results rounded to 0.1. Missing values are shown as unknown.

Measurements:
  2026-07-02 08:10  weight 80.0 kg  SMM 36.0 kg  body fat 15.0 kg  PBF 18.8 %
  2026-08-05 08:05  weight 80.6 kg  SMM 36.5 kg  body fat 15.1 kg  PBF 18.7 %
  2026-09-16 16:43  weight 81.0 kg  SMM 36.9 kg  body fat unknown  PBF unknown

Between measurements:
  2026-07-02 -> 2026-08-05 (34 d): weight +0.6 kg, SMM +0.5 kg, body fat +0.1 kg, PBF -0.1 %
  2026-08-05 -> 2026-09-16 (42 d): weight +0.4 kg, SMM +0.4 kg, body fat unknown, PBF unknown

First to last:
  weight    +1.0 kg over 76 d (2026-07-02 -> 2026-09-16), +0.4 kg per 28 d
  SMM       +0.9 kg over 76 d (2026-07-02 -> 2026-09-16), +0.3 kg per 28 d
  body fat  +0.1 kg over 34 d (2026-07-02 -> 2026-08-05), +0.1 kg per 28 d
  PBF       -0.1 % over 34 d (2026-07-02 -> 2026-08-05), -0.1 % per 28 d

Goal (skeletal muscle mass, from training goals):
  milestone 43.0 kg: latest 36.9 kg (2026-09-16), 6.1 kg to go
  long-term 50.0 kg: 13.1 kg to go

Last measurement: 2026-09-16, 19 days before 2026-10-05
```

예상 JSON 출력(합성 값, key 순서 고정, 값은 0.1 단위 decimal 문자열):

```json
{
  "trend_version": 1,
  "from": null,
  "to": null,
  "reference_date": "2026-10-05",
  "measurement_count": 3,
  "measurements": [
    {
      "measured_at": "2026-07-02T08:10:00+09:00",
      "local_date": "2026-07-02",
      "weight_kg": "80.0",
      "skeletal_muscle_mass_kg": "36.0",
      "body_fat_mass_kg": "15.0",
      "body_fat_percent": "18.8"
    }
  ],
  "intervals": [
    {
      "from_date": "2026-07-02",
      "to_date": "2026-08-05",
      "days": 34,
      "changes": {
        "weight_kg": "0.6",
        "skeletal_muscle_mass_kg": "0.5",
        "body_fat_mass_kg": "0.1",
        "body_fat_percent": "-0.1"
      }
    }
  ],
  "overall": {
    "skeletal_muscle_mass_kg": {
      "from_date": "2026-07-02",
      "to_date": "2026-09-16",
      "days": 76,
      "change": "0.9",
      "per_28_days": "0.3"
    }
  },
  "goal": {
    "metric": "skeletal_muscle_mass_kg",
    "latest": "36.9",
    "latest_date": "2026-09-16",
    "milestone": {"target": "43.0", "remaining": "6.1", "reached": false},
    "long_term": {"target": "50.0", "remaining": "13.1", "reached": false}
  },
  "conflicts": [],
  "last_measurement_date": "2026-09-16",
  "days_since_last_measurement": 19
}
```

JSON의 정확한 key 구성은 설계에서 확정한다. 위 예시는 생략(`...` 대신 일부만 표시)을 포함한다.

## 규칙

- 입력: `--from`/`--to`는 `YYYY-MM-DD`, 포함 범위, 측정의 local date 기준. 형식 오류나 `--from > --to`는 DB를 열기 전에
  `오류:` 메시지와 exit 1. 둘 다 없으면 저장된 모든 측정.
- 기준일(`reference_date`): `--to`가 있으면 `--to`, 없으면 이 컴퓨터의 오늘. "마지막 측정 후 경과 일수"는 기준일 기준.
- Read-only: 기존 analytics/nutrition reader처럼 SQLite를 `mode=ro` + `PRAGMA query_only`로 열고, `ensure_directories()`,
  `migrate()`, journal mode 변경을 하지 않는다. DB가 없으면 만들지 않고 `오류:` + exit 1.
  migration 007(InBody table) 이전 DB면 `오류:` + exit 1(무엇이 없는지 말한다).
- 측정 0건: "No InBody measurements stored" 안내, exit 0, JSON은 빈 배열과 `null`.
- 날짜와 순서: local date는 저장된 `measured_at`(offset 포함 문자열)의 날짜 부분. 정렬은 UTC 시각, 같으면 저장 id 순.
- 표시 정밀도: 저장 값(float)을 0.1 단위로 반올림해 표시한다(InBody 표시 단위). float 잡음(예: `41.400001525878906`)을
  그대로 내보내지 않는다. 변화량은 **반올림한 값끼리** 계산해 표시된 수치가 서로 맞게 한다. 반올림 방식은 설계에서
  정하고 문서에 적는다. JSON 값은 decimal 문자열.
- 결측: 지표 값이 없으면 `unknown`(JSON `null`). 0으로 채우지 않는다. 지표마다 따로 계열을 만든다. 체중만 있는 행은
  체중 계열에만 들어간다. 측정 사이 변화는 그 지표가 양쪽 측정에 모두 있을 때만 계산하고, 아니면 `unknown`.
- 같은 날 여러 행(예: 같은 측정이 서로 다른 source identity로 두 번 저장된 경우):
  - 목록에는 저장된 행을 모두 보여 준다. 합치지 않는다(`domain-principles` 2절, migration 007 주석).
  - 추세 계산은 지표별로 날짜당 한 점을 쓴다. 그 날짜의 그 지표 값(0.1 반올림 후)이 모두 같으면 그 값을 쓴다.
    다르면 그 날짜·지표를 **conflict**로 보고하고 그 지표의 추세 계산에서 뺀다(어느 값이 맞는지 고르지 않는다).
  - 측정 사이 구간(`intervals`)은 날짜 단위다(같은 날 행끼리의 구간은 만들지 않는다).
- 처음→마지막 변화: 지표마다 기간 안에서 값이 있는 첫 날짜와 마지막 날짜 사이. 한 점뿐이면 변화 `unknown`.
  28일당 변화(`per_28_days`)는 두 날짜 간격이 28일 이상일 때만 계산하고 아니면 `null`.
- 목표: `TrainingGoals`(`src/muscle50/domain/training_goals.py`) 기본값의 milestone/long-term을 쓴다(설정 파일 없음).
  기간 안 마지막(conflict 아닌) SMM 점을 기준으로 남은 양을 계산한다. 목표 이상이면 `reached: true`, 남은 양 `0.0`이
  아니라 `null`. SMM 점이 없으면 목표 진행은 `unknown`.
- 값 출력: 이 명령은 사용자가 수치를 보려고 직접 실행하므로 값을 출력한다. `inbody sync`의 "기본은 값 숨김,
  `--show-values`로만 표시" 정책은 바뀌지 않는다. 다른 명령(`daily` 등)에 체성분 값을 추가하지 않는다.
- 출력: text는 ASCII, 고정 순서. JSON은 고정 key 순서, `ensure_ascii`, 같은 입력이면 byte-identical.

## 인수 조건

- [ ] AC1: 서로 다른 날짜의 합성 측정 3개가 있으면 `inbody trend`가 측정 목록(시간순), 날짜 사이 변화, 지표별 처음→마지막 변화,
  목표까지 남은 양, 마지막 측정 후 경과 일수를 출력하고 exit 0이다.
- [ ] AC2: 체지방량이 없는 측정은 체지방량을 `unknown`(JSON `null`)으로 표시하고, 그 측정이 낀 구간의 체지방량 변화는
  `unknown`이다. 어떤 값도 0으로 표시되지 않는다.
- [ ] AC3: 같은 날짜에 두 행이 있고 체중 값이 같고(0.1 단위) 한쪽에만 SMM이 있으면, 목록에 두 행이 모두 나오고 추세에는 그 날짜가
  체중 한 점, SMM 한 점으로 들어간다. 체중 값이 다르면 그 날짜·체중이 `conflicts`에 나오고 체중 추세 계산에서 빠진다.
  두 경우 모두 DB 행 수와 내용이 그대로다.
- [ ] AC4: 최근 SMM이 43.0 미만이면 milestone 남은 양을 표시하고, 43.0 이상이면 `reached: true`와 long-term 남은 양을 표시한다.
  SMM 값이 하나도 없으면 목표 진행이 `unknown`이다.
- [ ] AC5: 측정 0건이면 안내 문구와 exit 0, JSON은 빈 배열과 `null`이다.
- [ ] AC6: `--from`/`--to`가 기간을 제한한다. 잘못된 날짜 형식이나 `--from > --to`는 DB를 열기 전에 `오류:`와 exit 1이다.
- [ ] AC7: DB가 없는 임시 `MUSCLE50_HOME`에서 실행하면 `오류:`와 exit 1이고, 디렉터리·DB·`config\`를 만들지 않는다.
  측정이 있는 DB에서 실행 전후 DB/WAL 내용과 `schema_migrations`가 같다.
- [ ] AC8: 같은 입력으로 `--json`을 두 번 실행하면 byte-identical이고, text 출력은 ASCII다. float 잡음이 출력에 없다.
- [ ] AC9: `inbody sync`(`--show-values` 유무 모두), `recommend --json`, `analytics snapshot --json` 출력이 이 기능 전과
  byte-identical이다.
- [ ] AC10: 품질 게이트 4개가 통과한다.

## 한계 / 후속 후보

- InBody 측정이 적으면(현재 production은 같은 날 같은 측정의 두 행뿐) 추세가 거의 비어 있다. 의미 있는 추세는 측정이
  쌓인 뒤에 나온다. Samsung Health export가 과거 측정을 포함하는지는 아직 확인되지 않았다(docs/inbody-access-decision.md).
- 목표는 코드 기본값이다(설정·이력 없음).
- 후속 후보:
  - 측정 사이 리뷰: 체성분 추세 + 그 기간의 근력 진척, 근육별 주당 set, 식단 준수, 회복(`docs/goals.md` 우선순위 4).
  - 조정 권고(kcal/탄수/볼륨), 부위별 근육량, 체수분·기초대사량 등 지표 추가.
