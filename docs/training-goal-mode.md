# Training Goal Mode and Evidence-Linked Rules v1

스펙: `docs/specs/training-goal-mode.md`. 근거 ID: `docs/evidence/training-nutrition-evidence.md`(2026-10-25 사용자 승인).
설계 결정(D1-D7): 2026-10-26 사용자 승인("모두 추천").

## 목적과 non-goal

- 사용자가 목표를 **cut(근육 유지하며 감량) / maintain / gain** 중 하나로 정하면 `recommend`, `daily`, `nutrition status`의
  진행 목표와 표시가 그 목표에 맞게 바뀐다. 목표 파일이 없으면 모든 기존 출력은 byte-identical이다(gain, 코드 기본값).
- 새 규칙과 줄마다 근거 ID를 단다. 근거에 숫자가 없는 기준은 `[design]`이고, 자동 규칙이 아니라 표시·조언·사용자 설정이다.
- Non-goal:
  - 식단 목표와 운동 계획을 자동으로 바꾸지 않는다. cut이 바꾸는 것은 진행 목표(무게·횟수)뿐이고 set 수, 종목, focus는
    그대로다. 영양은 계획을 바꾸지 않는다.
  - 수면·러닝을 이유로 set이나 무게를 줄이는 새 규칙은 없다(근거 없음). "쉬운 강도로" 같은 조언도 없다(CONC-06).
  - 체중 입력 명령 없음(D2). 체중은 InBody에서만 읽는다. Migration 없음.
  - LLM 없음. 결정적 규칙만.

## 명령

```powershell
muscle50 goal set --mode cut --target-body-fat 18 --by 2027-02-28 --min-smm 41 --weekly-loss 0.3 0.5
muscle50 goal show [--json]
muscle50 goal unset [--json]
muscle50 settings sleep show [--json]
muscle50 settings sleep set [--hold-below-hours H] [--reduce-below-hours H] [--hold-below-score N] [--json]
muscle50 settings sleep reset
```

- `goal set`: `--mode`(필수), `--target-body-fat PCT` 또는 `--target-weight KG`(하나만), `--by YYYY-MM-DD`(목표가 있어야 하고
  오늘 이후), `--min-smm KG`, `--weekly-loss MIN MAX`(cut만, MIN ≤ MAX). **문서 전체를 바꾼다**(주지 않은 값은 지워진다;
  `nutrition target set`의 영양소별 병합과 다르다, D7).
- 범위: 체지방률 3-60 %(스펙), 체중 30-250 kg, SMM 하한 10-100 kg, 주당 감량 0.05-2.0 %(셋은 `[design]` 타당성 한계).
- 잘못된 값은 exit 1과 `오류: --target-body-fat은 3~60 사이여야 합니다. 아무것도 바꾸지 않았습니다.`처럼 flag와 범위만
  말하고 값은 출력하지 않는다. 파일은 그대로다(없으면 계속 없다). 형식 오류(`--mode` 없음, 모르는 mode, `--weekly-loss`
  인자 1개)는 argparse exit 2.
- `settings sleep set`: 주지 않은 값은 지금 값을 유지한다(병합). 시간은 정수 초가 되어야 하고(예 5, 5.5, 5.25),
  0 < reduce < hold ≤ 12 h, 점수는 1-100 정수(`[design]`). flag가 하나도 없으면 exit 2.
- 두 명령 모두 DB를 열지 않고 `ensure_directories()`를 부르지 않으며 Garmin을 쓰지 않는다. 파일은 `set`만 만든다
  (`config\training_goal.json`, `config\sleep_thresholds.json`). 읽기는 아무것도 만들지 않는다. `unset`/`reset`은 파일을
  지우고, 없으면 "Nothing changed"(exit 0).

### `goal set` / `goal show` 출력(합성 값)

```text
Training goal set.
Training goal (config\training_goal.json, user setting):
  mode: cut
  target body fat: 18 % by 2027-02-28
  skeletal muscle mass floor: 41 kg
  weekly loss target: 0.3-0.5 %/week (evidence range 0.5-1.0 %/week [MAINT-05])
  effects: progression keeps load and reps (maintain_load [MAINT-02]); goal lines in recommend/daily;
  cut references in nutrition status. Nutrition targets and the training plan are not changed.
```

목표가 없으면 `No training goal set. recommend and daily use the default rules (gain).`, `--json`은
`{"goal_version": 1, "goal": null}`.

### 파일 schema

