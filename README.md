# Monke Pipeline

A Blender → OpenUSD asset publishing pipeline. It exports Blender scenes as
layered, versioned USD assets (geometry, materials, armature/skinning,
LOD/material variants), and resolves them at runtime through a custom OpenUSD
asset resolver plugin using a `monkeDisc://` URI scheme, so downstream apps
(usdview, Omniverse Kit) always load the latest published version of a layer
without hardcoded paths.

## Components

- **`publisher/`** — the Blender-side collector and USD exporter.
  - `collector.py` — walks Blender collections and builds the asset/variant/LOD
    tree from naming conventions.
  - `exporter/` — writes the USD layers (`mesh.py`, `materials.py`,
    `material_binding.py`, `armature.py`, `usd_exporter.py` orchestrates them
    all into a main asset file with sublayers).
  - `proxy_generator/` — generates decimated LOD proxy meshes before export.
- **`templates/`** — the path templating and versioning engine
    (`templates.json` defines the on-disk layout, `templates.py` resolves and
    versions paths).
- **`ui/`** — the PySide6 export dialog, registered into Blender as a top-bar
  menu via `publisher_plugin.py`.
- **`usd_asset_resolver/`** — a C++ `ArResolver` plugin implementing the
  `monkeDisc://` URI scheme, so USD layers can reference each other by asset
  name and resolve to whichever version is tagged `:latest` on disk. It's
  only used for the three sublayer references (`geom`/`look`/`rig`) inside
  each asset's main `.usda` file — see below if you'd rather skip building it.
- **`run_blender.py` / `run_usdview.sh` / `run_omniverse.sh`** — launchers
  that source `pipeline.env` and start each host application with the
  correct plugin/library paths.

## Prerequisites

