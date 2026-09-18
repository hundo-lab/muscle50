package com.muscle50.inbodydiagnostic

import android.content.Context
import android.util.Log
import com.samsung.android.sdk.health.data.HealthDataService
import com.samsung.android.sdk.health.data.HealthDataStore
import com.samsung.android.sdk.health.data.data.HealthDataPoint
import com.samsung.android.sdk.health.data.permission.AccessType
import com.samsung.android.sdk.health.data.permission.Permission
import com.samsung.android.sdk.health.data.request.DataTypes
import com.samsung.android.sdk.health.data.request.Ordering
import com.samsung.android.sdk.health.data.request.LocalTimeFilter
import com.samsung.android.sdk.health.data.request.DataType.BodyCompositionType
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDateTime
import java.time.ZoneOffset

/**
 * Diagnostic-only wrapper around the Samsung Health Data SDK's BodyCompositionType read path.
 *
 * Class/method names below (HealthDataService.getStore, Permission.of, getGrantedPermissions,
 * requestPermissions, DataTypes.BODY_COMPOSITION.readDataRequestBuilder, healthDataStore.readData,
 * HealthDataPoint.uid/startTime/zoneOffset/dataSource/getValue) were confirmed against Samsung's
 * public API reference, the locally linked 1.1.0 AAR, and a successful Android Studio build
 * (see docs/samsung-health-payload-contract.md and README.md).
 *
 * This class never logs an actual health value. It never reads anything except
 * DataTypes.BODY_COMPOSITION, and never requests AccessType.WRITE.
 */
private const val TAG = "InBodyDiagnostic"
private const val LOOKBACK_DAYS = 400L
private const val MAX_RECORDS = 20

/** Presence-only view of one Samsung BodyCompositionType point (Phase 6 diagnostic screen). */
data class RecordPresence(
    val hasSourceApplication: Boolean,
    val hasUid: Boolean,
    val hasZoneOffset: Boolean,
    val hasWeight: Boolean,
    val hasSkeletalMuscleMass: Boolean,
    val hasBodyFatMass: Boolean,
    val hasBodyFatPercent: Boolean,
    val hasBmi: Boolean,
    val hasTotalBodyWater: Boolean,
    val hasBasalMetabolicRate: Boolean,
    val hasFatFreeMass: Boolean,
)

class SamsungHealthDiagnostic(context: Context) {

    private val appContext = context.applicationContext
    private val healthDataStore: HealthDataStore = HealthDataService.getStore(appContext)

    private val bodyCompositionPermission: Permission =
        Permission.of(DataTypes.BODY_COMPOSITION, AccessType.READ)

    suspend fun hasGrantedPermission(): Boolean {
        val granted = healthDataStore.getGrantedPermissions(setOf(bodyCompositionPermission))
        return granted.contains(bodyCompositionPermission)
    }

    /**
     * Return the permission state produced by Samsung Health's consent UI.
     *
     * requestPermissions is a suspend API and its returned Set is the updated permission state.
     * Using that result avoids an immediate second getGrantedPermissions call racing the UI/state
     * propagation. A later revocation is still handled safely by the subsequent read failure.
     */
    suspend fun ensureReadPermission(activity: android.app.Activity): Boolean {
        if (hasGrantedPermission()) {
            return true
        }
        val updated = healthDataStore.requestPermissions(setOf(bodyCompositionPermission), activity)
        return updated.contains(bodyCompositionPermission)
    }

    /**
     * Reads the most recent Body Composition points (newest first), bounded to
     * [LOOKBACK_DAYS]/[MAX_RECORDS] so a diagnostic run stays bounded and read-only.
     */
    suspend fun readRecentBodyComposition(): List<HealthDataPoint> {
        val end = LocalDateTime.now()
        val start = end.minusDays(LOOKBACK_DAYS)
        val timeFilter = LocalTimeFilter.of(start, end)
        val request = DataTypes.BODY_COMPOSITION.readDataRequestBuilder
            .setLocalTimeFilter(timeFilter)
            .setOrdering(Ordering.DESC)
            .build()
        val result = healthDataStore.readData(request)
        return result.dataList.take(MAX_RECORDS)
    }

    fun presenceOf(point: HealthDataPoint): RecordPresence = RecordPresence(
        hasSourceApplication = point.dataSource?.appId != null,
        hasUid = point.uid.isNotBlank(),
        hasZoneOffset = point.zoneOffset != null,
        hasWeight = point.getValue(BodyCompositionType.WEIGHT) != null,
        hasSkeletalMuscleMass = point.getValue(BodyCompositionType.SKELETAL_MUSCLE_MASS) != null,
        hasBodyFatMass = point.getValue(BodyCompositionType.BODY_FAT_MASS) != null,
        hasBodyFatPercent = point.getValue(BodyCompositionType.BODY_FAT) != null,
        hasBmi = point.getValue(BodyCompositionType.BODY_MASS_INDEX) != null,
        hasTotalBodyWater = point.getValue(BodyCompositionType.TOTAL_BODY_WATER) != null,
        hasBasalMetabolicRate = point.getValue(BodyCompositionType.BASAL_METABOLIC_RATE) != null,
        hasFatFreeMass = point.getValue(BodyCompositionType.FAT_FREE_MASS) != null,
    )

