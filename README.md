# muscle50

Windows 로컬 환경에서 개인 운동 데이터를 관리하는 도구입니다. Garmin Connect의 가장 최근
activity와 날짜별 recovery/daily-health 응답을 RAW 파일과 normalized SQLite 데이터로
보존합니다. 웨이트 activity는 Garmin exercise set의 종목·중량·반복·휴식 구간도 함께
정규화합니다.

## 요구 환경

- Windows 11
- Python 3.12 이상
- Garmin Connect 계정

## 설치

PowerShell에서 별도 virtual environment를 만든 뒤 editable install을 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## 최신 Garmin activity 동기화

```powershell
muscle50 garmin latest
```

첫 실행에는 터미널에서 Garmin 이메일과 비밀번호를 묻습니다. 비밀번호 입력은 화면에
표시되지 않습니다. Garmin 계정에 MFA가 설정되어 있으면 이어서 일회용 코드를 입력합니다.
로그인 성공 후에는 저장된 token을 재사용하므로 일반적으로 다시 자격 증명을 묻지 않습니다.

개인 데이터는 저장소가 아니라 다음 위치에 저장됩니다.

```text
%LOCALAPPDATA%\muscle50\
├─ auth\garmin\                 # Garmin token
├─ raw\garmin\activities\      # initial RAW와 content-addressed refresh snapshots
├─ raw\garmin\recovery\        # 날짜별 immutable recovery snapshot history
├─ db\muscle50.sqlite3          # normalized activity/recovery, nutrition, correction
└─ config\nutrition_targets.json # nutrition 목표 (처음 설정할 때 생성)
```

`MUSCLE50_HOME` 환경 변수로 데이터 위치를 바꿀 수 있지만 Git worktree 내부 경로는 안전을
위해 거부합니다. Garmin 이메일·비밀번호를 CLI 인자나 환경 변수로 받지 않습니다.

동일한 최신 activity를 다시 실행하면 Garmin activity ID의 database unique constraint를
기준으로 중복 저장하지 않고 기존 normalized 데이터를 요약합니다.

웨이트 activity는 종목별 운동 세트를 표시하고 마지막에 운동 세트/반복 합계를 보여 줍니다.
`REST` 행은 `strength_sets`에 그대로 저장하지만 운동 합계에서는 제외합니다. Garmin이 제공하지
않은 중량, 반복, 시간 값은 추정하지 않고 `NULL`로 유지합니다. 기존 DB는 시작할 때 migration 2가
`strength_sets` 테이블을 추가하며, 이미 보존된 웨이트 RAW가 있으면 원격 상세 API를 다시 호출하지
않고 해당 파일에서 세트를 백필합니다.

가져온 뒤에는 `daily`와 같은 방식으로 activity load metric 10종을 저장된 RAW에서 바로 채우므로
`garmin backfill-load-metrics`를 따로 실행하지 않아도 됩니다(Garmin 추가 호출 없음, 여러 번 실행해도 안전).
출력 마지막 줄에 결과가 붙습니다(예시 형식).

```text
Load metrics: metric rows inserted <n>, updated <n>, unchanged <n>
```

이번 실행에서 저장한 activity의 RAW summary를 읽을 수 없으면 `Load metrics failed: ...`를 표시하고 exit code 1로
끝납니다. 이미 저장된 activity와 RAW는 그대로 남습니다. 경고는 `Load metrics warning: ...` 줄로 보여 줍니다.

## 기간별 Garmin activity 동기화

```powershell
muscle50 garmin activities --from 2026-01-01 --to 2026-01-31
```

`--from`/`--to`는 포함 범위의 local 날짜(YYYY-MM-DD)이며 잘못된 날짜/범위는 로그인이나
네트워크 호출 전에 거부합니다. `garmin latest`와 동일한 RAW 저장·normalization·persistence
경로를 activity마다 그대로 재사용하므로 웨이트 세트, 수영 lap/length 정규화도 동일하게
적용됩니다. 이미 저장된 activity는 다시 가져오지 않고 건너뛰며, 한 activity가 실패해도 나머지
activity는 계속 처리됩니다. 실행할 때마다 발견/신규 저장/이미 저장됨/실패 건수를 요약해서
보여줍니다. 그 뒤 `garmin latest`와 같은 load metric 단계를 실행하고 `Load metrics: ...` 줄을 마지막에
출력합니다. 새로 저장한 activity가 없어도 실행하며, 이미 채워진 경우에는 `unchanged`만 나옵니다.

