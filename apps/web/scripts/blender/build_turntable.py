"""Builds the landing page's turntable in Blender: a GLB for the live hero and Cycles stills.

The record is pressed from a demo meeting: the groove runs from the outer edge (00:00) to the run-out
(the last word), and every band of groove is tinted in the colour of whoever was speaking. The web hero
re-tints the grooves at runtime from the same fixtures, so this file only needs the shapes, the
materials that are not data, and the node names the hero animates (ArmPivot, ArmLift, StylusTip,
Platter, Record).

Run from apps/web:
  blender -b -P scripts/blender/build_turntable.py -- --out public/landing [--render] [--samples 256]

1 Blender unit is 100 mm, so the record is 3.048 units across.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.normpath(os.path.join(HERE, "..", ".."))
FIXTURES = os.path.join(WEB, "src", "api", "demo", "fixtures.json")

# speaker hues from tokens.css, tuned for a dark desk
SPEAKERS = ["#5B8CFF", "#2CC4A8", "#F2B53A", "#E066B3", "#9BC53D", "#F07A3C", "#9B7BFF", "#8CA0B3"]

# layout, in Blender units (100 mm)
PLINTH = (4.5, 3.5, 0.5)  # width, depth, height
SPINDLE = Vector((-0.35, 0.1))
PIVOT = Vector((1.6, 1.0))
PLATTER_R = 1.66
PLATTER_Z = (0.52, 0.70)
MAT_Z = 0.73
RECORD_R = 1.524
RECORD_TOP = 0.75
GROOVE_OUT = 1.46  # where 00:00 sits
GROOVE_IN = 0.62  # where the last word sits
LABEL_R = 0.5
ARM_Z = 0.93
ARM_LEN = 1.86
HEADSHELL_OFFSET = math.radians(22)


def args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.join(WEB, "public", "landing"))
    p.add_argument("--meta", default=os.path.join(WEB, "src", "landing", "turntable", "meta.json"))
    p.add_argument("--meeting", default="demo-pricing-review")
    p.add_argument("--render", action="store_true")
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--scale", type=int, default=100, help="render resolution percentage")
    p.add_argument("--record-only", action="store_true", help="render just the floating record")
    return p.parse_args(argv)


def hex_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    srgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)  # linear


# ---- scene -------------------------------------------------------------------------------------


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    return scene


def link(obj, parent=None):
    bpy.context.scene.collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def empty(name, loc=(0, 0, 0), parent=None):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = 0.15
    e.location = loc
    return link(e, parent)


def finish_mesh(me, sharp_deg=32):
    me.validate()
    me.update()
    for poly in me.polygons:
        poly.use_smooth = True
    try:
        me.set_sharp_from_angle(angle=math.radians(sharp_deg))
    except AttributeError:  # older API
        me.use_auto_smooth = True
        me.auto_smooth_angle = math.radians(sharp_deg)


def lathe(name, profile, segments=128, mats=None, planar_r=RECORD_R, xform=None, sharp_deg=32):
    """Revolve [(r, z), ...] about Z. Flat-ish faces get planar UVs (u, v over +/- planar_r) so a texture
    can be laid over the top like a printed disc; steep faces get cylindrical UVs for the rim.
    mats[i] is the material slot of the band between profile points i and i+1."""
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")
    rings = []
    for r, z in profile:
        if r < 1e-6:
            rings.append([bm.verts.new((0, 0, z))])
        else:
            rings.append(
                [bm.verts.new((r * math.cos(2 * math.pi * j / segments), r * math.sin(2 * math.pi * j / segments), z)) for j in range(segments)]
            )
    bm.verts.ensure_lookup_table()
    zs = [z for _, z in profile]
    zmin, zmax = min(zs), max(zs)
    for i in range(len(profile) - 1):
        (r0, z0), (r1, z1) = profile[i], profile[i + 1]
        steep = abs(z1 - z0) > abs(r1 - r0)
        a, b = rings[i], rings[i + 1]
        for j in range(segments):
            j2 = (j + 1) % segments
            if len(a) == 1 and len(b) == 1:
                continue
            if len(a) == 1:
                verts = [a[0], b[j], b[j2]]
                us = [(j + 0.5) / segments, j / segments, (j + 1) / segments]
                ps = [(0.0, z0), (r1, z1), (r1, z1)]
            elif len(b) == 1:
                verts = [a[j], b[0], a[j2]]
                us = [j / segments, (j + 0.5) / segments, (j + 1) / segments]
                ps = [(r0, z0), (0.0, z1), (r0, z0)]
            else:
                verts = [a[j], b[j], b[j2], a[j2]]
                us = [j / segments, j / segments, (j + 1) / segments, (j + 1) / segments]
                ps = [(r0, z0), (r1, z1), (r1, z1), (r0, z0)]
            try:
                f = bm.faces.new(verts)
            except ValueError:
                continue
            f.material_index = mats[i] if mats else 0
            for loop in f.loops:
                k = verts.index(loop.vert)
                if steep:
                    loop[uv].uv = (us[k], (ps[k][1] - zmin) / max(zmax - zmin, 1e-6))
                else:
                    co = loop.vert.co
                    loop[uv].uv = (0.5 + co.x / (2 * planar_r), 0.5 + co.y / (2 * planar_r))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if xform is not None:
        me.transform(xform)
    finish_mesh(me, sharp_deg)
    return me


def rounded_box(name, size, radius, segments=4, loc=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(scale=True)
    mod = obj.modifiers.new("bevel", "BEVEL")
    mod.width = radius
    mod.segments = segments
    mod.limit_method = "NONE"
    bpy.ops.object.modifier_apply(modifier=mod.name)
    finish_mesh(obj.data, 40)
    return obj


def mesh_obj(name, me, parent=None, loc=(0, 0, 0)):
    obj = bpy.data.objects.new(name, me)
    obj.location = loc
    return link(obj, parent)


def mat(name, base="#000000", metallic=0.0, roughness=0.5, emission=None, strength=0.0, coat=0.0, aniso=0.0):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except AttributeError:
        pass
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*hex_rgb(base), 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if coat:
        bsdf.inputs["Coat Weight"].default_value = coat
        bsdf.inputs["Coat Roughness"].default_value = 0.08
    if aniso:
        bsdf.inputs["Anisotropic"].default_value = aniso
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*hex_rgb(emission), 1)
        bsdf.inputs["Emission Strength"].default_value = strength
    return m


def put(obj, *materials):
    # meshes arrive with no slots; clearing them would also drop the per-face material indices
    for m in materials:
        obj.data.materials.append(m)
    return obj


# ---- textures ----------------------------------------------------------------------------------


def save_image(name, rgba: np.ndarray, path: str, data=False):
    h, w, _ = rgba.shape
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.pixels.foreach_set(np.flipud(rgba).astype(np.float32).ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    if data:
        img.colorspace_settings.name = "Non-Color"
    return img


def strobe_texture(path, w=2048, h=128):
    """The platter rim: four rows of machined dots, as on a DJ deck's strobe ring."""
    u = (np.arange(w) + 0.5) / w
    v = (np.arange(h) + 0.5) / h
    U, V = np.meshgrid(u, v)
    img = np.zeros((h, w, 4), np.float32)
    base = np.array(hex_rgb("#8b9097"))
    img[..., :3] = base
    rows = [(0.2, 180), (0.4, 183), (0.6, 186), (0.8, 189)]
    for vc, count in rows:
        cu = (np.floor(U * count) + 0.5) / count
        du = (U - cu) * count  # -0.5..0.5 per dot
        dv = (V - vc) * h / 9.0
        dot = np.clip(1.4 - np.sqrt((du * 2.2) ** 2 + (dv * 1.0) ** 2) * 2.2, 0, 1)
        img[..., :3] += dot[..., None] * (np.array(hex_rgb("#f4f5f7")) - base)
    img[..., 3] = 1
    return save_image("strobe", np.clip(img, 0, 1), path)


