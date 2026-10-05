# Feature specs: 스펙 → `/feature` (병렬)

기능마다 프롬프트를 새로 쓰는 대신, 스펙 파일을 쓰고 Claude Code에서 `/feature <스펙> [<스펙> ...]`을 실행한다.
여러 스펙은 한 번에 병렬로 진행된다(여러 세션에서 동시에 실행해도 된다). 설계, 구현, 검증, 통합은 정해진 에이전트와
skill이 같은 규칙으로 처리하고, 사람은 다섯 개의 게이트에서만 결정한다.

## 1. 스펙 작성

1. `docs/specs/_TEMPLATE.md`를 `docs/specs/<id>.md`로 복사한다. `id`는 kebab-case로 쓰고, 이것이 branch `feature/<id>`가 된다.
2. frontmatter는 `status: draft`, `migration: none` 그대로 둔다. 진행 상태와 migration 번호는 `/feature`가 관리한다.
3. 본문 6개 절을 채운다: 목적 / 범위·Non-goals / 명령 예시(text, `--json`) / 규칙 / 인수 조건 / 한계·후속 후보.
   인수 조건은 verifier가 하나씩 대조하므로, 테스트나 smoke로 확인할 수 있게 쓴다.
4. 커밋은 하지 않아도 된다. 설계가 승인되면 오케스트레이터가 `docs: add spec <id>`로 main에 커밋한 뒤 branch를 만든다.

## 2. 실행

main checkout에서 실행한다.

```text
/feature docs/specs/a.md docs/specs/b.md
```

| 단계 | 누가 | 무엇을 | 병렬 |
|---|---|---|---|
| 1 | 오케스트레이터 | 스펙 확인, 진행 상태(`feature_state.py`) 확인. 중단된 실행은 이어서 진행 | — |
| 2 | `designer` | 구현 계획 작성(모호하면 대안 2~3개). migration이 필요하면 오케스트레이터가 번호를 원자적으로 예약 | 스펙마다 동시 |
| — | **게이트 1: 설계 승인** | 계획을 한꺼번에 보여 주고 기능별로 승인받음 | 일괄 |
| 3 | 오케스트레이터 → `implementer` | 스펙을 main에 커밋 → Paseo worktree `feature/<id>` 생성 → 구현, 게이트, mutation check, 커밋 | 기능마다 동시 |
| 4 | `verifier` | 별도 컨텍스트에서 게이트(check-only), 인수 조건 대조, 임시 `MUSCLE50_HOME` smoke. 반려되면 3으로(최대 3회) | 기능마다 동시 |
| — | **게이트 2: 통합 승인** | 변경 요약, 게이트 결과, 인수 조건 표를 보고 통합 여부를 결정 | 일괄 |
| 5 | `integrator` | lock → 최신 local main 위로 rebase → 게이트 재실행 → README·스펙 frontmatter 커밋 → `merge --ff-only` → unlock | **한 번에 하나** |
| 6 | 오케스트레이터 | 남은 사람 게이트를 목록으로 보고 | — |

rebase에서 충돌이 나면(다른 기능이 같은 곳을 먼저 바꾼 경우) implementer가 두 기능의 동작을 모두 살려 해결한다.
내용이 바뀌었으므로 verifier 검증과 게이트 2를 다시 거친다.

## 3. 사람 게이트

| 게이트 | 언제 | 사람이 하는 일 |
|---|---|---|
| 1. 설계 승인 | 계획이 나온 뒤, branch와 코드가 생기기 전 | 승인 / 수정 후 승인 / 대안 선택 / 거절 |
| 2. 통합 승인 | verifier PASS 뒤, local main에 들어가기 전 | 통합 / 보류 / 의견을 달아 되돌림 |
| 3. production migration | 통합된 기능에 migration이 있을 때 | 백업 → 적용 → 검증(`.claude/skills/add-migration` 6절). 적용 전까지 hook이 production 실행을 막는다. |
| 4. live Garmin 검증 | Garmin sync를 바꾼 기능 | 실제 계정으로 확인할지 결정(main에서 Claude가 실행해도 됨) |
| 5. push | 마지막 | `git push origin main`을 사용자가 직접 실행 |

## 4. 기록 위치

- `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`는 2026-10-05 기준으로 동결된 이력이다. 더 이상 갱신하지 않는다.
- 이후의 기록은 다음에 남는다.
  - 통합된 스펙(`status: integrated`, 한계·후속 후보 포함)
  - 기능 문서 `docs/<feature>.md`(Known issues 포함)
  - `README.md`
  - 통합 커밋 메시지(게이트 수치 포함)
- 진행 중 상태(예약된 migration, 상태, 승인된 계획, 통합 lock)는 `.git/muscle50-orchestration/`에 있다.
  커밋되지 않고 모든 worktree가 공유한다. 확인 명령: `python .claude/scripts/feature_state.py list`.
