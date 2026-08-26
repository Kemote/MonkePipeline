import os
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline_config import apply_pipeline_env


apply_pipeline_env()
os.environ.setdefault("PXR_PLUGINPATH_NAME", os.environ["PXR_PLUGINPATH_NAME_USDVIEW"])
os.environ.setdefault("TF_DEBUG", "AR_RESOLVER_INIT")
# pxr must be imported after PXR_PLUGINPATH_NAME is already set
from pxr import Ar


class MonkeDiscResolverTest(unittest.TestCase):
    def test_resolves_versioned_disc_path(self):
        print("TEST")
        test_disc_path = "monkeDisc://assets/roboticArm/layers/roboticArm_geom_<version>.usda:latest"
        resolved_disc_path = Ar.GetResolver().Resolve(test_disc_path)
        print(resolved_disc_path)
        self.assertTrue(resolved_disc_path)


if __name__ == "__main__":
    unittest.main()