def groove_textures(meeting, out_dir, size=2048):
    """Colour and a roughness map for the record top, in the planar UV of `lathe` (radius RECORD_R)."""
    d = meeting
    dur = d["meeting"]["duration_s"]
    color_of = {s["track"]: SPEAKERS[s["color_idx"] % len(SPEAKERS)] for s in d["speakers"]}
    xs = (np.arange(size) + 0.5) / size * 2 - 1
    X, Y = np.meshgrid(xs, -xs)
    R = np.sqrt(X**2 + Y**2) * RECORD_R
    t = (GROOVE_OUT - R) / (GROOVE_OUT - GROOVE_IN) * dur
    in_grooves = (R >= GROOVE_IN) & (R <= GROOVE_OUT)
    vinyl = np.array(hex_rgb("#0b0b0d"))
    col = np.broadcast_to(vinyl, R.shape + (3,)).copy()
    spoken = np.zeros(R.shape, bool)
    for u in d["utterances"]:
        m = in_grooves & (t >= u["t_start"]) & (t <= u["t_end"])
        col[m] = np.array(hex_rgb(color_of.get(u["speaker"], SPEAKERS[-1])))
        spoken |= m
    # the groove itself: fine rings, a little lighter on each wall
    rings = 0.5 + 0.5 * np.sin(R * 2 * math.pi * 260)
    # the same dark film the hero lays over the colour (textures.ts), so stills and the live deck match
    col = np.where(spoken[..., None], col * 0.59, col)
    col *= (0.8 + 0.2 * rings)[..., None]
    # spoken bands are tinted metal, so their colour shows where light rakes across them;
    # silences stay glossy black lands, like the gaps between tracks
    rough = np.where(in_grooves, np.where(spoken, 0.3, 0.1), 0.14) + 0.06 * rings * in_grooves
    metal = np.where(spoken, 0.85, 0.0)
    rgba = np.dstack([col, np.ones(R.shape)])
    rmap = np.dstack([rough, metal, np.zeros(R.shape), np.ones(R.shape)])
    return (
        save_image("grooves", rgba, os.path.join(out_dir, "_grooves.png")),
        save_image("groove_rough", rmap, os.path.join(out_dir, "_grooves-rough.png"), data=True),
        spoken,
    )


