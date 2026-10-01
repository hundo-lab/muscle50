# Exercise Taxonomy v1

Garmin strength set의 **원본 exercise label `(category, name)`을 저장된 그대로 identity로 유지**하고, 각 label에
movement pattern, primary muscle, secondary muscles만 붙이는 순수 domain lookup table이다.
`src/muscle50/domain/exercise_taxonomy.py`. Migration, ingestion/normalization 변경, production 데이터 수정 없음.
Analytics Engine이 snapshot 계산 시점에 매번 적용한다(저장하지 않음).

## 핵심 원칙

- 원본 Garmin category/name을 저장된 값 그대로 보존한다. **이름을 바꾸거나 canonical 이름을 만들거나 서로 다른
  Garmin label을 합치지 않는다.** 예: `CRUNCH/LEG_EXTENSIONS`와 `CRUNCH/WEIGHTED_LEG_EXTENSIONS`, `BENCH_PRESS/-`와
  `BENCH_PRESS/DUMBBELL_BENCH_PRESS`는 taxonomy 속성이 같아도 별개 identity다.
- Exercise 단위 analytics는 원본 Garmin identity 기준이다. Movement pattern / primary muscle 집계만 같은 값을 가진
  label들을 합친다.
- Taxonomy가 붙이는 것: movement pattern, primary muscle(정확히 1개), secondary muscles, mapping basis, 그리고
  set 단위 confirmed/auto-detected provenance.

## 모델

| 타입 | 의미 |
| --- | --- |
| `ExerciseRule` | `source_category`, `source_name`(원본 label, `None` = Garmin이 category만 줌), `movement_pattern`, `primary_muscle`, `secondary_muscles`(primary와 겹치지 않음), `basis`, `note`(override 사유) |
| `ExerciseClassification` | 저장된 `source_category`/`source_name`(변경 없음) + `rule` 또는 `unmapped_reason` |
| `MappingBasis` | `exercise_name`(category + 구체 name), `category_only`(name 없음), `category_override`(Garmin category 의미를 의도적으로 벗어남, `note` 필수) |
| `UnmappedReason` | `unknown_source_label`(Garmin UNKNOWN/missing, `derive_activity_review`와 동일 predicate), `no_rule`(알려진 label이지만 v1 rule 없음) |
| `LabelOrigin` | set의 Garmin probability에서만 계산: `confirmed`(=100), `auto_detected`(<100), `unspecified`(NULL) |

`TAXONOMY_VERSION = 1`. API: `classify_exercise(category, name)`, `classify_strength_set(set)`,
`label_origin(probability)`, `EXERCISE_RULES`.

Movement pattern 15개: `horizontal_push`, `vertical_push`, `horizontal_pull`, `vertical_pull`, `squat`,
`hinge`, `lunge`, `knee_flexion`, `knee_extension`, `elbow_flexion`, `elbow_extension`,
`shoulder_abduction`, `shoulder_horizontal_adduction`, `scapular_elevation`, `core`.

Muscle group 13개: `chest`, `lats`, `upper_back`, `anterior_deltoid`, `lateral_deltoid`, `posterior_deltoid`,
`biceps`(elbow flexor 전체), `triceps`, `forearms`, `quadriceps`, `hamstrings`, `glutes`, `core`.

데이터가 쓰지 않는 값은 만들지 않았다: `calf`, `carry`, `shoulder_rear_delt` pattern과 `calves` muscle group
없음. 테스트가 모든 enum 값이 최소 하나의 rule에서 쓰이는지 검사한다.

## Mapping 규칙

- Rule lookup은 저장된 `(category, name)`과의 **정확한 일치**다. Fuzzy matching, 대소문자/공백 보정, 무게/반복/
  인접 set 기반 추론, LLM 분류 없음.
- **Rule은 production에서 관찰되고 사람이 검토한 label에만 존재한다**(2026-10-01 ACTIVE label 39개 중 38개; 같은 날 coverage update로
  Garmin Connect에서 지정된 7개 추가 → UNKNOWN 제외 46개 중 45개, 남은 `no_rule`은 `PLYO/BOX_JUMP`뿐).
  테스트가 rule 집합 = 검토한 production label 집합을 고정한다.
- **Category fallback 없음**: `BENCH_PRESS/<새 name>`은 `BENCH_PRESS/-` rule로 떨어지지 않고 `no_rule`이 되어
  `strength_unmapped_exercise` quality issue로 드러난다. 새 Garmin label은 rule을 명시적으로 추가해야 한다.
- UNKNOWN 판정은 `derive_activity_review`와 같다: stored key 또는 category가 NULL이거나 strip/upper 후
  `UNKNOWN`. 따라서 taxonomy UNKNOWN 수 = 기존 `unclassified_active_set_count`(테스트로 전 조합 확인).
