from __future__ import annotations

import bpy
import math
import bmesh
import logging

from mathutils import Matrix
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set


log = logging.getLogger(__name__)
COLLISION_SUFFIX = "__COLLISION"


@dataclass(frozen=True)
class ConvexHullParams:
    # Standard parameters, used when the caller provides none.
    # Points closer than this are merged before hulling (scene units).
    merge_distance: float = 1e-4
    # Coplanar neighbour faces are dissolved up to this angle (radians). 0 = off.
    dissolve_angle: float = math.radians(1.0)
    # PhysX convex hulls are limited (64 verts by default). Only warns for now.
    max_vertices: Optional[int] = 64


class CollisionHullBuilder:
    def __init__(self, default_params: Optional[ConvexHullParams] = None):
        self.default_params = default_params or ConvexHullParams()

    def generate(
        self,
        objects: Iterable[bpy.types.Object],
        hull_params: Optional[ConvexHullParams] = None,
        parent_to_final: bool = False,
        name: Optional[str] = None,
        apply_transform: bool = True,
    ) -> bpy.types.Object:
                
        objects_list = self._validate(objects)
        params = hull_params or self.default_params

        collision_name = self._collision_name(objects_list[0], name)
        roots = [o for o in objects_list if o.parent not in objects_list]
        origin = self._hull_origin(objects_list[0])


        mesh = bpy.data.meshes.new(collision_name)
        self._fill_hull_mesh(mesh, objects_list, origin, params)

        collision = bpy.data.objects.new(collision_name, mesh)
        cols = list(objects_list[0].users_collection) or [bpy.context.scene.collection]
        for col in cols:
            col.objects.link(collision)
        collision.display_type = "WIRE"

        outer_parent = roots[0].parent if roots else None
        if outer_parent is not None and self._has_ancestor_in(outer_parent, objects_list):
            outer_parent = None  # would create a parent cycle
        if outer_parent is not None:
            collision.parent = outer_parent
        collision.matrix_world = origin
        bpy.context.view_layer.update()

        # Before parenting the sources, so they don't need compensating
        # for the collision object's transform changing under them.
        if apply_transform:
            self._apply_transform(collision)

        if parent_to_final:
            for src in roots:
                world = src.matrix_world.copy()
                src.parent = collision
                src.parent_type = "OBJECT"
                src.matrix_parent_inverse = Matrix.Identity(4)
                src.matrix_world = world

        bpy.context.view_layer.update()
        return collision

    @staticmethod
    def _apply_transform(obj: bpy.types.Object) -> None:
        """Bake location, rotation and scale into the mesh, like Blender's
        Apply > All Transforms: the local transform becomes identity and the
        world-space shape stays where it was."""
        basis = obj.matrix_basis.copy()
        obj.data.transform(basis)
        # A negative scale mirrors the mesh and turns the faces inside out.
        if basis.determinant() < 0.0:
            obj.data.flip_normals()
        obj.data.update()
        obj.matrix_basis = Matrix.Identity(4)
        bpy.context.view_layer.update()

    @staticmethod
    def _validate(objects: Iterable[bpy.types.Object]) -> List[bpy.types.Object]:
        sources: List[bpy.types.Object] = []
        for obj in objects:
            if obj is None or obj.type != "MESH":
                raise TypeError(f"Not a mesh object: {obj!r}")
            if obj.name.endswith(COLLISION_SUFFIX):
                raise ValueError(f"{obj.name} is already a collision mesh")
            if bpy.context.view_layer.objects.get(obj.name) is None:
                raise ValueError(f"{obj.name} is not in the active view layer")
            if obj not in sources:
                sources.append(obj)
        if not sources:
            raise ValueError("No mesh objects given")
        return sources

    @staticmethod
    def _collision_name(first: bpy.types.Object, name: Optional[str]) -> str:
        # get name for collision name we creating
        base = name or first.name
        return base if base.endswith(COLLISION_SUFFIX) else base + COLLISION_SUFFIX

    @staticmethod
    def _hull_origin(first: bpy.types.Object) -> Matrix:
        """Location + rotation of the first object, no scale."""
        loc, rot, _ = first.matrix_world.decompose()
        return Matrix.LocRotScale(loc, rot, None)

    @staticmethod
    def _has_ancestor_in(obj: bpy.types.Object, objects: Set[bpy.types.Object]) -> bool:
        while obj is not None:
            if obj in objects:
                return True
            obj = obj.parent
        return False

    def _fill_hull_mesh(
        self,
        mesh: bpy.types.Mesh,
        sources: List[bpy.types.Object],
        origin: Matrix,
        params: ConvexHullParams,
    ) -> None:
        """One convex hull per source object, boolean-unioned into one
        triangulated solid.

        The union of several hulls is generally NOT convex. PhysX accepts a
        non-convex triangle mesh only on static or kinematic bodies; on a
        dynamic rigid body it has to be re-approximated (convexHull,
        convexDecomposition or sdf) when authored to USD.
        """
        depsgraph = bpy.context.evaluated_depsgraph_get()
        to_local = origin.inverted()

        hull_meshes: List[bpy.types.Mesh] = []
        try:
            for src in sources:
                hull_meshes.append(
                    self._source_hull_mesh(src, depsgraph, to_local, params)
                )

            result = bmesh.new()
            try:
                if len(hull_meshes) == 1:
                    result.from_mesh(hull_meshes[0])
                else:
                    self._boolean_union(hull_meshes, result)

                if not result.faces:
                    raise ValueError("Boolean union of the hulls is empty")

                # The boolean can leave coincident verts where hulls touch.
                if params.merge_distance > 0.0:
                    bmesh.ops.remove_doubles(result, verts=result.verts[:], dist=params.merge_distance)
                bmesh.ops.triangulate(result, faces=result.faces[:])
                bmesh.ops.recalc_face_normals(result, faces=result.faces[:])
                result.to_mesh(mesh)
            finally:
                result.free()
        finally:
            for hull_mesh in hull_meshes:
                bpy.data.meshes.remove(hull_mesh)
        mesh.update()

    @staticmethod
    def _source_hull_mesh(
        src: bpy.types.Object,
        depsgraph: bpy.types.Depsgraph,
        to_local: Matrix,
        params: ConvexHullParams,
    ) -> bpy.types.Mesh:
        """Convex hull of one source, in the collision object's local space.
        The caller owns the returned temporary mesh and must remove it."""
        # Evaluated mesh == "copy + apply all modifiers", without touching the source.
        tmp = bpy.data.meshes.new_from_object(
            src.evaluated_get(depsgraph),
            preserve_all_data_layers=False,
            depsgraph=depsgraph,
        )
        if tmp is None:
            raise RuntimeError(f"Could not evaluate {src.name}")

        hull_bmesh = bmesh.new()
        try:
            tmp.transform(to_local @ src.matrix_world)
            for v in tmp.vertices:
                hull_bmesh.verts.new(v.co)
            if not hull_bmesh.verts:
                raise ValueError(f"{src.name} contains no vertices")

            if params.merge_distance > 0.0:
                bmesh.ops.remove_doubles(hull_bmesh, verts=hull_bmesh.verts[:], dist=params.merge_distance)

            res = bmesh.ops.convex_hull(hull_bmesh, input=hull_bmesh.verts[:])
            discard = set(res["geom_unused"]) | set(res["geom_interior"])
            if discard:
                bmesh.ops.delete(hull_bmesh, geom=list(discard), context="VERTS")
            if not hull_bmesh.faces:
                raise ValueError(f"{src.name}: convex hull is degenerate (flat or too few points)")

            if params.dissolve_angle > 0.0:
                bmesh.ops.dissolve_limit(
                    hull_bmesh,
                    angle_limit=params.dissolve_angle,
                    verts=hull_bmesh.verts[:],
                    edges=hull_bmesh.edges[:],
                )
            bmesh.ops.recalc_face_normals(hull_bmesh, faces=hull_bmesh.faces[:])

            if params.max_vertices and len(hull_bmesh.verts) > params.max_vertices:
                log.warning(
                    "%s: hull has %d vertices (limit %d) - PhysX may reject or re-cook it",
                    src.name, len(hull_bmesh.verts), params.max_vertices,
                )

            # Reuse tmp to hold the hull instead of allocating another mesh.
            hull_bmesh.to_mesh(tmp)
        except Exception:
            bpy.data.meshes.remove(tmp)
            raise
        finally:
            hull_bmesh.free()
        return tmp

    @staticmethod
    def _boolean_union(hull_meshes: List[bpy.types.Mesh], result: bmesh.types.BMesh) -> None:
        """Union all hull meshes into ``result``.

        bmesh has no boolean op, so this goes through a Boolean modifier on
        temporary objects. Reading the evaluated mesh applies the modifier
        without bpy.ops, so it works from the Qt dialog and headless.
        """
        scene = bpy.context.scene
        # Operands must be in the view layer, or the depsgraph skips them.
        temp_col = bpy.data.collections.new("__collision_union_tmp")
        operand_col = bpy.data.collections.new("__collision_union_operands")
        scene.collection.children.link(temp_col)
        temp_objs: List[bpy.types.Object] = []
        try:
            for hull_mesh in hull_meshes:
                obj = bpy.data.objects.new(hull_mesh.name, hull_mesh)
                temp_col.objects.link(obj)
                temp_objs.append(obj)
            for obj in temp_objs[1:]:
                operand_col.objects.link(obj)

            mod = temp_objs[0].modifiers.new("union", "BOOLEAN")
            mod.operation = "UNION"
            mod.operand_type = "COLLECTION"
            mod.collection = operand_col
            # manifold solver is faster, and convex hulls are already manifolds
            mod.solver = "MANIFOLD"

            depsgraph = bpy.context.evaluated_depsgraph_get()
            result.from_object(temp_objs[0], depsgraph)
        finally:
            for obj in temp_objs:
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(operand_col)
            bpy.data.collections.remove(temp_col)