def label_texture(meeting, path, size=1024):
    """Text-free paper label for the stills: talk-time arcs around the spindle, one per speaker."""
    xs = (np.arange(size) + 0.5) / size * 2 - 1
    X, Y = np.meshgrid(xs, -xs)
    R = np.sqrt(X**2 + Y**2) * RECORD_R
    A = (np.arctan2(X, Y) % (2 * math.pi)) / (2 * math.pi)  # clockwise from 12 o'clock
    paper = np.array(hex_rgb("#ECE9E2"))
    img = np.broadcast_to(paper, R.shape + (3,)).copy()
    speakers = sorted(meeting["speakers"], key=lambda s: -s["talk_time_s"])
    total = sum(s["talk_time_s"] for s in speakers)
    start = 0.0
    for s in speakers:
        span = s["talk_time_s"] / total
        m = (A >= start + 0.004) & (A <= start + span - 0.004) & (R > LABEL_R * 0.66) & (R < LABEL_R * 0.84)
        img[m] = np.array(hex_rgb(SPEAKERS[s["color_idx"] % len(SPEAKERS)]))
        start += span
    ink = np.array(hex_rgb("#101216"))
    img[(R > LABEL_R * 0.93) & (R < LABEL_R * 0.945)] = ink
    img[(R > LABEL_R * 0.2) & (R < LABEL_R * 0.31)] = ink
    rgba = np.dstack([img, np.ones(R.shape)])
    return save_image("label", rgba, path)


# ---- build -------------------------------------------------------------------------------------