- Taxonomy는 추천/생리학 가중치와 무관하다. 가중치·fractional set·effective set 없음.

### 검토된 v1 결정

| label | 결정 | 이유 |
| --- | --- | --- |
| `CRUNCH/LEG_EXTENSIONS`, `CRUNCH/WEIGHTED_LEG_EXTENSIONS` (7 + 3 set, 별개 label 유지) | `knee_extension`, primary quadriceps, basis `category_override` | Garmin FIT profile에서 "leg extension"은 `crunch_exercise_name`(33, 34)과 banded exercise에만 있고 machine knee extension 항목이 없다. 10 set 모두 사용자가 Connect에서 지정한 label(probability 100)이고 40–70 kg. Rule은 label에만 의존하며 무게로 판정하지 않는다 |
| `FLYE/DUMBBELL_FLYE`, `FLYE/CABLE_CROSSOVER` (13) | `shoulder_horizontal_adduction`, chest | press가 아니므로 horizontal_push에 넣지 않음 |
| `SHRUG/-` (55) | `scapular_elevation`, primary `upper_back`(trapezius 포함) | 55 set 전부 auto-detected(37–61%). 아래 label origin 참고 |
| `PULL_UP/STRAIGHT_ARM_PULLDOWN`, `PULL_UP/STANDING_CABLE_PULLOVER` (5) | `vertical_pull`, lats, secondary 없음 | 수직면 lat 주도 shoulder extension. 5 set 때문에 pattern을 늘리지 않음 |
| `BENCH_PRESS/CLOSE_GRIP_BARBELL_BENCH_PRESS` | primary triceps | close grip은 triceps target |
| `ROW/-`, `ROW/SEATED_CABLE_ROW` | primary `upper_back`; lats/biceps/posterior_deltoid secondary | horizontal row의 mid-back 주도 |
| `DEADLIFT/BARBELL_DEADLIFT` | primary glutes; hamstrings/quadriceps secondary | `DEADLIFT/STRAIGHT_LEG_DEADLIFT`는 primary hamstrings |
| `SHRUG/UPRIGHT_ROW` | `shoulder_abduction`, lateral_deltoid; upper_back secondary | |
| `PLYO/BOX_JUMP` (1, auto-detected 37.5%) | rule 없음 → `no_rule` | plyometric은 v1 strength taxonomy 밖. explicit unmapped 경로. 2026-10-01 coverage update에서 재검토 후 유지 |
| `SHOULDER_PRESS/SEATED_BARBELL_SHOULDER_PRESS` (8), `SHOULDER_PRESS/DUMBBELL_SHOULDER_PRESS` (6) | `vertical_push`, anterior_deltoid; triceps/lateral_deltoid secondary. 서로, 그리고 `SHOULDER_PRESS/-`와 별개 label | 2026-09-22 `24451010022` Connect 수정 label(probability 100) |
| `LATERAL_RAISE/ONE_ARM_CABLE_LATERAL_RAISE` (3) | `shoulder_abduction`, lateral_deltoid, secondary 없음. `LATERAL_RAISE/-`와 별개 label | `LATERAL_RAISE/-` rule과 같은 속성 |
| `ROW/BENT_OVER_ROW_WITH_BARBELL` (6) | `horizontal_pull`, upper_back; lats/biceps/posterior_deltoid secondary | `ROW/-`·`ROW/SEATED_CABLE_ROW`와 같은 row-family secondary(사용자 결정 2026-10-01) |
| `PULL_UP/CLOSE_GRIP_LAT_PULLDOWN` (5), `PULL_UP/WIDE_GRIP_LAT_PULLDOWN` (4) | `vertical_pull`, lats; biceps/upper_back secondary | `PULL_UP/LAT_PULLDOWN`과 같은 속성, 별개 label |
| `TRICEPS_EXTENSION/LYING_TRICEPS_EXTENSION_TO_CLOSE_GRIP_BENCH_PRESS` (6) | `elbow_extension`, triceps; chest/anterior_deltoid secondary | Garmin FIT `triceps_extension_exercise_name` 14: lying extension에서 close-grip press로 잇는 복합 동작. Garmin category와 `TRICEPS_EXTENSION/BENCH_DIP` 선례를 따라 elbow_extension(추천에서는 isolation)이며 press 부분은 secondary로만 반영. 추천 자격을 바꾸려고 horizontal_push로 재분류하지 않는다(사용자 결정 2026-10-01) |

이 선택들은 primary headline 합계를 움직이므로 바꾸려면 rule table과 테스트를 함께 수정한다.

## Label origin (Garmin label 신뢰도)

