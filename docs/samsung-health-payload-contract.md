# Samsung Health InBody diagnostic payload contract (v1)

Status: versioned diagnostic interchange contract and live-validated Windows ingestion input, not yet a
shared production CLI contract. The Android side has built successfully against the user's local Samsung
Health Data SDK 1.1.0 AAR. A real Galaxy export has passed RAW preservation, normalization, SQLite storage,
and duplicate re-import on Windows. Items not observed in those live checks remain `UNKNOWN` and must not be
guessed.

## Live evidence (2026-09-18)

| Item | Status |
|---|---|
| Professional InBody result visible in Samsung Health | CONFIRMED |
| Body Composition read through Samsung Health Data SDK | CONFIRMED |
| Skeletal muscle mass present | CONFIRMED |
| Android `:app:assembleDebug` with local SDK AAR | CONFIRMED |
| `DataSource.appId` presence | CONFIRMED (2/2 exported records) |
| `DataSource.appId` value | CONFIRMED as `com.inbody2014.inbody` in this export |
| `DataSource.appId` attribution stability across future records/app versions | REQUIRES LIVE VERIFICATION |
| Samsung UID stability | REQUIRES LIVE VERIFICATION |
| Weight | CONFIRMED (2/2 exported records) |
| SMM/BFM/PBF/BMR/FFM | CONFIRMED (1/2 exported records) |
| BMI | CONFIRMED (2/2 exported records) |
| TBW | ABSENT in this export (0/2); broader support remains UNKNOWN |
| Zone offset | CONFIRMED (2/2 exported records) |
| Historical/backfill behavior | REQUIRES LIVE VERIFICATION |
| Actual JSON -> Windows RAW/normalized/SQLite | CONFIRMED (2 records inserted) |
| Same-file duplicate re-import | CONFIRMED (0 inserted, 2 existing, 0 changed RAW) |

## Sources consulted (2026-09-17)

