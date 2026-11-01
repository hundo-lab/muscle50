---
id: telegram-goal-summary-compact
title: Telegram Goal Summary - compact evidence marks v1.1
status: integrated
migration: none
output_change: changed
user_gates: [design, integration]
---

# Telegram Goal Summary - compact evidence marks v1.1

## 목적

- Telegram Goal Summary v1(`docs/specs/telegram-goal-summary.md`)의 `/daily` 목표 줄은 줄마다 CLI와 같은 근거 표시를 붙인다
  (`[design: user setting]`, `[design: fat-free mass assumed constant]`, `[EXL-03; design]` 등). 휴대폰 화면에서는 이 표시가
  줄 길이의 큰 부분이라 줄이 접힌다.
- 사용자 요청(2026-11-01, 실제 `/daily`를 본 뒤): "후속 수정으로 해줘". 오케스트레이터가 제안한 두 방법(근거 표시를 짧게 / `full`에만)
  중 **근거 ID는 그대로 보이고 `design…` 문구만 짧게** 하는 쪽으로 정했다. 사용자 원칙(모든 규칙에 근거 ID)과 v1 AC7을 지키기 위해서다.
- 근거 문서 `docs/evidence/training-nutrition-evidence.md`는 바꾸지 않는다.

## 범위 / Non-goals

- 범위(Telegram `/daily` 요약의 목표 줄만):
  1. 근거 ID(`EXL-03`, `PLAT-06` 등)는 줄마다 지금처럼 `[...]` 안에 그대로 남긴다. ID 순서와 줄과 ID의 짝도 그대로다.
  2. `design` 계열 문구를 짧은 기호로 바꾼다.
     - `[design: user setting]` -> `(내 설정)`. 줄에 이미 `(내 설정)`이 있으면 한 번만 쓴다.
     - `[design]` 단독 -> `*`
     - ID와 함께인 `design`(예: `[EXL-03; design]`, `[REST-07, design]`, `[design: user setting; PLAT-01, PLAT-02]`) -> ID만 남기고
       `*` 또는 `(내 설정)`를 붙인다(예: `[EXL-03]*`, `(내 설정) [PLAT-01, PLAT-02]`).
     - `[design: <설명>]`(예: `fat-free mass assumed constant`) -> `*` 와 짧은 한국어 설명 한 번(예: `* 제지방 일정 가정`). 설명 문구는 설계에서 정한다.
     - `[RUNPROG-03: 관찰 연구의 연관, 알림만]` -> `[RUNPROG-03] 알림만`처럼 ID와 뜻이 남게 줄인다.
  3. 목표 블록 끝에 범례 한 줄을 둔다: 예 `* 근거 수치 없는 설계값 · [ID] 근거 문서 항목 · (내 설정) 직접 정한 값`.
  4. `docs/telegram-goal-summary.md`의 줄 표와 예시를 바꾼다.
- Non-goals:
  - CLI(`recommend`/`daily` text·JSON), `/today`, `full` 답장, 코치 입력은 바꾸지 않는다(byte-identical).
  - 영어 `reason` 문구의 번역·축약은 하지 않는다(v1 D3: 그대로 복사, 추측 금지). 후속 후보로 남긴다.
  - 줄의 내용, 상태별 문구, 선택지 순서·내용, fallback 규칙은 바꾸지 않는다.

## 규칙

- 근거 ID는 하나도 빠지거나 옮겨 가지 않는다. 기호는 표시만 짧게 할 뿐 뜻을 바꾸지 않는다(`*`는 늘 "근거 수치 없는 설계값").
- 결정적 출력. 목표 파일이 없거나 `daily`가 실패하면 답장은 지금과 byte-identical.

## 인수 조건

- [x] AC1: v1의 모든 상태 줄에서 v1이 붙이던 근거 ID 집합이 줄마다 그대로 남는다(테스트가 v1 표시에서 ID를 뽑아 비교).
  `test_every_line_keeps_the_v1_evidence_ids_in_order`(상태마다 parametrize, 순서까지 비교),
  `test_the_whole_cut_block_keeps_the_v1_ids_line_by_line`.
