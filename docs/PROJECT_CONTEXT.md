# muscle50 프로젝트 현황 보고서 (PROJECT_CONTEXT)

- 작성일: 2026-10-05
- 기준 커밋: `main` = `eb67806` (working tree clean)
- 작성 방식: 읽기 전용 분석. 파일 탐색, `git log`/`git branch`, `grep`/`cat`만 사용했고 테스트·lint·앱은 실행하지 않았다.
- 출처 표기 규칙
  - **[코드]**: 이번 분석에서 소스·설정·git을 직접 확인한 사실
  - **[문서]**: `docs/CURRENT_STATE.md`, `docs/HANDOFF.md` 등 저장소 문서에 적힌 기록. 이번에 재실행해 검증하지는 않았다.
  - **(추정)**: 분석자의 추론
- 개인 데이터 값(건강 수치, 계정 정보, Garmin activity ID 등)은 의도적으로 적지 않았다.
- **스냅샷 주의:** `eb67806` 시점의 분석이다. 이후 추가된 Claude Code 오케스트레이션(`CLAUDE.md`, `.claude/`, `docs/specs/`)과 CURRENT_STATE/HANDOFF 동결은 11·14·15절에 반영돼 있지 않다. 현재 규칙은 `CLAUDE.md`를 따른다.

---

## 1. 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 정체 | Windows 로컬에서 동작하는 **개인용 fitness 데이터 CLI 도구** (Python 패키지 `muscle50`, 명령어 `muscle50`) [코드] |
| 하는 일 | Garmin Connect의 운동(activity)과 회복(recovery/daily-health) 데이터, Samsung Health 경유 InBody 체성분, 사용자가 직접 입력한 식사·영양 데이터를 로컬에 보존한다. 처리 흐름은 **RAW → NORMALIZED(SQLite) → DERIVED(분석/추천) → REPORT(터미널/JSON)**이다. [문서·코드] |
| 핵심 산출물 | rolling training snapshot(분석), 결정적 규칙 기반 근력/수영 운동 추천(`recommend`), 하루 일괄 실행(`daily`), 식사 기록, 영양 목표 대비 status [코드] |
| 대상 사용자 | 저장소 소유자 **1인**. 다중 사용자, 계정, 공유 기능은 없다. [코드] |
| 설계 철학 | local-first, append-only/immutable RAW, source 값과 보정/파생 값의 분리, LLM/ML 미사용(결정적 규칙), 값이 없으면 0이 아니라 `unknown`/`unavailable`로 표기 [문서·코드] |

**지원 플랫폼**

| 플랫폼 | 상태 |
|---|---|
| Windows 11 (CLI) | **유일한 production 대상**. Python ≥ 3.12. [코드/README] |
| Android | `android/inbody-diagnostic-companion/` Kotlin 앱이 있다. **진단 및 export 전용** companion이다. Samsung Health의 Body Composition을 읽어 JSON 파일로 내보내면 사용자가 그 파일을 PC로 옮긴다. production sync, 네트워크, 서버 기능은 없다. [코드/README] |
| Web | 없음 |
| iOS | 없음 |

---

## 2. 기술 스택

### Python 본체 [코드: `pyproject.toml`, `uv.lock`]

| 구분 | 내용 |
|---|---|
| 언어 | Python ≥ 3.12. `from __future__ import annotations`, `StrEnum`, `X \| None`, `datetime.UTC`를 사용한다. |
| 빌드 | hatchling ≥ 1.27, wheel 패키지 `src/muscle50`, PEP 561 `py.typed` |
| 패키지 관리 | `uv`(`uv.lock` 존재). README에는 `python -m venv` + `pip install -e ".[dev]"` 절차도 있다. |
| 런타임 의존성 | **`garminconnect==0.3.15`** 하나뿐이다. lock에 따르면 transitive로 `curl-cffi 0.16.3`, `requests 2.34.2`, `ua-generator 2.1.4` 등이 들어온다. |
| 개발 의존성 (`[dev]`) | `pytest 8.4.2`(<9), `pytest-cov 6.3.0`, `ruff 0.16.7`(<1), `mypy 1.20.2`(<2). 괄호 안은 범위 제약, 버전은 lock 기준. |
| CLI 프레임워크 | 표준 라이브러리 `argparse` |
| DB | **SQLite**(표준 `sqlite3`). 단일 파일 `%LOCALAPPDATA%\muscle50\db\muscle50.sqlite3`. 자체 numbered SQL migration loader(001~010)를 쓴다. ORM은 없다. |
| 숫자 정밀도 | 영양 값은 `Decimal`을 쓰고 DB에는 canonical text로 저장한다. |
| 백엔드/인증/스토리지/호스팅 | **서버 없음**. 인증은 Garmin 계정 로그인(비공식 라이브러리, token을 로컬 디렉터리에 저장)뿐이다. 스토리지는 로컬 파일시스템과 SQLite다. 호스팅, 클라우드, 배포 파이프라인은 없다. |
| 배포 방식 | 배포 개념이 없다. 사용자 PC에서 editable install 후 `muscle50 ...`나 `uv run muscle50 ...`로 실행한다. 별도 release/tag는 없다. [코드: `git tag` 결과 없음] |

### Android companion [코드: `android/inbody-diagnostic-companion/*.gradle.kts`]

| 구분 | 내용 |
|---|---|
| 언어/빌드 | Kotlin, Android Gradle Plugin 8.6.0, Kotlin 2.0.20, Gradle wrapper |
| SDK | compileSdk/targetSdk 34, minSdk 29, versionName `0.1.0-diagnostic` |
| 라이브러리 | androidx core-ktx 1.13.1, activity-ktx 1.9.2, appcompat 1.7.0, lifecycle-runtime-ktx 2.8.6, material 1.12.0, kotlinx-coroutines-android 1.8.1, gson 2.10.1 |
| 외부 SDK | Samsung Health Data SDK 1.1.0 `.aar`. Maven에 없으므로 `app/libs/`에 수동 배치하고, git에는 포함하지 않는다. |
| 빌드 | Android Studio, 또는 `.\gradlew.bat :app:assembleDebug`(JBR 필요). 사용자가 수동 빌드에 성공했다는 기록이 있다. [문서] |

---

## 3. 폴더 구조

```text
muscle50/
├─ AGENTS.md                 # 에이전트 작업 규칙 (CLAUDE.md 역할)
├─ README.md                 # 사용자용 설치/명령 안내 (한국어)
├─ pyproject.toml / uv.lock  # 패키지, 의존성, ruff/mypy/pytest 설정
├─ .gitignore / .gitattributes   # 개인 데이터 제외, LF 강제(* text=auto eol=lf)
├─ src/muscle50/
│  ├─ cli.py                 # argparse 명령 트리 + 각 명령의 조립(composition root), 1,099줄
│  ├─ config.py              # AppPaths: 데이터 루트(MUSCLE50_HOME / LOCALAPPDATA) 결정, git worktree 내부 경로 거부
│  ├─ domain/                # 순수 규칙: 정규화, 분석, taxonomy, 추천, 영양 계산 (I/O 없음)
│  ├─ application/           # use case 클래스(execute) + Protocol 포트
│  ├─ infrastructure/
│  │  ├─ garmin/             # garminconnect 래퍼(PythonGarminConnector)
│  │  ├─ inbody/             # Samsung Health export reader, InBody RAW store, 네트워크 connector 경계(테스트 전용)
│  │  ├─ sqlite/             # repository들, read-only reader들, migrations/*.sql
│  │  ├─ raw_store.py        # Garmin activity/recovery RAW 파일 저장(content-addressed)
│  │  ├─ nutrition_target_store.py  # 영양 목표 JSON 저장소
│  │  └─ nutrition_serialization.py / decimal_text.py
│  ├─ presentation/          # terminal.py(운동), nutrition_terminal.py(영양): text/JSON 렌더러
│  └─ schemas/               # nutrition_meal_v1.schema.json (meal interchange JSON Schema)
├─ tests/                    # pytest 47개 파일 + fixtures/(합성 데이터만) + analytics_builders.py
├─ docs/                     # 상태/인계 문서 + 기능별 설계/규칙 문서(17개)
└─ android/inbody-diagnostic-companion/   # Kotlin 진단 앱(독립 프로젝트, Python과 코드 공유 없음)
```

