bl_info = {
    "name": "Sisters Prosthetics Designer",
    "author": "Sisters Prosthetics",
    "version": (2, 5, 0),
    "blender": (4, 5, 0),
    "location": "Sidebar > Sisters",
    "description": "Demo builder, robust STL import (fallback), true object mirror, base fit, export with fallback, mold generation with fallback.",
    "category": "3D View",
}

import bpy, os, struct, bmesh
from mathutils import Matrix, Vector

# --------------------------- Helpers ---------------------------

def ensure_midline(context=None):
    mid = bpy.data.objects.get("Midline")
    if not mid:
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0,0,0))
        mid = bpy.context.active_object
        mid.name = "Midline"
    return mid

def frame_object(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True); bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.view3d.view_selected(use_all_regions=False)
    except Exception:
        pass

def world_bbox_x(obj):
    coords = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    xs = [c.x for c in coords]
    return min(xs), max(xs), 0.5*(min(xs)+max(xs))

def count_vertices_left_right(obj):
    left = right = 0
    for v in obj.data.vertices:
        x = (obj.matrix_world @ v.co).x
        if x < 0: left += 1
        elif x > 0: right += 1
    return left, right

# -------- Minimal STL loader (binary + ASCII) fallback ----------
def load_stl_to_mesh(name, filepath):
    with open(filepath, 'rb') as f:
        data = f.read()

    def _try_binary(d):
        if len(d) < 84: return None
        tri_count = struct.unpack_from("<I", d, 80)[0]
        expected = 84 + tri_count * 50
        if len(d) < expected: return None
        verts, faces, vmap = [], [], {}
        def key(x,y,z): return (round(x,6), round(y,6), round(z,6))
        off = 84
        for _ in range(tri_count):
            vals = struct.unpack_from("<12f", d, off); off += 48
            _attr = struct.unpack_from("<H", d, off)[0]; off += 2
            v1 = vals[3:6]; v2 = vals[6:9]; v3 = vals[9:12]
            tri = []
            for vx,vy,vz in (v1,v2,v3):
                k = key(vx,vy,vz)
                if k not in vmap:
                    vmap[k] = len(verts); verts.append((vx,vy,vz))
                tri.append(vmap[k])
            faces.append(tuple(tri))
        return verts, faces

    def _try_ascii(d):
        try: text = d.decode('utf-8', errors='ignore')
        except Exception: return None
        if not text.lstrip().startswith('solid'): return None
        verts, faces, tri, vmap = [], [], [], {}
        def key(x,y,z): return (round(x,6), round(y,6), round(z,6))
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 4 and parts[0] == 'vertex':
                x,y,z = map(float, parts[1:4])
                k = key(x,y,z)
                if k not in vmap: vmap[k] = len(verts); verts.append((x,y,z))
                tri.append(vmap[k])
                if len(tri) == 3:
                    faces.append(tuple(tri)); tri=[]
        return (verts, faces) if faces else None

    parsed = _try_binary(data) or _try_ascii(data)
    if parsed is None:
        raise RuntimeError("Unrecognized STL (not valid binary or ASCII).")

    verts, faces = parsed
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.validate(clean_customdata=True); mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return obj

