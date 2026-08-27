cmake_minimum_required(VERSION 3.12)
project(monke_resolver)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# override the OpenUSD install with -Dpxr_DIR=/path/to/usd if needed
#
# USD's MaterialX/garch targets reference OpenGL::GL and X11::X11 in their link
# interface, so those packages must be found before find_package(pxr) or CMake
# fails to resolve the imported targets.
find_package(OpenGL REQUIRED)
find_package(X11 REQUIRED)
find_package(pxr REQUIRED)

include_directories(${PXR_INCLUDE_DIRS})

# pxr/usd/ar/resolverContext.h drags in tf/pyLock.h -> Python.h unconditionally
# (USD's Python bindings are compiled in). When linking against the "ar"
# imported target this comes along automatically via its interface include
# dirs, but the BUILD_FOR_KIT path below doesn't use that target for linking,
# so it must be added explicitly.
find_package(Python3 COMPONENTS Development REQUIRED)
include_directories(${Python3_INCLUDE_DIRS})

add_library(monke_resolver SHARED
    monke_resolver.cpp
    resolver_disk.h
    resolver_disk.cpp
)

# Only the Ar module (and its own transitive deps) is actually used here -
# linking the full ${PXR_LIBRARIES} pulls in unrelated Hydra/imaging targets
# like garch, which in prebuilt distributions (e.g. UsdRoot) can carry
# hardcoded link paths baked in from a different build machine.
#
# When BUILD_FOR_KIT is set, pxr_DIR only supplies matching headers (built
# from the same USD tag Kit ships) - we link directly against Kit's own
# libusd_ar.so instead of our own compiled one, so the plugin shares the
# exact USD binary already loaded in the Kit process instead of pulling in
# a second, separately-built copy of USD (which would duplicate TfType
# registrations and crash).
if(BUILD_FOR_KIT)
    if(NOT KIT_USD_LIBS_DIR)
        message(FATAL_ERROR "KIT_USD_LIBS_DIR must be set (path to Kit's omni.usd.libs 'bin' directory) when BUILD_FOR_KIT=ON")
    endif()
    target_link_libraries(monke_resolver PRIVATE "${KIT_USD_LIBS_DIR}/libusd_ar.so")
else()
    target_link_libraries(monke_resolver PRIVATE ar)
endif()

if(MSVC)
    # silence benign narrowing-conversion warnings (C4244/C4305) from USD's own headers
    target_compile_options(monke_resolver PRIVATE /wd4244 /wd4305)
else()
    target_compile_options(monke_resolver PRIVATE -fPIC)
endif()

# copy plugInfo.json next to the built library so USD can find it
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/plugInfo.json 
    ${CMAKE_CURRENT_BINARY_DIR}/plugInfo.json 
    COPYONLY
)