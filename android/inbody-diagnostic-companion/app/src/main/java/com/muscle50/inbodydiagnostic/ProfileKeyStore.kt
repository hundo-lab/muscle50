package com.muscle50.inbodydiagnostic

import android.content.Context
import java.util.UUID

/**
 * Generates and persists one opaque profile key per app install.
 *
 * Samsung's SDK does not expose a Samsung account identifier to a read-only companion, and this
 * key must never be an account email/phone number (see docs/inbody-access-decision.md's identity
 * rules and docs/samsung-health-payload-contract.md). A reinstall of this diagnostic app produces
 * a new key; that is acceptable for a diagnostic tool and must be revisited before any production
 * companion relies on stable cross-install identity.
 */
object ProfileKeyStore {
    private const val PREFS_NAME = "inbody_diagnostic_profile"
    private const val KEY_PROFILE_KEY = "profile_key"

    fun getOrCreate(context: Context): String {
        val prefs = context.applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val existing = prefs.getString(KEY_PROFILE_KEY, null)
        if (existing != null) {
            return existing
        }
        val generated = UUID.randomUUID().toString()
        prefs.edit().putString(KEY_PROFILE_KEY, generated).apply()
        return generated
    }
}
