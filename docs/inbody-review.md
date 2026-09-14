# Independent review: Professional InBody path (2026-09-14)

## Verdict before remediation

The reviewer made no code changes and found one blocker plus high-risk modeling gaps:

- **BLOCKER:** `SyncInBody` required OAuth/session and account list/detail semantics even though Samsung
  Health, Health Connect, and file export do not share that authentication model.
- **HIGH:** RAW lacked source type/application/schema/fetch/record provenance, so an OS-health snapshot could
  be mistaken for original InBody RAW.
- **HIGH:** source IDs were not namespaced by source, and canonical versus source-local identity was not
  separated. Cross-source heuristic adoption could silently merge records.
- **MEDIUM:** Samsung Health can represent a full body-composition point, but Professional InBody App WRITE
  behavior needs a Galaxy smoke test. Health Connect has no SMM record and lean mass is not a substitute.

The reviewer also confirmed that shared CLI, migration numbering, and database bootstrap remained untouched;
fixtures contained no personal data or credentials; fixed auth errors and content-addressed storage were sound.

## Evidence review

- Professional device to InBody App is official for listed devices and facility Cloud/phone-number setup.
- Home-use OAuth is not evidence for Professional App history.
- Samsung Health's official Body Composition type has UID, timestamp, zone offset, source, weight, SMM kg,
  BFM, PBF, FFM, TBW, BMR, and BMI capacity.
- InBody officially lists Samsung Health integration and those metrics, but public material does not prove
  direction, Professional inclusion, or history.
- Health Connect uses separate Weight/PBF/Lean records and has no SMM/BFM/BMI record.
- App machine-readable export is not publicly documented. Samsung personal-data download exists, but its
  schema/InBody content needs inspection.
- LookinBody Web/API/LB120/device exports are official and potentially full, but facility-controlled.

## Remediation implemented

- Added a source-neutral application port and moved auth/session lifecycle into an optional infrastructure
  wrapper.
- Added source permission-denied, permission-revoked, and unavailable errors with fixed redacted text.
- Added RAW source type, fetch time, record ID, application, and schema version and source-namespaced paths.
- Split `SourceMeasurementIdentity` from `CanonicalMeasurementIdentity`.
- Made repository uniqueness source-local and canonical fingerprints non-unique comparison hints.
- Removed automatic ID-less-to-official-ID adoption and all automatic cross-source merging.
- Added explicit full/partial measurement reporting and tests proving missing SMM is never inferred.
- Added synthetic source tests for Samsung-shaped full/partial boundaries, zero versus missing, permission
  failures, schema drift, unit mismatch, RAW provenance, and same-measurement cross-source behavior.

## Remaining gate

Do not add a production Android adapter until the user's Galaxy confirms an InBody-origin Professional
`BodyCompositionType` record with SMM kg. Do not call Health Connect full sync. A distributable Samsung Health
reader also requires Samsung partner/package/signature registration; developer mode is smoke-test only.

Official evidence and the exact smoke procedure are recorded in `docs/inbody-access-decision.md`.
