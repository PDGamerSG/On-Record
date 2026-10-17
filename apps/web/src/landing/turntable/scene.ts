// The hero's turntable: the GLB built in Blender (scripts/blender/build_turntable.py), lit by a small
// studio of softboxes, with the record re-pressed from whichever meeting is on the platter.
//
// Frames: the GLB is Y-up. Blender's (x, y) on the deck maps to three's (x, -z), and a rotation about
// Blender Z is the same angle about three's Y, so the arm maths stays in Blender units (see meta.ts).
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import type { Side } from "../sides";
import { aimArm, type TurntableMeta } from "./meta";
import { grooveDirection, grooveMaps, labelTexture, radiusAt, timeAtRadius } from "./textures";

export interface TurntableHooks {
  /** seconds into the side on the platter */
  time(): number;
  /** is the platter turning */
  playing(): boolean;
  onHover(hit: { t: number; x: number; y: number } | null): void;
  onPick(t: number): void;
  onReady(): void;
}

const RPM = 100 / 3;
const OMEGA = (RPM / 60) * Math.PI * 2;
const LIFT = 0.075; // radians the arm rises to cue
const DROP_THRESHOLD = 0.03; // a jump bigger than this lifts the arm instead of sliding it

type ArmPhase = "rest" | "lifting" | "moving" | "lowering" | "tracking";

function studioEnvironment(renderer: THREE.WebGLRenderer): THREE.Texture {
  // A dark room with three softboxes: a big overhead key, a tall strip on the right, a thin rim behind.
  const env = new THREE.Scene();
  env.background = new THREE.Color(0x030304);
  const box = (w: number, h: number, pos: [number, number, number], strength: number, color = 0xffffff) => {
    const m = new THREE.Mesh(
      new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(strength), side: THREE.DoubleSide }),
    );
    m.position.set(...pos);
    m.lookAt(0, 0, 0);
    env.add(m);
  };
  box(9, 5, [-2.5, 10, 3], 5.5, 0xf4f1ea);
  box(1.4, 11, [11, 3.5, 1], 3.2, 0xdfe7ff);
  box(12, 0.9, [0, 3.2, -11], 2.6);
  box(7, 3.5, [-11, 2, 4], 0.5, 0x9fb3dc);
  box(30, 30, [0, -12, 0], 0.03); // the desk, faintly
  const pmrem = new THREE.PMREMGenerator(renderer);
  const tex = pmrem.fromScene(env, 0.035).texture;
  pmrem.dispose();
  env.traverse((o) => {
    if (o instanceof THREE.Mesh) {
      o.geometry.dispose();
      (o.material as THREE.Material).dispose();
    }
  });
  return tex;
}

export class TurntableScene {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(24, 1, 0.1, 100);
  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2(2, 2);
  private parallax = new THREE.Vector2();
  private parallaxTarget = new THREE.Vector2();
  private disposed = false;
  private running = false;
  private raf = 0;
  private last = 0;
  private spin = 0;

  private platter?: THREE.Object3D;
  private armPivot?: THREE.Object3D;
  private armLift?: THREE.Object3D;
  private grooveMeshes: THREE.Mesh[] = [];
  private grooveMat = new THREE.MeshPhysicalMaterial({
    color: 0xffffff,
    roughness: 1,
    metalness: 1,
    anisotropy: 0.95,
    clearcoat: 0.15,
    clearcoatRoughness: 0.3,
    envMapIntensity: 2,
  });
  private labelMat = new THREE.MeshPhysicalMaterial({ roughness: 0.68, metalness: 0, clearcoat: 0.08 });
  private vinylMat = new THREE.MeshPhysicalMaterial({ color: 0x08080a, roughness: 0.2, metalness: 0, clearcoat: 1, clearcoatRoughness: 0.08 });
  private textures: THREE.Texture[] = [];
  private key = new THREE.DirectionalLight(0xfff6ea, 2.6);
  private clock = 0;

  private side?: Side;
  private arm = { phase: "rest" as ArmPhase, angle: 0, lift: 0, target: 0 };

  /** Desktop composition: shift the deck right of centre so the headline owns the left. */
  framing = { offsetX: 0, offsetY: 0, distance: 14.2, azimuth: -0.34, elevation: 0.72 };

  private canvas: HTMLCanvasElement;
  private meta: TurntableMeta;
  private hooks: TurntableHooks;
  private reducedMotion: boolean;

  constructor(canvas: HTMLCanvasElement, meta: TurntableMeta, hooks: TurntableHooks, reducedMotion: boolean) {
    this.canvas = canvas;
    this.meta = meta;
    this.hooks = hooks;
    this.reducedMotion = reducedMotion;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.AgXToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.scene.environment = studioEnvironment(this.renderer);
    this.scene.environmentIntensity = 1;
    this.arm.angle = meta.rest_angle;
    this.arm.target = meta.rest_angle;

    this.key.position.set(0.5, 9, 6);
    this.scene.add(this.key);
    const rim = new THREE.DirectionalLight(0xcfe0ff, 0.8);
    rim.position.set(5, 3, -7);
    this.scene.add(rim);

    const dir = grooveDirection(meta);
    this.grooveMat.anisotropyMap = dir;
    this.textures.push(dir);
  }

