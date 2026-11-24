# Monke Pipeline

A Blender → OpenUSD publishing pipeline for simulation-ready assets. It exports
Blender scenes as layered, versioned USD assets (geometry, materials,
armature/skinning, physics, LOD/material variants) plus a world layout and
lights, so the same scene loads correctly in Isaac Sim, Omniverse and usdview.
Robots come out as articulations with joints, limits and motor drives, ready
to simulate. An optional custom OpenUSD asset resolver (`monkeDisc://`) lets
apps load the latest published version of each layer without hardcoded paths.

## Components

- **`exporter/`** — the Blender-side collectors and USD exporters.
  - `collectors/collector_assets.py` — walks Blender collections and builds the
    asset/variant/LOD tree from naming conventions.
  - `collectors/collector_world.py` — reads Geometry Nodes instancers and the
    asset placements they generate, for the world layout.
  - `layers_exporters/` — writes the USD layers: `mesh.py` (points, UVs,
    subdivision scheme, skinning, purposes), `materials.py` and
    `material_binding.py` (UsdPreviewSurface), `armature.py` (UsdSkel),
    `physics.py` (rigid bodies, colliders, joints, articulations, motor drives)
    and `lights.py` (UsdLux). `usd_exporter.py` orchestrates them into a main
    asset file with sublayers, and writes the world file.
  - `ui/exporter_ui.py` — the PySide6 export dialog.
- **`proxy_generator/`** — generates decimated proxy meshes before export, for
  `visuals*` collections or a `lod_VAR_render` collection (see below).
- **`convex_hull_generator/`** — a Blender tool that builds collision meshes
  from selected objects: one convex hull per object, unioned into one mesh.
- **`templates/`** — the path templating and versioning engine
  (`templates.json` defines the on-disk layout, `templates.py` resolves and
  versions paths).
- **`usd_asset_resolver/`** — an optional C++ `ArResolver` plugin implementing
  the `monkeDisc://` URI scheme, so sublayer references resolve to whichever
  version is newest on disk (`:latest`).
- **`publisher_plugin.py` / `run_blender.py`** — `run_blender.py` sources
  `pipeline.env` and starts the Blender Flatpak with the plugin registered,
  which adds a **Monke Pipeline** menu (**USD Export**, **Generate Collision
  Object**) to Blender's top bar.

## Prerequisites

- **Blender 5.2 or newer**, installed as a Flatpak (`org.blender.Blender` by default —
  see `run_blender.py`). Blender ships its own `pxr`, which the exporter uses.
- **PySide6**, in a `site-packages` folder that Blender's Python 3.13 can
  import (Blender doesn't ship PySide6; `run_blender.py` appends the folder
  from `PYSIDE6_SITE_PACKAGES` to `sys.path` at launch instead of installing
  into Blender itself).
- *(Optional)* **Isaac Sim** or another **Omniverse Kit** app, to simulate or
  view the exported scenes.
- *(Optional)* **usdview**, to inspect published assets outside Blender.
- *(Optional, only for the `monkeDisc://` resolver)* **OpenUSD** built from
  source with headers and the CMake `pxr` package config (a `pip install
  usd-core` wheel is *not* enough), **CMake ≥ 3.12** and a C++17 compiler.

## ⚠️ The asset resolver is optional — and must match your OpenUSD build

The export dialog's **Sublayers AssetResolver** option decides how an asset's
main file points at its sublayers (`geom`/`look`/`rig`/`physics`):

- **Default** — plain paths relative to the main file, pointing at the newest
  version of each step. Loads in any app with no plugin. Use this for Isaac
  Sim, Unreal and Unity.
- **MonkeResolver** — `monkeDisc://…:latest` paths, resolved at load time by
  the plugin. Needs the plugin built and loaded in every app that opens the
  files, and `PROJECTSROOT`/`PROJECTNAME` set.

Everything else the exporter writes (variant and LOD layers, material
bindings, textures, world references) always uses plain relative paths.

