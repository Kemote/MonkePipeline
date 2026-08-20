# UsdRoot ships libosdCPU.so.3.6.0 / libosdGPU.so.3.6.0 - report that version
# so find_dependency(OpenSubdiv 3.6.0 CONFIG) in UsdRoot's pxrConfig.cmake succeeds.
set(PACKAGE_VERSION "3.6.0")

if(PACKAGE_VERSION VERSION_LESS PACKAGE_FIND_VERSION)
    set(PACKAGE_VERSION_COMPATIBLE FALSE)
else()
    set(PACKAGE_VERSION_COMPATIBLE TRUE)
    if(PACKAGE_VERSION STREQUAL PACKAGE_FIND_VERSION)
        set(PACKAGE_VERSION_EXACT TRUE)
    endif()
endif()
