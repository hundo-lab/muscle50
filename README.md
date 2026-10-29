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
`garmin activities --from/--to`, `garmin recovery`(단일 날짜/범위), `daily`, `garmin sync`가 sync한 날짜마다 최신 결과 하나를 기록합니다
(activities: `synced`/`failed`, recovery: `synced`/`partial`/`failed`). `garmin latest`와 `garmin refresh`는 기록하지 않습니다.

```powershell
muscle50 garmin coverage --from 2026-10-01 --to 2026-10-05          # read-only, Garmin 호출 없음, 최대 366일
muscle50 garmin coverage --from 2026-10-01 --to 2026-10-05 --json   # 기록한 명령과 시각 포함
muscle50 garmin backfill-recovery-coverage --dry-run                # 이전에 저장한 recovery 날짜를 RAW에서 채울 결과만 표시
muscle50 garmin backfill-recovery-coverage
```

Discovery 실패, page limit 도달, 날짜를 읽을 수 없는 목록 항목이 있으면 그 범위의 activities는 `synced`로 기록하지 않고,
오늘 이후 날짜와 인증 실패로 시도하지 않은 recovery 날짜도 기록하지 않습니다. 기록에 실패해도 sync 결과(stdout, exit code)는
그대로입니다. 단독 명령은 stderr에 경고 한 줄을 내고, `daily`에서는 해당 stage(`activities`/`recovery`)의 warning으로
보여 줍니다. `backfill-recovery-coverage`는 이 기능 이전에 저장된 recovery 날짜를 accepted
RAW capture의 endpoint 목록으로 `synced`/`partial`(출처 `backfilled from RAW`)로 채웁니다. Garmin을 호출하거나 RAW를 쓰지
않고, 이미 기록이 있는 날짜는 건드리지 않아 여러 번 실행해도 안전합니다. 과거 activity 날짜는 추정하지 않으므로
`garmin activities --from --to`로 다시 sync하기 전까지 `not synced`입니다. 이 기능은 migration 010을 씁니다(첫 쓰기 명령에서
적용, `garmin coverage`는 그 전 DB도 읽음). `garmin coverage` 출력 끝의 `Recorded by:` 줄은 `garmin sync`를 적지 않습니다(출력을
바꾸지 않으려고 그대로 둠). 상세: `docs/sync-coverage.md`.

## Training snapshot (Analytics v1)

저장된 데이터만 읽어 지정 날짜로 끝나는 기간(기본 7일)의 운동/회복 요약을 계산합니다. DB를 읽기 전용으로
열고 Garmin에 접속하지 않습니다. 없는 값은 0이 아니라 `unavailable`로 표시합니다.

```powershell
muscle50 analytics snapshot --date 2026-09-28
muscle50 analytics snapshot --date 2026-09-28 --days 28 --json
```

집계 규칙과 수영 lap/length 이상치 처리는 `docs/analytics-engine.md`를, 종목 → movement pattern/
muscle group 매핑(Exercise Taxonomy v1)은 `docs/exercise-taxonomy.md`를 참고하세요.

근력 세트 중 1회당 1.0초 미만인 ACTIVE 세트(버튼을 늦게 눌러 운동이 앞 REST로 기록된 경우)가 기간 안에 있으면
Strength 절 끝에 `Set timing`과 `Rest between sets` 줄이, `--json` 끝에 `strength_set_timing` key가 붙습니다. 저장된
세트와 심박 RAW(`details.json`)만 읽어 추정하고(방법과 신뢰도 표시, 심박 값은 출력하지 않음), 아무것도 저장하지 않으며
추천 규칙은 이 값을 쓰지 않습니다. 의심 세트가 없으면 출력은 전과 같습니다. 규칙과 한계는 `docs/strength-set-timing.md`.

## 하루 workflow (`muscle50 daily`)

평소 하루에 필요한 activity 동기화, load metric 채우기, recovery 동기화, 오늘 추천을 명령 하나로 실행합니다. 각 단계는
위의 개별 명령과 같은 코드를 그대로 쓰므로 여러 번 실행해도 안전합니다.

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
목표 모드가 설정돼 있으면 `daily`는 Garmin 접속 전에 목표·수면 설정 파일을 읽고(깨졌으면 exit 1), 추천에 `recommend`와 같은
goal 절과 진행 목표가 들어갑니다. `--after-workout`은 목표 파일을 읽지 않습니다(아래 Training goal mode).

