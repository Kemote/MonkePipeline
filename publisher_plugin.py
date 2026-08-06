bl_info = {
    "name": "USD Monke Exporter",
    "author": "Monke Pipeline",
    "version": (0, 1, 0),
    "blender": (3, 6, 0),
    "location": "Top Bar > Monke Pipeline > USD Export",
    "description": "Sample USD export entry point for the Monke Pipeline.",
    "category": "Pipeline",
}

import bpy
from ui.blender_publisher_ui import classes, TOPBAR_MT_monke_pipeline


def draw_monke_pipeline_menu(self, context):
    self.layout.menu(TOPBAR_MT_monke_pipeline.bl_idname)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_editor_menus.append(draw_monke_pipeline_menu)


def unregister():
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_monke_pipeline_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