def build(meeting, out_dir):
    M = {
        "plinth": mat("Plinth", "#121317", 0.15, 0.42, coat=0.35),
        "deck": mat("Deck", "#17191d", 0.55, 0.34),
        "alu": mat("Aluminium", "#c4c8ce", 1.0, 0.26),
        "chrome": mat("Chrome", "#eceef1", 1.0, 0.07),
        "satin": mat("Satin", "#d9dce0", 1.0, 0.18),
        "dark_metal": mat("DarkMetal", "#1b1d21", 0.85, 0.32),
        "rubber": mat("Rubber", "#0c0c0e", 0.0, 0.88),
        "vinyl": mat("Vinyl", "#09090a", 0.0, 0.16, coat=0.5),
        "grooves": mat("Grooves", "#0b0b0d", 0.0, 0.24),
        "label": mat("Label", "#ece9e2", 0.0, 0.62),
        "cart": mat("Cartridge", "#e9e7e2", 0.0, 0.38, coat=0.4),
        "lamp": mat("StrobeLamp", "#ff7a2e", 0.0, 0.3, emission="#ff7a2e", strength=2.5),
        "led": mat("PowerLed", "#ff4d3d", 0.0, 0.3, emission="#ff4d3d", strength=4.0),
        "button": mat("Button", "#24272c", 0.6, 0.3),
        "rim": mat("PlatterRim", "#8b9097", 1.0, 0.3),
    }
    # the platter rim carries the strobe dots
    rim = M["rim"]
    nt = rim.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = strobe_texture(os.path.join(out_dir, "_strobe.png"))
    nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])

    root = empty("Turntable")

    # plinth with a slightly inset deck plate
    w, d, h = PLINTH
    plinth = rounded_box("Plinth", (w, d, h), 0.09, 5, loc=(0, 0, h / 2))
    plinth.parent = root
    put(plinth, M["plinth"])
    deck = rounded_box("Deck", (w - 0.16, d - 0.16, 0.02), 0.05, 3, loc=(0, 0, h + 0.004))
    deck.parent = root
    put(deck, M["deck"])
    for i, (fx, fy) in enumerate([(-1.85, -1.35), (1.85, -1.35), (-1.85, 1.35), (1.85, 1.35)]):
        foot = mesh_obj(f"Foot{i}", lathe(f"foot{i}", [(0, -0.16), (0.24, -0.16), (0.28, -0.12), (0.28, -0.02), (0.22, 0.0), (0, 0.0)], 48), root, (fx, fy, 0))
        put(foot, M["rubber"])

    # platter: rim with strobe dots, rubber mat on top
    z0, z1 = PLATTER_Z
    platter = empty("Platter", (SPINDLE.x, SPINDLE.y, 0), root)
    rim_me = lathe(
        "platter",
        [(0, z0), (PLATTER_R - 0.02, z0), (PLATTER_R, z0 + 0.02), (PLATTER_R, z1 - 0.025), (PLATTER_R - 0.025, z1), (1.56, z1), (1.56, z1 + 0.005), (0, z1 + 0.005)],
        192,
        mats=[0, 0, 1, 0, 0, 0, 0],
        planar_r=PLATTER_R,
    )
    put(mesh_obj("PlatterBody", rim_me, platter), M["alu"], M["rim"])
    mat_me = lathe("mat", [(0.05, z1 + 0.005), (1.55, z1 + 0.005), (1.55, MAT_Z), (0.05, MAT_Z)], 160)
    put(mesh_obj("Mat", mat_me, platter), M["rubber"])

    # the record: lip, grooves, run-out, label, spindle hole
    record = empty("Record", (0, 0, 0), platter)
    rb = MAT_Z + 0.001
    prof = [
        (0.036, RECORD_TOP + 0.002),
        (LABEL_R, RECORD_TOP + 0.002),
        (LABEL_R + 0.012, RECORD_TOP),
        (GROOVE_IN - 0.04, RECORD_TOP),
        (GROOVE_IN, RECORD_TOP - 0.001),
        (GROOVE_OUT, RECORD_TOP - 0.001),
        (GROOVE_OUT + 0.02, RECORD_TOP + 0.003),
        (RECORD_R - 0.012, RECORD_TOP + 0.003),
        (RECORD_R, RECORD_TOP - 0.006),
        (RECORD_R, rb + 0.004),
        (RECORD_R - 0.01, rb),
        (0.036, rb),
        (0.036, RECORD_TOP + 0.002),
    ]
    rec_mats = [2, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0]
    rec_me = lathe("record", prof, 256, mats=rec_mats, planar_r=RECORD_R)
    rec_obj = put(mesh_obj("RecordDisc", rec_me, record), M["vinyl"], M["grooves"], M["label"])

    spindle = mesh_obj(
        "Spindle",
        lathe("spindle", [(0, z1), (0.034, z1), (0.034, RECORD_TOP + 0.17), (0.026, RECORD_TOP + 0.2), (0, RECORD_TOP + 0.205)], 32),
        platter,
    )
    put(spindle, M["chrome"])

    # strobe lamp, start/stop, speed buttons, pitch fader
    lamp_pos = SPINDLE + Vector((math.cos(math.radians(215)), math.sin(math.radians(215)))) * 1.82
    lamp = mesh_obj(
        "StrobeTower",
        lathe("lamp", [(0, h), (0.085, h), (0.085, h + 0.14), (0.07, h + 0.17), (0, h + 0.17)], 40, mats=[0, 0, 1, 1]),
        root,
        (lamp_pos.x, lamp_pos.y, 0),
    )
    put(lamp, M["dark_metal"], M["lamp"])
    start = rounded_box("StartStop", (0.46, 0.26, 0.05), 0.03, 3, loc=(-1.72, -1.42, h + 0.03))
    start.parent = root
    put(start, M["button"])
    for i, x in enumerate((-1.2, -0.92)):
        b = rounded_box(f"Speed{i}", (0.2, 0.12, 0.035), 0.02, 2, loc=(x, -1.46, h + 0.025))
        b.parent = root
        put(b, M["button"])
    led = mesh_obj("PowerLed", lathe("led", [(0, h + 0.012), (0.022, h + 0.012), (0.022, h + 0.02), (0, h + 0.022)], 16), root, (-1.2, -1.31, 0))
    put(led, M["led"])
    slot = rounded_box("PitchSlot", (0.08, 1.05, 0.012), 0.03, 2, loc=(1.98, -0.92, h + 0.008))
    slot.parent = root
    put(slot, M["rubber"])
    knob = rounded_box("PitchKnob", (0.2, 0.12, 0.09), 0.03, 3, loc=(1.98, -0.92, h + 0.05))
    knob.parent = root
    put(knob, M["satin"])

    # tonearm base (static)
    base = mesh_obj(
        "ArmBase",
        lathe(
            "armbase",
            [(0, h), (0.36, h), (0.36, h + 0.05), (0.32, h + 0.07), (0.2, h + 0.07), (0.2, h + 0.11), (0.15, h + 0.13), (0.15, ARM_Z - 0.07), (0.1, ARM_Z - 0.05), (0, ARM_Z - 0.05)],
            64,
            mats=[0, 0, 0, 0, 1, 1, 1, 1, 1],
        ),
        root,
        (PIVOT.x, PIVOT.y, 0),
    )
    put(base, M["dark_metal"], M["satin"])

    # arm rest post where the arm parks
    rest_angle = math.radians(-93)
    rest_xy = PIVOT + Vector((math.cos(rest_angle), math.sin(rest_angle))) * 1.32
    post = mesh_obj(
        "ArmRest",
        lathe("rest", [(0, h), (0.06, h), (0.04, h + 0.02), (0.035, ARM_Z - 0.07), (0.07, ARM_Z - 0.05), (0, ARM_Z - 0.05)], 32),
        root,
        (rest_xy.x, rest_xy.y, 0),
    )
    put(post, M["dark_metal"])

    # moving arm: ArmPivot turns about Z, ArmLift tilts about Y; local +X points down the arm
    pivot = empty("ArmPivot", (PIVOT.x, PIVOT.y, ARM_Z), root)
    lift = empty("ArmLift", (0, 0, 0), pivot)
    along_x = Matrix.Rotation(math.radians(90), 4, "Y")
    gimbal = mesh_obj(
        "Gimbal",
        lathe("gimbal", [(0, -0.09), (0.11, -0.09), (0.12, -0.06), (0.12, 0.06), (0.11, 0.09), (0, 0.09)], 48, xform=Matrix.Rotation(math.radians(90), 4, "X")),
        lift,
    )
    put(gimbal, M["satin"])
    tube = mesh_obj(
        "ArmTube",
        lathe("tube", [(0, -0.5), (0.04, -0.5), (0.045, -0.46), (0.045, ARM_LEN - 0.02), (0.035, ARM_LEN), (0, ARM_LEN)], 32, xform=along_x),
        lift,
    )
    put(tube, M["satin"])
    cw = mesh_obj(
        "Counterweight",
        lathe(
            "cw",
            [(0, -0.82), (0.13, -0.82), (0.155, -0.79), (0.155, -0.62), (0.13, -0.59), (0.06, -0.59), (0.06, -0.52), (0, -0.52)],
            64,
            xform=along_x,
        ),
        lift,
    )
    put(cw, M["dark_metal"])
    cw_ring = mesh_obj("CounterweightRing", lathe("cwring", [(0.156, -0.71), (0.158, -0.7), (0.158, -0.66), (0.156, -0.65)], 64, xform=along_x), lift)
    put(cw_ring, M["chrome"])

    # headshell, rotated by the offset angle toward the spindle
    head = empty("Headshell", (ARM_LEN, 0, 0), lift)
    head.rotation_euler = (0, 0, -HEADSHELL_OFFSET)
    collar = mesh_obj("Collar", lathe("collar", [(0, -0.06), (0.055, -0.06), (0.06, -0.04), (0.06, 0.08), (0.05, 0.1), (0, 0.1)], 32, xform=along_x), head)
    put(collar, M["dark_metal"])
    shell_bm = bmesh.new()
    outline = [(0.06, -0.08), (0.42, -0.1), (0.46, -0.07), (0.46, 0.07), (0.42, 0.1), (0.06, 0.08)]
    top = [shell_bm.verts.new((x, y, -0.005)) for x, y in outline]
    bot = [shell_bm.verts.new((x, y, -0.035)) for x, y in outline]
    shell_bm.faces.new(top)
    shell_bm.faces.new(bot[::-1])
    for i in range(len(outline)):
        j = (i + 1) % len(outline)
        shell_bm.faces.new([top[j], top[i], bot[i], bot[j]])
    bmesh.ops.recalc_face_normals(shell_bm, faces=shell_bm.faces)
    shell_me = bpy.data.meshes.new("shell")
    shell_bm.to_mesh(shell_me)
    shell_bm.free()
    finish_mesh(shell_me, 30)
    put(mesh_obj("Shell", shell_me, head), M["dark_metal"])
    lift_bar = mesh_obj(
        "FingerLift",
        lathe("fl", [(0, 0), (0.014, 0), (0.014, 0.2), (0, 0.2)], 12, xform=Matrix.Rotation(math.radians(-70), 4, "X")),
        head,
        (0.34, 0.09, -0.02),
    )
    put(lift_bar, M["satin"])
    cart = rounded_box("Cartridge", (0.26, 0.15, 0.1), 0.02, 3, loc=(0, 0, 0))
    cart.parent = head
    cart.location = (0.27, 0, -0.088)
    put(cart, M["cart"])
    stylus_z = (RECORD_TOP - 0.001) - ARM_Z
    cant = mesh_obj(
        "Cantilever",
        lathe("cant", [(0, 0), (0.006, 0), (0.004, 0.09), (0, 0.095)], 10, xform=Matrix.Rotation(math.radians(135), 4, "Y")),
        head,
        (0.38, 0, stylus_z - 0.095 * math.cos(math.radians(135))),
    )
    put(cant, M["chrome"])
    tip = empty("StylusTip", (0.38 + 0.095 * math.sin(math.radians(135)), 0, stylus_z), head)

    # park the arm on its rest
    pivot.rotation_euler = (0, 0, rest_angle)

    return {"root": root, "record": rec_obj, "materials": M, "tip": tip, "pivot": pivot}


