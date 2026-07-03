/**
 * Kingsfield Audio Player
 * ─────────────────────────────────────────────────────────────────────────────
 * Self-contained. Drop into any page with:
 *   <script src="/assets/js/kingsfield-player.js"></script>
 *
 * Three modes:
 *   Ambient  — background music, loops, user-controlled volume
 *   Events   — short branded clips, triggered by UI interactions
 *   Voice    — ElevenLabs intro/narrative clips
 *
 * Global API (for other scripts to trigger audio):
 *   KingsfieldAudio.playEvent('trust-verify')
 *   KingsfieldAudio.playAmbient('guillotine-hard')
 *   KingsfieldAudio.stop()
 *   KingsfieldAudio.setVolume(0.4)
 *
 * Config — set before the script loads to override defaults:
 *   window.KINGSFIELD_PLAYER_CONFIG = {
 *     apiBase: 'http://localhost:3001',  // backend URL
 *     startCollapsed: true,              // default true
 *     defaultVolume: 0.35,
 *     autoplayEvent: null,               // e.g. 'welcome-goliath' to play on first visit
 *   };
 */

(function() {
  'use strict';

  const CFG = Object.assign({
    apiBase:        '',           // same origin by default
    startCollapsed: true,
    defaultVolume:  0.35,
    autoplayEvent:  null,
  }, window.KINGSFIELD_PLAYER_CONFIG || {});

  // ── STATE ──────────────────────────────────────────────────────────────────
  let catalog = { ambient: [], events: [], voices: [] };
  let currentAudio = null;
  let currentTrack = null;
  let isPlaying    = false;
  let activeTab    = 'ambient';
  let volume       = CFG.defaultVolume;
  let expanded     = !CFG.startCollapsed;
  let catalogLoaded = false;

  // ── CSS ────────────────────────────────────────────────────────────────────
  const STYLE = `
    #kf-player {
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 9000;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      user-select: none;
    }
    #kf-player * { box-sizing: border-box; }

    /* Collapsed pill */
    #kf-pill {
      display: flex;
      align-items: center;
      gap: 8px;
      background: #111;
      border: 1px solid #2a2a2a;
      border-radius: 24px;
      padding: 8px 14px 8px 10px;
      cursor: pointer;
      transition: border-color 0.2s, background 0.2s;
    }
    #kf-pill:hover { border-color: #c9a84c; background: #161616; }
    #kf-pill-icon { width: 28px; height: 28px; }
    #kf-pill-label {
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #888;
      white-space: nowrap;
    }
    #kf-pill.playing #kf-pill-label { color: #c9a84c; }
    #kf-pill.playing { border-color: rgba(201,168,76,0.4); }

    /* Expanded panel */
    #kf-panel {
      background: #0e0e0e;
      border: 1px solid #2a2a2a;
      border-radius: 12px;
      width: 300px;
      overflow: hidden;
      box-shadow: 0 8px 40px rgba(0,0,0,0.7);
    }
    #kf-panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 14px 10px;
      border-bottom: 1px solid #1a1a1a;
    }
    #kf-panel-title {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #c9a84c;
    }
    #kf-close-btn {
      background: none;
      border: none;
      color: #555;
      font-size: 16px;
      cursor: pointer;
      line-height: 1;
      padding: 2px 4px;
    }
    #kf-close-btn:hover { color: #f5f5f0; }

    /* Now playing */
    #kf-now-playing {
      padding: 10px 14px;
      min-height: 44px;
      border-bottom: 1px solid #1a1a1a;
    }
    #kf-track-name {
      font-size: 13px;
      font-weight: 600;
      color: #f5f5f0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    #kf-track-cat {
      font-size: 10px;
      color: #555;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-top: 2px;
    }

    /* Progress bar */
    #kf-progress-wrap {
      padding: 6px 14px 0;
      cursor: pointer;
    }
    #kf-progress-bar {
      height: 2px;
      background: #2a2a2a;
      border-radius: 2px;
      overflow: hidden;
    }
    #kf-progress-fill {
      height: 100%;
      background: #c9a84c;
      width: 0%;
      transition: width 0.25s linear;
    }

    /* Controls */
    #kf-controls {
      display: flex;
      align-items: center;
      gap: 4px;
      padding: 8px 10px 10px;
    }
    .kf-ctrl-btn {
      background: none;
      border: none;
      color: #888;
      cursor: pointer;
      padding: 6px;
      border-radius: 6px;
      line-height: 0;
      transition: color 0.15s, background 0.15s;
    }
    .kf-ctrl-btn:hover { color: #f5f5f0; background: rgba(255,255,255,0.05); }
    .kf-ctrl-btn.active { color: #c9a84c; }
    #kf-play-btn {
      background: #c9a84c;
      border: none;
      border-radius: 50%;
      width: 34px; height: 34px;
      display: flex; align-items: center; justify-content: center;
      cursor: pointer;
      margin: 0 4px;
      color: #0a0a0a;
      transition: background 0.15s, transform 0.1s;
    }
    #kf-play-btn:hover { background: #d9b85c; transform: scale(1.05); }
    #kf-volume-wrap {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-left: auto;
    }
    #kf-volume-icon { color: #555; }
    #kf-vol-slider {
      -webkit-appearance: none;
      width: 60px; height: 2px;
      background: #2a2a2a;
      outline: none;
      border-radius: 2px;
      cursor: pointer;
    }
    #kf-vol-slider::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 10px; height: 10px;
      border-radius: 50%;
      background: #c9a84c;
      cursor: pointer;
    }

    /* Tabs */
    #kf-tabs {
      display: flex;
      border-bottom: 1px solid #1a1a1a;
    }
    .kf-tab {
      flex: 1;
      background: none;
      border: none;
      padding: 8px 4px;
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #555;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: color 0.15s, border-color 0.15s;
    }
    .kf-tab:hover { color: #888; }
    .kf-tab.active { color: #c9a84c; border-bottom-color: #c9a84c; }

    /* Track list */
    #kf-tracklist {
      max-height: 160px;
      overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: #2a2a2a transparent;
    }
    .kf-track-row {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 7px 14px;
      cursor: pointer;
      border-bottom: 1px solid #141414;
      transition: background 0.12s;
    }
    .kf-track-row:hover { background: rgba(255,255,255,0.03); }
    .kf-track-row.playing { background: rgba(201,168,76,0.07); }
    .kf-track-row-name {
      font-size: 12px;
      color: #ccc;
      flex: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .kf-track-row.playing .kf-track-row-name { color: #c9a84c; }
    .kf-track-duration {
      font-size: 10px;
      color: #555;
    }
    .kf-play-icon {
      width: 14px; height: 14px;
      color: #555;
      flex-shrink: 0;
    }
    .kf-track-row:hover .kf-play-icon,
    .kf-track-row.playing .kf-play-icon { color: #c9a84c; }
  `;

  // ── SVG ICONS ──────────────────────────────────────────────────────────────
  const ICONS = {
    logo: `<svg viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="14" cy="14" r="13" stroke="#c9a84c" stroke-width="1.5"/>
      <circle cx="14" cy="14" r="4" fill="#c9a84c"/>
      <circle cx="14" cy="14" r="8" stroke="#c9a84c" stroke-width="1" stroke-dasharray="2 3" opacity="0.5"/>
    </svg>`,
    play: `<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M3 2l9 5-9 5V2z"/></svg>`,
    pause: `<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><rect x="2" y="2" width="4" height="10"/><rect x="8" y="2" width="4" height="10"/></svg>`,
    skip: `<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M2 2l8 5-8 5V2z"/><rect x="11" y="2" width="2" height="10"/></svg>`,
    prev: `<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M12 2L4 7l8 5V2z"/><rect x="1" y="2" width="2" height="10"/></svg>`,
    vol: `<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor"><path d="M2 5v4h3l4 3V2L5 5H2zm9.5 2a3.5 3.5 0 0 0-3-3.47v6.94A3.5 3.5 0 0 0 11.5 7z" opacity=".6"/></svg>`,
    row: `<svg class="kf-play-icon" viewBox="0 0 14 14" fill="currentColor"><circle cx="7" cy="7" r="6" stroke="currentColor" stroke-width="1.2" fill="none"/><path d="M5.5 5l4 2-4 2V5z"/></svg>`,
    bars: `<svg class="kf-play-icon" viewBox="0 0 14 14" fill="currentColor"><rect x="2" y="6" width="2" height="6"/><rect x="6" y="3" width="2" height="9"/><rect x="10" y="5" width="2" height="7"/></svg>`,
  };

  // ── DOM BUILD ──────────────────────────────────────────────────────────────
  function buildDOM() {
    const style = document.createElement('style');
    style.textContent = STYLE;
    document.head.appendChild(style);

    const root = document.createElement('div');
    root.id = 'kf-player';
    root.innerHTML = `
      <!-- Collapsed pill -->
      <div id="kf-pill" title="Kingsfield Audio">
        <span id="kf-pill-icon">${ICONS.logo}</span>
        <span id="kf-pill-label">Audio</span>
      </div>

      <!-- Expanded panel -->
      <div id="kf-panel" style="display:none">
        <div id="kf-panel-header">
          <span id="kf-panel-title">Kingsfield Audio</span>
          <button id="kf-close-btn" title="Collapse">−</button>
        </div>

        <div id="kf-now-playing">
          <div id="kf-track-name">— No track selected —</div>
          <div id="kf-track-cat">Select a track below</div>
        </div>

        <div id="kf-progress-wrap">
          <div id="kf-progress-bar"><div id="kf-progress-fill"></div></div>
        </div>

        <div id="kf-controls">
          <button class="kf-ctrl-btn" id="kf-prev-btn" title="Previous">${ICONS.prev}</button>
          <button id="kf-play-btn" title="Play / Pause">${ICONS.play}</button>
          <button class="kf-ctrl-btn" id="kf-next-btn" title="Next">${ICONS.skip}</button>
          <div id="kf-volume-wrap">
            <span id="kf-volume-icon">${ICONS.vol}</span>
            <input type="range" id="kf-vol-slider" min="0" max="1" step="0.05" value="${volume}">
          </div>
        </div>

        <div id="kf-tabs">
          <button class="kf-tab active" data-tab="ambient">Ambient</button>
          <button class="kf-tab" data-tab="events">Events</button>
          <button class="kf-tab" data-tab="voices">Voice</button>
        </div>

        <div id="kf-tracklist">
          <div style="padding:16px;color:#555;font-size:12px;text-align:center">Loading…</div>
        </div>
      </div>
    `;
    document.body.appendChild(root);
  }

  // ── EVENT BINDING ──────────────────────────────────────────────────────────
  function bindEvents() {
    // Toggle expanded/collapsed
    document.getElementById('kf-pill').addEventListener('click', () => setExpanded(true));
    document.getElementById('kf-close-btn').addEventListener('click', () => setExpanded(false));

    // Play/pause
    document.getElementById('kf-play-btn').addEventListener('click', togglePlay);

    // Prev / next
    document.getElementById('kf-prev-btn').addEventListener('click', playPrev);
    document.getElementById('kf-next-btn').addEventListener('click', playNext);

    // Volume
    document.getElementById('kf-vol-slider').addEventListener('input', (e) => {
      volume = parseFloat(e.target.value);
      if (currentAudio) currentAudio.volume = volume;
    });

    // Tabs
    document.querySelectorAll('.kf-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        activeTab = btn.dataset.tab;
        document.querySelectorAll('.kf-tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderTrackList();
      });
    });

    // Progress bar click to seek
    document.getElementById('kf-progress-wrap').addEventListener('click', (e) => {
      if (!currentAudio || !currentAudio.duration) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const pct = (e.clientX - rect.left) / rect.width;
      currentAudio.currentTime = pct * currentAudio.duration;
    });
  }

  function setExpanded(open) {
    expanded = open;
    document.getElementById('kf-pill').style.display = open ? 'none' : 'flex';
    document.getElementById('kf-panel').style.display = open ? 'block' : 'none';
  }

  // ── CATALOG ────────────────────────────────────────────────────────────────
  async function loadCatalog() {
    try {
      const res = await fetch(CFG.apiBase + '/api/media/catalog');
      if (res.ok) {
        catalog = await res.json();
        catalogLoaded = true;
        renderTrackList();
        if (CFG.autoplayEvent) {
          // Check if user has already heard the intro in this session
          if (!sessionStorage.getItem('kf_intro_played')) {
            setTimeout(() => {
              playEventById(CFG.autoplayEvent);
              sessionStorage.setItem('kf_intro_played', '1');
            }, 1200);
          }
        }
      }
    } catch (e) {
      // Backend not running — use fallback catalog if defined
      console.debug('[kf-player] Catalog fetch failed — backend may not be running');
      renderTrackListFallback();
    }
  }

  // ── TRACK LIST RENDER ──────────────────────────────────────────────────────
  function renderTrackList() {
    const list = document.getElementById('kf-tracklist');
    const tracks = activeTab === 'ambient' ? catalog.ambient
                 : activeTab === 'events'  ? catalog.events
                 : catalog.voices;

    if (!tracks || tracks.length === 0) {
      list.innerHTML = '<div style="padding:16px;color:#555;font-size:12px;text-align:center">No tracks</div>';
      return;
    }

    list.innerHTML = tracks.map(t => `
      <div class="kf-track-row${currentTrack && currentTrack.id === t.id ? ' playing' : ''}"
           data-id="${t.id}" data-url="${encodeURIComponent(t.url)}">
        <span>${currentTrack && currentTrack.id === t.id && isPlaying ? ICONS.bars : ICONS.row}</span>
        <span class="kf-track-row-name">${t.title}</span>
        ${t.duration ? `<span class="kf-track-duration">${t.duration}</span>` : ''}
      </div>
    `).join('');

    list.querySelectorAll('.kf-track-row').forEach(row => {
      row.addEventListener('click', () => {
        const id = row.dataset.id;
        const track = tracks.find(t => t.id === id);
        if (track) playTrack(track);
      });
    });
  }

  function renderTrackListFallback() {
    document.getElementById('kf-tracklist').innerHTML =
      '<div style="padding:16px;color:#555;font-size:12px;text-align:center">Start the backend to load tracks</div>';
  }

  // ── PLAYBACK ───────────────────────────────────────────────────────────────
  function playTrack(track, startPaused = false) {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.src = '';
    }
    currentTrack = track;
    currentAudio = new Audio(CFG.apiBase + decodeURIComponent(track.url));
    currentAudio.volume = volume;
    currentAudio.preload = 'auto';

    // Loop ambient tracks
    if (track.category === 'ambient') currentAudio.loop = true;

    currentAudio.addEventListener('timeupdate', updateProgress);
    currentAudio.addEventListener('ended', () => {
      if (track.category !== 'ambient') {
        isPlaying = false;
        updatePlayBtn();
        updateProgress();
      }
    });
    currentAudio.addEventListener('error', (e) => {
      console.warn('[kf-player] Audio error:', e);
    });

    // Update UI
    document.getElementById('kf-track-name').textContent = track.title;
    document.getElementById('kf-track-cat').textContent =
      track.category === 'ambient' ? 'Ambient — loops' :
      track.category === 'event'   ? 'Event clip' : 'Voice';

    if (!startPaused) {
      const playPromise = currentAudio.play();
      if (playPromise) playPromise.catch(() => {
        console.debug('[kf-player] Autoplay blocked — click play to start');
      });
      isPlaying = true;
    }

    updatePlayBtn();
    updatePill();
    renderTrackList();
  }

  function togglePlay() {
    if (!currentAudio) {
      // Start first ambient track
      const first = catalog.ambient[0];
      if (first) playTrack(first);
      return;
    }
    if (isPlaying) {
      currentAudio.pause();
      isPlaying = false;
    } else {
      currentAudio.play().catch(() => {});
      isPlaying = true;
    }
    updatePlayBtn();
    updatePill();
  }

  function playPrev() {
    const tracks = activeTab === 'ambient' ? catalog.ambient
                 : activeTab === 'events'  ? catalog.events
                 : catalog.voices;
    if (!tracks.length) return;
    const idx = currentTrack ? tracks.findIndex(t => t.id === currentTrack.id) : 0;
    const prev = tracks[(idx - 1 + tracks.length) % tracks.length];
    playTrack(prev);
  }

  function playNext() {
    const tracks = activeTab === 'ambient' ? catalog.ambient
                 : activeTab === 'events'  ? catalog.events
                 : catalog.voices;
    if (!tracks.length) return;
    const idx = currentTrack ? tracks.findIndex(t => t.id === currentTrack.id) : -1;
    const next = tracks[(idx + 1) % tracks.length];
    playTrack(next);
  }

  function playEventById(id) {
    const track = [...catalog.events, ...catalog.voices, ...catalog.ambient].find(t => t.id === id);
    if (track) playTrack(track);
  }

  // ── UI UPDATES ─────────────────────────────────────────────────────────────
  function updatePlayBtn() {
    const btn = document.getElementById('kf-play-btn');
    if (btn) btn.innerHTML = isPlaying ? ICONS.pause : ICONS.play;
  }

  function updatePill() {
    const pill = document.getElementById('kf-pill');
    const label = document.getElementById('kf-pill-label');
    if (!pill) return;
    if (isPlaying) {
      pill.classList.add('playing');
      label.textContent = currentTrack ? currentTrack.title.slice(0, 18) : 'Playing';
    } else {
      pill.classList.remove('playing');
      label.textContent = 'Audio';
    }
  }

  function updateProgress() {
    if (!currentAudio || !currentAudio.duration) return;
    const pct = (currentAudio.currentTime / currentAudio.duration) * 100;
    const fill = document.getElementById('kf-progress-fill');
    if (fill) fill.style.width = pct + '%';
  }

  // ── PUBLIC API ─────────────────────────────────────────────────────────────
  window.KingsfieldAudio = {
    /** Play a specific event/voice clip by ID */
    playEvent: function(id) { playEventById(id); },
    /** Play an ambient track by ID */
    playAmbient: function(id) {
      const track = catalog.ambient.find(t => t.id === id);
      if (track) { activeTab = 'ambient'; playTrack(track); }
    },
    /** Stop playback */
    stop: function() {
      if (currentAudio) { currentAudio.pause(); isPlaying = false; updatePlayBtn(); updatePill(); }
    },
    /** Set volume 0–1 */
    setVolume: function(v) {
      volume = Math.max(0, Math.min(1, v));
      const slider = document.getElementById('kf-vol-slider');
      if (slider) slider.value = volume;
      if (currentAudio) currentAudio.volume = volume;
    },
    /** Open the player panel */
    open: function() { setExpanded(true); },
    /** Get current track info */
    nowPlaying: function() { return currentTrack; },
  };

  // ── INIT ───────────────────────────────────────────────────────────────────
  function init() {
    buildDOM();
    bindEvents();
    if (!expanded) {
      document.getElementById('kf-pill').style.display = 'flex';
      document.getElementById('kf-panel').style.display = 'none';
    } else {
      document.getElementById('kf-pill').style.display = 'none';
      document.getElementById('kf-panel').style.display = 'block';
    }
    loadCatalog();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