```json
{
  "schema_version": 1,
  "goal": {
    "mode": "cut",
    "target_body_fat_percent": "18",
    "target_weight_kg": null,
    "target_date": "2027-02-28",
    "min_skeletal_muscle_mass_kg": "41",
    "weekly_loss_percent": {"minimum": "0.3", "maximum": "0.5"}
  }
}
```

```json
{"schema_version": 1, "sleep_thresholds": {"hold_below_seconds": 18000, "reduce_below_seconds": 14400, "hold_below_score": 50}}
```

엄격하게 읽는다: 정확한 key, 소수는 decimal 문자열(JSON number 거부), 수면 값은 정수(bool 거부), `set`과 같은 범위 검사.
틀린 파일은 `오류: training goal file <path> is not valid (<key>)`로 key만 말한다. 단 저장된 기한이 지난 것은 유효하다
(`deadline_passed`로 표시). 원자적 쓰기(임시 파일 + `os.replace`), LF.

### `recommend` / `daily`의 goal 절(합성 값, cut)

`== Data freshness ==` 앞(영양 절 뒤)에 추가된다. cut에서는 진행 목표 header가 `SQUAT/- [maintain_load, load confidence normal]`이
되고 basis에 한 줄이 붙는다.

```text
== Goal: cut (user setting) ==
  Target [design: user setting]: body fat 18 % by 2027-02-28; SMM floor 41 kg; weekly loss 0.3-0.5 %/week
  Progression [MAINT-02, MAINT-06; optional PROG-03]: keep load and reps; the increase is optional
    SQUAT/- [maintain_load]: keep 60 kg x 10 (optional: 60 kg x 11)
  Weekly sets below 10, 2026-03-09..2026-03-15 (primary 1, secondary 0.5) [VOL-04; counting VOL-02]:
    quadriceps 3, hamstrings 0, glutes 1.5, ... (lower bounds: 1 UNKNOWN sets not counted)
  Weight change 2026-02-16 -> 2026-03-16 (28 d; latest InBody 2026-03-16, 0 d ago): -0.62 %/week [MAINT-05; design: >= 7 d apart]
    evidence 0.5-1.0 [MAINT-05]; your target 0.3-0.5 (user setting)
    -> outside your target range [design: user setting]
  SMM: below your 41 kg floor (InBody 2026-03-16) [design: user setting]
  Goal progress [design: fat-free mass assumed constant]: needs -0.03 %/week to reach body fat 18 % by 2027-02-28; actual -0.62 %/week
  Same-day run and legs under 3 h, 2026-03-09..2026-03-16 [design; CONC-03, CONC-04]:
    2026-03-12: run 07:00, legs 08:00 (1 h apart): lift first next time [CONC-05]
  Nights under 7 h, 2026-03-10..2026-03-16: 0 of 1 with sleep data, 6 without [SLEEP-05, display only]
    training sleep rules [design]: hold < 5 h, reduce < 4 h, score < 50 (default; not evidence-based, SLEEP-05)
```

들여쓴 이어지는 줄은 바로 위 태그 줄의 근거를 따른다. maintain/gain은 `Progression [design]: unchanged (the default gain rules)`
이고 감량 경고와 근거 범위 줄이 없다.

`--json`: `nutrition` 뒤 마지막 key `goal_mode`(`goal_mode_version` 1). `recommendation_version`은 1 그대로다(영양 통합과
같은 선례). 순서: `goal`(+`source`, `evidence`), `progression[]`(`label`, `action: maintain_load`, `load_kg`, `target_reps`,
`optional{action, load_kg, load_increase_from_kg, load_step, target_reps}`, `evidence`), `weekly_sets`(`from`, `to`, `threshold`,
`secondary_weight`, `evidence`, `unknown_sets`, `no_rule_sets`, `lower_bound`, `muscles[]{muscle, direct_sets, indirect_sets,
fractional_sets, below_threshold, countable}`), `weight_change`(`status`, `from_date`, `to_date`, `days`, `percent_per_week`(문자열,
0.01 HALF_EVEN), `flags`, `evidence_range_percent_per_week`, `latest_measurement_date`, `days_since_latest_measurement`,
`evidence`, `reason`), `smm_floor`(`status`, `measurement_date`, `floor_kg`, `evidence`), `goal_progress`(`status`,
`required_percent_per_week`, `actual_percent_per_week`, `measurement_date`, `evidence`, `assumption`, `reason`), `run_legs`(`from`,
`to`, `gap_threshold_hours`, `evidence`, `pairs[]{date, run_activity_id, strength_activity_id, run_start_local_time,
strength_start_local_time, gap_minutes, under_threshold, order, advice, advice_evidence}`), `sleep`(`from`, `to`,
`threshold_hours`, `nights_under`, `nights_with_data`, `nights_without_data`, `display_only`, `evidence`,
`training_rules{hold_below_seconds, reduce_below_seconds, hold_below_score, source, evidence}`).
`daily --json`의 `recommendation`은 이 문서 그대로다.