def ground(size=14):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, -0.16))
    g = bpy.context.active_object
    g.name = "Ground"
    return g


# ---- cycles stills -----------------------------------------------------------------------------


def cycles(scene, samples):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for dev in prefs.devices:
            dev.use = True
        scene.cycles.device = "GPU"
    except Exception:  # CPU is fine, just slower
        scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"


def upgrade_record(parts, meeting, out_dir):
    """Swap the flat record materials for image-driven ones with radial anisotropy (Cycles only)."""
    M = parts["materials"]
    color_img, rough_img, _ = groove_textures(meeting, out_dir)
    g = M["grooves"]
    nt = g.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = color_img
    tr = nt.nodes.new("ShaderNodeTexImage")
    tr.image = rough_img
    tr.image.colorspace_settings.name = "Non-Color"
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(tr.outputs["Color"], sep.inputs["Color"])
    nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(sep.outputs["Red"], bsdf.inputs["Roughness"])
    nt.links.new(sep.outputs["Green"], bsdf.inputs["Metallic"])
    bsdf.inputs["Anisotropic"].default_value = 0.9
    tan = nt.nodes.new("ShaderNodeTangent")
    tan.direction_type = "RADIAL"
    tan.axis = "Z"
    nt.links.new(tan.outputs["Tangent"], bsdf.inputs["Tangent"])
    lab = M["label"]
    lt = lab.node_tree.nodes.new("ShaderNodeTexImage")
    lt.image = label_texture(meeting, os.path.join(out_dir, "_label.png"))
    lab.node_tree.links.new(lt.outputs["Color"], lab.node_tree.nodes["Principled BSDF"].inputs["Base Color"])


