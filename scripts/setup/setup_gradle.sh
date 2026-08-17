#!/data/data/com.termux/files/usr/bin/bash

if [ -z "${JAVA_HOME:-}" ]; then
    export JAVA_HOME=$(find "${PREFIX:-/data/data/com.termux/files/usr}/lib/jvm" -maxdepth 1 -type d -name 'java-*-openjdk' 2>/dev/null | sort -V | tail -1)
fi

# Download Gradle 8.5
echo ">>> Downloading Gradle 8.5..."
cd ~
wget -q https://services.gradle.org/distributions/gradle-8.5-bin.zip

# Extract Gradle
echo ">>> Extracting Gradle..."
mkdir -p ~/.gradle
unzip -q -o gradle-8.5-bin.zip -d ~/.gradle/
rm gradle-8.5-bin.zip

# Add to PATH
export PATH=$PATH:~/.gradle/gradle-8.5/bin

# Verify
echo ">>> Gradle version:"
gradle --version

echo ">>> Done!"
