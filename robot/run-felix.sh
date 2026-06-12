#!/bin/bash
# Chay PolyScope GUI don le (khong co URControl / RTDE)
ROOT=/root/.udocker/containers/b94e91f2-bfd0-3bb8-a65d-569a968f3137/ROOT
JAVA=$ROOT/usr/lib/jvm/jdk1.8.0_371/jre/bin/java
export HOME=/ursim
export DISPLAY=:10.0
export XAUTHORITY=/root/.Xauthority
export QEMU_LD_PREFIX=$ROOT

rm -rf /ursim/GUI/felix-cache 2>/dev/null

cd /ursim/GUI || exit 1
exec $JAVA \
  -Duser.home=/ursim \
  -Dconfig.path=/ursim/.urcontrol \
  -DmockCybersecurityBackend=true \
  "-Djava.library.path=$ROOT/usr/lib/jni" \
  -Dorg.osgi.framework.storage.clean=onFirstInit \
  -jar bin/felix.jar