Garmin category를 신뢰할 수 있는 muscle label로 가정하지 않는다. Production 감사 결과:

- probability < 100인 960 ACTIVE set은 **모두** FIT 파일의 device 자동 인식 첫 후보와 category가 같다
  (FIT `set` message의 `category` 배열, message index로 join).
- probability = 100인 94 set은 5개 activity에만 있고, 이 activity들은 Connect가 `messageIndex`를 전부 NULL로
  바꿨다. ACTIVE set 수가 FIT와 같은 4개 activity(76 set)를 위치로 맞추면 49 set은 device label과 다르고
  27 set은 같다. 나머지 `24524226596`(18 set)은 Connect에서 set 하나가 삭제돼(FIT ACTIVE 19 vs 저장 18) 위치
  비교를 하지 않았다 → probability 100은 Connect에서 사용자가 편집/확인한 label.
- 자동 인식 label은 눈에 띄게 틀린 경우가 있다(SIT_UP 50 kg, PUSH_UP 25 kg, SHRUG 55 set).

그래서 모든 taxonomy group은 `label_origins`(confirmed / auto_detected / unspecified 개수)를 함께 보고한다.
**개수만 나눠 보여주며 가중치는 없다**(auto-detected set도 1 set).

Unmapped UNKNOWN set도 probability가 98.8–99.6%라 `auto_detected`로 집계된다. 이는 Garmin이 종목을
인식했다는 뜻이 아니라 "UNKNOWN이라는 판정"의 확신도다.

## Analytics Engine 연동

`StrengthSummary.taxonomy`(`StrengthTaxonomySummary`)가 추가됐다. 기존 필드(`exercises` 등)는 변경 없음 —
기존 `ExerciseAggregate`도 이미 원본 Garmin key/category 기준이다. JSON `--json`에 전부 포함되고 text 출력에
절이 추가된다.

`StrengthTaxonomySummary` 필드:

| 필드 | 의미 |
| --- | --- |
| `taxonomy_version` | 1 |
| `active_set_count` | window의 ACTIVE strength set 수 |
| `mapped_active_set_count` / `unmapped_active_set_count` | 합 = `active_set_count` |
| `unknown_active_set_count` / `no_rule_active_set_count` | 합 = `unmapped_active_set_count` |
| `unknown_source_activity_ids` | UNKNOWN set이 있는 activity(정렬) |
| `mapped_label_origins` | 매핑된 set의 confirmed/auto_detected/unspecified 개수 |
| `by_exercise` | `TaxonomyExerciseGroup` — **원본 Garmin label별**(mapped/unmapped 모두). `category`, `exercise_name`(저장값 그대로), `movement_pattern`, `primary_muscle`, `secondary_muscles`, `mapping_basis`, `unmapped_reason`, `active_set_count`, `label_origins`, `source_activity_ids`, `sets`. 합 = `active_set_count` |
| `by_movement_pattern`, `by_primary_muscle` | `TaxonomyGroup`(`key`, `active_set_count`, `label_origins`, `source_activity_ids`, `sets`). 매핑된 set을 **각각 정확히 한 번** 센다. 합 + unmapped = `active_set_count` |
| `secondary_muscle_set_exposures` | `TaxonomyGroup`. muscle별로 그 muscle을 secondary로 가진 ACTIVE set 수 |

- **Primary-muscle active sets가 v1의 muscle-group headline이다.**
- Secondary exposure는 **별도 목록이며 primary 합계에 더하지 않는다.** muscle 간 합산도 의미 없다(한 set이 여러
  secondary를 가짐).
- Unmapped는 조용히 버리지 않는다: `by_exercise`에 `unmapped_reason`과 set provenance가 남고, UNKNOWN 수와 영향
  activity가 summary에 따로 나온다. `no_rule` set은 activity별 `strength_unmapped_exercise` quality issue(set
  sequence 포함)를 낸다. UNKNOWN은 기존 `strength_unclassified_exercise` issue가 그대로 담당한다.
- Provenance: 모든 group에 `source_activity_ids`와 `sets`(`source_activity_id`, `sequence`).
- 결정성: group은 (set 수 내림차순, key 또는 category/name) 정렬, set ref는 activity 정렬 순서 → 입력 순서 무관,
  같은 DB 상태에서 byte-identical JSON(production 재실행으로 확인).

## 범위 밖 (이후 기능)

운동 추천, 선호/빈도 종목 선택, progressive overload, 무게/반복 목표, recovery 기반 조정, UNKNOWN 수정 안내 같은
사용자 알림, 수영 목표/추천, Daily Recommendation, Training Goals/Profile. Taxonomy는 label에 속성을 붙이는 것만
담당한다.

## Coverage update (2026-10-01)