**이어 받기**: 동기화 범위는 sync coverage 기록으로 정합니다. 운동·회복이 모두 `synced`이고 그 날이 끝난 뒤에 기록된 마지막
날의 다음 날부터 오늘까지 받습니다. 시작일은 어제보다 늦지 않고(매일 아침 `daily`를 돌리면 지금처럼 어제~오늘) 7일 전보다
이르지 않습니다. `--after-workout`은 운동 coverage만 봅니다. 시작일이 어제보다 이를 때만 daily 단계 결과 끝(추천 앞)에
`Sync range: ...` 줄이, 7일보다 오래 빠진 날이 있으면 `Older unsynced days: ...` 줄과 받는 명령이 붙고, `--json`에는 마지막 key
`catch_up`이 붙습니다. 빠진 날이 없거나 coverage 기록이 없으면 출력은 이전과 같습니다.

```powershell
muscle50 daily                                                   # 빠진 날이 있으면 stderr에 "syncing 2026-10-14..2026-10-21"
muscle50 garmin sync --from 2026-10-09 --to 2026-10-13           # 정한 기간의 activities + load metric + recovery (추천 없음)
muscle50 garmin sync --from 2026-10-01 --to 2026-10-18 --yes     # 7일 넘으면 --yes 필요, 최대 31일
muscle50 garmin sync --from 2026-10-09 --to 2026-10-13 --json    # daily --json과 같은 문서("mode": "sync")
```

`garmin sync`는 로그인 한 번으로 `daily`의 동기화 단계만 돌리고 coverage를 `garmin sync`로 기록합니다. 날짜 형식, 순서,
미래 날짜, 31일 초과, 7일 초과인데 `--yes`가 없으면 디렉터리·로그인 전에 `오류:`로 거부합니다(exit 1). Garmin 요청은
회복만 하루 약 9회이고 운동 목록·상세 요청이 더해집니다. 상세와 한계: `docs/daily-catch-up.md`.

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

규칙과 한계는 `docs/training-recommendation.md`를 참고하세요. 목표 모드(cut/maintain/gain)가 설정돼 있으면 아래
Training goal mode의 goal 절과 진행 목표가 더해집니다.

## Training goal mode (v1)

목표를 **cut(근육 유지하며 감량) / maintain / gain** 중 하나로 직접 정하면 `recommend`, `daily`, `nutrition status`의 진행 목표와
표시가 그 목표에 맞게 바뀝니다. 목표를 계산하거나 식단 목표·운동 계획을 자동으로 바꾸지 않습니다. 목표는
`%LOCALAPPDATA%\muscle50\config\training_goal.json`에 저장됩니다(DB migration 없음, 파일은 `goal set`만 만듦).

```powershell
# <...>에는 본인 목표를 넣으세요(예시 값 없음). 값은 모두 선택이고, 목표 체지방률과 목표 체중은 하나만.
# 감량 정체 확인은 선택: --plateau-weeks <N>(2~26주, cut + --weekly-loss일 때만)
muscle50 goal set --mode cut --target-body-fat <PCT> --by <YYYY-MM-DD> --min-smm <KG> --weekly-loss <MIN> <MAX> [--plateau-weeks <N>]
muscle50 goal set --mode maintain                         # 또는 --mode gain
muscle50 goal show                                        # --json 가능. 목표가 없으면 기본 규칙(gain)
muscle50 goal unset                                       # 목표 지우기(기존 출력으로 돌아감)
# 훈련 수면 기준(지금 기본값: 5시간 미만 유지, 4시간 미만 감소, 점수 50 미만 유지)
muscle50 settings sleep show                              # --json 가능
muscle50 settings sleep set --hold-below-hours <H> --reduce-below-hours <H> --hold-below-score <N>
muscle50 settings sleep reset                             # 기본값으로
```

`goal set`은 목표 문서 전체를 바꿉니다(주지 않은 값은 지워짐; 영양소별로 합치는 `nutrition target set`과 다름). 잘못된 값은
flag와 범위만 말하고 값은 출력하지 않으며 exit 1로 거부합니다(파일은 그대로). 두 명령 모두 DB와 Garmin을 쓰지 않습니다.

- **cut 모드의 진행 목표**: 마지막 session에 무게가 기록된 종목의 `increase_load`/`add_reps`가 `maintain_load`(같은 무게, 같은
  횟수)가 되고 원래 증가 목표는 선택으로 보여 줍니다. set 수, 종목, focus는 바뀌지 않습니다. maintain과 gain의 진행은 지금과
  같습니다.
