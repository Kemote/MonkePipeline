import os
import bpy
import math
import json

from collections import deque, namedtuple
from mathutils import Matrix
from pxr import Usd, UsdGeom, UsdPhysics, Gf, Sdf
from exporter.layers_exporters.common import (
    geom_scope_path,
    joints_scope_path,
    sanitize_name,
    set_stage_metrics,
    unique_child_path,
)
from exporter.monke_logging import get_logger


logger = get_logger(__name__)
COLLISIONS_COLLECTION_PREFIX = "collisions"
MOTORS_JSON_FILENAME = "isaac_sim.json"
ROOT_JOINT_NAME = "root_joint"

# Blender collision shapes with a direct UsdPhysics mesh approximation. MESH and CONVEX_HULL
# depend on the body, see PhysicsLayerExporter._collision_approximation
COLLISION_APPROXIMATIONS = {
    "BOX": UsdPhysics.Tokens.boundingCube,
    "SPHERE": UsdPhysics.Tokens.boundingSphere,
    "COMPOUND": UsdPhysics.Tokens.convexDecomposition,
}

# prim_path: the prim holding RigidBodyAPI, matrix_world: that prim's world matrix in Blender space,
# passive: Blender PASSIVE rigid body, animated: Blender's "Animated" option, mass: Blender mass
RigidBody = namedtuple("RigidBody", ["prim_path", "matrix_world", "passive", "animated", "mass"])


def is_collisions_collection_name(name):
    return name.lower().startswith(COLLISIONS_COLLECTION_PREFIX)


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
        self.flip = False

    def create_usd_joint(self, joints_path, body0, body1, motors_data, flip=False, exclude=False):
        """
        flip: swap the bodies so body0 is the parent in the articulation tree. Both local frames come
              from the same constraint matrix, so only the sign of the joint position changes
        exclude: the joint closes a loop and is solved outside the articulation
        """
        joint_schema = self.JOINT_SCHEMAS.get(self.rb_constraint.type)
        if joint_schema is None:
            logger.warning(f"Skipping constraint '{self.name}': {self.rb_constraint.type} constraints aren't exported")
            return None

        self.flip = flip
        if flip:
            body0, body1 = body1, body0
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

        if exclude:
            self.joint.CreateExcludeFromArticulationAttr(True)
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
        if self.flip:
            # with the bodies swapped the joint moves the other way: [l, u] becomes [-u, -l]
            lower, upper = (-upper if upper is not None else None), (-lower if lower is not None else None)
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


