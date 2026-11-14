from pxr import Usd, UsdPhysics


class PhysicsLayerExporter:
    def __init__(self, asset_name, output_path):
        self.stage = Usd.Stage.CreateNew(output_path)
        self.joints_prim = self.stage.DefinePrim(f"/{asset_name}/Joints")

    def save(self):
        self.stage.Save()

    def export(self, blender_obj, prim_path):
        # export rigid body
        # TODO: ommit prims which hane no phuysics !!
        prim = self.stage.GetPrimAtPath(prim_path)
        if not prim:
            prim = self.stage.DefinePrim(prim_path, "Xform")

        clean_name = self._get_clean_name(blender_obj)

        blender_rb = blender_obj.rigid_body
        if blender_rb:
            rb_api = UsdPhysics.RigidBodyAPI.Apply(prim)
            rb_api.CreateRigidBodyEnabledAttr(True)

            if blender_rb.type == "PASSIVE":
                fixed_joint_path = f"{str(self.joints_prim.GetPath())}/{clean_name}"
                fixed_joint = UsdPhysics.FixedJoint.Define(self.stage, fixed_joint_path)
                # TODO check if we can opmmit body_0_rel
                body_1_rel = fixed_joint.CreateBody1Rel()
                body_1_rel.SetTargets([prim.GetPath()])

            mass_api = UsdPhysics.MassAPI.Apply(prim)
            mass_api.CreateMassAttr(blender_rb.mass)

            # TODO: set visuals and collisions prim visibility, for test puprose we want them both to be visible

        # TODO: add constraints creation

    @staticmethod
    def _get_clean_name(blender_obj):
        # TODO: handle name cleaning.
        name = blender_obj.name
        return name


