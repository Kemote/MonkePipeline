import os
import bpy
import math
import json

from pxr import Usd, UsdPhysics, Gf, Sdf
from exporter.monke_logging import get_logger


logger = get_logger(__name__)
COLLISIONS_PREFIX = "collisions"
MOTORS_JSON_FILENAME = "isaac_sim.json"


def sanitize_blender_name(blender_obj):
        name = blender_obj.name
        return name


class ConstraintsConstructor:
    def __init__(self, stage : Usd.Stage, rb_constraint):
        self.stage = stage
        self.rb_constraint = rb_constraint
        self.rbc_name = sanitize_blender_name(rb_constraint)
        self.blender_objects = [rb_constraint.object1, rb_constraint.object2]
        self.joint = None
        # self._create_usd_joint(str(joints_prim.GetPath()), rb_constraint, blender_obj, motors_data)

    def set_target(self, prim_path, blender_obj):
        if blender_obj == self.blender_objects[0]:
            self.joint.CreateBody0Rel().SetTargets([prim_path])
        if blender_obj == self.blender_objects[1]:
            self.joint.CreateBody1Rel().SetTargets([prim_path])
        
    def create_usd_joint(self, joints_prim_path, blender_obj, motors_data):
        if not self.joint:
            joint_path = f"{joints_prim_path}/{self.rbc_name}"
            joint_prim = self.stage.GetPrimAtPath(joint_path)
            
            if self.rb_constraint.type == "HINGE":
                if joint_prim:
                    self.joint = UsdPhysics.RevoluteJoint(joint_prim)
                    return 
                
                self.joint = UsdPhysics.RevoluteJoint.Define(self.stage, joint_path)
                self._configure_hinge(self.rb_constraint, blender_obj, motors_data)

            if self.rb_constraint.type == "SLIDER":
                if joint_prim:
                    self.joint = UsdPhysics.PrismaticJoint(joint_prim)
                    return

                self.joint = UsdPhysics.PrismaticJoint.Define(self.stage, joint_path)

    def _configure_hinge(self, blender_obj, motors_data):
        # TODO: Learn motre about this!!
        # Blender Hinge constraints always rotate around the constraint Empty's local Z-axis
        self.joint.CreateAxisAttr(UsdPhysics.Tokens.z)
        
        # Compute local positions of the hinge pivot in parent and child local frames
        world_pivot = blender_obj.matrix_world.translation
        local_pos0 = self.rb_constraint.object1.matrix_world.inverted() @ world_pivot
        local_pos1 = self.rb_constraint.object2.matrix_world.inverted() @ world_pivot

        self.joint.CreateLocalPos0Attr(Gf.Vec3f(*local_pos0))
        self.joint.CreateLocalPos1Attr(Gf.Vec3f(*local_pos1))

        # Compute local orientations of the hinge ZConstraintsConstructor-axis in parent and child local frames
        rot_world = blender_obj.matrix_world.to_quaternion()
        rot0 = self.rb_constraint.object1.matrix_world.to_quaternion().inverted() @ rot_world
        rot1 = self.rb_constraint.object2.matrix_world.to_quaternion().inverted() @ rot_world

        self.joint.CreateLocalRot0Attr(Gf.Quatf(rot0.w, rot0.x, rot0.y, rot0.z))
        self.joint.CreateLocalRot1Attr(Gf.Quatf(rot1.w, rot1.x, rot1.y, rot1.z))

        # Angular limits (Blender stores radians; USD Physics uses degrees)
        if self.rb_constraint.use_limit_ang_z:
            self.joint.CreateLowerLimitAttr(math.degrees(self.rb_constraint.limit_ang_z_lower))
            self.joint.CreateUpperLimitAttr(math.degrees(self.rb_constraint.limit_ang_z_upper))

        self._add_motor_data(motors_data)

    def _add_motor_data(self, motors_data):
        # in Blender outliner, object representing motor should start with motor name (e.g., "st3020_joint_1")
        motor_name = self.rbc_name.split("_")[0].lower()
        motor_data = motors_data.get(motor_name)

        if not motor_data:
            return

        # mechanical angle limits (wrap self.joint_prim as RevoluteJoint)
        if self.joint_prim.IsA(UsdPhysics.RevoluteJoint):
            rev_joint = UsdPhysics.RevoluteJoint(self.joint_prim)
            rev_joint.CreateLowerLimitAttr(float(motor_data.get("lower_limit_deg", -180.0)))
            rev_joint.CreateUpperLimitAttr(float(motor_data.get("upper_limit_deg", 180.0)))

        # motor actuator & PD gains (UsdPhysics.DriveAPI)
        drive = UsdPhysics.DriveAPI.Apply(self.joint_prim, UsdPhysics.Tokens.angular)
        drive.CreateTypeAttr("force")
        drive.CreateMaxForceAttr(float(motor_data.get("max_force_nm", 0.0)))
        drive.CreateStiffnessAttr(float(motor_data.get("stiffness", 0.0)))
        drive.CreateDampingAttr(float(motor_data.get("damping", 0.0)))

        # Isaac Sim / PhysX solver limits & friction (authored directly for Blender's pxr)
        self.joint_prim.AddAppliedSchema("PhysxJointAPI")
        self.joint_prim.CreateAttribute("physxJoint:maxJointVelocity", Sdf.ValueTypeNames.Float).Set(
            float(motor_data.get("max_joint_velocity_deg_s", 360.0))
        )
        self.joint_prim.CreateAttribute("physxJoint:armature", Sdf.ValueTypeNames.Float).Set(
            float(motor_data.get("armature", 0.0))
        )
        self.joint_prim.CreateAttribute("physxJoint:jointFriction", Sdf.ValueTypeNames.Float).Set(
            float(motor_data.get("joint_friction", 0.0))
        )

