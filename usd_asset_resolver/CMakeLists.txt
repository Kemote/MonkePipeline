cmake_minimum_required(VERSION 3.12)
project(monke_resolver)

# 1. Force C++17 (Modern standard for OpenUSD / Omniverse / Houdini 20+)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# 2. Locate your local OpenUSD installation
# You can override this path by passing -Dpxr_DIR="/path/to/usd" to cmake.
# By default, we search the system/environment paths.
# USD's MaterialX/garch targets reference OpenGL::GL and X11::X11 in their link
# interface, so those packages must be found before find_package(pxr) or CMake
# fails to resolve the imported targets.
find_package(OpenGL REQUIRED)
find_package(X11 REQUIRED)
find_package(pxr REQUIRED)
find_package(CURL REQUIRED)

# 3. Include USD header directories so the compiler finds "pxr/usd/ar/..."
include_directories(${PXR_INCLUDE_DIRS})

# 4. Define our dynamic library (.dll on Windows, .so on Linux, .dylib on macOS)
add_library(monke_resolver SHARED
    monke_resolver.cpp
    resolver_db.h
    resolver_db.cpp
    resolver_disk.h
    resolver_disk.cpp
)

# 5. Link against the necessary OpenUSD core libraries.
# Only the Ar module (and its own transitive deps) is actually used here -
# linking the full ${PXR_LIBRARIES} pulls in unrelated Hydra/imaging targets
# like garch, which in prebuilt distributions (e.g. UsdRoot) can carry
# hardcoded link paths baked in from a different build machine.
target_link_libraries(monke_resolver PRIVATE ar CURL::libcurl)

# 6. Configure compiler-specific flags for plugins
if(MSVC)
    # Windows: Export symbols so USD can locate the class loader
    target_compile_options(monke_resolver PRIVATE /wd4244 /wd4305)
else()
    # Linux/macOS: Standard position-independent code for shared objects
    target_compile_options(monke_resolver PRIVATE -fPIC)
endif()

# 7. Automatically copy plugInfo.json into the build output folder next to the library
configure_file(
    ${CMAKE_CURRENT_SOURCE_DIR}/plugInfo.json 
    ${CMAKE_CURRENT_BINARY_DIR}/plugInfo.json 
    COPYONLY
)