/* Liar's Poker Stats: the admin dashboard. No framework: each change re-renders
   the page from `state`; clicks go through one listener (data-act). Every value
   from the server goes through esc() before it reaches the HTML. */
'use strict';
(() => {
  const app = document.getElementById('app');
  const phone = () => window.matchMedia('(max-width: 900px)').matches;
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  // ----- icons (Lucide, MIT) ------------------------------------------------
  const ICONS = {
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4M12 17h.01"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    left: '<path d="m15 18-6-6 6-6"/>',
    right: '<path d="m9 18 6-6-6-6"/>',
    down: '<path d="m6 9 6 6 6-6"/>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    eye: '<path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0"/><circle cx="12" cy="12" r="3"/>',
    eyeOff: '<path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68M6.61 6.61A13.53 13.53 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61M2 2l20 20M9.88 9.88a3 3 0 1 0 4.24 4.24"/>',
    lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    unlock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>',
    reset: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    shuffle: '<path d="m18 14 4 4-4 4M18 2l4 4-4 4"/><path d="M2 18h2c1.6 0 3-.8 3.8-2.1l4.4-7.8C13 6.8 14.4 6 16 6h6M2 6h2c1.4 0 2.7.6 3.5 1.7M22 18h-6c-1.4 0-2.7-.6-3.5-1.7"/>',
    ban: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    plus: '<path d="M5 12h14M12 5v14"/>',
    bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2M20 14h2M15 13v2M9 13v2"/>',
    server: '<rect width="20" height="8" x="2" y="2" rx="2"/><rect width="20" height="8" x="2" y="14" rx="2"/><path d="M6 6h.01M6 18h.01"/>',
    door: '<path d="M13 4h3a2 2 0 0 1 2 2v14M2 20h3M13 20h9M10 12v.01"/><path d="M13 4.56v16.5a.5.5 0 0 1-.6.5L5 20V5.56a1 1 0 0 1 .72-.96l6-1.71A1 1 0 0 1 13 3.86z"/>',
    phone: '<rect width="14" height="20" x="5" y="2" rx="2"/><path d="M12 18h.01"/>',
    info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    circleAlert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
    timer: '<path d="M10 2h4M12 14l3-3"/><circle cx="12" cy="14" r="8"/>',
    gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    mute: '<path d="M8.7 3A6 6 0 0 1 18 8a21.3 21.3 0 0 0 .6 5M17 17H3s3-2 3-9a4.67 4.67 0 0 1 .3-1.7M10.3 21a1.94 1.94 0 0 0 3.4 0M2 2l20 20"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    spade: '<path d="M12 3.5 6.2 9.3C5 10.5 4 11.8 4 13.5A4 4 0 0 0 8 17.5c1.4 0 2.4-.4 3.4-1.4h1.2c1 1 2 1.4 3.4 1.4a4 4 0 0 0 4-4c0-1.7-1-3-2.2-4.2ZM12 16v4.5"/>',
    circleCheck: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    inside: '<path d="M17 6H3M21 12H3M15 18H3"/>',
    whole: '<path d="M4 7V4h16v3M9 20h6M12 4v16"/>',
    message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5M12 7v5l4 2"/>',
    bulb: '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6M10 22h4"/>',
    more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    external: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
    file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4M16 13H8M16 17H8M10 9H8"/>',
    mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
  };
  const icon = (name, cls = '') => `<svg class="svg ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;

  // ----- formatting -----------------------------------------------------------
  const fmt = (n) => (n == null ? '—' : Math.round(n).toLocaleString('en-US'));
  const pct = (x, d = 0) => (x == null ? '—' : `${(x * 100).toFixed(d)}%`);
  const dur = (s) => {
    if (s == null) return '—';
    s = Math.round(s);
    const m = Math.floor(s / 60);
    return m ? `${m}m ${String(s % 60).padStart(2, '0')}s` : `${s}s`;
  };
  const now = () => Date.now() / 1000;
  const ago = (t) => {
    if (!t) return '—';
    const d = now() - t;
    if (d < 90) return 'now';
    if (d < 3600) return `${Math.round(d / 60)}m ago`;
    if (d < 86400) return `${Math.round(d / 3600)}h ago`;
    if (d < 60 * 86400) return `${Math.round(d / 86400)}d ago`;
    if (d < 365 * 86400) return `${Math.round(d / (30 * 86400))}mo ago`;
    return `${Math.round(d / (365 * 86400))}y ago`;
  };
  const day = (t) => (t ? new Date(t * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—');
  const clock = (t) => (t ? new Date(t * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '—');
  const isToday = (t) => new Date(t * 1000).toDateString() === new Date().toDateString();
  const whenShort = (t) => (isToday(t) ? `Today ${clock(t)}` : day(t));
  const PREV = { '24h': 'prev 24h', '7d': 'prev 7d', '30d': 'prev 30d', all: 'before' };
  const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const RANKS = { 9: ['9', '9s'], T: ['10', '10s'], J: ['J', 'Jacks'], Q: ['Q', 'Queens'], K: ['K', 'Kings'], A: ['A', 'Aces'] };
  const betText = (bet) => {
    if (!bet) return '';
    const p = bet.split('_');
    const short = (r) => (RANKS[r] || [r])[0];
    const many = (r) => (RANKS[r] || [r, r])[1];
    if (bet.startsWith('high_card_')) return `high card ${short(p[2])}`;
    if (bet.startsWith('pair_')) return `pair of ${many(p[1])}`;
    if (bet.startsWith('two_pair_')) return `two pair ${short(p[2])} & ${short(p[3])}`;
    if (bet === 'small_straight' || bet === 'big_straight') return bet.replace('_', ' ');
    if (bet.startsWith('three_')) return `three ${many(p[1])}`;
    if (bet.startsWith('full_')) return `full house ${short(p[1])} over ${short(p[2])}`;
    if (bet.startsWith('quad_')) return `four ${many(p[1])}`;
    if (bet.startsWith('flush_')) return `flush ${p[1]}`;
    if (bet.includes('_poker_')) return `${p[0]} poker ${p[2]}`;
    return bet.replace(/_/g, ' ');
  };

  /** "+14% vs prev 7d", green when it went the good way. */
  function delta(cur, prev, { kind = 'pct', bad = false, label } = {}) {
    label = label ?? `vs ${PREV[state.range]}`;
    if (cur == null || prev == null) return `<div class="delta">${esc(label)}</div>`;
    let diff = cur - prev;
    let text;
    if (kind === 'pct') {
      if (!prev) return `<div class="delta">${esc(label)}</div>`;
      diff = (cur - prev) / prev;
      text = `${diff >= 0 ? '+' : '−'}${Math.abs(Math.round(diff * 100))}%`;
    } else if (kind === 'pt') text = `${diff >= 0 ? '+' : '−'}${Math.abs(Math.round(diff * 100))} pt`;
    else if (kind === 'dur') {
      const s = Math.round(Math.abs(diff));
      text = `${diff >= 0 ? '+' : '−'}${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    } else if (kind === 'ms') text = `${diff >= 0 ? '+' : '−'}${Math.abs(Math.round(diff))} ms`;
    else if (kind === 'dec') text = `${diff >= 0 ? '+' : '−'}${Math.abs(diff).toFixed(1)}`;
    else text = `${diff >= 0 ? '+' : '−'}${fmt(Math.abs(diff))}`;
    const good = Math.abs(diff) < 1e-9 ? '' : (diff > 0) !== bad ? 'up' : 'down';
    return `<div class="delta"><span class="${good}">${text}</span> ${esc(label)}</div>`;
  }

  const spark = (values, cls = '') => {
    const max = Math.max(1e-9, ...values.map((v) => v || 0));
    return `<div class="spark ${cls}">${values.map((v) => `<i style="height:${Math.max(8, ((v || 0) / max) * 100)}%"></i>`).join('')}</div>`;
  };
  const kpi = (label, value, deltaHtml, sparkHtml = '') =>
    `<div class="kpi"><div class="eyebrow">${label}</div><div class="kpi-row"><div class="big">${value}</div>${sparkHtml}</div>${deltaHtml}</div>`;
  const dash = (share, n = 16, cls = '') =>
    `<div class="dash ${cls}">${Array.from({ length: n }, (_, i) => `<i class="${share != null && i < Math.round(share * n) ? 'on' : ''}"></i>`).join('')}</div>`;

  const initials = (name) => {
    const words = String(name || '?').split(/[^\p{L}\p{N}]+/u).filter(Boolean);
    return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || '?').slice(0, 2)).toUpperCase();
  };
  /** A player's name: masked in Moderation unless "Show words" is on; auto names in italics. */
  const nameOf = (p, masked = false) => {
    if (!p || p.bot) return `Bot${p && p.level ? ` · ${p.level[0].toUpperCase()}${p.level.slice(1)}` : ''}`;
    return masked && !state.showWords && p.masked ? p.masked : p.name;
  };
  const avatar = (p, cls = '') =>
    p && p.bot ? `<span class="av bot ${cls}">${icon('bot')}</span>` : `<span class="av ${cls}">${esc(initials(p && p.name))}</span>`;
  function who(p, { av = true, inline = false, tag = '', masked = false } = {}) {
    const name = `<span class="who-name ${p && p.auto ? 'auto' : ''}">${esc(nameOf(p, masked))}${inline && p && !p.bot ? ` <span class="who-id">#${esc(p.sid)}</span>` : ''}${tag}</span>`;
    const id = !inline && p && !p.bot ? `<div class="who-id">#${esc(p.sid)}</div>` : '';
    return `<div class="who">${av ? avatar(p) : ''}<div class="who-text">${name}${id}</div></div>`;
  }
  const statusPill = (s) =>
    s === 'playing' ? '<span class="pill green">Playing</span>' : s === 'online' ? '<span class="pill dark">Online</span>' : '<span class="pill ring">Offline</span>';
  const REASONS = {
    offensive_name: ['Offensive name', 'red'], abusive_reactions: ['Rude reactions', 'amber'],
    cheating: ['Cheating', 'amber'], other: ['Something else', ''],
  };
  const reasonPill = (r) => `<span class="pill ${REASONS[r]?.[1] || ''}">${esc(REASONS[r]?.[0] || r)}</span>`;

  // ----- state, data, routing -----------------------------------------------
  const PAGES = [
    ['overview', 'Overview', 'grid'], ['players', 'Players', 'users'], ['games', 'Games', 'layers'],
    ['moderation', 'Moderation', 'shield'], ['problems', 'Problems', 'alert'],
    ['feedback', 'Feedback', 'message'], ['changelog', 'Changelog', 'history'], ['requests', 'Requests', 'bulb'],
    ['more', 'More', 'more'],
  ];
  /** The sidebar's two groups; on a phone the tab bar has four pages and More. */
  const NAV_GROUPS = [['Stats', ['overview', 'players', 'games', 'moderation', 'problems']], ['Product', ['feedback', 'changelog', 'requests']]];
  const PHONE_TABS = ['overview', 'players', 'games', 'problems', 'more'];
  const MORE_PAGES = ['moderation', 'feedback', 'changelog', 'requests'];
  /** Pages without data of their own. */
  const NO_DATA = ['more'];
  const badge = (id) => {
    const shell = state.shell || {};
    if (id === 'moderation') return shell.reports_open;
    if (id === 'problems') return shell.problems_open;
    if (id === 'feedback') return shell.feedback_open;
    if (id === 'more') return MORE_PAGES.reduce((n, p) => n + (p === 'feedback' ? 0 : badge(p) || 0), 0);
    return 0;
  };
  const saved = (key, fallback) => { try { return localStorage.getItem(key) || fallback; } catch { return fallback; } };
  const state = {
    page: 'overview', range: saved('lp_range', '7d'), tabs: { players: 'all', games: 'all', problems: 'open', moderation: 'open', words: 'yours', feedback: 'open', requests: 'now' },
    q: { players: '', games: '', problems: '', moderation: '', feedback: '' }, sort: 'last_seen', pageNo: { players: 0, games: 0 },
    sel: { players: null, problems: null, moderation: null, feedback: null }, sheet: null, data: null, detail: null, game: null,
    shell: null, updated: 0, failed: false, showWords: false, login: null, wordInput: '', wordWhole: false,
    newName: null, blockOld: true, lockName: false, builtinAll: {}, allTables: false, tip: null,
  };

  async function api(path, body) {
    const options = { credentials: 'same-origin' };
    if (body) Object.assign(options, { method: 'POST', headers: { 'content-type': 'application/json', 'x-admin': '1' }, body: JSON.stringify(body) });
    const res = await fetch(`/admin/api/${path}`, options);
    let json = {};
    try { json = await res.json(); } catch { /* not JSON */ }
    if (res.status === 401 && path !== 'login') {
      state.login = state.login || { error: null, wait: 0 };
      render();
      throw new Error('login');
    }
    return { status: res.status, ...json };
  }

  function route() {
    const [page, query] = (location.hash.replace(/^#\/?/, '') || 'overview').split('?');
    state.page = PAGES.some((p) => p[0] === page) ? page : 'overview';
    const params = new URLSearchParams(query || '');
    if (params.get('q') != null) state.q[state.page] = params.get('q');
    if (params.get('tab')) state.tabs[state.page] = params.get('tab');
    if (params.get('sel')) state.sel[state.page] = params.get('sel');
    state.sheet = null;
    state.data = null;
    state.detail = null;
    load();
  }
  const go = (page, params = {}) => {
    const q = new URLSearchParams(params).toString();
    location.hash = `#/${page}${q ? `?${q}` : ''}`;
  };

  let loading = 0;
  async function load(quiet = false) {
    const ticket = ++loading;
    const page = state.page;
    if (NO_DATA.includes(page)) {
      state.data = {};
      try {
        const res = await api('changelog');
        if (ticket !== loading) return;
        if (res.ok) { state.shell = res.shell; state.updated = now(); state.failed = false; }
      } catch (error) { if (error.message === 'login') return; }
      render(quiet);
      return;
    }
    const params = new URLSearchParams({ range: state.range });
    if (state.tabs[page]) params.set('tab', state.tabs[page]);
    if (state.q[page]) params.set('q', state.q[page]);
    if (page === 'players') params.set('sort', state.sort);
    if (state.pageNo[page] != null) params.set('page', state.pageNo[page]);
    try {
      const res = await api(`${page}?${params}`);
      if (ticket !== loading) return;
      if (!res.ok) throw new Error(res.error);
      state.data = res.data;
      state.shell = res.shell;
      state.updated = now();
      state.failed = false;
      state.login = null;
      pickDefault();
      await loadDetail(true);
    } catch (error) {
      if (error.message === 'login') return;
      state.failed = true;
    }
    if (ticket === loading) render(quiet);
  }

  /** On a desktop, the first row is open in the side panel, as in the design. */
  function pickDefault() {
    const rows = state.data?.rows;
    if (!rows || phone() || !(state.page in state.sel) || state.noDefault === state.page) return;
    if (!state.sel[state.page] || (state.page !== 'players' && !rows.some((r) => r.id === state.sel[state.page]))) {
      state.sel[state.page] = rows[0]?.id ?? null;
    }
  }

  async function loadDetail(quiet) {
    const page = state.page;
    const id = state.sel[page];
    if (page === 'games' && state.sheet) {
      const res = await api(`games/${encodeURIComponent(state.sheet)}`);
      state.game = res.ok ? res.data : null;
      return;
    }
    if (!(page in state.sel) || !id) { state.detail = null; return; }
    const res = await api(`${page}/${encodeURIComponent(id)}`);
    if (state.sel[page] !== id) return;
    state.detail = res.ok ? res.data : null;
    if (page === 'moderation' && state.detail && (state.newName == null || !quiet)) {
      state.newName = state.detail.suggestions[0];
    }
    if (!quiet) render();
  }

  // ----- the frame ----------------------------------------------------------
  function render() {
    if (state.login) return renderLogin();
    const focus = document.activeElement?.id;
    const caret = document.activeElement?.selectionStart;
    const scrolls = [...document.querySelectorAll('[data-keep-scroll]')].map((el) => [el.dataset.keepScroll, el.scrollTop]);
    const page = PAGES.find((p) => p[0] === state.page);
    const body = state.data ? PAGE_RENDER[state.page](state.data) : `<div class="empty">${state.failed ? 'Could not load. Retrying…' : 'Loading…'}</div>`;
    app.innerHTML = `
      <div class="shell">
        ${sidebar()}
        <main class="main">
          <div class="phone-top"><div class="brand"><span class="logo">${icon('spade')}</span>Liar's Poker</div>${updated()}</div>
          <header class="top">
            <div><div class="eyebrow">Liar's Poker &nbsp;/&nbsp; ${state.page === 'overview' ? 'Stats' : NAV_GROUPS[1][1].includes(state.page) ? `Product &nbsp;/&nbsp; ${esc(page[1])}` : esc(page[1])}</div><h1>${esc(page[1])}</h1></div>
            <div class="top-tools">${tools()}</div>
          </header>
          ${body}
        </main>
      </div>
      ${tabbar()}
      ${state.page === 'games' && state.sheet ? gameSheet() : ''}
      ${state.toast ? `<div class="toast" role="status">${esc(state.toast)}</div>` : ''}`;
    if (focus) {
      const el = document.getElementById(focus);
      if (el) { el.focus(); if (caret != null && el.setSelectionRange) el.setSelectionRange(caret, caret); }
    }
    for (const [key, top] of scrolls) {
      const el = document.querySelector(`[data-keep-scroll="${key}"]`);
      if (el) el.scrollTop = top;
    }
  }

  function sidebar() {
    const shell = state.shell || {};
    const m = shell.month;
    return `<aside class="side">
      <div class="brand"><span class="logo">${icon('spade')}</span>Liar's Poker</div>
      ${NAV_GROUPS.map(([group, ids], i) => `<div class="eyebrow" ${i ? 'style="margin-top:18px"' : ''}>${group}</div>
      <nav class="nav">${ids.map((id) => {
        const [, label, ic] = PAGES.find((p) => p[0] === id);
        const count = badge(id);
        return `<a href="#/${id}" class="${state.page === id ? 'on' : ''}">${icon(ic)}${label}${count ? `<span class="badge ${id === 'feedback' ? 'soft' : ''}">${count}</span>` : ''}</a>`;
      }).join('')}</nav>`).join('')}
      ${m ? `<div class="month">
        <div class="month-head"><span class="eyebrow">Players this month</span>${m.change != null ? `<span class="mono ${m.change >= 0 ? 'up' : 'down'}" style="font-size:10.5px">${m.change >= 0 ? '+' : '−'}${Math.abs(Math.round(m.change * 100))}%</span>` : ''}</div>
        <div class="month-value num">${fmt(m.this)} <small>/ last month ${fmt(m.last)}</small></div>
        <div class="dots">${Array.from({ length: 30 }, (_, i) => `<i class="${i < Math.round((m.day / m.days) * 30) ? 'on' : ''}"></i>`).join('')}</div>
        <div class="foot">${esc(new Date(m.start * 1000).toLocaleDateString('en-US', { month: 'short' }))} 1 – ${m.day} · ${m.day} of ${m.days} days</div>
      </div>` : ''}
      <button class="logout" data-act="logout">${icon('logout')}Log out</button>
    </aside>`;
  }

  function tabbar() {
    const current = MORE_PAGES.includes(state.page) ? 'more' : state.page;
    return `<nav class="tabbar">${PHONE_TABS.map((id) => {
      const [, label, ic] = PAGES.find((p) => p[0] === id);
      const count = badge(id);
      return `<a href="#/${id}" class="${current === id ? 'on' : ''}">${icon(ic)}${label}${count ? `<span class="badge">${count}</span>` : ''}</a>`;
    }).join('')}</nav>`;
  }

  function updated() {
    const age = state.updated ? Math.max(0, Math.round(now() - state.updated)) : null;
    const text = state.failed ? 'Offline · retrying' : age == null ? 'Loading' : `Updated ${age < 60 ? `${age}s` : `${Math.round(age / 60)}m`} ago`;
    return `<span class="updated" data-updated><span class="pulse ${state.failed ? 'stale' : ''}"></span>${text}</span>`;
  }

  function tools() {
    const placeholder = { players: 'Search name or #id', games: 'Search game # or player', problems: 'Search problems or logs', moderation: 'Search name or #id', feedback: 'Search feedback' }[state.page];
    const search = placeholder ? `<label class="search">${icon('search')}<input id="search" data-search value="${esc(state.q[state.page])}" placeholder="${placeholder}" autocomplete="off" spellcheck="false"><span class="kbd">/</span></label>` : '';
    const words = state.page === 'moderation' ? `<button class="toggle-chip" data-act="words" aria-pressed="${state.showWords}">${icon(state.showWords ? 'eye' : 'eyeOff')}Show words<span class="switch ${state.showWords ? 'on' : ''}"></span></button>` : '';
    const ranges = ['24h', '7d', '30d', 'all'].map((r) => `<button class="${state.range === r ? 'on' : ''}" data-act="range" data-v="${r}">${r === 'all' ? 'All' : r}</button>`).join('');
    if (['feedback', 'changelog', 'requests', 'more'].includes(state.page)) return `${search}${updated()}`;
    return `${search}${words}${updated()}<div class="seg range" role="group" aria-label="Time range">${ranges}</div>`;
  }

  const seg = (act, items, current) =>
    `<div class="seg" role="tablist">${items.map(([v, label, n]) => `<button role="tab" class="${current === v ? 'on' : ''}" data-act="${act}" data-v="${v}">${label}${n != null ? `<small>${n}</small>` : ''}</button>`).join('')}</div>`;

  // ----- charts -------------------------------------------------------------
  function stackedChart(bars, label) {
    const max = Math.max(1, ...bars.map((b) => b.real + b.bots + b.abandoned));
    const col = (b, i) => {
      const h = (v) => (v / max) * 100;
      return `<div class="col" data-tip="${i}">${b.abandoned ? `<i class="ab" style="height:${Math.max(1.5, h(b.abandoned))}%"></i>` : ''}${b.bots ? `<i class="bt" style="height:${h(b.bots)}%"></i>` : ''}${b.real ? `<i class="rl" style="height:${h(b.real)}%"></i>` : ''}</div>`;
    };
    state.tipData = bars.map((b) => ({ label: label(b), rows: [['var(--bar)', `${fmt(b.real)} real players`], ['var(--bar-soft)', `${fmt(b.bots)} with bots`], ['var(--red)', `${fmt(b.abandoned)} abandoned`]], total: `${fmt(b.real + b.bots + b.abandoned)} games` }));
    return bars.map(col);
  }

  function tipCard(i) {
    const t = state.tipData?.[i];
    if (!t) return '';
    return `<div><div class="eyebrow">${esc(t.label)}</div><b>${esc(t.total)}</b></div>
      <div class="rows">${t.rows.map(([c, text]) => `<div${c === 'var(--red)' ? ' class="bad"' : ''}><i class="sq" style="background:${c}"></i>${esc(text)}</div>`).join('')}</div>`;
  }

  function gamesChart(chart) {
    const step = chart.step;
    const label = (b) => {
      const d = new Date(b.t * 1000);
      const dayName = isToday(b.t) ? 'Today' : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      if (step <= 3600) return `${dayName} · ${String(d.getHours()).padStart(2, '0')}H`;
      if (step <= 4 * 3600) return `${dayName} · ${String(d.getHours()).padStart(2, '0')}-${String((d.getHours() + 4) % 24).padStart(2, '0')}H`;
      if (step <= 86400) return dayName;
      return `Week of ${dayName}`;
    };
    const cols = stackedChart(chart.bars, label);
    if (step === 4 * 3600) {
      const groups = [];
      for (let i = 0; i < cols.length; i += 6) groups.push(cols.slice(i, i + 6).join(''));
      const days = chart.bars.filter((_, i) => i % 6 === 0).map((b) => (isToday(b.t) ? 'Today' : phone() ? new Date(b.t * 1000).getDate() : day(b.t)));
      return `<div class="groups" data-chart>${groups.map((g) => `<div class="chart">${g}</div>`).join('')}</div>
        <div class="axis">${days.map((d) => `<span class="${d === 'Today' ? 'on' : ''}">${esc(d)}</span>`).join('')}</div>`;
    }
    const every = Math.ceil(chart.bars.length / (phone() ? 5 : 8));
    return `<div class="chart" data-chart>${cols.join('')}</div>
      <div class="axis">${chart.bars.map((b, i) => `<span>${i % every === 0 ? esc(step <= 3600 ? String(new Date(b.t * 1000).getHours()).padStart(2, '0') : day(b.t)) : ''}</span>`).join('')}</div>`;
  }

  function gauge(value, record) {
    const share = record ? Math.min(1, value / record) : 0;
    return `<div class="gauge">
      <svg viewBox="0 0 280 150" role="img" aria-label="${value} players online, record ${record}">
        <path d="M24 140 A116 116 0 0 1 256 140" fill="none" stroke="var(--track)" stroke-width="30"/>
        <path d="M24 140 A116 116 0 0 1 256 140" fill="none" stroke="var(--bar)" stroke-width="30" pathLength="100" stroke-dasharray="${(share * 100).toFixed(1)} 100"/>
        <path d="M48 140 A92 92 0 0 1 232 140" fill="none" stroke="var(--faint)" stroke-width="2"/>
      </svg>
      <div class="gauge-center"><div class="huge" style="font-size:50px">${fmt(value)}</div><div class="eyebrow" style="margin-top:6px">Players online</div></div>
      <div class="gauge-scale"><span>0</span><span>${fmt(record)} record</span></div>
    </div>`;
  }

  // ----- attention cards (Overview) ----------------------------------------
  const PROBLEM_ICON = { error: ['server', 'red'], abandoned: ['door', 'amber'], old_app: ['phone', ''], timeouts: ['timer', 'amber'], slow: ['gauge', ''], gone: ['check', ''] };
  function attention(p) {
    const [ic, tone] = PROBLEM_ICON[p.kind] || ['alert', ''];
    let eyebrow = '';
    let body = '';
    let side = '';
    if (p.kind === 'error') {
      eyebrow = 'Server · errors';
      body = `<p>${esc(p.subtitle.split(' · ')[0])} · ${fmt(p.last_hour)} in last hour</p><div class="strip">${(p.strip || []).map((v) => `<i class="${v ? 'on' : ''}"></i>`).join('')}</div>`;
      side = `<a class="link" href="#/problems?sel=${encodeURIComponent(p.id)}">Inspect ${icon('right')}</a>`;
    } else if (p.kind === 'abandoned') {
      eyebrow = 'Games · today';
      side = `<span class="pill amber">${Math.round(p.times)}× usual</span>`;
      const usual = p.usual || 0;
      const max = Math.max(usual * 1.6, ...(p.strip || [0]), 0.05);
      body = `<p>${esc(p.subtitle)}</p><div class="bars-usual">${(p.strip || []).map((v) => `<i class="${v > usual ? 'over' : ''}" style="height:${Math.max(6, (v / max) * 100)}%"></i>`).join('')}<span class="line" style="bottom:${(usual / max) * 100}%"></span></div>`;
    } else if (p.kind === 'old_app') {
      eyebrow = 'App · versions';
      const total = p.versions.reduce((a, [, n]) => a + n, 0) || 1;
      const shades = ['var(--text)', 'var(--bar-soft)', 'var(--track)', 'var(--faint)'];
      let cells = '';
      p.versions.slice(0, 4).forEach(([, n], i) => { cells += `<i style="flex:${n / total};background:${shades[i]}"></i>`; });
      body = `<p>${esc(p.subtitle)}</p><div class="versions">${cells}</div><div class="legend" style="margin:8px 0 0">${p.versions.slice(0, 4).map(([v, n], i) => `<span><i class="sq" style="background:${shades[i]}"></i>v${esc(v)} · ${fmt(n)}</span>`).join('')}</div>`;
    } else {
      eyebrow = p.kind === 'timeouts' ? 'Games · today' : 'Server · replies';
      body = `<p>${esc(p.subtitle)}</p>`;
    }
    return `<div class="att"><span class="att-icon ${tone}">${icon(ic)}</span><div>
      <div class="panel-head"><span class="eyebrow">${eyebrow}</span><span class="push">${side}</span></div>
      <h3>${esc(p.title)}</h3>${body}</div></div>`;
  }

  // ----- pages --------------------------------------------------------------
  const PAGE_RENDER = {};

  PAGE_RENDER.overview = (d) => {
    const k = d.kpis;
    const live = d.live;
    const maxHeat = Math.max(1, ...d.heatmap.flat());
    const shade = (v) => (v ? `color-mix(in srgb, var(--text) ${Math.round(12 + (v / maxHeat) * 88)}%, var(--bg))` : 'var(--track)');
    const cb = d.coming_back;
    const rangeTitle = { '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days', all: 'All time' }[state.range];
    const stats = `
            <div><div class="eyebrow">Games played</div><div class="huge" style="margin-top:10px">${fmt(k.games)}</div>${delta(k.games, k.games_prev)}</div>
            <div><div class="eyebrow">Players</div><div class="huge" style="margin-top:10px">${fmt(k.players)}</div>${delta(k.players, k.players_prev)}</div>
            <div><div class="eyebrow">Avg game length</div><div class="huge" style="margin-top:10px">${dur(k.avg_game)}</div>${delta(k.avg_game, k.avg_game_prev, { kind: 'dur' })}</div>
            <div><div class="eyebrow">Came back next day</div><div class="huge" style="margin-top:10px">${pct(k.next_day)}</div>${delta(k.next_day, k.next_day_prev, { kind: 'pt' })}</div>`;
    const legend = `<div class="legend"><span><i class="sq" style="background:var(--bar)"></i>Real players</span><span><i class="sq" style="background:var(--bar-soft)"></i>With bots</span><span><i class="sq" style="background:var(--red)"></i>Abandoned</span></div>`;
    // Phone: the four numbers get their own 2x2 block, then the chart with its legend
    // and a card for the tapped bar (the latest one to start with).
    const gamesBlock = phone()
      ? `<section class="cell flush"><div class="statgrid">${stats}</div></section>
      <section class="cell">
        <div class="panel-head"><span class="title">Games · ${rangeTitle}</span></div>
        ${legend}
        ${(() => { const chart = gamesChart(d.chart); return `<div class="tipcard" data-tipcard>${tipCard(Math.max(0, d.chart.bars.map((b) => b.real + b.bots + b.abandoned > 0).lastIndexOf(true)))}</div><div style="position:relative">${chart}</div>`; })()}
      </section>`
      : `<section class="cell">
        <div class="panel-head"><span class="title">Games · ${rangeTitle}</span>${legend}</div>
        <div style="display:grid;grid-template-columns:190px minmax(0,1fr);gap:28px;margin-top:20px">
          <div class="statcol">${stats}
          </div>
          <div class="chart-fill" style="position:relative">${gamesChart(d.chart)}</div>
        </div>
      </section>`;
    return `<div class="grid">
      ${gamesBlock}
      <section class="cell">
        <div class="panel-head"><span class="title">Live now</span></div>
        ${gauge(live.online, live.record)}
        <div class="legend-list">
          <div><i class="sq" style="background:var(--text)"></i>Games playing<b class="num">${fmt(live.playing)}</b></div>
          <div><i class="sq" style="background:var(--bar)"></i>Waiting in lobby<b class="num">${fmt(live.waiting)}</b></div>
          <div><i class="sq" style="background:var(--bar-soft)"></i>Watching bots<b class="num">${fmt(live.bot_matches)}</b></div>
          <div><i class="sq" style="border:1px solid var(--faint)"></i>In menus<b class="num">${fmt(live.in_menus)}</b></div>
        </div>
      </section>
      <section class="cell flush">
        <div class="panel-head pad"><span class="title">Players</span><span class="count">${fmt(state.shell?.month?.this)}</span><span class="push">${seg('ov-tab', [['all', 'All'], ['new', 'New'], ['regulars', 'Regulars']], 'all')}</span></div>
        ${d.players.length ? `<div class="scroll"><table class="table"><thead><tr><th>Player</th><th>Status</th><th>Games · 7d</th><th class="r wide">Win rate</th><th class="r wide">Avg game</th><th class="r wide">Last seen</th></tr></thead><tbody>
          ${d.players.map((p) => `<tr data-act="open-player" data-id="${esc(p.id)}"><td>${who(p)}</td><td>${statusPill(p.status)}</td>
            <td class="num">${fmt(p.games)}${phone() ? '' : `<span class="mini">${miniBars(p.week)}</span>`}</td><td class="r wide">${pct(p.win_rate)}</td><td class="r wide">${dur(p.avg_game)}</td>
            <td class="r wide ${p.status !== 'offline' ? 'up' : ''}">${p.status !== 'offline' ? 'now' : ago(p.last_seen)}</td></tr>`).join('')}
        </tbody></table></div>` : '<div class="empty">No players yet.</div>'}
      </section>
      <section class="cell flush">
        <div class="panel-head pad"><span class="title">Needs attention</span><span class="count">${d.attention.length}</span></div>
        ${d.attention.length ? d.attention.map(attention).join('') : `<div class="empty">${icon('circleCheck')}<br>Nothing needs attention.</div>`}
      </section>
      <section class="cell">
        <div class="panel-head"><span class="title">When people play</span>
          <div class="legend"><span>Quiet</span>${[0.15, 0.35, 0.55, 0.8, 1].map((s) => `<i class="sq" style="background:${shade(s * maxHeat)}"></i>`).join('')}<span>Busy</span></div></div>
        <div class="heat">${d.heatmap.map((row, i) => `<span>${WEEKDAYS[i].toUpperCase()}</span>${row.map((v, h) => `<i style="background:${shade(v)}" title="${WEEKDAYS[i]} ${h}:00 · ${v} games"></i>`).join('')}`).join('')}</div>
        <div class="heat-axis"><span></span>${['00', '03', '06', '09', '12', '15', '18', '21'].map((h) => `<span>${h}</span>`).join('')}</div>
      </section>
      <section class="cell">
        <div class="panel-head"><span class="title">Coming back</span></div>
        <div style="margin-top:14px">
          <div class="back-row"><div><div class="eyebrow">Next day</div>${delta(cb.next_day, cb.next_day_prev, { kind: 'pt' })}</div>${dash(cb.next_day)}<div class="big">${pct(cb.next_day)}</div></div>
          <div class="back-row"><div><div class="eyebrow">After 7 days</div>${delta(cb.after_7, cb.after_7_prev, { kind: 'pt' })}</div>${dash(cb.after_7)}<div class="big">${pct(cb.after_7)}</div></div>
          <div class="back-row"><div><div class="eyebrow">Regulars</div><div class="delta">played 3+ days this week</div></div>${dash(Math.min(1, cb.regulars / Math.max(1, d.kpis.players)))}<div class="big">${fmt(cb.regulars)}</div></div>
        </div>
      </section>
    </div>`;
  };
  const miniBars = (values) => {
    const max = Math.max(1, ...values);
    return values.map((v) => `<i style="height:${Math.max(8, (v / max) * 100)}%"></i>`).join('');
  };

  PAGE_RENDER.players = (d) => {
    const k = d.kpis;
    const sorts = [['last_seen', 'Last seen'], ['games', 'Games'], ['win_rate', 'Win rate'], ['joined', 'Joined'], ['name', 'Name']];
    const rows = d.rows.map((p) => `<tr class="${state.sel.players === p.id ? 'on' : ''}" data-act="select" data-id="${esc(p.id)}">
      <td>${who(p, { inline: true, tag: p.new ? '<span class="tag-new">NEW</span>' : '' })}</td><td>${statusPill(p.status)}</td>
      <td class="r wide">${day(p.joined)}</td><td class="r num">${fmt(p.games)}</td><td class="r wide">${pct(p.win_rate)}</td><td class="r wide">${pct(p.bluff_rate)}</td>
      <td class="r wide ${p.status !== 'offline' ? 'up' : ''}">${p.status !== 'offline' ? 'now' : ago(p.last_seen)}</td></tr>`).join('');
    return `<div class="kpis">
      ${kpi('Total players', fmt(k.total), delta(k.total, k.total_prev, { label: 'vs last month' }), spark(k.total_spark))}
      ${kpi('New this week', fmt(k.new_week), delta(k.new_week, k.new_week_prev, { label: 'vs prev 7d' }), spark(k.new_spark))}
      ${kpi('Online now', fmt(k.online), `<div class="delta">${fmt(k.record)} record all-time high</div>`, spark(k.online_spark))}
      ${kpi('Regulars', fmt(k.regulars), delta(k.regulars, k.regulars_prev, { kind: 'abs', label: 'played 3+ days' }), spark(k.regulars_spark))}
      ${kpi('Churned · 30d', fmt(k.churned), `<div class="delta"><span class="${k.churned_change > 0 ? 'down' : ''}">${k.churned_change >= 0 ? '+' : '−'}${Math.abs(k.churned_change)}</span> no game in 14 days</div>`, spark(k.churned_spark, 'red'))}
    </div>
    <div class="grid">
      <section class="cell flush">
        <div class="panel-head pad"><span class="title">All players</span><span class="count">${fmt(d.total)}</span>
          <span class="push" style="display:flex;gap:10px;flex-wrap:wrap">${seg('tab', [['all', 'All'], ['new', 'New'], ['regulars', 'Regulars'], ['inactive', 'Inactive']], state.tabs.players)}
          <label class="seg" style="padding:0 8px;align-items:center;gap:6px"><span class="mono" style="font-size:11px;color:var(--muted)">Sort:</span>
          <select id="sort" data-sort class="mono" style="border:0;background:none;font-size:11px;outline:0">${sorts.map(([v, l]) => `<option value="${v}" ${state.sort === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label></span></div>
        ${d.rows.length ? `<div class="scroll"><table class="table"><thead><tr><th>Player</th><th>Status</th><th class="r wide">Joined</th><th class="r">Games</th><th class="r wide">Win rate</th><th class="r wide">Bluff rate</th><th class="r wide">Last seen</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="empty">No players match.</div>'}
        ${pager(d)}
      </section>
      <aside class="cell flush rail ${phone() && state.detail ? 'open' : ''}" data-keep-scroll="rail">${playerRail(state.detail)}</aside>
    </div>`;
  };

  const pager = (d) => {
    if (d.total <= d.page_size) return '';
    const from = d.page * d.page_size;
    return `<div class="pager"><span>${from + 1}–${Math.min(d.total, from + d.page_size)} of ${fmt(d.total)}</span><div>
      <button class="icon-btn" data-act="page" data-v="-1" ${d.page === 0 ? 'disabled' : ''} aria-label="Previous page">${icon('left')}</button>
      <button class="icon-btn" data-act="page" data-v="1" ${from + d.page_size >= d.total ? 'disabled' : ''} aria-label="Next page">${icon('right')}</button></div></div>`;
  };

  function railHead(title, closeAct = 'close') {
    return `<div class="rail-head"><span class="title">${phone() ? `<button class="link" data-act="${closeAct}">${icon('left')} Back</button>` : esc(title)}</span>${phone() ? '' : `<button class="icon-btn" style="border:0;background:none" data-act="${closeAct}" aria-label="Close">${icon('x')}</button>`}</div>`;
  }

  function playerRail(p) {
    if (!p) return `${railHead('Player')}<div class="empty">Pick a player to see their games.</div>`;
    const b = p.bluffing;
    const plat = { ios: 'iPhone', android: 'Android', web: 'Web' }[p.platform] || p.platform;
    const wins = p.last20.filter((g) => g.won).length;
    const quits = p.last20.filter((g) => g.quit).length;
    const monthAvg = p.month.reduce((a, b2) => a + b2, 0) / 30;
    const slot = p.plays_most ? `${WEEKDAYS[p.plays_most[0]]} · ${p.plays_most[1] * 2}-${p.plays_most[1] * 2 + 2}h` : '—';
    const meter = (label, share, value, cls = '') => `<div class="meter"><span>${label}</span>${dash(share, 24, cls)}<span class="num">${value}</span></div>`;
    return `${railHead('Player')}
      <div class="sec" style="display:flex;gap:14px;align-items:center">${avatar(p, 'big')}<div style="flex:1;min-width:0">
        <div style="font-size:18px" class="${p.auto ? 'auto' : ''}">${esc(p.name)} <span class="who-id">#${esc(p.sid)}</span></div>
        <div class="delta" style="margin-top:4px;white-space:normal">First seen ${day(p.first_seen)}${plat ? ` · ${esc(plat)}` : ''}${p.app_version ? ` · v${esc(p.app_version)}` : ''}${p.locked ? ` · ${icon('lock')} locked` : ''}</div></div>${statusPill(p.status)}</div>
      <div class="quad"><div><div class="eyebrow">Games</div><div class="big">${fmt(p.games)}</div></div><div><div class="eyebrow">Win rate</div><div class="big">${pct(p.win_rate)}</div></div>
        <div><div class="eyebrow">Avg game</div><div class="big">${dur(p.avg_game)}</div></div><div><div class="eyebrow">Day streak</div><div class="big">${fmt(p.streak)}</div></div></div>
      <div class="sec"><div class="panel-head"><span class="eyebrow">Last ${p.last20.length} games</span><span class="push delta" style="margin:0">${wins} W · ${p.last20.length - wins - quits} L · ${quits} quit</span></div>
        <div class="games20">${p.last20.map((g) => `<i class="${g.quit ? 'q' : g.won ? 'w' : ''}"></i>`).join('') || '<span class="delta">No games yet</span>'}</div>
        <div class="legend" style="margin:0"><span><i class="sq" style="background:var(--text)"></i>Won</span><span><i class="sq" style="background:var(--track)"></i>Lost</span><span><i class="sq" style="background:var(--red)"></i>Quit early</span></div></div>
      <div class="sec"><div class="eyebrow" style="margin-bottom:10px">Bluffing</div>
        ${meter('Bluffs made', b.bets ? b.bluffs / b.bets : 0, `${fmt(b.bluffs)} · ${pct(b.bets ? b.bluffs / b.bets : null)} of bets`)}
        ${meter('Bluffs caught', b.bluffs ? b.caught / b.bluffs : 0, `${fmt(b.caught)} · ${pct(b.bluffs ? b.caught / b.bluffs : null)}`)}
        ${meter('Checks right', b.checks ? b.called_right / b.checks : 0, pct(b.checks ? b.called_right / b.checks : null))}
        ${meter('Timer ran out', Math.min(1, b.timeouts / Math.max(1, p.games)), fmt(b.timeouts), 'amber')}
        <div class="kv" style="margin-top:8px;border-top:1px solid var(--border)"><span>Win rate</span><span style="display:flex;gap:6px"><span class="chip">vs bots ${pct(p.vs_bots)}</span><span class="chip">vs people ${pct(p.vs_people)}</span></span></div></div>
      <div class="sec"><div class="panel-head"><span class="eyebrow">Games · 30 days</span><span class="push delta" style="margin:0">avg ${monthAvg.toFixed(1)} / day</span></div>
        <div class="bars30">${miniBars(p.month)}</div></div>
      <div class="sec"><div class="eyebrow" style="margin-bottom:6px">Habits</div>
        <div class="kv"><span>Plays most</span><span>${slot}</span></div>
        <div class="kv"><span>Favorite room</span><span>${esc(p.favorite_room || '—')}</span></div>
        <div class="kv"><span>Usual table</span><span>${p.usual_table ? `${p.usual_table} players` : '—'}</span></div></div>
      <div class="actions"><button class="btn primary" data-act="player-games" data-sid="${esc(p.sid)}">${icon('layers')}View games</button><button class="btn" data-act="copy" data-v="${esc(p.id)}">${icon('copy')}Copy ID</button></div>`;
  }

  PAGE_RENDER.games = (d) => {
    const k = d.kpis;
    const h = d.by_hour;
    const max = Math.max(1, ...h.today, ...h.usual);
    const hourCols = h.today.map((v, i) => `<div class="col pair" title="${String(i).padStart(2, '0')}:00 · today ${v} · usual ${h.usual[i].toFixed(1)}">
      <i class="bt" style="height:${(h.usual[i] / max) * 100}%"></i>
      <span>${h.abandoned[i] ? `<i class="ab" style="display:block;height:${Math.max(1.5, (h.abandoned[i] / max) * 100)}%"></i><i class="gap"></i>` : ''}<i class="rl" style="display:block;height:${((v - h.abandoned[i]) / max) * 100}%;${i === h.hour ? 'background:var(--text)' : ''}"></i></span></div>`).join('');
    const sizes = Math.max(1, ...d.sizes.map((s) => s[1]));
    const biggest = Math.max(...d.sizes.map((s) => s[1]));
    const level = (name, v, first) => `<div style="flex:1;${first ? '' : 'padding-left:14px;border-left:1px solid var(--border)'}"><div class="eyebrow">${name}</div>
      ${v == null ? '<div style="margin-top:14px;display:flex;align-items:center;gap:10px"><span style="width:20px;height:2px;background:var(--faint)"></span><span class="foot">no bots yet</span></div>' : `<div class="big ${v >= 0.5 ? 'up' : v < 0.35 ? 'down' : ''}" style="margin-top:8px">${pct(v)}</div>`}</div>`;
    const rows = d.rows.map((g) => {
      const result = g.result === 'finished' ? '<span class="pill green">Finished</span>' : g.result === 'abandoned' ? '<span class="pill red">Abandoned</span>' : '<span class="pill">In progress</span>';
      const winner = g.winner ? (g.winner.bot ? `<span class="who">${avatar({ bot: true })}<span class="muted">${esc(nameOf(g.winner))}</span></span>` : `<span class="${g.winner.auto ? 'auto' : ''}">${esc(g.winner.name)}</span>`) : '<span style="color:var(--faint)">—</span>';
      return `<tr data-act="game" data-id="${esc(g.key)}"><td><div>#${g.number}${g.bot_match ? ' <span class="word-tag">' + icon('bot') + 'Bot match</span>' : ''}</div><div class="who-id">${esc(g.table)}</div></td>
        <td class="wide"><div class="avs">${g.players.map((p) => avatar(p)).join('')}${Array.from({ length: g.bots }, () => avatar({ bot: true })).join('')}</div></td>
        <td class="r wide ${g.bots ? '' : 'auto'}">${fmt(g.bots)}</td><td class="r wide">${g.rounds == null ? '—' : fmt(g.rounds)}</td><td class="r wide">${g.bluffs == null ? '—' : fmt(g.bluffs)}</td>
        <td class="r">${dur(g.seconds)}</td><td class="wide">${winner}</td><td>${result}${g.quits ? `<div class="warn mono" style="font-size:10px;margin-top:3px">${g.quits} quit</div>` : ''}</td><td class="r wide">${clock(g.start)}</td></tr>`;
    }).join('');
    const tables = state.allTables ? d.live_tables : d.live_tables.slice(0, 6);
    return `<div class="kpis">
      ${kpi('Games played', fmt(k.games), delta(k.games, k.games_prev), spark(k.games_spark))}
      ${kpi('Avg game length', dur(k.avg_game), delta(k.avg_game, k.avg_game_prev, { kind: 'dur' }), spark(k.avg_spark))}
      ${kpi('Players / table', k.seats == null ? '—' : k.seats.toFixed(1), delta(k.seats, k.seats_prev, { kind: 'dec', label: 'avg seats taken' }), spark(k.seats_spark))}
      ${kpi('Games with bots', pct(k.with_bots), delta(k.with_bots, k.with_bots_prev, { kind: 'pt', label: 'of all games' }), spark(k.bots_spark))}
      ${kpi('Abandoned', pct(k.abandoned, 1), delta(k.abandoned, k.abandoned_prev, { kind: 'pt', bad: true, label: 'quit before end' }), spark(k.abandoned_spark, 'red'))}
    </div>
    <div class="grid">
      <section class="cell"><div class="panel-head"><span class="title">Games by hour · today vs usual</span>
        <div class="legend"><span><i class="sq" style="background:var(--text)"></i>Today</span><span><i class="sq" style="background:var(--bar-soft)"></i>Usual</span><span><i class="sq" style="background:var(--red)"></i>Abandoned</span></div></div>
        <div class="chart" style="margin-top:24px">${hourCols}</div>
        <div class="axis">${h.today.map((_, i) => `<span class="${i === h.hour ? 'on' : ''}">${i % 3 === 0 ? String(i).padStart(2, '0') : ''}</span>`).join('')}</div></section>
      <section class="cell"><div class="panel-head"><span class="title">Table size</span></div>
        <div style="display:grid;gap:9px;margin-top:16px">${d.sizes.map(([n, c]) => `<div style="display:grid;grid-template-columns:70px 1fr 46px;align-items:center;gap:10px;font:400 11px var(--mono)">
          <span>${n} players</span><span style="height:9px"><i style="display:block;height:100%;width:${(c / sizes) * 100}%;background:${c === biggest && c ? 'var(--text)' : 'var(--bar)'}"></i></span><span class="r num" style="text-align:right">${fmt(c)}</span></div>`).join('')}</div>
        <div style="margin-top:22px;padding-top:16px;border-top:1px solid var(--border)"><div class="eyebrow">Win rate vs bots</div>
          <div style="display:flex;margin-top:14px">${level('Easy', d.vs_bots.easy, true)}${level('Medium', d.vs_bots.medium)}${level('Hard', d.vs_bots.hard)}</div></div></section>
      <section class="cell flush"><div class="panel-head pad"><span class="title">Recent games</span><span class="push">${seg('tab', [['all', 'All'], ['finished', 'Finished'], ['abandoned', 'Abandoned'], ['bots', 'With bots']], state.tabs.games)}</span></div>
        ${d.rows.length ? `<div class="scroll"><table class="table"><thead><tr><th>Game</th><th class="wide">Players</th><th class="r wide">Bots</th><th class="r wide">Rounds</th><th class="r wide">Bluffs</th><th class="r">Length</th><th class="wide">Winner</th><th>Result</th><th class="r wide">Start</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="empty">No games in this range yet.</div>'}
        ${pager(d)}</section>
      <section class="cell flush"><div class="panel-head pad"><span class="title">Live tables</span><span class="count">${d.live_tables.length}</span><span class="push live-dot">Live</span></div>
        ${tables.map((t) => `<div class="live-table"><div class="line"><b>${esc(t.table)}</b>${t.bot_match ? `<span class="word-tag">${icon('bot')}Bot match</span>` : ''}<span class="push mono num">${dur(t.seconds)}</span></div>
          <div style="margin:6px 0 10px"><small>${t.players.map((p) => `<span class="${p.auto ? 'auto' : ''}">${esc(p.name)}</span>`).join(' · ')}${t.bots ? `${t.players.length ? ' · ' : ''}${t.bots} bot${t.bots > 1 ? 's' : ''}` : ''}</small></div>
          <div class="line"><small>Round ${t.round} · ${t.left} of ${t.seats} left · ${t.cards} cards in play</small>${t.bid ? `<span class="push chip">${esc(t.bid)}</span>` : ''}</div></div>`).join('') || '<div class="empty">No one is playing right now.</div>'}
        ${d.live_tables.length > 6 ? `<div class="pager"><span>${state.allTables ? '' : `+${d.live_tables.length - 6} more tables`}</span><button class="link" data-act="all-tables">${state.allTables ? 'Show fewer' : `View all ${icon('right')}`}</button></div>` : ''}</section>
    </div>`;
  };

  function gameSheet() {
    const g = state.game;
    if (!g) return `<div class="rail open" style="display:block;position:fixed;inset:0 0 0 auto;width:min(440px,100%);z-index:30;background:var(--bg);border-left:1px solid var(--border)"><div class="empty">Loading…</div></div>`;
    const result = g.result === 'finished' ? '<span class="pill green">Finished</span>' : g.result === 'abandoned' ? '<span class="pill red">Abandoned</span>' : '<span class="pill">In progress</span>';
    const outText = (s, i) => (i === 0 && g.result === 'finished' ? '<span class="up">Winner</span>' : s.reason === 'left' ? `Left in round ${s.out_deal ?? '?'}` : s.reason === 'kicked' ? `Removed in round ${s.out_deal ?? '?'}` : s.out_deal ? `Out in round ${s.out_deal}` : 'Still in');
    const move = (m) => `<div style="display:grid;grid-template-columns:34px 110px 1fr;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font:400 11px var(--mono)">
      <span style="color:var(--faint)">R${m.deal}</span><span class="${m.who.auto ? 'auto' : ''}" style="overflow:hidden;text-overflow:ellipsis">${esc(nameOf(m.who))}</span>
      <span>${m.check ? `<span class="${m.held ? 'down' : 'up'}">checked · ${m.held ? 'bid was true' : 'bluff caught'}</span>` : `<span class="chip">${esc(betText(m.bet))}</span>`}${m.auto ? ' <span class="foot">timer</span>' : ''}</span></div>`;
    return `<div class="sheet-back" style="display:block;position:fixed;inset:0;background:#0004;z-index:29" data-act="close-game"></div>
      <div class="rail open" style="display:block;position:fixed;inset:0 0 0 auto;width:min(440px,100%);z-index:30;background:var(--bg);border-left:1px solid var(--border);overflow:auto" role="dialog" aria-label="Game ${g.number}">
      <div class="rail-head"><button class="link" data-act="close-game">${icon('left')} Games</button><button class="icon-btn" data-act="close-game" aria-label="Close">${icon('x')}</button></div>
      <div class="sec"><div class="panel-head"><span class="eyebrow">Game #${g.number}</span><span class="push">${result}</span></div>
        <div style="font-size:22px;margin:8px 0 6px">${esc(g.table)}</div>
        <div class="delta">${isToday(g.start) ? 'Today' : day(g.start)} ${clock(g.start)}${g.end ? ` – ${clock(g.end)}` : ''} · ${g.players.length} player${g.players.length === 1 ? '' : 's'}${g.bots ? ` + ${g.bots} bot${g.bots > 1 ? 's' : ''}` : ''}</div></div>
      <div class="quad"><div><div class="eyebrow">Rounds</div><div class="big">${g.rounds ?? '—'}</div></div><div><div class="eyebrow">Length</div><div class="big">${dur(g.seconds)}</div></div>
        <div><div class="eyebrow">Bluffs</div><div class="big">${g.bluffs ?? '—'}</div></div><div><div class="eyebrow">Checks</div><div class="big">${g.checks ?? '—'}</div></div></div>
      ${g.standing.length ? `<div class="sec"><div class="eyebrow" style="margin-bottom:8px">Final standing</div>
        ${g.standing.map((s, i) => `<div style="display:grid;grid-template-columns:20px auto 1fr auto;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid var(--border);font:400 12px var(--mono)">
          <span>${i + 1}</span>${avatar(s)}<div><div class="${s.auto ? 'auto' : ''}">${esc(nameOf(s))}${s.bot ? '' : ` <span class="who-id">#${esc(s.sid)}</span>`}</div><div class="foot" style="margin-top:2px">${outText(s, i)}</div></div><span>${s.bluffs} bluff${s.bluffs === 1 ? '' : 's'}</span></div>`).join('')}</div>` : ''}
      ${g.moves.length ? `<div class="sec"><div class="panel-head"><span class="eyebrow">Last rounds</span><span class="push foot">newest first</span></div>${g.moves.map(move).join('')}</div>` : ''}
      <div class="actions"><button class="btn primary" data-act="game-players" data-v="${esc(g.players.map((p) => p.sid).join(' '))}">${icon('users')}View players</button><button class="btn" data-act="copy" data-v="#${g.number}">${icon('copy')}Copy game #</button></div>
    </div>`;
  }

  PAGE_RENDER.problems = (d) => {
    const k = d.kpis;
    const maxReq = Math.max(1, ...d.hours.map((h) => h.requests));
    const maxErr = Math.max(1, ...d.hours.map((h) => h.errors));
    const cols = d.hours.map((h) => `<div class="col" title="${clock(h.t)} · ${h.errors} errors · ${fmt(h.requests)} requests">${h.errors ? `<i class="ab" style="height:${(h.errors / maxErr) * 45}%"></i>` : ''}<i class="bt" style="height:${Math.max(2, (h.requests / maxReq) * 50)}%"></i></div>`).join('');
    const dep = d.deploys[d.deploys.length - 1];
    const kinds = d.by_type.reduce((a, t) => a + t.count, 0);
    const kindColors = ['var(--red)', 'var(--text)', 'var(--bar)', 'var(--bar-soft)'];
    let cells = '';
    d.by_type.slice(0, 4).forEach((t, i) => { cells += Array.from({ length: Math.round((t.count / Math.max(1, kinds)) * 44) }, () => `<i style="background:${kindColors[i]}"></i>`).join(''); });
    const rows = d.rows.map((p) => {
      const [ic, tone] = PROBLEM_ICON[p.kind] || ['alert', ''];
      const st = p.status === 'open' ? '<span class="pill dark">Open</span>' : p.status === 'watching' ? '<span class="pill amber">Watching</span>' : '<span class="pill green">Resolved</span>';
      return `<tr class="${state.sel.problems === p.id ? 'on' : ''}" data-act="select" data-id="${esc(p.id)}">
        <td class="wide"><span class="sev ${p.severity}"><i></i><i></i><i></i>${p.severity[0].toUpperCase()}${p.severity.slice(1)}</span></td>
        <td><div class="prob"><span class="att-icon ${tone}">${icon(ic)}</span><div><b>${esc(p.title)}</b><small>${esc(p.subtitle)}</small></div></div></td>
        <td class="r wide">${whenShort(p.first_seen)}</td><td class="r">${fmt(p.count)}</td><td class="r wide">${p.players == null ? '—' : fmt(p.players)}</td><td class="r">${st}</td></tr>`;
    }).join('');
    return `<div class="kpis">
      ${kpi('Open problems', fmt(k.open), `<div class="delta"><span class="${k.open_new ? 'down' : ''}">+${k.open_new}</span> since yesterday</div>`)}
      ${kpi('Errors · 24h', fmt(k.errors), delta(k.errors, k.errors_prev, { kind: 'abs', bad: true, label: 'vs prev 24h' }), spark(k.errors_spark, 'red'))}
      ${kpi('Sessions without errors', pct(k.clean_sessions, 1), '<div class="delta">last 7 days</div>')}
      ${kpi('Reply time p95', k.p95 == null ? '—' : `${Math.round(k.p95)} ms`, delta(k.p95, k.p95_prev, { kind: 'ms', bad: true, label: 'vs prev hour' }))}
      ${kpi('Players affected', fmt(k.affected), '<div class="delta">today by any problem</div>')}
    </div>
    <div class="grid">
      <section class="cell"><div class="panel-head"><span class="title">Errors · last 24 hours</span>
        <div class="legend"><span><i class="sq" style="background:var(--red)"></i>Errors</span><span><i class="sq" style="background:var(--bar-soft)"></i>Requests (scaled)</span></div></div>
        <div class="chart" style="margin-top:24px;height:200px">${cols}</div>
        <div class="axis">${d.hours.map((h, i) => `<span>${i === 23 ? 'now' : i % 6 === 0 ? String(new Date(h.t * 1000).getHours()).padStart(2, '0') : ''}</span>`).join('')}</div>
        ${dep ? `<div class="note" style="margin-top:18px;color:var(--text)">${icon('right')}Server ${esc((dep.version || '').replace(/^server-?/, '') || '')} started at ${clock(dep.t)}${dep.errors_after != null ? ` · errors ${Math.max(1, Math.round(dep.errors_after / 60))} min later` : ' · no errors since'}</div>` : ''}</section>
      <section class="cell"><div class="panel-head"><span class="title">Errors by type</span></div>
        ${kinds ? `<div class="typebar">${cells}</div>${d.by_type.map((t, i) => `<div class="kv"><span style="display:flex;align-items:center;gap:10px;color:var(--text)"><i class="sq" style="background:${kindColors[i] || 'var(--faint)'}"></i>${esc(t.label)} <span class="foot">${esc(t.kind)}</span></span><span>${fmt(t.count)}</span></div>`).join('')}` : `<div class="empty" style="padding:30px 0">${icon('circleCheck')}<br>No errors in this range.</div>`}
        <div class="rejected"><div class="panel-head"><span class="eyebrow">Rejected requests · 24h</span><span class="push foot">not errors</span></div>
          <div class="rejected-row">${(d.rejected.length ? d.rejected : [{ label: 'None', count: 0 }]).map((r) => `<div><div style="font-size:17px">${fmt(r.count)}</div><div class="foot">${esc(r.label)}</div></div>`).join('')}</div></div></section>
      <section class="cell flush"><div class="panel-head pad"><span class="title">All problems</span><span class="push">${seg('tab', [['open', 'Open', d.counts.open], ['watching', 'Watching', d.counts.watching], ['resolved', 'Resolved', d.counts.resolved]], state.tabs.problems)}</span></div>
        ${d.rows.length ? `<div class="scroll"><table class="table"><thead><tr><th class="wide">Severity</th><th>Problem</th><th class="r wide">First seen</th><th class="r">Count</th><th class="r wide">Players</th><th class="r">Status</th></tr></thead><tbody>${rows}</tbody></table></div>` : `<div class="empty">${icon('circleCheck')}<br>Nothing here. The server is happy.</div>`}</section>
      <aside class="cell flush rail ${phone() && state.detail ? 'open' : ''}" data-keep-scroll="rail">${problemRail(state.detail)}</aside>
    </div>`;
  };

  function problemRail(p) {
    if (!p) return `${railHead('Problem')}<div class="empty">Pick a problem to see what happened.</div>`;
    const sevTone = p.severity === 'high' ? 'red' : p.severity === 'medium' ? 'amber' : '';
    const status = p.status === 'watching' ? `Watching${p.muted_until ? ` until ${clock(p.muted_until)}` : ''}` : p.status[0].toUpperCase() + p.status.slice(1);
    return `<div class="rail-head">${phone() ? `<button class="link" data-act="close">${icon('left')} Back</button>` : `<span class="title">${esc(p.title)}</span>`}<span class="pill ${sevTone}">${esc(p.severity[0].toUpperCase() + p.severity.slice(1))} · ${esc(status)}</span></div>
      <div class="sec"><div style="font-size:18px;margin:0 0 8px">${esc(p.subtitle)}</div><p class="mono" style="font-size:11px;line-height:1.6;margin:0">${esc(p.description || '')}</p></div>
      <div class="quad three" style="grid-template-columns:repeat(4,1fr)">
        <div><div class="eyebrow">First seen</div><div style="margin-top:6px">${whenShort(p.first_seen)}</div></div><div><div class="eyebrow">Last seen</div><div style="margin-top:6px">${ago(p.last_seen)}</div></div>
        <div><div class="eyebrow">Count</div><div style="margin-top:6px">${fmt(p.count)}</div></div><div><div class="eyebrow">Players</div><div style="margin-top:6px">${p.players == null ? '—' : fmt(p.players)}</div></div></div>
      ${p.events.length ? `<div class="sec"><div class="panel-head"><span class="eyebrow">Recent events</span><span class="push foot">auto-refresh</span></div>
        <div class="events">${p.events.slice(0, 12).map((e) => `<div title="${esc(e.message)}"><span>${new Date(e.t * 1000).toLocaleTimeString('en-GB')}</span><span class="err-tag">ERROR</span><span style="overflow:hidden;text-overflow:ellipsis">${esc(e.label)}${e.table ? ` · ${esc(e.table)}` : ''}</span><span class="who-id">${e.player === 'bot' ? 'bot' : `#${esc(e.player)}`}</span></div>`).join('')}</div></div>` : ''}
      <div class="actions" style="grid-template-columns:${p.status === 'open' ? '1.4fr 1fr 1fr' : '1fr 1fr'}">
        ${p.status === 'open' ? `<button class="btn primary" data-act="problem" data-v="resolve">${icon('check')}Mark resolved</button><button class="btn" data-act="problem" data-v="mute">${icon('mute')}Mute 1h</button>` : `<button class="btn primary" data-act="problem" data-v="reopen">${icon('reset')}Reopen</button>`}
        <button class="btn" data-act="copy-log">${icon('copy')}Copy log</button></div>`;
  }

  PAGE_RENDER.moderation = (d) => {
    const k = d.kpis;
    const tab = state.tabs.moderation;
    const rows = d.rows.filter((r) => !state.q.moderation || `${r.name} ${r.sid} ${r.now || ''}`.toLowerCase().includes(state.q.moderation.toLowerCase().replace(/^#/, '')));
    const table = rows.length ? `<div class="scroll"><table class="table"><thead><tr><th>Player</th><th>Reason</th><th class="r">Reports</th><th class="wide">Table</th><th class="r wide">Last</th><th class="r">Status</th></tr></thead><tbody>
      ${rows.map((r) => `<tr class="${state.sel.moderation === r.id ? 'on' : ''}" data-act="select" data-id="${esc(r.id)}">
        <td><div class="who-name">${esc(state.showWords ? r.name : r.masked)} ${r.masked !== r.name ? `<span style="color:var(--faint)">${icon(state.showWords ? 'eye' : 'eyeOff')}</span>` : ''}</div>
          <div class="who-id">#${esc(r.sid)}${r.now ? ` &nbsp;now: <span class="${r.now_auto ? 'auto' : ''}">${esc(r.now)}</span>` : ''}</div></td>
        <td>${reasonPill(r.reason)}${r.more ? ` <span class="foot">+${r.more}</span>` : ''}</td>
        <td class="r"><div>${r.count}</div><div class="foot">by ${r.by} player${r.by === 1 ? '' : 's'}</div></td><td class="wide">${esc(r.table)}</td>
        <td class="r wide">${ago(r.last)}</td><td class="r">${r.status === 'open' ? '<span class="pill ring dark">Open</span>' : r.status === 'dismissed' ? '<span class="pill">Dismissed</span>' : '<span class="pill green">Resolved</span>'}</td></tr>`).join('')}
      </tbody></table></div>` : `<div class="empty">${tab === 'open' ? `<span class="att-icon" style="margin:0 auto 14px;border-color:var(--green);color:var(--green);border-radius:50%;width:40px;height:40px">${icon('check')}</span><div style="font:400 15px var(--sans);color:var(--text)">No open reports. The tables are clean.</div>` : 'No reports yet.'}</div>`;
    const words = state.tabs.words === 'yours' ? `
      <div class="addword"><input id="word" class="field" data-word placeholder="Add a word…" value="${esc(state.wordInput)}" maxlength="30" autocomplete="off" spellcheck="false">
        <button class="check" data-act="whole" aria-pressed="${state.wordWhole}"><span class="switch ${state.wordWhole ? 'on' : ''}"></span>Whole word only</button>
        <button class="btn primary" data-act="add-word" ${state.wordInput.trim().length < 2 ? 'disabled' : ''}>${icon('plus')}Add</button></div>
      ${d.words.length ? `<div class="scroll"><table class="table"><thead><tr><th>Word</th><th>Matches</th><th class="r wide">Added</th><th class="r">Stopped</th><th></th></tr></thead><tbody>
        ${d.words.map((w) => `<tr><td>${esc(state.showWords ? w.word : w.masked)}</td><td><span class="word-tag">${icon(w.whole ? 'whole' : 'inside')}${w.whole ? 'Whole word' : 'Inside words'}</span></td>
          <td class="r wide">added ${day(w.added)}</td><td class="r">stopped ${w.stopped} name${w.stopped === 1 ? '' : 's'}</td>
          <td class="r" style="width:40px"><button class="icon-btn" style="border:0;background:none" data-act="remove-word" data-v="${esc(w.word)}" aria-label="Remove word">${icon('x')}</button></td></tr>`).join('')}</tbody></table></div>`
        : '<div class="empty">No words of your own yet. The built-in list still applies.</div>'}`
      : `<div class="sec"><div class="note">${icon('lock')}Read-only · managed on the server</div></div>
      ${Object.entries(d.builtin).map(([lang, list]) => `<div class="sec"><div class="panel-head"><span class="eyebrow">${lang} · ${list.length}</span><button class="push link" data-act="builtin-all" data-v="${lang}">${state.builtinAll[lang] ? 'Show less' : 'Show all'} ${icon('down')}</button></div>
        <div class="chips" style="${state.builtinAll[lang] ? '' : 'max-height:58px;overflow:hidden'}">${list.map((w) => `<span class="chip">${esc(w)}</span>`).join('')}</div></div>`).join('')}
      <div class="sec"><div class="note" style="border:1px solid var(--border);background:var(--surface);border-radius:6px;padding:10px 12px">${icon('info')}Built into the server. Catches look-alikes like a$$, f.u.c.k and fuuuck.</div></div>`;
    return `<div class="kpis">
      ${kpi('Open reports', fmt(k.open), `<div class="delta"><span class="${k.open_new ? 'down' : ''}">+${k.open_new}</span> since yesterday</div>`, spark(k.open_spark, 'red'))}
      ${kpi('Reports · 7d', fmt(k.week), `<div class="delta">from ${k.week_from} player${k.week_from === 1 ? '' : 's'}</div>`, spark(k.week_spark))}
      ${kpi('Names refused · 7d', fmt(k.refused), '<div class="delta">the filter stopped them</div>', spark(k.refused_spark))}
      ${kpi('Your blocked words', fmt(k.words), `<div class="delta">+ ${k.builtin} built-in</div>`, spark(k.words_spark))}
      ${kpi('Locked players', fmt(k.locked), '<div class="delta">can\'t change their name</div>', spark(k.locked_spark))}
    </div>
    <div class="grid">
      <div class="cell flush">
        <div class="panel-head pad"><span class="title">Reports</span><span class="count ${d.counts.open ? 'red' : ''}">${d.counts.open} open</span>
          <span class="push">${seg('tab', [['open', 'Open', d.counts.open], ['resolved', 'Resolved', d.counts.resolved], ['all', 'All', d.counts.all]], tab)}</span></div>
        ${table}
        <div class="panel-head pad" style="border-top:1px solid var(--border)"><span class="title">Blocked words</span>
          <span class="push">${seg('words-tab', [['yours', 'Your words', d.words.length], ['builtin', 'Built-in', k.builtin]], state.tabs.words)}</span></div>
        ${words}
        <div class="sec" style="border-top:1px solid var(--border)"><div class="note">${icon('info')}New names are checked against your words and the built-in list. Old names aren't changed.</div></div>
      </div>
      <aside class="cell flush">
        <div class="rail ${phone() && state.detail ? 'open' : ''}" data-keep-scroll="rail">${reportRail(state.detail)}</div>
        <div class="panel-head pad" style="border-top:1px solid var(--border)"><span class="title">Locked players</span><span class="count">${d.locked.length}</span><span class="push" style="color:var(--muted)">${icon('lock')}</span></div>
        ${d.locked.map((p) => `<div class="sec" style="display:flex;align-items:center;gap:12px"><span class="av">${icon('lock')}</span><div style="flex:1;min-width:0">
          <div class="${p.auto ? 'auto' : ''} mono" style="font-size:12px">${esc(p.name)} <span class="who-id">#${esc(p.sid)}</span></div><div class="foot">locked ${day(p.locked_at)}</div></div>
          <button class="link" data-act="unlock" data-id="${esc(p.id)}">${icon('unlock')}Unlock</button></div>`).join('') || '<div class="empty" style="padding:28px">No locked players.</div>'}
      </aside>
    </div>`;
  };

  function reportRail(r) {
    if (!r) return `${railHead('Reported player')}<div class="empty">Pick a report to act on it.</div>`;
    const plat = { ios: 'iPhone', android: 'Android', web: 'Web' }[r.platform] || r.platform;
    const status = r.status === 'open' ? '<span class="pill ring dark">Open</span>' : r.status === 'dismissed' ? '<span class="pill">Dismissed</span>' : '<span class="pill green">Resolved</span>';
    const ACTION_TEXT = {
      reset_name: ['reset', (d) => `Name reset to <span class="auto">${esc(d.split(' → ')[1] || '')}</span>`],
      blocked_name: ['ban', () => 'Old name blocked for everyone'], locked: ['lock', () => 'Name locked <span class="foot">they can\'t rename</span>'],
      unlocked: ['unlock', () => 'Name unlocked'], dismissed: ['x', () => 'Report dismissed'], resolved: ['check', () => 'Marked resolved'], reopened: ['reset', () => 'Reopened'],
    };
    const open = r.status === 'open';
    return `${railHead('Reported player')}
      <div class="sec"><div style="display:flex;align-items:center;gap:10px"><span style="font:400 21px var(--mono)">${esc(state.showWords ? r.name : r.masked)}</span>
        <button class="icon-btn" style="width:24px;height:24px" data-act="words" aria-label="Show or hide words">${icon(state.showWords ? 'eyeOff' : 'eye')}</button><span class="push">${status}</span></div>
        <div class="delta" style="margin-top:8px">#${esc(r.sid)} &nbsp;First seen ${day(r.first_seen)}${plat ? ` · ${esc(plat)}` : ''}${r.now ? ` &nbsp;now: <span class="${r.now_auto ? 'auto' : ''}">${esc(r.now)}</span>` : ''}</div></div>
      <div class="quad three"><div><div class="eyebrow">Reports</div><div class="big">${r.reports.length}</div></div><div><div class="eyebrow">Names refused</div><div class="big">${r.refused.length}</div></div><div><div class="eyebrow">Games</div><div class="big">${fmt(r.games)}</div></div></div>
      <div class="sec"><div class="panel-head"><span class="eyebrow">Reports</span><span class="push foot">${r.reports.length} from ${r.reporters} player${r.reporters === 1 ? '' : 's'}</span></div>
        ${r.reports.map((x) => `<div style="display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)">${reasonPill(x.reason)}
          <div class="mono" style="font-size:11px">by #${esc(x.by)}<div class="foot">${esc(x.table)}${x.note ? ` · “${esc(x.note)}”` : ''}</div></div><span class="foot">${ago(x.t)}</span></div>`).join('')}</div>
      ${r.refused.length ? `<div class="sec"><div class="panel-head"><span class="eyebrow">Names the filter refused</span><span class="push foot">${r.refused.length} tries</span></div>
        <div class="chips">${r.refused.slice(0, 12).map((n) => `<span class="chip">${esc(state.showWords ? n.name : n.masked)}</span>`).join('')}</div></div>` : ''}
      ${open ? `<div class="sec"><div class="eyebrow" style="margin-bottom:12px">Actions</div>
        <button class="btn primary wide" data-act="reset-name">${icon('reset')}Reset name</button>
        <div class="panel-head" style="margin:10px 0 14px"><span class="foot" style="font-size:11px">New name: <span class="auto" style="color:var(--text)">${esc(state.newName || '')}</span></span><button class="push btn sm" data-act="another">${icon('shuffle')}Another</button></div>
        <button class="check" data-act="block-old">${`<span class="box ${state.blockOld ? 'on' : ''}">${state.blockOld ? icon('check') : ''}</span>`}Also block this name for everyone</button>
        <button class="check" style="margin-top:12px" data-act="lock-name"><span class="switch ${state.lockName || r.locked ? 'on' : ''}"></span>Lock name: <span class="foot" style="font-size:11px">they can't rename anymore</span></button>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:18px"><button class="btn" data-act="moderate" data-v="dismiss">${icon('x')}Dismiss report</button><button class="btn" data-act="moderate" data-v="resolve">${icon('check')}Mark resolved</button></div></div>`
        : `${r.actions.length ? `<div class="sec"><div class="eyebrow">What was done</div><div class="done">${r.actions.map((a) => { const [ic, text] = ACTION_TEXT[a.action] || ['info', () => esc(a.action)]; return `<div>${icon(ic)}${text(a.detail)}</div>`; }).join('')}</div></div>` : ''}
        <div class="sec" style="display:flex;align-items:center;gap:8px;font:400 11px var(--mono)">${icon('circleCheck')}${r.status === 'dismissed' ? 'Dismissed' : 'Resolved'} by you · ${day(r.handled_at)} ${clock(r.handled_at)}<button class="push link" data-act="moderate" data-v="reopen">Reopen</button></div>`}`;
  }

  // ----- product: feedback, changelog, requests ---------------------------------
  const PRIORITY = { high: ['High', 'red'], medium: ['Medium', ''], low: ['Low', ''] };
  const priorityPill = (p) => `<span class="pill ${PRIORITY[p]?.[1] || ''}">${esc(PRIORITY[p]?.[0] || p)}</span>`;
  const doneOrOpen = (resolved) => (resolved ? '<span class="pill green">Resolved</span>' : '<span class="pill ring dark">Open</span>');
  const dateLong = (t) => (t ? new Date(t * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—');
  const isoDay = (d) => (d ? Date.parse(`${d}T12:00:00`) / 1000 : null);

  PAGE_RENDER.more = () => `<div class="more-list">${MORE_PAGES.map((id) => {
    const [, label, ic] = PAGES.find((p) => p[0] === id);
    const count = badge(id);
    const sub = { moderation: 'Reports and blocked words', feedback: 'What players tell you, from PocketBase', changelog: 'What changed in each version', requests: 'Your board and what players asked for' }[id];
    return `<a href="#/${id}"><span class="att-icon">${icon(ic)}</span><span><b>${label}</b><small>${sub}</small></span>${count ? `<span class="badge ${id === 'feedback' ? 'soft' : ''}">${count}</span>` : ''}${icon('right')}</a>`;
  }).join('')}</div>`;

  PAGE_RENDER.feedback = (d) => {
    if (!d.setup) return `<div class="empty">${icon('message')}<br><br>Feedback isn't connected yet.<br>Set FEEDBACK_PB_URL, FEEDBACK_PB_EMAIL and FEEDBACK_PB_PASSWORD on the server.</div>`;
    const k = d.kpis;
    const tab = state.tabs.feedback;
    const rows = d.rows.map((f) => `<tr class="${state.sel.feedback === f.id ? 'on' : ''}" data-act="select" data-id="${esc(f.id)}">
        <td class="r-when"><div>${whenShort(f.t)}</div><div class="foot">${ago(f.t)}</div></td>
        <td class="fb-msg"><div class="clamp ${f.test ? 'muted' : ''}">${esc(f.message) || '<span class="foot">No text</span>'}</div>
          <div class="tags">${f.place ? `<span class="word-tag">${esc(f.place)}</span>` : ''}${f.has_logs ? `<span class="word-tag red">${icon('file')}Crash log</span>` : ''}${f.shots ? `<span class="word-tag">${icon('image')}${f.shots > 1 ? f.shots : ''}Screenshot</span>` : ''}${f.audio ? `<span class="word-tag">${icon('mic')}Voice</span>` : ''}${f.test ? '<span class="word-tag">Looks like a test</span>' : ''}</div></td>
        <td class="wide">${f.version ? `v${esc(f.version)}` : '<span class="foot">—</span>'}</td>
        <td class="wide">${priorityPill(f.priority)}</td><td class="r">${doneOrOpen(f.resolved)}</td></tr>`).join('');
    const empty = tab === 'open' ? `${icon('circleCheck')}<br>Nothing open. Every message has been handled.` : 'No feedback here.';
    return `${d.error === 'unreachable' ? `<div class="banner">${icon('circleAlert')}PocketBase can't be reached right now. This is the last copy.</div>` : ''}
    <div class="kpis">
      ${kpi('Open', fmt(k.open), `<div class="delta">${k.open_high ? `<span class="down">${k.open_high} high priority</span>` : 'none high priority'}</div>`)}
      ${kpi('New · 7 days', fmt(k.week), delta(k.week, k.week_prev, { kind: 'abs', label: 'vs prev 7 days' }), spark(k.per_day))}
      ${kpi('Crash reports', fmt(k.crashes), `<div class="delta">open · ${fmt(k.crashes_all)} all time</div>`)}
      ${kpi('With screenshot', fmt(k.shots), `<div class="delta">of ${fmt(k.total)} messages</div>`)}
      ${kpi('Resolved', pct(k.total ? k.resolved / k.total : null), `<div class="delta">${fmt(k.resolved)} of ${fmt(k.total)}${k.tests ? ` · ${k.tests} tests hidden` : ''}</div>`)}
    </div>
    <div class="grid">
      <section class="cell flush">
        <div class="panel-head pad"><span class="title">Feedback</span><span class="count ${k.open_high ? 'red' : ''}">${k.open} open</span>
          <span class="push">${seg('tab', [['open', 'Open', d.counts.open], ['resolved', 'Resolved', d.counts.resolved], ['all', 'All', d.counts.all]], tab)}</span></div>
        ${d.rows.length ? `<div class="scroll"><table class="table fb"><thead><tr><th>When</th><th>Message</th><th class="wide">Version</th><th class="wide">Priority</th><th class="r">Status</th></tr></thead><tbody>${rows}</tbody></table></div>` : `<div class="empty">${empty}</div>`}
        ${d.places.length ? `<div class="sec" style="border-top:1px solid var(--border)"><div class="panel-head"><span class="eyebrow">Open, by screen</span></div>
          <div class="chips">${d.places.map(([p, n]) => `<span class="chip">${esc(p)} · ${n}</span>`).join('')}</div></div>` : ''}
        <div class="sec" style="border-top:1px solid var(--border)"><div class="note">${icon('info')}Read from PocketBase every minute. Mark messages resolved in PocketBase.</div></div>
      </section>
      <aside class="cell flush rail ${phone() && state.detail ? 'open' : ''}" data-keep-scroll="rail">${feedbackRail(state.detail)}</aside>
    </div>`;
  };

  function feedbackRail(f) {
    if (!f) return `${railHead('Message')}<div class="empty">Pick a message to read it.</div>`;
    const plat = [f.place, f.version ? `v${f.version}` : '', f.sender].filter(Boolean).map(esc).join(' · ');
    return `<div class="rail-head">${phone() ? `<button class="link" data-act="close">${icon('left')} Back</button>` : '<span class="title">Message</span>'}<span style="display:flex;gap:6px">${priorityPill(f.priority)}${doneOrOpen(f.resolved)}</span></div>
      <div class="sec"><div class="fb-full">${esc(f.message) || '<span class="foot">No text, only a log.</span>'}</div>
        <div class="delta" style="margin-top:12px">${dateLong(f.t)} ${clock(f.t)}${plat ? ` · ${plat}` : ''}</div></div>
      ${f.screenshots.length ? `<div class="sec"><div class="eyebrow" style="margin-bottom:12px">Screenshot${f.screenshots.length > 1 ? 's' : ''}</div>
        <div class="shots">${f.screenshots.map((s) => `<a href="${esc(s.full)}" target="_blank" rel="noopener noreferrer"><img src="${esc(s.thumb)}" alt="Screenshot from the player" loading="lazy"></a>`).join('')}</div></div>` : ''}
      ${f.audio_url ? `<div class="sec"><div class="eyebrow" style="margin-bottom:12px">Voice note</div><audio controls preload="none" src="${esc(f.audio_url)}" style="width:100%"></audio></div>` : ''}
      ${f.notes ? `<div class="sec"><div class="eyebrow" style="margin-bottom:8px">Your notes</div><div class="mono" style="font-size:11.5px;white-space:pre-wrap">${esc(f.notes)}</div></div>` : ''}
      ${f.logs ? `<div class="sec"><div class="panel-head"><span class="eyebrow">Crash log</span><span class="push foot">${f.logs_cut ? `last ${Math.round(f.logs.length / 1000)} of ${Math.round(f.logs_size / 1000)} KB` : `${Math.max(1, Math.round(f.logs_size / 1000))} KB`}</span></div>
        <pre class="logs">${esc(f.logs)}</pre></div>` : ''}
      <div class="actions" style="grid-template-columns:1.4fr 1fr"><a class="btn primary" href="${esc(f.pocketbase)}" target="_blank" rel="noopener noreferrer">${icon('external')}Open in PocketBase</a>
        <button class="btn" data-act="copy-feedback">${icon('copy')}Copy</button></div>`;
  }

  const KIND = { new: ['New', 'green'], better: ['Better', ''], fix: ['Fix', 'amber'] };
  PAGE_RENDER.changelog = (d) => {
    const released = d.releases.filter((r) => r.status === 'released');
    const next = d.releases.find((r) => r.status !== 'released');
    const shipped = released.reduce((n, r) => n + r.items.length, 0);
    const last = released[0];
    const byKind = (items, kind) => items.filter((i) => i.kind === kind).length;
    const month = now() - 30 * 86400;
    const recent = d.releases.reduce((n, r) => n + r.items.filter((i) => (isoDay(i.date || r.date) ?? now()) > month).length, 0);
    return `<div class="kpis">
      ${kpi('Releases', fmt(released.length), `<div class="delta">since ${dateLong(isoDay(released[released.length - 1]?.date))}</div>`)}
      ${kpi('Changes shipped', fmt(shipped), `<div class="delta">${released.reduce((n, r) => n + byKind(r.items, 'new'), 0)} new · ${released.reduce((n, r) => n + byKind(r.items, 'fix'), 0)} fixes</div>`)}
      ${kpi('Waiting to ship', fmt(next ? next.items.length : 0), '<div class="delta">in the next release</div>')}
      ${kpi('Last release', last ? esc(last.version) : '—', `<div class="delta">${last ? `${dateLong(isoDay(last.date))} · ${ago(isoDay(last.date))}` : ''}</div>`)}
      ${kpi('Changes · 30 days', fmt(recent), '<div class="delta">shipped or waiting to ship</div>')}
    </div>
    <section class="cell flush">${d.releases.map((r) => `<div class="release">
        <div class="rel-side"><div class="rel-version">${r.status === 'released' ? `v${esc(r.version)}` : 'Next'}</div>
          <div class="foot" style="margin-top:6px">${r.date ? dateLong(isoDay(r.date)) : 'not released yet'}</div>
          <div style="margin-top:10px">${r.status === 'released' ? '<span class="pill green">Released</span>' : '<span class="pill amber">In progress</span>'}</div></div>
        <div class="rel-body"><h3>${esc(r.title)}</h3>
          <div class="foot" style="margin-bottom:12px">${['new', 'better', 'fix'].map((k) => byKind(r.items, k) ? `${byKind(r.items, k)} ${KIND[k][0].toLowerCase()}` : '').filter(Boolean).join(' · ')}</div>
          ${r.items.map((i) => `<div class="rel-item"><span class="pill plain ${KIND[i.kind]?.[1] || ''}">${KIND[i.kind]?.[0] || esc(i.kind)}</span><span>${esc(i.text)}</span><span class="word-tag">${esc(i.area)}</span></div>`).join('')}</div>
      </div>`).join('')}
      <div class="sec"><div class="note">${icon('info')}Written by hand from the git history · updated ${dateLong(isoDay(d.updated))}</div></div>
    </section>`;
  };

  const COLUMNS = [['now', 'Now'], ['next', 'Next'], ['later', 'Later'], ['done', 'Done']];
  PAGE_RENDER.requests = (d) => {
    const col = (s) => d.items.filter((i) => (s === 'later' ? i.status === 'later' || i.status === 'idea' : i.status === s));
    const asked = d.items.filter((i) => i.feedback && i.feedback.length);
    const askedDone = asked.filter((i) => i.status === 'done');
    const card = (i) => `<div class="req">
        <div class="req-title">${esc(i.title)}</div>
        <div class="tags">${i.url ? `<a class="word-tag" href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">#${i.issue}${icon('external')}</a>` : ''}<span class="word-tag">${esc(i.area)}</span>${i.status === 'idea' ? '<span class="word-tag amber">Not on the board</span>' : ''}${i.shipped ? `<span class="word-tag green">${i.shipped === 'Next' ? 'In the next release' : `Shipped in ${esc(i.shipped)}`}</span>` : ''}</div>
        ${i.feedback && i.feedback.length ? `<div class="asked">${icon('message')}${i.feedback.length} player message${i.feedback.length > 1 ? 's' : ''}
          ${i.feedback.map((f) => f.message ? `<a href="#/feedback?tab=all&sel=${encodeURIComponent(f.id)}" class="quote">“${esc(f.message.length > 140 ? `${f.message.slice(0, 140)}…` : f.message)}”<span class="foot"> · ${day(f.t)}</span></a>` : '').join('')}</div>` : ''}
      </div>`;
    const tab = state.tabs.requests;
    const columns = phone() ? COLUMNS.filter(([s]) => s === tab) : COLUMNS;
    return `<div class="kpis">
      ${kpi('Now', fmt(col('now').length), '<div class="delta">being worked on</div>')}
      ${kpi('Next', fmt(col('next').length), '<div class="delta">up after that</div>')}
      ${kpi('Later', fmt(col('later').length), `<div class="delta">${d.items.filter((i) => i.status === 'idea').length} not on the board yet</div>`)}
      ${kpi('Done', fmt(col('done').length), '<div class="delta">on the board and from players</div>')}
      ${kpi('Players asked, you built', `${askedDone.length}<small style="font-size:14px;color:var(--muted)"> / ${asked.length}</small>`, '<div class="delta">requests from feedback</div>')}
    </div>
    ${phone() ? `<div class="sec seg-full" style="padding-top:16px;padding-bottom:16px">${seg('req-tab', COLUMNS.map(([s, l]) => [s, l, col(s).length]), tab)}</div>` : ''}
    <div class="board">${columns.map(([s, label]) => `<section class="board-col">
        <div class="panel-head" style="margin-bottom:14px"><span class="title">${label}</span><span class="count">${col(s).length}</span></div>
        ${col(s).map(card).join('') || '<div class="empty" style="padding:24px 0">Nothing here.</div>'}</section>`).join('')}</div>
    <div class="sec" style="border-top:1px solid var(--border)"><div class="note wrap">${icon('info')}From the GitHub board and player feedback, written by hand · updated ${dateLong(isoDay(d.updated))} · <a class="link" href="${esc(d.board)}" target="_blank" rel="noopener noreferrer">Open the board ${icon('external')}</a></div></div>`;
  };

  // ----- login --------------------------------------------------------------
  function renderLogin() {
    const l = state.login;
    const wait = Math.max(0, Math.ceil((l.until || 0) - now()));
    app.innerHTML = `<div class="login-wrap"><form class="login" data-login novalidate>
      <span class="logo">${icon('spade')}</span>
      <div class="eyebrow" style="margin-top:14px">Liar's Poker &nbsp;/&nbsp; Admin</div>
      <h1>Liar's Poker Stats</h1>
      <label class="eyebrow" for="pw">Password</label>
      <div class="pw ${l.error ? 'bad' : ''}"><input id="pw" type="${l.show ? 'text' : 'password'}" autocomplete="current-password" value="${esc(l.value || '')}" required aria-invalid="${!!l.error}" aria-describedby="pw-err">
        <button type="button" data-act="show-pw" aria-label="${l.show ? 'Hide' : 'Show'} password" style="color:var(--muted)">${icon(l.show ? 'eyeOff' : 'eye')}</button></div>
      ${l.error ? `<div class="err" id="pw-err" role="alert">${icon('circleAlert')}<span data-wait-text>${loginError(l, wait)}</span></div>` : ''}
      <button class="btn primary wide" type="submit" data-wait-btn ${wait || l.busy ? 'disabled' : ''}>${loginButton(l, wait)}</button>
      <div class="foot">${icon('lock')}Admin only</div></form></div>`;
    const input = document.getElementById('pw');
    if (input && !wait) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
  }

  const loginError = (l, wait) => `${esc(l.error)}${wait ? ` Try again in ${wait} s` : ''}`;
  const loginButton = (l, wait) => (l.busy ? 'Checking…' : wait ? `Log in · ${wait} s` : 'Log in');
  /** Counts the lock down without redrawing the form, so typing isn't lost. */
  function tickLogin() {
    const l = state.login;
    if (!l || !l.until) return;
    const wait = Math.max(0, Math.ceil(l.until - now()));
    const text = document.querySelector('[data-wait-text]');
    const button = document.querySelector('[data-wait-btn]');
    if (text) text.innerHTML = loginError(l, wait);
    if (button) { button.textContent = loginButton(l, wait); button.disabled = !!wait || !!l.busy; }
    if (!wait) l.until = 0;
  }

  async function login(form) {
    const l = state.login;
    l.value = form.querySelector('#pw').value;
    if (!l.value) return;
    l.busy = true;
    renderLogin();
    const res = await api('login', { password: l.value });
    l.busy = false;
    if (res.ok) {
      state.login = null;
      load();
      return;
    }
    l.error = res.error === 'wait' ? 'Too many tries.' : 'Wrong password.';
    l.until = now() + (res.wait || 0);
    l.value = '';
    renderLogin();
  }

  // ----- actions -------------------------------------------------------------
  function toast(text) {
    state.toast = text;
    render();
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { state.toast = null; render(); }, 2200);
  }
  const copy = async (text, what) => {
    try { await navigator.clipboard.writeText(text); toast(`${what} copied`); } catch { toast('Could not copy'); }
  };

  const ACTIONS = {
    range(el) { state.range = el.dataset.v; try { localStorage.setItem('lp_range', state.range); } catch { /* private mode */ } state.pageNo = { players: 0, games: 0 }; load(); },
    tab(el) { state.tabs[state.page] = el.dataset.v; state.pageNo[state.page] = 0; if (state.page !== 'players') state.sel[state.page] = null; load(); },
    'ov-tab'(el) { state.tabs.players = el.dataset.v; go('players', { tab: el.dataset.v }); },
    'words-tab'(el) { state.tabs.words = el.dataset.v; render(); },
    page(el) { state.pageNo[state.page] = Math.max(0, (state.pageNo[state.page] || 0) + Number(el.dataset.v)); load(); },
    select(el) {
      state.sel[state.page] = el.dataset.id;
      state.noDefault = null;
      state.newName = null; state.blockOld = true; state.lockName = false;
      state.detail = null;
      render();
      loadDetail(false);
    },
    close() { state.sel[state.page] = null; state.detail = null; state.noDefault = state.page; render(); },
    'open-player'(el) { go('players', { sel: el.dataset.id }); },
    'player-games'(el) { state.q.games = el.dataset.sid; go('games', { q: el.dataset.sid }); },
    'game-players'(el) { const first = el.dataset.v.split(' ')[0]; go('players', { q: first || '' }); },
    copy(el) { copy(el.dataset.v, el.dataset.v.startsWith('#') ? 'Game number' : 'ID'); },
    'copy-log'() {
      const p = state.detail;
      if (!p) return;
      copy([`${p.title} · ${p.subtitle}`, ...(p.events || []).map((e) => `${new Date(e.t * 1000).toISOString()} ${e.label} ${e.table} #${e.player} ${e.message}`)].join('\n'), 'Log');
    },
    game(el) { state.sheet = el.dataset.id; state.game = null; render(); loadDetail(false).then(render); },
    'close-game'() { state.sheet = null; state.game = null; render(); },
    'req-tab'(el) { state.tabs.requests = el.dataset.v; render(); },
    'copy-feedback'() {
      const f = state.detail;
      if (!f) return;
      copy([f.message, `${new Date(f.t * 1000).toISOString()} · ${f.place} · v${f.version} · ${f.priority}`, f.logs].filter(Boolean).join('\n\n'), 'Feedback');
    },
    'all-tables'() { state.allTables = !state.allTables; render(); },
    words() { state.showWords = !state.showWords; render(); },
    whole() { state.wordWhole = !state.wordWhole; render(); },
    'builtin-all'(el) { state.builtinAll[el.dataset.v] = !state.builtinAll[el.dataset.v]; render(); },
    async 'add-word'() {
      const word = state.wordInput.trim();
      if (word.length < 2) return;
      const res = await api('words/add', { word, whole: state.wordWhole });
      if (!res.ok) return toast('That word can\'t be added');
      state.wordInput = '';
      toast('Word added');
      load(true);
    },
    async 'remove-word'(el) {
      if (!window.confirm('Remove this word from your list?')) return;
      await api('words/remove', { word: el.dataset.v });
      toast('Word removed');
      load(true);
    },
    another() {
      const list = state.detail?.suggestions || [];
      state.newName = list[(list.indexOf(state.newName) + 1) % list.length] || state.newName;
      render();
    },
    'block-old'() { state.blockOld = !state.blockOld; render(); },
    'lock-name'() { state.lockName = !state.lockName; render(); },
    async 'reset-name'() {
      const r = state.detail;
      if (!r || !state.newName) return;
      const res = await api(`moderation/${encodeURIComponent(r.id)}`, { action: 'reset_name', name: state.newName, block: state.blockOld, lock: state.lockName });
      if (!res.ok) return toast(res.error === 'unknown_player' ? 'This player is gone from the server' : 'Could not reset the name');
      toast(`Renamed to ${state.newName}`);
      state.newName = null;
      load(true);
    },
    async moderate(el) {
      const r = state.detail;
      if (!r) return;
      await api(`moderation/${encodeURIComponent(r.id)}`, { action: el.dataset.v });
      toast(el.dataset.v === 'reopen' ? 'Reopened' : el.dataset.v === 'dismiss' ? 'Report dismissed' : 'Marked resolved');
      load(true);
    },
    async unlock(el) {
      await api(`moderation/${encodeURIComponent(el.dataset.id)}`, { action: 'unlock' });
      toast('Unlocked');
      load(true);
    },
    async problem(el) {
      const p = state.detail;
      if (!p) return;
      await api(`problems/${encodeURIComponent(p.id)}`, { action: el.dataset.v });
      toast({ resolve: 'Marked resolved', mute: 'Muted for an hour', reopen: 'Reopened' }[el.dataset.v]);
      load(true);
    },
    'show-pw'() { const input = document.getElementById('pw'); state.login.value = input.value; state.login.show = !state.login.show; renderLogin(); },
    async logout() { await api('logout', {}); state.login = { error: null }; renderLogin(); },
  };

  document.addEventListener('click', (event) => {
    const el = event.target.closest('[data-act]');
    if (!el || !app.contains(el)) return;
    const fn = ACTIONS[el.dataset.act];
    if (fn) { event.preventDefault(); fn(el); }
  });
  document.addEventListener('submit', (event) => {
    if (event.target.matches('[data-login]')) { event.preventDefault(); login(event.target); }
  });
  let searchTimer;
  document.addEventListener('input', (event) => {
    const el = event.target;
    if (el.matches('[data-search]')) {
      state.q[state.page] = el.value;
      clearTimeout(searchTimer);
      if (state.page === 'moderation') { render(); return; }
      searchTimer = setTimeout(() => { state.pageNo[state.page] = 0; load(); }, 250);
    } else if (el.matches('[data-word]')) {
      state.wordInput = el.value;
      const add = document.querySelector('[data-act="add-word"]');
      if (add) add.disabled = el.value.trim().length < 2;
    }
  });
  document.addEventListener('change', (event) => {
    if (event.target.matches('[data-sort]')) { state.sort = event.target.value; state.pageNo.players = 0; load(); }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === '/' && !/input|textarea|select/i.test(document.activeElement?.tagName || '')) {
      const search = document.getElementById('search');
      if (search) { event.preventDefault(); search.focus(); }
    } else if (event.key === 'Enter' && event.target.matches('[data-word]')) {
      ACTIONS['add-word']();
    } else if (event.key === 'Escape' && state.sheet) {
      ACTIONS['close-game']();
    }
  });

  // Chart tooltips.
  document.addEventListener('mouseover', (event) => {
    const col = event.target.closest('[data-tip]');
    const old = document.querySelector('.tip');
    if (old) old.remove();
    if (!col || !state.tipData) return;
    const card = col.closest('section')?.querySelector('[data-tipcard]');
    if (card) {
      card.innerHTML = tipCard(Number(col.dataset.tip));
      for (const c of col.parentElement.closest('[data-chart]').querySelectorAll('.col.hot')) c.classList.remove('hot');
      col.classList.add('hot');
      return;
    }
    const t = state.tipData[Number(col.dataset.tip)];
    if (!t) return;
    const host = col.closest('[data-chart]').parentElement;
    const box = col.getBoundingClientRect();
    const hostBox = host.getBoundingClientRect();
    const tip = document.createElement('div');
    tip.className = 'tip';
    tip.innerHTML = `<div class="eyebrow">${esc(t.label)}</div><b>${esc(t.total)}</b>${t.rows.map(([c, text]) => `<div><i class="sq" style="background:${c}"></i>${esc(text)}</div>`).join('')}`;
    host.appendChild(tip);
    const left = Math.min(hostBox.width - tip.offsetWidth, Math.max(0, box.left - hostBox.left + box.width / 2 - tip.offsetWidth / 2));
    tip.style.left = `${left}px`;
    tip.style.top = '0px';
  });

  // The "Updated 3s ago" line, every second; fresh data every 10 seconds.
  setInterval(() => {
    for (const el of document.querySelectorAll('[data-updated]')) el.outerHTML = updated();
    tickLogin();
  }, 1000);
  setInterval(() => {
    const typing = /input|select/i.test(document.activeElement?.tagName || '');
    if (!document.hidden && !state.login && !typing) load(true);
  }, 10000);
  window.addEventListener('hashchange', route);
  let wasPhone = phone();
  window.addEventListener('resize', () => { if (phone() !== wasPhone) { wasPhone = phone(); render(); } });
  route();
})();