# -------- Binary STL writer fallback (when export add-on is off) ----------
def write_binary_stl_from_object(obj, filepath):
    """Export an object as Binary STL (world-space, triangulated)."""
    deps = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(deps)
    me = obj_eval.to_mesh()

    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    M = obj.matrix_world
    N = M.to_3x3().inverted().transposed()

    tris = []
    for f in bm.faces:
        n = (N @ f.normal).normalized()
        vs = [M @ v.co for v in f.verts]
        if len(vs) == 3:
            tris.append((n, vs[0], vs[1], vs[2]))

    with open(filepath, "wb") as f:
        f.write(b"Sisters Prosthetics STL".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for n, v1, v2, v3 in tris:
            f.write(struct.pack("<12f",
                                n.x, n.y, n.z,
                                v1.x, v1.y, v1.z,
                                v2.x, v2.y, v2.z,
                                v3.x, v3.y, v3.z))
            f.write(struct.pack("<H", 0))

    bm.free()
    obj_eval.to_mesh_clear()

# --------------------------- Properties ---------------------------

class SistersProps(bpy.types.PropertyGroup):
    chestwall_name: bpy.props.StringProperty(
        name="Chest Wall",
        description="Name of the chest wall mesh to fit against",
        default="ChestWall"
    )
    base_offset_mm: bpy.props.FloatProperty(
        name="Base Comfort Offset (mm)",
        description="Clearance between inner surface and chest wall",
        default=2.0, min=0.0, max=6.0, step=0.1
    )
    mold_padding_mm: bpy.props.FloatProperty(
        name="Mold Padding (mm)",
        description="Extra room around prosthetic inside the mold block",
        default=10.0, min=2.0, max=50.0, step=1.0
    )

# --------------------------- Operators ---------------------------

class SP_OT_build_demo(bpy.types.Operator):
    """Create two chest-wall blocks, a left breast dome, and a midline"""
    bl_idname = "sp.build_demo"
    bl_label = "Build Demo Scene"

    def execute(self, context):
        for name in ("ChestWall_L","ChestWall_R","ChestWall","Breast","Breast_Mirrored","Midline"):
            obj = bpy.data.objects.get(name)
            if obj: bpy.data.objects.remove(obj, do_unlink=True)

        scene = bpy.context.scene
        scene.unit_settings.system = 'METRIC'
        scene.unit_settings.scale_length = 0.001

        def add_wall(name, xloc):
            bpy.ops.mesh.primitive_cube_add(location=(xloc, 0.0, 0.0))
            w = bpy.context.active_object
            w.name = name
            w.scale = (0.400, 0.020, 0.300)                 # 400 x 20 x 300 mm
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')
            return w

        L = add_wall("ChestWall_L", -1.0)
        R = add_wall("ChestWall_R",  1.0)

        CW = L.copy(); CW.data = L.data.copy(); CW.name = "ChestWall"
        CW.location = (0.0, 0.0, 0.0)
        bpy.context.scene.collection.objects.link(CW)
        CW.hide_set(True)

        bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=0.120,
                                             location=(L.location.x, 0.070, 0.120))
        breast = bpy.context.active_object
        breast.name = "Breast"
        breast.scale.y *= 0.70
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(plane_co=(0.0, 0.010, 0.0), plane_no=(0.0, -1.0, 0.0),
                            clear_inner=True, clear_outer=False)
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')

        bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
        mid = bpy.context.active_object; mid.name = "Midline"
        mid.rotation_euler = (0.0, 0.0, 0.0)

        frame_object(breast)
        self.report({'INFO'}, "Demo built. Select Breast → Step 3B to mirror.")
        return {'FINISHED'}

class SP_OT_import_stl(bpy.types.Operator):
    bl_idname = "sp.import_stl"
    bl_label = "Step 1: Import Scan (.stl)"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        path = bpy.path.abspath(self.filepath)
        name = os.path.basename(path).rsplit(".",1)[0]

        obj = None
        try:
            op = getattr(bpy.ops.import_mesh, "stl")
            op(filepath=path)
            obj = context.selected_objects[0]
        except Exception:
            obj = load_stl_to_mesh(name, path)
            self.report({'INFO'}, "Fallback STL loader used (enable Blender's STL add-on for best performance).")

        scene = bpy.context.scene
        scene.unit_settings.system = 'METRIC'
        scene.unit_settings.scale_length = 0.001
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')
        frame_object(obj)
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class SP_OT_clean_origin(bpy.types.Operator):
    bl_idname = "sp.clean_origin"
    bl_label = "Step 2: Clean, Re-Origin & mm scale"

    def execute(self, context):
        scene = bpy.context.scene
        scene.unit_settings.system = 'METRIC'
        scene.unit_settings.scale_length = 0.001
        for obj in context.selected_objects:
            if obj.type != 'MESH': continue
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            try: bpy.ops.mesh.remove_doubles(threshold=0.0005)
            except: pass
            try: bpy.ops.mesh.normals_make_consistent(inside=False)
            except: pass
            bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, "Cleaned & re-originated (1 unit = 1 mm).")
        return {'FINISHED'}

class SP_OT_snap_midline(bpy.types.Operator):
    bl_idname = "sp.snap_midline"
    bl_label = "Step 3A: Snap Midline (X=0 or between L/R walls)"

    def execute(self, context):
        mid = ensure_midline(context)
        L = bpy.data.objects.get("ChestWall_L")
        R = bpy.data.objects.get("ChestWall_R")
        if L and R:
            _,_,cxL = world_bbox_x(L); _,_,cxR = world_bbox_x(R)
            mid.location = (0.5*(cxL+cxR), 0.0, 0.0)
        else:
            mid.location = (0.0, 0.0, 0.0)
        mid.rotation_euler = (0.0, 0.0, 0.0)
        frame_object(mid)
        return {'FINISHED'}

