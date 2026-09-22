/**
 * Le réacteur : un quad plein écran piloté par un shader.
 *
 * Pas de géométrie, pas de modèle 3D — tout est calculé par pixel. C'est ce
 * qui permet de tenir 60 fps en arrière-plan sans peser sur l'inférence, qui
 * partage le même GPU. Trois uniformes suffisent : le temps, l'énergie
 * (niveau sonore ou activité), et l'état courant.
 */
import * as THREE from "three";

const vertex = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position, 1.0);
  }
`;

const fragment = /* glsl */ `
  precision highp float;
  varying vec2 vUv;

  uniform float uTime;
  uniform float uEnergy;   // 0..1
  uniform float uState;    // 0 repos · 1 écoute · 2 réflexion · 3 parole
  uniform vec2  uRes;

  const float TAU = 6.28318530718;

  // Bruit de valeur, pour faire respirer la lueur sans qu'elle scintille.
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x),
               mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
  }

  vec3 palette(float s) {
    vec3 idle   = vec3(0.16, 0.55, 0.78);
    vec3 listen = vec3(0.27, 0.85, 1.00);
    vec3 think  = vec3(1.00, 0.71, 0.28);
    vec3 speak  = vec3(0.49, 1.00, 0.77);
    vec3 c = mix(idle, listen, clamp(s, 0.0, 1.0));
    c = mix(c, think, clamp(s - 1.0, 0.0, 1.0));
    c = mix(c, speak, clamp(s - 2.0, 0.0, 1.0));
    return c;
  }

  void main() {
    vec2 uv = (vUv - 0.5) * vec2(uRes.x / uRes.y, 1.0);
    float r = length(uv);
    float a = atan(uv.y, uv.x);

    float pulse = 0.5 + 0.5 * sin(uTime * 1.3);
    float energy = clamp(uEnergy, 0.0, 1.0);
    vec3 tint = palette(uState);

    // Coeur : un noyau doux qui enfle avec l'énergie.
    float core = smoothstep(0.30 + 0.05 * energy, 0.0, r);
    core = pow(core, 2.2) * (0.35 + 0.65 * energy);

    // Anneaux concentriques, décalés pour éviter l'effet stroboscopique.
    float rings = 0.0;
    for (int i = 0; i < 5; i++) {
      float fi = float(i);
      float radius = 0.16 + fi * 0.075 + 0.012 * sin(uTime * (0.6 + fi * 0.17) + fi);
      float width = 0.0022 + 0.0016 * energy;
      rings += width / max(abs(r - radius), 0.0012) * (1.0 - fi * 0.14);
    }
    rings *= 0.14 * (0.45 + 0.55 * energy);

    // Arc qui balaie l'anneau : la seule chose qui tourne, donc la seule
    // qui donne le sentiment que le système travaille.
    float sweepSpeed = 0.35 + 0.9 * energy + 0.5 * step(1.5, uState);
    float sweep = fract((a / TAU) + uTime * sweepSpeed);
    float arc = smoothstep(0.0, 0.16, sweep) * smoothstep(0.30, 0.16, sweep);
    arc *= smoothstep(0.55, 0.40, r) * smoothstep(0.30, 0.40, r);

    // Grain léger : sans lui l'aplat numérique se voit sur les grands écrans.
    float grain = noise(vUv * uRes * 0.35 + uTime * 8.0) * 0.022;

    float halo = exp(-r * 2.6) * 0.10 * (0.5 + 0.5 * pulse);
    vec3 col = tint * (core + rings + arc * 0.75 + halo) + grain;

    // Vignette : ramène l'oeil au centre et laisse respirer les panneaux.
    col *= 1.0 - smoothstep(0.35, 1.05, r) * 0.85;

    gl_FragColor = vec4(col, 1.0);
  }
`;

export class Reactor {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  private uniforms;
  private energy = 0;
  private target = 0;
  private clock = new THREE.Clock();

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    this.uniforms = {
      uTime: { value: 0 },
      uEnergy: { value: 0 },
      uState: { value: 0 },
      uRes: { value: new THREE.Vector2(1, 1) },
    };

    this.scene.add(
      new THREE.Mesh(
        new THREE.PlaneGeometry(2, 2),
        new THREE.ShaderMaterial({ vertexShader: vertex, fragmentShader: fragment, uniforms: this.uniforms }),
      ),
    );

    this.resize();
    window.addEventListener("resize", () => this.resize());
    this.loop();
  }

  /** 0 repos · 1 écoute · 2 réflexion · 3 parole */
  setState(state: number) {
    this.uniforms.uState.value = state;
    this.target = state === 0 ? 0.12 : state === 1 ? 0.5 : state === 2 ? 0.75 : 1.0;
  }

  /** Impulsion ponctuelle — un mot transcrit, un outil appelé. */
  pulse(amount = 0.4) {
    this.energy = Math.min(1, this.energy + amount);
  }

  private resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.uniforms.uRes.value.set(w, h);
  }

  private loop = () => {
    // Lissage exponentiel : l'énergie monte vite et retombe lentement, sinon
    // l'anneau clignote à chaque événement au lieu de respirer.
    this.energy += (this.target - this.energy) * 0.045;
    this.uniforms.uEnergy.value = this.energy;
    this.uniforms.uTime.value = this.clock.getElapsedTime();
    this.renderer.render(this.scene, this.camera);
    requestAnimationFrame(this.loop);
  };
}