Garmin Connect에서 종목을 지정한 activity(2026-09-22 `24451010022`, 09-29 `24536298902`, 09-30 `24549434906`)의
label 7개가 `no_rule`이었다. 위 표의 rule을 추가했고 label은 저장값 그대로다. 28일 snapshot(as-of 2026-10-01):
ACTIVE 277 중 mapped 205 → 243, unmapped 72 → 34(UNKNOWN 33 그대로, no_rule 39 → 1 = `PLYO/BOX_JUMP`).
Primary anterior_deltoid 1 → 15, lateral_deltoid 3 → 6. Secondary posterior_deltoid 6 → 12. Recommendation 로직은
바꾸지 않았다.

`PLYO/BOX_JUMP` 최종 결정(사용자, 2026-10-01): **의도적으로 rule 없음(`no_rule`)**. Plyometric은 taxonomy v1 범위 밖이며 `squat`으로 매핑하지 않고 새 `jump` pattern도 추가하지 않는다. 현재 근거는 watch가 자동 인식한 1 set(confidence 37.5%)뿐이다: 2026-09-10 `24304351575` 마지막 set, 3 reps, 10 kg, 1.9 s, 직전 rest 1548 s(상체 세션 종료 후). 유일한 non-UNKNOWN ACTIVE `no_rule` label로 계속 드러난다.

## UNKNOWN 분석 (production, read-only, 2026-10-01)

ACTIVE 1054 중 UNKNOWN 276(50 activity). 저장된 DB/RAW로 **결정적으로 해소할 수 있는 set은 0개**다.

- Garmin JSON 후보: 260 set은 후보 3개 모두 UNKNOWN(99.61%, 0, 0), 16 set은 후보 1개 UNKNOWN(98.83%).
  대체 후보 없음.
- FIT 원본(`original.zip`): 260 set은 category `65534`(FIT unknown), 16 set은 `65535`(invalid). 추가 정보 없음.
- velocity/ROM 필드 전부 NULL, `wktStepIndex`(workout step) 전부 NULL, 모든 activity에 classified set도 있음.
- 남는 신호는 인접 set뿐이다(같은 category 사이 50, 다른 category 사이 117, 세션 처음/끝 109; 연속 길이 1이
  105회, 최대 11). 이는 추측이므로 사용하지 않는다.
- 반복 패턴: weight 20 kg(36), 40 kg(33), 0 kg(27), 60 kg(22); reps 0이 55 set.
- 해소 전/후: 276 → 276. Correction/overlay는 추가하지 않았고 production 수정은 이 작업 범위가 아니다.

## Production 결과 (as-of 2026-09-28, 90일 = 전체 데이터)

| 항목 | 값 |
| --- | --- |
| ACTIVE strength set | 1054 |
| 원본 Garmin label identity | 40개(UNKNOWN/-, PLYO/BOX_JUMP 포함), 서로 합쳐지지 않음 |
| movement pattern / primary muscle 매핑 | 777 (73.7%) — confirmed 94, auto-detected 683 |
| unmapped | 277 (26.3%) — `unknown_source_label` 276(50 activity), `no_rule` 1(PLYO/BOX_JUMP) |

Primary muscle active sets: chest 204, triceps 120, lats 114, biceps 87, upper_back 83, quadriceps 81,
anterior_deltoid 32, hamstrings 20, core 16, glutes 12, lateral_deltoid 8.

Secondary set exposures(별도, 합산 금지): triceps 223, anterior_deltoid 212, biceps 137, upper_back 110,
glutes 88, lateral_deltoid 32, lats 28, posterior_deltoid 28, hamstrings 12, forearms 10, quadriceps 9, chest 8.

Top Garmin labels: UNKNOWN/- 276(unmapped), BENCH_PRESS/- 152, PULL_UP/- 90, CURL/- 72, TRICEPS_EXTENSION/- 66,
SHRUG/- 55, SQUAT/- 45, TRICEPS_EXTENSION/TRICEPS_PRESSDOWN 35, SHOULDER_PRESS/- 32, ROW/- 27, PUSH_UP/- 26.

## 알려진 한계

- 777 매핑 set 중 683은 watch 자동 인식 label이다. Taxonomy는 label을 정확히 옮길 뿐 label이 맞는지는 판단하지
  않는다. Muscle 분포를 해석할 때 `label_origins`를 같이 봐야 한다.
- `category_only` label(BENCH_PRESS/- 등)은 Garmin이 변형을 주지 않았으므로 barbell/dumbbell 구분이 없다.
- Primary muscle은 set당 하나라 compound 운동의 분담이 단순화된다(의도적; fractional set은 v1 범위 밖).
- 새 Garmin label은 rule이 추가될 때까지 `no_rule`로 보고된다.
