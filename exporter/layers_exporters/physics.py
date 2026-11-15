import os
import bpy
import math
import json

from collections import namedtuple
from mathutils import Matrix
from pxr import Usd, UsdGeom, UsdPhysics, Gf, Sdf
from exporter.layers_exporters.common import geom_scope_path, joints_scope_path, sanitize_name
from exporter.monke_logging import get_logger


logger = get_logger(__name__)
COLLISIONS_PREFIX = "collisions"
MOTORS_JSON_FILENAME = "isaac_sim.json"

# prim_path: the prim holding RigidBodyAPI, matrix_world: that prim's world matrix in Blender space
RigidBody = namedtuple("RigidBody", ["prim_path", "matrix_world"])


def is_collisions_name(name):
    return name.lower().startswith(COLLISIONS_PREFIX)


def joint_local_frame(frame_matrix, body, mesh_scale):
    """
    localPos/localRot of a joint frame relative to a body prim, or to the world when body is None.
    UsdPhysics wants the position in the body's local space including its scale, and the rotation
    without scale. The mesh exporter multiplies points and translations by mesh_scale, so a Blender
    local position maps to USD as position * mesh_scale.
    """
    position, rotation, _ = frame_matrix.decompose()
    if body is not None:
        position = body.matrix_world.inverted() @ position
        rotation = body.matrix_world.decompose()[1].inverted() @ rotation
    position = position * mesh_scale
    return Gf.Vec3f(*position), Gf.Quatf(rotation.w, rotation.x, rotation.y, rotation.z)


def narrow_limit(limit, motor_limit, pick):
    """the motor's travel range narrows a joint limit, it never widens it"""
    if motor_limit is None:
        return limit
    if limit is None:
        return float(motor_limit)
    return pick(limit, float(motor_limit))