class ArticulationPlan:
    """
    turns the asset's constraints into articulation trees. PhysX solves an articulation in reduced
    coordinates, so its joints can't stretch the way separate joints do, but it needs a tree: one
    root, joints from parent (body0) to child (body1), no loops and no kinematic links.
    For each group of jointed bodies it works out:
    - fixed_bases: the group's passive body. It's held by a fixed joint instead of being kinematic.
      A group without a passive body is a floating base, walked from its heaviest body
    - flipped: constraints whose object1/object2 order points from child to parent
    - excluded: constraints that close a loop, solved as regular joints outside the articulation
    - unjointed_passive: passive bodies without constraints, they stay static or kinematic
    """
    def __init__(self, bodies, constraints):
        """bodies: iterable of RigidBody, constraints: [(constraint_name, body0, body1)]"""
        self.fixed_bases = []
        self.unjointed_passive = []
        self.flipped = set()
        self.excluded = set()

        # several Blender objects can share one body prim, the body is passive if any of them is
        self.bodies = {}
        for body in bodies:
            known = self.bodies.get(body.prim_path)
            if known is None or (body.passive and not known.passive):
                self.bodies[body.prim_path] = body

        # body path -> [(constraint_name, other body path, this body is the constraint's body1)]
        self.edges = {path: [] for path in self.bodies}
        for name, body0, body1 in constraints:
            self.edges[body0.prim_path].append((name, body1.prim_path, False))
            self.edges[body1.prim_path].append((name, body0.prim_path, True))

        visited = set()
        for path in sorted(self.bodies):
            if path in visited:
                continue
            group = self._group(path)
            visited |= group
            if len(group) == 1 and not self.edges[path]:
                if self.bodies[path].passive:
                    self.unjointed_passive.append(self.bodies[path])
                continue

            passive = sorted(p for p in group if self.bodies[p].passive)
            if passive:
                root = passive[0]
                self.fixed_bases.append(self.bodies[root])
                if len(passive) > 1:
                    logger.warning(
                        f"Jointed bodies {', '.join(str(p) for p in passive)} are all passive. {root} is the fixed "
                        "base, the others are simulated: an articulation can't have kinematic links"
                    )
            else:
                root = max(sorted(group), key=lambda p: self.bodies[p].mass)
                logger.info(f"Jointed bodies around {root} have no passive body, they form a floating base articulation")
            self._walk(root)

    def _group(self, start):
        group = {start}
        queue = deque([start])
        while queue:
            for _, other, _ in self.edges[queue.popleft()]:
                if other not in group:
                    group.add(other)
                    queue.append(other)
        return group

    def _walk(self, root):
        """breadth first from the root: the first constraint reaching a body makes it a child"""
        reached = {root}
        seen_constraints = set()
        queue = deque([root])
        while queue:
            parent = queue.popleft()
            for name, child, parent_is_body1 in self.edges[parent]:
                if name in seen_constraints:
                    continue
                seen_constraints.add(name)
                if child in reached:
                    self.excluded.add(name)
                    continue
                reached.add(child)
                if parent_is_body1:
                    self.flipped.add(name)
                queue.append(child)


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
        self.output_path = output_path
        # kept in memory until save(), so assets without rigid bodies write no file
        self.stage = Usd.Stage.CreateInMemory()
        set_stage_metrics(self.stage, meter_per_unit, up_axis)
        self.joints_path = UsdGeom.Scope.Define(self.stage, joints_scope_path(asset_name)).GetPath()
        self.motors_data = self._get_motors_data()
        # Blender object name -> RigidBody, filled by export()
        self.bodies = {}
        # (collider mesh path, Blender object, body path), filled by export()
        self.colliders = []

    def save(self):
        """writes the layer and returns its path, or None when the asset has no rigid bodies"""
        if not self.bodies:
            return None
        constraints = self._asset_constraints()
        plan = ArticulationPlan(self.bodies.values(), [(obj.name_full, b0, b1) for obj, b0, b1 in constraints])
        static_paths, kinematic_paths = self._author_bodies(plan)
        self._author_colliders(static_paths, kinematic_paths)
        self._add_constraints(constraints, plan)
        self.stage.GetRootLayer().Export(self.output_path)
        return self.output_path

    def export(self, blender_obj, prim_path):
        """records a rigid body mesh. What it becomes depends on every constraint, so save() authors it"""
        blender_rb = blender_obj.rigid_body
        if not blender_rb:
            return

        mesh_path = Sdf.Path(prim_path)
        body_path = self._rigid_body_path(mesh_path)
        # the mesh exporter writes the mesh's world matrix on the mesh prim. Link prims carry no
        # transform, so a body on a link has the world frame
        body_matrix = blender_obj.matrix_world.copy() if body_path == mesh_path else Matrix.Identity(4)
        self.bodies[blender_obj.name_full] = RigidBody(
            body_path, body_matrix, blender_rb.type == "PASSIVE", blender_rb.kinematic, blender_rb.mass
        )
        self.colliders.append((mesh_path, blender_obj, body_path))

    def _author_bodies(self, plan):
        """
        a passive body without constraints is a static collider: no RigidBodyAPI at all, which is the
        usual setup for floors and furniture and allows exact triangle collision. With Blender's
        "Animated" option it's kinematic instead. Every other body is simulated.
        Returns the static and the kinematic body paths
        """
        static_paths = {body.prim_path for body in plan.unjointed_passive if not body.animated}
        kinematic_paths = {body.prim_path for body in plan.unjointed_passive if body.animated}

        # several Blender objects can make up one body (colliders of one link), their masses add up
        masses = {}
        for body in self.bodies.values():
            masses[body.prim_path] = masses.get(body.prim_path, 0.0) + body.mass

        collider_paths = {mesh_path for mesh_path, _, _ in self.colliders}
        for body_path, mass in masses.items():
            if body_path in static_paths:
                continue
            # overs only: this layer adds APIs to prims the geom layer defines. A def with a type here
            # would replace the Mesh type whenever this layer is the stronger one
            body_prim = self.stage.OverridePrim(body_path)
            if body_path not in collider_paths:
                # the geom layer leaves collection prims typeless and a rigid body has to be Xformable
                body_prim.SetTypeName("Xform")
            rb_api = UsdPhysics.RigidBodyAPI.Apply(body_prim)
            rb_api.CreateRigidBodyEnabledAttr(True)
            if body_path in kinematic_paths:
                rb_api.CreateKinematicEnabledAttr(True)
            UsdPhysics.MassAPI.Apply(body_prim).CreateMassAttr(mass)
        return static_paths, kinematic_paths

    def _author_colliders(self, static_paths, kinematic_paths):
        for mesh_path, blender_obj, body_path in self.colliders:
            collision_prim = self.stage.OverridePrim(mesh_path)
            UsdPhysics.CollisionAPI.Apply(collision_prim)
            simulated = body_path not in static_paths and body_path not in kinematic_paths
            approximation = self._collision_approximation(blender_obj, simulated)
            UsdPhysics.MeshCollisionAPI.Apply(collision_prim).CreateApproximationAttr(approximation)

    @staticmethod
    def _collision_approximation(blender_obj, simulated):
        """
        follows the Blender collision shape. PhysX only takes exact triangle meshes ("none") on static
        and kinematic bodies, so a simulated MESH shape is split into convex pieces instead
        """
        shape = blender_obj.rigid_body.collision_shape
        if shape in COLLISION_APPROXIMATIONS:
            return COLLISION_APPROXIMATIONS[shape]
        if shape == "MESH":
            return UsdPhysics.Tokens.convexDecomposition if simulated else UsdPhysics.Tokens.none

        # CONVEX_HULL, and CAPSULE, CYLINDER and CONE, which have no UsdPhysics mesh approximation
        if PhysicsLayerExporter._is_flat(blender_obj):
            # the hull of a flat mesh (a floor plane) has no volume and PhysX can fail to build it
            if not simulated:
                return UsdPhysics.Tokens.none
            logger.warning(
                f"'{blender_obj.name}' is flat and simulated, its convex hull has no volume and may not "
                "collide. Give it some thickness"
            )
        return UsdPhysics.Tokens.convexHull

    @staticmethod
    def _is_flat(blender_obj):
        extents = [max(corner[axis] for corner in blender_obj.bound_box) - min(corner[axis] for corner in blender_obj.bound_box)
                   for axis in range(3)]
        return min(extents) <= 1e-6 * max(max(extents), 1e-12)

    def _rigid_body_path(self, mesh_path):
        """
        a mesh named "collisions*", or inside a "collisions*" collection, is the collider of the
        link that holds it, e.g. base_link/collisions/base_link_collisions. The rigid body goes on
        that link, so the link's visuals move with it in the simulation.
        Any other rigid body mesh is its own body.
        """
        if not (is_collisions_collection_name(mesh_path.name) or is_collisions_collection_name(mesh_path.GetParentPath().name)):
            return mesh_path

        body_path = mesh_path.GetParentPath()
        while is_collisions_collection_name(body_path.name):
            body_path = body_path.GetParentPath()

        geom_scopes = [Sdf.Path(geom_scope_path(self.asset_name, has_skeleton)) for has_skeleton in (False, True)]
        if not any(body_path.HasPrefix(scope) and body_path != scope for scope in geom_scopes):
            logger.warning(f"Collision mesh {mesh_path} has no link prim above it, its rigid body goes on the mesh")
            return mesh_path
        return body_path

    def _add_constraints(self, constraints, plan):
        for constraint_obj, body0, body1 in constraints:
            constructor = ConstraintsConstructor(self.stage, constraint_obj, self.mesh_scale, self.meter_per_unit)
            constructor.create_usd_joint(
                self.joints_path, body0, body1, self.motors_data,
                flip=constraint_obj.name_full in plan.flipped,
                exclude=constraint_obj.name_full in plan.excluded,
            )

        if constraints:
            self._add_articulation_root(plan)

    def _add_articulation_root(self, plan):
        """
        the articulation root goes on the asset's root prim, so it covers every jointed group and
        carries over to each place the asset is referenced
        """
        asset_path = Sdf.Path(f"/{sanitize_name(self.asset_name)}")
        root_prim = self.stage.OverridePrim(asset_path)
        UsdPhysics.ArticulationRootAPI.Apply(root_prim)
        # links that aren't jointed together don't collide, like Isaac's URDF importer sets it.
        # Authored by name, Blender's pxr has no PhysxSchema
        root_prim.AddAppliedSchema("PhysxArticulationAPI")
        root_prim.CreateAttribute("physxArticulation:enabledSelfCollisions", Sdf.ValueTypeNames.Bool).Set(False)

        for base in plan.fixed_bases:
            # body0 is the asset's root prim, which isn't a rigid body: physics parsers then attach the
            # joint to the world, with localPos0 read relative to that prim. So every instance is fixed
            # where the world layer places it, instead of at the asset's own origin
            joint_path = unique_child_path(self.stage, self.joints_path, ROOT_JOINT_NAME)
            joint = UsdPhysics.FixedJoint.Define(self.stage, joint_path)
            joint.CreateBody0Rel().SetTargets([asset_path])
            joint.CreateBody1Rel().SetTargets([base.prim_path])
            local_pos0, local_rot0 = joint_local_frame(base.matrix_world, None, self.mesh_scale)
            local_pos1, local_rot1 = joint_local_frame(base.matrix_world, base, self.mesh_scale)
            joint.CreateLocalPos0Attr(local_pos0)
            joint.CreateLocalRot0Attr(local_rot0)
            joint.CreateLocalPos1Attr(local_pos1)
            joint.CreateLocalRot1Attr(local_rot1)

        logger.info(
            f"Articulation on {asset_path}: fixed bases {[str(b.prim_path) for b in plan.fixed_bases]}, "
            f"flipped joints {sorted(plan.flipped)}, joints outside the articulation {sorted(plan.excluded)}"
        )

    def _asset_constraints(self):
        """[(constraint_obj, body0, body1)] for the constraints between two rigid bodies of this asset"""
        constraints = []
        for constraint_obj in sorted(bpy.context.scene.objects, key=lambda obj: obj.name_full):
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
            if rb_constraint.type not in ConstraintsConstructor.JOINT_SCHEMAS:
                logger.warning(f"Skipping constraint '{constraint_obj.name}': {rb_constraint.type} constraints aren't exported")
                continue
            constraints.append((constraint_obj, bodies[0], bodies[1]))
        return constraints

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
