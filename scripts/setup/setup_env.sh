#!/data/data/com.termux/files/usr/bin/bash
export JAVA_HOME=$(find "${PREFIX:-/data/data/com.termux/files/usr}/lib/jvm" -maxdepth 1 -type d -name 'java-*-openjdk' 2>/dev/null | sort -V | tail -1)
export ANDROID_HOME="${PREFIX:-/data/data/com.termux/files/usr}/opt/android-sdk"
export PATH=$PATH:$ANDROID_HOME/platform-tools
echo "JAVA_HOME=$JAVA_HOME"
echo "ANDROID_HOME=$ANDROID_HOME"
java --version
cd ~/testapp
flutter build apk --debug