If you use the resolver: the compiled plugin
(`usd_asset_resolver/build/libmonke_resolver.so`) links directly against USD's
`ar` library and is **not** portable across USD versions or builds — USD does
not guarantee plugin ABI compatibility across releases. **Build it yourself,
against the exact OpenUSD build each host application uses**:

- For **Blender/usdview**, build against the same OpenUSD install those apps
  load at runtime (`USD_INSTALL_DIR` for `usd_asset_resolver/build.sh`).
- For **Omniverse Kit**, Kit bundles its own USD build and does not ship
  headers — `usd_asset_resolver/build_kit.sh` compiles against a separately
  built headless OpenUSD matching Kit's USD tag purely to get compatible
  headers, but **links** against Kit's own `libusd_ar.so`, so the plugin
  shares the USD binary Kit already has loaded instead of pulling in a second,
  incompatible copy (which would duplicate `TfType` registrations and crash
  the app on load).

A stale or mismatched `libmonke_resolver.so` will fail to load or crash the
host process, not just fail to resolve paths.

## Setup

1. **Copy `pipeline.env.example` to `pipeline.env`** and fill in paths for
   your machine (`pipeline.env` is gitignored — it's machine-specific):

   | Variable | Purpose |
   |---|---|
   | `PROJECTSROOT` / `PROJECTNAME` | *Optional.* Output location `<PROJECTSROOT>/<PROJECTNAME>`. Left empty, the export goes to `<blend name>_usd` next to the .blend file. Required by the resolver |
   | `MONKENAME` | Author name stamped into exported layer metadata |
   | `BLENDER_FLATPAK_APP_ID` | Flatpak app id, e.g. `org.blender.Blender` |
   | `PYSIDE6_SITE_PACKAGES` | `site-packages` folder with PySide6 for Blender's Python |
   | `QT_QPA_PLATFORM` | `xcb` runs the Qt dialog through XWayland, so it stays on top on Wayland |
   | `LD_LIBRARY_PATH` | Your OpenUSD `lib/` directory (resolver only) |
   | `PXR_PLUGINPATH_NAME_BLENDER` | `usd_asset_resolver/build` (resolver only) |
   | `PXR_PLUGINPATH_NAME_USDVIEW` | Resolver build for usdview, used by the resolver test |
   | `PXR_PLUGINPATH_NAME_OMNIVERSE` | `usd_asset_resolver/build_kit` (resolver built for Kit) |

2. *(Optional)* **Build the resolver plugin** for each host app you'll use:

   ```bash
   # Blender / usdview: the OpenUSD install those apps load
   USD_INSTALL_DIR=/path/to/OpenUSD ./usd_asset_resolver/build.sh
   # Omniverse Kit: headers from an OpenUSD build matching Kit's USD tag,
   # plus your kit-app-template checkout
   USD_HEADERS_DIR=/path/to/OpenUSD_25_11 KIT_APP_TEMPLATE_DIR=/path/to/kit-app-template \
       ./usd_asset_resolver/build_kit.sh
   ```

   Without the variables, the scripts look in `~/UsdRoot`,
   `~/UsdRoot_25_11` and `~/kit-app-template`.

3. **Launch Blender with the pipeline plugin registered:**

   ```bash
   python3 run_blender.py
   ```

   This starts Blender (as the configured Flatpak app) with the pipeline's
   environment variables injected and `publisher_plugin.register()` run at
   startup. Blender keeps the exporter's Python modules loaded, so restart it
   after changing the pipeline code.

## Scene conventions

**Assets**

- Each asset is a child collection of `/Scene Collection/assets`.
- `<set>_VAR_<variant>` collections define variant sets, nested to any depth.
  Materials named `<base>_VAR_<variant>` define material variants.
- `lod` is a reserved set: `lod_VAR_render` and `lod_VAR_proxy` map to USD
  `render`/`proxy` purposes, not to variants.
- Armatures go in a child collection literally named `armature`.
- A mesh with a Subdivision Surface modifier is exported as its base mesh
  with the matching `subdivisionScheme`. Realtime renderers such as Isaac
  Sim's show the base mesh unless their refinement level is raised. Other
  non-deforming modifiers (Mirror, Geometry Nodes, …) aren't applied yet;
  apply them before export, the exporter logs a warning for each.

**Materials**

- Each material's **Principled BSDF** becomes a `UsdPreviewSurface`: base
  color, metallic, roughness, IOR, alpha, coat, emission and normal map.
  Other shader nodes aren't translated; a material without a Principled BSDF
  is exported as flat magenta so it's easy to spot.
- An **Image Texture** node linked to one of those inputs becomes a
  `UsdUVTexture`, and its image is copied into the asset's `textures/` folder:
  - **Extension** sets the wrap mode: Repeat → `repeat`, Extend → `clamp`,
    Clip → `black`, Mirror → `mirror`. Use Repeat for tiling textures.
  - The image's **colour space** sets `sourceColorSpace`: sRGB → `sRGB`,
    Non-Color or any linear space → `raw`. Set data maps (roughness,
    metallic, normal) to Non-Color, as Blender itself expects.
  - The **output socket** you link picks the channel: Color → `rgb` (or `r`
    for a single-value input), Alpha → `a`. A JPG has no alpha, so link its
    Color output.
- A Normal Map node with an Image Texture is exported as a tangent-space
  normal map (scale 2, bias −1).
- Textures read the mesh's active UV map, exported as the `st` primvar.

**Proxy LOD** (*Generate proxy LOD* in the dialog)

- With a `lod_VAR_render` collection, its meshes are decimated into a
  `proxy` LOD layer.
- Without one, every mesh in a `visuals*` collection gets a decimated
  `<name>_proxy` sibling with `purpose = proxy`, linked from the render mesh
  through `proxyPrim`. The proxy sits under the same link as the render mesh,
  so it also follows the simulation. Use this mode for robots.
- Collision meshes never get proxies.

**Physics** (Blender rigid bodies and rigid body constraints)

- A robot link is a collection, e.g. `base_link/{visuals, collisions}`. The
  rigid body mesh inside a `collisions*` collection becomes the link's
  collider, and the rigid body goes on the link, so its visuals move with it.
- FIXED, HINGE and SLIDER constraints become `FixedJoint`, `RevoluteJoint` and
  `PrismaticJoint`. Assets with joints get an `ArticulationRootAPI`; joints are
  ordered parent → child and loops are excluded from the articulation.
- A **passive** body that has joints is the robot's fixed base: it's held by a
  fixed joint to the world, wherever the world layout places the asset. A
  passive body without joints is a static collider, or kinematic when
  Blender's **Animated** option is on.
- The collider follows Blender's collision shape: Convex Hull → `convexHull`,
  Mesh → exact triangles on static colliders and `convexDecomposition` on
  simulated bodies, Box → `boundingCube`, Sphere → `boundingSphere`.
- Motor data comes from `isaac_sim.json` next to the .blend file, keyed by the
  first part of the constraint name (`st3020_1` → `"st3020"`): max torque,
  stiffness, damping, velocity limit, armature and friction become an angular
  drive and PhysX joint settings.
- A **slider moved by a rotary motor** through a mechanism (a gripper finger
  pushed by a servo-driven disc, a rack and pinion, a crank) gets a linear
  drive converted from that motor. Name the constraint after the motor
  (`st3020_grip_l`) and add a Float custom property `finger_travel_per_rad_m`
  to its Empty: the slider's travel in metres per radian of the motor,
  averaged over the stroke (e.g. 23 mm over 70° → 0.023 / 1.222 ≈ 0.0188).
  The exporter converts the motor through that ratio: force = torque / r,
  speed = angular speed × r, stiffness and damping ÷ r², armature ÷ r². A
  slider with a motor but no ratio is exported without a drive, with a
  warning.

**Driving the robot in Isaac Sim**

Every exported joint with a motor has a position drive, so during Play the
robot moves to whatever target you set — from the Property panel, or from
Python by setting the joint prim's drive target:

```python
joints = "/World/robots/monkeArm_001/Joints"
stage.GetPrimAtPath(f"{joints}/st3020_2").GetAttribute(
    "drive:angular:physics:targetPosition").Set(45.0)      # degrees
# close the gripper 20 mm: the fingers are mirrored, so the right one is negative
stage.GetPrimAtPath(f"{joints}/st3020_grip_l").GetAttribute(
    "drive:linear:physics:targetPosition").Set(0.02)       # stage units (m)
stage.GetPrimAtPath(f"{joints}/st3020_grip_r").GetAttribute(
    "drive:linear:physics:targetPosition").Set(-0.02)
```

Target 0 is the pose the robot was exported in. The fingers and the disc
that drives them on the real robot are separate joints in the simulation, so
command them together: disc angle θ, fingers at the matching travel.

**Generating collision meshes** (**Monke Pipeline → Generate Collision
Object**)

A link's visual meshes are usually too detailed to collide with. The
generator builds one convex hull per selected mesh and boolean-unions them
into a single triangulated `<name>__COLLISION` mesh, shown as wireframe:

1. Select the link's visual meshes and open the tool (they're added to the
   list automatically, or use **Add selected**).
