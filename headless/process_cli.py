# headless/process_cli.py
# Run INSIDE Blender with: blender -b -P headless/process_cli.py -- <args>

import sys
import os
import argparse

# Blender context imports
import bpy

# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Vitaius Vestra headless processor")
parser.add_argument("--addon_path", default="blender_addon/vitaius_vestra_designer.py",
                    help="Path to the Vitaius Vestra Designer add-on file")
parser.add_argument("--input", required=True, help="Path to input scan (.stl/.obj/.ply)")
parser.add_argument("--axis", default="X", choices=["X", "Y", "Z"], help="Mirror axis (default X)")
parser.add_argument("--midline", type=float, default=0.0, help="Midline world X/Y/Z value (used by add-on; default 0)")
parser.add_argument("--base_offset_mm", type=float, default=2.0, help="Base comfort offset in mm")
parser.add_argument("--mold_padding_mm", type=float, default=10.0, help="Mold padding (shell) in mm")
parser.add_argument("--chest_wall", default="", help="Optional path to chest wall mesh to fit against")
parser.add_argument("--out_prosthetic", default="", help="Output STL path for prosthetic")
parser.add_argument("--out_mold", default="", help="Output STL path for mold")
args, _ = parser.parse_known_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

# ─────────────────────────────────────────────────────────────────────
# Load the Vitaius add-on module dynamically
# ─────────────────────────────────────────────────────────────────────
addon_abspath = bpy.path.abspath("//" + args.addon_path) if not os.path.isabs(args.addon_path) else args.addon_path
if not os.path.isfile(addon_abspath):
    # Try repo-relative (run from repo root)
    addon_abspath = os.path.abspath(args.addon_path)
if not os.path.isfile(addon_abspath):
    raise RuntimeError(f"Add-on not found at {args.addon_path} (resolved {addon_abspath})")

# Execute the add-on file so all operators/classes are registered
bpy.ops.script.python_file_run(filepath=addon_abspath)

# Ensure the scene prop group exists (the add-on's register() creates it)
if not hasattr(bpy.types.Scene, "vvestra"):
    raise RuntimeError("Vitaius add-on did not register. Check addon_path.")

props = bpy.context.scene.vvestra
props.mirror_axis = args.axis
props.base_offset_mm = args.base_offset_mm
props.mold_padding_mm = args.mold_padding_mm
props.treat_units_as_mm = True

# ─────────────────────────────────────────────────────────────────────
# Helper: import a mesh file by extension (same as add-on)
# ─────────────────────────────────────────────────────────────────────
def import_scan(path):
    p = os.path.abspath(path)
    ext = os.path.splitext(p)[1].lower()
    if ext == ".stl":
        # Make sure STL import is available
        try:
            bpy.ops.preferences.addon_enable(module="io_mesh_stl")
        except Exception:
            pass
        bpy.ops.import_mesh.stl(filepath=p)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=p)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=p)
    else:
        raise RuntimeError(f"Unsupported input extension: {ext}")

# ─────────────────────────────────────────────────────────────────────
# Fresh scene
# ─────────────────────────────────────────────────────────────────────
bpy.ops.wm.read_homefile(use_empty=True)

# Import breast
import_scan(args.input)
breast = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = breast

# Optional: import chest wall
cw_obj = None
if args.chest_wall:
    import_scan(args.chest_wall)
    cw_obj = bpy.context.selected_objects[0]
    props.chest_wall_obj = cw_obj

# Step 2 — Clean & Orient
bpy.ops.vitaius.clean_orient()

# Step 3 — Mirror (true object mirror)
bpy.ops.object.select_all(action='DESELECT')
breast.select_set(True)
bpy.context.view_layer.objects.active = breast
bpy.ops.vitaius.mirror_true()

# Use the mirrored copy (name ends with _Mirrored)
mirrored = None
for obj in bpy.context.scene.objects:
    if obj.name.startswith(breast.name) and obj.name.endswith("_Mirrored"):
        mirrored = obj
        break
if mirrored is None:
    # Fallback: use active
    mirrored = bpy.context.active_object

# Step 4 — Fit base if chest wall provided
if cw_obj is not None:
    bpy.ops.object.select_all(action='DESELECT')
    mirrored.select_set(True)
    bpy.context.view_layer.objects.active = mirrored
    bpy.ops.vitaius.fit_base()

# Step 5 — Export Prosthetic STL
bpy.ops.object.select_all(action='DESELECT')
mirrored.select_set(True)
bpy.context.view_layer.objects.active = mirrored

if args.out_prosthetic:
    # Temporarily set a filepath property if operator supports it; otherwise the add-on writes default name.
    try:
        bpy.ops.vitaius.export_stl('INVOKE_DEFAULT')
        # Native exporter in the add-on writes to //vitaius_vestra_prosthetic.stl; move/rename if a custom path was passed.
        default_out = bpy.path.abspath("//vitaius_vestra_prosthetic.stl")
        if os.path.isfile(default_out) and os.path.abspath(args.out_prosthetic) != default_out:
            os.replace(default_out, os.path.abspath(args.out_prosthetic))
    except Exception as e:
        raise RuntimeError(f"Export prosthetic failed: {e}")
else:
    bpy.ops.vitaius.export_stl()

# Step 6 — Export Mold STL
if args.out_mold:
    try:
        bpy.ops.vitaius.export_mold('INVOKE_DEFAULT')
        default_mold = bpy.path.abspath("//vitaius_vestra_mold.stl")
        if os.path.isfile(default_mold) and os.path.abspath(args.out_mold) != default_mold:
            os.replace(default_mold, os.path.abspath(args.out_mold))
    except Exception as e:
        raise RuntimeError(f"Export mold failed: {e}")
else:
    bpy.ops.vitaius.export_mold()

print("Vitaius Vestra headless process: DONE")