- **goal 절**(`== Goal: ... ==`, `== Data freshness ==` 앞): 목표, 진행 규칙, 근육별 주 10세트 미만(primary 1, secondary 0.5),
  InBody 두 측정(7일 이상 간격) 사이 주당 체중 변화 %(cut이면 사용자 목표 범위 밖과 근거 상한 1 %/주 초과를 알림), 골격근량 하한
  위/아래, 목표까지 필요한 주당 속도, 같은 날 3시간 안에 붙은 러닝과 하체 근력(러닝이 먼저면 "근력 먼저"), 7시간 미만 수면 밤 수. 모두 표시만
  하고 줄마다 근거 ID(`docs/evidence/training-nutrition-evidence.md`) 또는 `[design]`이 붙습니다. 측정 kg은 보여 주지 않고 속도와
  flag만 보여 줍니다(측정값은 `inbody trend`). 값이 없으면 0이 아니라 `unknown`입니다.
- **유산소 가이드**(Aerobic Guide v1, goal 절 끝, 모든 모드): 지난 7일 러닝·수영의 중강도/고강도 분(Garmin intensity minutes)과
  지침 기준선 150/300분, 그 전 30일 최장 러닝보다 10 % 넘게 긴 러닝 알림(관찰 연구의 연관, 알림만). intensity minutes가 없는
  활동은 더하지 않고 합계를 하한으로 표시합니다. cut에서 `--plateau-weeks`를 정했으면 InBody 구간(2개 이상, N주 이상)이 모두
  `--weekly-loss` MIN보다 느릴 때 정체로 보고, 순위 없는 네 선택지(식사 기록 확인, 섭취 100~150 kcal 줄이기, 섭취는 두고 활동
  늘리기, 1주 유지)를 근거 ID와 함께 보여 줍니다. 처방하거나 계획·목표를 바꾸지 않습니다.
- `recommend --json`과 `daily --json`의 추천에는 마지막 key `goal_mode`가 붙고 `recommendation_version`은 1 그대로입니다.
  `goal_mode` 끝에는 `aerobic_minutes`, `run_length`, `plateau`(gain/maintain이면 null)가 붙습니다(`goal_mode_version` 1 그대로).
- 목표 파일은 `--plateau-weeks`를 줬을 때만 schema 2로 쓰이고(이전 빌드는 읽지 못함), 없으면 schema 1 그대로입니다.
- 목표 파일이나 수면 설정 파일이 깨졌으면 `recommend`/`daily`는 Garmin 접속 전에 `오류:`로 끝납니다(exit 1). `goal unset`
  또는 `settings sleep reset`으로 지웁니다.
- 수면 기준은 근거가 없는 설계 값(SLEEP-05)이라 사용자 설정으로 두었습니다. 설정 파일이 없으면 동작은 이전과 같습니다.
- 목표가 없으면 `recommend`, `daily`, `analytics snapshot`, `nutrition status` 출력은 이전과 byte-identical입니다. Telegram
  코치는 `recommend --json`/`nutrition status --json`을 읽으므로 `goal_mode`/`goal_reference`(상대값과 단백질 g 범위)를 받습니다.

상세와 한계: `docs/training-goal-mode.md`, 유산소 가이드는 `docs/aerobic-guide.md`.

## Nutrition logging (MVP)

