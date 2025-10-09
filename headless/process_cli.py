# headless/process_cli.py
import json, sys, os, bpy
from mathutils import Matrix, Vector

def import_mesh(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".stl":
        bpy.ops.import_mesh.stl(filepath=path)
    elif ext == ".obj":
        bpy.ops.import_scene.obj(filepath=path)
    elif ext == ".ply":
        bpy.ops.import_mesh.ply(filepath=path)
    else:
        raise RuntimeError(f"Unsupported mesh: {ext}")
    return bpy.context.selected_objects[0]

def ensure_midline():
    m = bpy.data.objects.get("Midline")
    if not m:
        bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0,0,0))
        m = bpy.context.active_object; m.name = "Midline"
    return m

def reflect_obj_x(obj, xplane):
    T1 = Matrix.Translation(Vector((-xplane,0,0)))
    SX = Matrix.Scale(-1.0, 4, Vector((1,0,0)))
    T2 = Matrix.Translation(Vector(( xplane,0,0)))
    obj.matrix_world = T2 @ SX @ T1 @ obj.matrix_world
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

def bbox_x(obj):
    xs = [(obj.matrix_world @ Vector(c)).x for c in obj.bound_box]
    return min(xs), max(xs), 0.5*(min(xs)+max(xs))

def make_mold_from(obj, outpath, padding_m=0.01):
    ws = [obj.matrix_world @ v.co for v in obj.data.vertices]
    minx,maxx = min(v.x for v in ws), max(v.x for v in ws)
    miny,maxy = min(v.y for v in ws), max(v.y for v in ws)
    minz,maxz = min(v.z for v in ws), max(v.z for v in ws)
    size = (maxx-minx+2*padding_m, maxy-miny+2*padding_m, maxz-minz+2*padding_m)
    center = ((minx+maxx)/2, (miny+maxy)/2, (minz+maxz)/2)
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    mold = bpy.context.active_object; mold.name = f"{obj.name}_Mold"
    mold.scale = (size[0]/2, size[1]/2, size[2]/2)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    boolmod = mold.modifiers.new("Cut", 'BOOLEAN')
    boolmod.operation = 'DIFFERENCE'; boolmod.solver = 'EXACT'; boolmod.object = obj
    bpy.context.view_layer.objects.active = mold
    bpy.ops.object.modifier_apply(modifier=boolmod.name)
    bpy.ops.object.select_all(action='DESELECT'); mold.select_set(True)
    try:
        bpy.ops.export_mesh.stl(filepath=outpath, use_selection=True, ascii=False)
    except Exception as e:
        # fallback quick STL writer if export add-on disabled
        import bmesh, struct
        deps = bpy.context.evaluated_depsgraph_get()
        me = mold.evaluated_get(deps).to_mesh()
        bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.triangulate(bm, faces=bm.faces[:])
        M = mold.matrix_world; N = M.to_3x3().inverted().transposed()
        with open(outpath,"wb") as f:
            f.write(b"Sisters Prosthetics STL".ljust(80,b" ")); f.write(struct.pack("<I", len(bm.faces)))
            for face in bm.faces:
                n = (N @ face.normal).normalized(); vs = [M @ v.co for v in face.verts]
                v1,v2,v3 = vs[0],vs[1],vs[2]
                f.write(struct.pack("<12f", n.x,n.y,n.z, v1.x,v1.y,v1.z, v2.x,v2.y,v2.z, v3.x,v3.y,v3.z))
                f.write(struct.pack("<H",0))
        bm.free(); mold.evaluated_get(deps).to_mesh_clear()

