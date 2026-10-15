plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "com.bobstevens.kotassium"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.bobstevens.kotassium"
        minSdk = 24
        targetSdk = 34
        versionCode = 32
        versionName = "1.0.32"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }

    // Keep the existing source layout (no src/main move): the app predates Gradle.
    sourceSets["main"].apply {
        java.srcDirs("src")
        res.srcDirs("res")
        assets.srcDirs("assets")
        manifest.srcFile("AndroidManifest.xml")
    }

    // Same debug key as the released APKs, so updates install over existing versions.
    signingConfigs {
        create("kotassium") {
            storeFile = file("../build/debug.keystore")
            storePassword = "android"
            keyAlias = "kotassium"
            keyPassword = "android"
        }
    }
    buildTypes {
        getByName("debug") { signingConfig = signingConfigs.getByName("kotassium") }
        getByName("release") { signingConfig = signingConfigs.getByName("kotassium") }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        buildPython("/home/bobstevens/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu/bin/python3.12")
        pip {
            install("yt-dlp")
        }
        sourceSets {
            getByName("main") { srcDir("python") }
        }
    }
}
