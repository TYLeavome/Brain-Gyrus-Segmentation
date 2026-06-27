import os
import sys
import argparse
import bpy
import struct
from pathlib import Path

_BAKE_PROGRESS_STATE = {
    "enabled": False,
    "last_frame": None,
}

def parse_blender_cli_args():

    '''
    Parse script args passed after `--` in Blender CLI.

    Example:
    /Applications/Blender.app/Contents/MacOS/Blender --background --python script.py -- --brain_ply_path=/path/to/wmparc_all.ply
    '''

    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--brain_ply_path",
        required=True,
        help="Path to wmparc_all.ply. The dilated ply will be inferred as *_dilated_all.ply in the same directory.",
    )
    parser.add_argument(
        "--end_frame",
        type=int,
        default=150,
        help="Frame to stop rendering/baking. Default: 150",
    )

    args, _ = parser.parse_known_args(argv)
    return args

def _bake_progress_frame_change_post(scene):

    '''
    Print one line per frame while Blender advances frames during ptcache baking.

    Notes:
    - ptcache baking advances scene frames internally; this handler observes
      `scene.frame_current` changes and logs them.
    - Works in background mode as well.
    '''

    if not _BAKE_PROGRESS_STATE.get("enabled", False):
        return

    f = int(scene.frame_current)
    last = _BAKE_PROGRESS_STATE.get("last_frame", None)
    if last != f:
        _BAKE_PROGRESS_STATE["last_frame"] = f
        print(f"[Bake] frame {f}", flush=True)

def enable_bake_progress_logging():

    '''Enable per-frame bake progress logs.'''

    _BAKE_PROGRESS_STATE["enabled"] = True
    _BAKE_PROGRESS_STATE["last_frame"] = None

    h = bpy.app.handlers.frame_change_post
    if _bake_progress_frame_change_post not in h:
        h.append(_bake_progress_frame_change_post)

def disable_bake_progress_logging():

    '''Disable per-frame bake progress logs and remove handler.'''

    _BAKE_PROGRESS_STATE["enabled"] = False
    _BAKE_PROGRESS_STATE["last_frame"] = None

    h = bpy.app.handlers.frame_change_post
    while _bake_progress_frame_change_post in h:
        h.remove(_bake_progress_frame_change_post)

def import_ply_and_show(ply_path: str, clear_scene: bool = False, frame_to_view: bool = True):
    
    '''
    Import a .ply into Blender and make it visible in viewport.
    Compatible with Blender 3.x / 4.x / 5.x.
    '''

    p = Path(ply_path).expanduser()
    if not p.is_file() or p.suffix.lower() != ".ply":
        raise FileNotFoundError(f"PLY not found: {p}")

    if clear_scene:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

        for m in list(bpy.data.meshes):
            if m.users == 0:
                bpy.data.meshes.remove(m)

        for mat in list(bpy.data.materials):
            if mat.users == 0:
                bpy.data.materials.remove(mat)

        for l in list(bpy.data.lights):
            if l.users == 0:
                bpy.data.lights.remove(l)

        for c in list(bpy.data.cameras):
            if c.users == 0:
                bpy.data.cameras.remove(c)

    before = set(bpy.data.objects)

    did_import = False
    err_msgs = []

    '''Blender 4.x/5.x'''
    if hasattr(bpy.ops, "wm") and hasattr(bpy.ops.wm, "ply_import"):
        try:
            bpy.ops.wm.ply_import(filepath=str(p))
            did_import = True
        except Exception as e:
            err_msgs.append(f"wm.ply_import failed: {e}")

    '''Older Blender'''
    if (not did_import) and hasattr(bpy.ops, "import_mesh") and hasattr(bpy.ops.import_mesh, "ply"):
        try:
            bpy.ops.import_mesh.ply(filepath=str(p))
            did_import = True
        except Exception as e:
            err_msgs.append(f"import_mesh.ply failed: {e}")

    if not did_import:
        raise RuntimeError("PLY import operator not available or failed. " + " | ".join(err_msgs))

    after = set(bpy.data.objects)
    new_objs = [o for o in (after - before) if o.type == "MESH"]

    if not new_objs:
        raise RuntimeError("Import succeeded but no mesh object was created.")

    for o in new_objs:
        o.select_set(True)
        bpy.context.view_layer.objects.active = o

    if frame_to_view:
        try:
            bpy.ops.view3d.view_selected()
        except Exception:
            pass

    return new_objs

