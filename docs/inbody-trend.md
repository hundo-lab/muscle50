# InBody Body Composition Trend v1

Spec: `docs/specs/inbody-trend.md`. Migration 없음(`007_inbody.sql`의 기존 column만 읽는다). Output change: additive(새 명령).

## 목적과 non-goal

- `inbody sync`로 저장된 InBody 측정을 시간순으로 보여 주고, 측정 사이의 체중·골격근량(SMM)·체지방량·체지방률 변화와
  SMM 목표(1차 43 kg, 장기 50 kg)까지 남은 양, 마지막 측정 후 경과 일수를 한 명령으로 보여 준다.
- 사용자가 수치를 보려고 직접 실행하는 명령이므로 값을 출력한다. `inbody sync`의 "기본은 값 숨김, `--show-values`로만 표시"
  정책은 그대로다. 다른 명령(`daily`, `recommend`, `nutrition` 등)에는 체성분 값을 추가하지 않는다.
- Non-goal:
  - 저장 데이터 변경 없음. 같은 측정으로 보이는 행의 자동 병합 없음.
  - 판단·권고 문구 없음(좋다/나쁘다, 칼로리 조정 등). 목표 도달 시점 예측 없음.
  - 체중 수동 입력, 부위별(segmental), 기초대사량, 체수분, InBody 점수 등 나머지 지표 없음.

## 명령

```powershell
muscle50 inbody trend
muscle50 inbody trend --from 2026-07-01 --to 2026-10-05
muscle50 inbody trend --json
```

- `--from`/`--to`: `YYYY-MM-DD`, 포함 범위, 측정의 local date 기준. 둘 다 선택이다. 없으면 저장된 모든 측정.
- 기준일(`reference_date`): `--to`가 있으면 `--to`, 없으면 이 컴퓨터의 오늘. "Last measurement ... N days before"는 기준일 기준이다.
- Read-only: SQLite를 `mode=ro` + `PRAGMA query_only`로 한 read transaction 안에서 연다. `ensure_directories()`, `migrate()`,
  journal mode 변경이 없고, DB가 없으면 아무것도 만들지 않는다.

### Text 예시(합성 값)

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

Text 변형:

- `--from`이나 `--to`가 있으면 첫 줄 다음에 `Range: local dates between X and Y (inclusive)`(또는 `on or after X`,
  `on or before Y`) 줄이 들어간다. 반올림 안내 줄은 그대로 남는다.
- 날짜가 하나면 머리글 범위가 `(2026-09-16)`, 행이 하나면 `1 measurement on 1 date`.
- 같은 날짜 conflict가 있으면 Measurements 다음에 섹션이 생긴다:
  `Same-date conflicts (left out of the trend):` / `  2026-09-16 weight: 81.0 kg, 81.4 kg`.
- 날짜가 2개 미만이면 `Between measurements:` 아래가 `  none (fewer than 2 measurement dates)`.
- First to last: 28일 미만이면 `..., per 28 d not computed (under 28 d)`, 값이 있는 날짜가 하나면
  `unknown (one date with a value: D)`, 하나도 없으면 `unknown (no usable values)`.
- Goal: 목표 이상이면 `reached`(예: `milestone 43.0 kg: latest 44.0 kg (2026-09-16), reached`,
  `long-term 50.0 kg: 6.0 kg to go`). SMM 값이 없으면 `milestone 43.0 kg: unknown (no skeletal muscle mass value)`,
  `long-term 50.0 kg: unknown`.
- `1 day before`, `0 days before`. `--to` 없이 오늘 이후 날짜의 행이 있으면 `N days after`.
- 측정 0건: `No InBody measurements stored.` 한 줄(범위가 있으면 `No InBody measurements stored in local dates ...`), exit 0.

### JSON(`--json`)

`json.dumps(indent=2, ensure_ascii=True)`, key 순서 고정, 값은 0.1 단위 decimal 문자열, 없는 값은 `null`.

