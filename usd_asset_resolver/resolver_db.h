#pragma once // This is a preprocessor directive. It prevents the compiler from 
             // accidentally loading ("including") this header file more than once.

#include "pxr/pxr.h"               // Brings in foundational OpenUSD macros.
#include "pxr/usd/ar/resolver.h"  // Brings in the parent "ArResolver" class.
#include <string>                  // Standard C++ library to use text strings.

// USD wraps all of its code inside a "namespace" (like a folder) called "pxr" 
// to prevent code naming conflicts. This macro says "we are using the pxr folder".
PXR_NAMESPACE_USING_DIRECTIVE

// We define our own class "MonkeDbResolver" which inherits from "ArResolver".
// "public" means external USD code is allowed to treat us as an ArResolver.
class MonkeDbResolver : public ArResolver {
    public:
        // Constructor: This is called when the class is first created.
        // "= default" tells the compiler to just generate the basic, standard initializer.
        MonkeDbResolver() = default;

        // Destructor: This is called when the class is destroyed and cleaned up.
        // "virtual" ensures that when USD cleans up this object through a base pointer,
        // it correctly runs our cleanup code first, preventing memory leaks.
        virtual ~MonkeDbResolver() = default;

    protected: // "protected" means only this class (or classes that inherit from it) can run these functions.
        
        // 1. Convert any incoming raw string into a clean, unique USD identifier.
        // - "override" tells the compiler: "This function MUST match the exact signature in the parent ArResolver."
        // - "const" at the end guarantees this function will not modify any variables inside this class.
        //   This is extremely important because USD runs this function across multiple threads at the same time.
        std::string _CreateIdentifier(
            const std::string& assetPath,              // "const &" means: pass the string by reference (fast) and don't allow modifying it.
            const ArResolvedPath& anchorAssetPath     // The resolved path of the parent layer that called this asset.
        ) const override;

        // 2. The core "workhorse". This takes the identifier and translates it to a real file on your hard drive.
        ArResolvedPath _Resolve(
            const std::string& assetPath
        ) const override;

        // 3. Tells USD how to read the raw binary data.
        // - "std::shared_ptr" is a C++ "smart pointer". It manages memory for us. It keeps track of how many
        //   places are reading this asset, and automatically deletes the memory when that number hits zero (no manual "delete" needed).
        std::shared_ptr<ArAsset> _OpenAsset(
            const ArResolvedPath& resolvedPath
        ) const override;

        // 4. Same as _CreateIdentifier, but for an asset that doesn't exist on disk yet
        // (e.g. USD is about to write out a brand-new layer for the first time).
        std::string _CreateIdentifierForNewAsset(
            const std::string& assetPath,
            const ArResolvedPath& anchorAssetPath
        ) const override;

        // 5. Same as _Resolve, but for locating where a new (not-yet-written) asset should go.
        ArResolvedPath _ResolveForNewAsset(
            const std::string& assetPath
        ) const override;

        // 6. Tells USD how to open a writable stream for saving data to an asset.
        std::shared_ptr<ArWritableAsset> _OpenAssetForWrite(
            const ArResolvedPath& resolvedPath,
            WriteMode writeMode
        ) const override;
    };