def add_smooth_modifier(
    obj: bpy.types.Object,
    name: str = "Smooth",
    iterations: int = 10,
    factor: float = 0.5,
    use_x: bool = True,
    use_y: bool = True,
    use_z: bool = True,
    vertex_group: str = "",
    invert_vertex_group: bool = False,
    shade_smooth: bool = True,
    move_to_top: bool = True,
    apply: bool = False,
):
    
    '''
    Add/configure a Smooth modifier for an already-imported mesh object.

    Parameters:
    - obj: target Blender object (must be type 'MESH')
    - name: modifier name (created if not exists, otherwise reused)
    - iterations: Smooth iterations
    - factor: Smooth factor (strength)
    - use_x/use_y/use_z: axis toggles
    - vertex_group: optional vertex group name to limit smoothing
    - invert_vertex_group: invert the vertex group mask
    - shade_smooth: set object shading to smooth (viewport shading, not geometry)
    - move_to_top: move modifier to top of modifier stack
    - apply: apply modifier (bake into mesh)

    Returns:
    - mod: the created or updated modifier
    '''

    if obj is None:
        raise ValueError("obj is None")

    if obj.type != "MESH":
        raise TypeError(f"Object must be a MESH, got: {obj.type}")

    '''Ensure the object is active/selected if we need ops-based actions'''
    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    prev_selected = [o for o in view_layer.objects if o.select_get()]

    obj.select_set(True)
    view_layer.objects.active = obj

    try:
        if shade_smooth:
            try:
                bpy.ops.object.shade_smooth()
            except Exception:
                pass

        mod = obj.modifiers.get(name)
        if mod is None:
            mod = obj.modifiers.new(name=name, type="SMOOTH")

        mod.iterations = int(iterations)
        mod.factor = float(factor)
        mod.use_x = bool(use_x)
        mod.use_y = bool(use_y)
        mod.use_z = bool(use_z)

        if vertex_group:
            if vertex_group in obj.vertex_groups:
                mod.vertex_group = vertex_group
                mod.invert_vertex_group = bool(invert_vertex_group)
            else:
                '''If group not found, keep empty to avoid silent mismatch'''
                mod.vertex_group = ""

        if move_to_top:
            '''Move modifier to top of stack'''
            try:
                while obj.modifiers[0] != mod:
                    bpy.ops.object.modifier_move_up(modifier=mod.name)
            except Exception:
                pass

        if apply:
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except Exception:
                pass

        return mod

    finally:
        '''Restore previous selection/active state'''
        for o in view_layer.objects:
            o.select_set(False)
        for o in prev_selected:
            if o.name in bpy.data.objects:
                bpy.data.objects[o.name].select_set(True)
        view_layer.objects.active = prev_active
        
def add_tight_bounding_sphere_for_object(
    obj: bpy.types.Object,
    sphere_name: str = "TightBoundingSphere",
    segments: int = 64,
    ring_count: int = 32,
    show_wire: bool = False,
    use_world_coords: bool = True,
    apply_scale: bool = True,
):
    
    '''
    Add a tighter bounding sphere based on evaluated mesh vertices (after modifiers),
    using Ritter's algorithm (approximate minimal enclosing sphere).

    Parameters:
    - obj: target mesh object
    - sphere_name: created sphere object name
    - segments/ring_count: UV sphere resolution
    - show_wire: display sphere as wire in viewport
    - use_world_coords: compute in world space (recommended)
    - apply_scale: include object scale in world transform (recommended)

    Returns:
    - sphere_obj, center(Vector), radius(float)
    '''

    if obj is None or obj.type != "MESH":
        raise TypeError("obj must be a mesh object")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)

    eval_mesh = eval_obj.to_mesh()
    try:
        if len(eval_mesh.vertices) == 0:
            raise RuntimeError("Evaluated mesh has no vertices")

        mw = eval_obj.matrix_world.copy()

        '''Collect points'''
        pts = []
        if use_world_coords:
            for v in eval_mesh.vertices:
                pts.append(mw @ v.co)
        else:
            for v in eval_mesh.vertices:
                pts.append(v.co.copy())

        '''Ritter's algorithm: pick a point, find farthest A, from A find farthest B'''
        p0 = pts[0]

        a = max(pts, key=lambda p: (p - p0).length_squared)
        b = max(pts, key=lambda p: (p - a).length_squared)

        center = (a + b) * 0.5
        radius = (b - center).length

        '''Expand sphere to include all points'''
        r2 = radius * radius
        for p in pts:
            d = p - center
            dist2 = d.length_squared
            if dist2 > r2:
                dist = dist2 ** 0.5
                '''Move center towards p and increase radius just enough'''
                new_radius = (radius + dist) * 0.5
                k = (new_radius - radius) / dist
                center = center + d * k
                radius = new_radius
                r2 = radius * radius

        '''Create UV sphere'''
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=int(segments),
            ring_count=int(ring_count),
            radius=float(radius),
            location=(center.x, center.y, center.z),
        )
        sphere_obj = bpy.context.active_object
        sphere_obj.name = sphere_name

        if show_wire: sphere_obj.display_type = "WIRE"
        else: sphere_obj.display_type = "TEXTURED"

        return sphere_obj, center, radius

    finally:
        '''Free evaluated mesh'''
        eval_obj.to_mesh_clear()
        