2. Keep **Use standard parameters**, or set:
   - **Merge distance** — points closer than this are merged before hulling
     (scene units).
   - **Dissolve angle** — coplanar neighbour faces up to this angle are
     merged, for fewer triangles.
   - **Max vertices (warn)** — warns when a hull has more vertices than PhysX
     allows for one convex hull (64 by default).
3. Under **Output**, optionally set a name, whether to parent the source
   meshes to the collision mesh, and whether to apply its transform.
4. **Generate**, then move the result into the link's `collisions`
   collection and give it a rigid body with the **Mesh** collision shape. The
   union of several hulls isn't convex, so on a simulated link it's exported
   as `convexDecomposition`.

**World layout** (*Export world* in the dialog)

- Objects with an empty base geometry and a Geometry Nodes modifier that
  instances asset collections are read as placements. Each placement becomes
  a prim referencing the asset, under `/World/<collection path>`.
- The instancer's name prefix sets how it's referenced: `INST_…` makes the
  placements instanceable, `REF_…` plain references. `REF_` is the safer
  choice for anything with physics, since physics engines handle bodies
  inside instanced prims in limited ways.
- An Empty at an instance point names that placement.
- Lights are exported to a separate world sublayer, and a `PhysicsScene` is
  added when physics is exported.

## Publishing

