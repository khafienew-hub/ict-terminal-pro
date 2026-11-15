/* ===================================================================
   ICT TERMINAL PRO — MOTION & INTERACTION LAYER
   Preloader, custom cursor, magnetic buttons, scroll reveals,
   Lenis smooth scroll, GSAP scroll storytelling, menu overlay.
   All enhancements degrade gracefully without third-party libs.
   =================================================================== */
(function () {
  'use strict';

  var root = document.documentElement;
  var body = document.body;
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  var header = document.getElementById('siteHeader');
  var headerH = header ? header.offsetHeight : 76;

  /* ---------------------------------------------------------------
     01. PRELOADER
     --------------------------------------------------------------- */
  (function preloader() {
    var pre = document.getElementById('preloader');
    var bar = document.getElementById('preloaderBar');
    var count = document.getElementById('preloaderCount');
    var finished = false;
    var start = performance.now();
    var duration = reduceMotion ? 260 : 1500;

    function finish() {
      if (finished) return;
      finished = true;
      body.classList.remove('is-loading');
      body.classList.add('is-ready');
      if (pre) {
        pre.classList.add('is-done');
        pre.setAttribute('aria-hidden', 'true');
        window.setTimeout(function () {
          pre.style.display = 'none';
        }, 800);
      }
      window.setTimeout(refreshScrollTriggers, 120);
    }

    function tick(now) {
      var t = Math.min(1, (now - start) / duration);
      var eased = 1 - Math.pow(1 - t, 3);
      var value = Math.round(eased * 100);
      if (bar) bar.style.width = value + '%';
      if (count) count.textContent = value < 10 ? '00' + value : value < 100 ? '0' + value : String(value);
      if (t < 1) window.requestAnimationFrame(tick);
      else finish();
    }

    window.requestAnimationFrame(tick);
    window.setTimeout(finish, 3600);

    if (document.readyState === 'complete') {
      finish();
    }
  })();

  /* ---------------------------------------------------------------
     02. CUSTOM CURSOR
     --------------------------------------------------------------- */
  (function cursor() {
    if (!finePointer || reduceMotion) return;

    var dot = document.getElementById('cursorDot');
    var ring = document.getElementById('cursorRing');
    if (!dot || !ring) return;

    body.classList.add('has-pointer');

    var mx = window.innerWidth / 2;
    var my = window.innerHeight / 2;
    var rx = mx;
    var ry = my;
    var tickId = 0;

    function render() {
      rx += (mx - rx) * 0.16;
      ry += (my - ry) * 0.16;
      dot.style.transform = 'translate3d(' + mx + 'px,' + my + 'px,0) translate(-50%,-50%)';
      ring.style.transform = 'translate3d(' + rx + 'px,' + ry + 'px,0) translate(-50%,-50%)';
      tickId = window.requestAnimationFrame(render);
    }

    window.addEventListener('pointermove', function (e) {
      mx = e.clientX;
      my = e.clientY;
      var target = e.target.closest('a, button, [data-cursor], input, .proof-card, .pillar, .cap-row');
      ring.classList.toggle('is-hover', !!target);
      ring.classList.toggle('is-view', !!(target && target.getAttribute && target.getAttribute('data-cursor') === 'view'));
      dot.style.opacity = '1';
      ring.style.opacity = '1';
    }, { passive: true });

    document.addEventListener('pointerleave', function () {
      dot.style.opacity = '0';
      ring.style.opacity = '0';
    });

    render();
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        window.cancelAnimationFrame(tickId);
      } else {
        tickId = window.requestAnimationFrame(render);
      }
    });
  })();

  /* ---------------------------------------------------------------
     03. REVEALS
     --------------------------------------------------------------- */
  (function reveals() {
    // Large headings get reveal treatment automatically
    document.querySelectorAll('[data-split]').forEach(function (el) {
      if (el.classList.contains('hero-title')) return;
      el.classList.add('reveal');
    });

    var items = Array.prototype.slice.call(document.querySelectorAll('.reveal'));
    if (!items.length) return;

    if (!('IntersectionObserver' in window) || reduceMotion) {
      items.forEach(function (el) { el.classList.add('is-in'); });
      return;
    }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        var siblings = el.parentElement ? Array.prototype.slice.call(el.parentElement.children) : [];
        var index = siblings.indexOf(el);
        if (index > 0 && !el.style.getPropertyValue('--delay')) {
          el.style.setProperty('--delay', Math.min(index, 5) * 70 + 'ms');
        }
        el.classList.add('is-in');
        io.unobserve(el);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });

    items.forEach(function (el) { io.observe(el); });

    // Safety net: never leave content invisible
    window.setTimeout(function () {
      items.forEach(function (el) {
        if (!el.classList.contains('is-in') && el.getBoundingClientRect().top < window.innerHeight) {
          el.classList.add('is-in');
        }
      });
    }, 4000);
  })();

  /* ---------------------------------------------------------------
     04. MAGNETIC BUTTONS + TILT
     --------------------------------------------------------------- */
  if (finePointer && !reduceMotion) {
    document.querySelectorAll('[data-magnetic]').forEach(function (el) {
      var strength = 0.22;
      el.addEventListener('pointermove', function (e) {
        var r = el.getBoundingClientRect();
        var x = (e.clientX - r.left - r.width / 2) * strength;
        var y = (e.clientY - r.top - r.height / 2) * strength;
        el.style.transition = 'transform .12s linear';
        el.style.transform = 'translate3d(' + x.toFixed(2) + 'px,' + y.toFixed(2) + 'px,0)';
      });
      el.addEventListener('pointerleave', function () {
        el.style.transition = 'transform .5s cubic-bezier(.16,1,.3,1)';
        el.style.transform = '';
      });
    });

    document.querySelectorAll('[data-tilt]').forEach(function (el) {
      var max = parseFloat(el.getAttribute('data-tilt-max')) || 4;
      var rafId = 0;
      var tx = 0;
      var ty = 0;
      var cx = 0;
      var cy = 0;

      function apply() {
        cx += (tx - cx) * 0.12;
        cy += (ty - cy) * 0.12;
        el.style.transform = 'perspective(1400px) rotateX(' + cy.toFixed(2) + 'deg) rotateY(' + cx.toFixed(2) + 'deg)';
        if (Math.abs(cx - tx) > 0.01 || Math.abs(cy - ty) > 0.01) {
          rafId = window.requestAnimationFrame(apply);
        } else {
          rafId = 0;
        }
      }

      el.addEventListener('pointermove', function (e) {
        var r = el.getBoundingClientRect();
        var px = (e.clientX - r.left) / r.width - 0.5;
        var py = (e.clientY - r.top) / r.height - 0.5;
        tx = px * max;
        ty = -py * max;
        if (!rafId) rafId = window.requestAnimationFrame(apply);
      });

      el.addEventListener('pointerleave', function () {
        tx = 0;
        ty = 0;
        if (!rafId) rafId = window.requestAnimationFrame(apply);
      });
    });
  }

  /* ---------------------------------------------------------------
     05. HEADER / SCROLL PROGRESS / ACTIVE NAV
     --------------------------------------------------------------- */
  (function scrollChrome() {
    var progress = document.getElementById('scrollProgress');
    var links = Array.prototype.slice.call(document.querySelectorAll('.nav-link'));
    var sections = Array.prototype.slice.call(document.querySelectorAll('section[id]'));

    function onScroll() {
      var y = window.pageYOffset || document.documentElement.scrollTop;
      var max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      if (progress) progress.style.width = Math.min(100, (y / max) * 100) + '%';
      if (header) header.classList.toggle('is-scrolled', y > 24);
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    if ('IntersectionObserver' in window && sections.length) {
      var spy = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var id = '#' + entry.target.id;
          links.forEach(function (link) {
            link.classList.toggle('active', link.getAttribute('href') === id);
          });
        });
      }, { rootMargin: '-45% 0px -45% 0px', threshold: 0 });

      sections.forEach(function (s) { spy.observe(s); });
    }
  })();

  /* ---------------------------------------------------------------
     06. MENU OVERLAY
     --------------------------------------------------------------- */
  var closeMenu = function () {};

  (function menu() {
    var toggle = document.getElementById('menuToggle');
    var overlay = document.getElementById('menuOverlay');
    if (!toggle || !overlay) return;

    function setOpen(open) {
      body.classList.toggle('menu-open', open);
      overlay.classList.toggle('is-open', open);
      overlay.setAttribute('aria-hidden', open ? 'false' : 'true');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      toggle.setAttribute('aria-label', open ? 'Tutup navigasi' : 'Buka navigasi');
      if (window.__lenis) {
        if (open) window.__lenis.stop();
        else window.__lenis.start();
      }
    }

    closeMenu = function () { setOpen(false); };

    toggle.addEventListener('click', function () {
      setOpen(!overlay.classList.contains('is-open'));
    });

    overlay.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () { setOpen(false); });
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && overlay.classList.contains('is-open')) setOpen(false);
    });
  })();

  /* ---------------------------------------------------------------
     07. SMOOTH SCROLL (LENIS) + ANCHORS
     --------------------------------------------------------------- */
  var lenis = null;

  (function smoothScroll() {
    if (window.Lenis && !reduceMotion) {
      try {
        lenis = new window.Lenis({
          lerp: 0.09,
          wheelMultiplier: 0.95,
          touchMultiplier: 1.6,
          smoothWheel: true
        });
        window.__lenis = lenis;

        if (window.gsap) {
          window.gsap.ticker.add(function (time) { lenis.raf(time * 1000); });
          window.gsap.ticker.lagSmoothing(0);
        } else {
          var raf = function (time) {
            lenis.raf(time);
            window.requestAnimationFrame(raf);
          };
          window.requestAnimationFrame(raf);
        }
      } catch (err) {
        lenis = null;
      }
    }

    window.__scrollTo = function (target) {
      var node = typeof target === 'string' ? document.querySelector(target) : target;
      if (!node) return;
      var top = node.getBoundingClientRect().top + window.pageYOffset - headerH - 4;
      if (lenis) lenis.scrollTo(top, { duration: 1.2 });
      else window.scrollTo({ top: top, behavior: reduceMotion ? 'auto' : 'smooth' });
    };

    document.addEventListener('click', function (e) {
      var link = e.target.closest('a[href^="#"]');
      if (!link) return;
      var href = link.getAttribute('href');
      if (!href || href === '#' || href.length < 2) return;
      var node = document.querySelector(href);
      if (!node) return;
      e.preventDefault();
      closeMenu();
      window.__scrollTo(node);
      if (window.history && history.replaceState) history.replaceState(null, '', href);
    });
  })();

  /* ---------------------------------------------------------------
     08. MARQUEE LOOP
     --------------------------------------------------------------- */
  (function marquee() {
    var track = document.getElementById('marqueeTrack');
    if (!track) return;
    var original = track.innerHTML;
    track.innerHTML = original + original;
  })();

  /* ---------------------------------------------------------------
     09. GSAP SCROLL STORYTELLING
     --------------------------------------------------------------- */
  function refreshScrollTriggers() {
    if (window.ScrollTrigger) window.ScrollTrigger.refresh();
  }
  window.refreshScrollTriggers = refreshScrollTriggers;

  (function storytelling() {
    if (!window.gsap || !window.ScrollTrigger || reduceMotion) return;
    var gsap = window.gsap;
    gsap.registerPlugin(window.ScrollTrigger);

    if (lenis) {
      lenis.on('scroll', window.ScrollTrigger.update);
    }

    /* Horizontal proof gallery on large screens */
    var pin = document.getElementById('proofPin');
    var viewport = document.getElementById('proofViewport');
    var track = document.getElementById('proofTrack');
    var bar = document.getElementById('proofProgress');

    if (pin && viewport && track && window.innerWidth > 1024) {
      var distance = function () {
        return Math.max(0, track.scrollWidth - viewport.clientWidth);
      };

      if (distance() > 80) {
        gsap.to(track, {
          x: function () { return -distance(); },
          ease: 'none',
          scrollTrigger: {
            trigger: pin,
            start: 'top top',
            end: function () { return '+=' + Math.max(1, distance()); },
            pin: true,
            anticipatePin: 1,
            scrub: 0.7,
            invalidateOnRefresh: true,
            onUpdate: function (self) {
              if (bar) bar.style.width = (self.progress * 100).toFixed(1) + '%';
            }
          }
        });
      }
    } else if (viewport) {
      var updateBar = function () {
        var max = viewport.scrollWidth - viewport.clientWidth;
        if (bar && max > 0) bar.style.width = ((viewport.scrollLeft / max) * 100).toFixed(1) + '%';
      };
      viewport.addEventListener('scroll', updateBar, { passive: true });
    }

    /* Section headline drift */
    gsap.utils.toArray('.section-head .section-title').forEach(function (el) {
      gsap.fromTo(el, { y: 26 }, {
        y: 0,
        ease: 'none',
        scrollTrigger: {
          trigger: el,
          start: 'top 92%',
          end: 'top 55%',
          scrub: true
        }
      });
    });

    window.addEventListener('load', refreshScrollTriggers);
  })();

  /* ---------------------------------------------------------------
     10. UNIVERSAL CARD SPOTLIGHT TRACKING
     Interactive mouse-following ambient shine on cards across all sections
     --------------------------------------------------------------- */
  (function initCardSpotlights() {
    if (reduceMotion) return;
    var cards = document.querySelectorAll('.pillar, .cap-row, .dl-card, .pricing-card, .faq-item, .calc-box, .lab-stage, .lab-panel, .showcase-content');
    cards.forEach(function (el) {
      el.addEventListener('pointermove', function (e) {
        var rect = el.getBoundingClientRect();
        var x = e.clientX - rect.left;
        var y = e.clientY - rect.top;
        el.style.setProperty('--spot-x', x + 'px');
        el.style.setProperty('--spot-y', y + 'px');
      }, { passive: true });
    });
  })();

  /* Keep layout metrics correct on resize */
  var resizeTimer = 0;
  window.addEventListener('resize', function () {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(function () {
      headerH = header ? header.offsetHeight : 76;
      refreshScrollTriggers();
    }, 180);
  }, { passive: true });
})();
