---
id: meal-void-edit
title: Nutrition Meal Void, Edit and Merge v1
status: integrated
migration: reserved:009
output_change: additive
user_gates: [design, integration, prod-migration, push]
---

# Nutrition Meal Void, Edit and Merge v1

## 목적

- 이미 기록한 식사를 고칠 방법을 채운다. 아래 세 가지가 아직 없다
  (docs/CURRENT_STATE.md(동결) Known issues "Nutrition Logging MVP", "Meal Edit v1").
  - 잘못 기록한 식사 취소(void)
  - 식사 날짜, 종류, 시간 수정
  - `--additional`로 쪼개진 두 식사 합치기
- 근거: HANDOFF(동결) Meal Edit v1 "Recommended next action: Meal Merge / meal metadata edit 설계", Meal Repeat v1
  "후속 후보: meal void/merge".

## 범위 / Non-goals

- 범위:
  - `nutrition meal void <meal_id> [--reason TEXT]`
  - `nutrition meal edit <meal_id> [--date D] [--meal T] [--time HH:MM | --no-time]`
  - `nutrition meal merge <target_meal_id> <source_meal_id>`
  - 세 명령 모두 `--json`을 지원한다.
- Non-goals:
  - void 되돌리기(unvoid) 없음.
  - 음식(catalog) 이름/alias 수정 없음.
  - 영양 값 재계산 없음. 기존 snapshot을 유지하고 새 fact를 고르지 않는다.
  - 세 개 이상 한 번에 병합 없음.
  - 자동 병합 없음.

## 명령 예시

```powershell
muscle50 nutrition meal void 2026-10-02-snack-1 --reason "double entry"
muscle50 nutrition meal edit 2026-10-02-dinner-1 --date 2026-10-01 --time 21:30
muscle50 nutrition meal merge 2026-10-02-breakfast-1 2026-10-02-breakfast-2 --json
```

텍스트 출력은 `meal show` 형식을 그대로 쓴다. 맨 위에 무엇이 바뀌었는지 한 줄을 붙이고, 그 뒤에 식사 상세를 보여 준다.
JSON은 `meal show --json` 문서에 끝쪽 key를 추가하는 방식으로 확장한다. 예: `voided`, `void_reason`, `merged_into`,
`revisions`. 구체적인 key 이름과 순서는 설계에서 정한다.

## 규칙

- **Append-only 원칙 유지.**
  - 기존 meal, item, fact row는 UPDATE/DELETE하지 않는다(fact와 removal trigger는 그대로).
  - void, metadata 변경, 병합은 모두 새 기록으로 남긴다. 예: 식사 단위 tombstone과 revision 기록.
  - migration이 필요할 것으로 보이며, 번호는 오케스트레이터가 예약한다.
  - 기존 table은 ALTER하지 않는다(add-migration skill 참고).
- **Meal ID 불변.**
  - ID에 날짜와 종류가 들어 있어도 바꾸지 않는다(Meal Edit v1과 같은 원칙).
  - 집계와 표시는 수정된 metadata를 따른다.
  - ID와 실제 날짜/종류가 달라질 수 있다는 점을 `meal show`와 문서에 밝힌다.
- **영양 값 불변.** 어떤 명령도 item의 snapshot fact 선택을 바꾸지 않는다. 병합한 item도 원래 snapshot 값을 그대로
  유지한다. 지금 catalog를 기준으로 다시 snapshot하지 않는다.
- **void:**
  - void된 식사는 `day`/`status`/`recommend`/`daily`에서 즉시 빠진다.
  - `meal show`에서는 계속 조회할 수 있고, void 표시와 사유가 나온다.
  - 이미 void된 식사를 다시 void하거나, void된 식사를 edit/merge/add-item하려 하면 거부한다.
