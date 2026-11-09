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
from exporter.ui.exporter_ui import show_export_dialog
from convex_hull_generator.collision_hull_ui import show

class MONKE_OT_usd_export(bpy.types.Operator):
    bl_idname = "monke.usd_export"
    bl_label = "USD Export"
    bl_options = {'REGISTER'}

    def execute(self, context):
        show_export_dialog()
        return {'FINISHED'}


class MONKE_OT_convex_hull_generator(bpy.types.Operator):
    bl_idname = "monke.convex_hull_generator"
    bl_label = "Generate Collision Object"
    bl_options = {'REGISTER'}

    def execute(self, context):
        show()
        return {'FINISHED'}


class TOPBAR_MT_monke_pipeline(bpy.types.Menu):
    bl_idname = "TOPBAR_MT_monke_pipeline"
    bl_label = "Monke Pipeline"

    def draw(self, context):
        layout = self.layout
        layout.operator(MONKE_OT_usd_export.bl_idname, text="USD Export")
        layout.operator(MONKE_OT_convex_hull_generator.bl_idname, text="Generate Collision Object")


classes = (
    MONKE_OT_usd_export,
    MONKE_OT_convex_hull_generator,
    TOPBAR_MT_monke_pipeline,
)


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