- [`BodyCompositionType`](https://developer.samsung.com/health/data/api-reference/-shd/com.samsung.android.sdk.health.data.request/-data-type/-body-composition-type/index.html)
- [`DataSource`](https://developer.samsung.com/health/data/api-reference/-shd/com.samsung.android.sdk.health.data.data/-data-source/index.html)
- [Data permission guide](https://developer.samsung.com/health/data/guide/features/data-permission.html)
- [`AccessType.READ`](https://developer.samsung.com/health/data/api-reference/-shd/com.samsung.android.sdk.health.data.permission/-access-type/-r-e-a-d/index.html)
- [App verification guide](https://developer.samsung.com/health/data/guide/app-verification.html)
- [`Change`](https://developer.samsung.com/health/data/api-reference/-shd/com.samsung.android.sdk.health.data.data/-change/index.html)
- [Read data changes guide](https://developer.samsung.com/health/data/guide/hello-sdk/read-changes.html)
- `BodyCompositionType.Companion` field pages (e.g. `.../-w-e-i-g-h-t.html`,
  `.../-s-k-e-l-e-t-a-l_-m-u-s-c-l-e_-m-a-s-s.html`, `.../-b-a-s-a-l_-m-e-t-a-b-o-l-i-c_-r-a-t-e.html`),
  fetched by this session's reviewer, corrected the field types below from an earlier draft that
  incorrectly stated every field as `Double`.

## Confirmed Samsung SDK facts this contract relies on

- `BodyCompositionType` mandatory fields: `uid` (String), `startTime` (`Instant`, ms), `zoneOffset`
  (`ZoneOffset`), `dataSource` (`DataSource`), `WEIGHT` (**Field&lt;Float&gt;**, kilograms).
- `BodyCompositionType` optional fields relevant here: `BASAL_METABOLIC_RATE`
  (**Field&lt;Int&gt;**, kcal/day — the only integer field in this set), `BODY_FAT` (Field&lt;Float&gt;,
  percent), `BODY_FAT_MASS` (Field&lt;Float&gt;, kg), `FAT_FREE_MASS` (Field&lt;Float&gt;, kg),
  `SKELETAL_MUSCLE_MASS` (Field&lt;Float&gt;, kg), `TOTAL_BODY_WATER` (Field&lt;Float&gt;, L),
  `BODY_MASS_INDEX` (Field&lt;Float&gt;, computed by Samsung Health, no unit). `SKELETAL_MUSCLE`/
  `FAT_FREE`/`MUSCLE_MASS` are separate **percentage** fields and are never substituted for the
  corresponding kilogram field. An Android reader must convert `Float`/`Int` results explicitly
  (Kotlin does not widen either type to `Double` implicitly); this JSON contract itself has no
  int/float distinction, so `fields.*.value` is simply a JSON number on the wire either way.
- `DataSource` exposes exactly `appId` ("the unique identifier of the source app"; Samsung Health itself
  reports `com.sec.android.app.shealth`) and `deviceId` ("the unique identifier of the source device").
- Read permission is requested as `Permission.of(DataTypes.BODY_COMPOSITION, AccessType.READ)` via
  `HealthDataStore.requestPermissions()`/`requestPermissionsAsync()`, checked with `getGrantedPermissions()`.
- Public distribution requires registering the app's package name and SHA-256 signing certificate with
  Samsung; unregistered use only works with developer-mode signature-check bypass, which the guide states is
  for testing/debugging only.
- `BodyCompositionType` supports `ChangedDataRequest`/`readChanges`. A `Change` exposes `changeType`
  (`UPSERT` or `DELETE`), `changeTime`, `upsertDataPoint` (for `UPSERT`), and `deleteDataUid` (for `DELETE`).
  Deletion is therefore a real, documented SDK concept — not `UNKNOWN` — but this diagnostic contract does
  not use change tracking yet (see "Not covered by v1" below).

## `UNKNOWN` — do not guess these

- Whether `DataSource.appId` reflects the original third-party app that wrote a partner-contributed data
  point (e.g. an InBody package identifier), or always reports Samsung Health's own package
  (`com.sec.android.app.shealth`) regardless of which partner app supplied the value. The docs state only
  what Samsung Health's own `appId` is; they do not describe partner attribution. This is exactly the
  Phase 7 question and must be read from a live `dataSource.appId` value at the Galaxy smoke test, never
  assumed either way.
- Change-token acquisition, ordering guarantees, duplicate handling, and token expiry for
  `readChanges`/`readChangesAsync`. The programming guide shows only a time-range-filtered example; API
  reference detail beyond that was not available from the pages fetched.
- Whether the confirmed Professional-to-Body-Composition behavior generalizes across App versions, regions,
  facilities and device models, and whether history is backfilled.

## Non-Samsung-SDK design choices (companion-invented, explicitly not from Samsung docs)

- `profile_key`: Samsung's SDK does not expose an account identifier to a read-only companion. The companion
  generates one random opaque UUID once, persists it in local Android app storage, and includes it in every
  export's envelope. It is not a Samsung account ID, phone number, or email, and it is stable only for that
  app install (a reinstall changes it). This satisfies `SourceMeasurementIdentity.source_profile_key`'s
  existing "opaque, never an email/phone" rule in `docs/inbody-access-decision.md`.
- `source_type`: fixed literal `"inbody_samsung_health"`, matching the value already reserved for this path
  in `docs/inbody-sync-design.md`. It names the pipeline (Samsung Health Data SDK via this companion), not a
  claim that a given record originates from InBody — see Phase 7 candidate-labeling below.

## Envelope (one export = one JSON document)

```json
{
  "schema": "muscle50.samsung_health.inbody_diagnostic_export.v1",
  "schema_version": "1",
  "source_type": "inbody_samsung_health",
  "exported_at": "2026-09-17T09:00:00Z",
  "source_sdk_name": "Samsung Health Data SDK",
  "source_sdk_version": "<value read from the SDK/app at build or runtime, never hand-typed>",
  "profile_key": "5e6f2c9a-....",
  "companion_app_id": "<this diagnostic companion's own Android package name>",
  "records": [ /* zero or more Record objects, see below */ ]
}
```

`schema_version` is a string so the Python adapter can reject an unrecognized version without guessing
forward compatibility. `records: []` (empty list) is a valid, successfully-exported "no records found"
result and is distinct from an export failure (which the companion does not produce a payload for at all).
The v1 adapter rejects missing or additional envelope, record, and metric keys rather than silently accepting
schema drift. `source_sdk_version` is generated from the exact AAR version configured in Gradle.

## Record

```json
{
  "source_record_id": "<Samsung BodyCompositionType.uid, verbatim>",
  "measured_at": "2026-09-17T08:55:00",
  "zone_offset": "+09:00",
  "data_source_app_id": "com.sec.android.app.shealth",
  "data_source_device_id": "<DataSource.deviceId, or null if the SDK returned none>",
  "fields": {
    "weight": {"value": 70.0, "unit": "kg", "path": "BodyCompositionType.WEIGHT"},
    "skeletal_muscle_mass": {"value": 31.2, "unit": "kg", "path": "BodyCompositionType.SKELETAL_MUSCLE_MASS"},
    "body_fat_mass": null,
    "body_fat_percent": {"value": 20.1, "unit": "%", "path": "BodyCompositionType.BODY_FAT"},
    "bmi": {"value": 22.9, "unit": null, "path": "BodyCompositionType.BODY_MASS_INDEX"},
    "basal_metabolic_rate": {"value": 1590, "unit": "kcal/day", "path": "BodyCompositionType.BASAL_METABOLIC_RATE"},
    "total_body_water": {"value": 39.8, "unit": "L", "path": "BodyCompositionType.TOTAL_BODY_WATER"},
    "fat_free_mass": {"value": 55.9, "unit": "kg", "path": "BodyCompositionType.FAT_FREE_MASS"}
  }
}
```

Rules:

- `zone_offset` is `null` only if the SDK genuinely returned no offset for that point; a present-but-empty
  string is treated as malformed, not missing.
- A key absent from `fields`, or present with value `null`, means "this metric was not populated on this
  Samsung record" and normalizes to `None`. It is never coerced to `0`. A genuine Samsung-reported `0.0`
  (e.g. `body_fat_mass: {"value": 0.0, ...}`) is preserved as `0.0`, not treated as missing. These are
  different states and the adapter must be able to tell them apart from the payload alone.
- Every populated metric object contains all three keys: `value`, `unit`, and `path`. Unitless BMI uses the
  explicit JSON value `"unit": null`; omitting the key is schema drift. Android must use `JSONObject.NULL`
  because `JSONObject.put(name, null)` removes the key.
- `fields.skeletal_muscle_mass` may be populated **only** from `BodyCompositionType.SKELETAL_MUSCLE_MASS`
  (kilograms). `FAT_FREE_MASS`, `FAT_FREE` (percent), `MUSCLE_MASS` (percent), and any Health Connect
  `LeanBodyMassRecord`-shaped value must never be substituted, mapped, or estimated into
  `skeletal_muscle_mass`. This applies even if `skeletal_muscle_mass` is absent and `fat_free_mass` is
  present — the record stays partial rather than backfilled from a different metric.
- `path` values are exact Samsung Kotlin identifiers (`BodyCompositionType.<FIELD>`) so provenance can be
  audited against the field table above without re-deriving it later.
- `data_source_app_id` is copied verbatim from `DataSource.appId` and is never used, by itself, to assert
  that a record originated from InBody (see Phase 7 in `docs/HANDOFF.md`/the review doc). It is provenance,
  not a classification.
- `source_record_id` (Samsung's `uid`) is required and must be unique per export. Two records sharing a
  `source_record_id` are accepted only if their parsed JSON record structures are equal (a harmless
  re-export/retry duplicate; object key order and equivalent JSON number spellings are irrelevant). Any
  semantic content difference under a repeated `source_record_id` is rejected
  as a malformed export rather than silently keeping one side and dropping the other. This closes a gap an
  earlier draft of this adapter had, where two same-uid records that also happened to share `measured_at`
  could pass reference-level deduplication while differing in body-composition values.
- Across imports, the same UID and same record payload is idempotent. The same UID with different record
  content creates a new immutable RAW artifact, sets an explicit changed-RAW status, and never overwrites the
  existing normalized row. Actual Samsung update semantics remain unknown, so no automatic correction is
  inferred.
- The whole exported envelope is preserved byte-for-byte as the list RAW snapshot. Per-record detail RAW is
  a deterministic JSON projection of the corresponding envelope record. `data_source_app_id` is retained as
  detail provenance and is never replaced with the companion package when Samsung did not provide it.

## Safe Windows transfer and smoke import

Do not place a live export anywhere in the Git worktree. Copy it to a local application-data path such as:

```text
%LOCALAPPDATA%\muscle50\imports\inbody\samsung-health\latest.json
```

The repository ignores common RAW/database locations, but keeping personal health data entirely outside the
repository is safer. Run the feature-local developer entry point from the repository root:

```powershell
uv run python -m muscle50.infrastructure.inbody.samsung_health_smoke `
  "$env:LOCALAPPDATA\muscle50\imports\inbody\samsung-health\latest.json"
```

By default it prints only record counts, UID/timestamp/metric presence, inserted/existing/changed status, and
artifact/database paths. It stores the smoke database at
`%LOCALAPPDATA%\muscle50\db\inbody-samsung-health-smoke.sqlite3` and immutable RAW under
`%LOCALAPPDATA%\muscle50\raw\inbody\samsung_health`. `--show-values` is explicit opt-in and should not be
used when capturing logs or issue reports.

## Not covered by v1

- Incremental sync via `readChanges`/change tokens. The diagnostic companion performs a full point-in-time
  export of recent records only; `Change`/`ChangedDataRequest`/`deleteDataUid` semantics are confirmed to
  exist (see above) but are out of scope until token/ordering/expiry behavior is verified against the SDK
  reference beyond what was fetched for this contract.
- Any write, insert, update, or delete operation against Samsung Health. This companion is read-only.
- Any InBody credential, Samsung account credential, Health Connect record, or private storage access.