| 폴더 | 역할 | 규모 [코드] |
|---|---|---|
| `src/muscle50/domain/` | 결정적 도메인 규칙과 값 객체 | 22 파일(`__init__` 포함). 가장 큰 파일은 `strength_recommendation.py` 1,554줄, `analytics.py` 1,145줄 |
| `src/muscle50/application/` | use case 조합, 포트(Protocol) 정의 | 19 파일(`__init__` 포함) |
| `src/muscle50/infrastructure/` | Garmin/Samsung/파일/SQLite 어댑터 | `sqlite/database.py` 1,107줄, `nutrition_repository.py` 619줄 |
| `src/muscle50/presentation/` | 출력 포맷(ASCII text, byte-stable JSON) | `terminal.py` 901줄, `nutrition_terminal.py` 622줄 |
| `tests/` | 단위, 통합(임시 SQLite), CLI 테스트 | 47 test 파일 |
| 합계 | src + tests Python | 약 32,500줄 |

런타임 데이터는 저장소 밖에 둔다 [코드: `config.py`, README].

```text
%LOCALAPPDATA%\muscle50\        (또는 MUSCLE50_HOME)
├─ auth\garmin\                  # Garmin token
├─ raw\garmin\activities\<id>\   # 최초 RAW + snapshots\<sha256>\ (refresh)
├─ raw\garmin\recovery\          # 날짜별 content-addressed capture
├─ raw\inbody\samsung_health\    # InBody RAW
├─ imports\inbody\samsung-health\latest.json   # Android export 투입 위치 (README 권장)
├─ db\muscle50.sqlite3
├─ config\nutrition_targets.json # 첫 `target set` 때만 생성
├─ config\telegram.json          # bot token + 허용 chat id. 사용자가 직접 만듦
├─ config\telegram_state.json    # 처리한 update id. `telegram run`이 첫 허용 메시지 때 생성
└─ tmp\
```

---

## 4. 구현된 기능 목록

완성도 기준은 다음과 같다. **완료**는 CLI로 노출되고 테스트가 있으며 문서상 production 검증 기록이 있는 것이다. **부분**은 동작하지만 문서에 명시된 미구현 범위나 수동 단계가 있는 것이다. **스텁**은 경계나 포트만 있고 실제 연동이 없거나 테스트에서만 쓰이는 것이다.

### 4-1. Garmin 데이터 수집

| 기능 | 관련 파일 / 명령 | 완성도 | 비고 |
|---|---|---|---|
| 최신 activity 1건 sync | `garmin latest` / `application/sync_latest_garmin.py`, `ingest_activity.py` | 완료 | activity ID unique 기준 idempotent |
| 기간 activity sync | `garmin activities --from --to` / `ingest_activity_range.py` | 완료 | 페이지네이션 상한 50페이지(1,000건). 건별 실패를 격리한다. |
| Strength set 정규화 | `domain/normalization.py`, migration 002 | 완료 | 기존 RAW에서 local backfill한다. UNKNOWN 분류는 추측하지 않는다. |
| Pool swim lap/length 정규화 | `domain/swim_normalization.py`, migration 004 | 완료 | Garmin 거리와 보정 거리를 분리한다. |
| Activity refresh | `garmin refresh <id>` / `refresh_garmin_activity.py`, migration 006 | 완료 | snapshot history를 남기고 transaction으로 교체한다. 같은 내용이어도 새 capture가 쌓인다(Known issue). |
| Strength review 경고 | `domain/activity_review.py` | 부분 | UNKNOWN/missing 분류만 본다. weight 0 규칙은 보류했다. [문서] |
| Recovery sync (단일/범위) | `garmin recovery D` / `--from --to [--yes]` / `sync_garmin_recovery.py`, migration 005 | 완료 | 날짜당 endpoint 9개, 최대 31일, 7일 초과는 `--yes` 필요 |
| Recovery 재정규화 | `garmin recovery-renormalize [--dry-run]` | 완료 | Garmin 호출 없이 accepted RAW로 재생성한다. |
| Load metric backfill | `garmin backfill-load-metrics [--dry-run]` / `domain/activity_load.py` | 부분 | 10종 metric. `latest`/`activities`/`daily`가 import 뒤 자동으로 채운다(Auto Load Metrics v1). `garmin refresh` 뒤에는 다시 계산하지 않는다. [문서] |
| Sync coverage | `garmin coverage --from --to [--json]`, `garmin backfill-recovery-coverage [--dry-run]` / `application/sync_coverage.py`, migration 010 | 부분 | `garmin activities`/`recovery`/`daily`가 날짜별 최신 결과(synced/partial/failed)를 기록하고 `recommend`/`daily` data freshness에 표시한다. 추천 결정에는 쓰지 않는다(v2). `latest`/`refresh`는 기록하지 않는다. production 적용과 live 검증 전이다. [문서] |
| Sync 이력 기록 | `sync_runs` 테이블 | 스텁 | 스키마만 있고 **어떤 코드도 쓰지 않는다**(날짜별 coverage는 `sync_coverage`가 맡는다). [코드 grep] |
| Activity 보정 overlay | `activity_corrections` 테이블 | 스텁 | 스키마만 있고 **코드 사용 없음**. [코드 grep] |

### 4-2. 분석 / 추천 / 오케스트레이션

| 기능 | 관련 파일 / 명령 | 완성도 | 비고 |
|---|---|---|---|
| Analytics snapshot | `analytics snapshot --date [--days 1..90] [--json]` / `domain/analytics.py`, `sqlite/analytics_reader.py` | 완료 | read-only(`mode=ro`), migration 없음. trend/기간 비교는 없다. [문서] |
| Exercise taxonomy | `domain/exercise_taxonomy.py` | 부분 | 명시적 rule table(45 label, movement 15 / muscle 13) [문서]. posterior deltoid 등에 미커버 label이 있다. |
| Training recommendation | `recommend --date [--focus] [--avoid ...] [--json]` / `domain/training_recommendation.py`, `strength_recommendation.py`, `swim_recommendation.py`, `recovery_assessment.py`, `training_goals.py` | 완료 | 결정적 규칙. Hardening v1과 Progression Hardening v1을 거쳤다. `TrainingGoals`는 코드 기본값이다. |
| Daily orchestration | `daily [--date] [--focus] [--avoid] [--json]`, `daily --after-workout` / `application/daily_sync.py` | 완료 | 실제 계정 live 검증 기록 있음 [문서]. scheduler는 없다(수동 실행). |
| 영양 → 추천 통합 | `application/nutrition_recommendation.py`, `domain/nutrition_guidance.py` | 완료 | 영양은 운동 계획을 바꾸지 않고 안내만 추가한다. |

### 4-3. Nutrition