개인 음식 catalog에 직접 입력한 영양 정보(라벨/본인 입력)로 식사를 기록하고, 식사별·하루 섭취 kcal/단백질/탄수화물/
지방을 계산합니다. 외부 DB 조회나 이름 기반 추정은 하지 않습니다. 메뉴 추천과 CLI의 자유 문장 파싱은 없습니다(Telegram 자유 문장·사진은 아래 Telegram v2, 목표와
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
# 아직 값이 없는 단위(pack, count 등)의 첫 fact를 기존 단위 옆에 추가(다른 단위 fact는 그대로, 환산 없음)
muscle50 nutrition food fact add chicken-breast --per 1 pack `
  --kcal <kcal> --protein <g> --carbs <g> --fat <g> --source nutrition_label --accuracy exact --new-unit
muscle50 nutrition log --meal breakfast --item chicken-breast 200 g --item egg 2 count
# food ID 대신 음식 이름이나 alias를 정확히 써도 됨(공백이 있으면 따옴표). log/meal add-item/meal replace-item 공통
muscle50 nutrition log --meal lunch --item 닭가슴살 150 g --item 계란 1 count
# 메뉴·영양값을 모르는 일반식(영양값 unknown, 메모는 선택). --item과 섞을 수 있고 명령줄 순서대로 item이 됨
muscle50 nutrition log --meal lunch --general --general-note 구내식당
muscle50 nutrition log --meal dinner --general --item chicken-breast 100 g
# 일반식에 추정 범위만 붙이기(값은 비워 두고 estimated 범위만 저장. 합계는 계속 incomplete)
muscle50 nutrition log --meal dinner --general --general-note 제육볶음 `
  --general-estimate visual_estimate:kcal=700-950,protein=30-45
muscle50 nutrition day                      # 오늘 섭취량 (--date YYYY-MM-DD, --json)
# 이전 식사를 그대로 다시 기록(같은 음식/양/단위, 영양 값은 지금 catalog의 fact로 새로 snapshot)
muscle50 nutrition repeat 2026-10-02-breakfast-1                       # 오늘, 같은 식사 종류, 시간 없음
muscle50 nutrition repeat 2026-10-02-dinner-1 --meal lunch --time 12:30 --date 2026-10-03
# 이미 기록한 식사 고치기(meal ID 유지; 새 --additional 식사를 만들지 않음)
muscle50 nutrition meal show 2026-10-02-breakfast-1
muscle50 nutrition meal add-item 2026-10-02-breakfast-1 --item hetbahn-white-210 210 g
muscle50 nutrition meal remove-item 2026-10-02-breakfast-1 --item-number 3
muscle50 nutrition meal replace-item 2026-10-02-breakfast-1 --item-number 2 --item hetbahn-white-210 105 g
# 일반식 item을 추정값(과 메모)이 든 일반식으로 바꾸기. 옛 item과 옛 추정은 지워지지 않고 기록으로 남음
muscle50 nutrition meal replace-item 2026-10-02-dinner-1 --item-number 2 --general --general-note "삼각김밥 1개" `
  --general-estimate language_estimate:kcal=185-185,protein=5-5 --general-estimate-ref "직접 입력; 라벨"
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
`--general [--general-note TEXT]`은 "일반식을 먹었다"는 기록만 남깁니다(`log`/`meal add-item`/`meal replace-item` 공통,
여러 번 쓸 수 있고 메모는 그 `--general` 바로 뒤, 최대 100자 한 줄). `meal replace-item`에는 `--general-estimate SPEC`과
`--general-estimate-ref TEXT`도 있어(둘 다 선택, 각각 `--general`, `--general-estimate`가 있어야 함) 일반식 item의 추정 범위와
메모를 새 값으로 바꿉니다(옵션을 쓰지 않은 `replace-item` 출력은 그대로). 영양값을 추정하지 않으므로 일반식이 있는 날의 합계는
incomplete이고 부족 판단이나 행동 안내가 나오지 않습니다. `일반식`/`general-meal`은 예약 이름이라 `food add`로 만들 수
없습니다(migration 없음). 상세: `docs/nutrition-general-meal.md`.

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

목표 모드가 cut이면 `nutrition status` 끝에 `Cut goal reference` 줄이 붙습니다: 최근 InBody의 제지방량(체중 - 체지방량) 기준
감량기 단백질 범위(kg당 2.3~3.1 g, PRO-05)를 g/일로, 열량 결손 상한(하루 약 500 kcal, PRO-04)은 측정할 수 없다는 안내와 함께
보여 줍니다. 참고일 뿐 목표 값은 바꾸지 않으며, `--json`은 끝에 `goal_reference` key가 붙습니다. 목표 파일이 깨졌으면 이 부분만
"unavailable" 한 줄이 되고 status는 계속 나옵니다. maintain/gain이나 목표가 없으면 출력은 그대로입니다. 상세:
`docs/training-goal-mode.md`.

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

### InBody trend (read-only)

```powershell
muscle50 inbody trend                                       # 저장된 모든 측정
muscle50 inbody trend --from 2026-07-01 --to 2026-10-05     # 측정 날짜 기준 포함 범위
muscle50 inbody trend --json
```

저장된 InBody 측정을 시간순으로 보여 주고, 체중·골격근량(SMM)·체지방량·체지방률 4개 지표의 측정 사이 변화와 처음→마지막
변화, SMM 목표(1차 43 kg, 장기 50 kg)까지 남은 양, 마지막 측정 후 경과 일수를 표시합니다. DB를 읽기만 하고(migration 없음,
DB가 없으면 만들지 않음) 값은 0.1 단위로 반올림합니다. 없는 값은 0이 아니라 `unknown`입니다. 각 측정은 측정한 곳의 현지
날짜·시각으로 표시합니다. 같은 날짜에 값이 다른 행이 있으면 합치거나 고르지 않고 conflict로 보고하며 그 지표의 추세에서
뺍니다. 사용자가 직접 실행하는 명령이라 수치를 출력하며, `inbody sync`의 값 숨김 정책과 다른 명령의 출력은 그대로입니다.
상세: `docs/inbody-trend.md`.

## Telegram bot (v1.2, 명령어형)

휴대폰 Telegram에서 정해진 명령으로 muscle50을 씁니다. 각 bot 명령은 해당 CLI 명령을 같은 코드로 실행합니다.
`/today`, `/status`, `/daily`는 그 CLI의 JSON 결과로 만든 짧은 요약을 답하고, 뒤에 `full`을 붙이면 CLI text 전체를
그대로 답합니다. 나머지 명령은 CLI text 출력을 그대로 답합니다. 요약의 숫자와 상태는 JSON 값 그대로이고 CLI 출력은
바뀌지 않습니다. 이 절의 명령어형 bot에는 LLM, 서버, 예약 알림, 자동 refresh가 없습니다(자유 문장·사진은 아래 v2, 선택 기능). 이 PC에서 `telegram run`이 실행 중일
때만 답합니다.

설정 파일 `%LOCALAPPDATA%\muscle50\config\telegram.json`은 사용자가 직접 만듭니다(muscle50은 만들지 않음, repo에 두지
않음). BotFather로 bot을 만들고 내 chat id를 찾는 방법은 `docs/telegram-bot.md`를 참고하세요.

```json
{
  "bot_token": "<BotFather가 준 token>",
  "allowed_chat_ids": [123456789]
}
```

`allowed_chat_ids`의 숫자는 예시입니다. 본인 chat id(따옴표 없는 정수)를 넣으세요.

```powershell
muscle50 telegram check    # 설정·token 확인, bot 이름 표시. 메시지를 읽거나 답하지 않음
muscle50 telegram run      # long polling 시작. Ctrl+C로 종료(exit 130)
```

| bot 명령 | 실행되는 CLI 명령 |
|---|---|
| `/today [full]` | `recommend --date <오늘>` (기본은 요약, `full`은 CLI text) |
| `/status [full]` | `nutrition status` (기본은 요약, `full`은 CLI text) |
| `/day [YYYY-MM-DD]` | `nutrition day [--date ...]` |
| `/log <meal>[+] <food> <qty> <unit>[, ...]` | `nutrition log --meal <meal> --item ... [--additional]` (`+`는 `--additional`) |
| `/log <meal>[+] 일반식 [메모][, ...]` | `nutrition log --meal <meal> --general [--general-note=<메모>] ...` (메뉴·영양값을 모르는 식사. 카탈로그 음식과 쉼표로 섞음. `일반식 1 serving`처럼 수량·단위를 붙이면 거부) |
| `/void <meal_id> [이유]` | `nutrition meal void <meal_id> [--reason ...]` |
| `/show <meal_id>` | `nutrition meal show <meal_id>` |
| `/inbody` | `inbody trend` |
| `/daily [full]` | `daily` (Garmin 동기화 포함, 진행 답을 먼저 보냄. 기본은 요약, `full`은 CLI text. 이어 받았으면 `이어 받기: 10-14부터 ...` 줄, 7일보다 오래 빠진 날이 남으면 `/sync 10-09 10-13` 안내) |
| `/sync <시작> <끝>` | `garmin sync --from ... --to ... --json` (날짜는 `YYYY-MM-DD` 또는 `MM-DD`(올해), 끝은 오늘까지, 최대 31일. 운동·load metric·회복만 받고 추천은 만들지 않음. 진행 답을 먼저 보내고 짧은 요약을 답함. 7일을 넘으면 바로 실행하지 않고 요청 수와 `/sync_ok_<id>`를 답하며, 같은 chat에서 10분 안에 한 번만 누를 수 있음(bot 메모리에만 있어 재시작하면 사라짐)) |
| `/unknown` | `recommend --date <오늘>`의 UNKNOWN notice (최근 14일, 오늘 운동 제외. 운동마다 Garmin Connect 링크와 `/refresh <id>`, 목록 끝에 `모두 다시 받기: /refresh`) |
| `/refresh` | UNKNOWN 운동 모두 다시 받기, 한 번에 10개 (`/unknown` 목록을 차례로 `garmin refresh`. 진행 답을 먼저 보내고, 운동마다 전후 UNKNOWN 세트 수와 남은 UNKNOWN 운동 수를 답함) |
| `/refresh <activity_id>` | `garmin refresh <activity_id>` (진행 답을 먼저 보내고, 전후 UNKNOWN 세트 수를 답함) |
| `/help`, `/start` | 명령 목록 |

`allowed_chat_ids`에 없는 chat의 메시지에는 답하지 않고 콘솔에 chat id 한 줄만 남깁니다. 개인 chat id만 넣으세요.
token은 콘솔, 오류, 답장 어디에도 출력하지 않습니다. 처리한 update는 `config\telegram_state.json`에 기록해 재시작 뒤에도
다시 실행하지 않고(`/log` 중복 방지), bot이 시작되기 전에 보낸 메시지는 실행하지 않습니다. 적용하지 않은 migration이
있으면 bot은 migration을 적용하지 않고 `/status`, `/day`, `/show`, `/log`, `/void`, `/daily`, `/sync`, `/refresh`를 거부합니다(터미널에서 백업 후 적용하고
`telegram run`을 다시 시작). bot이 직접 쓰는 문구(`/help`, 사용법, `취소: /void <meal_id>` 줄 등)는 한국어입니다.
상세와 한계: `docs/telegram-bot.md`.

### Telegram v2: 자유 문장, 사진, 코치 (선택)

명령어 대신 자유 문장과 사진으로 식사를 기록하고, 운동·영양·InBody 질문에 코치 말투로 답받습니다. 이 PC에 설치된 공식
CLI(`claude -p` 또는 `codex exec`)를 본인 구독으로 실행하며 API 키는 쓰지 않습니다. **`config\telegram_llm.json`을 직접
만들어야 켜지고, 없으면 bot은 위 v1.2와 byte 단위로 같습니다.** `{}`이면 기본값입니다: (v2.5) provider `codex`(모델
`gpt-6.1-sol`), 대체 제공자 꺼짐, 사용 한도 때만 Claude로 한 번 넘기기 켜짐(`fallback_on_usage_limit`). Claude로 쓰려면
`"provider": "claude"`를 적거나 `/llm claude`로 바꿉니다.

```json
{"provider": "codex", "timeout_seconds": 90, "fallback_provider": null, "fallback_on_usage_limit": true}
```

- 식사 문장·음식 사진·구내식당 메뉴 캡처는 먼저 **제안**으로 답하고, `/ok`로 확인하기 전에는 DB가 바뀌지 않습니다.
  확인하면 `nutrition log`/`meal ...` 명령과 같은 코드로 저장합니다(한 번만, 유효 시간 안에서만).
- 카탈로그에 없거나 모호한 음식은 이름만으로 연결하지 않고 일반식+메모로 제안합니다. 사진·문장 추정값은 `estimated` 범위로만
  저장되고(`--general-estimate`), 합계는 계속 incomplete이며 모르는 값을 0으로 쓰지 않습니다.
- (v2.2) **한 메시지에 여러 끼니**("아침 ... 점심 ... 저녁 ...")를 쓰면 끼니별로 나눈 제안 하나를 보여 주고 `/ok` 한 번에
  모두 기록합니다. 일반식 item에는 항상 kcal·단백질 **추정 범위**가 붙고(있으면 양 기준), "햇반"처럼 이름이 조금 달라도
  LLM이 고른 카탈로그 음식은 이름을 보여 주어 `/ok`로 확인하게 합니다(그 이름·별칭·단위 목록이 제공자로 전송됩니다).
- (v2.2) 상표·식당·제품 이름이 든 item은 Claude가 **웹 검색**으로 찾아보고 근거와 가정을 답장에 보여 줍니다. 기본 켜짐이고
  `config\telegram_llm.json`에서 `web_search`(기본 true), `web_search_max`(메시지당 검색 횟수, 기본 3),
  `web_search_timeout_seconds`(기본 150)로 조절하며, Claude만 검색합니다(Codex는 검색하지 않음). 검색은 응답 시간과 구독
  사용량을 늘리므로 끄려면 `"web_search": false`입니다. 제공자가 Codex일 때의 검색은 아래 v2.5를 보세요.
- (v2.2) 추정 숫자는 kcal·단백질·탄수·지방 사이의 관계와 가정에 적힌 숫자로 한 번 **재확인**합니다. 맞지 않으면 같은 제공자에
  **한 번만** 다시 묻고, 그래도 맞지 않으면 그 item에 "(값 확인 필요)"를 붙여 보여 줍니다.
- (v2.3) **방금 기록한 식사 고치기**: "삼각김밥 지방 2g이네", "아침 1식 닭가슴살 2팩으로 바꿔줘"처럼 말하면 새 식사를 만들지
  않고 기존 식사를 고치는 **제안**을 보여 주며, `/ok` 뒤에만 고쳐집니다. "방금 거"는 이 chat의 마지막으로 기록한 식사
  둘 중 하나로 정해지고(둘 다 맞거나 아무것도 안 맞으면 후보만 보여 주고 쓰지 않음), "아침 1식"은 그날 아침의 첫 기록입니다.
  일반식 item은 메모로 찾고(모호하면 후보만) 추정 범위와 메모를 고칠 수 있습니다. 아직 `/ok` 전인 제안을 고치는 말은 새
  제안을 만들고 이전 제안은 취소합니다.
- (v2.3) **같은 끼니에 같은 음식**을 또 말하면 하나 더 기록하지 않고 `/fix_<토큰>`(기존 식사 고치기. 기록한 값이 제안 값으로
  바뀌며 두 값을 보여 준 뒤 `/ok`), `/ok_<토큰>`(하나 더 기록), `/no_<토큰>`(취소)를 고르게 합니다. 겹치지 않는 다른 음식은
  이전처럼 하나 더 기록하되 그 사실을 제안 맨 위에 적습니다. 최근 메뉴 캡처·제안에 있는 항목은 이름으로 말해 고를 수
  있습니다("위 사진에 있는 ○○ 먹었어").
- (v2.3) 영양정보 **라벨**에서 읽은 값은 한 값이어도 재확인하지 않고 `라벨: kcal 185, 단백질 5 g`으로 보입니다. 양을 말하지
  않은 일반식은 가정한 무게를 재료별 그램으로 보여 줍니다(`양 가정: 닭 150~200 g, 감자 100~150 g`).
- (v2.3) **누적**은 영양소마다 하나의 범위입니다(`kcal 600~620`, 추정이 없으면 한 숫자). 값을 모르는 항목은 0으로 더하지
  않고 `값 모르는 항목 N개 빠짐`으로 적습니다. 어제 같은 다른 날을 기록하면 그날의 누적(`10-14 누적`)을 보여 줍니다. 숫자는
  CLI와 같은 반올림입니다(1.95 g는 2 g). 범위를 근거로 한 부족·초과 판단은 하지 않습니다.
- (v2.4) **사진 여러 장(앨범)**: 같은 앨범으로 보낸 사진은 잠깐(최대 6초) 모아 최대 4장까지 한 번에 읽습니다. 캡션은 앨범 전체에
  쓰이고, 못 읽었거나 4장을 넘은 사진이 있으면 `사진 5장 중 4장만 읽었습니다`라고 알립니다. 사진을 해석하지 못했을 때는
  캡션에 "먹었" 같은 말이 있고 "메뉴"가 없을 때만 값 없는 일반식 기록을 제안하고, 아니면 아무것도 쓰지 않고 캡션을 적어 다시
  보내 달라고 합니다. 보낸 사진은 대화 기억에도 `[사진 2장] 점심 → 메뉴 캡처로 읽음`처럼 남아(`/memory`로 보임) 코치가 "사진이
  없다"고 답하지 않습니다.
- (v2.4) **bot이 계속 돕니다**: 메시지 하나를 처리하다 예상 못 한 오류가 나도 기록하고 다음 메시지로 넘어가며, 연속 5번 나면
  멈춥니다. 상태 파일 저장이 Windows에서 잠깐 막혀도 몇 번 다시 시도합니다. 콘솔 줄은 `telegram\run-YYYY-MM.log`에도 남습니다
  (시작, 멈춘 이유, 30분마다 `alive`, 창 닫힘 이벤트. 메시지 원문과 token은 넣지 않음. LLM이 꺼져 있어도 만들어지며 muscle50은
  이 파일을 지우지 않음). 네트워크 오류는 `WinError 10054 connection reset by remote host`처럼 번호와 짧은 영어 설명으로 보입니다.
- (v2.4) **메뉴 제안은 4시간** 유효합니다(식사 기록·수정 제안은 60분 그대로). `/ok`로 기록·수정·void하면 CLI 영어 출력 대신
  **짧은 한국어 요약**(기록한 item, 이 끼니와 오늘 누적, 취소 명령)을 보내고, 자세한 내용은 `/show <meal id>`로 봅니다. 요약을
  만들지 못하면 CLI 출력을 그대로 보냅니다. "동기화 해줘"는 아무것도 실행하지 않고 누를 수 있는 `/daily`(전체 동기화)와
  `/refresh`(UNKNOWN 운동 다시 받기)를 안내합니다. 다음 `daily`가 받지 않을 빠진 날(7일보다 오래됨)이 남아 있으면
  `받기: /sync 10-09 10-13` 줄을 하나 더 붙입니다.
- (v2.4) 개발: 모든 테스트는 실제 muscle50 홈(`%LOCALAPPDATA%\muscle50`)을 건드리지 않도록 임시 폴더로 격리됩니다.
- (v2.5) **실패하면 이유와 할 일**을 알려 줍니다: 인터넷 연결, 사용 한도, 로그인 필요, 시간 초과, 실행 파일 없음(그 밖은 v2.4
  문구). 답장에 누를 수 있는 `/retry_<토큰>`(60분 유효, 한 번만)이 붙고, 누르면 그 메시지(사진은 같은 사진)를 처음 받은 것처럼
  다시 처리합니다(날짜·끼니는 처음 받은 시각 기준, `/ok` 전에는 아무것도 쓰지 않음). CLI 오류 원문은 어디에도 남기지 않고 이유만
  `telegram history`에 `reason=network`처럼 남깁니다. 사용 한도에 걸리면 다른 제공자로 한 번 넘기고 답장에 그 사실을 적습니다
  (끄려면 `"fallback_on_usage_limit": false`).
- (v2.5) **기존 끼니에 더하기**: "아침은 하나에 같이 기록해줘"처럼 말하고 그날 그 끼니 기록이 하나뿐이면 새 끼니 대신
  `기존 아침 2026-10-16-breakfast-1(...)에 추가할까요?`를 제안합니다(`/ok` 뒤에도 끼니 ID 그대로, `/new_<토큰>`은 따로 새 끼니).
  그런 말이 없어도 같은 끼니가 하나 있으면 `기존 아침에 추가: /add_<토큰>`이 붙습니다. `/ok` 때 그 끼니가 없거나 void되었으면
  `오류:`이고 아무것도 쓰지 않습니다. 열린 제안을 고치는 말은 앞선 고치기 요청을 함께 넘겨 이전 수정이 유지됩니다.
- (v2.5) **웹 검색은 Claude로만**: 제공자가 Codex면 먼저 검색 없이 읽고, 상표·식당·포장 제품처럼 검색이 값을 크게 바꿀 item이
  있다고 모델이 표시한 식사 기록만 Claude가 웹 검색으로 한 번 더 읽어 그 답을 씁니다(`웹 검색 2회 (Claude)`). 이런 메시지는 호출이
  둘이라 더 늦고 Claude 사용량도 쓰며, 메시지·사진이 OpenAI와 Anthropic 둘 다로 갑니다. Claude 검색이 실패하면 Codex 답에
  `(웹 검색은 하지 못했습니다: 사용 한도)`처럼 붙입니다. `"web_search": false`면 하지 않습니다.
- (v2.5) 코치가 bot 명령 목록과 최근 14일 동기화 상태를 압니다. "동기화 명령어 뭐야?"에는 누를 수 있는 명령으로 답하고, 운동·회복
  질문에서 "기록 없음"과 "동기화 안 됨"(예: `10-09~10-18`)을 구분해 `/daily`를 안내합니다. 그 날 뒤에 동기화된 날이 있거나
  7일보다 오래된 날(다음 `daily`가 받지 않는 날)은 `/sync <시작> <끝>`을 안내합니다(프롬프트 규칙이라 틀릴 수 있음).
- 질문 답은 muscle50 결과 JSON에 있는 숫자만 쓸 수 있고, 다른 숫자가 섞이면 보내지 않고 기존 명령 답장을 보냅니다.
- `/llm`(제공자 확인·변경), `/memory`(다음 호출에 넘어갈 기억), `/forget`(이 chat의 기억 삭제, 기록은 남음),
  `/history [N|YYYY-MM-DD]`(대화 기록). PC에서는 `muscle50 telegram history [--last N | --date YYYY-MM-DD] [--json]`
  (읽기 전용).
- 메시지 종류별로 모델을 고릅니다(제공자 설정의 `model`=글, `photo_model`=사진, `retry_model`=형식 실패 뒤 재시도). 기본값은
  Claude `haiku`(글) / `sonnet`(사진) / `sonnet`(재시도), Codex `gpt-6.1-sol`(글) / `gpt-6.1-sol`(사진) / 재시도 없음입니다
  (v2.5. 모델 이름은 바뀔 수 있으니 `telegram_llm.json`에서 고칩니다). 식사 제안이 열려 있는 동안의 글은 `retry_model`로 돕니다. 재시도는
  답이 형식 검사를 통과하지 못했을 때 **한 번만** 하고, 시간 초과·로그인 문제나 내용이 틀린 답은 재시도하지 않습니다.
  `/llm`과 `/history`가 실제로 답한 모델과 재시도 여부를 보여 줍니다.
- 메시지와 사진은 고른 제공자(Anthropic 또는 OpenAI)로 전송되고, 사용 한도 대체나 Claude 웹 검색 때는 다른 회사로도 갑니다.
  Codex는 사용자 전역 `~/.codex/AGENTS.md`를 읽는 알려진 한계가 있고, 기본이 Codex가 되면서 이 위험이 모든 메시지에 해당하는
  것을 사용자가 2026-10-21에 받아들였습니다(피하려면 `"provider": "claude"`). 구독 사용량을 쓰고 응답에 수 초~수십 초가 걸립니다.

설정 key, 코치 가이드, 격리 방식, 파일·개인정보, 알려진 한계: [`docs/telegram-llm.md`](docs/telegram-llm.md).
