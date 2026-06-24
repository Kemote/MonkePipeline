bl_info = {
    "name": "Monke Pipeline Exporter",
    "author": "Tomasz Szymski",
    "version": (1, 0),
    "blender": (4, 0, 0),  # Works for Blender 4.0+ and 3.x
    "location": "Top Menu Bar > Monke Pipeline",
    "description": "Monke Pipeline Addon",
    "category": "Interface",
}


import bpy


# 1. Define an example operator (the action that happens when you click a menu item)
class MONKE_PIPELINE_OT_PUBLISHER(bpy.types.Operator):
    bl_idname = "monke_pipeline.publisher"
    bl_label = "Run Monke Script"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        self.report({'INFO'}, "Monke script executed successfully!")
        print("Monke script is running...")
        return {'FINISHED'}


# custom menu
class MONKE_PIPELINE_MT_menu(bpy.types.Menu):
    bl_label = "Monke Pipeline"
    bl_idname = "MONKE_PIPELINE_MT_menu"

    def draw(self, context):
        layout = self.layout
        
        # Add items to your menu here
        layout.operator("monke_pipeline.publisher", icon='PLAY')
        
        # You can add separators and more items like this:
        # layout.separator()
        # layout.operator("object.select_all", text="Select All Shortcut")


# append the menu to Blender's main top menu bar
def draw_menu_func(self, context):
    layout = self.layout
    layout.menu("MONKE_PIPELINE_MT_menu")


# registration
classes = (
    MONKE_PIPELINE_OT_PUBLISHER,
    MONKE_PIPELINE_MT_menu,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_editor_menus.append(draw_menu_func)


def unregister():
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_menu_func)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()