def setup_brain_as_static_collider(
    brain_obj: bpy.types.Object,
    collision_thickness_outer: float = 0.002,
    collision_thickness_inner: float = 0.002,
    damping: float = 0.0,
    friction: float = 5.0,
    use_rigidbody_passive: bool = False,
):
    
    '''
    Set brain_obj as a static collider:
    - Adds Collision physics (for cloth collision)
    - Optionally adds Passive Rigid Body (keeps it fixed/stable in physics world)
    '''

    if brain_obj is None or brain_obj.type != "MESH":
        raise TypeError("brain_obj must be a mesh object")

    '''Add collision physics settings'''
    if brain_obj.collision is None:
        bpy.ops.object.select_all(action='DESELECT')
        brain_obj.select_set(True)
        bpy.context.view_layer.objects.active = brain_obj
        bpy.ops.object.modifier_add(type='COLLISION')

    col = brain_obj.collision
    col.thickness_outer = float(collision_thickness_outer)
    col.thickness_inner = float(collision_thickness_inner)
    col.damping = float(damping)
    if hasattr(col, "cloth_friction"):
        col.cloth_friction = 0.0
#    if hasattr(col, "cloth_friction"):
#        col.cloth_friction = float(friction)
#    elif hasattr(col, "friction_factor"):
#        col.friction_factor = max(0.0, min(1.0, float(friction)))

    '''Optional: add Passive Rigid Body.
    Note: Cloth collision does NOT require rigid bodies.
    If enabled, we must ensure the mesh has vertices, otherwise Blender prints:
    "no vertices to define Convex Hull collision shape with".
    '''
    if use_rigidbody_passive:
        if brain_obj.data is None or len(brain_obj.data.vertices) == 0:
            print(f"WARNING: {brain_obj.name} has 0 vertices; skipping rigid body setup.")
            return brain_obj

        bpy.ops.object.select_all(action='DESELECT')
        brain_obj.select_set(True)
        bpy.context.view_layer.objects.active = brain_obj

        if brain_obj.rigid_body is None:
            bpy.ops.rigidbody.object_add()

        rb = brain_obj.rigid_body
        rb.type = 'PASSIVE'
        rb.kinematic = True
        rb.enabled = True

        '''Use MESH collision to avoid convex hull creation issues on unusual meshes.'''
        if hasattr(rb, "collision_shape"):
            rb.collision_shape = 'MESH'

        '''Prefer evaluated/deformed mesh if Blender exposes mesh_source (2.8+).'''
        if hasattr(rb, "mesh_source"):
            try:
                rb.mesh_source = 'DEFORM'
            except Exception:
                pass

    return brain_obj