## 기존 Garmin activity 명시적 refresh

Garmin Connect에서 종목명, 세트 또는 수영 기록을 수정한 뒤 기존 activity 하나만 다시
가져오려면 다음 명령을 사용합니다.

```powershell
muscle50 garmin refresh 24481518495
```

일반 `latest`/기간 동기화는 기존 activity를 계속 건너뜁니다. `refresh`만 activity/details,
splits, strength exercise sets 및 original archive를 다시 요청하고, 응답 전체를
`raw\garmin\activities\<activity-id>\snapshots\<sha256>\` 아래 immutable snapshot으로
보존합니다. 같은 응답은 같은 snapshot을 재사용하고 변경된 응답은 새 snapshot이 됩니다.
정규화와 DB 저장이 실패해도 새 RAW는 남고 이전 canonical activity와 Strength/Swim child
행은 그대로 유지됩니다. 성공하면 canonical activity, metrics, strength sets, swim
activity/laps/lengths를 하나의 transaction에서 교체합니다.

ACTIVE strength set의 Garmin 분류가 `UNKNOWN`이거나 비어 있으면 structured review warning을
표시합니다. muscle50는 종목 분류를 추측해 고치지 않습니다.

## Garmin recovery 동기화

Garmin 계정의 달력 날짜를 명시해 수면, HRV, 안정시 심박, Body Battery, 스트레스, 훈련
준비도/회복 시간, 훈련 상태, 호흡 데이터를 동기화합니다.

```powershell
muscle50 garmin recovery 2026-09-15
```

각 endpoint의 성공 응답은 내용 기반 immutable snapshot으로 보존됩니다. 일부 metric이 없거나
endpoint 하나가 실패해도 가능한 데이터는 저장하고 경고를 표시합니다. 동일 응답은 같은 RAW
capture를 재사용하고, 응답이 바뀌면 과거 snapshot을 유지한 채 해당 날짜의 normalized 행만
최신 accepted capture 기준으로 갱신합니다. 잘못된 날짜는 로그인이나 네트워크 호출 전에
거부합니다.

## Garmin sync coverage

날짜별로 "동기화했고 데이터가 없었음"(`synced`, activity 0개)과 "동기화한 적 없음"(`not synced`)을 구분해 보여 줍니다.
`garmin activities --from/--to`, `garmin recovery`(단일 날짜/범위), `daily`가 sync한 날짜마다 최신 결과 하나를 기록합니다
(activities: `synced`/`failed`, recovery: `synced`/`partial`/`failed`). `garmin latest`와 `garmin refresh`는 기록하지 않습니다.

```powershell
muscle50 garmin coverage --from 2026-10-01 --to 2026-10-05          # read-only, Garmin 호출 없음, 최대 366일
muscle50 garmin coverage --from 2026-10-01 --to 2026-10-05 --json   # 기록한 명령과 시각 포함
muscle50 garmin backfill-recovery-coverage --dry-run                # 이전에 저장한 recovery 날짜를 RAW에서 채울 결과만 표시
muscle50 garmin backfill-recovery-coverage
```

Discovery 실패, page limit 도달, 날짜를 읽을 수 없는 목록 항목이 있으면 그 범위의 activities는 `synced`로 기록하지 않고,
오늘 이후 날짜와 인증 실패로 시도하지 않은 recovery 날짜도 기록하지 않습니다. 기록에 실패해도 sync 결과(stdout, exit code)는
그대로이고 stderr에 경고 한 줄만 나옵니다. `backfill-recovery-coverage`는 이 기능 이전에 저장된 recovery 날짜를 accepted
RAW capture의 endpoint 목록으로 `synced`/`partial`(출처 `backfilled from RAW`)로 채웁니다. Garmin을 호출하거나 RAW를 쓰지
않고, 이미 기록이 있는 날짜는 건드리지 않아 여러 번 실행해도 안전합니다. 과거 activity 날짜는 추정하지 않으므로
`garmin activities --from --to`로 다시 sync하기 전까지 `not synced`입니다. 이 기능은 migration 010을 씁니다(첫 쓰기 명령에서
적용, `garmin coverage`는 그 전 DB도 읽음). 상세: `docs/sync-coverage.md`.

## Training snapshot (Analytics v1)

저장된 데이터만 읽어 지정 날짜로 끝나는 기간(기본 7일)의 운동/회복 요약을 계산합니다. DB를 읽기 전용으로
열고 Garmin에 접속하지 않습니다. 없는 값은 0이 아니라 `unavailable`로 표시합니다.

```powershell
muscle50 analytics snapshot --date 2026-09-28
muscle50 analytics snapshot --date 2026-09-28 --days 28 --json
```

집계 규칙과 수영 lap/length 이상치 처리는 `docs/analytics-engine.md`를, 종목 → movement pattern/
muscle group 매핑(Exercise Taxonomy v1)은 `docs/exercise-taxonomy.md`를 참고하세요.

## 하루 workflow (`muscle50 daily`)

평소 하루에 필요한 activity 동기화(어제~오늘), load metric 채우기, recovery 동기화(어제~오늘), 오늘 추천을 명령 하나로
실행합니다. 각 단계는 위의 개별 명령과 같은 코드를 그대로 쓰므로 여러 번 실행해도 안전합니다.

```powershell
muscle50 daily                              # 운동 전: 오늘 날짜로 sync 후 자동 추천
muscle50 daily --focus pull                 # 오늘 focus 직접 지정 (push/pull/legs/shoulders)
muscle50 daily --avoid triceps --json       # recommend와 같은 --avoid / JSON 출력
muscle50 daily --date 2026-10-02            # 날짜 직접 지정 (기본값: 이 컴퓨터의 오늘)
muscle50 daily --after-workout              # 운동 후: activity 가져오기 + load metric만 (recovery·추천 없음)
```

단계(Garmin 로그인, activities, load_metrics, recovery, recommendation)별 결과를 먼저 보여 주고, 추천은
`muscle50 recommend --date <날짜>`와 같은 내용을 그 아래에 그대로 출력합니다. 어느 sync 단계든 실패하면 실패한 단계를
표시하고 exit code 1로 끝나며, 불완전할 수 있는 데이터로 추천을 만들지 않습니다(이미 저장된 데이터는 유지).
`garmin refresh`, InBody import, Garmin 첫 로그인(MFA)은 여전히 별도 명령입니다.

## Training recommendation (v1)

저장된 데이터만 읽어 지정 날짜의 strength 계획(focus, 익숙한 Garmin 종목, set/rep/load 목표, recovery·수영
간섭 조정)과 다음 수영 목표를 결정적 규칙으로 계산합니다. DB는 읽기 전용, Garmin 접속 없음, LLM 없음.

```powershell
muscle50 recommend --date 2026-09-24
muscle50 recommend --date 2026-09-24 --json
muscle50 recommend --date 2026-09-24 --avoid triceps
muscle50 recommend --date 2026-09-24 --focus shoulders   # 오늘 할 focus 직접 지정: push/pull/legs/shoulders
```

추천 창(D-28..D)에 sync coverage 기록이 있으면 `== Data freshness ==`에 coverage 요약 두 줄("synced, no activity"와
"not synced" 날짜 구분)이, JSON `data_freshness`에는 `sync_coverage_recorded: true`와 마지막 key `sync_coverage`가 추가됩니다
(`daily`의 추천도 같음). 기록이 없으면 출력은 기존과 같습니다. coverage는 표시만 하고 추천 결정은 바꾸지 않습니다.

규칙과 한계는 `docs/training-recommendation.md`를 참고하세요.

## Nutrition logging (MVP)

개인 음식 catalog에 직접 입력한 영양 정보(라벨/본인 입력)로 식사를 기록하고, 식사별·하루 섭취 kcal/단백질/탄수화물/
지방을 계산합니다. 외부 DB 조회나 이름 기반 추정은 하지 않습니다. 메뉴 추천, 자유 문장 파싱은 아직 없습니다(목표와
남은 양은 아래 Nutrition targets).

```powershell
# <...>에는 포장 라벨 등 본인이 가진 값을 넣습니다(예시 값 없음). 모르는 값은 unknown.
muscle50 nutrition food add --id chicken-breast --name 닭가슴살 --per 100 g `
  --kcal <kcal> --protein <g> --carbs <g> --fat <g|unknown> --source nutrition_label --accuracy exact
muscle50 nutrition food add --id egg --name 계란 --per 1 count `
  --kcal <kcal> --protein <g> --carbs <g> --fat <g|unknown> --source user_provided --accuracy estimated
