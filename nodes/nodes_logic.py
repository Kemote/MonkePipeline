import os
import sys

from pxr import Usd, Sdf, UsdGeom, UsdShade
from nodes.nodes import UsdOutputNode
from OdenGraphQt import Port
from publisher.collector import CollectedAssetItem


class UsdOutputExecutor:
    """
    Execution logic for USD ouptu node
    """
    def __init__(self, node : UsdOutputNode):
        output_path = node.get_property("output_path").text()
        output_format = node.get_property("export_format").current_text()
        self.output_path = f"{output_path}.{output_format}"
        self.stage = Usd.Stage.CreateInMemory()
        self.node = node
        self.assets_main_prims = {}

    def execute(self):
        for input_port in self.node.input_ports():
            self._execute_input_ports(input_port)

    def _execute_input_ports(self, input_port : Port):
        if input_port.name().statrswith("data"):
            input_node = input_port.node()
            if input_node.DATA_TYPE == "Asset":
                self._execute_asset_data(input_node)

    def _execute_asset_data(self, input_node):
        """
        nadle asset data
        """
        collected_item : CollectedAssetItem = input_node.collected_item
        asset_name = collected_item.name
        asset_main_prim = self.assets_main_prims.get(asset_name)
        if not asset_main_prim:
            asset_main_prim = self._create_asset_main_prim(asset_name)
            self.assets_main_prims[asset_name] = asset_main_prim

    def _create_asset_main_prim(self, asset_name):
        # here we need assume that if there is more than one asset all of them should be under "assets" prim
        number_of_assets = len(self.assets_main_prims)
        if  number_of_assets == 1:
            # we need to chang already created prims
            usd_namespacee_editor = Usd.NamespaceEditor(self.stage)
            cached_dict = {}
            for key, item in self.assets_main_prims.items():
                current_prim_path = item.GetPath()
                new_path = f"/Assets{current_prim_path}"
                assets_scope = UsdGeom.Scope.Define(self.stage, "/Assets")
                self.stage.SetDefaultPrim(assets_scope)
                usd_namespacee_editor.MovePrimAtPath(current_prim_path, new_path)
                moved_prim = self.stage.GetPrimAtPath(new_path)
                cached_dict[key] = moved_prim
        
        if number_of_assets == 0:
            main_prim_path = f"/{asset_name}"
            main_prim = UsdGeom.Xform.Define(self.stage, main_prim_path)
            self.stage.SetDefaultPrim(main_prim_path)

        else:
            main_prim_path = f"/Assets/{asset_name}"
            main_prim = UsdGeom.Xform.Define(self.stage, main_prim_path)

        self.assets_main_prims[asset_name] = main_prim
            
        
        return main_prim     
            

