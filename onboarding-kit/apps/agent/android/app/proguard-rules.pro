# OnboardKit Agent — R8/ProGuard keep rules for the release build.
# The Flutter Gradle plugin supplies embedding rules; these cover the plugins
# this app uses (image_picker, flutter_secure_storage) and silence warnings for
# optional deps R8 cannot see.

# Flutter engine / embedding.
-keep class io.flutter.** { *; }
-keep class io.flutter.plugins.** { *; }
-dontwarn io.flutter.embedding.**

# flutter_secure_storage uses AndroidX security-crypto (Tink under the hood).
-keep class androidx.security.crypto.** { *; }
-dontwarn com.google.crypto.tink.**

# image_picker delegates to platform intents — keep its plugin surface.
-keep class io.flutter.plugins.imagepicker.** { *; }
