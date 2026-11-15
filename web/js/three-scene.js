/* ===================================================================
   ICT TERMINAL PRO — HERO 3D ENGINE
   Procedural WebGL scene (Three.js): market "liquidity skyline",
   wireframe core, orbital geometry, particle field.
   Gracefully degrades when WebGL or the CDN is unavailable.
   =================================================================== */
(function () {
  'use strict';

  var canvas = document.getElementById('heroCanvas');
  var hero = document.getElementById('hero');
  if (!canvas || !hero) return;

  var root = document.documentElement;
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var isMobile = window.matchMedia('(max-width: 860px)').matches;
  var THREE = window.THREE;

  if (!THREE) {
    root.classList.add('no-webgl');
    return;
  }

  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas: canvas,
      antialias: !isMobile,
      alpha: true,
      powerPreference: 'high-performance'
    });
  } catch (err) {
    root.classList.add('no-webgl');
    return;
  }

  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isMobile ? 1.4 : 1.6));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;

  var scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x05060a, 0.026);

  var camera = new THREE.PerspectiveCamera(42, 1, 0.1, 120);
  camera.position.set(0, 0.9, 17);

  var world = new THREE.Group();
  scene.add(world);

  /* ---------------------------------------------------------------
     Lights
     --------------------------------------------------------------- */
  scene.add(new THREE.AmbientLight(0x24334a, 1.2));

  var keyLight = new THREE.DirectionalLight(0xbfe9ff, 1);
  keyLight.position.set(6, 9, 7);
  scene.add(keyLight);

  var cyanLight = new THREE.PointLight(0x6ff2ff, 24, 44, 2);
  cyanLight.position.set(-7, 3.5, 6);
  scene.add(cyanLight);

  var violetLight = new THREE.PointLight(0x9a7bff, 28, 46, 2);
  violetLight.position.set(7, -4, 4);
  scene.add(violetLight);

  /* ---------------------------------------------------------------
     Procedural market skyline
     --------------------------------------------------------------- */
  var COLS = isMobile ? 16 : 27;
  var ROWS = isMobile ? 11 : 19;
  var GAP = 0.62;
  var COUNT = COLS * ROWS;

  var cellGeo = new THREE.BoxGeometry(0.23, 1, 0.23, 1, 1, 1);
  cellGeo.translate(0, 0.5, 0);

  var cellMat = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0.58,
    fog: true
  });

  var field = new THREE.InstancedMesh(cellGeo, cellMat, COUNT);
  field.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

  var dummy = new THREE.Object3D();
  var color = new THREE.Color();
  var cyan = new THREE.Color(0x6ff2ff);
  var deep = new THREE.Color(0x0b3c55);
  var violet = new THREE.Color(0x7d66e8);

  var baseHeights = new Float32Array(COUNT);
  var phase = new Float32Array(COUNT);

  for (var i = 0; i < COLS; i++) {
    for (var j = 0; j < ROWS; j++) {
      var id = i * ROWS + j;
      var x = i - (COLS - 1) / 2;
      var z = j - (ROWS - 1) / 2;
      var h = 0.3 +
        Math.abs(Math.sin(x * 0.42 + z * 0.28) * Math.cos(z * 0.47 - x * 0.19)) * 1.75 +
        Math.abs(Math.sin((x + z) * 0.17)) * 0.85;
      baseHeights[id] = h;
      phase[id] = (x * 0.34 + z * 0.57);

      dummy.position.set(x * GAP, 0, z * GAP);
      dummy.scale.set(1, h, 1);
      dummy.rotation.y = 0;
      dummy.updateMatrix();
      field.setMatrixAt(id, dummy.matrix);

      if ((i + j) % 11 === 0) {
        color.copy(violet).lerp(cyan, 0.15 + (h / 4) * 0.35);
        color.multiplyScalar(0.42);
      } else {
        color.copy(deep).lerp(cyan, Math.min(0.9, 0.1 + (h / 4) * 0.7));
        color.multiplyScalar(0.4 + (h / 5) * 0.3);
      }
      field.setColorAt(id, color);
    }
  }

  field.instanceColor.needsUpdate = true;
  field.rotation.x = 0;
  world.add(field);

  var fieldTilt = new THREE.Group();
  fieldTilt.rotation.x = -0.5;
  fieldTilt.position.set(0, -0.4, -2);
  world.add(fieldTilt);
  fieldTilt.add(field);
  field.position.set(0, -4.1, 0);

  /* ---------------------------------------------------------------
     Central core
     --------------------------------------------------------------- */
  var core = new THREE.Group();
  core.position.set(0, 0.9, -1.4);
  world.add(core);

  var inner = new THREE.Mesh(
    new THREE.SphereGeometry(1.95, 48, 48),
    new THREE.MeshStandardMaterial({
      color: 0x05080f,
      metalness: 0.95,
      roughness: 0.22,
      emissive: 0x061a2a,
      emissiveIntensity: 0.6
    })
  );
  core.add(inner);

  var wire = new THREE.Mesh(
    new THREE.IcosahedronGeometry(2.9, 1),
    new THREE.MeshBasicMaterial({
      color: 0x6ff2ff,
      wireframe: true,
      transparent: true,
      opacity: 0.14
    })
  );
  core.add(wire);

  var ringA = new THREE.Mesh(
    new THREE.TorusGeometry(3.95, 0.01, 6, 180),
    new THREE.MeshBasicMaterial({ color: 0x6ff2ff, transparent: true, opacity: 0.34 })
  );
  ringA.rotation.set(1.34, 0.18, 0);
  core.add(ringA);

  var ringB = new THREE.Mesh(
    new THREE.TorusGeometry(4.85, 0.008, 6, 180),
    new THREE.MeshBasicMaterial({ color: 0x9a7bff, transparent: true, opacity: 0.28 })
  );
  ringB.rotation.set(-1.15, 0.6, 0.4);
  core.add(ringB);

  var orbiters = [];
  var orbGeo = new THREE.OctahedronGeometry(0.1, 0);
  for (var o = 0; o < 7; o++) {
    var orbMat = new THREE.MeshStandardMaterial({
      color: o % 2 ? 0x9a7bff : 0x6ff2ff,
      emissive: o % 2 ? 0x5f43d6 : 0x1fa9c9,
      emissiveIntensity: 1.2,
      metalness: 0.4,
      roughness: 0.3
    });
    var orb = new THREE.Mesh(orbGeo, orbMat);
    orb.userData.angle = (o / 7) * Math.PI * 2;
    orb.userData.radius = 3.55 + (o % 3) * 0.5;
    orb.userData.speed = 0.16 + (o % 4) * 0.035;
    orb.userData.tilt = (o % 2 ? 1 : -1) * 0.55;
    core.add(orb);
    orbiters.push(orb);
  }

  /* ---------------------------------------------------------------
     Particle field
     --------------------------------------------------------------- */
  function makeParticles(count, colorHex, size, spread, opacity) {
    var positions = new Float32Array(count * 3);
    for (var p = 0; p < count; p++) {
      var r = spread * (0.45 + Math.random() * 0.55);
      var theta = Math.random() * Math.PI * 2;
      var phi = Math.acos(2 * Math.random() - 1);
      positions[p * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[p * 3 + 1] = r * Math.cos(phi) * 0.55;
      positions[p * 3 + 2] = r * Math.sin(phi) * Math.sin(theta) * 0.7;
    }
    var geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    var mat = new THREE.PointsMaterial({
      color: colorHex,
      size: size,
      sizeAttenuation: true,
      transparent: true,
      opacity: opacity,
      depthWrite: false,
      blending: THREE.AdditiveBlending
    });
    var points = new THREE.Points(geo, mat);
    world.add(points);
    return points;
  }

  var particles = makeParticles(isMobile ? 300 : 820, 0x9fe9ff, 0.04, 26, 0.45);
  var particlesB = makeParticles(isMobile ? 110 : 280, 0xa892ff, 0.065, 24, 0.3);

  /* ---------------------------------------------------------------
     Interaction state
     --------------------------------------------------------------- */
  var pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  var scrollProgress = 0;
  var running = false;
  var visible = true;
  var rafId = 0;
  var clock = new THREE.Clock();

  function onPointerMove(e) {
    pointer.tx = (e.clientX / window.innerWidth) * 2 - 1;
    pointer.ty = (e.clientY / window.innerHeight) * 2 - 1;
  }

  function onScroll() {
    var h = hero.offsetHeight || 1;
    scrollProgress = Math.min(1, Math.max(0, window.pageYOffset / h));
  }

  function resize() {
    var w = hero.clientWidth || window.innerWidth;
    var h = hero.clientHeight || window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (!running) renderFrame(0);
  }

  function renderFrame(dt) {
    var t = clock.elapsedTime;

    pointer.x += (pointer.tx - pointer.x) * Math.min(1, dt * 3.2);
    pointer.y += (pointer.ty - pointer.y) * Math.min(1, dt * 3.2);

    camera.position.x = pointer.x * 0.9;
    camera.position.y = 0.9 - pointer.y * 0.6 + scrollProgress * 0.8;
    camera.position.z = 17 + scrollProgress * 5.5;
    camera.lookAt(0, 0.1 - scrollProgress * 0.6, 0);

    world.rotation.y = pointer.x * 0.14;
    world.rotation.x = -pointer.y * 0.04;

    core.rotation.y = t * 0.055 + pointer.x * 0.12;
    core.rotation.x = Math.sin(t * 0.22) * 0.05;
    core.position.y = 0.9 + Math.sin(t * 0.6) * 0.08 - scrollProgress * 1.2;

    wire.rotation.y = -t * 0.1;
    wire.rotation.z = t * 0.04;
    ringA.rotation.z = t * 0.09;
    ringB.rotation.z = -t * 0.065;

    for (var k = 0; k < orbiters.length; k++) {
      var ob = orbiters[k];
      var a = ob.userData.angle + t * ob.userData.speed;
      ob.position.set(
        Math.cos(a) * ob.userData.radius,
        Math.sin(a * 1.3) * ob.userData.tilt,
        Math.sin(a) * ob.userData.radius
      );
      ob.rotation.y = t * 0.8;
      ob.rotation.x = t * 0.5;
    }

    // breathing skyline
    for (var m = 0; m < COUNT; m++) {
      var breathe = Math.sin(t * 0.55 + phase[m] * 1.6) * 0.24;
      dummy.position.set(
        (Math.floor(m / ROWS) - (COLS - 1) / 2) * GAP,
        0,
        ((m % ROWS) - (ROWS - 1) / 2) * GAP
      );
      dummy.scale.set(1, Math.max(0.12, baseHeights[m] + breathe), 1);
      dummy.updateMatrix();
      field.setMatrixAt(m, dummy.matrix);
    }
    field.instanceMatrix.needsUpdate = true;

    particles.rotation.y = t * 0.018 + pointer.x * 0.05;
    particlesB.rotation.y = -t * 0.014 - pointer.x * 0.04;

    field.position.y = -4.1 - scrollProgress * 0.9;
    renderer.render(scene, camera);
  }

  function loop() {
    rafId = requestAnimationFrame(loop);
    var dt = Math.min(0.05, clock.getDelta());
    renderFrame(dt);
  }

  function start() {
    if (running || reduceMotion) return;
    running = true;
    clock.getDelta();
    loop();
  }

  function stop() {
    running = false;
    if (rafId) cancelAnimationFrame(rafId);
    rafId = 0;
  }

  /* ---------------------------------------------------------------
     Observers & listeners
     --------------------------------------------------------------- */
  window.addEventListener('resize', resize, { passive: true });
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('pointermove', onPointerMove, { passive: true });

  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        visible = entry.isIntersecting;
        if (visible && !document.hidden) start();
        else stop();
      });
    }, { threshold: 0.02 }).observe(hero);
  } else {
    visible = true;
    start();
  }

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stop();
    else if (visible) start();
  });

  canvas.addEventListener('webglcontextlost', function (e) {
    e.preventDefault();
    stop();
    root.classList.add('no-webgl');
  });

  resize();
  onScroll();

  if (reduceMotion) {
    renderFrame(0);
    window.addEventListener('resize', function () { renderFrame(0); }, { passive: true });
    window.addEventListener('scroll', function () { onScroll(); renderFrame(0); }, { passive: true });
  } else {
    start();
  }
})();