muscle50 nutrition food list
muscle50 nutrition food show chicken-breast   # fact history (active/superseded)
# 기존 음식에 새 영양 fact version 추가(이전 fact와 이미 기록한 식사는 그대로, 이후 식사부터 새 fact 사용)
muscle50 nutrition food fact add chicken-breast --per 100 g `
  --kcal <kcal> --protein <g> --carbs <g> --fat <g> --source food_database --accuracy estimated --source-ref "<출처>"
muscle50 nutrition log --meal breakfast --item chicken-breast 200 g --item egg 2 count
# food ID 대신 음식 이름이나 alias를 정확히 써도 됨(공백이 있으면 따옴표). log/meal add-item/meal replace-item 공통
muscle50 nutrition log --meal lunch --item 닭가슴살 150 g --item 계란 1 count
muscle50 nutrition day                      # 오늘 섭취량 (--date YYYY-MM-DD, --json)
# 이전 식사를 그대로 다시 기록(같은 음식/양/단위, 영양 값은 지금 catalog의 fact로 새로 snapshot)
muscle50 nutrition repeat 2026-10-02-breakfast-1                       # 오늘, 같은 식사 종류, 시간 없음
muscle50 nutrition repeat 2026-10-02-dinner-1 --meal lunch --time 12:30 --date 2026-10-03
# 이미 기록한 식사 고치기(meal ID 유지; 새 --additional 식사를 만들지 않음)
muscle50 nutrition meal show 2026-10-02-breakfast-1
muscle50 nutrition meal add-item 2026-10-02-breakfast-1 --item hetbahn-white-210 210 g
muscle50 nutrition meal remove-item 2026-10-02-breakfast-1 --item-number 3
muscle50 nutrition meal replace-item 2026-10-02-breakfast-1 --item-number 2 --item hetbahn-white-210 105 g
# 식사 전체 고치기(meal ID와 item snapshot 유지; 기존 row를 바꾸지 않고 기록을 append)
muscle50 nutrition meal void 2026-10-02-snack-1 --reason "double entry"   # 집계에서 제외(되돌릴 수 없음)
muscle50 nutrition meal edit 2026-10-02-dinner-1 --date 2026-10-01 --time 21:30   # 날짜/종류/시간 (--meal, --no-time)
muscle50 nutrition meal merge 2026-10-02-breakfast-1 2026-10-02-breakfast-2       # target <- source, source는 void
```

