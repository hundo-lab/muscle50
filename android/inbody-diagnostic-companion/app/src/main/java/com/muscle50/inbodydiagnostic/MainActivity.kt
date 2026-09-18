package com.muscle50.inbodydiagnostic

import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import com.muscle50.inbodydiagnostic.databinding.ActivityMainBinding
import com.samsung.android.sdk.health.data.data.HealthDataPoint
import com.samsung.android.sdk.health.data.request.DataType.BodyCompositionType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Diagnostic-only screen (Phase 5/6): connect, request Body Composition read permission, show
 * presence-only status for the most recent candidate record, and export the versioned JSON
 * payload for manual transfer to the Windows muscle50 side.
 */
class MainActivity : ComponentActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var diagnostic: SamsungHealthDiagnostic
    private var lastPoints: List<HealthDataPoint> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        diagnostic = SamsungHealthDiagnostic(this)

        binding.connectButton.setOnClickListener { connectAndRead() }
        binding.exportButton.setOnClickListener { exportDiagnosticJson() }
    }

    private fun connectAndRead() {
        clearPreviousResult()
        binding.statusText.text = "Samsung Health connection: connecting..."
        lifecycleScope.launch {
            try {
                // The suspend SDK call returns the updated permission set after Samsung Health's
                // consent UI completes. Do not immediately poll again and risk a false negative.
                if (!diagnostic.ensureReadPermission(this@MainActivity)) {
                    binding.statusText.text = "Samsung Health connection: permission not granted"
                    return@launch
                }
                val points = withContext(Dispatchers.IO) { diagnostic.readRecentBodyComposition() }
                lastPoints = points
                binding.statusText.text = "Samsung Health connection: OK"
                binding.recordCountText.text = "Body composition records found: ${points.size}"
                binding.exportButton.isEnabled = points.isNotEmpty()
                renderCandidateSummary(points.firstOrNull())
            } catch (exc: Exception) {
                // Fixed, redacted status text; never include exc.message verbatim, since SDK
                // exceptions are not guaranteed to exclude device/account-adjacent detail.
                clearPreviousResult()
                binding.statusText.text = "Samsung Health connection: FAIL"
                android.util.Log.w("InBodyDiagnostic", "Samsung Health read failed: ${exc.javaClass.simpleName}")
            }
        }
    }

    private fun clearPreviousResult() {
        lastPoints = emptyList()
        binding.exportButton.isEnabled = false
        binding.recordCountText.text = ""
        binding.candidateSummaryText.text = ""
    }

    private fun renderCandidateSummary(point: HealthDataPoint?) {
        if (point == null) {
            binding.candidateSummaryText.text = "(no candidate record)"
            return
        }
        val presence = diagnostic.presenceOf(point)
        logPresenceOnly(presence)
        val showValues = binding.showValuesToggle.isChecked
        binding.candidateSummaryText.text = buildString {
            appendLine("source application: ${presenceLabel(presence.hasSourceApplication)}")
            appendLine("record UID: ${presenceLabel(presence.hasUid)}")
            appendLine("timestamp: present")
            appendLine("zone offset: ${presenceLabel(presence.hasZoneOffset)}")
            appendLine()
            // BodyCompositionType's mass/percent/BMI fields are Field<Float> and
            // BASAL_METABOLIC_RATE is Field<Int>, never Field<Double>; presenceLabel takes
            // Double?, so every value is widened explicitly with .toDouble().
            appendLine("weight: ${presenceLabel(presence.hasWeight, showValues, point.getValue(BodyCompositionType.WEIGHT)?.toDouble())}")
            appendLine("skeletal muscle mass: ${presenceLabel(presence.hasSkeletalMuscleMass, showValues, point.getValue(BodyCompositionType.SKELETAL_MUSCLE_MASS)?.toDouble())}")
            appendLine("body fat mass: ${presenceLabel(presence.hasBodyFatMass, showValues, point.getValue(BodyCompositionType.BODY_FAT_MASS)?.toDouble())}")
            appendLine("body fat percentage: ${presenceLabel(presence.hasBodyFatPercent, showValues, point.getValue(BodyCompositionType.BODY_FAT)?.toDouble())}")
            appendLine("BMI: ${presenceLabel(presence.hasBmi, showValues, point.getValue(BodyCompositionType.BODY_MASS_INDEX)?.toDouble())}")
            appendLine("total body water: ${presenceLabel(presence.hasTotalBodyWater, showValues, point.getValue(BodyCompositionType.TOTAL_BODY_WATER)?.toDouble())}")
            appendLine("BMR: ${presenceLabel(presence.hasBasalMetabolicRate, showValues, point.getValue(BodyCompositionType.BASAL_METABOLIC_RATE)?.toDouble())}")
            append("fat-free mass: ${presenceLabel(presence.hasFatFreeMass, showValues, point.getValue(BodyCompositionType.FAT_FREE_MASS)?.toDouble())}")
        }
    }

    private fun presenceLabel(present: Boolean, showValue: Boolean = false, value: Double? = null): String {
        if (!present) return "absent"
        return if (showValue && value != null) "present ($value)" else "present"
    }

    private fun exportDiagnosticJson() {
        val profileKey = ProfileKeyStore.getOrCreate(this)
        val envelope = diagnostic.buildExportEnvelope(lastPoints, profileKey, packageName)
        val file = File(getExternalFilesDir(null), "inbody_samsung_health_export_${System.currentTimeMillis()}.json")
        file.writeText(envelope.toString(2))
        Toast.makeText(this, "Exported: ${file.absolutePath}", Toast.LENGTH_LONG).show()
    }
}