class ConstraintsConstructor:
    """
    authors one Blender rigid body constraint as a UsdPhysics joint. The constraint object's
    transform is the joint frame, object1 becomes body0 and object2 becomes body1.
    """
    JOINT_SCHEMAS = {
        "FIXED": UsdPhysics.FixedJoint,
        "HINGE": UsdPhysics.RevoluteJoint,
        "SLIDER": UsdPhysics.PrismaticJoint,
    }

    def __init__(self, stage : Usd.Stage, constraint_obj, mesh_scale, meter_per_unit):
        self.stage = stage
        self.constraint_obj = constraint_obj
        self.rb_constraint = constraint_obj.rigid_body_constraint
        self.name = constraint_obj.name
        self.mesh_scale = mesh_scale
        self.meter_per_unit = meter_per_unit
        self.joint = None

    def create_usd_joint(self, joints_path, body0, body1, motors_data):
        joint_schema = self.JOINT_SCHEMAS.get(self.rb_constraint.type)
        if joint_schema is None:
            logger.warning(f"Skipping constraint '{self.name}': {self.rb_constraint.type} constraints aren't exported")
            return None

        self.joint = joint_schema.Define(self.stage, joints_path.AppendChild(sanitize_name(self.name)))
        self.joint.CreateBody0Rel().SetTargets([body0.prim_path])
        self.joint.CreateBody1Rel().SetTargets([body1.prim_path])
        for body, create_pos, create_rot in (
            (body0, self.joint.CreateLocalPos0Attr, self.joint.CreateLocalRot0Attr),
            (body1, self.joint.CreateLocalPos1Attr, self.joint.CreateLocalRot1Attr),
        ):
            local_pos, local_rot = joint_local_frame(self.constraint_obj.matrix_world, body, self.mesh_scale)
            create_pos(local_pos)
            create_rot(local_rot)

        self.joint.CreateJointEnabledAttr(self.rb_constraint.enabled)
        # Blender and UsdPhysics both disable collisions between the jointed bodies by default
        self.joint.CreateCollisionEnabledAttr(not self.rb_constraint.disable_collisions)

        # in Blender outliner, object representing motor should start with motor name (e.g., "st3020_joint_1")
        motor_data = motors_data.get(self.name.split("_")[0].lower())
        if self.rb_constraint.type == "HINGE":
            self._configure_hinge(motor_data)
        elif self.rb_constraint.type == "SLIDER":
            self._configure_slider(motor_data)
        return self.joint

    def _configure_hinge(self, motor_data):
        # Blender hinges rotate around the constraint object's local Z axis
        self.joint.CreateAxisAttr(UsdPhysics.Tokens.z)

        # Blender stores radians, UsdPhysics uses degrees
        lower, upper = self._blender_limits(
            self.rb_constraint.use_limit_ang_z,
            math.degrees(self.rb_constraint.limit_ang_z_lower),
            math.degrees(self.rb_constraint.limit_ang_z_upper),
        )
        if motor_data:
            motor_lower = narrow_limit(lower, motor_data.get("lower_limit_deg"), max)
            motor_upper = narrow_limit(upper, motor_data.get("upper_limit_deg"), min)
            if motor_lower is not None and motor_upper is not None and motor_lower > motor_upper:
                logger.warning(
                    f"Constraint '{self.name}': motor limits in {MOTORS_JSON_FILENAME} don't overlap "
                    "the Blender limits, using the Blender limits"
                )
            else:
                lower, upper = motor_lower, motor_upper
        self._set_limits(lower, upper)

        if motor_data:
            self._add_motor_data(motor_data)

    def _configure_slider(self, motor_data):
        # Blender sliders move along the constraint object's local X axis
        self.joint.CreateAxisAttr(UsdPhysics.Tokens.x)

        lower, upper = self._blender_limits(
            self.rb_constraint.use_limit_lin_x,
            self.rb_constraint.limit_lin_x_lower,
            self.rb_constraint.limit_lin_x_upper,
        )
        if lower is not None:
            # linear limits are distances, so they scale like the exported points
            lower, upper = lower * self.mesh_scale, upper * self.mesh_scale
        self._set_limits(lower, upper)

        if motor_data:
            logger.warning(
                f"Constraint '{self.name}': {MOTORS_JSON_FILENAME} only describes rotary motors, "
                "no drive was added to this slider"
            )

    def _blender_limits(self, use_limit, lower, upper):
        """
        Blender passes the limits to Bullet, which leaves the axis free when lower > upper
        (Blender itself sends (0, -1) to mean "no limit"), so that case is exported without limits
        """
        if not use_limit:
            return None, None
        if lower > upper:
            logger.warning(
                f"Constraint '{self.name}': lower limit {lower:g} is above upper limit {upper:g}, so Blender "
                "leaves this axis free. Exported without limits, swap the values in Blender to limit it"
            )
            return None, None
        return lower, upper

    def _set_limits(self, lower, upper):
        # an unset side keeps the schema fallback (-inf or inf): no limit in that direction
        if lower is not None:
            self.joint.CreateLowerLimitAttr(float(lower))
        if upper is not None:
            self.joint.CreateUpperLimitAttr(float(upper))

    def _add_motor_data(self, motor_data):
        """
        angular drive and PhysX joint settings from isaac_sim.json, which uses SI units (N*m).
        Angular drive force, stiffness and damping, and the joint armature, are in
        mass * distance^2 units, so they're converted for stages that aren't in meters.
        Keys that are missing or null in the json keep the schema fallbacks.
        """
        joint_prim = self.joint.GetPrim()
        torque_scale = 1.0 / self.meter_per_unit ** 2

        # motor actuator & PD gains (UsdPhysics.DriveAPI)
        drive = UsdPhysics.DriveAPI.Apply(joint_prim, UsdPhysics.Tokens.angular)
        drive.CreateTypeAttr(UsdPhysics.Tokens.force)
        for key, create_attr, scale in (
            ("max_force_nm", drive.CreateMaxForceAttr, torque_scale),
            ("stiffness", drive.CreateStiffnessAttr, torque_scale),
            ("damping", drive.CreateDampingAttr, torque_scale),
        ):
            value = motor_data.get(key)
            if value is not None:
                create_attr(float(value) * scale)

        # Isaac Sim / PhysX solver limits & friction (authored by name, Blender's pxr has no PhysxSchema)
        joint_prim.AddAppliedSchema("PhysxJointAPI")
        for key, attr_name, scale in (
            ("max_joint_velocity_deg_s", "physxJoint:maxJointVelocity", 1.0),
            ("armature", "physxJoint:armature", torque_scale),
            ("joint_friction", "physxJoint:jointFriction", 1.0),
        ):
            value = motor_data.get(key)
            if value is not None:
                joint_prim.CreateAttribute(attr_name, Sdf.ValueTypeNames.Float).Set(float(value) * scale)


