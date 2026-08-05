#!/bin/sh
# Flutter & Android SDK Configuration
export ANDROID_HOME=$PREFIX/opt/android-sdk
export JAVA_HOME=$PREFIX
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin
