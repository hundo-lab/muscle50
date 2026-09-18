# Professional InBody personal access decision (2026-09-14)

## Decision

`Professional InBody -> InBody App -> Samsung Health -> Samsung Health Data SDK` 경로는 사용자의
실제 Galaxy에서 live 검증되었고, 읽은 Body Composition record에 SMM이 존재함도 확인됐다. 따라서
Samsung Health Data SDK companion을 **live-validated primary source**로 선택한다. 다만 source
application의 장기 안정성과 UID의 독립적인 재-export 간 안정성, historical/backfill behavior는 계속
검증한다. Android JSON -> Windows RAW/normalization/SQLite와 동일 파일 duplicate 재수집은 통과했다.

Home-use OAuth는 Professional 결과 경로로 사용하지 않는다. InBody는 공식 개발자 페이지에서
Professional 장비의 Web API와 home-use 데이터용 OAuth API를 구분한다. private mobile endpoint,
password replay, scraping, APK 분석, MITM, root/private storage 접근은 후보에서 제외한다.

## Target flow already confirmed

Professional 측정 결과가 InBody App으로 들어오는 단계는 공식 확인되었다. 한국 InBody FAQ는
InBody270/370S/470/570/620/770/970/BWA2.0 및 LookinBody120에서, 장비 Cloud/인터넷 설정과 측정 시
휴대전화번호를 사용해 App으로 전송할 수 있다고 설명한다.

