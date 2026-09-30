# Garmin recovery / daily-health endpoint notes

Source: the pinned `garminconnect==0.3.15` package in `.venv/Lib/site-packages/garminconnect/`.
The method bodies and typed response models were inspected locally. No live Garmin account was queried.

All endpoints reuse the authenticated `Garmin` session. A single endpoint exception or malformed optional
response is isolated as a warning so other daily metrics can still be stored. An authentication exception fails
the sync immediately, and a run where every endpoint fails is not accepted as an empty success.

## Endpoint and normalization map

| RAW artifact | Client method | Normalized values | Missing/no-data handling |
|---|---|---|---|
| `sleep.json` | `get_sleep_data(date)` | duration/stages, GMT start/end epoch-ms, sleep score, sleep HRV (`dailySleepDTO.avgSleepHRV`, else top-level `avgOvernightHrv`), sleep respiration | `None`, `{}`, and missing nested fields normalize to `None` |
| `hrv.json` | `get_hrv_data(date)` | last-night average, weekly average, status | package explicitly permits `None` |
| `resting_heart_rate.json` | `get_rhr_daily(date, date)` | matching date's resting HR | empty list or missing row becomes `None` |
| `daily_stats.json` | `get_stats(date)` | Body Battery high/low and average stress | missing values become `None`; negative stress sentinels are not normalized |
| `body_battery.json` | `get_body_battery(date, date)` | RAW only | timeline is not used to derive high/low |
| `stress.json` | `get_all_day_stress(date)` | RAW only | timeline is not used to derive average stress |
| `training_readiness.json` | `get_training_readiness(date)` | score, level, recovery time and change phrase | empty list becomes `None` values |
| `training_status.json` | `get_training_status(date)` | one unique status key: a string `trainingStatusKey`/`trainingStatus`, else the key prefix of `trainingStatusFeedbackPhrase` (`RECOVERY_2` → `RECOVERY`); the numeric `trainingStatus` code is never used | absent, malformed, or ambiguous multi-device values become `None` |
| `respiration.json` | `get_respiration_data(date)` | RAW only | normalized respiration comes from the verified sleep field |

Training readiness selects `inputContext == "AFTER_WAKEUP_RESET"`, falling back to the first entry when the
marker is unavailable, matching `garminconnect`'s morning-readiness helper. `recoveryTime` is stored in minutes
without interpreting `recoveryTimeChangePhrase`. `acwrFactorPercent` is not an acute/chronic workload ratio and
is intentionally not normalized.

Live RAW (2026-09-01 ~ 2026-09-28, recovery normalizer version 2) confirmed two shapes the pinned package
models did not show. Sleep HRV is top-level `sleep.avgOvernightHrv`; `dailySleepDTO` has no HRV key. It equals the
HRV endpoint's `lastNightAvg` on every observed date. Training status is
`mostRecentTrainingStatus.latestTrainingStatusData.<deviceId>` with numeric `trainingStatus` and a
`trainingStatusFeedbackPhrase` whose numeric suffix is a feedback-message variant (it changes while `sinceDate`
stays fixed). Observed code/key pairs were 4 = `MAINTAINING`, 5 = `RECOVERY`, 7 = `PRODUCTIVE`.
`garmin recovery-renormalize` re-applies the current normalizer to each date's accepted RAW capture without
calling Garmin or creating captures.

## RAW and date policy

- Every successful endpoint response, including JSON `null`, `{}`, and `[]`, is preserved independently.
- Failed or malformed endpoints have no fabricated RAW response; their diagnostic is stored in the capture
  manifest.
- Content-identical payloads and diagnostics reuse the same content-addressed capture.
- Changed responses create a new immutable capture while the one normalized row for the date is updated to point
  at the latest accepted capture.
- Credentials, tokens, cookies, and authenticated client state are never serialized into recovery RAW.
- The requested `YYYY-MM-DD` is stored on the capture. Response `calendarDate`/`date` mismatches become warnings;
  the implementation does not silently shift dates or synthesize measurement timestamps.
- Sleep, HRV, and sleep respiration describe the night ending on the date. Body Battery, stress, resting HR,
  readiness, and status describe that calendar day.

## Live-smoke gaps

The following must be checked with an explicitly authorized account before treating the private API shapes as
stable:

- training-readiness list shape, wake-up context, recovery-time value/phrase semantics;
- training-status nesting and behavior with multiple devices;
- exact no-data responses for every endpoint;
- account/device-specific endpoint availability and stress sentinel values;
- timezone and `calendarDate` attribution around travel and midnight boundaries;
- historical availability depth.