- **edit:**
  - 바꾸려는 값이 현재 값과 모두 같으면 거부한다(아무것도 쓰지 않음).
  - 옮겨 갈 날짜와 종류에 이미 식사가 있으면 `--additional` 없이는 거부한다(`log`의 이중 기록 방지 규칙과 같음).
  - `--time`과 `--no-time`은 함께 쓸 수 없다.
- **merge:**
  - source의 active item을 target에 새 item 번호로 붙이고 source를 void하는 작업을 한 transaction으로 한다.
  - 날짜가 다른 두 식사의 병합은 거부한다.
  - 병합 뒤 그 날짜의 kcal/P/C/F 총합, incomplete 여부, estimated 여부는 병합 전과 같아야 한다.
- 읽기 전용 reader(`recommend`/`daily`)는 이번 migration 이전 DB도 읽는다(table 존재 확인).
- 오류(없는 meal, void된 meal, 형식 오류, storage 실패)가 나면 아무것도 쓰지 않는다.

## 인수 조건

- [ ] AC1: void한 식사는 `nutrition day`/`status`와 `recommend --json`의 nutrition 절에서 빠지고, `meal show`에는 void와
      사유가 나온다. 다른 식사의 출력은 변하지 않는다.
- [ ] AC2: edit로 날짜를 옮기면 원래 날짜의 `day`에서 빠지고 새 날짜의 `day`에 나온다. meal ID와 item snapshot은 그대로다.
- [ ] AC3: 옮겨 갈 자리가 중복이면 `--additional` 없이 거부된다(exit 1, DB 불변).
- [ ] AC4: merge 뒤 target에는 두 식사의 item이 모두 있고, source는 void되며, 그 날짜 총합(text와 JSON)은 병합 전과
      byte-identical이다.
- [ ] AC5: void된 식사에 대한 edit, merge, add-item, 다시 void는 모두 거부된다(DB 불변).
- [ ] AC6: 이번 migration 이전 스키마 DB에서도 `recommend`/`daily`의 read-only 경로가 동작한다.
- [ ] AC7: 기존 nutrition 테스트가 수정 없이 통과한다. migration 버전 목록 기대값만 갱신한다.
- [ ] AC8: 품질 게이트 4개를 통과한다.

## 한계 / 후속 후보

- void 되돌리기, 식사 메모 수정, 세 개 이상 병합.
- meal ID를 날짜/종류와 다시 맞추는 기능(ID가 새로 생겨 다른 기록의 참조가 끊기므로 v1에서는 하지 않는다).
- 구현/검증에서 확인된 한계(상세: `docs/nutrition-meal-corrections.md` "Known issues / limitations"):
  - edit 취소, void 사유 수정 없음. merge target을 void하면 그 target에 복사된 item도 함께 빠진다(source는 void 유지).
  - merge는 item 이동으로 그 날짜의 정확한 총합(28자리 Decimal 합산 순서)이 달라지면 거부한다. 순환소수 값에서만 생긴다.
  - merge의 날짜/총합 검사는 저장된 UTC offset 기준 날짜와 이 컴퓨터의 offset을 쓴다. 다른 offset으로 기록한 식사는
    병합 대신 거부될 수 있다.
  - edit의 이중 기록 검사는 `log`처럼 쓰기 transaction 밖에서 한다(단일 사용자 CLI).
  - 식사 목록 조회가 `eaten_at_utc_sort_key` index를 더 이상 쓰지 않고, 식사마다 작은 query가 2-3개 늘었다(개인 규모에서는
    무시 가능).
  - edit된 식사의 `add-item`/`remove-item`/`replace-item` 출력에는 history 줄/key가 없다(`meal show`에는 있음).
  - `--time 00:00`과 `--no-time`은 구분되지 않는다(`log`의 기존 한계).
  - edit/merge에는 `--reason`이 없다(승인된 plan). 시각은 CLI의 현재 시각(`cli._now()`)으로 기록된다.
  - 운영 DB는 첫 쓰기 명령에서 migration 9가 적용된다. 그 전까지 `recommend`/`daily`는 기존과 같게 읽는다.
