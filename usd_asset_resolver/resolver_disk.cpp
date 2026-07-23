#include <iostream>
#include <string>
#include <string_view>
#include <filesystem>
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
    size_t versionSep = assetPath.rfind(":");
    std::string versionType = assetPath.substr(versionSep + 1);
    std::string pathBody = assetPath.substr(11, versionSep - 11);
    std::string projectsRoot = getenv("PROJECTSROOT");
    std::string projectName = getenv("PROJECTNAME");
    std::string fullPath = projectsRoot + "/" + projectName + pathBody;
    int version = 0;

    std::cout << "FULL PATH: " << fullPath << std::endl;
    std::cout << "VERSION TYPE: " << versionType << std::endl;
    
    // now we need to get version
    if (versionType == "lastest"){
        size_t versionToken = fullPath.find("<version>");
        std::string basedir = fullPath;
        std::string startName = "";
        std::string endName = "";
        
        if (versionToken != std::string_view::npos){
            basedir = fullPath.substr(0, versionToken);
            
            std::cout << "BASEDIR: " << basedir << std::endl;

            size_t lastSlash = basedir.rfind("/");
            if (lastSlash != std::string_view::npos){
                // cos z tym version token jest nie tak
                startName = fullPath.substr(lastSlash + 1, versionToken - (lastSlash + 1));
                std::string restOfPath = fullPath.substr(versionToken);
                size_t nameSlash = restOfPath.find("/");
                endName = restOfPath.substr(9, nameSlash - 9);
                basedir = basedir.substr(0, lastSlash);
            }
        }

        std::cout << "STARNAME: " << startName << std::endl;
        std::cout << "ENDNAME: " << endName << std::endl;
        std::cout << "PATH TO SEARCH: " << basedir << std::endl;
        
        for (const auto& entry : fs::directory_iterator(basedir)){
            
            std::cout << "ENTRY: " << entry << std::endl;
                

        }

    }

    else if (versionType == "json"){
        std::cout << "jsonjsonjson" << std::endl;
    }

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
