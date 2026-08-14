export PATH=${PREFIX}/opt/flutter/bin:${PATH}
# Force Gradle to use our pre-configured NDK (prevents auto-download of new versions)
if [ -z "$ANDROID_NDK_HOME" ]; then
  for ndk in ${PREFIX}/opt/android-sdk/ndk/*/; do
    [ -d "$ndk" ] && export ANDROID_NDK_HOME="${ndk%/}" && break
  done
fi