// Samsung Health Data SDK 1.1.0 requires API 29 or later. The local diagnostic build uses the
// user-supplied AAR under app/libs; that binary is intentionally ignored by Git.
plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("kotlin-parcelize") // required by the Samsung Health Data SDK per its setup guide
}

val samsungHealthDataSdkVersion = "1.1.0"

android {
    namespace = "com.muscle50.inbodydiagnostic"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.muscle50.inbodydiagnostic"
        minSdk = 29
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0-diagnostic"
        buildConfigField("String", "SAMSUNG_HEALTH_DATA_SDK_VERSION", "\"$samsungHealthDataSdkVersion\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
        buildConfig = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.2")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("com.google.android.material:material:1.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // Samsung Health Data SDK: not on Maven Central. The explicit filename makes the version
    // exported in the diagnostic payload the same version Gradle actually links.
    implementation(files("libs/samsung-health-data-api-$samsungHealthDataSdkVersion.aar"))
    implementation("com.google.code.gson:gson:2.10.1")
}