class SP_OT_mirror_selected(bpy.types.Operator):
    """Duplicate active mesh and reflect it as a true object across Midline (X-plane)"""
    bl_idname = "sp.mirror_selected"
    bl_label = "Step 3B: Mirror Across Midline (True Object Mirror)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        src = context.active_object
        if not src or src.type != 'MESH':
            self.report({'ERROR'}, "Select the healthy breast mesh before mirroring.")
            return {'CANCELLED'}

        mid = ensure_midline(context)
        mn, mx, cx = world_bbox_x(src)
        width = max(1e-9, mx - mn)
        if abs(cx - mid.location.x) < 1e-6:
            left, right = count_vertices_left_right(src)
            side = 1 if right >= left else -1
            nudge = max(width * 0.6, 0.03)  # ≥ 30 mm
            src.location.x += side * nudge

        bpy.ops.object.select_all(action='DESELECT')
        src.select_set(True); bpy.context.view_layer.objects.active = src
        bpy.ops.object.duplicate()
        dup = bpy.context.active_object
        dup.name = f"{src.name}_Mirrored"
        src.hide_set(True)

        T_to = Matrix.Translation(Vector((-mid.location.x,0,0)))
        S_refX = Matrix.Scale(-1.0, 4, Vector((1,0,0)))
        T_back = Matrix.Translation(Vector(( mid.location.x,0,0)))
        R = T_back @ S_refX @ T_to
        dup.matrix_world = R @ dup.matrix_world

        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        try: bpy.ops.mesh.normals_make_consistent(inside=False)
        except: pass
        bpy.ops.object.mode_set(mode='OBJECT')

        frame_object(dup)
        self.report({'INFO'}, f"Mirrored: {dup.name}")
        return {'FINISHED'}

class SP_OT_fit_base(bpy.types.Operator):
    """Add comfort offset and subtract chest wall geometry for a conforming base"""
    bl_idname = "sp.fit_base"
    bl_label = "Step 4: Fit Base to Chest Wall"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.sisters_props
        prosth = context.active_object
        if not prosth or prosth.type != 'MESH':
            self.report({'ERROR'}, "Select the mirrored prosthesis mesh first.")
            return {'CANCELLED'}

        cw = (bpy.data.objects.get(props.chestwall_name)
              or bpy.data.objects.get("ChestWall_L")
              or bpy.data.objects.get("ChestWall"))
        if not cw or cw.type != 'MESH':
            self.report({'ERROR'}, f"Chest wall '{props.chestwall_name}' not found.")
            return {'CANCELLED'}

        offset = props.base_offset_mm / 1000.0
        solid = prosth.modifiers.new("SP_ComfortOffset", 'SOLIDIFY')
        solid.thickness = -offset
        solid.offset = 0.0
        try: bpy.ops.object.modifier_apply(modifier=solid.name)
        except Exception as e:
            self.report({'WARNING'}, f"Offset applied with issues: {e}")

        boolean = prosth.modifiers.new("SP_BaseFit", 'BOOLEAN')
        boolean.operation = 'DIFFERENCE'
        boolean.solver = 'FAST'
        boolean.object = cw
        try:
            bpy.ops.object.modifier_apply(modifier=boolean.name)
        except Exception:
            boolean.solver = 'EXACT'
            try:
                bpy.ops.object.modifier_apply(modifier=boolean.name)
            except Exception as e2:
                self.report({'ERROR'}, f"Boolean failed. Clean/decimate the chest wall. {e2}")
                return {'CANCELLED'}

        frame_object(prosth)
        self.report({'INFO'}, "Base fit complete.")
        return {'FINISHED'}

