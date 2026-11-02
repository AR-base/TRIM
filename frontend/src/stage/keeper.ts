/**
 * The Keeper: Trim drawn as a character on the sign-in page.
 *
 * A dark bronze bust with one line of light for eyes, a halo ring behind it, and the example agent's
 * permissions as keys on the ring. A few seconds after load, the keys the agent never used fall away
 * and the ones it used turn blue. The head follows the pointer and blinks.
 *
 * Loaded with a dynamic import from SignIn, so three.js never reaches the dashboard bundle.
 */
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { mergeVertices } from "three/addons/utils/BufferGeometryUtils.js";

export interface KeySpec {
  scope: string;
  kept: boolean;
}

export interface KeeperOptions {
  keys: KeySpec[];
  reducedMotion: boolean;
  /** Called after the first frame is drawn. */
  onReady?: () => void;
  /** Called if the GPU context is lost, so the page can show its still version. */
  onLost?: () => void;
}

const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

const BG = 0x050608;
const RING_R = 1.32;
const TRIM_AT = 2.4; // seconds after mount when the unused keys start to fall

/** Gives a smooth surface a faint hammered, cast-bronze texture. */
function sculpt(geo: THREE.BufferGeometry, amount: number): THREE.BufferGeometry {
  geo.deleteAttribute("uv");
  geo.deleteAttribute("normal");
  const g = mergeVertices(geo, 1e-4);
  g.computeVertexNormals();
  const p = g.getAttribute("position") as THREE.BufferAttribute;
  const n = g.getAttribute("normal") as THREE.BufferAttribute;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
    const d =
      amount *
      (Math.sin(x * 7.1 + y * 3.3) * Math.sin(z * 5.3 + y * 2.1) * 0.6 +
        Math.sin(x * 19 + z * 3) * Math.sin(y * 17 + z * 4) * 0.4);
    p.setXYZ(i, x + n.getX(i) * d, y + n.getY(i) * d, z + n.getZ(i) * d);
  }
  g.computeVertexNormals();
  return g;
}

const lathe = (pts: [number, number][]) => new THREE.LatheGeometry(pts.map(([r, y]) => new THREE.Vector2(r, y)), 128);