class PhysicsLayerExporter:
    """
    authors UsdPhysics data as overs on the prims the mesh exporter writes. export() runs for each
    mesh while the geom layer is written; save() then adds the constraint joints, which need every
    rigid body of the asset, and writes the layer.
    """
    def __init__(self, asset_name, output_path, meter_per_unit, mesh_scale=1.0, up_axis=UsdGeom.Tokens.z):
        self.asset_name = asset_name
        self.meter_per_unit = meter_per_unit
        self.mesh_scale = mesh_scale
        self.stage = Usd.Stage.CreateNew(output_path)
        UsdGeom.SetStageMetersPerUnit(self.stage, meter_per_unit)
        UsdGeom.SetStageUpAxis(self.stage, up_axis)
        self.joints_path = UsdGeom.Scope.Define(self.stage, joints_scope_path(asset_name)).GetPath()
        self.motors_data = self._get_motors_data()
        # Blender object name -> RigidBody, filled by export()
        self.bodies = {}

    def save(self):
        self._add_constraints()
        self.stage.Save()

    def export(self, blender_obj, prim_path):
        # export rigid body
        blender_rb = blender_obj.rigid_body
        if not blender_rb:
            return

        body = self._create_rigid_body(blender_obj, blender_rb, Sdf.Path(prim_path))
        self.bodies[blender_obj.name_full] = body

        # handle passive rigid body
        if blender_rb.type == "PASSIVE":
            self._add_world_fixed_joint(blender_obj, body)

    def _create_rigid_body(self, blender_obj, blender_rb, mesh_path):
        # overs only: this layer adds APIs to prims the geom layer defines. A def with a type here
        # would replace the Mesh type whenever this layer is the stronger one
        collision_prim = self.stage.OverridePrim(mesh_path)
        body_path = self._rigid_body_path(mesh_path)
        if body_path == mesh_path:
            body_prim = collision_prim
            # the mesh exporter writes the mesh's world matrix on the mesh prim
            body_matrix = blender_obj.matrix_world.copy()
        else:
            body_prim = self.stage.OverridePrim(body_path)
            # the geom layer leaves collection prims typeless and a rigid body has to be Xformable.
            # They carry no transform, so the body frame is the world frame
            body_prim.SetTypeName("Xform")
            body_matrix = Matrix.Identity(4)

        # sets rigid bodies APIs and mass
        rb_api = UsdPhysics.RigidBodyAPI.Apply(body_prim)
        rb_api.CreateRigidBodyEnabledAttr(True)
        mass_api = UsdPhysics.MassAPI.Apply(body_prim)
        mass_api.CreateMassAttr(blender_rb.mass)

        UsdPhysics.CollisionAPI.Apply(collision_prim)
        mesh_collision = UsdPhysics.MeshCollisionAPI.Apply(collision_prim)
        mesh_collision.CreateApproximationAttr(UsdPhysics.Tokens.convexDecomposition)
        return RigidBody(body_path, body_matrix)

    def _rigid_body_path(self, mesh_path):
        """
        a mesh named "collisions*", or inside a "collisions*" collection, is the collider of the
        link that holds it, e.g. base_link/collisions/base_link_collisions. The rigid body goes on
        that link, so the link's visuals move with it in the simulation.
        Any other rigid body mesh is its own body.
        """
        if not (is_collisions_name(mesh_path.name) or is_collisions_name(mesh_path.GetParentPath().name)):
            return mesh_path

        body_path = mesh_path.GetParentPath()
        while is_collisions_name(body_path.name):
            body_path = body_path.GetParentPath()

        geom_scopes = [Sdf.Path(geom_scope_path(self.asset_name, has_skeleton)) for has_skeleton in (False, True)]
        if not any(body_path.HasPrefix(scope) and body_path != scope for scope in geom_scopes):
            logger.warning(f"Collision mesh {mesh_path} has no link prim above it, its rigid body goes on the mesh")
            return mesh_path
        return body_path

    def _add_world_fixed_joint(self, blender_obj, body):
        """
        a fixed joint with no body0 pins a passive body to the world. With no body0 the frame-0
        attributes are in world space; they default to the world origin, which would pull the body
        there when the simulation starts, so the frame is placed at the body's origin instead
        """
        fixed_joint = UsdPhysics.FixedJoint.Define(self.stage, self.joints_path.AppendChild(sanitize_name(blender_obj.name)))
        fixed_joint.CreateBody1Rel().SetTargets([body.prim_path])
        local_pos0, local_rot0 = joint_local_frame(body.matrix_world, None, self.mesh_scale)
        fixed_joint.CreateLocalPos0Attr(local_pos0)
        fixed_joint.CreateLocalRot0Attr(local_rot0)

    def _add_constraints(self):
        for constraint_obj in bpy.context.scene.objects:
            rb_constraint = constraint_obj.rigid_body_constraint
            if rb_constraint is None:
                continue

            bodies = [
                self.bodies.get(obj.name_full) if obj else None
                for obj in (rb_constraint.object1, rb_constraint.object2)
            ]
            if not any(bodies):
                # constraint of another asset
                continue
            if not all(bodies):
                logger.warning(
                    f"Skipping constraint '{constraint_obj.name}': object1 and object2 must both be "
                    f"rigid bodies of '{self.asset_name}'"
                )
                continue
            if bodies[0].prim_path == bodies[1].prim_path:
                logger.warning(f"Skipping constraint '{constraint_obj.name}': both objects are the body {bodies[0].prim_path}")
                continue

            constructor = ConstraintsConstructor(self.stage, constraint_obj, self.mesh_scale, self.meter_per_unit)
            constructor.create_usd_joint(self.joints_path, bodies[0], bodies[1], self.motors_data)

    @staticmethod
    def _get_motors_data():
        """motor specs from isaac_sim.json next to the .blend file, keyed by motor name"""
        if not bpy.data.is_saved:
            return {}
        motors_path = os.path.join(os.path.dirname(bpy.data.filepath), MOTORS_JSON_FILENAME)
        if not os.path.exists(motors_path):
            return {}
        try:
            with open(motors_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as err:
            logger.error(f"Can't read {motors_path}, joints are exported without motors: {err}")
            return {}