class SP_OT_export_stl(bpy.types.Operator):
    bl_idname = "sp.export_stl"
    bl_label = "Step 5: Export Prosthetic STL"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        if not context.selected_objects:
            self.report({'ERROR'}, "Select prosthetic object to export.")
            return {'CANCELLED'}
        obj = context.selected_objects[0]
        path = self.filepath or bpy.path.abspath(f"//{obj.name}.stl")

        # Try Blender's exporter; if missing, fallback
        try:
            op = getattr(bpy.ops.export_mesh, "stl")
            op(filepath=path, use_selection=True, ascii=False)
            self.report({'INFO'}, f"Exported to: {path}")
            return {'FINISHED'}
        except Exception:
            try:
                write_binary_stl_from_object(obj, path)
                self.report({'INFO'}, f"Exported (fallback) to: {path}")
                return {'FINISHED'}
            except Exception as e:
                self.report({'ERROR'}, f"Export failed: {e}")
                return {'CANCELLED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class SP_OT_generate_mold(bpy.types.Operator):
    """Generate a mold STL by subtracting the prosthetic from a padded block"""
    bl_idname = "sp.generate_mold"
    bl_label = "Step 6: Generate Mold STL"
    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        props = context.scene.sisters_props
        sel = context.selected_objects
        if not sel or sel[0].type != 'MESH':
            self.report({'ERROR'}, "Select prosthetic object to make mold.")
            return {'CANCELLED'}
        prosth = sel[0]

        pad = max(2.0, props.mold_padding_mm) / 1000.0
        ws = [prosth.matrix_world @ v.co for v in prosth.data.vertices]
        minx = min(v.x for v in ws); maxx = max(v.x for v in ws)
        miny = min(v.y for v in ws); maxy = max(v.y for v in ws)
        minz = min(v.z for v in ws); maxz = max(v.z for v in ws)

        size = (maxx - minx + 2*pad, maxy - miny + 2*pad, maxz - minz + 2*pad)
        center = ((maxx + minx)/2, (maxy + miny)/2, (maxz + minz)/2)

        bpy.ops.mesh.primitive_cube_add(size=1, location=center)
        mold = bpy.context.active_object
        mold.name = f"{prosth.name}_Mold"
        mold.scale = (size[0]/2, size[1]/2, size[2]/2)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        boolean = mold.modifiers.new("SP_MoldCut", 'BOOLEAN')
        boolean.operation = 'DIFFERENCE'
        boolean.solver = 'EXACT'
        boolean.object = prosth
        bpy.context.view_layer.objects.active = mold
        try:
            bpy.ops.object.modifier_apply(modifier=boolean.name)
        except Exception as e:
            self.report({'ERROR'}, f"Mold generation failed: {e}")
            return {'CANCELLED'}

        out_path = self.filepath or bpy.path.abspath(f"//{prosth.name}_mold.stl")
        bpy.ops.object.select_all(action='DESELECT')
        mold.select_set(True); bpy.context.view_layer.objects.active = mold

        try:
            op = getattr(bpy.ops.export_mesh, "stl")
            op(filepath=out_path, use_selection=True, ascii=False)
            self.report({'INFO'}, f"Mold exported to: {out_path}")
        except Exception:
            try:
                write_binary_stl_from_object(mold, out_path)
                self.report({'INFO'}, f"Mold exported (fallback) to: {out_path}")
            except Exception as e:
                self.report({'ERROR'}, f"Mold export failed: {e}")
                return {'CANCELLED'}

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

# --------------------------- UI Panel ---------------------------

class SP_PT_panel(bpy.types.Panel):
    bl_label = "Sisters Prosthetics Designer"
    bl_idname = "SP_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Sisters'

    def draw(self, context):
        props = context.scene.sisters_props
        col = self.layout.column(align=True)

        col.operator("sp.build_demo", icon='MESH_CUBE')
        col.separator()

        col.operator("sp.import_stl", icon='IMPORT')
        col.operator("sp.clean_origin", icon='MOD_TRIANGULATE')
        col.separator()

        col.operator("sp.snap_midline", icon='EMPTY_AXIS')
        col.operator("sp.mirror_selected", icon='MOD_MIRROR')
        col.separator()

        col.prop(props, "chestwall_name", text="Chest Wall")
        col.prop(props, "base_offset_mm")
        col.operator("sp.fit_base", icon='MOD_BOOLEAN')
        col.separator()

        col.operator("sp.export_stl", icon='EXPORT')
        col.prop(props, "mold_padding_mm")
        col.operator("sp.generate_mold", icon='CUBE')

# --------------------------- Register ---------------------------

classes = [
    SistersProps,
    SP_OT_build_demo,
    SP_OT_import_stl,
    SP_OT_clean_origin,
    SP_OT_snap_midline,
    SP_OT_mirror_selected,
    SP_OT_fit_base,
    SP_OT_export_stl,
    SP_OT_generate_mold,
    SP_PT_panel
]

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.sisters_props = bpy.props.PointerProperty(type=SistersProps)

def unregister():
    del bpy.types.Scene.sisters_props
    for c in reversed(classes):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    register()

bl_info = {
    "name": "Vitaius – Vestra Designer",
    "author": "Vitaius",
    "version": (1, 8, 0),
    "blender": (3, 6, 0),
    "location": "N-Panel > Vitaius",
    "description": "Mirror & base-fitting tools for Vestra Forms custom prosthetics",
    "category": "3D View",
}

class VESTRA_PT_panel(bpy.types.Panel):
    bl_label = "Vitaius – Vestra Designer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Vitaius"   # sidebar tab name