def setup_membrane_as_shrinking_cloth(
    sphere_obj: bpy.types.Object,
    quality_steps: int = 12,
    time_scale: float = 2.0,
    vertex_mass: float = 15.0,
    air_viscosity: float = 2.0,
    bending_model: str = "ANGULAR",
    tension: float = 0.5,
    compression: float = 0.5,
    shear: float = 0.5,
    bending: float = 0.05,
    tension_damping: float = 50.0,
    compression_damping: float = 50.0,
    shear_damping: float = 50.0,
    bending_damping: float = 10.0,
    use_internal_springs: bool = False,
    internal_max_spring_length: float = 0.0,
    internal_max_diversion_deg: float = 45.0,
    internal_tension: float = 15.0,
    internal_compression: float = 15.0,
    internal_max_tension: float = 15.0,
    internal_max_compression: float = 15.0,
    internal_check_surface_normals: bool = True,
    use_pressure: bool = True,
    pressure: float = -10.0,
    pressure_scale: float = 1.0,
    target_volume: float = 0.0,
    fluid_density: float = 0.0,
    use_custom_volume: bool = False,
    use_shrink: bool = True,
    shrinking_factor: float = 0.4,
    use_dynamic_mesh: bool = True,  # <<< change default to True
    pin_stiffness: float = 1.0,
    collision_quality: int = 16,
    collision_distance: float = 0.001,
    collision_impulse_clamp: float = 0.2,
    enable_self_collision: bool = True,
    self_collision_distance: float = 0.001,
    self_collision_friction: float = 5.0,
    self_collision_impulse_clamp: float = 0.2,
    effector_collection_name: str = "Collection",
    collision_collection_name: str = "Collection",
    gravity_weight: float = 0.0,
    cache_start: int = 1,
    cache_end: int = 150,
    shade_smooth: bool = True,
    prop_max_tension: float = 1.0,
    prop_max_compression: float = 1.0,
    prop_max_shearing: float = 1.0,
    prop_max_bending: float = 0.4,
    prop_max_shrinking: float = 0.4,
):
    
    '''
    Match the screenshots.

    Critical fix per your screenshot:
    - The UI "Shrinking Factor" is actually driven by:
        bpy.context.object.modifiers["Cloth"].settings.shrink_min = 0.4
      So we set shrink_min directly (and verify it).
    - Cache End = 50.
    '''

    if sphere_obj is None or sphere_obj.type != "MESH":
        raise TypeError("sphere_obj must be a mesh object")

    '''Make sphere_obj active (so bpy.context.object matches your console usage)'''
    bpy.ops.object.select_all(action="DESELECT")
    sphere_obj.select_set(True)
    bpy.context.view_layer.objects.active = sphere_obj

    '''Get or add cloth modifier'''
    cloth_mod = None
    for m in sphere_obj.modifiers:
        if m.type == "CLOTH":
            cloth_mod = m
            break

    if cloth_mod is None:
        bpy.ops.object.modifier_add(type="CLOTH")
        for m in sphere_obj.modifiers:
            if m.type == "CLOTH":
                cloth_mod = m
                break

    if cloth_mod is None:
        raise RuntimeError("Failed to create/find CLOTH modifier")

    settings = cloth_mod.settings

    '''Cloth main'''
    if hasattr(settings, "quality"):
        settings.quality = int(quality_steps)
    if hasattr(settings, "time_scale"):
        settings.time_scale = float(time_scale)

    '''Physical Properties'''
    if hasattr(settings, "mass"):
        settings.mass = float(vertex_mass)
    if hasattr(settings, "air_damping"):
        settings.air_damping = float(air_viscosity)

    '''Bending Model'''
    if hasattr(settings, "bending_model"):
        try:
            settings.bending_model = str(bending_model).upper()
        except Exception:
            pass

    '''Stiffness'''
    if hasattr(settings, "tension_stiffness"):
        settings.tension_stiffness = float(tension)
    if hasattr(settings, "compression_stiffness"):
        settings.compression_stiffness = float(compression)
    if hasattr(settings, "shear_stiffness"):
        settings.shear_stiffness = float(shear)
    if hasattr(settings, "bending_stiffness"):
        settings.bending_stiffness = float(bending)

    '''Damping'''
    if hasattr(settings, "tension_damping"):
        settings.tension_damping = float(tension_damping)
    if hasattr(settings, "compression_damping"):
        settings.compression_damping = float(compression_damping)
    if hasattr(settings, "shear_damping"):
        settings.shear_damping = float(shear_damping)
    if hasattr(settings, "bending_damping"):
        settings.bending_damping = float(bending_damping)

    '''Internal Springs'''
    if hasattr(settings, "use_internal_springs"):
        settings.use_internal_springs = bool(use_internal_springs)

    if use_internal_springs:
        if hasattr(settings, "internal_spring_max_length"):
            settings.internal_spring_max_length = float(internal_max_spring_length)
        elif hasattr(settings, "internal_spring_max_len"):
            settings.internal_spring_max_len = float(internal_max_spring_length)

        if hasattr(settings, "internal_spring_max_diversion"):
            settings.internal_spring_max_diversion = float(internal_max_diversion_deg)

        if hasattr(settings, "internal_tension_stiffness"):
            settings.internal_tension_stiffness = float(internal_tension)
        if hasattr(settings, "internal_compression_stiffness"):
            settings.internal_compression_stiffness = float(internal_compression)

        if hasattr(settings, "internal_tension_stiffness_max"):
            settings.internal_tension_stiffness_max = float(internal_max_tension)
        if hasattr(settings, "internal_compression_stiffness_max"):
            settings.internal_compression_stiffness_max = float(internal_max_compression)

        if hasattr(settings, "internal_spring_normal_check"):
            settings.internal_spring_normal_check = bool(internal_check_surface_normals)
        elif hasattr(settings, "internal_spring_check_surface_normals"):
            settings.internal_spring_check_surface_normals = bool(internal_check_surface_normals)

    '''Property Weights (match screenshot).'''
    if hasattr(settings, "vertex_group_structural_stiffness"):
        settings.vertex_group_structural_stiffness = ""
    if hasattr(settings, "vertex_group_shear_stiffness"):
        settings.vertex_group_shear_stiffness = ""
    if hasattr(settings, "vertex_group_bending"):
        settings.vertex_group_bending = ""
    if hasattr(settings, "vertex_group_shrink"):
        settings.vertex_group_shrink = ""
    if hasattr(settings, "tension_stiffness_max"):
        settings.tension_stiffness_max = float(prop_max_tension)
    if hasattr(settings, "compression_stiffness_max"):
        settings.compression_stiffness_max = float(prop_max_compression)
    if hasattr(settings, "shear_stiffness_max"):
        settings.shear_stiffness_max = float(prop_max_shearing)
    if hasattr(settings, "bending_stiffness_max"):
        settings.bending_stiffness_max = float(prop_max_bending)
    if hasattr(settings, "shrink_max") and (hasattr(settings, "vertex_group_shrink") or hasattr(settings, "use_shrink")):
        settings.shrink_max = float(prop_max_shrinking)

    '''Pressure'''
    if hasattr(settings, "use_pressure"):
        settings.use_pressure = bool(use_pressure)

    if use_pressure:
        if hasattr(settings, "uniform_pressure_force"):
            settings.uniform_pressure_force = float(pressure)
        elif hasattr(settings, "pressure"):
            settings.pressure = float(pressure)

        if hasattr(settings, "pressure_scale"):
            settings.pressure_scale = float(pressure_scale)

        if hasattr(settings, "use_pressure_volume"):
            settings.use_pressure_volume = bool(use_custom_volume)
        elif hasattr(settings, "use_custom_volume"):
            settings.use_custom_volume = bool(use_custom_volume)

        if hasattr(settings, "target_volume"):
            settings.target_volume = float(target_volume)

        if hasattr(settings, "fluid_density"):
            settings.fluid_density = float(fluid_density)

    '''Shape: Pin stiffness (Pin Group empty in screenshot)'''
    if hasattr(settings, "pin_stiffness"):
        settings.pin_stiffness = float(pin_stiffness)
    if hasattr(settings, "pin_group"):
        settings.pin_group = ""

    '''Sewing (0.0)'''
    if hasattr(settings, "use_sewing_springs"):
        settings.use_sewing_springs = False
    if hasattr(settings, "sewing_force_max"):
        settings.sewing_force_max = 0.0
    elif hasattr(settings, "sewing_force"):
        settings.sewing_force = 0.0

    '''Shrink'''
    if hasattr(settings, "use_shrink"):
        settings.use_shrink = bool(use_shrink)

    if use_shrink:
        sf = float(shrinking_factor)

        if hasattr(settings, "shrink_min"):
            settings.shrink_min = sf
        else:
            raise RuntimeError("This Blender build does not expose ClothSettings.shrink_min, cannot drive UI Shrinking Factor as in your screenshot.")

        '''Dynamic Mesh toggle (default ON now)'''
        if hasattr(settings, "use_dynamic_mesh"):
            settings.use_dynamic_mesh = bool(use_dynamic_mesh)

        try:
            if abs(float(settings.shrink_min) - sf) > 1e-6:
                raise RuntimeError(f"Failed to set shrink_min to {sf}. Current value is {settings.shrink_min}.")
        except Exception as e:
            raise RuntimeError(f"Shrink verification failed: {e}")

    '''Collision settings'''
    cset = cloth_mod.collision_settings

    if hasattr(cset, "collision_quality"):
        cset.collision_quality = int(collision_quality)

    '''Object collisions'''
    if hasattr(cset, "use_collision"):
        cset.use_collision = True
    if hasattr(cset, "distance_min"):
        cset.distance_min = float(collision_distance)
    if hasattr(cset, "impulse_clamp"):
        cset.impulse_clamp = float(collision_impulse_clamp)

    if hasattr(cset, "collision_collection"):
        col = bpy.data.collections.get(collision_collection_name)
        if col is not None:
            cset.collision_collection = col

    if hasattr(cset, "vertex_group"):
        cset.vertex_group = ""

    '''Self collisions'''
    if hasattr(cset, "use_self_collision"):
        cset.use_self_collision = bool(enable_self_collision)

    if enable_self_collision:
        if hasattr(cset, "self_distance_min"):
            cset.self_distance_min = float(self_collision_distance)
        if hasattr(cset, "self_friction"):
            cset.self_friction = float(self_collision_friction)
        if hasattr(cset, "self_impulse_clamp"):
            cset.self_impulse_clamp = float(self_collision_impulse_clamp)
        if hasattr(cset, "self_vertex_group"):
            cset.self_vertex_group = ""

    '''Field Weights'''
    if hasattr(settings, "effector_weights") and settings.effector_weights is not None:
        ew = settings.effector_weights

        ewc = bpy.data.collections.get(effector_collection_name)
        if ewc is not None:
            if hasattr(ew, "collection"):
                ew.collection = ewc
            elif hasattr(ew, "effector_collection"):
                ew.effector_collection = ewc

        if hasattr(ew, "gravity"):
            ew.gravity = float(gravity_weight)

        for k in (
            "all", "force", "vortex", "magnetic", "harmonic", "charge", "lennardjones",
            "wind", "curve_guide", "texture", "turbulence", "drag", "boid", "smokeflow",
            "fluid_flow",
        ):
            if hasattr(ew, k):
                setattr(ew, k, 1.0)

    '''Cache'''
    if hasattr(cloth_mod, "point_cache") and cloth_mod.point_cache is not None:
        pc = cloth_mod.point_cache
        if hasattr(pc, "frame_start"):
            pc.frame_start = int(cache_start)
        if hasattr(pc, "frame_end"):
            pc.frame_end = int(cache_end)

    '''Smooth shading'''
    if shade_smooth:
        try:
            bpy.ops.object.shade_smooth()
        except Exception:
            pass

    return cloth_mod