- [x] AC2: `design` 문자열이 목표 블록에 남지 않고, v1의 `design` 표시는 규칙 2대로 `*` 또는 `(내 설정)`이 된다.
  `test_no_design_text_and_one_legend_at_the_end_of_every_block`.
- [x] AC3: 범례 줄이 목표 블록 끝에 한 번 나온다. 같은 테스트.
- [x] AC4: 실제 cut 시나리오에서 목표 블록 전체 글자 수가 v1보다 줄어든다(수치 고정). 1104 -> 1013자,
  `test_the_cut_block_is_shorter_than_v1`.
- [x] AC5: 목표 없음, 실패한 daily, `/today`, `full`, CLI 출력, 코치 입력은 byte-identical. 목표 없음·실패·`/today`는 테스트로,
  `full`·CLI·코치 입력은 구조로 확인했다(`src/` 변경은 `presentation/telegram_summary.py`의 목표 줄뿐). 검증 smoke에서 main과
  branch의 `recommend` text·`--json`, `/today`, 실패한 daily가 byte-identical이었다.
- [x] AC6: v1의 나머지 인수 조건(상태 문구, 선택지 순위 없음, 150/300 금지어, 측정 kg 없음, fallback)은 그대로 통과한다.
- [x] AC7: 품질 게이트 4개가 통과한다.

## 구현 결과

- 표시 바꾸기(전체 표는 `docs/telegram-goal-summary.md` "근거 표시 (v1.1)"):
  - `[design: user setting]` -> `(내 설정)`, 줄에 정확히 `(내 설정)`이 이미 있으면 한 번만.
  - `[design: user setting; PLAT-01, PLAT-02]` -> `(내 설정) [PLAT-01, PLAT-02]`.
  - `[design]` -> `*`, `[MAINT-05; design]`·`[EXL-03; design]`·`[design; PLAT-01]` -> `[ID]*`.
  - JSON 근거 목록의 `design`(예: `[FATEX-02, design]`) -> `[FATEX-02]*`.
  - `[design: fat-free mass assumed constant]` -> `* 제지방 일정 가정`.
  - `[RUNPROG-03: 관찰 연구의 연관, 알림만]` -> `[RUNPROG-03] 알림만`.
  - 범례: `* 근거 수치 없는 설계값 · [ID] 근거 문서 항목 · (내 설정) 직접 정한 값`.
- 해석(검증에서 승인): 정체 머리줄은 `정체 확인: 조건 충족 (내 설정 3주, ...) (내 설정) [PLAT-01, PLAT-02]`로 `내 설정`이 두 번
  보인다. 중복 규칙은 표시 `(내 설정)` 자체에만 적용하고 `(내 설정 3주, ...`는 줄 내용이라 그대로 둔다. 범위 2의 예시를 글자 그대로
  따른 결과이고, 반대로 하면 이 v1 `design` 표시가 `*`도 `(내 설정)`도 아니게 되어 AC2와 어긋난다.

## 한계 / 후속 후보

- 영어 이유 문구(예: InBody 측정 부족)는 여전히 길다. 번역 표는 CLI 문구가 바뀌면 깨질 수 있어 따로 정한다.
- 목표 블록은 약 8 %만 짧아졌다(cut 1104 -> 1013자). 길이 대부분은 줄 내용과 영어 이유 문구라 표시만으로는 더 줄지 않는다.
- 후속 후보: 정체 선택지 a-d 줄을 짧게(문구가 근거 내용을 담아야 하므로 근거별로 따로 정함), 영어 이유 문구의 한국어 표(위 항목).
- 정체 머리줄의 `내 설정` 두 번(구현 결과 참고). 하나로 합치려면 이 줄의 표시 규칙을 따로 정해야 한다.
- 빈 근거 목록은 v1처럼 `[]`로 나온다.
- 휴대폰 Telegram에서 줄이 어떻게 접히는지는 눈으로 확인하지 않았다. 반영하려면 `telegram run`을 다시 시작해야 한다.