def main():
    # argv: blender -b -P process_cli.py -- <case_dir> <out_prosthetic> <out_mold>
    argv = sys.argv; sep = argv.index('--'); case_dir = argv[sep+1]
    out_prosthetic = argv[sep+2]; out_mold = argv[sep+3]
    mf = json.load(open(os.path.join(case_dir, "manifest.json"), "r"))
    units = mf.get("units","mm")
    healthy = mf.get("healthy_side","left").lower()
    base = mf.get("base_fit", {"enabled": False})
    base_enabled = bool(base.get("enabled", False))
    base_offset_m = float(base.get("offset_mm", 2.0))/1000.0
    mid = mf.get("midline", {"point":[0,0,0], "normal":[1,0,0]})
    midx = float(mid["point"][0])

    bpy.context.scene.unit_settings.system='METRIC'
    bpy.context.scene.unit_settings.scale_length = 0.001 if units=="mm" else 1.0

    breast_path = os.path.join(case_dir, "mesh_breast.stl")
    chest_path  = os.path.join(case_dir, "mesh_chestwall.stl")
    breast = import_mesh(breast_path); breast.name="Breast"
    chest = None
    if os.path.exists(chest_path):
        chest = import_mesh(chest_path); chest.name="ChestWall"

    # origin + clean transforms
    for o in [breast, chest] if chest else [breast]:
        if not o: continue
        bpy.ops.object.select_all(action='DESELECT')
        o.select_set(True); bpy.context.view_layer.objects.active = o
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')

    midline = ensure_midline(); midline.location = (midx,0,0)

    # Ensure breast is on the stated healthy side
    _,_,cx = bbox_x(breast)
    is_left = cx < midx
    if (healthy=="left") != is_left:
        reflect_obj_x(breast, midx)

    # Duplicate and reflect to opposite side
    bpy.ops.object.select_all(action='DESELECT'); breast.select_set(True)
    bpy.ops.object.duplicate(); mir = bpy.context.active_object; mir.name="Breast_Mirrored"
    breast.hide_set(True)
    reflect_obj_x(mir, midx)

    # Optional base fit to chest
    if base_enabled and chest:
        # negative solidify (comfort)
        solid = mir.modifiers.new("Comfort", 'SOLIDIFY')
        solid.thickness = -base_offset_m; solid.offset=0.0
        try: bpy.ops.object.modifier_apply(modifier=solid.name)
        except: pass
        # boolean fit
        boolm = mir.modifiers.new("Fit", 'BOOLEAN')
        boolm.operation='DIFFERENCE'; boolm.solver='FAST'; boolm.object=chest
        try: bpy.ops.object.modifier_apply(modifier=boolm.name)
        except:
            boolm.solver='EXACT'; bpy.ops.object.modifier_apply(modifier=boolm.name)

    # Export prosthetic
    bpy.ops.object.select_all(action='DESELECT'); mir.select_set(True)
    try:
        bpy.ops.export_mesh.stl(filepath=out_prosthetic, use_selection=True, ascii=False)
    except Exception:
        # fallback writer
        import bmesh, struct
        deps = bpy.context.evaluated_depsgraph_get()
        me = mir.evaluated_get(deps).to_mesh()
        bm = bmesh.new(); bm.from_mesh(me); bmesh.ops.triangulate(bm, faces=bm.faces[:])
        M = mir.matrix_world; N = M.to_3x3().inverted().transposed()
        with open(out_prosthetic,"wb") as f:
            f.write(b"Sisters Prosthetics STL".ljust(80,b" ")); f.write(struct.pack("<I", len(bm.faces)))
            for face in bm.faces:
                n=(N@face.normal).normalized(); vs=[M@v.co for v in face.verts]
                v1,v2,v3=vs[0],vs[1],vs[2]
                f.write(struct.pack("<12f", n.x,n.y,n.z, v1.x,v1.y,v1.z, v2.x,v2.y,v2.z, v3.x,v3.y,v3.z))
                f.write(struct.pack("<H",0))
        bm.free(); mir.evaluated_get(deps).to_mesh_clear()

    # Export mold
    make_mold_from(mir, out_mold, padding_m=0.01)  # 10 mm padding

if __name__ == "__main__":
    main()
