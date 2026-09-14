# Current State

Last updated: 2026-09-13

## Project goal

muscle50는 개인 fitness 데이터를 로컬에 보존하고 RAW → NORMALIZED → DERIVED → REPORT
흐름으로 처리하는 Windows용 Python 프로젝트다.

## Current architecture

- Python 3.12 패키지와 `muscle50` CLI를 사용한다.
- 개인정보, Garmin token, RAW 파일, SQLite DB는 기본적으로
  `%LOCALAPPDATA%\muscle50`에 저장한다.
- Garmin Activity Sync는 immutable RAW artifact와 normalized SQLite activity를 분리한다.
- SQLite schema는 package에 포함된 numbered migration을 순서대로 적용한다.
- Garmin source 값과 corrected/derived 값은 서로 덮어쓰지 않는다.

## Implemented

- 최신 Garmin activity 1건 동기화 및 activity ID 기반 idempotency
- Garmin RAW JSON/original archive 보존과 normalized activity 저장
- 러닝, 수영, 웨이트 등 기본 activity 요약
- Garmin strength exercise set 정규화, SQLite 저장 및 기존 RAW 기반 local backfill
- Garmin 수영 activity/lap/length 정규화와 Garmin/corrected 거리 분리

## Not integrated

- `feature/nutrition-core`: 기능 commit은 있으나 worktree에 미커밋 문서가 남아 있음
- `feature/inbody-connector`: 기능 구현 전체가 미커밋 상태
- `feature/garmin-recovery`: 기능 구현 전체와 provisional migration 2가 미커밋 상태

이 branch들은 원본 worktree에서 먼저 commit/정리된 뒤 별도 integration이 필요하다.

## Verification

2026-09-13 integration에서 실행:

```powershell
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run mypy src
git diff --check
```

결과: 55 tests passed, Ruff 통과, mypy 통과, diff-check 통과.

## SQLite migrations

1. `001_initial.sql` — Garmin activity/RAW/correction 기본 schema
2. `002_strength_sets.sql` — normalized Garmin strength sets

두 migration을 새 임시 DB에 두 번 적용하는 smoke check에서 version `(1, 2)`와 예상
테이블을 확인했다.

## Known issues

- Garmin Connect 연동은 비공식 API이므로 인증 및 응답 shape 변경 위험이 있다.
- 실제 Garmin 계정/개인 데이터 기반 smoke test는 자동 검증에 포함하지 않는다.
- 아직 통합되지 않은 feature들의 provisional schema/migration 번호를 이후 재조정해야 한다.

## Important decisions

- 미커밋 feature worktree는 integration agent가 대신 commit하거나 추정해 통합하지 않는다.
- `feature/strength-sets`를 migration 2로 먼저 통합하고, migration이 없는
  `feature/swim-details`를 그다음 통합했다.
- 원본 feature branch와 Paseo worktree는 삭제하거나 수정하지 않는다.
