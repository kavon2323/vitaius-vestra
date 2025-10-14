# vitaius_vestra_designer.py
# Vitaius – Vestra Designer (single-file Blender add-on)

bl_info = {
    "name": "Vitaius – Vestra Designer",
    "author": "Vitaius",
    "version": (1, 8, 0),
    "blender": (3, 6, 0),
    "location": "3D View > Sidebar (N) > Vitaius",
    "description": "Mirror & base-fitting tools for Vestra Forms custom prosthetics",
    "category": "3D View",
}

import bpy
import bmesh
import struct
from mathutils import Vector, Matrix
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import (
    StringProperty, FloatProperty, EnumProperty, BoolProperty,
    PointerProperty
)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def mm_to_m(x_mm: float) -> float:
    return x_mm * 0.001

def ensure_stl_addon_enabled():
    """Enable Blender's STL exporter if available."""
    mod = "io_mesh_stl"
    if mod not in bpy.context.preferences.addons:
        try:
            bpy.ops.preferences.addon_enable(module=mod)
        except Exception:
            pass  # We'll fallback to our own writer if needed.

def write_binary_stl_from_object(obj: bpy.types.Object, filepath: str):
    """
    Minimal binary STL writer (fallback if io_mesh_stl is unavailable).
    Exports the CURRENT evaluated mesh of obj with simple triangulation.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(mesh)
    bm.free()

    with open(filepath, "wb") as f:
        # 80-byte header
        f.write(b"Vitaius-Vestra binary STL" + b"\0" * (80 - len("Vitaius-Vestra binary STL")))
        f.write(struct.pack("<I", len(mesh.polygons)))  # number of triangles

        verts = mesh.vertices
        loops = mesh.loops

        for poly in mesh.polygons:
            n = poly.normal
            f.write(struct.pack("<3f", n.x, n.y, n.z))
            idxs = [loops[i].vertex_index for i in poly.loop_indices]
            if len(idxs) != 3:
                # Should not happen after triangulation
                continue
            for vid in idxs:
                v = verts[vid].co
                f.write(struct.pack("<3f", v.x, v.y, v.z))
            f.write(struct.pack("<H", 0))  # attribute byte count

    eval_obj.to_mesh_clear()

def get_or_create_midline():
    """Create an Empty named 'Midline' at world origin if not present."""
    mid = bpy.data.objects.get("Midline")
    if mid is None:
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
        mid = bpy.context.active_object
        mid.name = "Midline"
    return mid

def active_mesh_or_none():
    obj = bpy.context.active_object
    if obj and obj.type == 'MESH':
        return obj
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Properties (UI State)
# ──────────────────────────────────────────────────────────────────────────────

class VEStraProps(PropertyGroup):
    treat_units_as_mm: BoolProperty(
        name="Treat units as millimeters",
        default=True,
        description="When set, numeric mm offsets are converted to meters internally"
    )
    mirror_axis: EnumProperty(
        name="Axis",
        items=[
            ('X', "X", "Mirror across X (left/right)"),
            ('Y', "Y", "Mirror across Y (front/back)"),
            ('Z', "Z", "Mirror across Z (up/down)"),
        ],
        default='X'
    )
    base_offset_mm: FloatProperty(
        name="Base Comfort Offset (mm)",
        description="Small offset to relieve base (positive lifts away)",
        default=2.0, min=-10.0, max=20.0
    )
    chest_wall_obj: PointerProperty(
        name="Chest Wall",
        type=bpy.types.Object,
        description="Select the chest wall mesh used to fit the base"
    )
    mold_padding_mm: FloatProperty(
        name="Mold Padding (mm)",
        description="Extra shell thickness for mold generation",
        default=10.0, min=0.0, max=50.0
    )

# ──────────────────────────────────────────────────────────────────────────────
# Operators
# ──────────────────────────────────────────────────────────────────────────────

class VES_OT_import_scan(Operator):
    """Import scan (.stl/.obj/.ply)"""
    bl_idname = "vitaius.import_scan"
    bl_label = "Step 1 — Import Scan"

    filepath: StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        path = self.filepath
        if not path:
            self.report({'ERROR'}, "No file chosen.")
            return {'CANCELLED'}
        ensure_stl_addon_enabled()
        ext = path.lower().split('.')[-1]
        try:
            if ext == "stl":
                bpy.ops.import_mesh.stl(filepath=path)
            elif ext == "obj":
                bpy.ops.wm.obj_import(filepath=path)
            elif ext == "ply":
                bpy.ops.wm.ply_import(filepath=path)
            else:
                self.report({'ERROR'}, f"Unsupported extension: .{ext}")
                return {'CANCELLED'}
        except Exception as e:
            self.report({'ERROR'}, f"Import failed: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class VES_OT_clean_orient(Operator):
    """Clean transforms, orient scan to +Y front, +Z up, and center midline at X=0"""
    bl_idname = "vitaius.clean_orient"
    bl_label = "Step 2 — Clean & Orient"

    def execute(self, context):
        obj = active_mesh_or_none()
        if obj is None:
            self.report({'ERROR'}, "Select the breast mesh first.")
            return {'CANCELLED'}

        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        # Ensure object is roughly facing +Y (front). User can adjust manually if needed.
        obj.rotation_euler = (0.0, 0.0, 0.0)

        # Move object so midline is at X=0 by centering its origin on geometry bounds
        # and then offsetting to world X=0.
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        obj.location.x = 0.0  # align origin to world X=0 as a simple midline proxy

        # Create/center Midline helper
        get_or_create_midline().location = (0.0, 0.0, 0.0)
        self.report({'INFO'}, "Oriented. Midline at X=0.")
        return {'FINISHED'}


class VES_OT_mirror_true(Operator):
    """Create a true mirrored copy across chosen axis about the Midline object"""
    bl_idname = "vitaius.mirror_true"
    bl_label = "Step 3 — Mirror Across Midline (True Object Mirror)"

    def execute(self, context):
        props = context.scene.vvestra
        axis = props.mirror_axis
        src = active_mesh_or_none()
        if src is None:
            self.report({'ERROR'}, "Select the breast mesh to mirror.")
            return {'CANCELLED'}

        mid = get_or_create_midline()

        # Duplicate and add Mirror modifier using Midline as reference object
        dup = src.copy()
        dup.data = src.data.copy()
        dup.name = f"{src.name}_Mirrored"
        context.collection.objects.link(dup)
        context.view_layer.objects.active = dup

        mod = dup.modifiers.new(name="TrueMirror", type='MIRROR')
        mod.mirror_object = mid
        mod.use_axis[0] = (axis == 'X')
        mod.use_axis[1] = (axis == 'Y')
        mod.use_axis[2] = (axis == 'Z')
        mod.use_bisect_axis[0] = False
        mod.use_bisect_axis[1] = False
        mod.use_bisect_axis[2] = False

        # Apply modifier to make it real geometry
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except Exception as e:
            self.report({'ERROR'}, f"Mirror apply failed: {e}")
            return {'CANCELLED'}

        # Put mirrored object on the opposite side (if it overlaps)
        # Center around midline by flipping sign on axis coordinate if needed.
        if axis == 'X' and dup.location.x == src.location.x:
            dup.location.x = -src.location.x
        elif axis == 'Y' and dup.location.y == src.location.y:
            dup.location.y = -src.location.y
        elif axis == 'Z' and dup.location.z == src.location.z:
            dup.location.z = -src.location.z

        self.report({'INFO'}, f"Created {dup.name}")
        return {'FINISHED'}


class VES_OT_fit_base(Operator):
    """Conform base of selected prosthetic to chest wall using Shrinkwrap offset"""
    bl_idname = "vitaius.fit_base"
    bl_label = "Step 4 — Fit Base to Chest Wall"

    def execute(self, context):
        props = context.scene.vvestra
        cw = props.chest_wall_obj
        if cw is None or cw.type != 'MESH':
            self.report({'ERROR'}, "Pick a Chest Wall mesh in the field above.")
            return {'CANCELLED'}

        obj = active_mesh_or_none()
        if obj is None:
            self.report({'ERROR'}, "Select the prosthetic mesh to fit.")
            return {'CANCELLED'}

        # Add Shrinkwrap to push base toward chest wall with small offset
        off_m = mm_to_m(props.base_offset_mm) if props.treat_units_as_mm else props.base_offset_mm

        sw = obj.modifiers.new(name="BaseFit", type='SHRINKWRAP')
        sw.target = cw
        sw.wrap_method = 'NEAREST_SURFACEPOINT'
        sw.offset = off_m

        try:
            bpy.ops.object.modifier_apply(modifier=sw.name)
        except Exception as e:
            self.report({'ERROR'}, f"Fit apply failed: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, "Base fitted to chest wall.")
        return {'FINISHED'}


class VES_OT_export_stl(Operator):
    """Export prosthetic STL (Vitaius Vestra naming)"""
    bl_idname = "vitaius.export_stl"
    bl_label = "Step 5 — Export Prosthetic STL"

    filepath: StringProperty(subtype="FILE_PATH", options={'HIDDEN'})

    def execute(self, context):
        obj = active_mesh_or_none()
        if obj is None:
            self.report({'ERROR'}, "Select prosthetic object to export.")
            return {'CANCELLED'}

        ensure_stl_addon_enabled()
        default_name = "vitaius_vestra_prosthetic.stl"
        path = self.filepath or bpy.path.abspath(f"//{default_name}")

        # Try Blender exporter first
        try:
            op = getattr(bpy.ops.export_mesh, "stl")
            op(filepath=path, use_selection=True, ascii=False)
            self.report({'INFO'}, f"Exported to: {path}")
            return {'FINISHED'}
        except Exception:
            # Fallback to internal writer
            try:
                write_binary_stl_from_object(obj, path)
                self.report({'INFO'}, f"Exported (fallback) to: {path}")
                return {'FINISHED'}
            except Exception as e:
                self.report({'ERROR'}, f"Export failed: {e}")
                return {'CANCELLED'}


class VES_OT_export_mold(Operator):
    """Generate simple mold shell and export STL (Vitaius Vestra naming)"""
    bl_idname = "vitaius.export_mold"
    bl_label = "Step 6 — Generate Mold STL"

    def execute(self, context):
        props = context.scene.vvestra
        src = active_mesh_or_none()
        if src is None:
            self.report({'ERROR'}, "Select prosthetic object first.")
            return {'CANCELLED'}

        # Duplicate and make a simple thick shell as a mold
        dup = src.copy()
        dup.data = src.data.copy()
        dup.name = f"{src.name}_Mold"
        context.collection.objects.link(dup)
        context.view_layer.objects.active = dup

        thickness = mm_to_m(props.mold_padding_mm) if props.treat_units_as_mm else props.mold_padding_mm
        solid = dup.modifiers.new(name="MoldSolid", type='SOLIDIFY')
        solid.thickness = thickness
        solid.offset = 1.0
        try:
            bpy.ops.object.modifier_apply(modifier=solid.name)
        except Exception as e:
            self.report({'ERROR'}, f"Mold generation failed: {e}")
            return {'CANCELLED'}

        # Export
        ensure_stl_addon_enabled()
        path = bpy.path.abspath("//vitaius_vestra_mold.stl")
        try:
            op = getattr(bpy.ops.export_mesh, "stl")
            # select only dup for export
            bpy.ops.object.select_all(action='DESELECT')
            dup.select_set(True)
            op(filepath=path, use_selection=True, ascii=False)
            self.report({'INFO'}, f"Mold exported to: {path}")
        except Exception:
            try:
                write_binary_stl_from_object(dup, path)
                self.report({'INFO'}, f"Mold exported (fallback) to: {path}")
            except Exception as e:
                self.report({'ERROR'}, f"Mold export failed: {e}")
                return {'CANCELLED'}
        return {'FINISHED'}


# ──────────────────────────────────────────────────────────────────────────────
# UI Panel
# ──────────────────────────────────────────────────────────────────────────────

class VES_PT_panel(Panel):
    bl_label = "Vitaius – Vestra Designer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Vitaius"

    def draw(self, context):
        layout = self.layout
        props = context.scene.vvestra

        col = layout.column(align=True)
        col.operator("vitaius.import_scan", icon='IMPORT')

        box = layout.box()
        box.label(text="Step 2 — Clean & Orient", icon='ORIENTATION_VIEW')
        box.prop(props, "treat_units_as_mm")
        box.operator("vitaius.clean_orient", icon='ORIENTATION_GLOBAL')

        box3 = layout.box()
        box3.label(text="Step 3 — Mirror Across Midline", icon='MOD_MIRROR')
        box3.prop(props, "mirror_axis", text="Axis")
        box3.operator("vitaius.mirror_true", icon='MOD_MIRROR')

        box4 = layout.box()
        box4.label(text="Step 4 — Fit Base", icon='MOD_SHRINKWRAP')
        box4.prop(props, "chest_wall_obj", text="Chest Wall")
        box4.prop(props, "base_offset_mm")
        box4.operator("vitaius.fit_base", icon='CHECKMARK')

        col2 = layout.column(align=True)
        col2.separator()
        col2.operator("vitaius.export_stl", icon='EXPORT')
        col2.prop(props, "mold_padding_mm")
        col2.operator("vitaius.export_mold", icon='MESH_CUBE')


# ──────────────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────────────

classes = (
    VEStraProps,
    VES_OT_import_scan,
    VES_OT_clean_orient,
    VES_OT_mirror_true,
    VES_OT_fit_base,
    VES_OT_export_stl,
    VES_OT_export_mold,
    VES_PT_panel,
)

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.vvestra = PointerProperty(type=VEStraProps)

def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    if hasattr(bpy.types.Scene, "vvestra"):
        del bpy.types.Scene.vvestra

if __name__ == "__main__":
    register()
