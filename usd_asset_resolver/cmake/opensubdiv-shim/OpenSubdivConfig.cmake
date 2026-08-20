# Minimal shim so CMake's find_dependency(OpenSubdiv ...) succeeds against
# /home/kemot/UsdRoot, which ships OpenSubdiv's runtime libs/headers but no
# CMake package config of its own. Points at UsdRoot's own copies so the
# resolver plugin links against the exact same build the rest of UsdRoot uses
# (mixing in a different OpenSubdiv build caused ABI symbol clashes before).

set(_osd_root "/home/kemot/UsdRoot")
set(OpenSubdiv_INCLUDE_DIR "${_osd_root}/include")
set(OpenSubdiv_LIB_DIR "${_osd_root}/lib")

if(NOT TARGET OpenSubdiv::osdCPU)
    add_library(OpenSubdiv::osdCPU SHARED IMPORTED)
    set_target_properties(OpenSubdiv::osdCPU PROPERTIES
        IMPORTED_LOCATION "${_osd_root}/lib/libosdCPU.so"
        INTERFACE_INCLUDE_DIRECTORIES "${OpenSubdiv_INCLUDE_DIR}"
    )
endif()

if(NOT TARGET OpenSubdiv::osdGPU)
    add_library(OpenSubdiv::osdGPU SHARED IMPORTED)
    set_target_properties(OpenSubdiv::osdGPU PROPERTIES
        IMPORTED_LOCATION "${_osd_root}/lib/libosdGPU.so"
        INTERFACE_INCLUDE_DIRECTORIES "${OpenSubdiv_INCLUDE_DIR}"
    )
endif()

if(NOT TARGET opensubdiv::opensubdiv)
    add_library(opensubdiv::opensubdiv INTERFACE IMPORTED)
    set_target_properties(opensubdiv::opensubdiv PROPERTIES
        INTERFACE_LINK_LIBRARIES "OpenSubdiv::osdCPU;OpenSubdiv::osdGPU"
        INTERFACE_INCLUDE_DIRECTORIES "${OpenSubdiv_INCLUDE_DIR}"
    )
endif()

unset(_osd_root)
