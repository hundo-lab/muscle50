# InBody Samsung Health diagnostic companion

Diagnostic-only Android app, Kotlin. It does **not** perform production sync. Its only job is to
answer one question: does a Professional InBody measurement, already visible in the InBody App,
appear in Samsung Health's `BodyCompositionType` with `SKELETAL_MUSCLE_MASS` populated?

It is a clearly separate project from the Python `muscle50` package — nothing here is imported by
`src/muscle50/`, and nothing in `src/muscle50/` imports this. The only connection between them is
the versioned JSON file this app exports, consumed by
`muscle50.infrastructure.inbody.samsung_health.SamsungHealthInBodySource` on the Windows side, per
`docs/samsung-health-payload-contract.md`.

## Validated toolchain state

The user linked `samsung-health-data-api-1.1.0.aar`, set `minSdk = 29`, and successfully built
`:app:assembleDebug` in Android Studio. The current source uses the SDK's suspend
`getGrantedPermissions`, `requestPermissions`, and `readData` APIs. The project-level
`gradle.properties` enables AndroidX and Jetifier.

The `.aar`, `local.properties`, `.gradle/`, `.idea/`, APK/AAB and build directories are ignored and
must never be committed. Another machine must supply its own Samsung SDK AAR and Android SDK path.

## What you need before building

1. **Android Studio** with Android API 34 installed. Samsung Health Data SDK 1.1.0 requires
   `minSdk = 29` in this project.
2. **The Samsung Health Data SDK `.aar`**, downloaded from your Samsung Developer account at
   <https://developer.samsung.com/health/data/overview.html>. Samsung does not publish this SDK to
   Maven Central or Google's Maven repository — place version 1.1.0 at
   `app/libs/samsung-health-data-api-1.1.0.aar`. The explicit filename is also used to populate
   `source_sdk_version` in the exported payload.
3. **Samsung Health app installed on the test Galaxy device**, with **Developer Mode** enabled in
   Samsung Health's settings so an unregistered/unsigned debug build can call the SDK at all. This
   is stated by Samsung's own app-verification guide to be for testing only — do not hand this APK
   to anyone else while only developer mode is enabled, and do not present developer mode as an
   end-user setup step.
4. A Galaxy device signed into the same Samsung account that has a Professional InBody result
   visible in the InBody App.

## Build

Open `android/inbody-diagnostic-companion/` as a project root in Android Studio and let Gradle
sync. If sync fails on the SDK dependency, re-check step 2's filename/path first — that is the
single most likely first failure, not a code defect.

From PowerShell with Android Studio's JBR selected:

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat :app:assembleDebug
```

## What it does (Phase 5/6 scope)

1. Initializes `HealthDataStore` via the Samsung Health Data SDK.
2. Checks exactly one read permission: `Permission.of(DataTypes.BODY_COMPOSITION, AccessType.READ)`.
   If missing, it opens Samsung Health's consent UI and uses the suspend `requestPermissions()`
   return set as the updated state. Denial exits without a read. No write permission, no other
   data type, and no InBody/Samsung account credential are used.
3. Reads recent `BodyCompositionType` records (most recent first).
4. Shows a **presence-only** diagnostic screen by default (see Phase 6 in `docs/HANDOFF.md`):
   connection status, record count, and for the most recent candidate record: presence/absence of
   `uid`, `startTime`, `zoneOffset`, `dataSource`/app id, and each mapped field. Actual health
   values are never written to Logcat; an optional in-app "show values" developer toggle is the
   only way to see them on screen, and it defaults off.
5. Exports the current record set as one JSON file matching
   `docs/samsung-health-payload-contract.md` exactly, for manual transfer to the Windows machine
   (`android/inbody-diagnostic-companion` → JSON file → user copies it → `muscle50 inbody`
   consumes it via `SamsungHealthInBodySource`). No network server, cloud backend, or account
   system is implemented.

## What it never does

- Never asks for an InBody username/password, token, or cookie.
- Never asks for the user's Samsung account password.
- Never requests write access, or any data type other than Body Composition.
- Never reads Health Connect.
- Never logs an actual health value (weight, SMM, BFM, PBF, BMI, TBW, BMR) to Logcat.
- Never guesses whether a given Samsung record is InBody-authored. It reports
  `dataSource`'s app id verbatim as provenance and leaves the "is this InBody" judgment to the
  smoke-test operator, per Phase 7 — because the public SDK docs do not confirm whether a
  partner-written point's `appId` reflects the partner app or Samsung Health itself.

## Known gaps to close before this is anything but a diagnostic tool

- The Galaxy live read confirmed SMM presence, but `dataSource.appId`, UID stability, weight,
  BFM/PBF/BMI/TBW/BMR presence, and historical/backfill behavior still need presence-only capture.
- An actual exported JSON has not yet completed the Windows RAW -> normalization -> SQLite smoke.
- Public distribution requires registering this app's package name and release-signing SHA-256
  certificate with Samsung; this repository does not and should not contain that registration or
  any signing key.

## Export and Windows smoke

`Export diagnostic JSON` writes to this app's external-files directory. Use Android Studio Device
Explorer or an explicit user-controlled file copy to move it to:

```text
%LOCALAPPDATA%\muscle50\imports\inbody\samsung-health\latest.json
```

Do not copy the live file into the repository. Then run from the Python repository root:

```powershell
uv run python -m muscle50.infrastructure.inbody.samsung_health_smoke `
  "$env:LOCALAPPDATA\muscle50\imports\inbody\samsung-health\latest.json"
```

Run it twice with the same file. The second run must report `Inserted: 0`,
`Already existing: N`, and `Changed RAW conflicts: 0`. Output is presence-only unless the user
explicitly supplies `--show-values`.
