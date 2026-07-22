import os
import requests

# set correct environment
os.environ["PXR_PLUGINPATH_NAME"] = "/home/kemot/Documents/Dev/MonkePipeline/usd_asset_resolver/build"
os.environ["TF_DEBUG"] = "AR_RESOLVER_INIT"
# pxr should be imported after ar environ is already set
from pxr import Usd, Sdf, Ar, Tf


# get db token:
db_url = "http://127.0.0.1:5000/api/login"
payload = {
    "Content-Type": "application/json",
    "Accept": "aplication/json",
    "username": "admin",
    "password": "admin"
}
response = requests.post(url=db_url, json=payload, timeout=10)
response_json = response.json()
token = response_json.get("token")
print(f"TOKEN: {token}")
os.environ["MONKEDBTOKEN"] = token


# test code
test_path = "monkeDb://asset:monkeHero:Geom?version=2&status=hujowy"
asset_resolver = Ar.GetResolver()
resolved_path = asset_resolver.Resolve(test_path)
str_path = resolved_path.GetPathString()

current_resolver = Ar.GetResolver()
resolver_type = Tf.Type.Find(current_resolver)
print(f"TFTYPE: {resolver_type.typeName}")

print(f"PATH: {resolved_path}")