def area(name, loc, rot, size, energy, color="#ffffff", shape="RECTANGLE", size_y=None):
    light = bpy.data.lights.new(name, "AREA")
    light.shape = shape
    light.size = size
    if size_y is not None:
        light.size_y = size_y
    light.energy = energy
    light.color = hex_rgb(color)
    obj = bpy.data.objects.new(name, light)
    obj.location = loc
    obj.rotation_euler = [math.radians(a) for a in rot]
    return link(obj)


def look_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def camera(name, loc, target, lens=50, dof=None, fstop=2.8):
    cam = bpy.data.cameras.new(name)
    cam.lens = lens
    obj = link(bpy.data.objects.new(name, cam))
    obj.location = loc
    look_at(obj, target)
    if dof is not None:
        cam.dof.use_dof = True
        cam.dof.focus_distance = (Vector(dof) - Vector(loc)).length
        cam.dof.aperture_fstop = fstop
    return obj


def studio_world(scene, strength=0.25):
    world = bpy.data.worlds.new("Studio")
    scene.world = world
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*hex_rgb("#0c0d10"), 1)
    bg.inputs["Strength"].default_value = strength


def render(scene, cam, path, res, samples=None):
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = res
    if samples:
        scene.cycles.samples = samples
    scene.render.filepath = path
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    bpy.ops.render.render(write_still=True)