def add_subdivision_modifier(
    obj: bpy.types.Object,
    name: str = "Subsurf",
    levels_viewport: int = 2,
    levels_render: int = 2,
    subdivision_type: str = "CATMULL_CLARK",
    place_before_modifier: str = "Cloth",
):
    
    '''
    Add Subdivision Surface modifier to an existing mesh object, and optionally place it before Cloth.

    Parameters:
    - obj: mesh object
    - levels_viewport/levels_render: subdivision levels
    - subdivision_type: 'CATMULL_CLARK' or 'SIMPLE'
    - place_before_modifier: if a modifier with this name/type exists, move subsurf above it

    Returns:
    - subsurf_mod
    '''

    if obj is None or obj.type != "MESH":
        raise TypeError("obj must be a mesh object")

    mod = obj.modifiers.get(name)
    if mod is None:
        mod = obj.modifiers.new(name=name, type="SUBSURF")

    mod.levels = int(levels_viewport)
    mod.render_levels = int(levels_render)
    mod.subdivision_type = subdivision_type

    '''Try to move Subsurf above Cloth (or above a named modifier)'''
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    try:
        while True:
            idx = list(obj.modifiers).index(mod)
            if idx == 0:
                break

            above = obj.modifiers[idx - 1]

            '''Stop if we are already above Cloth'''
            if above.type == "CLOTH" or above.name == place_before_modifier:
                bpy.ops.object.modifier_move_up(modifier=mod.name)
                continue

            '''If the modifier above is not cloth, still move up until we reach top or above cloth'''
            bpy.ops.object.modifier_move_up(modifier=mod.name)
    except Exception:
        pass

    return mod

