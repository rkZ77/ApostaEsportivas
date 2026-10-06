/*
 * Motor de tempo dos anúncios. Tudo vira função do tempo t:
 *   - as animações CSS ficam pausadas e `seek(t)` põe cada uma no instante t;
 *   - o que CSS não faz (número contando, texto digitando, cena visível) sai
 *     de `atualizar(t)`.
 * Por isso o quadro 412 sai igual em qualquer máquina, e `anuncio.py` pode
 * fotografar devagar sem pular quadro.
 *
 * Cada vídeo declara no <body>:  data-dur="22"  data-cortes="3,7,12"
 * e pode registrar ganchos:
 *   A.montar(fn)    roda antes de as animações serem coletadas (gera DOM)
 *   A.quadro(fn)    roda a cada quadro com t (coisas que dependem do tempo)
 */
(() => {
  const body = document.body;
  const DUR = parseFloat(body.dataset.dur || '22');
  const CORTES = (body.dataset.cortes || '').split(',').filter(Boolean).map(Number);
  const RENDER = new URLSearchParams(location.search).has('render');
  if (RENDER) document.documentElement.classList.add('render');
  window.DUR = DUR;

  const montadores = [], quadros = [];
  const rnd = n => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
  const R = '../saida/anuncio/';
  const LOGO = '../../../frontend/public/logo.png';
  const A = window.A = {
    rnd, R, LOGO,
    montar: f => montadores.push(f),
    quadro: f => quadros.push(f),
    ease: x => 1 - Math.pow(1 - x, 3),
    clamp: (x, a = 0, b = 1) => Math.min(b, Math.max(a, x)),
    esc: (id, px = 120) => `<span class="esc" style="width:${px}px;height:${px}px"><img src="${R}logos/teams/${id}.png" alt=""></span>`,
    lgo: (id, px = 100) => `<span class="lgo" style="width:${px}px;height:${px}px"><img src="${R}logos/leagues/${id}.png" alt=""></span>`,
    tela: nome => `${R}telas/${nome}.png`,
  };

  const stage = document.getElementById('stage');
  stage.insertAdjacentHTML('afterbegin', '<div class="bg-grid"></div><div class="bg-glow"></div>');
  stage.insertAdjacentHTML('beforeend', '<div class="bg-vig"></div><div id="cutbar"></div><div id="flash"></div>');
  document.body.insertAdjacentHTML('beforeend',
    '<div id="ctl"><button id="pp">pausar</button><input id="scrub" type="range" min="0" step="0.01" value="0"><span id="tt">0.00s</span></div>');

  /* ------------------------------------------------------------ cartão final */
  function cartaoFinal(sec) {
    const t0 = parseFloat(sec.dataset.in);
    const l1 = sec.dataset.l1 || '', l2 = sec.dataset.l2 || '', sub = sec.dataset.sub || '';
    let raios = '';
    for (let i = 0; i < 36; i++) {
      const a = i / 36 * Math.PI * 2, r0 = 240 + rnd(i) * 80, r1 = r0 + 140 + rnd(i + 50) * 260;
      const x = r => (Math.cos(a) * r).toFixed(1), y = r => (Math.sin(a) * r).toFixed(1);
      raios += `<line x1="${x(r0)}" y1="${y(r0)}" x2="${x(r1)}" y2="${y(r1)}" stroke="#00cc00" stroke-opacity="${(.15 + rnd(i + 7) * .35).toFixed(2)}" stroke-width="3" stroke-linecap="round"/>`
             + `<circle cx="${x(r1)}" cy="${y(r1)}" r="6" fill="#00cc00" fill-opacity=".6"/>`;
    }
    sec.insertAdjacentHTML('afterbegin', `
      <div class="rays a fade" style="--at:${t0}"><svg viewBox="-700 -700 1400 1400">${raios}</svg></div>
      <div class="logo a pop" style="--at:${t0 + .02}">
        <div class="ring2 r1"></div><div class="ring2 r2"></div>
        <div class="logo-ring" style="animation-delay:${t0}s"></div>
        <img src="${LOGO}" alt="" style="width:100%;height:100%;filter:drop-shadow(0 0 40px rgba(0,204,0,.45))">
      </div>
      <h2 class="hl abs cx" style="top:900px">
        ${l1 ? `<span class="ln split fit" data-at="${t0 + .2}" style="font-size:${sec.dataset.f1 || 100}px">${l1}</span>` : ''}
        ${l2 ? `<span class="ln fit a slam" style="--at:${t0 + .45};font-size:${sec.dataset.f2 || 120}px"><em>${l2}</em></span>` : ''}
      </h2>
      ${sub ? `<div class="abs cx a up" style="--at:${t0 + .6};top:${sec.dataset.subtop || 1170}px;font:600 34px/1.3 Inter;color:var(--ink2)">${sub}</div>` : ''}
      <div class="abs cx a up" style="--at:${t0 + .75};top:${sec.dataset.urltop || 1260}px"><span class="url"><span class="dot" style="width:20px;height:20px"></span>pickia.com.br</span></div>
      <div class="scanline" style="animation-delay:${t0 + 1.05}s"></div>`);
  }

  /* ------------------------------------------------------------ palavra por palavra */
  function dividir(el) {
    let at = parseFloat(el.dataset.at), passo = parseFloat(el.dataset.passo || '.07');
    const walk = node => {
      [...node.childNodes].forEach(n => {
        if (n.nodeType === 3) {
          const frag = document.createDocumentFragment();
          n.textContent.split(/(\s+)/).forEach(p => {
            if (!p) return;
            if (/^\s+$/.test(p)) { frag.appendChild(document.createTextNode(' ')); return; }
            const m = document.createElement('span'); m.className = 'wm';
            const w = document.createElement('span'); w.className = 'w'; w.textContent = p;
            w.style.setProperty('--at', at.toFixed(2)); at += passo;
            m.appendChild(w); frag.appendChild(m);
          });
          n.replaceWith(frag);
        } else walk(n);
      });
    };
    walk(el);
  }

  // Linha que não cabe encolhe até caber. offsetWidth ignora transform.
  function encaixar() {
    document.querySelectorAll('.fit').forEach(el => {
      let fs = parseFloat(el.style.fontSize || getComputedStyle(el).fontSize);
      const max = parseFloat(el.dataset.max || '990');
      const medir = () => { el.style.display = 'inline-block'; const w = el.offsetWidth; el.style.display = ''; return w; };
      while (medir() > max && fs > 24) { fs -= 2; el.style.fontSize = fs + 'px'; }
    });
  }

  /* ------------------------------------------------------------ tempo */
  let cenas, flick, cnts, tipos, flash, cutbar, anims = [];
  const fmt = (v, dec) => dec ? v.toFixed(dec).replace('.', body.dataset.virgula ? ',' : '.') : Math.round(v).toLocaleString('pt-BR');

  function atualizar(t) {
    cenas.forEach(s => { s.style.visibility = (t >= +s.dataset.in && t < +s.dataset.out) ? 'visible' : 'hidden'; });
    const tick = Math.floor(t * 9);
    flick.forEach((el, i) => {
      const stop = el.dataset.stop ? parseFloat(el.dataset.stop) : Infinity;
      if (t >= stop) { el.textContent = el.dataset.v; return; }
      const [a, b, dec] = el.dataset.fl.split(',').map(Number);
      el.textContent = (a + rnd(tick * 31 + i * 7) * (b - a)).toFixed(dec) + (el.dataset.suf || '');
    });
    cnts.forEach(el => {
      const [a, b, t0, t1, dec] = el.dataset.cnt.split(',').map(Number);
      const k = A.clamp((t - t0) / (t1 - t0));
      el.textContent = (el.dataset.pre || '') + fmt(a + (b - a) * A.ease(k), dec || 0) + (el.dataset.suf || '');
    });
    tipos.forEach(el => {
      const n = Math.max(0, Math.floor((t - parseFloat(el.dataset.t0)) * parseFloat(el.dataset.cps || '30')));
      const full = el.dataset.type;
      el.textContent = n === 0 ? ' ' : full.slice(0, n) + (n < full.length ? '▍' : '');
    });
    let f = 0, bar = null;
    CORTES.forEach(c => { const d = t - c; if (d >= 0 && d < .2) f = Math.max(f, 1 - d / .2); if (d >= -0.12 && d < 0.1) bar = (d + .12) / .22; });
    flash.style.opacity = (f * .7).toFixed(3);
    if (bar !== null) { cutbar.style.opacity = 1; cutbar.style.top = (bar * 1920 - 40) + 'px'; } else cutbar.style.opacity = 0;
    quadros.forEach(q => q(t));
  }

  function seek(t) { anims.forEach(a => { a.currentTime = t * 1000; }); atualizar(t); }

  async function pronto() {
    document.querySelectorAll('.endcard').forEach(cartaoFinal);
    montadores.forEach(m => m());
    document.querySelectorAll('.split').forEach(dividir);
    cenas = [...document.querySelectorAll('.scene')];
    flick = [...document.querySelectorAll('[data-fl]')];
    cnts = [...document.querySelectorAll('[data-cnt]')];
    tipos = [...document.querySelectorAll('[data-type]')];
    flash = document.getElementById('flash'); cutbar = document.getElementById('cutbar');
    await document.fonts.ready;
    await Promise.all([...document.images].map(i => i.decode().catch(() => {})));
    cenas.forEach(s => s.style.visibility = 'visible');
    encaixar();
    anims = document.getAnimations();
    anims.forEach(a => a.pause());
    seek(0);
    window.__seek = t => { seek(t); return true; };
    window.__pronto = true;
  }

  function escala() { stage.style.setProperty('--k', Math.min(innerWidth / 1080, innerHeight / 1920)); }
  escala(); addEventListener('resize', escala);

  addEventListener('DOMContentLoaded', () => pronto().then(() => {
    if (RENDER) return;
    let t0 = performance.now(), tocando = true, tPausa = 0;
    const scrub = document.getElementById('scrub'), tt = document.getElementById('tt'), pp = document.getElementById('pp');
    scrub.max = DUR;
    const loop = () => {
      if (tocando) { const t = ((performance.now() - t0) / 1000) % DUR; seek(t); scrub.value = t; tt.textContent = t.toFixed(2) + 's'; }
      requestAnimationFrame(loop);
    };
    pp.onclick = () => { tocando = !tocando; pp.textContent = tocando ? 'pausar' : 'tocar'; if (tocando) t0 = performance.now() - tPausa * 1000; else tPausa = +scrub.value; };
    scrub.oninput = () => { const t = +scrub.value; tPausa = t; t0 = performance.now() - t * 1000; seek(t); tt.textContent = t.toFixed(2) + 's'; };
    loop();
  }));
})();