1. Open **Monke Pipeline → USD Export** from the top bar.
2. Pick the assets and layers (geometry/materials/armature/physics), whether
   to export the world and lights, the up axis, meters per unit, mesh scale,
   the sublayer resolver and (optionally) proxy LOD generation.
   **Light exposure offset** adds stops to every light's exposure: the
   default of 10 suits Isaac Sim and Omniverse RTX, which need far more light
   than Blender for the same image; 0 writes the same values as Blender's own
   USD exporter.
3. Export — this writes a main file plus versioned sublayers per asset, and
   the world file, following `templates/templates.json`:

   ```
   <PROJECTSROOT>/<PROJECTNAME>/
   ├── <PROJECTNAME>.usda                  world: layout, lights, PhysicsScene
   ├── layers/<PROJECTNAME>_lights_v001.usda
   └── assets/<asset>/
       ├── <asset>.usda                    main file, sublayers the newest versions
       ├── layers/<asset>_{geom,look,rig,physics}_v001.usda
       ├── layers/mesh_variants/…          variant and LOD layers
       └── textures/
   ```

4. Open the world file in Isaac Sim and press Play.

## Running tests

```bash
python3 -m unittest test/ar_resolver_test.py
```

This requires the resolver plugin to already be built for this machine and
`PXR_PLUGINPATH_NAME_USDVIEW` to point at it — it isn't a pure-Python unit
test, it round-trips a real `Ar.GetResolver().Resolve()` call.