`--kcal/--protein/--carbs/--fat`는 모두 필수이며 모르는 값은 `unknown`으로 남깁니다(0으로 채우지 않음). 단위는
변환하지 않습니다(pack으로 등록한 음식을 g으로 기록할 수 없음). 영양 값 변경은 `food fact add`로 새 version을
append할 때만 가능합니다(기존 fact UPDATE/DELETE 없음). 식사 item은 `nutrition meal`로 추가/제거/교체할 수 있고,
추가한 item은 그 시점의 active fact를 snapshot하며 기존 item은 그대로입니다. 마지막 item은 제거할 수 없고, 이름
수정은 아직 없습니다. 같은 `add-item`을 두 번 실행하면 item이 두 번 추가됩니다(`remove-item`으로 되돌림).
`nutrition meal void`한 식사는 `day`/`status`/`recommend`/`daily`에서 바로 빠지고 `meal show`에는 void와 사유가 남으며,
되돌릴 수 없고 더 고칠 수도 없습니다. `meal edit`은 날짜/종류/시간만 바꾸고(ID는 그대로라 ID의 날짜/종류와 달라질 수
있음), 옮겨 갈 날짜·종류에 식사가 있으면 `--additional` 없이 거부합니다. `meal merge`는 같은 날짜의 두 식사만 합치며,
source의 item을 원래 snapshot 그대로 target에 붙이고 source를 void합니다. 그 날짜 총합이 달라지면 거부합니다.
이 기능은 migration 009를 씁니다(첫 쓰기 명령에서 적용).
`nutrition repeat`는 원본 식사의 현재 item(제거된 item 제외, 교체 item 포함)의 음식 ID/양/단위만 가져와 `nutrition log`와 같은 방식으로 새 식사를 기록하며 원본 식사는 바꾸지 않습니다. 같은 날짜·같은 식사 종류가
이미 있으면 `--additional` 없이 거부합니다. 양 조절, 저장된 template은 없습니다. `--item`의 음식은 food ID, 또는 이름/alias와
정확히 같을 때(대소문자 무시는 ASCII만)만 찾습니다. 부분 일치·추측은 하지 않고, 한 음식의 ID가 다른 음식의 이름/alias와 겹치면
거부합니다(아무것도 기록하지 않음). 상세: `docs/nutrition-logging.md`, `docs/food-name-lookup.md`,
`docs/nutrition-meal-corrections.md`.

