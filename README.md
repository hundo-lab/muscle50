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
├─ raw\garmin\activities\      # immutable JSON 및 가능한 경우 original.zip
├─ raw\garmin\recovery\        # 날짜별 immutable recovery snapshot history
└─ db\muscle50.sqlite3          # normalized activity/recovery, nutrition, correction
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

## 기간별 Garmin activity 동기화

```powershell
muscle50 garmin activities --from 2026-01-01 --to 2026-01-31
```

`--from`/`--to`는 포함 범위의 local 날짜(YYYY-MM-DD)이며 잘못된 날짜/범위는 로그인이나
네트워크 호출 전에 거부합니다. `garmin latest`와 동일한 RAW 저장·normalization·persistence
경로를 activity마다 그대로 재사용하므로 웨이트 세트, 수영 lap/length 정규화도 동일하게
적용됩니다. 이미 저장된 activity는 다시 가져오지 않고 건너뛰며, 한 activity가 실패해도 나머지
activity는 계속 처리됩니다. 실행할 때마다 발견/신규 저장/이미 저장됨/실패 건수를 요약해서
보여줍니다.

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

## 개발 검증

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src tests
```

테스트 데이터는 실제 계정에서 수집하지 않은 합성 fixture만 사용합니다.
