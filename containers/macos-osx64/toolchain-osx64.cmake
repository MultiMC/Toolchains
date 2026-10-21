# CMake toolchain for the osx64-5.15.2 cross build.
# Wraps osxcross's toolchain file; expects OSXCROSS_* in the environment (see build-osx64.sh).
include(/opt/osxcross/toolchain.cmake)

# osxcross only looks for packages inside the SDK. Qt lives outside it (at its original
# macmini path), so let find_package also search CMAKE_PREFIX_PATH as-is. Libraries and
# headers (zlib etc.) still come from the SDK only.
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)
