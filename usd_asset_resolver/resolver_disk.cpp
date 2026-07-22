#include "resolver_disk.h"

// Pass-through: return the identifier USD gave us unchanged.
std::string MonkeDiskResolver::_CreateIdentifier(
    const std::string& assetPath,
    const ArResolvedPath& anchorAssetPath) const
{
    return assetPath;
}

// Pass-through: treat the asset path as an already-valid local path.
ArResolvedPath MonkeDiskResolver::_Resolve(const std::string& assetPath) const {
    // test
    std::string test_output = "testTestTest";
    return ArResolvedPath(test_output);
}

// nullptr tells USD to fall back to its default local-disk asset reader.
std::shared_ptr<ArAsset> MonkeDiskResolver::_OpenAsset(const ArResolvedPath& resolvedPath) const {
    return nullptr;
}

std::string MonkeDiskResolver::_CreateIdentifierForNewAsset(
    const std::string& assetPath,
    const ArResolvedPath& anchorAssetPath) const
{
    return assetPath;
}

ArResolvedPath MonkeDiskResolver::_ResolveForNewAsset(const std::string& assetPath) const {
    return ArResolvedPath(assetPath);
}

// nullptr tells USD to fall back to its default local-disk asset writer.
std::shared_ptr<ArWritableAsset> MonkeDiskResolver::_OpenAssetForWrite(
    const ArResolvedPath& resolvedPath,
    WriteMode writeMode) const
{
    return nullptr;
}
