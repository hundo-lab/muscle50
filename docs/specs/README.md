# Feature specs: 스펙 1개 → `/feature` 1회

기능마다 프롬프트를 새로 쓰는 대신, 스펙 파일 하나를 쓰고 Claude Code에서 `/feature <스펙 경로>`를 실행한다.
설계, 구현, 검증, 통합은 정해진 에이전트와 skill이 같은 규칙으로 진행하고, 사람은 네 개의 게이트에서만 결정한다.

## 1. 스펙 작성

1. `docs/specs/_TEMPLATE.md`를 `docs/specs/<id>.md`로 복사한다. `id`는 kebab-case로 쓰며 branch `feature/<id>`가 된다.
2. frontmatter는 `status: draft`, `migration: none`으로 둔다. migration 번호는 직접 쓰지 않는다.
3. 본문 6개 절을 채운다: 목적 / 범위·Non-goals / 명령 예시(text, `--json`) / 규칙 / 인수 조건 / 한계·후속 후보.
   인수 조건은 verifier가 하나씩 대조하므로 테스트나 smoke로 확인할 수 있게 쓴다.
4. (권장) 스펙을 main에 커밋해 둔다(`docs: add spec <id>`). `/feature`는 진행 상태를 같은 파일의 frontmatter에 기록한다.

## 2. 실행

main checkout에서 실행한다.

```text
/feature docs/specs/<id>.md
```

| 단계 | 누가 | 무엇을 | 산출물 |
|---|---|---|---|
| 1 | 오케스트레이터 | 스펙과 status 확인 | — |
| 2 | 오케스트레이터 | migration이 필요하면 다음 번호를 예약(main의 migrations, 모든 local branch, 다른 스펙의 `reserved:`) | frontmatter `migration: reserved:NNN` |
| 3 | `designer` | 구현 계획(모호하면 대안 2~3개) | 계획 → **게이트 1: 사람 승인** |
| 4 | 오케스트레이터 → `implementer` | Paseo worktree `feature/<id>` 생성 후 구현(코드, 테스트, `docs/<feature>.md`), 게이트, mutation check, 커밋 | feature 커밋 |
| 5 | `verifier` | 별도 컨텍스트에서 게이트(check-only), 인수 조건 대조, 임시 `MUSCLE50_HOME` smoke | PASS/REJECT. REJECT면 4로 돌아간다(최대 3회, 넘으면 멈춤). |
| 6 | `integrator` | ff-only로 local main 통합, main에서 게이트 재실행, CURRENT_STATE/HANDOFF/README 갱신 | `docs: record ... integration` 커밋 |
| 7 | 오케스트레이터 | status `integrated`, 남은 사람 게이트 목록 보고 | 보고 |

## 3. 사람 게이트

| 게이트 | 언제 | 사람이 하는 일 |
|---|---|---|
| 1. 설계 승인 | 3단계 후 `/feature`가 멈춤 | 승인 / 수정 후 승인 / 대안 선택 / 거절 |
| 2. production migration | 통합 후, 스펙에 `reserved:NNN`이 있을 때 | 백업 → 쓰기 명령 1회로 적용 → 검증(`.claude/skills/add-migration` 6절) |
| 3. live Garmin 검증 | Garmin sync를 바꾼 기능 | 실제 계정으로 명령 실행(MFA는 대화형) |
| 4. push | 마지막 | `git push origin main`을 사용자가 직접 실행. 에이전트는 hook으로 차단된다. |

## 4. 규칙 요약

- 상태 문서(`docs/CURRENT_STATE.md`, `docs/HANDOFF.md`, `README.md`)는 integrator만 수정한다.
- migration 번호는 오케스트레이터만 할당한다. `INSERT OR IGNORE` 마커 때문에 번호가 중복돼도 조용히 무시되기 때문이다(006 충돌 사례).
- 데이터·출력 원칙은 `.claude/skills/domain-principles`에 출처와 함께 정리돼 있다.
- 개발 중 production(`%LOCALAPPDATA%\muscle50`)은 건드리지 않는다. `muscle50` CLI는 임시 `MUSCLE50_HOME`에서만 실행한다(hook으로 강제).
- 중단된 실행은 `/feature`를 다시 실행하면 status(`in-progress`/`verified`)를 보고 이어갈 단계를 묻는다.