| 기능 | 관련 파일 / 명령 | 완성도 | 비고 |
|---|---|---|---|
| Nutrition Core (domain, port, JSON schema) | `domain/nutrition.py`, `application/nutrition.py`, `schemas/nutrition_meal_v1.schema.json`, migration 003 | 완료 | append-only fact, supersession |
| Food catalog | `nutrition food add\|list\|show` | 완료 | source 4종만 허용하고 추정 source는 거부한다. |
| Food fact versioning | `nutrition food fact add` | 완료 | 같은 unit의 새 버전만 만든다. unit 변환은 없다. |
| 식사 기록 | `nutrition log --meal --item FOOD QTY UNIT ... [--general [--general-note TEXT]] [--additional]` | 부분 | `FOOD`는 food ID, 또는 정확히 같은 이름/alias다(Food Name Lookup v1, 부분 일치·추측 없음). `--general`은 메뉴·영양값을 모르는 일반식(영양값 unknown, 메모 선택, 예약 profile `general-meal`, General Meal v1)이다. 자유 문장 parser(`MealParser`는 Protocol만 있음), 외부 food DB는 없다. |
| 하루 섭취 | `nutrition day [--date] [--json]` | 완료 | |
| Meal edit | `nutrition meal show\|add-item\|remove-item\|replace-item\|void\|edit\|merge`, migration 008, 009 | 부분 | void(집계 제외), 날짜·종류·시간 수정, 같은 날짜 두 식사 병합은 append-only 기록으로 한다(Meal Void, Edit and Merge v1). `add-item`/`replace-item`은 `--general`도 받는다. void·edit·item 제거 취소, 세 개 이상 병합, 메모 수정은 없다. |
| Meal repeat | `nutrition repeat <meal_id>` | 완료 | 양 조절과 template은 없다. |
| 영양 목표 + status | `nutrition target set\|show`, `nutrition status` / `domain/nutrition_targets.py`, `infrastructure/nutrition_target_store.py` | 부분 | 목표 history와 요일별 목표가 없다. 자동 계산도 없다(의도된 설계). |

### 4-4. InBody / 체성분

| 기능 | 관련 파일 / 명령 | 완성도 | 비고 |
|---|---|---|---|
| Samsung Health export import | `inbody sync --file <json> [--show-values]` / `application/sync_inbody.py`, `infrastructure/inbody/samsung_health.py`, migration 007 | 부분 | 실제 Galaxy export가 RAW 보존·정규화·저장을 통과했다는 기록 있음 [문서]. 체성분 데이터는 read-only 명령 `inbody trend`(`docs/inbody-trend.md`)만 읽는다. **분석이나 추천은 여전히 읽지 않는다**(`analytics_reader`가 body_composition을 참조하지 않음) [코드 grep]. |
| Android 진단 companion | `android/inbody-diagnostic-companion/` | 부분 | 진단 및 export 전용. 수동 빌드와 Developer Mode가 필요하다. |
| InBody 네트워크(OAuth/계정) 연동 | `infrastructure/inbody/auth.py`, `connector.py`, `authenticated_source.py`, `synthetic.py`, `application/sync_latest_inbody.py` | 스텁 | Protocol 경계와 합성 구현뿐이다. **테스트에서만 사용**하고 CLI와는 연결되지 않았다 [코드 grep]. 접근 경로 결정은 `docs/inbody-access-decision.md`에 있다. |
| InBody smoke 진입점 | `infrastructure/inbody/samsung_health_smoke.py` | 스텁(개발용) | 공용 CLI와는 의도적으로 연결하지 않았다. |

### 4-5. Telegram

| 기능 | 관련 파일 / 명령 | 완성도 | 비고 |
|---|---|---|---|
| Telegram 명령어 bot v1.2 | `telegram check\|run` / `application/telegram_bot.py`, `application/activity_unknown_sets.py`, `domain/telegram_commands.py`, `infrastructure/telegram/`, `presentation/telegram_format.py`, `presentation/telegram_summary.py` | 부분 | 고정 명령(`/today` `/status` `/day` `/log` `/void` `/show` `/inbody` `/daily` `/unknown` `/refresh`)을 `cli.main`으로 실행한다. `/today` `/status` `/daily`는 같은 명령의 JSON으로 만든 짧은 요약을 답하고(`full`이면 CLI text), 나머지는 CLI text를 답한다. `/unknown`과 요약 끝의 UNKNOWN 알림은 Garmin Connect 링크와 `/refresh <id>`(=`garmin refresh`)를 준다. 인자 없는 `/refresh`(v1.2)는 `/unknown` 목록을 차례로 다시 받는다(한 번에 10개, 운동 사이 2초, 연속 3번 실패하면 멈춤, 남은 UNKNOWN 수를 답함). 자동 refresh 없음, CLI 출력 변경 없음. stdlib `urllib` long polling, 허용 chat 목록, token 비출력, migration 없음. LLM 자유 문장은 v2. 실제 Telegram 확인은 사용자 수동 단계다. 상세: `docs/telegram-bot.md`. |

---

## 5. 데이터 모델

### 5-1. 저장소 종류

| 저장소 | 형식 | 비고 |
|---|---|---|
| SQLite `muscle50.sqlite3` | 테이블 33개 [코드: migration 001~010의 `CREATE TABLE` 수] | migration 001~010 |
| RAW 파일 | Garmin JSON, original zip, recovery endpoint JSON, InBody JSON | immutable, sha256 content-addressed, DB에서 상대 경로와 hash로 추적한다. |
| `config/nutrition_targets.json` | versioned JSON(`schema_version` 1, 값은 decimal 문자열) | DB가 아닌 파일로 둔다(의도된 결정). |
| `config/telegram.json` | JSON(`bot_token`, `allowed_chat_ids`) | 사용자가 직접 만든다. muscle50은 만들지 않는다. |
| `config/telegram_state.json` | versioned JSON(`schema_version` 1, bot id, 최근 처리한 update id 100개) | `telegram run`이 첫 허용 메시지 때 만든다. 원자적 쓰기. |
| Garmin token | `auth/garmin/` 디렉터리 | garminconnect 라이브러리가 관리한다. |

### 5-2. 테이블 (migration별) [코드: `src/muscle50/infrastructure/sqlite/migrations/*.sql`]