| key | 내용 |
|---|---|
| `trend_version` | `1` |
| `from`, `to` | flag 값 또는 `null` |
| `reference_date` | 기준일 |
| `measurement_count` | 목록의 행 수 |
| `measurements[]` | `measured_at`(저장 문자열 그대로), `local_date`, `weight_kg`, `skeletal_muscle_mass_kg`, `body_fat_mass_kg`, `body_fat_percent`. 행 id, source, profile key는 넣지 않는다. |
| `intervals[]` | `from_date`, `to_date`, `days`, `changes{4 metrics}` |
| `overall` | 항상 4개 metric, 각각 `from_date`, `to_date`, `days`, `change`, `per_28_days`. 점 0개면 모두 `null`, 1개면 `from_date` = `to_date`, `days` 0, `change`/`per_28_days` `null`. |
| `goal` | `metric`(`skeletal_muscle_mass_kg`), `latest`, `latest_date`, `milestone{target, remaining, reached}`, `long_term{...}` |
| `conflicts[]` | `local_date`, `metric`, `values`(그 날짜에 그 metric이 있는 행들의 반올림 값, 목록 순서) |
| `last_measurement_date`, `days_since_last_measurement` | 0건이면 `null` |

측정 0건: `measurements`/`intervals`/`conflicts`는 `[]`, `overall`의 모든 값과 goal의 `latest`/`latest_date`/`remaining`/`reached`는
`null`(target `"43.0"`/`"50.0"`은 남는다).

## 규칙

### 날짜와 시각: 측정한 곳의 현지 시각

- 각 측정은 **측정한 곳의 현지 날짜와 시각**으로 표시한다. 저장된 `measured_at` 문자열에 적힌 날짜와 `HH:MM`을 그대로 쓴다.
  한국에서 잰 측정은 KST로, 해외에서 잰 측정은 그곳 시각으로 보인다.
- 이 컴퓨터의 현재 시간대로 바꾸지 않는다. 그래서 같은 DB는 어느 컴퓨터, 어느 시간대에서 실행해도 같은 출력이 나온다.
- Samsung Health가 offset을 주지 않아 offset 없이 저장된 측정(naive)도 적힌 시각 그대로 표시한다. 시간대를 추측하지 않는다.
- `--from`/`--to` 범위와 측정 사이 구간도 이 local date 기준이다. 예: `2026-07-02T23:30:00-05:00`은 UTC로는 07-03이지만
  07-02 측정이다.
- 정렬: (local date, 저장된 시각, UTC 시각 또는 offset이 없으면 `""`, 저장 id). UTC 시각은 같은 날짜·같은 시각의 행
  사이에서 순서를 정하는 데만 쓰고 출력하지 않는다. 한 시간대에서 잰 측정들은 UTC 순서와 같다. 같은 local date에
  다른 offset의 행이 섞인 경우(여행)에만 UTC 순서와 다를 수 있다. 그 대신 목록, 머리글 범위, 구간이 항상 서로 맞는다.

### 반올림과 변화량

- 저장 값(float)을 0.1 단위로 반올림한다: `Decimal(repr(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)`.
  float 잡음(예: `41.400001525878906`)은 `41.4`로 나온다.
- HALF_EVEN을 쓰는 이유: InBody canonical fingerprint(`inbody_normalization._canonical_number`)가 같은 0.1 규칙이다.
  fingerprint가 같다고 보는 두 행은 여기서도 같은 값이다. HALF_UP과는 정확한 `.x5` 값에서만 다르다(예: 36.05는 36.0).
- 변화량은 **반올림한 값끼리** 뺀다. 표시된 수치끼리 항상 맞는다(예: 80.04 -> 80.09는 80.0 -> 80.1, 변화 +0.1).
- `per_28_days` = 변화량 x 28 / 일수(HALF_EVEN, 0.1). 두 날짜 간격이 28일 이상일 때만 계산한다.
- 부호: text는 `+0.6`, `-0.1`, 0은 부호 없는 `0.0`. JSON은 `"0.6"`, `"-0.1"`, `"0.0"`(`+` 없음). `-0.0`은 `0.0`이 된다.

### 결측과 같은 날짜의 여러 행

- 값이 없으면 text `unknown`, JSON `null`이다. 0으로 채우지 않는다. 지표마다 따로 계열을 만든다(체중만 있는 행은 체중
  계열에만 들어간다). 측정 사이 변화는 그 지표가 양쪽 날짜에 모두 있을 때만 계산한다.