def bake_shadow(scene, out_path, size=1024):
    """Ambient occlusion on the ground under the deck, saved as a grey map the hero uses as alpha."""
    g = ground(8)
    m = bpy.data.materials.new("GroundBake")
    try:
        m.use_nodes = True
    except AttributeError:
        pass
    img = bpy.data.images.new("shadow", size, size, alpha=False)
    node = m.node_tree.nodes.new("ShaderNodeTexImage")
    node.image = img
    m.node_tree.nodes.active = node
    g.data.materials.append(m)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 256
    scene.world.light_settings.distance = 2.2
    bpy.ops.object.select_all(action="DESELECT")
    g.select_set(True)
    bpy.context.view_layer.objects.active = g
    bpy.ops.object.bake(type="AO", margin=4)
    # the hero lays this over a black plane as alpha: dark where the deck shades the floor, clear elsewhere
    ao = np.array(img.pixels[:], np.float32).reshape(size, size, 4)[..., 0]
    alpha = np.clip((1.0 - ao) * 1.25, 0, 1)
    half = alpha.reshape(size // 2, 2, size // 2, 2).mean(axis=(1, 3))
    out = bpy.data.images.new("shadow_alpha", size // 2, size // 2, alpha=True)
    rgba = np.dstack([half, half, half, np.ones_like(half)])
    out.pixels.foreach_set(rgba.astype(np.float32).ravel())
    out.filepath_raw = out_path
    out.file_format = "PNG"
    out.save()
    bpy.data.objects.remove(g, do_unlink=True)


def aim(meta, r):
    """Pivot angle that puts the stylus at radius r from the spindle (the same maths runs in the hero)."""
    sx, sy = meta["spindle"]
    px, py = meta["pivot"]
    lx, ly, _ = meta["tip_local"]
    dx, dy = px - sx, py - sy
    dist, length = math.hypot(dx, dy), math.hypot(lx, ly)
    c = (r * r - dist * dist - length * length) / (2 * length * dist)
    base = math.atan2(-dy, -dx) - math.atan2(ly, lx)  # stylus pointing at the spindle
    options = [base + math.acos(max(-1, min(1, -c))), base - math.acos(max(-1, min(1, -c)))]
    return min(options, key=lambda a: abs(math.remainder(a - meta["rest_angle"], 2 * math.pi)))


def main():
    a = args()
    os.makedirs(a.out, exist_ok=True)
    fixtures = json.load(open(FIXTURES))
    meeting = fixtures["details"][a.meeting]

    scene = reset()
    studio_world(scene)
    parts = build(meeting, a.out)

    # what the hero needs to aim the stylus: the tip in the pivot's own frame, plus the record's radii
    bpy.context.view_layer.update()
    pivot = parts["pivot"]
    tip_local = pivot.matrix_world.inverted() @ parts["tip"].matrix_world.translation
    meta = {
        "unit_mm": 100,
        "spindle": [SPINDLE.x, SPINDLE.y],
        "pivot": [PIVOT.x, PIVOT.y],
        "tip_local": [tip_local.x, tip_local.y, tip_local.z],
        "rest_angle": pivot.rotation_euler.z,
        "record_r": RECORD_R,
        "groove_out": GROOVE_OUT,
        "groove_in": GROOVE_IN,
        "label_r": LABEL_R,
        "record_top": RECORD_TOP,
    }
    with open(a.meta, "w") as f:
        json.dump({k: (round(v, 5) if isinstance(v, float) else [round(x, 5) for x in v] if isinstance(v, list) else v) for k, v in meta.items()}, f, indent=2)
        f.write("\n")

    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.export_scene.gltf(
        filepath=os.path.join(a.out, "turntable.glb"),
        export_format="GLB",
        export_yup=True,
        export_apply=True,
        export_cameras=False,
        export_lights=False,
        export_extras=False,
        export_image_format="JPEG",
    )

    bake_shadow(scene, os.path.join(a.out, "turntable-shadow.png"))

    if not a.render:
        return

    upgrade_record(parts, meeting, a.out)
    cycles(scene, a.samples)
    scene.render.resolution_percentage = a.scale
    catcher = ground(30)
    catcher.is_shadow_catcher = True

    # drop the needle where the first decision lands
    decision_t = meeting["decisions"][0]["made_at"]
    r = GROOVE_OUT - decision_t / meeting["meeting"]["duration_s"] * (GROOVE_OUT - GROOVE_IN)
    pivot.rotation_euler.z = aim(meta, r)
    bpy.context.view_layer.update()
    target = (SPINDLE.x + 0.5, SPINDLE.y, 0.6)
    area("Key", (-2.5, -3.5, 6.5), (35, 0, -30), 5.0, 900, "#f3f1ec")
    area("Strip", (5.5, -1.5, 2.5), (60, 0, 75), 0.6, 300, "#dfe6ff", size_y=6.0)
    area("Rim", (2.0, 6.0, 2.8), (-70, 0, 180), 6.0, 450, "#ffffff", size_y=0.5)
    area("Fill", (-6, 1, 3), (0, -70, 0), 4.0, 70, "#a9b8d8")

    if not a.record_only:
        hero = camera("HeroCam", (5.6, -7.4, 6.4), target, lens=55)
        render(scene, hero, os.path.join(a.out, "_hero.png"), (2400, 1600))

        # macro: the stylus riding the grooves, shallow focus
        tipw = parts["tip"].matrix_world.translation
        macro = camera("MacroCam", (tipw.x - 1.2, tipw.y - 1.05, tipw.z + 0.42), (tipw.x, tipw.y, tipw.z + 0.02), lens=85, dof=tipw, fstop=1.6)
        render(scene, macro, os.path.join(a.out, "_macro.png"), (2400, 1350))

    # the record alone, square on and evenly lit, for the closing section (the page turns it)
    keep = {"RecordDisc", "Record", "Platter"}
    for o in scene.objects:
        if o.type in {"MESH", "LIGHT"} and o.name not in keep:
            o.hide_render = True
    # A broad light overhead bounces straight into a square-on camera and bleaches the vinyl, and low
    # lights miss it entirely. A thin strip above, plus a dim fill, gives the radial streak and keeps it dark.
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.04
    area("Strip", (SPINDLE.x + 0.6, SPINDLE.y, 6.0), (0, 0, 28), 0.35, 140, "#ffffff", size_y=9.0)
    area("Fill", (SPINDLE.x, SPINDLE.y, 6.5), (0, 0, 0), 8.0, 38, "#cfd8ea")
    rec = camera("RecordCam", (SPINDLE.x, SPINDLE.y, 6.0), (SPINDLE.x, SPINDLE.y, RECORD_TOP), lens=50)
    rec.data.type = "ORTHO"
    rec.data.ortho_scale = RECORD_R * 2.02
    render(scene, rec, os.path.join(a.out, "_record.png"), (1600, 1600), samples=128)


if __name__ == "__main__":
    main()
