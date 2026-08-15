import os
import requests


# set project settings:
# those envs should be set by some kind of luncher
os.environ["PROJECTNAME"] = "sample_usd_files"
os.environ["PROJECTSROOT"] = "/home/kemot/Documents/Dev/MonkePipeline"


# set correct pxr environment
os.environ["PXR_PLUGINPATH_NAME"] = "/home/kemot/Documents/Dev/MonkePipeline/usd_asset_resolver/build"
os.environ["TF_DEBUG"] = "AR_RESOLVER_INIT"
# pxr should be imported after ar environ is already set
from pxr import Usd, Sdf, Ar, Tf


# get db token:
# db_url = "http://127.0.0.1:5000/api/login"
# payload = {
#     "Content-Type": "application/json",
#     "Accept": "aplication/json",
#     "username": "admin",
#     "password": "admin"
# }
# response = requests.post(url=db_url, json=payload, timeout=10)
# response_json = response.json()
# token = response_json.get("token")
# print(f"TOKEN: {token}")
# os.environ["MONKEDBTOKEN"] = token



# test
# wypadku monkeDb to czy sciezki w glab tak jak sceizki do roznych variantow bede relartywnie? 
# Okreslany bylby tylko glowny plik stepu
# test_path = "monkeDb://asset:monkeHero:Geom?version=2&status=hujowy"
test_disc_path = "monkeDisc://assets/roboticArm/layers/roboticArm_geom_v<version>.usda:lastest"
asset_resolver = Ar.GetResolver()
# resolved_path = asset_resolver.Resolve(test_path)
resolved_disc_path = asset_resolver.Resolve(test_disc_path)

# current_resolver = Ar.GetResolver()
# resolver_type = Tf.Type.Find(current_resolver)
# print(f"TFTYPE: {resolver_type.typeName}")

# print(f"DB PATH: {resolved_path}")
print(f"DISC PATH: {resolved_disc_path}")