class PhysicsLayerExporter:
    def __init__(self, asset_name, output_path):
        self.stage = Usd.Stage.CreateNew(output_path)
        self.joints_prim = self.stage.DefinePrim(f"/{asset_name}/Joints")
        self.motors_data = self._get_motors_data()
        self.empty_constraints = list(self._get_empty_constraints())

    def save(self):
        self.stage.Save()

    def export(self, blender_obj, prim_path):
        # export rigid body
        blender_rb = blender_obj.rigid_body
        if blender_rb:
            collision_prim = self.stage.GetPrimAtPath(prim_path)
            if not collision_prim:
                collision_prim, collision_xform_prim = self._create_colisions_prim(prim_path, blender_obj, blender_rb)
            
            # handle passive rigid body
            if blender_rb.type == "PASSIVE":
                clean_name = sanitize_blender_name(blender_obj)
                fixed_joint_path = f"{str(self.joints_prim.GetPath())}/{clean_name}"
                fixed_joint = UsdPhysics.FixedJoint.Define(self.stage, fixed_joint_path)
                # TODO check if we can opmmit body_0_rel
                body_1_rel = fixed_joint.CreateBody1Rel()
                body_1_rel.SetTargets([collision_prim.GetPath()])

            for rb_constraint in blender_obj.rigid_body_constraint:
                if rb_constraint.object1 is None or rb_constraint.object2 is None:
                    logger.warning(f"[Warning] Skipping constraint '{blender_obj.name}': missing object1 or object2.")
                    continue
                self._add_constraint(collision_xform_prim, blender_obj, rb_constraint)

    def _create_colisions_prim(self, prim_path, blender_obj, blender_rb):
        if blender_obj.name.startswith(COLLISIONS_PREFIX):
            # if name starts with "collisions" we assume that there is parent prim which conatin also "visuals" prim, in that
            # case parent prim should contain rigid body attribute
            prim_path_split = prim_path.split("/")
            collision_xform_path = "/".join(prim_path_split[:-1])
            collision_xform_prim = self.stage.GetPrimAtPath(collision_xform_path)
            
            if not collision_xform_prim:
                collision_xform_prim = self.stage.DefinePrim(collision_xform_path, "Xform")
        
            collision_prim = self.stage.GetPrimAtPath(collision_xform_path)
            if not collision_prim:
                collision_prim = self.stage.DefinePrim(prim_path, "Xform")

        else:
            collision_prim = self.stage.GetPrimAtPath(prim_path)
            if not collision_prim:
                collision_prim = self.stage.DefinePrim(prim_path, "Xform")
            collision_xform_prim = collision_prim

        # sets rigid bodies APIs and mass
        rb_api = UsdPhysics.RigidBodyAPI.Apply(collision_xform_prim)
        rb_api.CreateRigidBodyEnabledAttr(True)
        collision_api = UsdPhysics.CollisionAPI.Apply(collision_prim)
        mesh_collision = UsdPhysics.MeshCollisionAPI.Apply(collision_prim)
        mesh_collision.CreateApproximationAttr(UsdPhysics.Tokens.convexDecomposition)     
        mass_api = UsdPhysics.MassAPI.Apply(collision_prim)
        mass_api.CreateMassAttr(blender_rb.mass)
        return collision_prim, collision_xform_prim

    def _add_constraint(self, xform_prim, blender_obj):
        for rbc in self.empty_constraints:
            if blender_obj in rbc.blender_objects:
                if not rbc.joint:
                    rbc.create_usd_joint(xform_prim, blender_obj, self.motors_data)           

    def _get_empty_constraints(self):
        for obj in bpy.context.scene.objects:
            rigid_body_constraint = obj.rigid_body_constraint
            if obj.type == "EMPTY" and rigid_body_constraint:
                yield(ConstraintsConstructor(self.stage, rigid_body_constraint))
                
    @staticmethod
    def _get_motors_data():
        motors_data = {}
        if bpy.data.is_saved:
            blend_dir = os.path.dirname(bpy.data.filepath)
            issac_sim_sheet_path = f"{blend_dir}/{MOTORS_JSON_FILENAME}"
            if os.path.exists(issac_sim_sheet_path):
                with open(issac_sim_sheet_path, "r", encoding="utf-8") as f:
                    motors_data = json.load(f)
        return motors_data