## Nutrition targets + daily status (v1)

하루 목표를 영양소별로 직접 정하고(정확한 값 / 범위 / 없음), 그 날짜에 기록한 섭취량과 비교합니다. 목표를 계산하거나
추정하지 않습니다. 목표는 `%LOCALAPPDATA%\muscle50\config\nutrition_targets.json`에 저장됩니다(DB migration 없음).

```powershell
# 예시 값입니다. 본인 목표를 넣으세요.
muscle50 nutrition target set protein --range 170 180     # 범위(양 끝 포함)
muscle50 nutrition target set fat --exact 80              # 정확한 값
muscle50 nutrition target set kcal --unset                # 목표 없음 (0이 아님)
muscle50 nutrition target show                            # --json 가능
muscle50 nutrition status                                 # 오늘 섭취 vs 목표 (--date YYYY-MM-DD, --json)
```

어느 식사 item에 해당 영양소 값이 없으면(`unknown`) 그 영양소의 총량과 남은 양은 모른다고 표시하고(0으로 계산하지 않음),
아는 item 합계와 값이 없는 item을 보여 줍니다. 아는 item 합계만으로 이미 목표/범위 상한을 넘으면 "above"만 확정합니다.
목표 기록은 하나뿐이라 과거 날짜도 현재 목표와 비교합니다. 상세: `docs/nutrition-targets.md`.

`muscle50 recommend`와 `muscle50 daily`는 목표가 하나라도 설정돼 있으면 추천 날짜의 영양 status(`nutrition status`와 같은
계산)를 `== Nutrition ...` 절로 보여 주고, 기록된 섭취가 목표보다 적을 때만 짧은 행동 안내를 붙입니다(protein; kcal; 운동이
계획된 날의 carbohydrate). 식사 기록이 없으면 0으로 보지 않고 "status를 쓰지 않음"만 표시하며, 값이 없는 item이 있으면 남은 양을
말하지 않습니다. 영양은 운동 계획을 바꾸거나 취소하지 않습니다. JSON은 끝에 `nutrition` key만 추가됩니다. 상세:
`docs/nutrition-recommendation.md`.

## 개발 검증

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src tests
```

테스트 데이터는 실제 계정에서 수집하지 않은 합성 fixture만 사용합니다.

## Samsung Health InBody sync

Galaxy diagnostic companion이 export한 JSON은 Git worktree 밖의 local application data에 둡니다.

```text
%LOCALAPPDATA%\muscle50\imports\inbody\samsung-health\latest.json
```

```powershell
uv run muscle50 inbody sync --file `
  "$env:LOCALAPPDATA\muscle50\imports\inbody\samsung-health\latest.json"
```

기본 출력은 discovered/inserted/existing/changed 상태만 표시하며 실제 건강 수치는 출력하지 않습니다.
명시적으로 `--show-values`를 추가한 경우에만 normalized 값을 표시합니다. 실제 저장 위치는
`%LOCALAPPDATA%\muscle50\db\muscle50.sqlite3`와
`%LOCALAPPDATA%\muscle50\raw\inbody\samsung_health`입니다.
