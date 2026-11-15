/**
 * ICT TERMINAL PRO - HIGH-TECH INTERACTIVE CONTROLLER
 * Pure Vanilla JS, zero dependencies, lightning fast.
 */

document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  initTabs();
  initLightbox();
  initFaqAccordion();
  initCalculator();
  initDownloadButtons();
});

/* ===================================================================
   1. NAVBAR & SMOOTH SCROLL
   =================================================================== */
function initNavbar() {
  const toggleBtn = document.querySelector('.menu-toggle');
  const navLinks = document.querySelector('.nav-links');
  const links = document.querySelectorAll('.nav-link');
  const sections = document.querySelectorAll('section[id]');

  if (toggleBtn && navLinks) {
    toggleBtn.addEventListener('click', () => {
      navLinks.classList.toggle('open');
      const isOpen = navLinks.classList.contains('open');
      toggleBtn.innerHTML = isOpen ? '&times;' : '&#9776;';
    });

    links.forEach(link => {
      link.addEventListener('click', () => {
        navLinks.classList.remove('open');
        if (toggleBtn) toggleBtn.innerHTML = '&#9776;';
      });
    });
  }

  // Active section spy
  window.addEventListener('scroll', () => {
    let current = '';
    const scrollY = window.pageYOffset;

    sections.forEach(section => {
      const sectionHeight = section.offsetHeight;
      const sectionTop = section.offsetTop - 120;
      const sectionId = section.getAttribute('id');

      if (scrollY > sectionTop && scrollY <= sectionTop + sectionHeight) {
        current = sectionId;
      }
    });

    links.forEach(link => {
      link.classList.remove('active');
      if (link.getAttribute('href') === `#${current}`) {
        link.classList.add('active');
      }
    });
  });
}

/* ===================================================================
   2. SHOWCASE TABS (MENU TAMPILAN)
   =================================================================== */
function initTabs() {
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabPanes = document.querySelectorAll('.tab-pane');

  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-target');

      // Update button active state
      tabBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      // Update pane active state
      tabPanes.forEach(pane => {
        pane.classList.remove('active');
        if (pane.id === targetId) {
          pane.classList.add('active');
        }
      });
    });
  });
}

/* ===================================================================
   3. LIGHTBOX / IMAGE MODAL
   =================================================================== */
function initLightbox() {
  const modal = document.getElementById('imageModal');
  const modalImg = document.getElementById('modalImage');
  const modalCaption = document.getElementById('modalCaption');
  const closeBtn = document.getElementById('modalClose');

  if (!modal || !modalImg) return;

  const clickableImages = document.querySelectorAll('[data-zoomable]');

  clickableImages.forEach(imgContainer => {
    imgContainer.addEventListener('click', () => {
      const img = imgContainer.querySelector('img') || imgContainer;
      const src = img.getAttribute('src');
      const caption = img.getAttribute('alt') || 'Tampilan ICT Terminal Pro';

      modalImg.setAttribute('src', src);
      if (modalCaption) modalCaption.textContent = caption;
      modal.classList.add('active');
      document.body.style.overflow = 'hidden';
    });
  });

  const closeModal = () => {
    modal.classList.remove('active');
    document.body.style.overflow = '';
  };

  if (closeBtn) closeBtn.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains('active')) {
      closeModal();
    }
  });
}

/* ===================================================================
   4. FAQ ACCORDION
   =================================================================== */
function initFaqAccordion() {
  const faqItems = document.querySelectorAll('.faq-item');

  faqItems.forEach(item => {
    const questionBtn = item.querySelector('.faq-question');
    if (!questionBtn) return;

    questionBtn.addEventListener('click', () => {
      const isOpen = item.classList.contains('open');

      // Optional: Close others
      faqItems.forEach(other => {
        if (other !== item) other.classList.remove('open');
      });

      if (isOpen) {
        item.classList.remove('open');
      } else {
        item.classList.add('open');
      }
    });
  });
}

/* ===================================================================
   5. RISK & REWARD SIMULATOR (CALCULATOR)
   =================================================================== */
function initCalculator() {
  const balanceInput = document.getElementById('calcBalance');
  const riskPctInput = document.getElementById('calcRiskPct');
  const stopLossInput = document.getElementById('calcSL');
  const rrRatioInput = document.getElementById('calcRR');

  const resRiskUsd = document.getElementById('resRiskUsd');
  const resRewardUsd = document.getElementById('resRewardUsd');
  const resLot = document.getElementById('resLot');
  const resPotentialReturn = document.getElementById('resPotentialReturn');

  if (!balanceInput || !riskPctInput || !stopLossInput || !rrRatioInput) return;

  function calculate() {
    const balance = parseFloat(balanceInput.value) || 10000;
    const riskPct = parseFloat(riskPctInput.value) || 0.5;
    const slPips = parseFloat(stopLossInput.value) || 25;
    const rr = parseFloat(rrRatioInput.value) || 2.5;

    // Risk calculation in USD
    const riskUsd = (balance * riskPct) / 100;
    const rewardUsd = riskUsd * rr;

    // Approximate Lot size for Gold/Forex ($10 per pip standard lot)
    // Pip value standard: 1 lot = $10/pip
    const lotSize = (riskUsd / (slPips * 10)).toFixed(2);
    const returnPct = (riskPct * rr).toFixed(2);

    if (resRiskUsd) resRiskUsd.textContent = `-$${riskUsd.toFixed(2)}`;
    if (resRewardUsd) resRewardUsd.textContent = `+$${rewardUsd.toFixed(2)}`;
    if (resLot) resLot.textContent = `${lotSize} Lot`;
    if (resPotentialReturn) resPotentialReturn.textContent = `+${returnPct}%`;
  }

  [balanceInput, riskPctInput, stopLossInput, rrRatioInput].forEach(inp => {
    inp.addEventListener('input', calculate);
  });

  calculate();
}

/* ===================================================================
   6. DOWNLOAD BUTTONS & TOAST
   =================================================================== */
function showToast(message) {
  let toast = document.getElementById('appToast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'appToast';
    toast.className = 'toast';
    document.body.appendChild(toast);
  }

  toast.innerHTML = `
    <span class="toast-icon">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M20 6L9 17l-5-5"/>
      </svg>
    </span>
    <span>${message}</span>
  `;

  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 3500);
}

function initDownloadButtons() {
  const downloadBtns = document.querySelectorAll('[data-dl-action]');
  const copyPathBtns = document.querySelectorAll('[data-copy-path]');

  downloadBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      const filename = btn.getAttribute('data-filename') || 'file';
      showToast(`Mengunduh ${filename}... Silakan periksa folder Download Anda!`);
    });
  });

  copyPathBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const pathText = btn.getAttribute('data-copy-path');
      navigator.clipboard.writeText(pathText).then(() => {
        showToast(`Lokasi folder disalin: "${pathText}". Tempel di File Explorer!`);
      }).catch(() => {
        showToast(`Lokasi: ${pathText}`);
      });
    });
  });
}