    /**
     * Builds the versioned export envelope defined in docs/samsung-health-payload-contract.md.
     * profileKey is a companion-generated opaque UUID (see ProfileKeyStore), never a Samsung
     * account identifier. dataSource.appId is carried through verbatim as provenance only; this
     * method never labels a record as InBody-authored (see Phase 7 / the payload contract).
     */
    fun buildExportEnvelope(
        points: List<HealthDataPoint>,
        profileKey: String,
        companionAppId: String,
    ): JSONObject {
        val records = JSONArray()
        for (point in points) {
            records.put(recordJson(point))
        }
        return JSONObject().apply {
            put("schema", "muscle50.samsung_health.inbody_diagnostic_export.v1")
            put("schema_version", "1")
            put("source_type", "inbody_samsung_health")
            put("exported_at", java.time.Instant.now().toString())
            put("source_sdk_name", "Samsung Health Data SDK")
            put("source_sdk_version", BuildConfig.SAMSUNG_HEALTH_DATA_SDK_VERSION)
            put("profile_key", profileKey)
            put("companion_app_id", companionAppId)
            put("records", records)
        }
    }

    private fun recordJson(point: HealthDataPoint): JSONObject {
        val fields = JSONObject().apply {
            // BodyCompositionType's mass/percent/BMI fields are Field<Float>, and
            // BASAL_METABOLIC_RATE is Field<Int> (confirmed against Samsung's Dokka reference
            // pages) — never Field<Double>. putField takes Double, so every value is widened
            // explicitly with .toDouble() here; passing the raw Float?/Int? would not compile.
            putField(
                this, "weight", point.getValue(BodyCompositionType.WEIGHT)?.toDouble(),
                "kg", "BodyCompositionType.WEIGHT",
            )
            putField(
                this, "skeletal_muscle_mass", point.getValue(BodyCompositionType.SKELETAL_MUSCLE_MASS)?.toDouble(),
                "kg", "BodyCompositionType.SKELETAL_MUSCLE_MASS",
            )
            putField(
                this, "body_fat_mass", point.getValue(BodyCompositionType.BODY_FAT_MASS)?.toDouble(),
                "kg", "BodyCompositionType.BODY_FAT_MASS",
            )
            putField(
                this, "body_fat_percent", point.getValue(BodyCompositionType.BODY_FAT)?.toDouble(),
                "%", "BodyCompositionType.BODY_FAT",
            )
            putField(
                this, "bmi", point.getValue(BodyCompositionType.BODY_MASS_INDEX)?.toDouble(),
                null, "BodyCompositionType.BODY_MASS_INDEX",
            )
            putField(
                this, "basal_metabolic_rate", point.getValue(BodyCompositionType.BASAL_METABOLIC_RATE)?.toDouble(),
                "kcal/day", "BodyCompositionType.BASAL_METABOLIC_RATE",
            )
            putField(
                this, "total_body_water", point.getValue(BodyCompositionType.TOTAL_BODY_WATER)?.toDouble(),
                "L", "BodyCompositionType.TOTAL_BODY_WATER",
            )
            // fat_free_mass is exported for completeness, but see Phase 3/Python adapter: it is
            // never substituted for skeletal_muscle_mass, and muscle50 does not yet map it into a
            // normalized column.
            putField(
                this, "fat_free_mass", point.getValue(BodyCompositionType.FAT_FREE_MASS)?.toDouble(),
                "kg", "BodyCompositionType.FAT_FREE_MASS",
            )
        }
        val zoneOffset: ZoneOffset? = point.zoneOffset
        return JSONObject().apply {
            put("source_record_id", point.uid)
            put("measured_at", point.getStartLocalDateTime().toString())
            // org.json.JSONObject.put(name, null) drops the key instead of writing JSON null,
            // so nullable fields go through JSONObject.NULL explicitly to match the documented
            // contract's "absent key or explicit null both mean absent" reading exactly.
            put("zone_offset", zoneOffset?.toString() ?: JSONObject.NULL)
            put("data_source_app_id", point.dataSource?.appId ?: JSONObject.NULL)
            put("data_source_device_id", point.dataSource?.deviceId ?: JSONObject.NULL)
            put("fields", fields)
        }
    }

    private fun putField(target: JSONObject, name: String, value: Double?, unit: String?, path: String) {
        if (value == null) {
            target.put(name, JSONObject.NULL)
            return
        }
        target.put(
            name,
            JSONObject().apply {
                put("value", value)
                // JSONObject.put(name, null) removes the key. The v1 contract requires an
                // explicit JSON null for unitless fields such as BMI.
                put("unit", unit ?: JSONObject.NULL)
                put("path", path)
            },
        )
    }
}

/** Presence-only, no health values: safe to log at debug level. */
fun logPresenceOnly(presence: RecordPresence) {
    Log.d(
        TAG,
        "uid=${presence.hasUid} zoneOffset=${presence.hasZoneOffset} " +
            "sourceApp=${presence.hasSourceApplication} weight=${presence.hasWeight} " +
            "smm=${presence.hasSkeletalMuscleMass} bfm=${presence.hasBodyFatMass} " +
            "pbf=${presence.hasBodyFatPercent} bmi=${presence.hasBmi} " +
            "tbw=${presence.hasTotalBodyWater} bmr=${presence.hasBasalMetabolicRate} " +
            "ffm=${presence.hasFatFreeMass}",
    )
}