Source: [InBody Korea FAQ](https://inbody.co.kr/faq/?lst_category=%EC%9D%B8%EB%B0%94%EB%94%94)

## Evidence matrix

각 셀은 `CONFIRMED`, `NOT SUPPORTED`, `UNKNOWN`, `REQUIRES LIVE VERIFICATION` 중 하나다.
`Personal`은 일반 개인 사용자가 target Professional 결과에 접근 가능한가를 뜻한다.

| Access path | Auto | Personal | SMM | Weight | PBF/BFM | Historical | Supported |
|---|---|---|---|---|---|---|---|
| InBody App -> Samsung Health Data SDK | CONFIRMED | CONFIRMED | CONFIRMED | REQUIRES LIVE VERIFICATION | REQUIRES LIVE VERIFICATION | UNKNOWN | CONFIRMED |
| InBody App -> Health Connect | UNKNOWN | UNKNOWN | NOT SUPPORTED | REQUIRES LIVE VERIFICATION | REQUIRES LIVE VERIFICATION | UNKNOWN | UNKNOWN |
| InBody App machine-readable export | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Samsung Health personal-data download | NOT SUPPORTED | CONFIRMED | REQUIRES LIVE VERIFICATION | REQUIRES LIVE VERIFICATION | REQUIRES LIVE VERIFICATION | REQUIRES LIVE VERIFICATION | CONFIRMED |
| Health Connect scheduled export | CONFIRMED | CONFIRMED | NOT SUPPORTED | REQUIRES LIVE VERIFICATION | REQUIRES LIVE VERIFICATION | CONFIRMED | CONFIRMED |
| LookinBody Web API | CONFIRMED | NOT SUPPORTED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED |
| LB120 configured-folder CSV | CONFIRMED | NOT SUPPORTED | CONFIRMED | CONFIRMED | CONFIRMED | UNKNOWN | CONFIRMED |
| Professional device USB Excel export | NOT SUPPORTED | NOT SUPPORTED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED | CONFIRMED |
| Home-use OAuth API | UNKNOWN | NOT SUPPORTED | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | CONFIRMED |
| Private App endpoint / scraping | NOT SUPPORTED | NOT SUPPORTED | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | NOT SUPPORTED |

Notes:

- 사용자의 Professional 결과가 Samsung Health Body Composition에 나타나고 SDK에서 SMM을 읽는 경로는
  live 확인됐다. 표의 weight/PBF/BFM과 historical은 아직 presence를 기록하지 않아 확인 상태를 올리지
  않았다. 이 확인은 현재 사용자 환경의 evidence이며 모든 지역/App/device 조합을 보장하지 않는다.
- Health Connect's platform supports Weight and PBF records; whether the classic InBody App writes them is
  unknown. Its current public body-measurement record set has no SMM or BFM record.
- The InBody terms permit a user to export/download their own content, but no public App CSV/JSON/Excel
  workflow or schema was found. Therefore machine-readable App export remains `UNKNOWN`; the individual
  metric cells also remain `UNKNOWN`.
- LookinBody/LB120/device export is facility-controlled and is not a personal connector primary path.

## Samsung Health result

Samsung's current `BodyCompositionType` is structurally sufficient for muscle50's minimum useful record.
One data point has mandatory `uid`, `startTime`, `zoneOffset`, `dataSource`, and weight. Optional fields include
body-fat percentage, body-fat mass, fat-free mass, skeletal-muscle mass in kilograms, total body water, BMR,
and BMI. The SDK supports change reads. This is materially better than grouping separate Health Connect
records because it preserves one body-composition record and its source identity.

InBody's official privacy policy lists Samsung Health integration fields as weight, height, BMR, BFM, FFM,
SMM, and PBF. Public material alone did not prove transfer direction, but the user's Galaxy now confirms a
Professional result can be read as Body Composition and that SMM is populated. `DataSource.appId`, UID
stability, other metric presence, backfill, and Windows import remain separate live gates.

A read-only companion requires user consent. A publicly distributed companion also requires Samsung partner
approval and registration of package name/signing certificate; Samsung developer mode is test-only and must
not be presented as an end-user setup.

Sources:

- [Samsung BodyCompositionType](https://developer.samsung.com/health/data/api-reference/-shd/com.samsung.android.sdk.health.data.request/-data-type/-body-composition-type/index.html)
- [Samsung Health Data SDK app verification](https://developer.samsung.com/health/data/guide/app-verification.html)
- [Samsung Health data permission](https://developer.samsung.com/health/data/guide/features/data-permission.html)
- [InBody privacy policy, integrated technologies](https://shop.inbodyusa.com/policies/privacy-policy)
- [InBody 2026 service/app terms](https://inbodyusa.com/inbody-service-and-app-terms-and-conditions/)

## Health Connect result

Current official SDK names are `WeightRecord`, `BodyFatRecord`, `LeanBodyMassRecord`, `BodyWaterMassRecord`,
`BoneMassRecord`, and `BasalMetabolicRateRecord`. There is no dedicated skeletal-muscle-mass, body-fat-mass,
or BMI record in the documented body-measurement set. `LeanBodyMassRecord` must not be treated as InBody SMM.

Health Connect records have record-local metadata/identity and data origin. Weight, PBF, and lean mass would
be separate records. Without an InBody-provided common client record ID or another explicit relationship,
grouping by timestamp is a versioned heuristic and cannot prove a single Professional measurement. The
classic InBody App's Health Connect WRITE support was not found in public official documentation.

Sources:

- [Android Health Connect data types](https://developer.android.com/health-and-fitness/health-connect/data-types)
- [Health Connect Metadata](https://developer.android.com/reference/androidx/health/connect/client/records/metadata/Metadata)
- [Health Connect overview and user control](https://support.google.com/android/answer/13770320)

## Export and portability result

- Samsung officially provides `Samsung Health > Settings > Download personal data`. The export's current
  body-composition filenames/schema and inclusion of InBody-origin Professional records require inspection.
- Android 14+ Health Connect supports scheduled zip export/import. This is a portability/backup path, not
  evidence that classic InBody writes target records, and cannot create an SMM record type that Health
  Connect does not have.
- InBody App publicly documents viewing/sharing results and the terms grant personal export/download rights,
  but no public machine-readable App export format was confirmed.
- PDF/result-sheet/image can be preserved as evidence but OCR is not implemented and is not an authoritative
  numeric production source in this phase.

Sources:

- [Samsung Health personal-data download](https://www.samsung.com/us/support/answer/ANS10001379/)
- [Health Connect backup and scheduled export](https://support.google.com/android/answer/15323271)
- [InBody App terms](https://inbodyusa.com/inbody-service-and-app-terms-and-conditions/)

## Facility-controlled alternatives

InBody officially offers Professional Web API, Open Protocol, LookinBody120 CSV/result image, LBS, and device
exports. LookinBody Web API requires an active paid LB Web account, application approval, API key, server IP,
and webhook configuration. These paths can be full fidelity, but require the gym/facility administrator and
are therefore fallback/cooperation paths rather than the personal connector.

Sources:

- [InBody data integration options](https://developers.inbody.com/en/data)
- [LookinBody Web API key setup](https://lbwebfaq.inbodyusa.com/support/solutions/articles/69000848771-lb-web-integration-api-key-setup)
- [LookinBody120 CSV/image export](https://support.inbody.com/product/contents/lb120)

## Recommended production source and gate

1. **Live-validated primary: Samsung Health Data SDK companion.** Professional Body Composition read and SMM
   presence, `dataSource.appId=com.inbody2014.inbody`, metric presence report, and actual JSON -> Windows
   duplicate-safe import passed on the user's Galaxy/Windows environment. Production classification uses that
   exact app ID only. Public distribution still requires Samsung partner/signature registration.
2. **Partial candidate: Health Connect.** Weight/PBF can be useful if classic InBody WRITE is observed, but
   missing SMM means it cannot satisfy full InBody sync. Never substitute lean mass.
3. **Export-assisted candidate:** inspect Samsung personal-data export or an official InBody machine-readable
   export. Implement a watched-folder importer only after a versioned, synthetic/redacted format sample is
   available.
4. **Facility fallback:** request LookinBody/LB120/API/export cooperation from the gym.

## Galaxy smoke status and remaining checks (no values collected)

Confirmed on the user's Galaxy:

- Professional InBody result is present in Samsung Health.
- The diagnostic companion reads a Body Composition record through the actual Samsung Health Data SDK.
- `skeletal muscle mass: present`.
- The project builds with the locally supplied Samsung Health Data SDK AAR.

Still to record as presence metadata only: `dataSource.appId`, UID stability, weight, BFM, PBF, BMI, TBW,
BMR, and historical/backfill behavior.

1. InBody App에서 target Professional 결과가 보이는지 확인하고 App의 공식 Samsung Health/Health Connect
   integration 설정이 있으면 사용자가 직접 활성화한다.
2. Samsung Health의 Body composition 화면에서 같은 측정 시각의 entry가 생성되는지만 확인한다.
3. Health Connect의 `App permissions`, `Data and access`, `Recent access`에서 InBody가 연결 앱인지와
   Weight/Body fat/Lean body mass entry를 썼는지 확인한다.
4. Samsung Health `Download personal data`를 실행해 export에 body-composition 파일이 있는지와 파일
   형식/헤더만 기록한다. 실제 수치는 공유하거나 Git에 넣지 않는다.
5. UI로 source/fields를 확인할 수 없을 때만, 개발 단계에서 Samsung 공식 Data Viewer 또는 최소
   read-only spike를 사용한다. 다음 presence metadata만 기록한다: `uid`, `startTime`, `zoneOffset`,
   `dataSource.packageName`, weight/SMM/BFM/PBF field yes/no 및 unit. 실제 값은 기록하지 않는다.
6. 새 Professional 측정과 기존 과거 측정을 각각 확인해 신규 전송과 historical backfill을 구분한다.
7. 권한을 해제해 permission-revoked 동작을 확인한다. developer mode는 production 사용자 설정으로
   사용하지 않는다.

Smoke report template:

```text
source application: present/absent (package name may be locally retained)
record type: BodyCompositionType present/absent
timestamp + zone offset: present/absent
weight kg: field present/absent
SMM kg: field present/absent
BFM kg: field present/absent
PBF %: field present/absent
historical result: present/absent
new result: present/absent
```

## Minimal Android bridge after the gate

The companion would request read-only Body Composition permission, preserve Samsung `uid`, timestamp,
zone offset, data source/application/device and available fields, and send only user-authorized records to a
paired local muscle50 ingestion boundary. It must not access InBody credentials, cookies, tokens, private app
storage, or unrelated Samsung Health records. Transport should be either an explicitly shared signed file or
a paired TLS channel; pairing secret belongs in Android Keystore/Windows credential storage, not SQLite.

The exact InBody package/source filter must come from the smoke test. It must not be guessed. Samsung UID plus
source application/profile is the source-local identity. Updated source data produces a new immutable RAW
artifact linked to the same source identity; normalized values remain immutable pending explicit correction.

### Authentication and unattended reuse

The recommended Samsung path does not log muscle50 into the InBody App and needs no InBody ID/password,
OAuth token, or cookie. The user grants the companion read permission through Samsung Health; the OS-managed
grant can be reused across syncs until the user revokes it. Permission denial, later revocation, Samsung Health
unavailability, and source schema change are separate safe errors. Production distribution additionally needs
Samsung's app/package/signature approval, but that registration material is not a user's health credential.

If a later official network source is approved, `AuthenticatedInBodySource` can reuse/refresh an opaque cached
session. It must store any secret only in platform-protected local storage and never in source, CLI arguments,
fixtures, logs, exceptions, or measurement SQLite. No such network adapter or secret storage is activated now.

## Questions that remain for InBody/Samsung

- Is Professional-to-Samsung behavior consistent across regions/App versions, and is it controlled by the
  user, the facility's LookinBody configuration, or both?
- Which fields, device models, regions, and App versions are supported, and is history backfilled?
- What package/data source identifies these records, and how are update/delete events represented?
- Does the App expose a documented CSV/JSON/Excel personal export and versioned schema?
- Can a local/personal companion obtain Samsung Health Data SDK production registration and Body Composition
  read scope?