### `nutrition status`(cut만)

```text
Cut goal reference (nutrition targets are not changed):
  Protein [PRO-05]: 2.3-3.1 g/kg fat-free mass = 145-195 g/day
    (fat-free mass = weight - body fat mass, InBody 2026-03-16 [design])
  Energy deficit [PRO-04]: keep it at or under about 500 kcal/day; muscle50 cannot measure it (maintenance kcal unknown)
```

`--json`은 마지막 key `goal_reference`(`goal_reference_version`, `status` known/unknown/unavailable, `mode`, `protein{g_per_kg_
fat_free_mass, min_g, max_g, measurement_date, evidence}`, `energy_deficit{limit_kcal_per_day, measurable: false, evidence}`,
`targets_changed: false`, `reason`). maintain/gain/목표 없음이면 출력이 그대로다.

## 규칙과 근거

| 규칙 | 숫자 | 근거 | 성격 |
| --- | --- | --- | --- |
| cut 진행: 최종 `increase_load`/`add_reps`이고 마지막 session에 load가 있으면 `maintain_load`(마지막 work load, reps = min(best, 상한)); 원래 목표는 optional | — | MAINT-02, MAINT-06; optional PROG-03 | 진행 목표(set 수 불변) |
| cut 진행 예외: regression/recovery/rest rule의 `maintain`, `establish_baseline`, load 없는 label(`add_reps`)은 그대로 | — | design | 진행 목표 |
| 근육별 주당 fractional set(D-7..D-1, primary 1, secondary 0.5) < 10 표시 | 10, 0.5 | VOL-04(ACSM ≥ 10), VOL-02 | 표시만(D5: 부위 선택에 안 씀) |
| 체중 변화 %/주: 최근 InBody 체중 vs 그보다 7일 이상 앞선 마지막 체중 | 7일 | MAINT-05 + design | 표시 |
| cut 경고: 감량 > 1.0 %/주, 사용자 범위 밖, 증가 | 1.0 | MAINT-05; 사용자 설정; design | 표시 |
| SMM 하한 아래/이상 | 사용자 값 | design(사용자 설정) | 표시 |
| 목표 진행: 제지방 = 체중 - 체지방량(같은 날짜), 목표 체중 = 제지방 / (1 - 목표%/100), 필요 %/주 = (목표/현재 - 1) / 남은 주 × 100 | — | design(제지방 유지 가정) | 표시 |
| 같은 날 러닝과 하체 근력(primary가 quads/hamstrings/glutes인 매핑 ACTIVE set ≥ 3) 시작 간격 < 3 h | 3 h | design, 근거 범위 2-6 h(CONC-03, CONC-04) | 표시 |
| 러닝이 먼저면 "lift first next time" | — | CONC-05 | 조언 |
| D-6..D 밤 중 7 h 미만 | 7 h | SLEEP-05 | 표시만 |
| 훈련 수면 기준(< 5 h hold, < 4 h reduce, score < 50) | 사용자 설정 | design, SLEEP-05(근거 없음) | 기존 규칙, 기본값 그대로 |
| cut 단백질 참고: 제지방 × 2.3-3.1 g, 정수 g HALF_EVEN | 2.3-3.1 | PRO-05 + design(제지방 계산) | 표시(목표 불변) |
| 결손 상한 약 500 kcal/일(측정 불가 문구) | 500 | PRO-04 | 고정 문구 |

- 모르는 값은 0이 아니다: InBody 점이 하나뿐이거나 7일 이상 앞선 점이 없으면, 체중이 없으면, 같은 날짜 행이 충돌하면
  (`inbody trend`의 conflict 규칙) 체중 변화는 `unknown`이다. 수면 값이 없는 밤은 "without data"로 따로 세고 짧은 밤으로
  세지 않는다. 시작 시각에 zone이 없거나 읽을 수 없으면 "gap unknown"이고 표시는 하되 경고하지 않는다.
