# Garmin swimming details 설계

## 확인된 RAW 경계

현재 connector는 activity 한 건에 대해 `activity`, `details`, `splits`, original archive를
보존한다. 수영 계층의 입력은 다음처럼 구분한다.

- `activity`: pool length와 activity-level 합계의 원천이다.
- `splits`: `lapDTOs`가 interval/lap이고, 각 lap의 `lengthDTOs`가 pool length 순서다.
  배열 위치로 정규화 sequence를 만들되 Garmin의 `lapIndex`와 `messageIndex`는 별도 보존한다.
- `details`: `metricDescriptors[].metricsIndex`가 `activityDetailMetrics[].metrics`의 열을
  설명하는 위치 기반 시계열이다. descriptor 순서가 고정이라고 가정할 수 없고 length ID도
  없으므로, 이번 단계에서는 length/lap HR 계산이나 interval 연결에 사용하지 않는다.
- `original.zip`: FIT 원본을 포함할 수 있으며 REST에 없는 length/event 필드의 장기적인
  재처리 원천이다. 이번 단계에서는 archive를 풀거나 FIT parser를 추가하지 않는다.

정규화에 사용하는 필드는 다음과 같다. API 세대나 device에 따른 이름 차이는 제한된 alias로
받고, 명시적으로 매핑하지 않은 필드도 `garmin_source_json`에서 손실 없이 남긴다.

| 의미 | lap source | length source | normalized field |
|---|---|---|---|
| 순서/식별자 | 배열 위치, `lapIndex`, `messageIndex` | 배열 위치, `messageIndex` | `sequence`, `source_*_index` |
| 거리 | `distance` | `distance` | `distance.garmin_meters` |
| 시간 | `duration`, `movingDuration`, `elapsedDuration`, `restDuration` | 같은 필드 | 각 `*_seconds` |
| 영법 | `swimStroke` 또는 `strokeType` | 같은 필드 | `stroke_type` |
| 길이 종류 | - | `lengthType` | `length_type` |
| 횟수 | `numberOfActiveLengths`, `numberOfLengths` | - | `active_length_count`, `total_length_count` |
| 스트로크 | `strokeCount`, `strokes`, `totalStrokes`, `totalNumberOfStrokes` | 같은 필드 | `stroke_count` |
| SWOLF | `avgSwolf`, `averageSwolf`, `averageSWOLF`, `swolf` | 같은 필드 | `swolf` |
| 속도/HR | `averageSpeed`, `averageHR`, `maxHR` | 같은 필드 | `average_speed_mps`, `*_hr_bpm` |

Garmin은 length를 pool의 한쪽 끝에서 다른 쪽 끝까지로, interval을 휴식 사이의 연속된
length로 정의한다. idle/active length와 stroke 관련 필드는 Garmin FIT의 length message에도
정의되어 있다.

참고:

- [python-garminconnect activity endpoints](https://github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/__init__.py)
- [Garmin swim terminology](https://www8.garmin.com/manuals-apac/webhelp/forerunner55/EN-SG/GUID-99BB5782-0C5F-40BF-85D5-0D186211218E-4544.html)
- [Garmin FIT activity encoding example](https://github.com/garmin/fit-java-sdk/blob/main/src/main/java/com/garmin/fit/examples/EncodeActivity.java)

## 정규화 정책

`normalize_garmin_swim()`은 RAW 값을 단위 정규화하고 계층화할 뿐 누락값을 만들지 않는다.

- 응답 배열 순서에서 0-based `sequence`를 만들고 source index/message index를 별도 보존한다.
- source distance와 corrected distance를 `SwimDistance`의 서로 다른 필드로 둔다. normalizer는
  corrected distance를 항상 `NULL`로 둔다.
- 25m/50m는 그대로 meter로 저장하고 yard는 정확한 환산 상수 `0.9144`만 적용한다. 단위를
  모르면 source 값과 단위는 보존하지만 meter 값은 `NULL`이다.
- stroke/mixed/drill/idle 값은 lower-case key로 정규화하되 알 수 없는 값도 버리지 않는다.
- pace와 휴식 시간의 산술 계산은 `DerivedSwimMetrics`에서만 수행한다. SWOLF는 계산하지 않고
  Garmin이 제공한 값만 정규화한다.
- 각 객체의 `GarminSource`는 source path와 전체 source JSON을 보존한다. canonical RAW 파일이
  최종 원본이며 이 snapshot은 필드 provenance 및 향후 재정규화를 돕는다.

## 향후 DB schema 제안

공용 migration 충돌을 피하기 위해 이번 branch에는 아래 DDL을 추가하지 않는다. strength
branch merge 후 새 migration 번호를 정해 반영한다.

```sql
CREATE TABLE swim_laps (
    id INTEGER PRIMARY KEY,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    source_lap_index INTEGER,
    source_message_index INTEGER,
    start_time_utc TEXT,
    intensity_type TEXT,
    stroke_type TEXT,
    garmin_distance_meters REAL,
    corrected_distance_meters REAL,
    duration_seconds REAL,
    moving_seconds REAL,
    elapsed_seconds REAL,
    garmin_rest_duration_seconds REAL,
    average_speed_mps REAL,
    active_length_count INTEGER,
    total_length_count INTEGER,
    stroke_count INTEGER,
    swolf REAL,
    average_hr_bpm REAL,
    max_hr_bpm REAL,
    garmin_source_path TEXT NOT NULL,
    garmin_source_json TEXT NOT NULL,
    UNIQUE (activity_id, sequence)
);

CREATE TABLE swim_lengths (
    id INTEGER PRIMARY KEY,
    swim_lap_id INTEGER NOT NULL REFERENCES swim_laps(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    sequence_in_lap INTEGER NOT NULL CHECK (sequence_in_lap >= 0),
    source_message_index INTEGER,
    start_time_utc TEXT,
    length_type TEXT,
    stroke_type TEXT,
    garmin_distance_meters REAL,
    corrected_distance_meters REAL,
    duration_seconds REAL,
    moving_seconds REAL,
    elapsed_seconds REAL,
    garmin_rest_duration_seconds REAL,
    average_speed_mps REAL,
    stroke_count INTEGER,
    swolf REAL,
    average_hr_bpm REAL,
    max_hr_bpm REAL,
    garmin_source_path TEXT NOT NULL,
    garmin_source_json TEXT NOT NULL,
    UNIQUE (swim_lap_id, sequence_in_lap)
);
```

`corrected_distance_meters`는 Garmin 값을 덮어쓰지 않는 overlay다. 실제 migration에서는 기존
`activity_corrections`처럼 revision/reason/time을 가진 append-only child correction table로
분리하는 방안도 함께 결정해야 한다. 화면과 집계가 사용할 effective distance는
`COALESCE(corrected_distance_meters, garmin_distance_meters)`로 파생한다.

pace는 correction이 있으면 corrected distance와 duration으로 다시 계산한다. correction이
없을 때는 `average_speed_mps`의 역수, 그 값도 없으면 Garmin distance와 duration이 모두
있을 때만 `duration * 100 / distance`로 파생한다. rest는 Garmin의 명시적
`restDuration`, idle length 시간, 마지막으로 `elapsedDuration - duration` 순으로 계산하며
음수이거나 입력이 빠진 경우 `NULL`이다. interval/set reconstruction과 missed-length correction은
이 normalized 계층 위의 별도 correction/derived 단계로 둔다.
