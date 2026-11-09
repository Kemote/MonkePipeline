from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

import bmesh
import bpy
from mathutils import Matrix

__all__ = ["COLLISION_SUFFIX", "ConvexHullParams", "CollisionHullBuilder"]

log = logging.getLogger(__name__)

COLLISION_SUFFIX = "__COLLISION"


@dataclass(frozen=True)
class ConvexHullParams:
    """Standard parameters, used when the caller provides none."""

    # Points closer than this are merged before hulling (scene units).
    merge_distance: float = 1e-4
    # Coplanar neighbour faces are dissolved up to this angle (radians). 0 = off.
    dissolve_angle: float = math.radians(1.0)
    # PhysX convex hulls are limited (64 verts by default). Only warns for now.
    max_vertices: Optional[int] = 64


class CollisionHullBuilder:
    def __init__(self, default_params: Optional[ConvexHullParams] = None):
        self.default_params = default_params or ConvexHullParams()

    # ------------------------------------------------------------------ API
    def generate(
        self,
        objects: Iterable[bpy.types.Object],
        hull_params: Optional[ConvexHullParams] = None,
        parent_to_final: bool = False,
        name: Optional[str] = None,
    ) -> bpy.types.Object:
        """Build and return the ``__COLLISION`` object for ``objects``."""
        sources = self._validate(objects)
        source_set: Set[bpy.types.Object] = set(sources)
        params = hull_params or self.default_params

        collision_name = self._collision_name(sources[0], name)
        self._remove_existing(collision_name, source_set)
        bpy.context.view_layer.update()

        roots = [o for o in sources if o.parent not in source_set]
        origin = self._hull_origin(sources[0])

        # --- hull mesh (no materials: fresh datablock, nothing assigned) ---
        mesh = bpy.data.meshes.new(collision_name)
        self._fill_hull_mesh(mesh, sources, origin, params)

        collision = bpy.data.objects.new(collision_name, mesh)
        cols = list(sources[0].users_collection) or [bpy.context.scene.collection]
        for col in cols:
            col.objects.link(collision)
        collision.display_type = "WIRE"

        outer_parent = roots[0].parent if roots else None
        if outer_parent is not None and self._has_ancestor_in(outer_parent, source_set):
            outer_parent = None  # would create a parent cycle
        if outer_parent is not None:
            collision.parent = outer_parent
        collision.matrix_world = origin
        bpy.context.view_layer.update()

        # --- optional parenting (world transforms kept) ---
        if parent_to_final:
            for src in roots:
                world = src.matrix_world.copy()
                src.parent = collision
                src.parent_type = "OBJECT"
                src.matrix_parent_inverse = Matrix.Identity(4)
                src.matrix_world = world

        bpy.context.view_layer.update()
        return collision

    # ------------------------------------------------------------ internals
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
        base = name or first.name
        return base if base.endswith(COLLISION_SUFFIX) else base + COLLISION_SUFFIX

    @staticmethod
    def _remove_existing(name: str, source_set: Set[bpy.types.Object]) -> None:
        """Re-running the pipeline replaces the previous result instead of
        producing ``Name__COLLISION.001``."""
        old = bpy.data.objects.get(name)
        if old is not None:
            if old in source_set:
                raise ValueError(f"{name} is one of the source objects")
            kept = [(c, c.matrix_world.copy()) for c in old.children]
            old_mesh = old.data
            bpy.data.objects.remove(old, do_unlink=True)
            if old_mesh is not None and old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh)
            for child, world in kept:
                child.matrix_world = world
        orphan = bpy.data.meshes.get(name)
        if orphan is not None and orphan.users == 0:
            bpy.data.meshes.remove(orphan)

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
        depsgraph = bpy.context.evaluated_depsgraph_get()
        to_local = origin.inverted()

        bm = bmesh.new()
        try:
            # Evaluated mesh == "copy + apply all modifiers", without touching
            # the source and without needing bpy.ops.object.join().
            for src in sources:
                tmp = bpy.data.meshes.new_from_object(
                    src.evaluated_get(depsgraph),
                    preserve_all_data_layers=False,
                    depsgraph=depsgraph,
                )
                if tmp is None:
                    raise RuntimeError(f"Could not evaluate {src.name}")
                try:
                    tmp.transform(to_local @ src.matrix_world)
                    for v in tmp.vertices:
                        bm.verts.new(v.co)
                finally:
                    bpy.data.meshes.remove(tmp)

            if not bm.verts:
                raise ValueError("Source meshes contain no vertices")

            if params.merge_distance > 0.0:
                bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=params.merge_distance)

            res = bmesh.ops.convex_hull(bm, input=bm.verts[:])
            # An element can be listed in both outputs; delete() rejects duplicates.
            discard = set(res["geom_unused"]) | set(res["geom_interior"])
            if discard:
                bmesh.ops.delete(bm, geom=list(discard), context="VERTS")
            if not bm.faces:
                raise ValueError("Convex hull is degenerate (flat or too few points)")

            if params.dissolve_angle > 0.0:
                bmesh.ops.dissolve_limit(
                    bm,
                    angle_limit=params.dissolve_angle,
                    verts=bm.verts[:],
                    edges=bm.edges[:],
                )
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

            if params.max_vertices and len(bm.verts) > params.max_vertices:
                log.warning(
                    "%s: hull has %d vertices (limit %d) - PhysX may reject or re-cook it",
                    mesh.name, len(bm.verts), params.max_vertices,
                )

            bm.to_mesh(mesh)
        finally:
            bm.free()
        mesh.update()