- 비교는 반올림 전 Decimal 값, 표시는 0.01 HALF_EVEN(예: 80.0 → 78.0, 28일 = 정확히 -0.625 → "-0.62").
- InBody 값은 `inbody trend`와 같은 0.1 반올림 점(`metric_points`)을 쓴다. InBody는 목표가 있을 때만 읽는다(read-only).
  InBody table이 없거나 읽을 수 없으면 해당 줄이 `unknown`이고 명령은 exit 0이다.
- **D1(체성분 값 노출)**: `recommend`/`daily`의 text와 JSON에는 측정 kg(체중, SMM, 체지방량, 제지방, 목표 체중 계산값)이 없다.
  비율, 표시(flag), 날짜, 사용자가 입력한 목표/하한만 나온다. `nutrition status`(cut)는 단백질 g 범위만 보여 준다.
- 잘못된 목표/수면 파일: `recommend`는 exit 1(`오류: ... is not valid (<key>)`, stdout 비어 있음). `daily`는 디렉터리 생성,
  migration, Garmin 로그인 전에 exit 1이다. `daily --after-workout`과 `garmin sync`는 두 파일을 읽지 않는다. `nutrition status`는
  목표 파일이 틀려도 한 줄 "Goal reference: unavailable (...)"만 붙이고 exit 0이다(Telegram `/status` 유지). `nutrition status`는
  수면 파일을 읽지 않는다.
- `analytics snapshot`, `inbody trend`, `inbody sync`, 다른 nutrition 명령, Garmin 명령은 바뀌지 않는다.

## Known issues / limitations

- **InBody가 드물면 감량 속도가 늦게 보인다.** 측정이 한 달 1-2회면 비율은 측정 뒤에야 나온다. 같은 날 행이 충돌하면 그 날짜는
  빠진다(InBody의 기존 known issue). 주 1회 정도 시계 체성분 측정 + `inbody sync`로 보완할 수 있다(D2).
- **제지방량은 계산값**(`[design]`): 체중 - 체지방량. InBody RAW metadata의 FFM은 읽지 않는다. 목표 진행은 제지방이 그대로라고
  가정한다.
- **`inbody trend`는 여전히 SMM 43/50 kg 목표**(코드 기본값)를 보여 준다. cut 목표의 SMM 하한(41 kg)과 다르게 보이는 것은 알려진
  불일치다(후속 후보).
- **러닝/하체 간격은 지난 기록만 본다.** "오늘 러닝이 이미 저장됐고 하체가 계획됨" 같은 앞으로의 안내는 없다(후속 후보). 간격은
  저장된 UTC 시작 시각(`started_at_utc`)의 차이다.
- **주당 set은 표시만**이다(D5). 부위 선택 규칙과 자동 계획에는 쓰지 않는다. UNKNOWN/no-rule set이 있으면 모든 수가 하한이다.
  창은 D-7..D-1이라 D에 이미 저장된 근력 session은 세지 않는다(계획의 `sets_last_7_days`와 같은 창).
- **애매한 label의 증량 안내 문구**: `PULL_UP/-` 등에서 원래 `increase_load`(방향 모름)가 `maintain_load`로 바뀌어도,
  `load_guidance`의 "assistance면 줄이고 추가 중량이면 늘린다" 문구는 그대로 남는다(진행 규칙을 다시 설계하지 않음). 무게는
  유지 목표가 맞고, 이 문구는 optional 증량에만 해당한다.
- **maintain 모드**는 gain과 같은 진행 규칙이고 체중 경고가 없다(D4: 근거에 유지·증가용 숫자 없음).
- **결손은 측정할 수 없다.** 유지 kcal을 모르므로 PRO-04는 고정 문구다. 단백질 참고는 비교만 하고 영양 목표(`nutrition target`)를
  바꾸지 않는다.
- **외부 LLM 노출**: Telegram 코치는 `recommend --json`과 `nutrition status --json`을 그대로 받으므로 `goal_mode`(비율·표시·사용자
  목표)와 `goal_reference`(단백질 g 범위)도 받는다. 측정 kg은 없다(D1).
- **수면 설정 파일이 틀리면** `settings sleep set`도 지금 값을 읽지 못해 exit 1이다. `settings sleep reset`으로 지우고 다시 설정한다.
  목표 파일은 `goal set`이 통째로 덮어쓰므로 틀린 파일도 고칠 수 있다.
- 후속 후보: Telegram `/goal`, 코치가 목표 모드 읽기, `inbody trend`가 목표 파일 읽기, 앞으로의 러닝/하체 안내, 근거 기반 휴식 시간
  조언(`strength-set-timing` 뒤).