export function mountKeeper(canvas: HTMLCanvasElement, labels: HTMLElement, opts: KeeperOptions): () => void {
  const host = canvas.parentElement ?? canvas;
  const reduced = opts.reducedMotion;

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(BG);
  scene.fog = new THREE.Fog(BG, 7, 15);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTexture = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
  scene.environment = envTexture;

  const camera = new THREE.PerspectiveCamera(26, 1, 0.1, 60);

  // ---------- the bust ----------
  const bronze = new THREE.MeshPhysicalMaterial({
    color: 0x1c1510, metalness: 1, roughness: 0.42, clearcoat: 0.35, clearcoatRoughness: 0.35, envMapIntensity: 0.16,
  });
  const glassBlack = new THREE.MeshPhysicalMaterial({
    color: 0x020203, metalness: 0.3, roughness: 0.08, clearcoat: 1, clearcoatRoughness: 0.05, envMapIntensity: 0.35,
    side: THREE.DoubleSide,
  });

  const rig = new THREE.Group();
  scene.add(rig);
  const bust = new THREE.Group();
  rig.add(bust);

  const shoulders = new THREE.Mesh(
    sculpt(lathe([[0, -1.66], [0.9, -1.66], [1.02, -1.55], [1.06, -1.32], [1, -1.08], [0.83, -0.92], [0.52, -0.8], [0.32, -0.72], [0, -0.69]]), 0.014),
    bronze,
  );
  shoulders.scale.set(1.42, 1, 0.64);
  bust.add(shoulders);

  const neck = new THREE.Mesh(sculpt(new THREE.CylinderGeometry(0.2, 0.25, 0.6, 64, 8, true), 0.008), bronze);
  neck.position.y = -0.45;
  neck.scale.z = 0.92;
  bust.add(neck);

  const BLUE = new THREE.Color(0.24, 0.42, 1);
  const collarMat = new THREE.MeshBasicMaterial({ color: BLUE.clone().multiplyScalar(2.4) });
  const collar = new THREE.Mesh(new THREE.TorusGeometry(0.262, 0.007, 12, 96), collarMat);
  collar.rotation.x = Math.PI / 2;
  collar.position.y = -0.66;
  bust.add(collar);

  const headPivot = new THREE.Group();
  headPivot.position.y = -0.2;
  bust.add(headPivot);
  const head = new THREE.Mesh(
    sculpt(lathe([[0, -0.1], [0.2, -0.09], [0.33, -0.02], [0.43, 0.1], [0.5, 0.25], [0.53, 0.45], [0.52, 0.65], [0.47, 0.83], [0.37, 0.99], [0.22, 1.1], [0, 1.14]]), 0.012),
    bronze,
  );
  head.scale.set(0.9, 1, 1);
  headPivot.add(head);

  // The visor: a dark glass slot with one line of light.
  const slot = new THREE.Mesh(new THREE.CylinderGeometry(0.533, 0.533, 0.13, 96, 1, true, -1, 2), glassBlack);
  slot.position.y = 0.5;
  head.add(slot);
  const visorColor = new THREE.Color();
  const visorMat = new THREE.MeshBasicMaterial({ color: visorColor, side: THREE.DoubleSide });
  const visor = new THREE.Mesh(new THREE.CylinderGeometry(0.537, 0.537, 0.032, 96, 1, true, -0.82, 1.64), visorMat);
  visor.position.y = 0.5;
  head.add(visor);

  const earMat = new THREE.MeshPhysicalMaterial({ color: 0x121316, metalness: 1, roughness: 0.25, envMapIntensity: 0.3 });
  const earDotMat = new THREE.MeshBasicMaterial({ color: BLUE.clone().multiplyScalar(3) });
  for (const s of [-1, 1]) {
    const ear = new THREE.Mesh(new THREE.TorusGeometry(0.085, 0.017, 16, 64), earMat);
    ear.position.set(s * 0.472, 0.46, 0);
    ear.rotation.y = Math.PI / 2;
    headPivot.add(ear);
    const dot = new THREE.Mesh(new THREE.SphereGeometry(0.022, 16, 16), earDotMat);
    dot.position.set(s * 0.488, 0.46, 0);
    headPivot.add(dot);
  }

  // ---------- halo, light, keys ----------
  const ringCenter = new THREE.Vector3(0, 0.36, -0.78);
  const ringMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(), transparent: true });
  const ring = new THREE.Mesh(new THREE.TorusGeometry(RING_R, 0.021, 24, 320), ringMat);
  ring.position.copy(ringCenter);
  rig.add(ring);
  const haloLight = new THREE.PointLight(0xffffff, 0, 4, 2);
  haloLight.position.copy(ringCenter).add(new THREE.Vector3(0, 0.1, 0.15));
  rig.add(haloLight);

  const keyLight = new THREE.DirectionalLight(0xffb98a, 0.9);
  keyLight.position.set(-3, 3, 4);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0x9fb7ff, 1.3);
  rimLight.position.set(3.5, 2, -3);
  scene.add(rimLight);
  scene.add(new THREE.AmbientLight(0xffffff, 0.05));

  const keysGroup = new THREE.Group();
  keysGroup.position.copy(ringCenter);
  rig.add(keysGroup);
  const keyGeo = new RoundedBoxGeometry(0.2, 0.072, 0.034, 3, 0.03);
  const WHITE = new THREE.Color(1, 1, 1);
  let cutIndex = 0;
  const keys = opts.keys.map((spec, i) => {
    const mat = new THREE.MeshStandardMaterial({
      color: 0x0b0c0f, metalness: 0.6, roughness: 0.35, emissive: WHITE.clone(), emissiveIntensity: 1, transparent: true,
    });
    const mesh = new THREE.Mesh(keyGeo, mat);
    keysGroup.add(mesh);
    const el = document.createElement("span");
    el.className = "keeper__label";
    el.textContent = spec.scope;
    labels.appendChild(el);
    // Spread the keys over the upper arc of the halo so their labels stay clear of the bust.
    const a0 = Math.PI * (0.22 + (0.6 * i) / Math.max(1, opts.keys.length - 1));
    return { mesh, mat, el, kept: spec.kept, a0, order: spec.kept ? 0 : cutIndex++ };
  });

  // ---------- post-processing ----------
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.42, 0.18, 1.2);
  composer.addPass(bloom);
  composer.addPass(new OutputPass());

  let W = 1, H = 1;
  function resize() {
    W = Math.max(1, host.clientWidth);
    H = Math.max(1, host.clientHeight);
    renderer.setSize(W, H, false);
    composer.setSize(W, H);
    bloom.resolution.set(W, H);
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(host);
  resize();

  // ---------- behaviour ----------
  const pointer = { x: 0, y: 0 };
  const onPointer = (e: PointerEvent) => {
    pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
    pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
  };
  window.addEventListener("pointermove", onPointer, { passive: true });

  const clock = new THREE.Clock();
  let blinkAt = -1, nextBlink = 3.2, nodAt = -9;
  let headScreen = { x: -1e4, y: -1e4 };
  const onClick = (e: MouseEvent) => {
    const r = canvas.getBoundingClientRect();
    if (Math.hypot(e.clientX - r.left - headScreen.x, e.clientY - r.top - headScreen.y) < 120) {
      blinkAt = clock.elapsedTime;
      nodAt = clock.elapsedTime;
    }
  };
  host.addEventListener("click", onClick);

  const v = new THREE.Vector3();
  const cs = { x: 0, y: 0 };
  const VISOR = new THREE.Color(0.78, 0.86, 1);
  let yaw = -0.3, pitch = 0.04, raf = 0, ready = false;

  function place(el: HTMLElement, obj: THREE.Object3D, opacity: number, push: number) {
    v.setFromMatrixPosition(obj.matrixWorld).project(camera);
    let x = (v.x * 0.5 + 0.5) * W, y = (-v.y * 0.5 + 0.5) * H;
    const dx = x - cs.x, dy = y - cs.y, len = Math.hypot(dx, dy) || 1;
    x += (dx / len) * push;
    y += (dy / len) * push;
    // keep the whole label on the stage
    const half = (el.offsetWidth || 120) / 2 + 10;
    x = Math.min(Math.max(x, half), W - half);
    const o = opacity * clamp((y - 16) / 30) * clamp((H - 16 - y) / 30);
    if (o < 0.02) {
      el.style.visibility = "hidden";
      return;
    }
    el.style.visibility = "visible";
    el.style.opacity = o.toFixed(3);
    el.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px) translate(-50%,-50%)`;
  }

  function frame() {
    raf = requestAnimationFrame(frame);
    if (document.hidden) return;
    const dt = Math.min(clock.getDelta(), 0.05);
    const t = reduced ? 99 : clock.elapsedTime;

    // framing: the bust a little right of centre on wide stages, centred on narrow ones
    const narrow = camera.aspect < 0.9;
    const d = narrow ? 8.2 : 6.9;
    const halfH = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * d;
    rig.position.x = narrow ? 0 : 0.05 * halfH * camera.aspect;
    rig.position.y = (narrow ? 0.18 : -0.04) * halfH + (reduced ? 0 : Math.sin(t * 1.1) * 0.012);
    camera.position.set(0, 0.18, d);
    camera.lookAt(0, 0.12, 0);

    // wake-up: the halo draws in, then the visor flickers on
    const wake = easeOut(clamp((t - 0.2) / 1.8));
    const visorOn = t > 1.6 ? 1 : t > 1.25 ? (Math.sin(t * 95) > 0 ? 1 : 0.12) : 0;

    // head pose
    let targetYaw = -0.3 + pointer.x * 0.35;
    let targetPitch = 0.04 + pointer.y * 0.12;
    const tn = t - nodAt;
    if (!reduced && tn > 0 && tn < 1.2) targetPitch += Math.sin((tn * Math.PI) / 0.6) * 0.12 * Math.exp(-tn * 2.5);
    if (reduced) {
      targetYaw = -0.3;
      targetPitch = 0.04;
    }
    const k = reduced ? 1 : 1 - Math.exp(-dt * 4);
    yaw += (targetYaw - yaw) * k;
    pitch += (targetPitch - pitch) * k;
    headPivot.rotation.set(pitch, yaw, 0);
    bust.rotation.y = yaw * 0.28;

    // blink
    if (!reduced && t > nextBlink) {
      blinkAt = t;
      nextBlink = t + 2.6 + Math.random() * 3.6;
    }
    const bt = (t - blinkAt) / 0.17;
    visor.scale.y = bt >= 0 && bt <= 1 ? 1 - 0.88 * Math.sin(Math.PI * bt) : 1;
    visorColor.copy(VISOR).multiplyScalar(3.8 * visorOn);

    // halo
    ring.scale.setScalar(0.84 + 0.16 * wake);
    ringMat.color.setRGB(1, 1, 1).multiplyScalar(2.2 * wake);
    ringMat.opacity = wake;
    haloLight.intensity = 2.2 * wake;
    collarMat.color.copy(BLUE).multiplyScalar(2.4 * visorOn);

    // keys
    rig.updateMatrixWorld();
    v.copy(ringCenter);
    rig.localToWorld(v);
    v.project(camera);
    cs.x = (v.x * 0.5 + 0.5) * W;
    cs.y = (-v.y * 0.5 + 0.5) * H;
    const show = easeOut(clamp((t - 0.9) / 1.0));
    const blueMix = easeInOut(clamp((t - TRIM_AT) / 1.0));
    for (const key of keys) {
      let x = Math.cos(key.a0) * RING_R, y = Math.sin(key.a0) * RING_R, z = 0.02, rot = 0, op = show, f = 0;
      if (!key.kept) {
        f = clamp((t - TRIM_AT - 0.35 * key.order) / 1.1);
        const g = f * f;
        y -= 2.8 * g;
        x += Math.cos(key.a0) * 0.5 * f;
        z += 0.4 * f;
        rot = f * 4;
        op *= 1 - f;
        key.mat.emissive.copy(WHITE);
        key.mat.emissiveIntensity = 0.9;
      } else {
        key.mat.emissive.copy(WHITE).lerp(BLUE, blueMix);
        key.mat.emissiveIntensity = 0.9 + 2.6 * blueMix;
      }
      key.mesh.position.set(x, y, z);
      key.mesh.rotation.set(rot, rot * 0.6, key.a0 + Math.PI / 2);
      key.mesh.scale.setScalar(Math.max(0.001, show));
      key.mat.opacity = op;
      key.mesh.visible = op > 0.01;
      key.mesh.updateMatrixWorld();
      key.el.classList.toggle("keeper__label--kept", key.kept && blueMix > 0.5);
      key.el.classList.toggle("keeper__label--cut", !key.kept && t > TRIM_AT);
      place(key.el, key.mesh, key.kept ? show : show * (1 - f * 0.55), narrow ? 26 : 36);
    }

    v.set(0, 0.5, 0);
    headPivot.localToWorld(v);
    v.project(camera);
    headScreen = { x: (v.x * 0.5 + 0.5) * W, y: (-v.y * 0.5 + 0.5) * H };

    composer.render(dt);
    if (!ready) {
      ready = true;
      opts.onReady?.();
    }
  }

  const onLost = (e: Event) => {
    e.preventDefault();
    cancelAnimationFrame(raf);
    opts.onLost?.();
  };
  canvas.addEventListener("webglcontextlost", onLost);
  frame();

  return () => {
    cancelAnimationFrame(raf);
    ro.disconnect();
    window.removeEventListener("pointermove", onPointer);
    host.removeEventListener("click", onClick);
    canvas.removeEventListener("webglcontextlost", onLost);
    for (const key of keys) key.el.remove();
    scene.traverse((o) => {
      if (o instanceof THREE.Mesh) {
        o.geometry.dispose();
        const m = o.material as THREE.Material | THREE.Material[];
        (Array.isArray(m) ? m : [m]).forEach((mm) => mm.dispose());
      }
    });
    envTexture.dispose();
    pmrem.dispose();
    composer.dispose();
    renderer.dispose();
  };
}