def set_scene_cache_and_bake(
    frame_start: int = 1,
    frame_end: int = 150,
    bake: bool = True,
):
    
    '''
    Set scene frame range and optionally bake all physics.

    Important:
    - bpy.ops.ptcache.bake_all() bakes per-simulation point_cache range,
      not necessarily scene.frame_end.
    - So we optionally force every point_cache.frame_start/frame_end to match.
    '''

    scene = bpy.context.scene
    scene.frame_start = int(frame_start)
    scene.frame_end = int(frame_end)

    if bake:
        '''In background mode, Blender already prints ptcache progress.'''
        if not bpy.app.background:
            enable_bake_progress_logging()
        try:
            bpy.ops.ptcache.free_bake_all()
            bpy.ops.ptcache.bake_all(bake=True)
        finally:
            if not bpy.app.background:
                disable_bake_progress_logging()

    return scene

def scale_object(
    obj: bpy.types.Object,
    scale_factor: float = 0.5,
    apply_scale: bool = True,
):
    
    '''
    Scale object uniformly by scale_factor.

    Parameters:
    - obj: Blender object
    - scale_factor: uniform scaling factor
    - apply_scale: if True, apply scale so physics uses baked geometry

    Returns:
    - obj
    '''

    if obj is None:
        raise ValueError("Object is None")

    if scale_factor <= 0:
        raise ValueError("scale_factor must be > 0")

    '''Uniform scale'''
    obj.scale = (
        obj.scale[0] * scale_factor,
        obj.scale[1] * scale_factor,
        obj.scale[2] * scale_factor,
    )

    if apply_scale:
        '''Apply scale so collision/cloth uses real mesh size'''
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(scale=True)

    return obj

def apply_all_modifiers(obj: bpy.types.Object):

    '''
    Apply all modifiers on obj in current stack order.

    Notes:
    - Uses bpy.ops.object.modifier_apply, so obj must be active/selected.
    - This will convert procedural modifiers (Solidify/Boolean/etc.) into real mesh geometry.
    '''

    if obj is None or obj.type != "MESH":
        raise TypeError("obj must be a mesh object")

    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    prev_selected = [o for o in view_layer.objects if o.select_get()]

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    view_layer.objects.active = obj

    try:
        for m in list(obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=m.name)
            except Exception as e:
                print(f"WARNING: Failed to apply modifier '{m.name}' on '{obj.name}': {e}")
        return obj
    finally:
        bpy.ops.object.select_all(action="DESELECT")
        for o in prev_selected:
            if o.name in bpy.data.objects:
                bpy.data.objects[o.name].select_set(True)
        view_layer.objects.active = prev_active

def add_remesh_smooth_modifier(
    obj: bpy.types.Object,
    name: str = "Remesh",
    mode: str = "SMOOTH",
    octree_depth: int = 6,
    scale: float = 0.9,
    sharpness: float = 1.0,
    threshold: float = 1.0,
    remove_disconnected: bool = True,
    remesh_smooth_shading: bool = True,
    shade_smooth_object: bool = False,
    apply: bool = False,
    move_to_top: bool = True,
):
    
    '''
    Add/configure a Remesh modifier similar to your screenshot.

    Defaults:
    - Mode: SMOOTH
    - Remove Disconnected: On
    - Smooth Shading (inside Remesh): On

    mode can be one of: "SMOOTH", "SHARP", "BLOCKS", "VOXEL"
    '''
    
    if obj is None or obj.type != "MESH":
        raise TypeError("obj must be a mesh object")

    '''Normalize and validate mode'''
    mode_norm = str(mode).strip().upper()
    valid_modes = {"SMOOTH", "SHARP", "BLOCKS", "VOXEL"}
    if mode_norm not in valid_modes:
        raise ValueError(f"mode must be one of {sorted(valid_modes)}, got: {mode!r}")

    '''Ensure active/selected for ops actions'''
    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    prev_selected = [o for o in view_layer.objects if o.select_get()]

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    view_layer.objects.active = obj

    try:
        '''Optional object smooth shading (not the Remesh "Smooth Shading" checkbox)'''
        if shade_smooth_object:
            try:
                bpy.ops.object.shade_smooth()
            except Exception:
                pass

        mod = obj.modifiers.get(name)
        if mod is None:
            mod = obj.modifiers.new(name=name, type="REMESH")

        '''Remesh mode'''
        if hasattr(mod, "mode"):
            mod.mode = mode_norm

        '''Core parameters (some may be ignored depending on mode/version)'''
        if hasattr(mod, "octree_depth"):
            mod.octree_depth = int(octree_depth)

        if hasattr(mod, "scale"):
            mod.scale = float(scale)

        if hasattr(mod, "sharpness"):
            mod.sharpness = float(sharpness)

        if hasattr(mod, "threshold"):
            mod.threshold = float(threshold)

        '''Remove disconnected pieces'''
        if hasattr(mod, "use_remove_disconnected"):
            mod.use_remove_disconnected = bool(remove_disconnected)
        elif hasattr(mod, "remove_disconnected"):
            mod.remove_disconnected = bool(remove_disconnected)

        '''Remesh internal smooth shading checkbox'''
        if hasattr(mod, "use_smooth_shade"):
            mod.use_smooth_shade = bool(remesh_smooth_shading)
        elif hasattr(mod, "use_smooth_shading"):
            mod.use_smooth_shading = bool(remesh_smooth_shading)

        '''Move to top of modifier stack'''
        if move_to_top:
            try:
                while obj.modifiers and obj.modifiers[0] != mod:
                    bpy.ops.object.modifier_move_up(modifier=mod.name)
            except Exception:
                pass

        '''Apply modifier'''
        if apply:
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except Exception:
                pass

        return mod

    finally:
        '''Restore selection/active'''
        bpy.ops.object.select_all(action="DESELECT")
        for o in prev_selected:
            if o.name in bpy.data.objects:
                bpy.data.objects[o.name].select_set(True)
        view_layer.objects.active = prev_active

