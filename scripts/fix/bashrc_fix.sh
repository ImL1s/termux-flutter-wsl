#!/bin/sh
# Flutter & Android SDK Configuration
export ANDROID_HOME=$PREFIX/opt/android-sdk
if [ -z "${JAVA_HOME:-}" ] && [ -d "$PREFIX/lib/jvm" ]; then
    export JAVA_HOME=$(find "$PREFIX/lib/jvm" -maxdepth 1 -type d -name 'java-*-openjdk' 2>/dev/null | sort -V | tail -1)
fi
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin
