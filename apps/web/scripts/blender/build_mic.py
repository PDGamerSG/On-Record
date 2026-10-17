"""Renders the talkback microphone for the landing page's "Ask it out loud" section.

A large-diaphragm studio condenser: satin nickel body, a two-layer wire grille over a dark capsule,
and a thin red ring that marks it as the live talkback. Rendered in Cycles on a transparent ground.

Run from apps/web:
  blender -b -P scripts/blender/build_mic.py -- --out /tmp/mic.png [--samples 256]
"""

from __future__ import annotations

import argparse
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_turntable import area, camera, cycles, lathe, link, mat, mesh_obj, reset, studio_world  # noqa: E402

BODY_R = 0.3
BODY_TOP = 1.55
HEAD_TOP = 2.32


def args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="/tmp/mic.png")
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--scale", type=int, default=100)
    return p.parse_args(argv)


def head_profile(r, rings=28):
    """Cylinder below the belt, a dome above it: the outline the grille wire follows."""
    pts = [(r, BODY_TOP + 0.04)]
    belt = 1.96
    for i in range(1, 7):
        pts.append((r, BODY_TOP + 0.04 + (belt - BODY_TOP - 0.04) * i / 6))
    dome = HEAD_TOP - belt
    for i in range(1, rings + 1):
        a = (math.pi / 2) * i / rings
        pts.append((max(0.0, r * math.cos(a)), belt + dome * math.sin(a) * (r / 0.31)))
    return pts


def grille(name, r, segments, wire, material, parent):
    me = lathe(name, head_profile(r), segments, sharp_deg=60)
    obj = mesh_obj(name, me, parent)
    obj.data.materials.append(material)
    mod = obj.modifiers.new("wire", "WIREFRAME")
    mod.thickness = wire
    mod.use_even_offset = True
    mod.use_relative_offset = False
    return obj


def build():
    nickel = mat("Nickel", "#c3c6cb", 1.0, 0.24)
    nickel_dark = mat("NickelDark", "#8d9197", 1.0, 0.3)
    black = mat("Black", "#0d0e10", 0.4, 0.38)
    capsule = mat("Capsule", "#16171a", 0.6, 0.5)
    gold = mat("Diaphragm", "#b8924a", 1.0, 0.22)
    live = mat("Live", "#ff4d3d", 0.0, 0.3, emission="#ff4d3d", strength=3.0)

    root = link(bpy.data.objects.new("Mic", None))

    body = mesh_obj(
        "Body",
        lathe(
            "body",
            [(0, -0.02), (0.22, -0.02), (0.27, 0.03), (BODY_R, 0.12), (BODY_R, BODY_TOP - 0.06), (BODY_R + 0.012, BODY_TOP - 0.03), (BODY_R + 0.012, BODY_TOP + 0.04), (0, BODY_TOP + 0.04)],
            128,
            mats=[0, 0, 0, 0, 1, 1, 1],
        ),
        root,
    )
    body.data.materials.append(nickel)
    body.data.materials.append(nickel_dark)

    ring = mesh_obj("LiveRing", lathe("ring", [(BODY_R + 0.002, 1.18), (BODY_R + 0.004, 1.185), (BODY_R + 0.004, 1.205), (BODY_R + 0.002, 1.21)], 128), root)
    ring.data.materials.append(live)

    badge = mesh_obj("Badge", lathe("badge", [(0, 0), (0.07, 0), (0.07, 0.012), (0, 0.016)], 48), root)
    badge.data.materials.append(black)
    badge.rotation_euler = (math.radians(90), 0, 0)
    badge.location = (0, -BODY_R - 0.004, 1.38)

    # the capsule: a dark drum with the diaphragm's gold edge, seen through the grille
    cap = mesh_obj("Capsule", lathe("cap", [(0, 1.78), (0.19, 1.78), (0.2, 1.8), (0.2, 2.06), (0.19, 2.08), (0, 2.08)], 64, mats=[0, 0, 0, 1, 1]), root)
    cap.data.materials.append(capsule)
    cap.data.materials.append(gold)
    post = mesh_obj("CapsulePost", lathe("post", [(0, BODY_TOP), (0.05, BODY_TOP), (0.05, 1.8), (0, 1.8)], 24), root)
    post.data.materials.append(capsule)

    grille("GrilleOuter", 0.31, 96, 0.0055, mat("Grille", "#a9adb3", 1.0, 0.34), root)
    grille("GrilleInner", 0.295, 72, 0.004, nickel_dark, root)
    belt = mesh_obj("Belt", lathe("belt", [(0.312, 1.94), (0.318, 1.945), (0.318, 1.975), (0.312, 1.98)], 128), root)
    belt.data.materials.append(nickel)
    base_ring = mesh_obj("BaseRing", lathe("basering", [(0.3, BODY_TOP + 0.03), (0.318, BODY_TOP + 0.04), (0.318, BODY_TOP + 0.09), (0.3, BODY_TOP + 0.1)], 128), root)
    base_ring.data.materials.append(nickel)

    # stand thread under the body
    thread = mesh_obj("Thread", lathe("thread", [(0, -0.4), (0.1, -0.4), (0.1, -0.02), (0, -0.02)], 32), root)
    thread.data.materials.append(black)

    root.rotation_euler = (math.radians(-5), math.radians(4), 0)
    return root


def main():
    a = args()
    scene = reset()
    studio_world(scene, 0.12)
    build()
    cycles(scene, a.samples)
    scene.render.resolution_percentage = a.scale
    target = (0, 0, 0.98)
    area("Key", (-3.2, -3.4, 4.2), (50, 0, -40), 2.6, 520, "#f6f2ea")
    area("RimR", (3.0, 1.6, 2.4), (70, 0, 120), 0.5, 380, "#dfe7ff", size_y=4.0)
    area("RimL", (-3.0, 2.0, 1.8), (75, 0, -125), 0.4, 300, "#ffffff", size_y=4.0)
    area("Top", (0, 0.4, 5.0), (0, 0, 0), 1.6, 160, "#ffffff")
    cam = camera("Cam", (1.0, -7.6, 1.55), target, lens=72)
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y = 1200, 1600
    scene.render.filepath = a.out
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
