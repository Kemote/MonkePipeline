#include <iostream>
#include <string>
#include <string_view>
#include <curl/curl.h>
#include <nlohmann/json.hpp>
#include "resolver_db.h" // Load our blueprint first.


// libcurl helper function
size_t WriteCallback(void* contents, size_t size, size_t nmemb, std::string* output) {
    size_t totalSize = size * nmemb;
    output->append((char*)contents, totalSize);
    return totalSize;
}


// function to handle REST API requests from test database
std::string MonkeApiRequest(const std::string& assetId) {
    CURL* curl = curl_easy_init();
    std::string responseString;

    if(curl) {
        std::string url = "http://127.0.0.1:5000/api/assets/" + assetId + "/fin_path";
        
        curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
        
        // http header
        struct curl_slist* headers = nullptr;
        
        // format your token header: "Authorization: Bearer <your_secret_token>"
        std::string token = getenv("MONKEDBTOKEN");
        std::string tokenHeader = "Authorization: Bearer " + token;
        headers = curl_slist_append(headers, tokenHeader.c_str());
        
        // pass the headers list to the curl session
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
        // --- AUTHENTICATION END ---

        // setup your string data callbacks
        curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, +[](void* contents, size_t size, size_t nmemb, std::string* output) -> size_t {
            size_t totalSize = size * nmemb;
            output->append((char*)contents, totalSize);
            return totalSize;
        });
        curl_easy_setopt(curl, CURLOPT_WRITEDATA, &responseString);
        
        // perform the request
        CURLcode res = curl_easy_perform(curl);
        
        // IMPORTANT: Always free the headers list and clean up session memory
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
    }
    return responseString; 
}


// function to obtain varaibles from monkeDbPath
std::tuple<std::string, std::string, std::string, std::string, std::string> GetMonkeTokens(std::string_view monkeDbPath) {
    std::string_view uriBody;
    std::string entity_type, entity_name, entity_step, version, status;
    size_t tokensSeparator = monkeDbPath.find("?");    

    if (tokensSeparator == std::string::npos) {
        uriBody = monkeDbPath.substr(11);
    }

    else {
        uriBody = monkeDbPath.substr(11, tokensSeparator - 11);
        std::string_view tokens = monkeDbPath.substr(tokensSeparator + 1);
        std::string valKey = "";
        std::string value = "";
        
        // get tokens
        while (!tokens.empty()) {
            size_t ampPos = tokens.find("&");
            std::string_view value_pair = (ampPos == std::string_view::npos) ? tokens : tokens.substr(0, ampPos);
            
            size_t eqPos = value_pair.find("=");
            if (eqPos != std::string_view::npos) {
                valKey = value_pair.substr(0, eqPos);
                value = value_pair.substr(eqPos + 1);
                // get tokens we need
                if (valKey == "version") {
                    version = value;
                }
                else if (valKey == "status") {
                    status = value;
                }
            } 
            tokens = tokens.substr(ampPos + 1);
            if (ampPos == std::string_view::npos) break;
        }
    }    

    // get monkeDbPath body parts
    int index = 1;
    while (!uriBody.empty()) {
        size_t eqPos = uriBody.find(":");
        if (eqPos == std::string_view::npos) {
            entity_step = uriBody;
        }
        else if (index == 1) {
            entity_type = uriBody.substr(0, eqPos);
        }
        else if (index == 2) {
            entity_name = uriBody.substr(0, eqPos);
        }
        index += 1;
        uriBody = uriBody.substr(eqPos + 1);
        if (eqPos == std::string_view::npos) break;
    }
    
    return {entity_type, entity_name, entity_step, version, status};
}

// this class can clean up paths, e.g. standarizing slshes, stripping relative  "../" etc.
std::string MonkeDbResolver::_CreateIdentifier(
    const std::string& assetPath,
    const ArResolvedPath& anchorAssetPath) const 
{
    // For a schematic pass-through, we do nothing.
    // We just return the exact same string USD gave us.
    return assetPath;
}


// resolve path
ArResolvedPath MonkeDbResolver::_Resolve(const std::string& monkeDbPath) const {
    auto [type, name, step, version, status] = GetMonkeTokens(monkeDbPath);
    
    // Test of GetMonkeTokens, it's working now we need DB which will works ass we will
    std::cout << "MONKEMONKEWAAGH!!: " << type << ", " << name << ", " << step << ", " << version << ", " << status << '\n';
    
    std::string modifiedPath = monkeDbPath;
    modifiedPath += "_MonkeWaaagh";
    return ArResolvedPath(modifiedPath);
}


// function which handle streaming USD from http or zip files
std::shared_ptr<ArAsset> MonkeDbResolver::_OpenAsset(const ArResolvedPath& resolvedPath) const {
    // nullptr is modern version of "NULL" in C++
    // if we return bullptr OpenUSD knwo that we don't have custom memory stream
    // and it should be oppened form local hard drive
    return nullptr;
}


// Same idea as _CreateIdentifier, but called when USD is about to write out a
// brand-new asset that doesn't exist on disk yet.
std::string MonkeDbResolver::_CreateIdentifierForNewAsset(
    const std::string& assetPath,
    const ArResolvedPath& anchorAssetPath) const
{
    return assetPath;
}


// same idea as _Resolve, but for figuring out where a new (not-yet-written) asset should be placed on disk.
ArResolvedPath MonkeDbResolver::_ResolveForNewAsset(const std::string& assetPath) const {
    return ArResolvedPath(assetPath);
}


// If your resolver needed custom logic to stream bytes out to storage (e.g.
// uploading to the cloud), you'd write that here. For a pass-through resolver,
std::shared_ptr<ArWritableAsset> MonkeDbResolver::_OpenAssetForWrite(
    const ArResolvedPath& resolvedPath,
    WriteMode writeMode) const
{
    return nullptr;
}
