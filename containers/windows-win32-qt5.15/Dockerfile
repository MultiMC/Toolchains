# syntax=docker/dockerfile:1
# MultiMC win32-5.15.2 toolchain: the win32 image plus the old Win7 build VM's second Qt,
# Qt 5.15.2 mingw81_32 with MinGW 8.1.0 and Qt's OpenSSL 1.1 and the VC++ 2010 runtime it
# needs, at the VM's paths under $TOOLS/QtX (C:\QtX on the VM). Everything else
# (GE-Proton, the Wine prefix, CMake 3.20.1, GnuWin32 zlib, dumpbin, the JDK) is the win32
# image's.
#
# The toolchain comes from the win32 image's Tools/ tree (hash-verified against the VM disk),
# as named build contexts, so it isn't copied twice:
#
#   docker buildx build -t multimc/toolchains/windows-win32-qt5.15:dev \
#       --build-context qt=../windows-win32/Tools/QtX/5.15.2/mingw81_32 \
#       --build-context mingw=../windows-win32/Tools/QtX/Tools/mingw810_32 \
#       --build-context openssl=../windows-win32/Tools/QtX/Tools/OpenSSL/Win_x86/bin \
#       --build-context vcredist=../windows-win32/Tools/QtX/vcredist \
#       --load .

# multimc/toolchains/windows-win32:dev as published on 2026-10-30
FROM ghcr.io/multimc/toolchains/windows-win32@sha256:f5712d15020fa1162344a8e076e6ba51e27914639237b5161031417aeb679378

COPY --from=qt . /opt/win32/Tools/QtX/5.15.2/mingw81_32
COPY --from=mingw . /opt/win32/Tools/QtX/Tools/mingw810_32
# Only the DLLs the Launcher bundles, as the VM's build copied them
COPY --from=openssl libcrypto-1_1.dll libssl-1_1.dll /opt/win32/Tools/QtX/Tools/OpenSSL/Win_x86/bin/
# Qt's OpenSSL 1.1 needs the Visual C++ 2010 runtime (msvcr100.dll), which the VM's build
# didn't bundle. Taken out of the redistributable Qt's installer put next to it (VC++ 2010
# SP1, 10.0.40219.1): the installer holds vc_red.cab, which holds the DLL.
COPY --from=vcredist vcredist_x86.exe /tmp/vcredist/
RUN cd /tmp/vcredist \
    && echo "67313b3d1bc86e83091e8de22981f14968f1a7fb12eb7ad467754c40cd94cc3d  vcredist_x86.exe" | sha256sum -c \
    && bsdtar -xf vcredist_x86.exe \
    && bsdtar -xf vc_red.cab F_CENTRAL_msvcr100_x86 \
    && mkdir -p /opt/win32/Tools/QtX/vcredist/x86 \
    && mv F_CENTRAL_msvcr100_x86 /opt/win32/Tools/QtX/vcredist/x86/msvcr100.dll \
    && echo "60c06e0fa4449314da3a0a87c1a9d9577df99226f943637e06f61188e5862efa  /opt/win32/Tools/QtX/vcredist/x86/msvcr100.dll" | sha256sum -c \
    && cd / && rm -rf /tmp/vcredist
RUN chmod -R a+rX /opt/win32/Tools/QtX

LABEL org.opencontainers.image.title="MultiMC win32-5.15.2 toolchain (GE-Proton10-15, Qt 5.15.2, MinGW 8.1.0)"