def export_evaluated_mesh_to_ply(
    obj_name: str,
    output_dir: str,
    filename: str = "constraint_membrane.ply",
    frame: int = 150,
):
    
    '''
    Export the evaluated (simulated) mesh at a specific frame to PLY.
    This exports the Cloth-deformed result without applying the Cloth modifier.

    Steps:
    - scene.frame_set(frame)
    - depsgraph evaluate
    - eval_obj.to_mesh()
    - write binary little-endian PLY
    '''

    scene = bpy.context.scene
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        raise ValueError(f"Object '{obj_name}' not found")
    if obj.type != "MESH":
        raise TypeError("Object must be a mesh")

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)

    '''Go to the target frame and ensure depsgraph is up to date'''
    scene.frame_set(int(frame))
    bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)

    eval_mesh = eval_obj.to_mesh()
    try:
        if eval_mesh is None or len(eval_mesh.vertices) == 0:
            raise RuntimeError("Evaluated mesh has no vertices. Cloth may not be evaluated or cache is missing.")

        '''Triangulate for PLY faces'''
        mesh_copy = eval_mesh.copy()
        mesh_copy.calc_loop_triangles()

        verts = [v.co.copy() for v in mesh_copy.vertices]
        tris = [lt.vertices for lt in mesh_copy.loop_triangles]

        '''Write binary little-endian PLY'''
        with open(filepath, "wb") as f:
            header = []
            header.append("ply")
            header.append("format binary_little_endian 1.0")
            header.append(f"element vertex {len(verts)}")
            header.append("property float x")
            header.append("property float y")
            header.append("property float z")
            header.append(f"element face {len(tris)}")
            header.append("property list uchar int vertex_indices")
            header.append("end_header")
            f.write(("\n".join(header) + "\n").encode("ascii"))

            for v in verts:
                f.write(struct.pack("<fff", float(v.x), float(v.y), float(v.z)))

            for a, b, c in tris:
                f.write(struct.pack("<Biii", 3, int(a), int(b), int(c)))

        print(f"PLY exported to: {filepath} (frame={frame})")
        return filepath

    finally:
        eval_obj.to_mesh_clear()

def duplicate_evaluated_mesh_as_object(
    src_obj_name: str,
    frame: int = 150,
    new_obj_name: str | None = None,
    link_to_same_collections: bool = True,
    make_single_user: bool = True,
):
    '''
    Duplicate the evaluated (modifier-applied) mesh of src_obj at a given frame
    as a new standalone object.

    This captures the Cloth-deformed geometry at that frame and makes it a new mesh,
    so you can do further processing without cloth/cache dependencies.
    '''

    scene = bpy.context.scene
    view_layer = bpy.context.view_layer

    src_obj = bpy.data.objects.get(src_obj_name)
    if src_obj is None:
        raise ValueError(f"Object not found: {src_obj_name}")
    if src_obj.type != "MESH":
        raise TypeError(f"Object must be MESH, got: {src_obj.type}")

    '''Go to target frame and update depsgraph'''
    scene.frame_set(int(frame))
    view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = src_obj.evaluated_get(depsgraph)

    '''Create new mesh from evaluated object (modifiers included)'''
    new_mesh = bpy.data.meshes.new_from_object(
        eval_obj,
        preserve_all_data_layers=True,
        depsgraph=depsgraph,
    )

    if make_single_user:
        '''Ensure the mesh is unique (usually already unique here)'''
        new_mesh = new_mesh.copy()

    if new_obj_name is None or not str(new_obj_name).strip():
        new_obj_name = f"{src_obj.name}_F{int(frame)}"

    new_obj = bpy.data.objects.new(new_obj_name, new_mesh)

    '''Keep world transform consistent'''
    new_obj.matrix_world = src_obj.matrix_world.copy()

    '''Link to collections'''
    if link_to_same_collections and len(src_obj.users_collection) > 0:
        for col in src_obj.users_collection:
            col.objects.link(new_obj)
    else:
        bpy.context.scene.collection.objects.link(new_obj)

    '''Make it visible and selectable'''
    new_obj.hide_set(False)
    new_obj.hide_viewport = False
    new_obj.hide_render = False

    return new_obj

