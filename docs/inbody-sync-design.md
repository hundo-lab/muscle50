# InBody source-neutral sync design (2026-09-14)

## Why the account/OAuth boundary changed

The current target is Professional InBody data already visible in the personal InBody App. Public InBody
documentation limits the described OAuth API to home-use data, while the best technical candidate for the
target flow is Samsung Health. Therefore `SyncInBody` no longer depends on OAuth, cookies, Android permissions,
or a session type.

`InBodyMeasurementSource` is the application port:

```text
InBodyMeasurementSource
    list_measurements()
    extract_measurement_references(raw_list)
    get_measurement(reference)
    extract_measurement(raw_detail)

Potential adapters
    SamsungHealthInBodySource       (implemented for companion JSON; Galaxy SMM gate passed)
    HealthConnectInBodySource       (partial only; not implemented)
    InBodyExportSource              (gated on documented format)
    LookinBodyWebSource             (facility-controlled)
    AuthenticatedInBodySource       (transport wrapper, not a production claim)
    SyntheticInBodyMeasurementSource
```

`AuthenticatedInBodySource` retains the tested initial authorization, cached session reuse, expired-session
refresh, one retry, and reauthentication-required behavior. The wrapper owns those mechanics around a future
official `InBodyConnector`; the application use case does not. No official network contract means there is no
production auth/network implementation in this branch.

## Sync flow

1. Ask the selected source for an exact measurement-list/export snapshot.
2. Preserve exact bytes before parsing.
3. Extract source-local references and reject conflicting duplicate references.
4. Skip a known source ID by `(source_type, opaque profile key, source record ID)`.
5. Fetch the exact source detail record for each new reference.
6. Preserve exact bytes before extraction and normalization.
7. Verify list/detail source type, profile, and record ID agree.
8. Normalize values without estimating missing fields.
9. Save normalized data and link the immutable source artifact atomically.
10. Report whether each row meets the minimum useful set: weight, SMM, and BFM or PBF.

`refresh_existing=True` fetches a known source record again. Changed bytes become another immutable artifact
linked to the same row; normalized data is not overwritten. A future correction workflow must explicitly
version a replacement rather than silently mutate history.

## RAW provenance

Every source document/artifact tracks:

- `source_type` (`inbody_samsung_health`, `inbody_health_connect`, `inbody_export`,
  `lookinbody_web`, or `inbody_synthetic`);
- `source_fetched_at`;
- `source_record_id`, when available;
- `source_application`/data origin;
- `source_format` and `source_schema_version`;
- exact bytes, content type, SHA-256, byte size, artifact kind, and local relative path.

The path is content-addressed and source-namespaced. Identifiers are not placed in filenames. An OS-health
snapshot is described as an `InBody-derived Samsung Health/Health Connect record`, never as original InBody
device/server RAW. Each preserve operation also writes an immutable `.meta` sidecar, so list snapshots and
details that later fail extraction/normalization retain their provenance even without a SQLite measurement row.

## Source-local and canonical identity

`SourceMeasurementIdentity` controls idempotency only within one source namespace:

```text
source ID:          source_type + opaque profile + source record ID
source fallback:    source_type + opaque profile + fingerprint version + fingerprint
```

Fallback fingerprint v1 uses normalized measurement timestamp, weight, and PBF at device-facing 0.1
precision. It is heuristic; missing weight or PBF with no source ID is rejected instead of using a weak
timestamp-only key.

`CanonicalMeasurementIdentity` stores the same versioned stable-value fingerprint as a comparison hint. It is
not a unique key and never authorizes automatic cross-source merge. Thus the same physical measurement from
Samsung Health and an InBody export creates two source rows unless explicit future reconciliation proves
equivalence. The prior "ID-less row automatically adopts a later official ID" heuristic was removed.

Health Connect records require extra caution: Weight/PBF/lean are separate records. Timestamp proximity alone
does not prove a common InBody measurement, and lean body mass is not SMM.

## Access and error ownership

Source-neutral errors distinguish permission denied, permission revoked, and temporary source unavailability.
An approved network source additionally distinguishes invalid credentials, authentication service failure,
session expiry, reauthentication required, list/detail failure, and response schema change. Error text is
fixed and never contains tokens, cookies, passwords, raw auth responses, account contact data, or health values.

Android consent and Samsung partnership/signature registration belong to the Android adapter/distribution
layer. OAuth/token storage belongs only to an approved network adapter. Neither belongs in domain models or
the measurement SQLite schema.

## CLI integration state

The application-level `SyncInBody` contract can back `muscle50 inbody sync`, but no production source currently
passes the discovery gate. Shared CLI/config/bootstrap and shared migration numbering are deliberately untouched.
The Galaxy SMM gate and latest-main update are complete on this feature branch. Shared CLI/migration wiring
still waits for an actual exported JSON -> Windows RAW/normalize/SQLite smoke and duplicate re-import check.
The feature-local developer smoke entry point reports source, discovered/existing/added/changed counts and
field presence without exposing health values by default.