- 같은 날 여러 행(예: 같은 측정이 서로 다른 source identity로 두 번 저장됨): 목록에는 모두 보여 준다. 합치지 않는다.
- 추세는 지표별로 날짜당 한 점이다. 그 날짜의 그 지표 값(반올림 후)이 모두 같으면 그 값을 쓰고, 다르면 그 날짜·지표를
  conflict로 보고하고 그 지표의 추세에서 뺀다(어느 값이 맞는지 고르지 않는다). conflict 구간의 변화는 `unknown`/`null`이다.
- 구간(`intervals`)은 서로 다른 날짜 사이다. 같은 날 행끼리는 구간을 만들지 않는다.

### 목표

- `TrainingGoals`(`src/muscle50/domain/training_goals.py`) 기본값 `skeletal_muscle_mass_milestone_kg`(43.0),
  `skeletal_muscle_mass_long_term_kg`(50.0)를 쓴다. 설정 파일은 없다.
- 기준은 범위 안 마지막 **conflict 아닌** SMM 점이다. 마지막 날짜가 conflict면 그 전 날짜로 내려가고 `latest_date`가 그 날짜를 보여 준다.
- 목표 이상이면 `reached: true`, `remaining: null`(0.0이 아님). 미만이면 `reached: false`, `remaining` = 목표 - 최근 값.
  SMM 점이 없으면 `reached`와 `remaining`이 `null`이다(false가 아니라 unknown). milestone과 long-term은 따로 계산한다.

### 오류와 exit code

| 경우 | stderr | exit |
|---|---|---|
| 날짜 형식 오류 | `오류: --from/--to는 YYYY-MM-DD 형식이어야 합니다.` | 1 |
| `--from` > `--to` | `오류: --from은 --to보다 이후일 수 없습니다.` | 1 |
| DB 없음 | `오류: muscle50 database not found: <path>` | 1 |
| read-only로 열 수 없음 | `오류: cannot open muscle50 database read-only: <sqlite error>` | 1 |
| migration 007 이전 DB(빈 파일 포함) | `오류: muscle50 database has no InBody measurement table (body_composition_measurements, added by migration 7); run any muscle50 command that writes, for example "muscle50 nutrition food list", once to migrate it` | 1 |
| 읽기 실패(SQLite 파일이 아님 등) | `오류: cannot read InBody measurements: <sqlite error>` | 1 |
| 읽을 수 없는 저장 시각/비유한 값 | `오류: stored InBody measurement <id> has an unreadable measured_at: ...` 등 | 1 |
| Ctrl+C | `취소되었습니다.` | 130 |

날짜 오류는 DB와 home 디렉터리를 건드리기 전에 거부한다. 측정 0건은 오류가 아니다(exit 0). InBody table은 migration
번호가 아니라 table 이름으로 확인한다(006/007 번호 충돌 때 InBody DDL이 version marker 없이 실행된 적이 있다).

## Known issues / limitations

- **측정이 적으면 추세가 거의 비어 있다.** 현재 production에는 같은 날 같은 측정의 두 행뿐이라 출력이 대부분
  "fewer than 2 measurement dates"다. 두 행의 체중이 0.1 단위로 다르면 weight conflict가 보이는데, 이는 정상 동작이다.
- **여행 중 같은 날짜의 다른 offset 측정**은 UTC 순서가 아니라 저장된 현지 시각 순서로 나온다(위 정렬 규칙).
- **목표는 코드 기본값**이다. 설정이나 이력이 없고, 목표를 바꾸면 과거 출력도 새 목표로 계산된다.
- **오류 언어**: `inbody trend`는 다른 read-only 명령처럼 `오류:`로 시작하고, `inbody sync`는 계속 영어(`InBody sync failed:`)다.
- **WAL sidecar**: WAL 모드 DB를 read-only로 열면 SQLite가 빈 `-wal`/`-shm` 파일을 남길 수 있다(analytics reader와 같다).
  DB 내용, mtime, WAL 내용은 바뀌지 않는다.
- 반올림은 HALF_EVEN이라 정확한 `.x5` 저장 값(예: 36.05)은 짝수 쪽(36.0)으로 간다. InBody 앱 표시와 0.1 차이가 날 수 있다.
- 후속 후보: 측정 사이 리뷰(근력 진척, 근육별 주당 set, 식단 준수, 회복과 함께), 조정 권고, 부위별 근육량 등 지표 추가,
  JSON measurement에 `source_type` 추가(행 id, Samsung UID, profile key는 넣지 않는다).