  async load(glbUrl: string, shadowUrl: string): Promise<void> {
    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    const [gltf, shadow] = await Promise.all([loader.loadAsync(glbUrl), new THREE.TextureLoader().loadAsync(shadowUrl)]);
    if (this.disposed) return;
    const root = gltf.scene;
    root.traverse((o) => {
      if (!(o instanceof THREE.Mesh)) return;
      const name = (o.material as THREE.Material).name;
      if (name === "Grooves") {
        o.material = this.grooveMat;
        this.grooveMeshes.push(o);
      } else if (name === "Label") o.material = this.labelMat;
      else if (name === "Vinyl") o.material = this.vinylMat;
      else if (name === "StrobeLamp" || name === "PowerLed") {
        const m = o.material as THREE.MeshStandardMaterial;
        m.emissiveIntensity = name === "StrobeLamp" ? 2.2 : 3;
        m.toneMapped = false;
      }
    });
    this.platter = root.getObjectByName("Platter");
    this.armPivot = root.getObjectByName("ArmPivot");
    this.armLift = root.getObjectByName("ArmLift");
    this.scene.add(root);

    // the strobe lamp throws warm light across the platter's dots
    const lamp = root.getObjectByName("StrobeTower");
    if (lamp) {
      const glow = new THREE.PointLight(0xff7a2e, 2.4, 2.2, 1.6);
      glow.position.copy(lamp.position).add(new THREE.Vector3(0.15, 0.85, -0.1));
      this.scene.add(glow);
    }

    this.scene.add(this.plinthPrint());

    // baked contact shadow from Blender
    shadow.colorSpace = THREE.NoColorSpace;
    this.textures.push(shadow);
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(8, 8),
      new THREE.MeshBasicMaterial({ color: 0x000000, alphaMap: shadow, transparent: true, opacity: 0.9, depthWrite: false }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -0.159;
    floor.renderOrder = -1;
    this.scene.add(floor);

    this.hooks.onReady();
    this.render();
  }

  /** Silk-screen on the deck's front strip: the controls' labels and the maker's mark. */
  private plinthPrint(): THREE.Mesh {
    const W = 2048;
    const H = 248;
    const x0 = -2.15;
    const x1 = 2.15;
    const back = -1.21;
    const front = -1.73;
    const c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    const g = c.getContext("2d")!;
    const px = (x: number) => ((x - x0) / (x1 - x0)) * W;
    const py = (y: number) => ((back - y) / (back - front)) * H;
    g.fillStyle = "#000";
    g.fillRect(0, 0, W, H);
    g.fillStyle = "#fff";
    g.textAlign = "center";
    g.textBaseline = "middle";
    const label = (text: string, x: number, y: number, size: number, weight: number, track: number) => {
      g.font = `${weight} ${size}px "Recursive Variable", sans-serif`;
      if ("letterSpacing" in g) (g as CanvasRenderingContext2D & { letterSpacing: string }).letterSpacing = `${track}px`;
      g.fillText(text, px(x), py(y));
    };
    label("START · STOP", -1.72, -1.635, 19, 600, 3);
    label("33", -1.2, -1.6, 19, 600, 2);
    label("45", -0.92, -1.6, 19, 600, 2);
    label("ON RECORD", 0.62, -1.47, 30, 650, 11);
    label("SPEAKER-ATTRIBUTED  ·  33⅓ RPM", 0.62, -1.6, 13, 500, 4);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.NoColorSpace;
    tex.anisotropy = 8;
    this.textures.push(tex);
    const mesh = new THREE.Mesh(
      new THREE.PlaneGeometry(x1 - x0, back - front),
      new THREE.MeshStandardMaterial({
        color: 0xaeb3ba,
        metalness: 0.5,
        roughness: 0.4,
        alphaMap: tex,
        transparent: true,
        depthWrite: false,
        polygonOffset: true,
        polygonOffsetFactor: -2,
      }),
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set((x0 + x1) / 2, 0.5146, -(back + front) / 2);
    return mesh;
  }

  setSide(side: Side, hex: string[]): void {
    this.side = side;
    const size = Math.min(2048, this.renderer.capabilities.maxTextureSize);
    const { map, orm } = grooveMaps(this.meta, side, hex, size);
    const label = labelTexture(this.meta, side, hex);
    for (const old of [this.grooveMat.map, this.grooveMat.roughnessMap, this.labelMat.map]) {
      if (old) {
        old.dispose();
        this.textures = this.textures.filter((t) => t !== old);
      }
    }
    this.grooveMat.map = map;
    this.grooveMat.roughnessMap = orm;
    this.grooveMat.metalnessMap = orm;
    this.grooveMat.needsUpdate = true;
    this.labelMat.map = label;
    this.labelMat.needsUpdate = true;
    this.textures.push(map, orm, label);
    this.render();
  }

  setSize(width: number, height: number): void {
    const dpr = Math.min(window.devicePixelRatio || 1, width < 700 ? 1.5 : 2);
    this.renderer.setPixelRatio(dpr);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    const { offsetX, offsetY } = this.framing;
    if (offsetX || offsetY) this.camera.setViewOffset(width, height, -offsetX * width, offsetY * height, width, height);
    else this.camera.clearViewOffset();
    this.camera.updateProjectionMatrix();
    this.render();
  }

  /** pointer in canvas pixels, or null when it leaves */
  setPointer(x: number | null, y = 0): void {
    const r = this.canvas.getBoundingClientRect();
    if (x === null) {
      this.pointer.set(2, 2);
      this.parallaxTarget.set(0, 0);
      this.hooks.onHover(null);
      this.canvas.style.cursor = "";
      return;
    }
    this.pointer.set(((x - r.left) / r.width) * 2 - 1, -((y - r.top) / r.height) * 2 + 1);
    if (!this.reducedMotion) this.parallaxTarget.set(this.pointer.x, this.pointer.y);
    const t = this.pick();
    this.canvas.style.cursor = t === null ? "" : "pointer";
    this.hooks.onHover(t === null ? null : { t, x: x - r.left, y: y - r.top });
  }

  click(x: number, y: number): boolean {
    this.setPointer(x, y);
    const t = this.pick();
    if (t === null) return false;
    this.hooks.onPick(t);
    return true;
  }

  private pick(): number | null {
    if (!this.side || !this.platter || !this.grooveMeshes.length) return null;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hit = this.raycaster.intersectObjects(this.grooveMeshes, false)[0];
    if (!hit) return null;
    const c = new THREE.Vector3();
    this.platter.getWorldPosition(c);
    return timeAtRadius(this.meta, this.side, Math.hypot(hit.point.x - c.x, hit.point.z - c.z));
  }

  start(): void {
    if (this.running || this.disposed) return;
    this.running = true;
    this.last = performance.now();
    const loop = (now: number) => {
      if (!this.running) return;
      this.step(Math.min(0.05, (now - this.last) / 1000));
      this.last = now;
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  /** Reduced motion: no loop; place everything where it belongs and draw one frame. */
  snap(): void {
    if (!this.side) return;
    this.arm.angle = this.arm.target = aimArm(this.meta, radiusAt(this.meta, this.side, this.hooks.time()));
    this.arm.lift = 0;
    this.arm.phase = "tracking";
    this.render();
  }

  private step(dt: number): void {
    const playing = this.hooks.playing();
    const goal = playing && !this.reducedMotion ? OMEGA : 0;
    this.spin += (goal - this.spin) * (1 - Math.exp(-dt * (goal ? 1.6 : 2.4)));
    if (this.platter) this.platter.rotation.y -= this.spin * dt;

    if (this.side) {
      const target = aimArm(this.meta, radiusAt(this.meta, this.side, this.hooks.time()));
      this.stepArm(dt, target, playing);
    }

    this.parallax.lerp(this.parallaxTarget, 1 - Math.exp(-dt * 3));
    // the key light drifts, and follows the pointer, so the colour in the grooves catches and moves
    this.clock += dt;
    this.key.position.set(0.5 + Math.sin(this.clock * 0.35) * 2.2 + this.parallax.x * 4.5, 9, 6 - this.parallax.y * 3.5);
    this.render();
  }

  private stepArm(dt: number, target: number, playing: boolean): void {
    const a = this.arm;
    const ease = (k: number) => 1 - Math.exp(-dt * k);
    switch (a.phase) {
      case "rest":
        if (playing) a.phase = "lifting";
        break;
      case "tracking":
        if (Math.abs(target - a.angle) > DROP_THRESHOLD) a.phase = "lifting";
        else a.angle += (target - a.angle) * ease(14);
        break;
      case "lifting":
        a.lift += (LIFT * 1.08 - a.lift) * ease(9);
        if (a.lift >= LIFT * 0.97) a.phase = "moving";
        break;
      case "moving":
        a.angle += (target - a.angle) * ease(4.2);
        if (Math.abs(target - a.angle) < 0.002) a.phase = "lowering";
        break;
      case "lowering":
        a.angle += (target - a.angle) * ease(14);
        a.lift += (0 - a.lift) * ease(5.5);
        if (a.lift < 0.0015) {
          a.lift = 0;
          a.phase = "tracking";
        }
        break;
    }
    // set every axis: the GLB's -93° rest pose decomposes to Euler (π, y, π), so touching y alone would flip the arm
    if (this.armPivot) this.armPivot.rotation.set(0, a.angle, 0);
    if (this.armLift) this.armLift.rotation.set(0, 0, a.lift);
  }

  private placeCamera(): void {
    const f = this.framing;
    const az = f.azimuth + this.parallax.x * 0.07;
    const el = f.elevation + this.parallax.y * 0.035;
    const target = new THREE.Vector3(0, 0.25, 0.1);
    this.camera.position.set(
      target.x + f.distance * Math.sin(az) * Math.cos(el),
      target.y + f.distance * Math.sin(el),
      target.z + f.distance * Math.cos(az) * Math.cos(el),
    );
    this.camera.lookAt(target);
  }

  render(): void {
    if (this.disposed) return;
    this.placeCamera();
    this.renderer.render(this.scene, this.camera);
  }

  dispose(): void {
    this.disposed = true;
    this.stop();
    this.textures.forEach((t) => t.dispose());
    this.scene.environment?.dispose();
    this.scene.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.geometry.dispose();
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m: THREE.Material) => m.dispose());
      }
    });
    this.renderer.dispose();
  }
}
