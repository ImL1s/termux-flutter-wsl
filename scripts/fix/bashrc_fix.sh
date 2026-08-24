#!/bin/sh
# Flutter & Android SDK Configuration
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
[ -f "$PREFIX/etc/profile.d/flutter.sh" ] && . "$PREFIX/etc/profile.d/flutter.sh"
export ANDROID_HOME="$PREFIX/opt/android-sdk"
if [ -z "${JAVA_HOME:-}" ] && [ -d "$PREFIX/lib/jvm" ]; then
    _jvm=$(find "$PREFIX/lib/jvm" -maxdepth 1 -type d -name 'java-*-openjdk' 2>/dev/null | sort -V | tail -1)
    [ -n "$_jvm" ] && export JAVA_HOME="$_jvm"
    unset _jvm
fi
export PATH="${PATH}:${ANDROID_HOME}/platform-tools:${ANDROID_HOME}/cmdline-tools/latest/bin"
