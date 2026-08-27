#pragma once

#include "pxr/pxr.h"
#include "pxr/usd/ar/resolver.h"
#include <string>

PXR_NAMESPACE_USING_DIRECTIVE

// resolves monkeDisc:// paths to versioned files on local disk
class MonkeDiskResolver : public ArResolver {
    public:
        MonkeDiskResolver() = default;
        virtual ~MonkeDiskResolver() = default;

    protected:
        std::string _CreateIdentifier(
            const std::string& assetPath,
            const ArResolvedPath& anchorAssetPath
        ) const override;

        ArResolvedPath _Resolve(
            const std::string& assetPath
        ) const override;

        std::shared_ptr<ArAsset> _OpenAsset(
            const ArResolvedPath& resolvedPath
        ) const override;

        std::string _CreateIdentifierForNewAsset(
            const std::string& assetPath,
            const ArResolvedPath& anchorAssetPath
        ) const override;

        ArResolvedPath _ResolveForNewAsset(
            const std::string& assetPath
        ) const override;

        std::shared_ptr<ArWritableAsset> _OpenAssetForWrite(
            const ArResolvedPath& resolvedPath,
            WriteMode writeMode
        ) const override;
};
