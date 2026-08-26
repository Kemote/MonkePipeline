#include <iostream>
#include <string>
#include <string_view>
#include <filesystem>
#include <fstream>
#include <cstdio>
#include <nlohmann/json.hpp>
#include "resolver_disk.h"


namespace fs = std::filesystem;


// Pass-through: return the identifier USD gave us unchanged.
std::string MonkeDiskResolver::_CreateIdentifier(
    const std::string& assetPath,
    const ArResolvedPath& anchorAssetPath) const
{   
    return assetPath;
}

// Pass-through: treat the asset path as an already-valid local path.
ArResolvedPath MonkeDiskResolver::_Resolve(const std::string& assetPath) const {
    const char* projectsRootEnv = getenv("PROJECTSROOT");
    const char* projectNameEnv = getenv("PROJECTNAME");
    if (!projectsRootEnv || !projectNameEnv) {
        std::cerr << "MonkeDiskResolver: PROJECTSROOT/PROJECTNAME env vars must be set to resolve '"
                  << assetPath << "'" << std::endl;
        return ArResolvedPath();
    }

    size_t versionSep = assetPath.rfind(":");
    std::string versionType = assetPath.substr(versionSep + 1);
    std::string pathBody = assetPath.substr(11, versionSep - 11);
    std::string projectsRoot = projectsRootEnv;
    std::string projectName = projectNameEnv;
    std::string fullPath = projectsRoot + "/" + projectName + pathBody;
    std::string basedir = fullPath;
    

    std::cout << "FULL PATH: " << fullPath << std::endl;
    std::cout << "VERSION TYPE: " << versionType << std::endl;

    size_t versionToken = fullPath.find("<version>");
        
    std::string startName = "";
    std::string endName = "";
    

    int version = 0;
    if (versionToken != std::string_view::npos){
        basedir = fullPath.substr(0, versionToken);
        size_t lastSlash = basedir.rfind("/");
        if (lastSlash != std::string_view::npos){
            startName = fullPath.substr(lastSlash + 1, versionToken - (lastSlash + 1));
            std::string restOfPath = fullPath.substr(versionToken);
            size_t nameSlash = restOfPath.find("/");
            endName = restOfPath.substr(9, nameSlash - 9);
            basedir = basedir.substr(0, lastSlash);
        }
    }

    // now we need to get version
    if (versionType == "latest"){        
        for (const auto& file_path : fs::directory_iterator(basedir)){
            std::string entryName = file_path.path().filename().string();
            if (entryName.size() <= startName.size() + endName.size()) {
                continue;
            }
            if (entryName.compare(0, startName.size(), startName) != 0) {
                continue;
            }
            if (entryName.compare(entryName.size() - endName.size(), endName.size(), endName) != 0) {
                continue;
            }

            std::string versionStr = entryName.substr(
                startName.size(), entryName.size() - startName.size() - endName.size());

            // version tokens may be a bare number ("003") or prefixed with
            // "v"/"V" ("v003"); strip an optional leading letter before parsing.
            std::string versionDigits = versionStr;
            if (!versionDigits.empty() && (versionDigits[0] == 'v' || versionDigits[0] == 'V')) {
                versionDigits = versionDigits.substr(1);
            }

            try {
                int entryVersion = std::stoi(versionDigits);
                if (entryVersion > version) {
                    version = entryVersion;
                }
            } catch (const std::exception&) {
                continue;
            }
        }
    }

    else if (versionType == "json"){
        // TODO: should we check if json
        std::cout << "jsonjsonjson" << std::endl;

        fs::path layerInfoPath = fs::path(basedir) / "layer_info.json";
        if (!fs::exists(layerInfoPath)) {
            return ArResolvedPath();
        }

        std::ifstream layerInfoFile(layerInfoPath);
        nlohmann::json layerInfo;
        layerInfoFile >> layerInfo;

        if (!layerInfo.contains("stable_version")) {
            return ArResolvedPath();
        }

        version = layerInfo["stable_version"].get<int>();
        std::cout << "STABLE VERSION: " << version << std::endl;
    }

    char versionBuf[16];
    std::snprintf(versionBuf, sizeof(versionBuf), "v%03d", version);
    std::string versionStr(versionBuf);

    std::string resolvedPath = fullPath;
    size_t tokenPos = resolvedPath.find("<version>");
    while (tokenPos != std::string::npos) {
        resolvedPath.replace(tokenPos, 9, versionStr);
        tokenPos = resolvedPath.find("<version>", tokenPos + versionStr.size());
    }

    // TODO check if file exists before returning path
    return ArResolvedPath(resolvedPath);
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
