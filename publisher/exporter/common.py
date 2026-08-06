from pxr import Gf, UsdGeom
from publisher.collector import VARIANT_SEPARATOR


FPS = 30
DEFORM_MODIFIER_TYPES = {"ARMATURE", "CLOTH", "SOFT_BODY", "SURFACE_DEFORM"}
MAX_JOINT_INFLUENCES = 4
LOD_VARIANT_SET = "lod"
LOD_PURPOSES = {
    "render": UsdGeom.Tokens.render,
    "proxy": UsdGeom.Tokens.proxy,
}


def sanitize_name(name):
    sanitized = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
    if sanitized[:1].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def split_variant(name):
    """splits "set{VARIANT_SEPARATOR}variant" into (set_name, variant_name); (None, name) otherwise"""
    parts = name.split(VARIANT_SEPARATOR)
    if len(parts) > 1:
        return parts[0], parts[-1]
    return None, name


def is_lod_set(variant_set_name):
    return variant_set_name.lower() == LOD_VARIANT_SET


def lod_purpose(variant_name):
    return LOD_PURPOSES.get(variant_name.lower(), UsdGeom.Tokens.guide)


def asset_root_path(asset_name):
    return f"/{sanitize_name(asset_name)}"


def geom_scope_path(asset_name):
    return f"{asset_root_path(asset_name)}/Geom"


def looks_scope_path(asset_name):
    return f"{asset_root_path(asset_name)}/Looks"


def armature_scope_path(asset_name):
    return f"{asset_root_path(asset_name)}/Rig"


def mesh_prim_path(asset_name, asset_outliner_path, outliner_path):
    """
    maps a mesh's outliner path (relative to the asset group) onto
    /{asset_name}/Geom/... - a variant collection ("set_VAR_variant") contributes
    no path component, since the variantSet selection already encodes that choice;
    the exception is a lod collection, whose meshes compose under a prim named
    after the lod's purpose (render/proxy/guide) so every lod can coexist
    """
    relative = outliner_path[len(asset_outliner_path):].strip("/")
    parts = []
    for part in relative.split("/"):
        if not part:
            continue
        set_name, variant_name = split_variant(part)
        if set_name is None:
            parts.append(sanitize_name(part))
        elif is_lod_set(set_name):
            parts.append(lod_purpose(variant_name))
    return "/".join([geom_scope_path(asset_name)] + parts)


def base_material_name(material_name):
    """a material named "base{VARIANT_SEPARATOR}variant" belongs to the "base" variant group"""
    return material_name.split(VARIANT_SEPARATOR)[0]


def material_prim_name(material_name):
    """
    "base_VAR_variant" materials become "{base}_{variant}" prims - the separator is
    dropped but both halves are kept, so names stay unique across variant groups
    (unlike keeping just the variant, where wood_VAR_dark and metal_VAR_dark clash)
    """
    set_name, variant_name = split_variant(material_name)
    if set_name is None:
        return sanitize_name(material_name)
    return f"{sanitize_name(set_name)}_{sanitize_name(variant_name)}"


def matrix_to_gf(matrix_world):
    transposed = matrix_world.transposed()
    return Gf.Matrix4d(*[component for row in transposed for component in row])


def bone_ancestors(bone):
    ancestors = []
    current = bone.parent
    while current is not None:
        ancestors.append(current)
        current = current.parent
    return ancestors


def find_armature_modifier(mesh_obj, armature_objects):
    for modifier in mesh_obj.modifiers:
        if modifier.type == "ARMATURE" and modifier.object in armature_objects:
            return modifier
    return None