'''
    import bpy
import math
from mathutils import Vector
from pxr import Usd, UsdGeom, UsdPhysics, Sdf, Gf

# ==============================================================================
# CONFIGURATION
# ==============================================================================
OUTPUT_USDA_PATH = bpy.path.abspath("//robot_isaac.usda")
ROBOT_ROOT_NAME = "Robot"

# Waveshare ST3020 Motor Defaults (12V, ~30 kg.cm)
ST3020_MAX_TORQUE_NM = 2.94     # 30 kg.cm -> N*m
ST3020_STIFFNESS = 80.0         # Position Kp (N*m/deg)
ST3020_DAMPING = 8.0            # Velocity Kd (N*m*s/deg)

def blender_name_to_usd(name: str) -> str:
    """Sanitize Blender object names for USD prim paths (no dots or spaces)."""
    return name.replace(".", "_").replace(" ", "_").replace("-", "_")

def export_and_inject_physics():
    # 1. Export standard meshes & hierarchy from Blender to .usda
    bpy.ops.wm.usd_export(
        filepath=OUTPUT_USDA_PATH,
        selected_objects_only=False,
        export_materials=True,
        export_meshes=True,
        root_prim_path=f"/{ROBOT_ROOT_NAME}",
        meters_per_unit=1.0
    )

    # 2. Open the exported .usda stage using Pixar's pxr library (built into Blender)
    stage = Usd.Stage.Open(OUTPUT_USDA_PATH)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    root_prim = stage.GetPrimAtPath(f"/{ROBOT_ROOT_NAME}")
    if root_prim.IsValid():
        UsdPhysics.ArticulationRootAPI.Apply(root_prim)

    # Map Blender object names -> USD prim paths
    obj_to_prim_path = {}
    for prim in stage.Traverse():
        obj_to_prim_path[prim.GetName()] = prim.GetPath()

    # 3. Inspect Blender Objects for Rigid Bodies & Visual/Collision Meshes
    for obj in bpy.context.scene.objects:
        clean_name = blender_name_to_usd(obj.name)
        prim_path = obj_to_prim_path.get(clean_name)
        if not prim_path:
            continue

        prim = stage.GetPrimAtPath(prim_path)

        # Apply RigidBodyAPI + MassAPI if object has Blender Rigid Body enabled
        if obj.rigid_body is not None:
            rb_api = UsdPhysics.RigidBodyAPI.Apply(prim)
            rb_api.CreateRigidBodyEnabledAttr(True)

            # Anchor passive base link to the world via FixedJoint
            if obj.rigid_body.type == 'PASSIVE':
                fixed_joint_path = f"/{ROBOT_ROOT_NAME}/world_fixed_{clean_name}"
                fixed_joint = UsdPhysics.FixedJoint.Define(stage, fixed_joint_path)
                fixed_joint.CreateBody1Rel().SetTargets([prim_path])

            mass_api = UsdPhysics.MassAPI.Apply(prim)
            mass_api.CreateMassAttr(obj.rigid_body.mass)

        # Separate Visuals vs. Collisions by naming convention
        if obj.type == 'MESH':
            lower_name = obj.name.lower()
            if "collision" in lower_name or "collider" in lower_name:
                # Hide collider from viewport render and apply convexHull collision
                imageable = UsdGeom.Imageable(prim)
                imageable.CreatePurposeAttr(UsdGeom.Tokens.guide)

                UsdPhysics.CollisionAPI.Apply(prim)
                mesh_col = UsdPhysics.MeshCollisionAPI.Apply(prim)
                mesh_col.CreateApproximationAttr(UsdPhysics.Tokens.convexHull)
                print(f"[Collider] Applied convexHull + guide purpose to: {prim_path}")

            elif "visual" in lower_name:
                print(f"[Visual]   Kept render-only mesh: {prim_path}")

    # 4. Inspect Blender Rigid Body Constraints -> Convert Hinges to Revolute Joints + Motors
    for obj in bpy.context.scene.objects:
        rbc = obj.rigid_body_constraint
        if rbc is None or rbc.type != 'HINGE':
            continue
        if rbc.object1 is None or rbc.object2 is None:
            print(f"[Warning] Skipping constraint '{obj.name}': missing object1 or object2.")
            continue

        parent_name = blender_name_to_usd(rbc.object1.name)
        child_name = blender_name_to_usd(rbc.object2.name)
        parent_path = obj_to_prim_path.get(parent_name)
        child_path = obj_to_prim_path.get(child_name)

        if not parent_path or not child_path:
            continue

        joint_name = blender_name_to_usd(obj.name)
        joint_path = f"/{ROBOT_ROOT_NAME}/joints/{joint_name}"
        joint = UsdPhysics.RevoluteJoint.Define(stage, joint_path)

        # Blender Hinge constraints always rotate around the constraint Empty's local Z-axis
        joint.CreateAxisAttr(UsdPhysics.Tokens.z)
        joint.CreateBody0Rel().SetTargets([parent_path])
        joint.CreateBody1Rel().SetTargets([child_path])

        # Compute local positions of the hinge pivot in parent and child local frames
        world_pivot = obj.matrix_world.translation
        local_pos0 = rbc.object1.matrix_world.inverted() @ world_pivot
        local_pos1 = rbc.object2.matrix_world.inverted() @ world_pivot

        joint.CreateLocalPos0Attr(Gf.Vec3f(*local_pos0))
        joint.CreateLocalPos1Attr(Gf.Vec3f(*local_pos1))

        # Compute local orientations of the hinge Z-axis in parent and child local frames
        rot_world = obj.matrix_world.to_quaternion()
        rot0 = rbc.object1.matrix_world.to_quaternion().inverted() @ rot_world
        rot1 = rbc.object2.matrix_world.to_quaternion().inverted() @ rot_world

        joint.CreateLocalRot0Attr(Gf.Quatf(rot0.w, rot0.x, rot0.y, rot0.z))
        joint.CreateLocalRot1Attr(Gf.Quatf(rot1.w, rot1.x, rot1.y, rot1.z))

        # Angular limits (Blender stores radians; USD Physics uses degrees)
        if rbc.use_limit_ang_z:
            joint.CreateLowerLimitAttr(math.degrees(rbc.limit_ang_z_lower))
            joint.CreateUpperLimitAttr(math.degrees(rbc.limit_ang_z_upper))

        # Add Angular Drive (Waveshare ST3020 Motor)
        drive = UsdPhysics.DriveAPI.Apply(joint.GetPrim(), UsdPhysics.Tokens.angular)
        drive.CreateTypeAttr("force")
        drive.CreateMaxForceAttr(ST3020_MAX_TORQUE_NM)
        drive.CreateStiffnessAttr(ST3020_STIFFNESS)
        drive.CreateDampingAttr(ST3020_DAMPING)
        drive.CreateTargetPositionAttr(0.0)

        print(f"[Joint]    Created ST3020 RevoluteJoint '{joint_name}': {parent_name} -> {child_name}")

    # Save modified .usda
    stage.GetRootLayer().Save()
    print(f"Done! Saved Isaac Sim ready USD to: {OUTPUT_USDA_PATH}")

export_and_inject_physics()

'''