DEFAULT_SCALE = 0.05
DEFAULT_EXPORT_FRAME = 150


def _add_remesh_modifier(obj: bpy.types.Object):
    mod = obj.modifiers.new(name="Remesh", type='REMESH')
    mod.mode = 'SMOOTH'
    mod.octree_depth = 7
    mod.use_smooth_shade = True
    return mod


def _add_postprocess_modifiers(ballon_static: bpy.types.Object, brain_obj: bpy.types.Object):
    solidify = ballon_static.modifiers.new(name="Solidify", type='SOLIDIFY')
    solidify.thickness = -0.07
    solidify.offset = 0
    solidify.use_rim = False

    boolean = ballon_static.modifiers.new(name="Boolean", type='BOOLEAN')
    boolean.operation = 'INTERSECT'
    boolean.solver = 'MANIFOLD'
    boolean.object = brain_obj

    subsurf = ballon_static.modifiers.new(name="Subsurf", type='SUBSURF')
    subsurf.levels = 1
    subsurf.render_levels = 2
    subsurf.show_only_control_edges = True


def _duplicate_for_export(src_obj: bpy.types.Object, new_name: str):
    new_obj = src_obj.copy()
    new_obj.data = src_obj.data.copy()
    new_obj.name = new_name

    if len(src_obj.users_collection) > 0:
        for col in src_obj.users_collection:
            col.objects.link(new_obj)
    else:
        bpy.context.scene.collection.objects.link(new_obj)

    new_obj.matrix_world = src_obj.matrix_world.copy()
    return new_obj


def run_gyrus_pipeline(
    brain_ply_path: str,
    export_frame: int = DEFAULT_EXPORT_FRAME,
    scale: float = DEFAULT_SCALE,
    output_dir: str | None = None,
    validate_brain_path: bool = False,
    cloth_cache_end: int | None = None,
    use_output_dir_fallback: bool = True,
):
    '''
    Build the gyrus mesh with the same Blender steps used by the original scripts.
    '''

    export_frame = int(export_frame)
    scale = float(scale)
    brain_ply = str(Path(brain_ply_path).expanduser())

    if validate_brain_path and (
        (not brain_ply.lower().endswith(".ply")) or (not Path(brain_ply).is_file())
    ):
        raise FileNotFoundError(f"brain_ply_path not found or not a .ply file: {brain_ply}")

    '''STEP 0: clear the scene.'''
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    '''STEP 1: import the original brain PLY.'''
    brain = import_ply_and_show(brain_ply, clear_scene=False, frame_to_view=True)

    '''STEP 2: import the dilated brain PLY as the shrinking start surface.'''
    ballon_ply = brain_ply.replace("_all.ply", "_dilated_all.ply")
    ballon = import_ply_and_show(ballon_ply, clear_scene=False, frame_to_view=True)

    '''STEP 3: rename imported mesh objects.'''
    bpy.data.objects[brain[0].name].name = "Brain"
    bpy.data.objects[ballon[0].name].name = "Ballon"
    brain_obj = brain[0]
    ballon_obj = ballon[0]

    '''STEP 4: scale down before physics simulation.'''
    scale_object(brain_obj, scale_factor=scale)
    scale_object(ballon_obj, scale_factor=scale)

    shrinkwrap = ballon_obj.modifiers.new(name="Shrinkwrap", type='SHRINKWRAP')
    shrinkwrap.target = bpy.data.objects["Brain"]
    shrinkwrap.offset = 0.1

    _add_remesh_modifier(ballon_obj)
    _add_remesh_modifier(brain_obj)

    setup_brain_as_static_collider(brain_obj)
    if cloth_cache_end is None:
        setup_membrane_as_shrinking_cloth(ballon_obj)
    else:
        setup_membrane_as_shrinking_cloth(ballon_obj, cache_end=int(cloth_cache_end))

    set_scene_cache_and_bake(frame_start=1, frame_end=export_frame, bake=True)

    duplicate_evaluated_mesh_as_object(
        src_obj_name="Ballon",
        frame=export_frame,
        new_obj_name="Ballon_static",
    )
    ballon_static = bpy.data.objects["Ballon_static"]
    _add_postprocess_modifiers(ballon_static, brain_obj)

    if output_dir is None:
        output_dir = os.path.dirname(brain_ply)
        if use_output_dir_fallback:
            output_dir = output_dir or "."

    gyrus = _duplicate_for_export(ballon_static, "gyrus")
    apply_all_modifiers(gyrus)
    scale_object(gyrus, scale_factor=int(1 / scale), apply_scale=True)

    return export_evaluated_mesh_to_ply(
        obj_name="gyrus",
        output_dir=output_dir,
        filename="gyrus.ply",
        frame=export_frame,
    )
