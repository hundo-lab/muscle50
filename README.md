# muscle50

Windows 로컬 환경에서 개인 운동 데이터를 관리하는 도구입니다. 현재 MVP는 Garmin Connect의
가장 최근 activity 한 건을 RAW 파일과 normalized SQLite 데이터로 보존합니다.

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
└─ db\muscle50.sqlite3          # normalized activity와 correction overlay
```

`MUSCLE50_HOME` 환경 변수로 데이터 위치를 바꿀 수 있지만 Git worktree 내부 경로는 안전을
위해 거부합니다. Garmin 이메일·비밀번호를 CLI 인자나 환경 변수로 받지 않습니다.

동일한 최신 activity를 다시 실행하면 Garmin activity ID의 database unique constraint를
기준으로 중복 저장하지 않고 기존 normalized 데이터를 요약합니다.

## 개발 검증

```powershell
pytest
ruff check .
mypy src
```

테스트 데이터는 실제 계정에서 수집하지 않은 합성 fixture만 사용합니다.