| Migration | 테이블 | 주요 필드 | 관계 / 제약 |
|---|---|---|---|
| 001 | `schema_migrations` | version, applied_at_utc | migration 마커 |
| 001 | `sync_runs` | provider, command, status, error_code | **미사용** |
| 001 | `raw_artifacts` | provider, source_activity_id, artifact_kind, relative_path, sha256, byte_size | UNIQUE(provider, activity, kind, sha256), UNIQUE(path) |
| 001 | `activities` | provider, source_activity_id, canonical_type(running/swimming/strength/cycling/walking/other), 시작 시각, 거리, 시간, HR, kcal, normalizer_version | FK → raw_artifacts. UNIQUE(provider, source_activity_id) |
| 001 | `activity_metrics` | metric_key, numeric_value XOR text_value, unit, source_path | FK → activities CASCADE. UNIQUE(activity, key) |
| 001 | `activity_corrections` | field_key, revision, corrected_value_json | append-only overlay 설계지만 **미사용** |
| 002 | `strength_sets` | sequence, source_exercise_category/name, set_type, reps, normalized_weight_kg, duration | FK → activities CASCADE |
| 003 | `nutrition_meals` | meal_id(PK, text), eaten_at, eaten_at_utc_sort_key, meal_type, original_text | |
| 003 | `nutrition_meal_items` | (meal_id, item_sequence) PK, food_profile_id, quantity(text), quantity_unit | FK → meals, food_profiles |
| 003 | `nutrition_food_profiles` / `_aliases` | profile_id, name / alias | |
| 003 | `nutrition_facts` | fact_id, owner(profile **XOR** meal item), kcal/protein/carb/fat(+min/max), basis, source_type, accuracy, supersedes_fact_id | **UPDATE/DELETE 금지 trigger**, supersession 검증 trigger, 다수의 CHECK |
| 004 | `swim_activities` → `swim_laps` → `swim_lengths` | pool length, lap/length 거리·시간·stroke | 계층 FK CASCADE |
| 005 | `recovery_raw_captures`, `recovery_raw_artifacts` | capture id, manifest path | content-addressed history |
| 005 | `daily_recovery` | calendar_date, 수면 단계, HRV, RHR, body battery, stress, readiness, training status 등 | UNIQUE(provider, date), FK → accepted capture |
| 006 | `activity_raw_captures`, `activity_raw_capture_artifacts`, `activity_refresh_state` | refresh snapshot, current_capture_id | |
| 007 | `inbody_raw_artifacts`, `body_composition_measurements`, `_source_identities`, `_raw_artifact_links`, `_provenance`, `_segmental_metrics`, `_metrics` | 체성분 지표, fingerprint, source identity | fingerprint는 의도적으로 unique가 아니다(자동 병합 금지). |
| 008 | `nutrition_meal_item_removals` | (meal_id, item_sequence) PK, removed_at, replaced_by_item_sequence | append-only tombstone, UPDATE/DELETE 금지 trigger |
| 009 | `nutrition_meal_revisions`, `nutrition_meal_voids`, `nutrition_meal_merged_items` | 식사 날짜·종류·시간 revision, void 사유, merge로 옮긴 item | append-only, UPDATE/DELETE 금지 trigger, void된 식사의 revision 거부 trigger |
| 010 | `sync_coverage` | (provider, data_kind, calendar_date) PK, status, missing_endpoints, failed_activity_ids, source(sync/raw_backfill), command, synced_at_utc | 날짜별 최신 상태(latest-state). `not_synced`는 row 부재 |

핵심 관계를 요약하면 다음과 같다. `activities` 1—N `activity_metrics`/`strength_sets`, 1—1 `swim_activities` 1—N laps 1—N lengths. `nutrition_meals` 1—N items 1—N facts(item 소유 snapshot). `food_profiles` 1—N facts(catalog).

### 5-3. 보안 규칙

- Firebase rules, RLS 같은 **접근 제어 계층은 없다**. 단일 사용자 로컬 파일이기 때문이다.
- 무결성 장치로는 CHECK 제약, FK, append-only trigger(nutrition facts, meal item removals, meal revisions/voids/merged items)를 쓴다. migration은 `BEGIN IMMEDIATE` transaction으로 적용한다.
- **암호화는 없다(at-rest 포함)**. 디렉터리에 `chmod 0o700`을 시도하지만 Windows에서는 오류를 무시하며 ACL 설정은 하지 않는다 [코드: `config.py`].
- `.gitignore`가 `.env*`, `*.sqlite*`, `*.db`, `garmin_tokens.json`, `tokens/`, `raw/`, `data/`를 제외한다. `config.py`는 데이터 루트가 git worktree 안이면 거부한다.

---

## 6. 화면/라우트 및 API 엔드포인트

HTTP 서버나 웹 라우트는 **없다**. CLI 명령 트리가 "라우트"에 해당한다.

### 6-1. CLI 명령 트리 [코드: `cli.py`]

```text
muscle50
├─ garmin
│  ├─ latest
│  ├─ activities --from D --to D
│  ├─ recovery [D] | --from D --to D [--yes]
│  ├─ refresh <activity_id>
│  ├─ backfill-load-metrics [--dry-run]
│  ├─ recovery-renormalize [--dry-run]
│  ├─ coverage --from D --to D [--json]
│  └─ backfill-recovery-coverage [--dry-run]
├─ analytics snapshot --date D [--days N] [--json]
├─ recommend --date D [--focus push|pull|legs|shoulders] [--avoid MUSCLE ...] [--json]
├─ daily [--date D] [--focus F] [--avoid M ...] [--json] | --after-workout [--date D] [--json]
├─ inbody sync --file PATH [--show-values]
├─ telegram check | run      # Telegram 명령어 bot v1(long polling, docs/telegram-bot.md)
└─ nutrition
   ├─ food add --id --name [--alias ...] --per QTY UNIT --kcal --protein --carbs --fat --source --accuracy [--source-ref] [--json]
   ├─ food fact add <food_id> (같은 fact 플래그) [--json]
   ├─ food list [--json] / food show <food_id> [--json]
   ├─ log --meal T [--date] [--time HH:MM] --item ID QTY UNIT ... [--additional] [--json]
   ├─ repeat <meal_id> [--date] [--time] [--meal] [--additional] [--json]
   ├─ meal show|add-item|remove-item|replace-item|void|edit|merge <meal_id> ... [--json]
   ├─ day [--date] [--json]
   ├─ target set {kcal,protein,carbs,fat} (--exact N | --range MIN MAX | --unset) [--json] / target show [--json]
   └─ status [--date] [--json]
```

Exit code 관례는 다음과 같다 [코드]. 0은 성공, 1은 알려진 오류(stderr 메시지), 2는 InBody RAW 충돌이나 argparse 오류, 130은 Ctrl+C다.

### 6-2. 외부(outbound) API 호출 [코드: `infrastructure/garmin/client.py`]

모두 `garminconnect` 라이브러리를 경유한 **비공식 Garmin Connect API**다.

| 용도 | 메서드 |
|---|---|
| Activity 목록 | `get_activities` |
| Activity 상세 | `get_activity`, `get_activity_details`, `get_activity_splits`, `get_activity_exercise_sets`(strength만), `download_activity`(original zip) |
| Recovery (날짜당 9개) | `get_sleep_data`, `get_hrv_data`, `get_rhr_daily`, `get_body_battery`, `get_all_day_stress`, `get_training_readiness`, `get_training_status`, `get_respiration_data`, `get_stats` |

InBody/Samsung은 네트워크 호출이 없다. Android 앱이 기기 안의 Samsung Health SDK에서 읽고 JSON 파일로 넘긴다.

### 6-3. Android 화면

`MainActivity` 단일 화면이다. 연결 상태, record 수, 필드 존재 여부를 보여 주고, 값 표시 토글(기본 off)과 JSON export를 제공한다. 권한은 Body Composition READ 하나만 쓴다.

---

## 7. 사용자 역할과 권한 구조

- **없음.** 로그인/계정 시스템이 없는 단일 사용자 로컬 도구다. 역할, 권한, 관리자 개념이 없다.
- 외부 인증은 사용자 본인의 Garmin 계정 하나뿐이다. 첫 실행 때 터미널에서 이메일, 비밀번호, MFA를 묻고 이후 token을 재사용한다. 자격 증명을 CLI 인자나 환경 변수로 받지 않는 것이 의도된 설계다.
- Android 앱은 Samsung Health 런타임 동의(READ, Body Composition) 하나만 요청한다.

---

## 8. 코드 컨벤션 (실제 코드에서 반복되는 패턴)