- **OpenUSD**, built from source or installed to a known prefix (headers +
  CMake `pxr` package config required — a `pip install usd-core` wheel is
  *not* enough, since the resolver plugin compiles against USD's C++ headers).
- **CMake ≥ 3.12** and a C++17 compiler.
- **OpenGL, X11, Python3 development headers** (linked by the resolver
  plugin — see `usd_asset_resolver/CMakeLists.txt`).
- **Blender** (tested against 3.6+), installed as a Flatpak
  (`org.blender.Blender` by default — see `run_blender.py`).
- **PySide6**, installed into a Python environment that Blender's own
  interpreter can see (Blender doesn't ship PySide6; `run_blender.py` appends
  your venv's `site-packages` to `sys.path` at launch instead of installing
  into Blender itself).
- **OdenGraphQt**, installed into a Python environment that Blender's own, it's 
  important for exporting nodoes.
- *(Optional)* **usdview**, if you want to inspect published assets outside
  Blender.
- *(Optional)* **Omniverse Kit** (via `kit-app-template`), if you want to
  load assets in Kit.

## ⚠️ Build the asset resolver against your own OpenUSD version

The compiled resolver plugin (`usd_asset_resolver/build/libmonke_resolver.so`)
links directly against USD's `ar` library and is **not** portable across USD
versions or builds — USD does not guarantee plugin ABI compatibility across
releases. **You must build `usd_asset_resolver` yourself, against the exact
OpenUSD build/version each host application uses**, not reuse a `.so` built
on another machine or against another USD version. Concretely:

- For **Blender/usdview**, build against the same OpenUSD install those apps
  load at runtime (`pxr_DIR` in `usd_asset_resolver/build.sh`).
- For **Omniverse Kit**, Kit bundles its own USD build and does not ship
  headers — `usd_asset_resolver/build_kit.sh` compiles against a separately
  built headless OpenUSD matching Kit's USD tag purely to get compatible
  headers, but **links** against Kit's own `libusd_ar.so` at build time, so
  the plugin shares the exact USD binary Kit already has loaded instead of
  pulling in a second, incompatible copy (which would duplicate `TfType`
  registrations and crash the app on load).

If you upgrade OpenUSD, or move to a machine with a different USD build,
**rebuild the resolver** before anything else — a stale/mismatched
`libmonke_resolver.so` will fail to load or crash the host process, not just
fail to resolve paths.

### Skipping the resolver entirely

The resolver's footprint is small and optional: `usd_exporter.py` uses
`monkeDisc://` only for the three sublayer entries (`geom`/`look`/`rig`) it
writes into an asset's main `.usda` file — everything else the exporter
writes (variant/LOD references, material-binding sublayers) already uses
plain relative paths and needs no resolver at all.

If you don't want to build the plugin, open the exported main `.usda` file
in a text editor, find the `subLayers` entries that look like
`@monkeDisc://assets/<name>/layers/<name>_geom_<version>.usda:latest@`, and
replace each with a regular relative path to the actual versioned file it
points at, e.g. `@./layers/<name>_geom_v001.usda@`. USD resolves plain
relative/`./` paths natively, no `ArResolver` plugin required — you'll just
have to update those three lines by hand whenever you re-export a newer
version, instead of `:latest` doing it for you automatically.

## Setup

1. **Build OpenUSD** (or point at an existing install) and note its install
   prefix — you'll need it for both the resolver build and `pipeline.env`.

2. **Build the resolver plugin** for each host app you'll use:

   ```bash
   cd usd_asset_resolver
   ./build.sh        # Blender / usdview, edit USD_INSTALL_DIR inside first
   ./build_kit.sh     # Omniverse Kit, edit the paths inside first
   ```

   Both scripts currently have machine paths hardcoded at the top — edit
   `USD_INSTALL_DIR` / `USD_HEADERS_DIR` / `KIT_APP_TEMPLATE_DIR` before
   running, or pass equivalent `-D...` overrides to `cmake` directly.

3. **Copy `pipeline.env.example` to `pipeline.env`** and fill in paths for
   your machine (`pipeline.env` is gitignored — it's machine-specific):

   | Variable | Purpose |
   |---|---|
   | `PROJECTNAME` | Name of the project whose assets you're publishing/loading |
   | `PROJECTSROOT` | Root folder projects live under |
   | `MONKENAME` | Author name stamped into exported layer metadata |
   | `LD_LIBRARY_PATH` | Path to your OpenUSD `lib/` directory |
   | `PXR_PLUGINPATH_NAME_BLENDER` | `usd_asset_resolver/build` (resolver built for Blender/usdview) |
   | `PXR_PLUGINPATH_NAME_OMNIVERSE` | `usd_asset_resolver/build_kit` (resolver built for Kit) |
   | `PXR_PLUGINPATH_NAME_USDVIEW` | Same as `PXR_PLUGINPATH_NAME_BLENDER` unless you use a separate USD build for usdview |
   | `BLENDER_FLATPAK_APP_ID` | Flatpak app id, e.g. `org.blender.Blender` |
   | `PYSIDE6_SITE_PACKAGES` | `site-packages` of a venv with PySide6 installed |
   | `QT_QPA_PLATFORM` | Qt platform plugin for usdview (`xcb` on Linux/X11) |
   | `USDVIEW_LAUNCHER` | Path to your `usdview` launch script/binary |
   | `OMNIVERSE_KIT_LAUNCHER` | Path to `kit-app-template`'s `repo.sh` |
   | `OMNIVERSE_KIT_APP` | Kit app id to launch |

4. **Launch Blender with the pipeline plugin registered:**

   ```bash
   python3 run_blender.py
   ```

   This starts Blender (as the configured Flatpak app) with the pipeline's
   environment variables injected and `publisher_plugin.register()` run at
   startup, adding a **Monke Pipeline** menu to Blender's top bar.

5. **(Optional) Inspect published assets in usdview:**

   ```bash
   ./run_usdview.sh
   ```

6. **(Optional) Load published assets in Omniverse Kit:**

   ```bash
   ./run_omniverse.sh
   ```

## Publishing an asset

1. In Blender, organize the scene under a collection at `/Scene
   Collection/assets`, with one child collection per asset. Meshes go under
   the asset collection directly, or under `<set>_VAR_<variant>` sub-collections
   to define variant sets (LOD uses a reserved `lod` set with `render`/`proxy`
   variants). Armatures go in a child collection literally named `armature`.
2. Open **Monke Pipeline → USD Export** from the top bar.
3. Pick which assets and layers (geometry/materials/armature) to export, set
   up axis, meters-per-unit, mesh scale, and (optionally) proxy LOD
   auto-generation.
4. Export — this writes a versioned main asset file plus per-step sublayers
   under `<PROJECTSROOT>/<PROJECTNAME>/assets/<asset_name>/`, per
   `templates/templates.json`.

## Running tests

```bash
python3 -m unittest test/ar_resolver_test.py
```

This requires the resolver plugin to already be built and
`PXR_PLUGINPATH_NAME_USDVIEW` (or equivalent) to point at it — it isn't a
pure-Python unit test, it round-trips a real `Ar.GetResolver().Resolve()`
call.
