// Hero animation: a sphere of points that breathes with 3D noise and turns towards the pointer.
// Monochrome, one draw call, paused when off screen; a single still frame for reduced motion.
import * as THREE from "three";

const canvas = document.getElementById("hero-canvas");
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function supportsWebGL() {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

if (canvas && supportsWebGL()) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 0, 6);

  // Points spread evenly over a sphere (Fibonacci lattice).
  const small = window.innerWidth < 720;
  const count = small ? 3200 : 7000;
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const t = golden * i;
    positions.set([Math.cos(t) * r, y, Math.sin(t) * r], i * 3);
    seeds[i] = Math.random();
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("seed", new THREE.BufferAttribute(seeds, 1));

  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uSize: { value: (small ? 2.2 : 2.6) * renderer.getPixelRatio() },
      uRadius: { value: 1.75 },
      uCamDist: { value: 6 },
    },
    vertexShader: /* glsl */ `
      uniform float uTime;
      uniform float uSize;
      uniform float uRadius;
      uniform float uCamDist;
      attribute float seed;
      varying float vAlpha;

      // 3D simplex noise, Ashima Arts / Stefan Gustavson (MIT).
      vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
      vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
      vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
      vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
      float snoise(vec3 v){
        const vec2 C=vec2(1.0/6.0,1.0/3.0); const vec4 D=vec4(0.0,0.5,1.0,2.0);
        vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
        vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.0-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
        vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;
        i=mod289(i);
        vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
        float n_=0.142857142857; vec3 ns=n_*D.wyz-D.xzx;
        vec4 j=p-49.0*floor(p*ns.z*ns.z); vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.0*x_);
        vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.0-abs(x)-abs(y);
        vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
        vec4 s0=floor(b0)*2.0+1.0; vec4 s1=floor(b1)*2.0+1.0; vec4 sh=-step(h,vec4(0.0));
        vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
        vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
        vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
        p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
        vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0); m=m*m;
        return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
      }

      void main(){
        vec3 dir = normalize(position);
        float n = snoise(dir * 1.6 + vec3(0.0, uTime * 0.18, uTime * 0.07));
        float r = uRadius * (1.0 + 0.16 * n) + 0.02 * sin(uTime * 1.5 + seed * 6.2831);
        vec4 mv = modelViewMatrix * vec4(dir * r, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = uSize * (0.6 + 0.6 * seed) * (uCamDist / -mv.z);
        // Points on the far side fade out, so the sphere reads in depth (relative to the camera distance).
        vAlpha = smoothstep(-(uCamDist + 1.8), -(uCamDist - 1.6), mv.z) * (0.35 + 0.65 * (n * 0.5 + 0.5));
      }
    `,
    fragmentShader: /* glsl */ `
      varying float vAlpha;
      void main(){
        float d = length(gl_PointCoord - 0.5);
        if (d > 0.5) discard;
        float soft = smoothstep(0.5, 0.0, d);
        gl_FragColor = vec4(vec3(0.92), soft * vAlpha * 0.85);
      }
    `,
  });
  const sphere = new THREE.Points(geometry, material);

  // Two thin orbits in grey add a sense of scale without colour.
  const group = new THREE.Group();
  group.add(sphere);
  const ringMat = new THREE.LineBasicMaterial({ color: 0x5a5a5a, transparent: true, opacity: 0.35 });
  for (const [radius, tilt] of [[2.45, 1.15], [2.85, -0.55]]) {
    const pts = [];
    for (let i = 0; i <= 192; i++) {
      const a = (i / 192) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
    }
    const ring = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), ringMat);
    ring.rotation.x = tilt;
    ring.rotation.z = tilt * 0.4;
    group.add(ring);
  }
  scene.add(group);

  function resize() {
    const { clientWidth: w, clientHeight: h } = canvas;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // Wide screens: the sphere sits to the right of the text. Narrow screens: centred and further back.
    camera.position.z = w < 720 ? 8.2 : 6.4;
    material.uniforms.uCamDist.value = camera.position.z;
    group.position.x = w >= 960 ? 2.1 : 0;
    canvas.dataset.layout = w >= 960 ? "side" : "behind";
    camera.updateProjectionMatrix();
  }
  resize();
  window.addEventListener("resize", resize);

  const pointer = { x: 0, y: 0 };
  window.addEventListener("pointermove", (e) => {
    pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
    pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
  });

  let visible = true;
  new IntersectionObserver(([entry]) => (visible = entry.isIntersecting)).observe(canvas);

  const clock = new THREE.Clock();
  function frame() {
    const t = clock.getElapsedTime();
    material.uniforms.uTime.value = t;
    group.rotation.y += (pointer.x * 0.5 + t * 0.06 - group.rotation.y) * 0.04;
    group.rotation.x += (pointer.y * 0.3 - group.rotation.x) * 0.04;
    // Drift up and fade a little as the page scrolls past the hero.
    const s = Math.min(window.scrollY / window.innerHeight, 1);
    group.position.y = s * 1.2;
    const base = canvas.dataset.layout === "behind" ? 0.55 : 1; // dimmer when it sits behind the text
    canvas.style.opacity = String(base * (1 - s * 0.7));
    renderer.render(scene, camera);
  }

  if (reduceMotion) {
    material.uniforms.uTime.value = 4;
    renderer.render(scene, camera);
  } else {
    renderer.setAnimationLoop(() => visible && frame());
  }
  document.documentElement.classList.add("has-3d");
}