| 영역 | 패턴 [코드] |
|---|---|
| 아키텍처 | **Ports & Adapters(헥사고날) 계열 4계층**: `domain`(순수) ← `application`(use case + `Protocol` 포트) ← `infrastructure`(어댑터) / `presentation`(렌더러). `cli.py`가 composition root다. |
| Use case | `class VerbNoun`(예: `SyncGarminRecovery`, `LogMeal`, `ShowDailyNutritionStatus`). 생성자로 포트를 주입하고 `execute(...)` 메서드 하나를 둔다. |
| 값 객체 | `@dataclass(frozen=True)`를 145곳에서 쓴다. 가변 dataclass는 거의 없다. |
| 열거형 | `StrEnum`(27개, DB/JSON 문자열과 1:1). |
| 포트 | `typing.Protocol`(21개). 테스트에서 Fake/Stub으로 교체한다. |
| 네이밍 | 모듈과 함수는 snake_case, 클래스는 PascalCase, 비공개 함수는 `_` prefix, 상수는 `UPPER_SNAKE`. 렌더러는 `render_<thing>` / `render_<thing>_json`. |
| 에러 처리 | 기능별 예외 클래스(`...Error(RuntimeError/ValueError)`, 34개)가 있고, 메시지는 "safe-to-display"다. CLI 함수는 `try: ... except (알려진 오류들) as exc: print("오류: ...", stderr); return 1` / `except KeyboardInterrupt: return 130`. 알려지지 않은 오류는 traceback으로 전파된다(의도). |
| CLI 핸들러 | 매 명령마다 `AppPaths.from_environment()` → `ensure_directories()` → `Repository(...).migrate()` → 어댑터 조립 → `print(render_...)`를 반복한다. |
| 출력 | text는 **ASCII만** 쓴다(cp949 콘솔 크래시 방지, 사용자 입력 음식명은 예외). JSON은 `ensure_ascii=True`, 고정 키 순서, Decimal 문자열로 **byte-stable**하게 만든다. 진행 메시지와 prompt는 stderr, 결과는 stdout으로 보낸다. |
| 데이터 원칙 | RAW 우선 저장 → normalize → transaction persist. source 값은 덮어쓰지 않는다. 값이 없으면 `None`이고 0으로 채우지 않는다. 추측, 자동 병합, 자동 보정은 하지 않는다. |
| 읽기 전용 경로 | 분석, 추천, 영양 reader는 `mode=ro`, `query_only`로 열고 migrate나 mkdir를 하지 않는다. |
| 스타일링 | UI가 없으므로 해당 없음. 출력 서식은 presentation 모듈에 모았다. |
| 상태 관리 | 프론트엔드 상태관리는 해당 없음. 영속 상태는 SQLite, RAW, JSON만 쓴다. |
| 언어 | 코드, docstring, 테스트는 영어다. Garmin 계열 CLI 오류는 한국어("오류: ..."), nutrition/InBody 출력은 영어다(혼재). 문서는 한국어 위주이고 일부 영어 문서가 있다. |
| 커밋 메시지 | Conventional Commits(`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `merge:`). 기능 커밋 뒤에 `docs: record ... integration` 커밋이 따라오는 쌍 구조다. |
| 줄 끝/포맷 | LF 강제(`.gitattributes`), 줄 길이 120. **ruff format은 일부 파일에만 적용**된 상태라 변경한 파일만 format하는 것이 관례다. [문서/메모] |

---

## 9. 테스트·품질 도구

| 항목 | 내용 |
|---|---|
| 테스트 프레임워크 | pytest(`addopts = "-ra --strict-markers"`, `testpaths = ["tests"]`). `conftest.py`가 `src`를 sys.path에 넣는다. |
| 테스트 규모 | **[문서]** 마지막 기록은 `917 passed`(2026-10-04, Meal Repeat 통합 후). **[코드 정적 집계]** `def test_` 671개, `parametrize` 84곳. 차이는 parametrize 확장으로 설명된다(추정). 이번에 실행해서 확인한 수치가 아니다. |
| 테스트 스타일 | 합성 fixture만 쓴다(`tests/fixtures/`). `tmp_path` 임시 SQLite와 `MUSCLE50_HOME`(30개 파일에서 사용), Fake/Stub 커넥터, `capsys` CLI 출력 검증, byte-identical JSON 비교. 실제 Garmin 계정 테스트는 자동 스위트에 없다. |
| 추가 검증 관행 [문서] | 기능마다 **mutation check**(코드를 일부러 망가뜨려 테스트가 잡는지 확인), 임시 home CLI smoke, **production DB/RAW fingerprint 전후 비교**(sha256/size/mtime, table row digest)를 한다. 증거는 `C:\temp\muscle50-evidence-<날짜>-<기능>\`에 저장한다(저장소 밖). |
| 커버리지 | `pytest-cov`는 설치돼 있지만 **커버리지 설정과 기록된 수치가 없다** → 커버리지 수준 미상 |
| Lint | ruff(`select = E, F, I, UP, B, SIM`, py312, line-length 120) |
| Format | ruff format(부분 적용 상태, 위 8절 참고) |
| Typecheck | mypy `strict = true`, `garminconnect` 모듈만 `ignore_missing_imports`. [문서] 마지막 기록은 `mypy src tests` 118 files 통과. |
| CI | **없음**(`.github/` 등 CI 설정 없음). 품질 게이트는 에이전트와 사용자가 로컬에서 수동 실행한다. |
| pre-commit/hook | 없음 [코드: 설정 파일 없음] |

**실행 명령어**

| 목적 | 명령 | 출처 |
|---|---|---|
| 설치 | `uv sync --extra dev`(추정) 또는 `python -m venv .venv` → `pip install -e ".[dev]"` | README(pip 방식) |
| dev 실행 | `uv run muscle50 <command>` / 설치 후 `muscle50 <command>` | README, 문서 |
| 테스트 | `uv run --extra dev pytest` (문서 게이트) / `uv run pytest -q` (README) | 둘이 다름 |
| lint | `uv run ruff check .` | 문서, README |
| typecheck | `uv run mypy src tests` | 문서, README |
| 공백 검사 | `git diff --check` | 문서 게이트 |
| build | 별도 build/배포 단계 없음 (Android: `.\gradlew.bat :app:assembleDebug`) | |

문서상 "게이트"는 위 네 가지(pytest, `ruff check .`, `mypy src tests`, `git diff --check`)다.

---

## 10. 환경 설정

### 환경 변수 [코드: `config.py`. 소스 전체에서 `os.environ` 사용처는 이곳뿐]

| 변수 | 용도 |
|---|---|
| `MUSCLE50_HOME` | 데이터 루트 override. git worktree 내부면 거부한다. 테스트와 smoke에서 임시 home으로 쓴다. |
| `LOCALAPPDATA` | 기본 데이터 루트(`%LOCALAPPDATA%\muscle50`). 없으면 실행을 거부한다. |
| `JAVA_HOME` | Android 빌드 시에만 쓴다(README 안내). |

- `.env` 파일은 없고 코드도 읽지 않는다. 비밀 값은 환경 변수로 받지 않는다.
- git에 추적되는 민감 파일은 없다 [코드: `git ls-files` 확인]. `ProfileKeyStore.kt`는 이름과 달리 기기 로컬 무작위 UUID를 SharedPreferences에 저장하는 코드이며 키 값은 없다.
- Android: `local.properties`(SDK 경로)와 Samsung SDK `.aar`는 로컬에만 두고 ignore한다.

### 외부 서비스 연동

| 서비스 | 방식 | 상태 |
|---|---|---|
| Garmin Connect | `garminconnect` 0.3.15(비공식 API), 대화형 로그인과 MFA, token 로컬 저장 | 운영 중 |
| Samsung Health (Galaxy) | Samsung Health Data SDK 1.1.0 → Android companion → JSON 파일 수동 이동 | 운영(수동) |
| InBody | 직접 API 연동 없음(Samsung Health 경유). 네트워크 connector는 스텁이다. | 스텁 |
| Paseo | 개발 워크플로 도구(멀티 worktree 에이전트 관리). 앱 기능과는 무관하다. | 개발 환경 |

---

## 11. 기존 Claude / 에이전트 설정

| 항목 | 상태 |
|---|---|
| `CLAUDE.md` | **없음**(저장소 어디에도 없다) |
| `.claude/` (agents, skills, commands, hooks, settings) | **없음**(저장소 루트에 디렉터리 없음) |
| `AGENTS.md` | **있음**. 사실상의 에이전트 지침이다. 요약은 아래와 같다. |

**`AGENTS.md` 요약**

1. 작업 전에 `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`, 관련 소스와 테스트를 읽고, `git status` / `git log --oneline -10` / `git diff`를 확인한다.
2. 이전 대화 맥락을 가정하지 않는다. "저장소가 source of truth"다.
3. 기존 아키텍처를 유지하고, 작고 리뷰 가능한 변경만 하며, 관련 없는 코드는 다시 쓰지 않는다. 테스트, lint, typecheck를 실행하고, 검증 없이 완료를 주장하지 않는다.
4. 큰 작업이 끝나면 CURRENT_STATE와 HANDOFF를 갱신한다. 시도/완료/남은 일/변경 파일/실행한 검사/알려진 실패/다음 행동을 적는다.
5. 다른 에이전트의 미커밋 작업을 버리지 않는다. 미완성 상태가 있으면 이어서 작업한다.

**저장소 밖(사용자 수준) 설정** (참고, 저장소 미포함)

- `~/.claude/settings.json`: marketplace, advisor 모델, 업데이트 채널, 테마, 위험모드 프롬프트 생략 등의 키만 있다. 프로젝트용 hooks나 permissions는 없다.
- `~/.claude/skills/`: Paseo 계열(`paseo`, `paseo-advisor`, `paseo-committee`, `paseo-handoff` 등)과 Cloudflare 계열 skill이 있다. muscle50 전용 skill은 없다.
- Claude 프로젝트 메모리 3건: (1) Windows에서 `zoneinfo`에 tzdata가 없다. 현재 `src`에 `ZoneInfo` 사용처가 없어 잠재 위험이다. (2) local main이 origin보다 앞설 수 있으니 local main을 기준으로 삼는다. (3) ruff format은 변경 파일에만 적용하고, Windows Python 쓰기는 CRLF가 되니 주의한다.
- **현행 개발 오케스트레이션은 Paseo 멀티 worktree 방식이다** [문서/코드: `git worktree list`]. 기능마다 Paseo worktree와 `feature/*` branch를 만들고, 구현과 게이트를 거친 뒤 local main으로 **fast-forward only** 통합한다. origin push는 별도 승인 후에 한다.

---

## 12. 개발 이력

### 12-1. 브랜치 / worktree 상태 [코드]

| 항목 | 값 |
|---|---|
| 현재 브랜치 | `main` = `eb67806`, working tree clean, stash 없음 |
| origin | `origin/main` = `eb67806`. 로컬 remote-tracking 기준이고 이번 분석에서 `git fetch`는 하지 않았다. |
| 총 커밋 수 | 58 (2026-09-08 ~ 2026-10-05), 작성자 1명 |
| main에 병합된 branch | `feature/nutrition-meal-repeat`(Paseo worktree `nutrition-quick-log`가 아직 존재) |
| main에 미병합 branch | `feature/garmin-recovery`, `feature/recommendation-hardening`, `backup/garmin-activity-ingestion-stale-audit-20260918`. 문서에 따르면 모두 **재통합이나 cherry-pick으로 내용이 이미 main에 반영된 reference 보존용**이다. backup은 "do not merge"로 명시돼 있다. |
| 태그 | 없음 (`git tag` 결과 비어 있음) |

### 12-2. 최근 30개 커밋

| 커밋 | 날짜 | 요약 |
|---|---|---|
| eb67806 | 10-05 | docs: Meal Repeat 통합 기록 |
| 42cf410 | 10-04 | docs: Meal Repeat 검증 노트 경로 수정 |
| 2d2ea84 | 10-04 | feat: Nutrition Meal Repeat v1 |
| e13acfa | 10-03 | docs: Meal Edit 통합 + production migration 8 기록 |
| b234ac8 | 10-03 | feat: Nutrition Meal Edit v1 (migration 8) |
| e1e66ed | 10-03 | docs: Food Fact Versioning 통합 기록 |
| 5e3a2c8 | 10-03 | feat: append-only nutrition fact versions |
| 55364fc | 10-02 | docs: Nutrition Targets push 표시 |
| 65263aa | 10-02 | docs: Nutrition Recommendation 통합 기록 |
| caa7982 | 10-02 | fix: 열 수 없는 targets 파일을 unavailable로 보고 |
| 8f267a2 | 10-02 | feat: recommend/daily에 nutrition status·guidance |
| f07f5a2 | 10-02 | docs: Nutrition Targets 통합 기록 |
| 1549c4a | 10-02 | fix: 반올림 경계에서 0이 아닌 gap을 0으로 표시하지 않음 |
| c77de0d | 10-02 | feat: Nutrition Targets + daily status v1 |
| 7f4a4ef | 10-02 | fix: catalog fact snapshot 시 nutrient별 supersession 유지 |
| 9ec54d1 | 10-02 | feat: Nutrition Logging MVP |
| 8845b41 | 10-02 | docs: daily 통합과 live 검증 기록 |
| 8b08773 | 10-02 | fix: daily에서 Garmin endpoint 경고 노출 |
| c3f5842 | 10-02 | feat: `muscle50 daily` 오케스트레이션 |
| c06a36c | 10-02 | docs: Recommendation Hardening 통합 표시 |
| 46c9f0e | 10-02 | docs: Progression Hardening 통합·push 기록 |
| 13d5ed2 | 10-01 | feat: 정확한 증량을 15%로 제한 (Progression Hardening v1) |
| 4f26ec2 | 10-01 | fix: Recommendation Hardening과 taxonomy coverage 통합 |
| 38a23ae | 10-01 | docs: Recommendation Hardening 커밋 상태 기록 |
| 5fbdd56 | 10-01 | feat: Recommendation Hardening v1 |
| aba8cfe | 10-01 | feat: exercise taxonomy coverage 확장 |
| 8b259e7 | 10-01 | feat: 사용자 지정 strength focus |
| 7740d7d | 10-01 | feat: Training Recommendation v1 |
| a92404b | 10-01 | feat: Exercise Taxonomy v1 |
| 2603b85 | 09-30 | feat: Analytics Engine v1 rolling snapshot |

### 12-3. 기능 개발 흐름

| 시기 | 단계 | 내용 |
|---|---|---|
| 09-08 | 초기화 | `chore: initialize muscle50` |
| 09-13~14 | 수집 기반 (병렬 branch + merge commit) | Garmin activity sync MVP, strength sets(mig 2), swim details, Nutrition Core(mig 3), AGENTS.md 도입, InBody 기반 |
| 09-17~19 | 범위 확대 | Garmin recovery(mig 5), Samsung Health InBody source, 기간 activity ingestion |
| 09-27~29 | 정합성 | Activity refresh(mig 6), InBody 통합(mig 번호 충돌 006 → 007 재배정), refresh hotfix |
| 09-30 | 분석 준비 | historical import, recovery backfill, load metric backfill, Analytics v1 |
| 10-01 | 추천 | Taxonomy v1, Recommendation v1, `--focus`, Hardening v1, Progression Hardening v1 |
| 10-02 | 일상화 + 영양 | `daily`, Nutrition Logging MVP, Targets, 추천 통합 |
| 10-03~04 | 영양 편집 | Fact versioning, Meal Edit(mig 8, production 적용), Meal Repeat |

흐름 요약: 초기에는 merge commit을 썼지만 09-28 이후 **fast-forward only 통합 + 별도 docs 커밋** 패턴으로 굳어졌다. 하루에 3~4개 기능이 들어가는 매우 빠른 에이전트 주도 개발이다(추정: 커밋 밀도 기준).

---

## 13. 기존 기획 / 프롬프트 문서

프롬프트 전용 파일(`prompts/`, `.prompt` 등)은 **없다**. 기획과 규칙은 모두 `docs/`에 있다.

| 문서 | 줄 수 | 요약 |
|---|---|---|
| `README.md` | — | 사용자용 설치, 명령, 데이터 위치 안내(한국어) |
| `AGENTS.md` | — | 에이전트 작업 규칙(11절) |
| `docs/CURRENT_STATE.md` | 828 | 지속 상태: 아키텍처, 구현 목록, pending merge, 데이터 coverage, 검증 기록, migration 목록, Known issues, 중요한 결정 |
| `docs/HANDOFF.md` | 1,258 | 세션별 인계 기록 누적(최신이 위). 작업마다 시도/완료/변경 파일/검사/위험/다음 행동 |
| `docs/analytics-engine.md` | 143 | Analytics v1 집계 규칙, 수영 이상치 처리 |
| `docs/exercise-taxonomy.md` | 176 | Garmin label → movement/muscle rule table 원칙 |
| `docs/training-recommendation.md` | 518 | 추천 규칙 전체(focus 선택, progression, recovery, 수영, 증량 step) |
| `docs/garmin-analytics-prerequisites.md` | 119 | load metric 계약, recovery coverage, 보류 항목 |
| `docs/garmin-recovery-endpoint-discovery.md` | 62 | garminconnect recovery endpoint 조사 |
| `docs/swimming-details.md` | 126 | 수영 lap/length 설계 |
| `docs/nutrition-core.md` / `nutrition-core-handoff.md` | 51 / 166 | Nutrition Core 설계 / 통합 전 인계(역사 문서) |
| `docs/nutrition-logging.md` | 340 | catalog, 식사 기록, fact versioning, meal edit/repeat 상세 |
| `docs/nutrition-targets.md` | 213 | 목표 형식과 status 판정 규칙 |
| `docs/nutrition-recommendation.md` | 139 | 영양 → 추천 안내 규칙 |
| `docs/inbody-access-decision.md` / `inbody-review.md` / `inbody-sync-design.md` | 211 / 51 / 108 | InBody 접근 경로 결정(Samsung Health 경유), 독립 리뷰, source-neutral sync 설계 |
| `docs/samsung-health-payload-contract.md` | 199 | Android export JSON v1 계약 |
| `android/.../README.md` | — | companion 앱 빌드와 범위 |

기능 문서의 구조는 `# 기능명 vN` → 목적과 범위("Migration 없음", "LLM 없음" 같은 명시적 비범위) → 명령 예시 → 규칙 → 한계 순서로 일관된다.

---

## 14. 미완성·문제 지점

### 14-1. TODO/FIXME

- `src`, `tests`, `android`의 소스에서 `TODO`/`FIXME`/`XXX`/`HACK`이 **0건**이다 [코드]. 미완성 항목은 코드 주석이 아니라 `CURRENT_STATE.md`의 "Known issues"에서 관리한다.

### 14-2. 기능 공백 / 미사용 코드 [코드·문서]

| 항목 | 내용 |
|---|---|
| `sync_runs`, `activity_corrections` | 스키마만 있고 사용처가 없다. 보정 overlay도 미구현이다. "운동 없음"과 "미동기화"의 구분은 이제 `sync_coverage`(migration 010)에 기록되지만 추천 결정은 아직 쓰지 않는다(v2). 과거 activity 날짜, `garmin latest`/`refresh`는 coverage가 없다. |
| InBody 네트워크 경로 | `auth`/`connector`/`authenticated_source`/`synthetic`/`sync_latest_inbody`는 테스트 전용 스텁이다. |
| 체성분 미활용 | 저장된 body composition은 `inbody trend`(read-only 표시)만 읽는다. 분석이나 추천은 아직 읽지 않는다. |
| Load metric 재계산 | `garmin refresh` 뒤에는 load metric을 다시 계산하지 않고 기존 값을 유지한다. |
| 영양 | 자유 문장 parser, unit 변환, 목표 history, void·edit 취소, 음식 이름/alias 수정, `food show`/`food fact add`의 이름 조회가 없다. |
| 추천 | 장비별 증량 단위 미학습(Progression v2 후보), posterior deltoid 미커버, plyometric 범위 밖 |
| 자동 실행 | scheduler가 없다. `daily`는 사람이 실행한다. |

### 14-3. 기술 부채 (코드 크기·중복·언어는 [코드], 포맷·refresh·수영 항목은 [문서] 기준)

| 항목 | 내용 |
|---|---|
| `cli.py` 1,099줄 | 명령마다 path → mkdir → migrate → 조립 → try/except 보일러플레이트가 반복된다(중복 코드). |
| 대형 도메인 파일 | `strength_recommendation.py` 1,554줄, `analytics.py` 1,145줄, `sqlite/database.py` 1,107줄 |
| 포맷 불일치 | ruff format이 일부 파일(`terminal.py`, `refresh_garmin_activity.py`, `analytics.py`, `nutrition_terminal.py`, `nutrition_repository.py` 등)에 미적용이다. 전체 format을 하면 대량 diff가 생긴다. |
| 출력 언어 혼재 | Garmin 오류는 한국어, nutrition/InBody는 영어다. |
| `except Exception` 9곳 | 주로 Garmin 어댑터 경계에서 외부 예외를 감싸는 용도다. |
| Refresh RAW 증가 | Garmin details의 column 순서와 zip timestamp가 매번 달라 refresh 때마다 capture가 늘어난다(저장공간 이슈). |
| 수영 provenance | `source_pool_length`가 endpoint에 따라 2500.0과 25.0으로 다르게 기록된다. `_append_pool_length()`는 factor를 읽지 않는다. |
| 문서 비대 | CURRENT_STATE 828줄, HANDOFF 1,258줄. 누적형이라 에이전트가 읽는 비용이 계속 커진다. |
| 문서-실제 불일치 가능성 | CURRENT_STATE의 Meal Repeat 항목은 "origin push 안 함"이라고 적혀 있지만, 로컬 `origin/main` ref는 `eb67806`(= main)이다. 이후 push된 것으로 보인다(추정, fetch는 안 함). |
| 명령 문서 불일치 | README는 `uv run pytest -q`, 상태 문서 게이트는 `uv run --extra dev pytest`다. |
| tzdata 미의존 | Windows에서 named timezone이 동작하지 않는다. 현재 `ZoneInfo` 사용처가 없어 잠재 위험이다. |

### 14-4. 보안상 우려

| 항목 | 내용 |
|---|---|
| 비공식 Garmin API | 인증 방식이나 응답 shape가 바뀌면 깨질 수 있다. 차단, rate-limit 위험도 있다. |
| 로컬 데이터 암호화 없음 | Garmin token, 건강 RAW, SQLite가 평문이다. Windows에서는 `chmod` 효과가 없고 ACL도 설정하지 않는다. 사용자 프로필 디렉터리 보호에 의존한다. |
| Android Developer Mode | 디버그 APK는 Samsung Health Developer Mode에서만 동작한다. 배포 금지가 명시돼 있다. |
| 양호한 점 | 자격 증명을 인자나 환경 변수로 받지 않는다. 데이터 루트가 git worktree 안이면 거부한다. 민감 파일이 git에 추적되지 않는다. 테스트는 합성 데이터만 쓴다. InBody 값은 기본적으로 출력하지 않는다. |

---

## 15. 자동화 관점 의견

### 15-1. 기능 단위 자동 개발의 걸림돌

| 걸림돌 | 이유 | 완화 방향 (제안) |
|---|---|---|
| **Production 데이터 보호 의식(ritual)** | 기능마다 production DB/WAL/SHM/RAW fingerprint를 전후로 비교하고, production에는 쓰기 명령을 금지하며, migration은 백업 후 사용자가 적용한다. 규칙이 문서에 서술형으로 흩어져 있다. | fingerprint 수집과 비교를 스크립트나 skill로 표준화하고, 에이전트에는 `MUSCLE50_HOME` 임시 home을 강제한다. |
| **대화형 Garmin 인증(MFA)** | 무인 에이전트가 live Garmin 테스트를 할 수 없다. 첫 로그인과 token 만료 시 사람이 필요하다. | live 검증은 "사용자 수행" 단계로 분리하고, 자동 단계는 Fake 커넥터와 합성 fixture로 한정한다. |
| **CI 부재** | 게이트를 각 에이전트가 로컬에서 실행하고 결과를 문서에 텍스트로 남긴다. 검증을 신뢰할 근거가 문서뿐이다. | GitHub Actions 등 CI 도입(Windows runner)을 검토한다(추정: cp949/경로 이슈가 있어 Windows가 필요). |
| **Migration 번호 충돌** | 병렬 branch가 같은 번호를 잡는 사고가 이미 있었다(006). `INSERT OR IGNORE` 마커 때문에 조용히 실패한다. | migration 번호 예약 규칙, 또는 오케스트레이터가 직렬로 할당한다. 마커 중복을 감지하는 테스트를 둔다. |
| **ff-only 통합 + push 승인** | 병렬 feature가 같은 파일(`cli.py`, `nutrition_terminal.py`, `CURRENT_STATE.md`)을 건드리면 순서대로 rebase해야 한다. push는 사람이 승인한다. | 통합 순서를 오케스트레이터가 관리하고, 공유 hotspot 파일을 분할(cli 서브모듈화)한다. |
| **출력 byte 안정성 요구** | 기존 text/JSON 출력은 byte 단위로 불변이어야 하는 규칙이 많다(ASCII-only, 고정 키 순서). 의도치 않은 출력 변경을 실패로 본다. | golden output 테스트와 "출력 불변" 체크리스트를 skill로 만든다. |
| **ruff format 부분 적용** | 자동 format 도구가 무관한 파일을 대량 수정하고, Windows Python 쓰기는 CRLF를 넣는다. | "변경 파일만 format, LF 확인" 규칙을 hook이나 skill로 강제하거나, 한 번 전체 format 커밋으로 부채를 청산한다. |
| **문서 비대와 누적형 HANDOFF** | 매 세션 1,000줄 이상을 읽어야 해서 컨텍스트 비용이 크다. 상태 정보가 중복 기재돼 stale해지기 쉽다(push 상태 불일치 사례). | HANDOFF는 최신 작업만 남기고 archive로 분리한다. CURRENT_STATE의 Verification은 별도 파일로 뺀다. |
| **암묵적 도메인 원칙** | "0으로 채우지 않음", "추측 금지", "source 덮어쓰기 금지", "영양은 운동 계획 불변" 같은 원칙이 여러 문서에 분산돼 있다. | 원칙을 한 장짜리 규칙 문서나 skill로 추출한다. |
| **사용자 결정 의존** | 다수 기능이 "A~F 대안 비교 → 사용자 승인 → 구현" 흐름을 탔다. 범위(Non-goal) 판단이 사람에게 있다. | 오케스트레이터에 "설계 승인 게이트" 단계를 명시적으로 둔다. |

### 15-2. Skill로 뽑아내면 좋을 반복 패턴 / 규칙 후보

| 후보 skill | 내용 (현재 반복되는 절차) |
|---|---|
| `feature-gate` | `uv run --extra dev pytest` → `ruff check .` → `mypy src tests` → `git diff --check` 순서 실행, 결과 요약, 변경 파일만 `ruff format`, LF 확인(`git ls-files --eol`) |
| `prod-fingerprint` | `%LOCALAPPDATA%\muscle50` DB/WAL/SHM sha256·size·mtime, table별 row digest, migration 목록, RAW 파일 수를 `mode=ro&immutable=1`로 수집 → before/after diff → evidence 폴더 저장 |
| `temp-home-smoke` | 임시 `MUSCLE50_HOME` 생성, 합성 음식/식사/목표 투입, CLI text·JSON 출력 캡처, 재실행 byte-identical 확인 |
| `add-migration` | 다음 번호 확인, `BEGIN IMMEDIATE ... INSERT OR IGNORE schema_migrations ... COMMIT` 템플릿, append-only trigger 패턴, `test_database.py`/`test_cli.py`의 migration 기대값 갱신, read-only reader의 이전 스키마 호환 확인, production 적용 전 백업 절차 |
| `add-cli-command` | argparse 등록 → `_handler` (paths/migrate/조립/try-except/exit code) → use case 클래스(`execute`) → `render_x`/`render_x_json`(ASCII, `ensure_ascii`, Decimal 문자열) → CLI 테스트(`capsys`) |
| `add-use-case` | Protocol 포트, frozen dataclass 결과, 도메인 예외(safe message), Fake 구현을 쓰는 단위 테스트 |
| `mutation-check` | 핵심 guard를 하나씩 일부러 제거하고 테스트가 실패하는지 확인한 뒤 원복하고 결과를 기록한다. |
| `handoff-update` | AGENTS.md 형식(시도/완료/남은 일/변경 파일/검사/위험/다음 행동)으로 HANDOFF를 갱신하고, CURRENT_STATE의 Implemented/Pending merge/Verification/Known issues를 동기화한다. |
| `ff-integrate` | `git fetch` + `ls-remote`로 origin 확인, `merge-base --is-ancestor`, ff-only merge, 통합 후 게이트 재실행, docs 커밋 작성. push는 승인을 기다린다. |
| `domain-principles` (규칙 문서형) | 결측은 0이 아님, 추측/자동병합 금지, RAW 먼저, source/derived 분리, read-only 경로는 mkdir/migrate 금지, 영양은 운동 계획을 바꾸지 않음, LLM/ML 미사용 |
| `garmin-payload-shapes` (참조형) | list와 detail endpoint의 shape 차이(`summaryDTO` 중첩), pool length factor, refresh 시 key 이름 차이 같은 Garmin 특이사항 |

### 15-3. 오케스트레이터 설계를 위한 참고 사실

- 기능 하나의 단위는 대체로 "use case 1~4개 + CLI 서브커맨드 + 렌더러 + 테스트 파일 1개(17~45 tests) + 기능 문서 1개 + CURRENT_STATE/HANDOFF/README 갱신"이다 [문서/코드 패턴].
- 공유 hotspot 파일: `cli.py`, `presentation/terminal.py`, `presentation/nutrition_terminal.py`, `application/nutrition_logging.py`, `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`, `README.md`, `tests/test_database.py`(migration 기대값). 병렬 작업 시 충돌 지점이다.
- 이미 존재하는 역할 분리는 다음과 같다. feature 구현 에이전트(worktree), integration 에이전트(ff-only + 게이트 재실행), 사용자(설계 승인, production migration 적용, live Garmin 검증, push 승인). 이를 오케스트레이터-에이전트 구조로 옮기는 것이 자연스럽다(추정).
