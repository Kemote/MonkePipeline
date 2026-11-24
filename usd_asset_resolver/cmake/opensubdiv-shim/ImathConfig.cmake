# Minimal shim so CMake's find_dependency(Imath) succeeds against
# the OpenUSD install (pxr_DIR, set by build.sh), which ships Imath's runtime libs/headers but no
# CMake package config of its own. See OpenSubdivConfig.cmake in this
# same directory for why: linking a different Imath build than the one
# already loaded by the host process causes ABI symbol clashes.

set(_imath_root "${pxr_DIR}")
set(Imath_INCLUDE_DIR "${_imath_root}/include")

if(NOT TARGET Imath::Imath)
    add_library(Imath::Imath SHARED IMPORTED)
    set_target_properties(Imath::Imath PROPERTIES
        IMPORTED_LOCATION "${_imath_root}/lib/libImath.so"
        INTERFACE_INCLUDE_DIRECTORIES "${Imath_INCLUDE_DIR}"
    )
endif()

unset(_imath_root)
