import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Settings2, RefreshCw, Download, RotateCw, Repeat, Repeat1 } from 'lucide-react';

const API = (path) => fetch(path).then((r) => r.json());
const postJSON = (path, data) => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then((r) => r.json());
const trackKey = (t) => `${t?.t || ''}|${t?.a || ''}`;
const fmt = (ms) => { const n = Math.round((Number(ms) || 0) / 1000); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`; };
const secs = (s) => `${Math.floor((Number(s) || 0) / 60)}:${String(Math.round(s || 0) % 60).padStart(2, '0')}`;
const hue = (name) => { let h = 0; for (const c of String(name || '?')) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % 360; };
const shuffledExcept = (length, excluded) => {
  const order = Array.from({ length }, (_, index) => index).filter((index) => index !== excluded);
  for (let index = order.length - 1; index > 0; index--) {
    const other = Math.floor(Math.random() * (index + 1));
    [order[index], order[other]] = [order[other], order[index]];
  }
  return order;
};
// These covers carry a 1px translucent border, and index.html keeps the paint
// out of that ring with background-clip:padding-box — but the inline
// `background:` shorthand resets background-clip, so the clip has to be
// repeated in the string itself. Without it the gradient runs under the border
// and its bright first stop shows as a bright green corner in the ring.
// no-repeat keeps a repeated tile inside the same box.
const gradient = (name) => { const h = hue(name); return `linear-gradient(135deg,hsl(${h},70%,38%),hsl(${(h + 40) % 360},60%,20%)) no-repeat padding-box`; };
const escStyle = (url) => `url("${String(url || '').replace(/["'<>)]/g, (c) => encodeURIComponent(c))}") center/cover no-repeat padding-box`;
// Release speed in px/ms, read from the touch samples of the last 100ms. A
// flick's last move and its touchend sit at the same point, so the speed has
// to come from the samples before the finger lifted, not the final segment.
const VELOCITY_WINDOW_MS = 100;
const releaseVelocity = (trail, now) => {
  const recent = trail.filter((s) => now - s.t <= VELOCITY_WINDOW_MS);
  if (recent.length < 2) return { vx: 0, vy: 0 };
  const a = recent[0], b = recent[recent.length - 1], span = Math.max(1, b.t - a.t);
  return { vx: (b.x - a.x) / span, vy: (b.y - a.y) / span };
};
// Every glyph is drawn on one 24-unit grid and its position lives in the
// coordinates. Never add a `transform` here: it is measured in user units, so
// a value tuned to centre a glyph inside one button misplaces it inside every
// other one at a different size. That is how the play triangle went from a CSS
// translateX(1px) to translate(0.6 0) to translate(-1.145 0) - too far right,
// then too far left - while each round was "verified" with
// getBoundingClientRect, which reports the ink BOX and cannot see that a
// right-pointing triangle's mass sits at its base. The centres below come from
// tools/icon_bbox.py (which measures the box, arc bulges included) and are
// asserted by tests/test_icons.py.
function Icon({ name, size = 20, children }) {
  const p = {
    library: <path d="M2.7 3L5.2 3L5.2 21L2.7 21ZM6.7 3L9.2 3L9.2 21L6.7 21ZM10.7 3.6L21.3 5L21.3 19L10.7 20.4Z" fill="currentColor" stroke="none" />,
    home: <path d="M12 3.5L21 11.5L18.5 11.5L18.5 20.5L13.5 20.5L13.5 14.5L10.5 14.5L10.5 20.5L5.5 20.5L5.5 11.5L3 11.5Z" fill="currentColor" stroke="none" />,
    search: <><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></>,
    close: <><path d="m5 5 14 14M19 5 5 19"/></>,
    browse: <path d="M3 3.75L16 3.75L16 5.75L3 5.75ZM3 7.5L16 7.5L16 9.5L3 9.5ZM3 11.25L21 11.25L21 18.75A1.5 1.5 0 0 1 19.5 20.25L4.5 20.25A1.5 1.5 0 0 1 3 18.75Z" fill="currentColor" stroke="none" />,
    // `plus` and `check` are lucide's own path data (24 grid, stroke 2, round
    // caps), as are search, close, shuffle, repeat, volume and the fullscreen
    // glyphs above: two hand-drawn glyphs next to a set of library ones is how
    // the pair ended up not matching each other. An earlier drawn plus was
    // filled and 17.25 units wide against a stroked 15-unit tick, so the two
    // marks in one ring had different weights, different corner rounding and
    // different ink sizes. Both are now the library's, drawn with the svg
    // attributes the wrapper already applies.
    //
    // lucide centres `plus` exactly (ink 4..20 both ways). Its `check` is
    // `M20 6 9 17l-5-5`, which puts the path box half a unit above the grid
    // centre, and the stroke widens that: the round join under the elbow
    // bulges a full stroke unit below the box while the 45-degree caps at the
    // tips bulge 0.71 above, so the ink box the eye sees sits 0.145 lower
    // again. In the 26px button that measured 0.31px high - 8.38px of green
    // above the tick against 9.00 below, next to a plus drawn dead centre -
    // and that is what read as off. The path is therefore moved down 0.35,
    // which puts the ink box on the disc centre within a pixel-grid step
    // (8.62 and 8.75 at 8x, measured on the real button). It leaves the mass
    // 0.34 low, and cannot not: a tick's elbow is where its weight is, so the
    // silhouette and the mass cannot both be on 12, and against a circle the
    // silhouette is the one being compared.
    add: <path d="M12 5v14M5 12h14" />,
    check: <path d="M20 6.35 9 17.35l-5-5" />,
    // the triangle needs its ink 0.75 right of centre: a box-centred play
    // glyph reads pulled towards its base, which is exactly what the old
    // -1.145 nudge made worse.
    play: <path d="M3.533 2.569A1.05 1.05 0 0 1 5.108 1.658L21.443 11.09A1.05 1.05 0 0 1 21.443 12.908L5.108 22.34A1.05 1.05 0 0 1 3.533 21.431L3.533 2.569Z" fill="currentColor" stroke="none" />,
    pause: <path d="M7.2 3A1.05 1.05 0 0 0 6.15 4.05L6.15 19.95A1.05 1.05 0 0 0 7.2 21L9.6 21A1.05 1.05 0 0 0 10.65 19.95L10.65 4.05A1.05 1.05 0 0 0 9.6 3L8.55 3ZM14.4 3A1.05 1.05 0 0 0 13.35 4.05L13.35 19.95A1.05 1.05 0 0 0 14.4 21L16.8 21A1.05 1.05 0 0 0 17.85 19.95L17.85 4.05A1.05 1.05 0 0 0 16.8 3L14.4 3Z" fill="currentColor" stroke="none" />,
    prev: <path d="M4.95 1.5A1.05 1.05 0 0 1 6 2.55L6 10.275L20.925 1.659A1.05 1.05 0 0 1 22.5 2.568L22.5 21.43A1.05 1.05 0 0 1 20.925 22.341L6 13.723L6 21.45A1.05 1.05 0 0 1 4.95 22.5L2.55 22.5A1.05 1.05 0 0 1 1.5 21.45L1.5 2.55A1.05 1.05 0 0 1 2.55 1.5L4.95 1.5Z" fill="currentColor" stroke="none" />,
    next: <path d="M19.05 1.5A1.05 1.05 0 0 0 18 2.55L18 10.275L3.075 1.66A1.05 1.05 0 0 0 1.5 2.568L1.5 21.43A1.05 1.05 0 0 0 3.075 22.341L18 13.723L18 21.45A1.05 1.05 0 0 0 19.05 22.5L21.45 22.5A1.05 1.05 0 0 0 22.5 21.45L22.5 2.55A1.05 1.05 0 0 0 21.45 1.5L19.05 1.5Z" fill="currentColor" stroke="none" />,
    clock: <><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/></>,
    shuffle: <><polyline points="15.5 3 20.5 3 20.5 8"/><line x1="3.5" y1="20" x2="20.5" y2="3"/><polyline points="20.5 16 20.5 21 15.5 21"/><line x1="14.5" y1="15" x2="20.5" y2="21"/><line x1="3.5" y1="4" x2="8.5" y2="9"/></>,
    repeat: <><path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/></>,
    volume: <><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></>,
    fullscreen: <><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></>,
    exitFullscreen: <><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children || p[name]}</svg>;
}

function TooltipLayer() {
  const [tooltip, setTooltip] = useState(null);
  useLayoutEffect(() => {
    if (!tooltip) return;
    const node = document.querySelector('.app-tooltip');
    if (!node) return;
    const halfWidth = node.getBoundingClientRect().width / 2;
    const left = Math.max(12 + halfWidth, Math.min(window.innerWidth - 12 - halfWidth, tooltip.left));
    if (left !== tooltip.left) setTooltip((current) => current === tooltip ? { ...current, left } : current);
  }, [tooltip]);
  useEffect(() => {
    let timer = 0;
    let target = null;
    let watch = null;
    const show = (event) => {
      const node = event.target?.closest?.('[data-tooltip]');
      if (!node || !node.dataset.tooltip || node.disabled) return;
      // Focus moved by code (after a click) is not keyboard focus and gets no tooltip.
      if (event.type === 'focusin' && !node.matches(':focus-visible')) return;
      target = node;
      // A tooltip on screen follows its control's label, so Play turns into Pause with it.
      watch?.disconnect();
      watch = new MutationObserver(() => setTooltip((t) => t && node.dataset.tooltip ? { ...t, text: node.dataset.tooltip } : t));
      watch.observe(node, { attributes: true, attributeFilter: ['data-tooltip'] });
      clearTimeout(timer);
      timer = setTimeout(() => {
        const rect = node.getBoundingClientRect();
        const left = rect.left + rect.width / 2;
        const above = rect.top > 44;
        setTooltip({ text: node.dataset.tooltip, left, top: above ? rect.top - 8 : rect.bottom + 8, above });
      }, event.type === 'focusin' ? 0 : 420);
    };
    const hide = (event) => {
      if (target && event.relatedTarget && target.contains(event.relatedTarget)) return;
      clearTimeout(timer); target = null; watch?.disconnect(); setTooltip(null);
    };
    const dismiss = () => { clearTimeout(timer); target = null; watch?.disconnect(); setTooltip(null); };
    document.addEventListener('mouseover', show);
    document.addEventListener('mouseout', hide);
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('focusin', show);
    document.addEventListener('focusout', hide);
    return () => {
      clearTimeout(timer);
      watch?.disconnect();
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('mouseover', show);
      document.removeEventListener('mouseout', hide);
      document.removeEventListener('focusin', show);
      document.removeEventListener('focusout', hide);
    };
  }, []);
  if (!tooltip) return null;
  return <div className={`app-tooltip ${tooltip.above ? 'above' : 'below'}`} role="tooltip" style={{ left: tooltip.left, top: tooltip.top }}>{tooltip.text}</div>;
}

function updateStepsText(current, latest) {
  const from = String(current || '').match(/\\d+/g), to = String(latest || '').match(/\\d+/g);
  if (!from || !to) return 'a new version';
  const a = from.slice(0, 3).map(Number), b = to.slice(0, 3).map(Number);
  while (a.length < 3) a.push(0);
  while (b.length < 3) b.push(0);
  const count = a[0] !== b[0] || a[1] !== b[1] ? 1 : Math.max(1, b[2] - a[2]);
  return `${count} version${count === 1 ? '' : 's'} forward`;
}

// The seek bar reads the audio clock itself: letting every timeupdate
// re-render the whole app (four times a second, forever) is what grew the
// web content process's heap. This widget is a handful of nodes.
// The control a dialog should hand focus back to. A click does not always
// focus a button (Safari never does), so the press is remembered as well.
let lastOutside = null;
const remember = (event) => {
  const node = event.target?.closest?.('button,a,[tabindex],input');
  if (node && !node.closest('[aria-modal="true"]')) lastOutside = node;
};
document.addEventListener('pointerdown', remember, true);
document.addEventListener('focusin', remember, true);

// A dialog takes focus when it opens, keeps Tab inside itself, and gives focus
// back to whatever opened it.
function useDialogFocus(open, selector, container) {
  useEffect(() => {
    if (!open) return undefined;
    const opener = lastOutside;
    const frame = requestAnimationFrame(() => document.querySelector(selector)?.focus());
    const trap = (event) => {
      const boxes = container ? [...document.querySelectorAll(container)] : [];
      if (event.key !== 'Tab' || !boxes.length) return;
      const stop = 'button:not([tabindex="-1"]),input:not([tabindex="-1"]),[tabindex]:not([tabindex="-1"])';
      const items = boxes.flatMap((box) => [...box.querySelectorAll(stop)]).filter((el) => !el.disabled && el.offsetParent && !el.closest('[inert]'));
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      const inside = boxes.some((box) => box.contains(document.activeElement));
      if (event.shiftKey ? document.activeElement === first || !inside : document.activeElement === last || !inside) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    };
    document.addEventListener('keydown', trap);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('keydown', trap);
      // After every cleanup has run, so an overlay's inert has already lifted.
      requestAnimationFrame(() => { if (opener && document.contains(opener)) opener.focus(); });
    };
  }, [open, selector, container]);
}

// A click anywhere on a settings row flips its switch, so the target is the row.
const toggleRow = (event) => {
  if (!event.target.closest('button,input,a')) event.currentTarget.querySelector('.setting-switch')?.click();
};

// A list that is one tab stop: arrows move between rows, Enter or Space plays.
const rowKeys = (fn) => (event) => {
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    const rows = [...(event.currentTarget.closest('#fsQrows, #dfsQrows, #tbl')?.querySelectorAll('[role=button]') || [])];
    rows[rows.indexOf(event.currentTarget) + (event.key === 'ArrowDown' ? 1 : -1)]?.focus();
  } else onActivate(fn)(event);
};

// Enter or Space on a focusable card does what a click does.
const onActivate = (fn) => (event) => {
  if (event.target !== event.currentTarget || (event.key !== 'Enter' && event.key !== ' ')) return;
  event.preventDefault();
  fn();
};

function SeekBar({ audioRef, duration, handlers, full, decor }) {
  const [pos, setPos] = useState(0);
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return undefined;
    const onTime = () => setPos(audio.currentTime || 0);
    const onReset = () => setPos(0);
    audio.addEventListener('timeupdate', onTime);
    audio.addEventListener('seeked', onTime);
    audio.addEventListener('loadstart', onReset);
    onTime();
    return () => {
      audio.removeEventListener('timeupdate', onTime);
      audio.removeEventListener('seeked', onTime);
      audio.removeEventListener('loadstart', onReset);
    };
  }, [audioRef]);
  return <div className={full ? 'fs-seek' : ''} id={full ? 'fsSeek' : 'prow'}><span className="ptime" id={full ? 'fsCur' : 'curt'}>{secs(pos)}</span><div className={full ? 'fs-progress' : ''} id={full ? 'fsProg' : 'prog'} {...(decor ? { 'aria-hidden': true } : handlers)} role={decor ? undefined : 'slider'} tabIndex={duration && !decor ? 0 : -1} aria-label="Seek" aria-valuemin={0} aria-valuemax={Math.round(duration || 0)} aria-valuenow={Math.round(pos)} aria-valuetext={`${secs(pos)} of ${secs(duration)}`} onKeyDown={(event) => {
    const audio = audioRef.current;
    const step = { ArrowRight: 5, ArrowUp: 5, ArrowLeft: -5, ArrowDown: -5, PageUp: 30, PageDown: -30 }[event.key];
    if (!audio?.duration || (step === undefined && event.key !== 'Home' && event.key !== 'End')) return;
    event.preventDefault();
    audio.currentTime = event.key === 'Home' ? 0 : event.key === 'End' ? Math.max(0, audio.duration - 1) : Math.max(0, Math.min(audio.duration, audio.currentTime + step));
  }}><i id={full ? 'fsProgf' : 'progf'} style={{ width: `${duration ? Math.min(100, pos / duration * 100) : 0}%` }} /></div><span className="ptime" id={full ? 'fsTot' : 'tott'}>{secs(duration)}</span></div>;
}

// Windowed list: only the rows near the viewport exist in the DOM. A long
// playlist otherwise builds thousands of nodes - and one cover layer each -
// in a single render, which is what let the web content process's heap grow
// to hundreds of megabytes. Both .row and .srow are height:56px.
const ROW_H = 56;
const WINDOW_ROWS = 80; // below this, render everything: no listener, no spacers
function WindowList({ count, renderRow }) {
  const OVERSCAN = 10;
  const hostRef = useRef(null);
  const [range, setRange] = useState({ start: 0, end: Math.min(count, 40) });
  useEffect(() => {
    const scroller = document.getElementById('main');
    const host = hostRef.current;
    if (!scroller || !host) return undefined;
    let frame = 0;
    const update = () => {
      frame = 0;
      const hostTop = host.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      const relTop = scroller.scrollTop - hostTop;
      const relBottom = relTop + scroller.clientHeight;
      const start = Math.max(0, Math.floor(relTop / ROW_H) - OVERSCAN);
      const end = Math.min(count, Math.ceil(relBottom / ROW_H) + OVERSCAN);
      setRange((prev) => (prev.start === start && prev.end === end ? prev : { start, end }));
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(update); };
    scroller.addEventListener('scroll', schedule, { passive: true });
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(schedule) : null;
    if (observer) observer.observe(scroller);
    update();
    return () => {
      scroller.removeEventListener('scroll', schedule);
      if (observer) observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [count]);
  const start = Math.min(range.start, count);
  const end = Math.min(range.end, count);
  return <div ref={hostRef}>
    {start > 0 && <div style={{ height: start * ROW_H }} />}
    {Array.from({ length: Math.max(0, end - start) }, (_, k) => renderRow(start + k))}
    {end < count && <div style={{ height: (count - end) * ROW_H }} />}
  </div>;
}

function App() {
  useEffect(() => { window.__kotReactReady?.(); }, []);
  const audioRef = useRef(null);
  const cacheRef = useRef(null);
  if (!cacheRef.current) {
    try { cacheRef.current = JSON.parse(localStorage.getItem('kot_ytcache') || '{}'); } catch { cacheRef.current = {}; }
  }
  // A remembered id and the file it wrote are the only reason a song is not
  // downloaded twice. That map used to live in localStorage alone, so cleared
  // web data, a second device, or a track whose title/artist reads slightly
  // differently sent a song already on disk back through a fresh search - and
  // a search can answer with a different video, which downloads a second copy
  // under its own id. Mirror it on the server, next to the library, and merge
  // that back on load: what is already downloaded stays downloaded.
  const rememberId = useCallback((key, id) => {
    if (!key) return;
    if (id) cacheRef.current[key] = id; else delete cacheRef.current[key];
    try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {}
    try { postJSON('/api/trackids', { ids: { [key]: id || '' } }).catch(() => {}); } catch {}
  }, []);
  useEffect(() => {
    API('/api/trackids').then((known) => {
      let gained = false;
      Object.entries(known || {}).forEach(([key, id]) => {
        if (id && key && !cacheRef.current[key]) { cacheRef.current[key] = id; gained = true; }
      });
      if (gained) { try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {} }
    }).catch(() => {});
  }, []);
  const coverCacheRef = useRef({});
  const jobsRef = useRef(new Map());
  const prefetchRef = useRef(new Set());
  const prefetchJobsRef = useRef(new Map());
  const prefetchTrackRef = useRef(null);
  const requestRef = useRef(0);
  const playbackEpoch = useRef(0);
  const lastNowPlaying = useRef({ key: '', at: 0, duration: 0 });
  const warmedPlaylists = useRef(new Map());
  const [links, setLinks] = useState([]);
  const [view, setView] = useState({ type: 'home' });
  const [plStuck, setPlStuck] = useState(false);
  // The playlist header scrolls away under #main; once it is gone, keep a
  // compact copy of the heading pinned beside the action row.
  useEffect(() => {
    const main = document.getElementById('main');
    if (!main) return undefined;
    const onScroll = () => {
      const head = document.getElementById('plhead');
      setPlStuck(!!head && main.scrollTop >= head.offsetHeight - 8);
    };
    main.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => main.removeEventListener('scroll', onScroll);
  }, [view]);
  const [playlist, setPlaylist] = useState([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [queue, setQueue] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [playingPlaylist, setPlayingPlaylist] = useState('');
  const [lastPlaylist, setLastPlaylist] = useState(() => { try { return localStorage.getItem('kot_last_playlist') || ''; } catch { return ''; } });
  useEffect(() => {
    if (!playingPlaylist) return;
    setLastPlaylist(playingPlaylist);
    try { localStorage.setItem('kot_last_playlist', playingPlaylist); } catch {}
  }, [playingPlaylist]);
  const [radio, setRadio] = useState(false);
  const [notifyTrackChanges, setNotifyTrackChanges] = useState(() => { try { return localStorage.getItem('kot_notify_track_changes') !== '0'; } catch { return true; } });
  const [shuffle, setShuffle] = useState(() => { try { return localStorage.getItem('kot_shuf') === '1'; } catch { return false; } });
  const [repeat, setRepeat] = useState(() => { try { const value = localStorage.getItem('kot_repeat'); return value === null ? 1 : Number(value); } catch { return 1; } });
  const [shuffleOrder, setShuffleOrder] = useState([]);
  const [shufflePos, setShufflePos] = useState(0);
  const [actualDuration, setActualDuration] = useState(0);
  const [paused, setPaused] = useState(true);
  const [volume, setVolume] = useState(() => { try { const stored = localStorage.getItem('kot_vol'); if (stored === null) return 1; const v = Number(stored); return Number.isFinite(v) ? v * v : 1; } catch { return 1; } });
  const [muted, setMuted] = useState(false);
  const [collapsed, setCollapsed] = useState(() => { try { return localStorage.getItem('kot_side_collapsed') === '1'; } catch { return false; } });
  const [sideDragWidth, setSideDragWidth] = useState(null);
  const [sideResizePreview, setSideResizePreview] = useState(null);
  const sideDrag = useRef(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveContains, setSaveContains] = useState(null);
  const [linkOpen, setLinkOpen] = useState(false);
  const [narrow, setNarrow] = useState(() => window.matchMedia('(max-width:820px)').matches);
  useEffect(() => {
    if (!settingsOpen) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') setSettingsOpen(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [settingsOpen]);
  useEffect(() => {
    const query = window.matchMedia('(max-width:820px)');
    const onChange = () => setNarrow(query.matches);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  const [linkValue, setLinkValue] = useState('');
  const [bgDownload, setBgDownload] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toastItems, setToastItems] = useState([]);
  const toastItemsRef = useRef([]);
  const [upNext, setUpNext] = useState(false);
  const upNextGone = useRef(false);
  const [upNextDismissed, setUpNextDismissed] = useState(false);
  const [download, setDownload] = useState(null);
  const [mobilePlayer, setMobilePlayer] = useState(false);
  const [desktopPlayer, setDesktopPlayer] = useState(false);
  const [desktopIdle, setDesktopIdle] = useState(false);
  const [coverMap, setCoverMap] = useState({});
  const [updateState, setUpdateState] = useState(null);
  const [updateMessage, setUpdateMessage] = useState('');
  const [updateBusy, setUpdateBusy] = useState(false);
  const updateCheckManual = useRef(false);
  const updateStatusTimer = useRef(0);
  const toastTimers = useRef(new Map());
  const dragStart = useRef(null);
  const mobileGesture = useRef({ startX: 0, startY: 0, target: null, queueScrollTop: 0, moved: false, openedBySwipe: false, closeTimer: 0 });
  const suppressTapUntil = useRef(0);
  const lastUpNextTrack = useRef('');
  const currentTrack = currentIndex >= 0 ? queue[currentIndex] : null;
  const duration = actualDuration || (currentTrack?.ms ? currentTrack.ms / 1000 : 0);
  const dismissToast = useCallback((id) => {
    clearTimeout(toastTimers.current.get(id));
    toastTimers.current.delete(id);
    const next = toastItemsRef.current.filter((item) => item.id !== id);
    toastItemsRef.current = next;
    setToastItems(next);
  }, []);
  const toast = useCallback((message) => {
    const text = String(message || '');
    const lower = text.toLowerCase();
    const variant = /could not|couldn't|failed|failure|error|unable|no source|not found/.test(lower)
      ? 'error'
      : /added|removed|saved|finished|ready/.test(lower) ? 'success' : 'default';
    const existing = toastItemsRef.current.find((item) => item.message === text);
    const id = existing?.id || `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    clearTimeout(toastTimers.current.get(id));
    const next = [{ id, message: text, variant }, ...toastItemsRef.current.filter((item) => item.id !== id)].slice(0, 4);
    toastItemsRef.current.forEach((item) => {
      if (!next.some((current) => current.id === item.id)) {
        clearTimeout(toastTimers.current.get(item.id));
        toastTimers.current.delete(item.id);
      }
    });
    toastItemsRef.current = next;
    setToastItems(next);
    const timer = setTimeout(() => dismissToast(id), variant === 'error' ? 5200 : 4000);
    toastTimers.current.set(id, timer);
  }, [dismissToast]);
  // Playback bar: a Spotify-style add-to-playlist control. The button's green
  // state tracks the playlist that is open; the menu manages every playlist.
  const inCurrentPlaylist = !!(currentTrack && saveContains && Object.values(saveContains).some(Boolean));
  const refreshSaveContains = useCallback(() => {
    if (!currentTrack) return;
    API(`/api/links/contains?t=${encodeURIComponent(currentTrack.t || '')}&a=${encodeURIComponent(currentTrack.a || '')}`)
      .then((j) => setSaveContains(j.contains || {}))
      .catch(() => setSaveContains({}));
  }, [currentTrack]);
  useEffect(() => { refreshSaveContains(); }, [refreshSaveContains]);
  const toggleSaveMenu = useCallback(() => {
    const next = !saveOpen;
    setSaveOpen(next);
    if (next) refreshSaveContains();
  }, [saveOpen, refreshSaveContains]);
  const togglePlaylistMembership = useCallback(async (link) => {
    if (!currentTrack) return;
    const url = link.url || link.name || '';
    const had = !!(saveContains && saveContains[url]);
    try {
      const result = await postJSON('/api/links/track', { url, op: had ? 'remove' : 'add', track: currentTrack });
      if (result.error) throw new Error(result.error);
      setSaveContains((prev) => ({ ...(prev || {}), [url]: !!result.contains }));
      setLinks((prev) => prev.map((l) => ((l.url || l.name) === url ? { ...l, count: result.count } : l)));
      if (view.type === 'playlist' && view.name === link.name) {
        setPlaylist((prev) => (had ? prev.filter((t) => trackKey(t) !== trackKey(currentTrack)) : [...prev, currentTrack]));
      }
      toast(had ? `Removed from ${link.name}` : `Added to ${link.name}`);
    } catch { toast('Could not update playlist'); }
  }, [currentTrack, saveContains, view, toast]);
  useEffect(() => {
    if (!saveOpen) return undefined;
    const away = (event) => {
      const target = event.target;
      if (!target || !target.closest || !target.closest('#nowsave, .save-menu')) setSaveOpen(false);
    };
    const onKey = (event) => { if (event.key === 'Escape') setSaveOpen(false); };
    document.addEventListener('pointerdown', away);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', away);
      document.removeEventListener('keydown', onKey);
    };
  }, [saveOpen]);
  useEffect(() => { setSaveOpen(false); setSaveContains(null); }, [currentTrack?.t, currentTrack?.a]);
  const warmCover = useCallback((url) => {
    if (!url || url.startsWith('/cover/') || coverCacheRef.current[url]) return;
    coverCacheRef.current[url] = 'pending';
    fetch(url, { mode: 'cors' }).then((r) => { if (!r.ok) throw new Error('cover fetch failed'); return r.blob(); })
      .then((blob) => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = reject; reader.readAsDataURL(blob); }))
      .then((data) => postJSON('/api/cover/cache', { url, data }).then((j) => { if (j?.file) { coverCacheRef.current[url] = j.file; setCoverMap((m) => ({ ...m, [url]: j.file })); } }))
      .catch(() => { coverCacheRef.current[url] = null; });
  }, []);
  const resolveCover = useCallback((url) => {
    if (!url) return '';
    const key = coverMap[url];
    if (key) return escStyle(`/cover/${key}`);
    warmCover(url);
    return escStyle(url);
  }, [coverMap, warmCover]);

  const loadLinks = useCallback(() => API('/api/links').then((j) => { const rows = j.links || []; setLinks(rows); return rows; }), []);
  const startQueueRef = useRef(null);
  const shuffleRef = useRef(false);
  // Opening a playlist and starting it are two failures, not one. They used to
  // share a catch, so anything the play half threw was reported as "could not
  // open playlist" while the playlist was already on screen and the queue was
  // never started - which is what a prefetch job that rejected did (see
  // prefetchTrack: the warm-up lane is handed a function, not a promise).
  const loadPlaylist = useCallback(async (i, play = false, suppliedLinks = links) => {
    const item = suppliedLinks[i];
    if (!item) return;
    const req = ++requestRef.current;
    const key = item.url || item.name || '';
    let full = null;
    let tracks = [];
    try {
      const warmed = key && warmedPlaylists.current.get(key);
      full = warmed ? await warmed : null;
      if (req !== requestRef.current) return;
      if (!full?.tracks?.length) {
        warmedPlaylists.current.delete(key);
        full = await API(`/api/links/get?url=${encodeURIComponent(item.url || '')}`);
        if (req !== requestRef.current) return;
      }
      if (full?.error) full = item;
      tracks = (full?.tracks || item.tracks || []).filter((t) => t?.t);
    } catch (error) {
      toast(`Could not open playlist: ${error.message || 'network error'}`);
      return;
    }
    setPlaylist(tracks); setView({ type: 'playlist', name: item.name || 'Playlist' });
    setDrawerOpen(false);
    if (!play || !tracks.length) return;
    try {
      const choice = full?.choice;
      const warmedIndex = choice ? tracks.findIndex((t) => trackKey(t) === trackKey(choice)) : -1;
      if (key && warmedIndex >= 0) {
        // A warm-up that failed is not a playlist that failed: forget the job
        // and play, rather than letting its rejection escape into the caller.
        const job = prefetchJobsRef.current.get(trackKey(choice));
        const warmedOk = job ? await job.then((value) => value !== false, () => false) : true;
        if (!warmedOk) prefetchJobsRef.current.delete(trackKey(choice));
        if (req !== requestRef.current) return;
      }
      const index = warmedIndex >= 0 ? warmedIndex : (shuffle ? Math.floor(Math.random() * tracks.length) : 0);
      startQueueRef.current(tracks, item.name || 'Playlist', index);
    } catch (error) { toast(error.message || 'Could not start this playlist'); }
  }, [links, shuffle, toast]);

  const chooseNext = useCallback((q = queue, index = currentIndex, shuf = shuffle, order = shuffleOrder, pos = shufflePos) => {
    if (index < 0 || !q.length) return -1;
    if (repeat === 2) return index;
    if (shuf && q.length > 1) return pos < order.length ? order[pos] : -1;
    if (index + 1 < q.length) return index + 1;
    return repeat === 1 ? 0 : -1;
  }, [queue, currentIndex, shuffle, shuffleOrder, shufflePos, repeat]);

  const downloadId = useCallback(async (id, label = '', quiet = false) => {
    if (!quiet) { setDownload({ label, pct: 0, status: 'queued' }); setBusy(true); }
    try {
      const start = await API(`/api/ytdl?id=${encodeURIComponent(id)}`);
      if (start.error) throw new Error(start.error);
      if (start.file) return start;
      if (!start.job) throw new Error('No download job returned');
      while (true) {
        const status = await API(`/api/job?id=${encodeURIComponent(start.job)}`);
        if (status.error) throw new Error(status.error);
        if (!quiet) setDownload({ label: label || status.label, pct: status.pct || 0, status: status.status });
        if (status.status === 'done') return { file: status.file };
        if (status.status === 'error') throw new Error(status.error || 'Download failed');
        await new Promise((resolve) => setTimeout(resolve, 400));
      }
    } finally {
      if (!quiet) { setBusy(false); setDownload(null); }
    }
  }, []);

  const runDownload = useCallback(async (id, label = '') => {
    if (jobsRef.current.has(id)) return jobsRef.current.get(id);
    const promise = downloadId(id, label, true).finally(() => jobsRef.current.delete(id));
    jobsRef.current.set(id, promise);
    return promise;
  }, [downloadId]);

  // Playback and prefetch mark their searches/downloads here so the opt-in
  // background lane can yield: it never starts an item while this is above
  // zero, which is what keeps prefetch (and whatever you press play on) in
  // front of the queue.
  const interactiveRef = useRef(0);
  const asInteractive = useCallback(async (fn) => {
    interactiveRef.current += 1;
    try { return await fn(); } finally { interactiveRef.current = Math.max(0, interactiveRef.current - 1); }
  }, []);

  const playTrackRef = useRef(null);
  const findCandidates = useCallback(async (track) => {
    const q = `${track.a ? `${track.a} ` : ''}${track.t || ''}`;
    // pick=1 hands the title/artist/length hints to the server, which ranks the
    // YouTube results on them (rank_videos in serve_web.py). Sorting here by
    // |duration - expected| played parodies, covers and concert recordings that
    // happened to run closer to the expected length than the original.
    const target = Math.round((Number(track.ms) || 0) / 1000);
    const response = await API(`/api/search?src=youtube&pick=1&q=${encodeURIComponent(q)}&t=${encodeURIComponent(track.t || '')}&a=${encodeURIComponent(track.a || '')}&d=${target}`);
    const videos = (response.results || []).filter((r) => r.source === 'youtube').slice(0, 8);
    if (videos.length) return videos;
    if (track.source === 'newgrounds' && track.id) return [{ ...track, source: 'newgrounds' }];
    if (track.source === 'soundcloud' && track.id) return [{ ...track, source: 'soundcloud' }];
    const ng = await API(`/api/search?src=newgrounds&q=${encodeURIComponent(q)}&t=${encodeURIComponent(track.t || '')}&a=${encodeURIComponent(track.a || '')}`);
    const newgrounds = (ng.results || []).filter((r) => r.source === 'newgrounds').slice(0, 6);
    if (newgrounds.length) return newgrounds;
    const soundcloud = await API(`/api/search?src=soundcloud&q=${encodeURIComponent(q)}`);
    return (soundcloud.results || []).filter((r) => r.source === 'soundcloud').slice(0, 6);
  }, []);

  const startResolvedTrack = useCallback(async (track, candidates, candidateIndex, cacheKey, cached = false, epoch = playbackEpoch.current) => {
    const audio = audioRef.current;
    if (!audio || !track || epoch !== playbackEpoch.current) return;
    const candidate = candidates[candidateIndex];
    if (!candidate) { toast(`Could not find a matching source for ${track.t || 'track'}`); return; }
    try {
      const result = await asInteractive(() => downloadId(candidate.id, track.t, false));
      if (epoch !== playbackEpoch.current) return;
      const expected = Number(track.ms) || 0;
      const pending = { trackKey: trackKey(track), candidates, index: candidateIndex, expected, cacheKey, cached, id: candidate.id, epoch };
      audio.dataset.pending = JSON.stringify(pending);
      setActualDuration(0);
      audio.src = `/lib/${encodeURIComponent(result.file)}`;
      await audio.play();
      // The id that just started playing is the one whose file is on disk, so
      // the next play (and every other device) can go straight to it instead
      // of searching again and perhaps picking a different video.
      if (!cached) rememberId(cacheKey, candidate.id);
    } catch (error) {
      if (epoch !== playbackEpoch.current) return;
      if (candidateIndex + 1 < candidates.length) return startResolvedTrack(track, candidates, candidateIndex + 1, cacheKey, false, epoch);
      if (cached) {
        rememberId(cacheKey, '');
        if (candidateIndex === 0) return playTrackRef.current?.({ ...track, source: '', id: '' });
      }
      toast(error.message || `Could not fetch ${track.t || 'track'}`);
    }
  }, [asInteractive, downloadId, rememberId, toast]);

  const playTrack = useCallback(async (track) => {
    if (!track) return;
    upNextGone.current = false;
    setUpNextDismissed(false);
    const epoch = ++playbackEpoch.current;
    setActualDuration(0); setPaused(true);
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause(); audio.removeAttribute('src'); audio.load();
    if (track.source === 'youtube' || track.source === 'newgrounds' || track.source === 'soundcloud' || !track.source || track.source === 'local') {
      const key = trackKey(track);
      const cached = cacheRef.current[key];
      try {
        let candidates;
        if (track.source === 'newgrounds' && track.id) candidates = [{ ...track, source: 'newgrounds' }];
        else if (track.source === 'youtube' && track.id) candidates = [{ ...track }];
        else if (cached && !track.source) {
          // The id that worked last time is remembered, and the file it wrote
          // is keyed by that id, so ytdl's existence check answers locally:
          // skip source discovery entirely. Every way this can be wrong -
          // deleted file, dead video, wrong duration - clears this cache and
          // re-enters playTrack, which falls through to findCandidates below.
          candidates = [{ source: 'youtube', id: cached, dur: 0 }];
        } else candidates = await asInteractive(() => findCandidates(track));
        if (epoch !== playbackEpoch.current) return;
        if (!candidates.length) { toast(`No source found for ${track.t || 'track'}`); return; }
        const cachedIndex = cached ? candidates.findIndex((c) => c.id === cached) : -1;
        const orderedCandidates = candidates.slice();
        if (cachedIndex >= 0 && !track.source) {
          const cachedCandidate = candidates[cachedIndex];
          orderedCandidates.splice(cachedIndex, 1);
          orderedCandidates.unshift(cachedCandidate);
        } else if (cached && !track.source) orderedCandidates.unshift({ source: 'youtube', id: cached, dur: 0 });
        await startResolvedTrack(track, orderedCandidates, 0, key, !!cached, epoch);
      } catch (error) { toast(error.message || 'Could not find a source'); }
      return;
    }
    const url = `/api/play?src=${encodeURIComponent(track.source)}&id=${encodeURIComponent(track.id || '')}${track.preview ? `&preview=${encodeURIComponent(track.preview)}` : ''}`;
    audio.src = url;
    audio.play().catch(() => toast('Playback could not start'));
  }, [asInteractive, findCandidates, startResolvedTrack, toast]);
  playTrackRef.current = playTrack;

  const startQueue = useCallback((tracks, name = '', index = 0) => {
    if (!tracks?.length || index < 0) return;
    const nextQueue = tracks.slice();
    shuffleRef.current = shuffle;
    const order = shuffle ? shuffledExcept(nextQueue.length, index) : [];
    setQueue(nextQueue); setPlayingPlaylist(name); setCurrentIndex(index); setShuffleOrder(order); setShufflePos(0);
    playTrack(nextQueue[index]);
  }, [shuffle, playTrack]);
  startQueueRef.current = startQueue;

  const playIndex = useCallback((i, sourceQueue = queue, name = playingPlaylist, advanceShuffle = false, shufflePass = null) => {
    if (!sourceQueue[i]) return;
    upNextGone.current = false;
    setUpNextDismissed(false);
    const order = shuffle ? shuffledExcept(sourceQueue.length, i) : [];
    shuffleRef.current = shuffle;
    const nextOrder = shufflePass || (advanceShuffle ? shuffleOrder : order);
    const nextPos = shufflePass ? 1 : advanceShuffle ? shufflePos + 1 : 0;
    setQueue(sourceQueue); setPlayingPlaylist(name); setCurrentIndex(i); setShuffleOrder(nextOrder); setShufflePos(nextPos);
    playTrack(sourceQueue[i]);
  }, [queue, playingPlaylist, shuffle, shuffleOrder, shufflePos, playTrack]);

  const playList = useCallback(async () => {
    if (!playlist.length) return;
    const link = links.find((item) => item.name === view.name);
    const key = link?.url || link?.name || '';
    const warmup = key && warmedPlaylists.current.get(key);
    if (warmup) {
      const full = await warmup;
      if (full?.choice) {
        const choiceIndex = playlist.findIndex((track) => trackKey(track) === trackKey(full.choice));
        if (choiceIndex >= 0) { startQueue(playlist, view.name || '', choiceIndex); return; }
      }
    }
    const index = shuffle ? Math.floor(Math.random() * playlist.length) : 0;
    startQueue(playlist, view.name || '', index);
  }, [playlist, view, shuffle, startQueue, links]);

  const radioLoadingRef = useRef(false);
  const fetchRadio = useCallback(async () => {
    if (radioLoadingRef.current) return;
    const seed = queue[currentIndex];
    if (!seed) return;
    radioLoadingRef.current = true;
    try {
      const endpoint = `/api/recommend${seed.source === 'youtube' && seed.id ? `?seed=${encodeURIComponent(seed.id)}` : `?artist=${encodeURIComponent(seed.a || seed.t || '')}`}`;
      const response = await API(endpoint);
      const additions = (response.results || []).map((track) => ({ t: track.title, a: track.artist, source: track.source, id: track.id, preview: track.preview, ms: (track.dur || 0) * 1000, cover: track.cover || '', album: '' }));
      const seen = new Set(queue.map(trackKey));
      const fresh = additions.filter((track) => !seen.has(trackKey(track)) && seen.add(trackKey(track)));
      if (fresh.length) {
        toast(`radio: +${fresh.length} tracks`);
        const first = queue.length;
        const extendedQueue = [...queue, ...fresh];
        setQueue(extendedQueue); setCurrentIndex(first);
        setPlayingPlaylist(playingPlaylist);
        playTrack(fresh[0]);
      } else setRadio(false);
    } catch { toast('radio failed'); }
    finally { radioLoadingRef.current = false; }
  }, [queue, currentIndex, toast, playingPlaylist, playTrack]);
  const next = useCallback(() => {
    if (!queue.length) return;
    if (repeat === 2) { playIndex(currentIndex); return; }
    if (shuffle && queue.length > 1 && shufflePos >= shuffleOrder.length) {
      const order = shuffledExcept(queue.length, currentIndex);
      if (order.length) {
        playIndex(order[0], queue, playingPlaylist, false, order);
        return;
      }
    }
    const n = chooseNext();
    if (n >= 0) playIndex(n, queue, playingPlaylist, shuffle && queue.length > 1);
    else if (radio) fetchRadio();
  }, [queue, chooseNext, repeat, playingPlaylist, playIndex, currentIndex, shuffle, shufflePos, shuffleOrder, radio, fetchRadio]);

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio?.src) { if (queue.length) playIndex(Math.max(0, currentIndex)); return; }
    if (audio.paused) audio.play().catch(() => toast('Playback could not start')); else audio.pause();
  }, [queue, currentIndex, playIndex, toast]);

  const toggleShuffle = useCallback(() => {
    const nextShuffle = !shuffle;
    warmedPlaylists.current.clear();
    prefetchJobsRef.current.clear();
    setShuffle(nextShuffle);
    try { localStorage.setItem('kot_shuf', nextShuffle ? '1' : '0'); } catch {}
    if (nextShuffle && currentIndex >= 0) {
      setShuffleOrder(shuffledExcept(queue.length, currentIndex)); setShufflePos(0);
    } else { setShuffleOrder([]); setShufflePos(0); }
    shuffleRef.current = nextShuffle;
    if (audioRef.current?.src && !audioRef.current.paused) {
      const next = nextShuffle ? shuffledExcept(queue.length, currentIndex)[0] : currentIndex + 1;
      if (next >= 0 && queue[next]) prefetchTrackRef.current?.(queue[next]);
    }
  }, [shuffle, queue, currentIndex]);
  const toggleRepeat = useCallback(() => setRepeat((r) => { const v = (r + 1) % 3; try { localStorage.setItem('kot_repeat', String(v)); } catch {} return v; }), []);
  const toggleRadio = useCallback(() => setRadio((value) => !value), []);
  const previous = useCallback(() => {
    if (currentIndex > 0) playIndex(currentIndex - 1);
  }, [currentIndex, playIndex]);
  const setVolumePercent = useCallback((percent) => {
    const value = Math.max(0, Math.min(1, Number(percent) / 100));
    setVolume(value * value); setMuted(false);
    try { localStorage.setItem('kot_vol', String(value)); } catch {}
  }, []);
  const toggleVolume = useCallback(() => setMuted((wasMuted) => {
    const nextMuted = !wasMuted;
    if (audioRef.current) audioRef.current.muted = nextMuted;
    return nextMuted;
  }), []);
  const setVolumeAt = useCallback((element, event) => {
    const rect = element.getBoundingClientRect();
    const clientX = event.clientX;
    const value = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    setVolume(value * value); setMuted(false);
    try { localStorage.setItem('kot_vol', String(value)); } catch {}
  }, []);
  const seekAt = useCallback((element, event) => {
    if (!audioRef.current?.duration) return;
    const rect = element.getBoundingClientRect();
    audioRef.current.currentTime = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * audioRef.current.duration;
  }, []);

  const prefetchTrack = useCallback((track) => {
    if (!track || (track.source && track.source !== 'youtube' && track.source !== 'newgrounds' && track.source !== 'soundcloud')) return Promise.resolve();
    const key = trackKey(track);
    if (prefetchJobsRef.current.has(key)) return prefetchJobsRef.current.get(key);
    prefetchRef.current.add(key);
    // asInteractive takes the function and awaits its result. Invoking the
    // arrow here (an extra `()` after the closing brace) handed it a promise
    // instead, so every warm-up job resolved to `fn is not a function`, and
    // any click that awaited one lost its playback.
    const pending = asInteractive(async () => {
      try {
        const knownId = track.id && (track.source === 'youtube' || track.source === 'newgrounds' || track.source === 'soundcloud');
        const cachedId = !track.source && cacheRef.current[key];
        // Prefetching must not be the thing that pays for source discovery:
        // an id the track already carries needs no search, and a remembered
        // one names a file ytdl can answer locally.
        const candidates = knownId ? [track] : cachedId ? [{ source: 'youtube', id: cachedId, dur: 0 }] : await findCandidates(track);
        if (!candidates[0]?.id) { prefetchRef.current.delete(key); return; }
        rememberId(key, candidates[0].id);
        await runDownload(candidates[0].id, track.t);
        return undefined;
      } catch {
        prefetchRef.current.delete(key);
        return false;
      }
    });
    prefetchJobsRef.current.set(key, pending);
    return pending;
  }, [asInteractive, findCandidates, rememberId, runDownload]);
  prefetchTrackRef.current = prefetchTrack;

  // Opt-in background download (the add-link checkbox, off by default): one
  // track at a time that only ever starts while playback and prefetch are
  // idle, with a few seconds of air between items - this lane shares the
  // search and download queues with everything else, so it never bursts.
  const bgQueueRef = useRef([]);
  const bgRunningRef = useRef(false);
  const startBackgroundDownload = useCallback((tracks, name) => {
    const items = (tracks || []).filter((t) => t && t.t);
    if (!items.length) return;
    bgQueueRef.current.push(...items);
    toast(`background download queued: ${items.length} tracks${name ? ` from ${name}` : ''}`);
    if (bgRunningRef.current) return;
    bgRunningRef.current = true;
    const fetchOne = async (track) => {
      const key = trackKey(track);
      const knownId = track.id && (track.source === 'youtube' || track.source === 'newgrounds' || track.source === 'soundcloud');
      const remember = (id) => rememberId(key, id);
      const forget = () => { if (!knownId && cacheRef.current[key]) rememberId(key, ''); };
      const discover = async () => (await findCandidates(track))[0]?.id || '';
      const remembered = knownId ? track.id : cacheRef.current[key];
      const id = knownId ? remembered : remembered || await discover();
      if (!id) return false;
      try {
        await runDownload(id, track.t);
        if (!knownId) remember(id);
        return true;
      } catch {
        // A remembered id can point at a dead video: forget it and take one
        // fresh discovery pass before giving up on the track. Only ids that
        // actually worked are ever written back to the cache.
        forget();
        if (knownId || !remembered) return false;
        const fresh = await discover();
        if (!fresh) return false;
        try { await runDownload(fresh, track.t); remember(fresh); return true; } catch { forget(); return false; }
      }
    };
    (async () => {
      let saved = 0, failed = 0;
      try {
        while (bgQueueRef.current.length) {
          // Yield first: never start a background item while playback or
          // prefetch has work in flight.
          while (interactiveRef.current > 0) await new Promise((resolve) => setTimeout(resolve, 900));
          const track = bgQueueRef.current.shift();
          if (!track) break;
          if (await fetchOne(track)) saved += 1;
          else failed += 1;
          if (bgQueueRef.current.length) {
            await new Promise((resolve) => setTimeout(resolve, 4000 + Math.random() * 6000));
          }
        }
      } finally {
        bgRunningRef.current = false;
      }
      toast(failed ? `background download: ${saved} saved, ${failed} failed` : `background download finished: ${saved} tracks saved`);
    })();
  }, [findCandidates, rememberId, runDownload, toast]);

  // The next-track identity is derived from the queue state, so changes to the
  // queue, current item, shuffle order, or repeat mode always reconsider it.
  const nextIndex = chooseNext();
  const nextTrack = nextIndex >= 0 && nextIndex !== currentIndex ? queue[nextIndex] : null;
  const displayNextTrack = nextTrack || (radio && currentIndex >= 0 ? queue[currentIndex] : null);
  const radioSearching = radio && !nextTrack;
  useEffect(() => { if (nextTrack) prefetchTrack(nextTrack); }, [nextTrack, prefetchTrack]);
  useEffect(() => {
    const key = trackKey(currentTrack);
    if (key !== lastUpNextTrack.current) {
      lastUpNextTrack.current = key;
      upNextGone.current = false;
      setUpNextDismissed(false);
    }
    // Read the audio clock on a slow tick instead of re-rendering the whole
    // app from every timeupdate: a4-times-a-second full render is what let
    // the web content process's heap grow to hundreds of megabytes.
    const check = () => {
      const pos = audioRef.current?.currentTime || 0;
      const shouldShow = !!(actualDuration && pos > 0 && actualDuration - pos <= 30 && (nextTrack || radio));
      if (!shouldShow) {
        setUpNextDismissed(false); upNextGone.current = false; setUpNext(false);
      } else if (!upNextGone.current) {
        setUpNext(true);
      }
    };
    check();
    const timer = setInterval(check, 1000);
    return () => clearInterval(timer);
  }, [actualDuration, nextTrack, currentTrack, radio]);

  useEffect(() => {
    let alive = true;
    loadLinks();
    API('/api/cover/index').then((m) => { if (alive && m && typeof m === 'object') { coverCacheRef.current = m; setCoverMap(m); } }).catch(() => {});
    if (/[?&]desktop=1/.test(location.search)) setTimeout(() => pollUpdate(), 1500);
    else {
      let mtime = 0;
      const check = () => API('/api/mtime').then((j) => { if (mtime && j.mtime && j.mtime !== mtime) location.reload(); mtime = j.mtime || mtime; }).catch(() => {});
      check(); const timer = setInterval(check, 2000);
      return () => {
        alive = false;
        clearInterval(timer);
        toastTimers.current.forEach(clearTimeout);
        toastTimers.current.clear();
      };
    }
    return () => {
      alive = false;
      toastTimers.current.forEach(clearTimeout);
      toastTimers.current.clear();
    };
  }, [loadLinks]);

  useEffect(() => {
    if (audioRef.current) { audioRef.current.volume = volume; audioRef.current.muted = muted; }
  }, [volume, muted]);

  useEffect(() => {
    links.forEach((link) => {
      const key = link.url || link.name || '';
      if (!key || warmedPlaylists.current.has(key)) return;
      const warmup = API(`/api/links/get?url=${encodeURIComponent(link.url || '')}`).then((full) => {
        const tracks = (full?.tracks || []).filter((t) => t?.t);
        if (!tracks.length) return null;
        const choiceIndex = shuffle ? Math.floor(Math.random() * tracks.length) : 0;
        const choice = tracks[choiceIndex];
        const result = { ...full, tracks, choice, choiceIndex };
        warmedPlaylists.current.set(key, result);
        prefetchTrackRef.current?.(choice);
        return result;
      }).catch(() => null);
      warmedPlaylists.current.set(key, warmup);
      // Keep only the newest few playlists' full track lists: retaining every
      // playlist forever let the page's heap grow without bound.
      while (warmedPlaylists.current.size > 6) warmedPlaylists.current.delete(warmedPlaylists.current.keys().next().value);
      warmup.then((full) => { if (!full && warmedPlaylists.current.get(key) === warmup) warmedPlaylists.current.delete(key); });
    });
  }, [links, shuffle]);

  useEffect(() => {
    try { setCollapsed(localStorage.getItem('kot_side_collapsed') === '1'); } catch {}
  }, []);
  useEffect(() => {
    document.body.classList.toggle('dfs', desktopPlayer);
    document.body.classList.toggle('dfsidle', desktopPlayer && desktopIdle);
    return () => { document.body.classList.remove('dfs', 'dfsidle'); };
  }, [desktopPlayer, desktopIdle]);

  useEffect(() => {
    if (!desktopPlayer) return;
    let timer = 0;
    const wake = () => { setDesktopIdle(false); clearTimeout(timer); timer = setTimeout(() => setDesktopIdle(true), 10000); };
    const blur = () => { clearTimeout(timer); setDesktopIdle(true); };
    const resize = () => { if (window.innerWidth <= 820) setDesktopPlayer(false); };
    const visibility = () => { if (document.hidden) blur(); };
    const escape = (event) => { if (event.key === 'Escape') setDesktopPlayer(false); };
    wake();
    for (const event of ['mousemove', 'keydown', 'pointerdown', 'pointermove', 'wheel', 'touchstart']) window.addEventListener(event, wake, { passive: true });
    window.addEventListener('blur', blur); window.addEventListener('resize', resize); window.addEventListener('keydown', escape);
    document.addEventListener('visibilitychange', visibility);
    return () => {
      clearTimeout(timer);
      for (const event of ['mousemove', 'keydown', 'pointerdown', 'pointermove', 'wheel', 'touchstart']) window.removeEventListener(event, wake);
      window.removeEventListener('blur', blur); window.removeEventListener('resize', resize); window.removeEventListener('keydown', escape);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [desktopPlayer]);


  useEffect(() => {
    if (!updateState || !['checking', 'downloading', 'installing'].includes(updateState.state)) return;
    const timer = setTimeout(async () => {
      const st = await API('/api/update').catch(() => null);
      if (!st) return;
      setUpdateState(st);
      if (st.state === 'downloading') setUpdateMessage(`downloading update ${Math.round(st.pct || 0)}%`);
      else if (st.state === 'installing') setUpdateMessage('installing update…');
      else if (st.state === 'checking') setUpdateMessage('Checking for updates…');
      // A check can finish with an answer the pill has to relay even though
      // nothing failed: the latest release carrying no build for this Mac is
      // reported as state=idle plus an error message, and the old condition
      // here matched neither branch - so the pill sat on "Checking for
      // updates…" for ever.
      else if (st.error || st.state === 'error') { updateCheckManual.current = false; setUpdateMessage(st.error || 'update failed'); }
      else if (st.available) setUpdateMessage(`Kotassium ${st.latest || 'A Kotassium update'} is available (${updateStepsText(st.version, st.latest)})${st.can_install === false ? ' — move it to Applications to update' : ''}`);
      else if (updateCheckManual.current) {
        updateCheckManual.current = false;
        setUpdateMessage(`Kotassium ${st.version || ''} is up to date`);
        clearTimeout(updateStatusTimer.current);
        updateStatusTimer.current = setTimeout(() => {
          setUpdateMessage((message) => message.startsWith('Kotassium ') && message.endsWith(' is up to date') ? '' : message);
        }, 4000);
      }
    }, 700);
    return () => clearTimeout(timer);
  }, [updateState]);
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const onPlay = () => setPaused(false);
    const onPause = () => setPaused(true);
    const onMeta = () => {
      const actual = audio.duration;
      if (!Number.isFinite(actual) || actual <= 0) return;
      let pending = null;
      try { pending = JSON.parse(audio.dataset.pending || 'null'); } catch {}
      if (pending && pending.epoch === playbackEpoch.current && pending.trackKey === trackKey(queue[currentIndex])) {
        delete audio.dataset.pending;
        const expected = (pending.expected || 0) / 1000;
        if (expected && Math.abs(actual - expected) > Math.max(8, expected * 0.2) && pending.index + 1 < pending.candidates.length) {
          if (pending.cached) rememberId(pending.cacheKey, '');
          else {
            const actualKey = `${queue[currentIndex]?.t || ''}|${queue[currentIndex]?.a || ''}`;
            rememberId(actualKey, pending.id);
          }
          audio.pause(); audio.removeAttribute('src'); audio.load();
          startResolvedTrack(queue[currentIndex], pending.candidates, pending.index + 1, pending.cacheKey, false, playbackEpoch.current);
          return;
        }
        if (expected && Math.abs(actual - expected) > Math.max(8, expected * 0.2) && pending.cached) {
          rememberId(pending.cacheKey, '');
          delete audio.dataset.pending;
          audio.pause(); audio.removeAttribute('src'); audio.load();
          const retryTrack = { ...queue[currentIndex], source: '', id: '' };
          setQueue((current) => current.map((track, index) => index === currentIndex ? retryTrack : track));
          playTrackRef.current?.(retryTrack);
          return;
        }
      }
      setActualDuration(actual);
      setQueue((q) => q.map((t, i) => i === currentIndex ? { ...t, ms: Math.round(actual * 1000) } : t));
    };
    const onEnded = () => {
      if (repeat === 2) { audio.currentTime = 0; audio.play(); return; }
      if (radio && currentIndex === queue.length - 1 && repeat !== 1) { fetchRadio(); return; }
      next();
    };
    const onError = () => { if (audio.currentSrc) toast('Audio source could not be played'); };
    audio.addEventListener('play', onPlay); audio.addEventListener('pause', onPause);
    audio.addEventListener('loadedmetadata', onMeta); audio.addEventListener('ended', onEnded); audio.addEventListener('error', onError);
    return () => { audio.removeEventListener('play', onPlay); audio.removeEventListener('pause', onPause); audio.removeEventListener('loadedmetadata', onMeta); audio.removeEventListener('ended', onEnded); audio.removeEventListener('error', onError); };
  }, [queue, currentIndex, repeat, next, playTrack, startResolvedTrack, radio, fetchRadio, shufflePos, shuffleOrder, rememberId]);

  useEffect(() => {
    if (!currentTrack) return undefined;
    // The server (MPRIS, notifications) only needs the position every few
    // seconds; posting on every timeupdate re-rendered the whole app.
    const send = () => {
      const state = paused ? 'paused' : 'playing';
      const key = `${trackKey(currentTrack)}|${state}`;
      const now = Date.now();
      if (key !== lastNowPlaying.current.key || now - lastNowPlaying.current.at >= 2500 || duration !== lastNowPlaying.current.duration) {
        lastNowPlaying.current = { key, at: now, duration };
        const payload = { t: currentTrack.t || '', a: currentTrack.a || '', album: currentTrack.album || '', cover: currentTrack.cover || '', ms: Math.round(duration * 1000) || currentTrack.ms || 0, pos: Math.round((audioRef.current?.currentTime || 0) * 1000), state, notify_track_changes: notifyTrackChanges };
        postJSON('/api/nowplaying', payload).catch(() => {});
      }
    };
    send();
    if ('mediaSession' in navigator && typeof MediaMetadata !== 'undefined') {
      try { navigator.mediaSession.metadata = new MediaMetadata({ title: currentTrack.t || '?', artist: currentTrack.a || '', album: currentTrack.album || '' }); } catch {}
    }
    const timer = setInterval(send, 2500);
    return () => clearInterval(timer);
  }, [currentTrack, duration, paused, notifyTrackChanges]);
  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    try {
      navigator.mediaSession.setActionHandler('play', () => { if (audioRef.current) audioRef.current.play().catch(() => {}); }); navigator.mediaSession.setActionHandler('pause', () => audioRef.current?.pause());
      navigator.mediaSession.setActionHandler('nexttrack', () => next()); navigator.mediaSession.setActionHandler('previoustrack', () => previous());
    } catch {}
  }, [togglePlay, next, previous]);
  useEffect(() => {
    const onKeyDown = (event) => {
      const focus = document.activeElement;
      if (event.code === 'Space' && !/INPUT|TEXTAREA|SELECT|BUTTON|A/.test(focus?.tagName || '') && !focus?.closest?.('[role=button],[role=link],[role=slider],[role=switch],[role=radio]')) {
        event.preventDefault(); togglePlay();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [togglePlay]);

  const search = useCallback(async () => {
    const q = query.trim(); if (!q) return;
    setView({ type: 'search', query: q }); setResults([]); setSearching(true);
    try { const j = await API(`/api/search?q=${encodeURIComponent(q)}`); setResults((j.results || []).map((t) => ({ t: t.title, a: t.artist, source: t.source, id: t.id, preview: t.preview, full: t.full, ms: (t.dur || 0) * 1000, cover: t.cover || '', album: '' }))); }
    catch { toast('Search failed'); }
    finally { setSearching(false); }
  }, [query, toast]);

  const addLink = useCallback(async () => {
    const url = linkValue.trim(); if (!url) return;
    setBusy(true);
    const resolving = setInterval(() => toast('resolving link...'), 2500);
    toast('resolving Spotify link...');
    try {
      const j = await API(`/api/spot/resolve?url=${encodeURIComponent(url)}`);
      if (j.error) throw new Error(j.error_description || j.error);
      setLinkValue(''); setLinkOpen(false);
      const updated = await loadLinks();
      toast(`saved: ${j.name || 'link'} - ${(j.tracks || []).length} tracks`);
      if (bgDownload) startBackgroundDownload(j.tracks || [], j.name || '');
      const ix = updated.findIndex((p) => p.url === url || p.name === j.name);
      if (ix >= 0) await loadPlaylist(ix, false, updated);
    } catch (error) { toast(`could not open: ${error.message || 'network error'}`); }
    finally { clearInterval(resolving); setBusy(false); }
  }, [bgDownload, linkValue, loadLinks, loadPlaylist, startBackgroundDownload, toast]);

  const goHome = useCallback(() => { setQuery(''); setView({ type: 'home' }); }, []);
  useEffect(() => {
    if (!linkOpen) return;
    document.getElementById('plink')?.focus();
    const closeOnEscape = (event) => { if (event.key === 'Escape' && !busy) setLinkOpen(false); };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [linkOpen, busy]);

  const toggleSide = useCallback(() => {
    if (window.matchMedia('(max-width:820px)').matches) {
      const side = document.getElementById('side');
      if (side) { side.style.transition = ''; side.style.transform = ''; }
      setCollapsed(false);
      setDrawerOpen((x) => !x);
    } else setCollapsed((x) => { const v = !x; try { localStorage.setItem('kot_side_collapsed', v ? '1' : '0'); } catch {} return v; });
  }, []);
  const saveSidebarCollapsed = useCallback((value) => {
    setCollapsed(value);
    try { localStorage.setItem('kot_side_collapsed', value ? '1' : '0'); } catch {}
  }, []);
  const startSidebarResize = useCallback((event) => {
    if (window.matchMedia('(max-width:820px)').matches || event.button !== 0) return;
    const side = document.getElementById('side');
    if (!side) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const width = side.getBoundingClientRect().width;
    sideDrag.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: width };
    setSideDragWidth(width);
    setSideResizePreview(null);
  }, []);
  const moveSidebarResize = useCallback((event) => {
    const drag = sideDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const width = Math.min(262, Math.max(68, drag.startWidth + event.clientX - drag.startX));
    setSideDragWidth(width);
    setSideResizePreview(width < 165);
  }, []);
  const finishSidebarResize = useCallback((event) => {
    const drag = sideDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const width = Math.min(262, Math.max(68, drag.startWidth + event.clientX - drag.startX));
    sideDrag.current = null;
    setSideDragWidth(null);
    setSideResizePreview(null);
    saveSidebarCollapsed(width < 165);
  }, [saveSidebarCollapsed]);
  const keySidebarResize = useCallback((event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    saveSidebarCollapsed(event.key === 'ArrowLeft' || event.key === 'Home');
  }, [saveSidebarCollapsed]);
  const addLibraryLink = useCallback(() => {
    setLinkValue('');
    // The phone drawer hands over to the dialog: two open modals would each trap Tab.
    setDrawerOpen(false);
    setLinkOpen(true);
    setBgDownload(false);
  }, []);
  const mobileOpen = useCallback(() => {
    if (!window.matchMedia('(max-width:820px)').matches) return;
    const fs = document.getElementById('fs');
    if (!fs) return;
    if (mobileGesture.current.closeTimer) {
      clearTimeout(mobileGesture.current.closeTimer);
      mobileGesture.current.closeTimer = 0;
      fs.style.transition = 'transform .3s cubic-bezier(.2,.8,.2,1)';
      fs.style.transform = 'translateY(0)';
      setMobilePlayer(true);
      return;
    }
    if (fs.classList.contains('on')) return;
    fs.style.transition = 'none'; fs.style.transform = 'translateY(100%)';
    fs.classList.add('on');
    void fs.offsetHeight;
    setMobilePlayer(true);
    const list = document.getElementById('fsQueue'); if (list) list.scrollTop = 0;
    requestAnimationFrame(() => { fs.style.transition = 'transform .3s cubic-bezier(.2,.8,.2,1)'; fs.style.transform = 'translateY(0)'; });
  }, []);
  const mobileClose = useCallback(() => {
    const fs = document.getElementById('fs');
    if (!fs || !fs.classList.contains('on')) { setMobilePlayer(false); return; }
    fs.style.transition = 'transform .25s cubic-bezier(.2,.8,.2,1)'; fs.style.transform = 'translateY(100%)';
    clearTimeout(mobileGesture.current.closeTimer);
    mobileGesture.current.closeTimer = setTimeout(() => {
      fs.classList.remove('on'); fs.style.transition = 'none'; fs.style.transform = '';
      mobileGesture.current.closeTimer = 0;
      setMobilePlayer(false);
    }, 300);
  }, []);
  const gestureStart = (event, owner) => {
    if (!window.matchMedia('(max-width:820px)').matches) return;
    const target = event.target;
    if (owner === 'bar' && target.closest?.('#prog,#vol,#rside')) return;
    if (owner === 'fs' && target.closest?.('#fsProg,#fsVolBar')) return;
    if (owner === 'side' && (target.closest?.('input') || !drawerOpen)) return;
    const touch = event.touches[0];
    const queue = owner === 'fs' && target.closest?.('#fsQueue');
    mobileGesture.current = {
      ...mobileGesture.current, owner, startX: touch.clientX, startY: touch.clientY,
      lastX: touch.clientX, lastY: touch.clientY, lastAt: Date.now(), moved: false,
      trail: [{ x: touch.clientX, y: touch.clientY, t: Date.now() }],
      dragging: owner === 'fs' && !queue, inQueue: !!queue,
      baseY: owner === 'fs' ? 0 : window.innerHeight, queueScrollTop: queue?.scrollTop || 0,
    };
  };
  const gestureMove = (event, owner) => {
    const g = mobileGesture.current;
    if (g.owner !== owner) return;
    const touch = event.touches[0], dx = touch.clientX - g.startX, dy = touch.clientY - g.startY;
    g.lastX = touch.clientX; g.lastY = touch.clientY; g.lastAt = Date.now();
    g.trail = g.trail.filter((s) => g.lastAt - s.t <= VELOCITY_WINDOW_MS).concat({ x: touch.clientX, y: touch.clientY, t: g.lastAt });
    if (!g.dragging) {
      if (owner === 'bar' && (dy >= -6 || Math.abs(dx) >= Math.abs(dy))) return;
      if (owner === 'side' && (dx >= -6 || Math.abs(dy) >= Math.abs(dx))) return;
      if (owner === 'fs') {
        if (!g.inQueue || dy < 6 || Math.abs(dx) >= Math.abs(dy)) return;
        const list = document.getElementById('fsQueue');
        if (list && list.scrollTop > 0) return;
      }
      g.dragging = true; g.moved = true;
      if (owner === 'bar') {
        const fs = document.getElementById('fs');
        if (!fs) return;
        fs.style.transition = 'none'; fs.style.transform = `translateY(${g.baseY}px)`;
        fs.classList.add('on'); setMobilePlayer(true);
      }
      if (owner === 'side') {
        const side = document.getElementById('side'); if (side) side.style.transition = 'none';
      }
    }
    event.preventDefault();
    g.moved = Math.abs(dx) > 6 || Math.abs(dy) > 6;
    if (owner === 'bar' || owner === 'fs') {
      const fs = document.getElementById('fs'); if (!fs) return;
      const y = Math.max(0, Math.min(window.innerHeight, g.baseY + dy));
      fs.style.transform = `translateY(${y}px)`; g.positionY = y;
    } else {
      const side = document.getElementById('side'); if (side) side.style.transform = `translateX(${Math.min(0, dx)}px)`;
    }
  };
  const gestureEnd = (event, owner) => {
    const g = mobileGesture.current;
    if (g.owner !== owner) return;
    const touch = event.changedTouches[0], dx = touch.clientX - g.startX, dy = touch.clientY - g.startY;
    const { vx, vy } = releaseVelocity(g.trail, Date.now());
    if (g.dragging && g.moved) suppressTapUntil.current = Date.now() + 400;
    if (owner === 'bar' && g.dragging) {
      const fs = document.getElementById('fs');
      // A slow drag has to reach the top fifth of the screen; a flick faster
      // than 0.6 px/ms expands from anywhere.
      if (fs && (g.positionY < window.innerHeight * 0.2 || vy < -0.6)) {
        fs.style.transition = 'transform .3s cubic-bezier(.2,.8,.2,1)'; fs.style.transform = 'translateY(0)';
        const list = document.getElementById('fsQueue'); if (list) list.scrollTop = 0;
      } else mobileClose();
    } else if (owner === 'fs' && g.dragging) {
      if (Math.max(0, g.baseY + dy) > 90) mobileClose();
      else { const fs = document.getElementById('fs'); if (fs) { fs.style.transition = 'transform .25s cubic-bezier(.2,.8,.2,1)'; fs.style.transform = 'translateY(0)'; } }
    } else if (owner === 'side' && g.dragging) {
      const side = document.getElementById('side');
      if (side && (dx < -(side.getBoundingClientRect().width || 280) * 0.4 || vx < -0.5)) {
        side.style.transition = 'transform .25s cubic-bezier(.2,.8,.2,1)'; side.style.transform = 'translateX(-100%)';
        setTimeout(() => { if (side.style.transform === 'translateX(-100%)') { side.style.transition = ''; side.style.transform = ''; setDrawerOpen(false); } }, 250);
      } else if (side) { side.style.transition = 'transform .25s cubic-bezier(.2,.8,.2,1)'; side.style.transform = 'translateX(0)'; setTimeout(() => { side.style.transition = ''; side.style.transform = ''; }, 250); }
    }
    mobileGesture.current.owner = null;
  };
  const suppressGestureClick = (event) => {
    if (Date.now() < suppressTapUntil.current) { event.preventDefault(); event.stopPropagation(); }
  };
  useEffect(() => {
    if (!mobilePlayer) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') mobileClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [mobilePlayer, mobileClose]);
  useDialogFocus(settingsOpen, '.settings-close', '.settings-dialog');
  useDialogFocus(linkOpen, '#plink', '.link-dialog');
  useDialogFocus(mobilePlayer, '#fsGrip', '#fs');
  useDialogFocus(desktopPlayer, '#dfsExit', '#dfs, #bar');
  useDialogFocus(saveOpen, '.save-row', '.save-menu');
  useDialogFocus(drawerOpen && narrow, '#sideList [role=link]', '#side');
  useEffect(() => {
    if (!drawerOpen || !narrow) return undefined;
    const onKey = (event) => { if (event.key === 'Escape') setDrawerOpen(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [drawerOpen, narrow]);
  // What an overlay covers cannot take focus or clicks while it is open.
  useEffect(() => {
    const covered = mobilePlayer ? ['skip', 'skip2', 'top', 'mid', 'bar'] : desktopPlayer ? ['skip', 'skip2', 'top', 'mid'] : drawerOpen && narrow ? ['skip', 'skip2', 'top', 'main', 'bar'] : [];
    covered.forEach((id) => document.getElementById(id)?.setAttribute('inert', ''));
    return () => covered.forEach((id) => document.getElementById(id)?.removeAttribute('inert'));
  }, [mobilePlayer, desktopPlayer, drawerOpen, narrow]);
  const toggleDesktop = useCallback(() => {
    if (!desktopPlayer && (window.innerWidth <= 820 || !currentTrack)) return;
    setDesktopPlayer((value) => !value);
    setDesktopIdle(false);
  }, [desktopPlayer, currentTrack]);
  const pollUpdate = useCallback(() => API('/api/update').then((st) => { setUpdateState(st); if (st.supported) setUpdateMessage(st.state === 'error' && st.error ? st.error : st.available ? `Kotassium ${st.latest} is available` : ''); return st; }).catch(() => {}), []);
  // Settings shows which version this is, and it can be opened before the
  // launch poll has run - or on a phone/browser, which never polls at all -
  // so the status is fetched again whenever the dialog opens. GET /api/update
  // is local: it asks the server, never GitHub.
  useEffect(() => { if (settingsOpen) pollUpdate(); }, [settingsOpen, pollUpdate]);
  const appVersion = useMemo(() => {
    const raw = String(updateState?.version ?? '').trim().replace(/^v/i, '');
    return /^\d/.test(raw) && raw !== '0' ? raw : '';
  }, [updateState]);
  const versionLabel = appVersion || (updateState ? 'development build' : '…');
  const versionNote = updateState?.available ? `Version ${updateState.latest} is available`
    : (updateState?.state === 'error' && updateState.error) ? updateState.error
    : updateState?.supported ? 'Updates are checked at launch' : '';
  const updateSteps = useCallback((current, latest) => {
    const from = String(current || '').match(/\d+/g), to = String(latest || '').match(/\d+/g);
    if (!from || !to) return 'a new version';
    const a = from.slice(0, 3).map(Number), b = to.slice(0, 3).map(Number);
    while (a.length < 3) a.push(0);
    while (b.length < 3) b.push(0);
    const count = a[0] !== b[0] || a[1] !== b[1] ? 1 : Math.max(1, b[2] - a[2]);
    return `${count} version${count === 1 ? '' : 's'} forward`;
  }, []);
  const checkUpdate = useCallback(async () => { updateCheckManual.current = true; clearTimeout(updateStatusTimer.current); setUpdateBusy(true); setUpdateMessage('Checking for updates…'); try { const st = await postJSON('/api/update/check', {}); setUpdateState(st); if (st.state === 'checking') setUpdateMessage('Checking for updates…'); else if (st.error || st.state === 'error') { updateCheckManual.current = false; setUpdateMessage(st.error || 'update failed'); } else if (st.available) { updateCheckManual.current = false; setUpdateMessage(`Kotassium ${st.latest || 'A Kotassium update'} is available (${updateStepsText(st.version, st.latest)})${st.can_install === false ? ' — move it to Applications to update' : ''}`); } else { updateCheckManual.current = false; setUpdateMessage(`Kotassium ${st.version || ''} is up to date`); updateStatusTimer.current = setTimeout(() => setUpdateMessage(''), 4000); } } catch { updateCheckManual.current = false; setUpdateMessage('could not check for updates'); clearTimeout(updateStatusTimer.current); updateStatusTimer.current = setTimeout(() => setUpdateMessage((message) => message === 'could not check for updates' ? '' : message), 4000); toast('could not check for updates'); } finally { setUpdateBusy(false); } }, [toast]);
  const startUpdate = useCallback(async () => { setUpdateBusy(true); try { const started = await postJSON('/api/update', {}); const st = await pollUpdate(); if (st?.state === 'installing' || st?.state === 'downloading') setUpdateMessage(st.state === 'downloading' ? `downloading update ${Math.round(st.pct || 0)}%` : 'installing update…'); else { const why = started?.error || st?.error; if (why) { setUpdateMessage(why); toast(why); } } } catch { toast('could not start the update'); } finally { setUpdateBusy(false); } }, [pollUpdate, toast]);

  const imageStyle = (url, name) => ({ background: url ? resolveCover(url) : gradient(name) });
  // One song count everywhere a playlist is named: a partial import says how far it got.
const songCount = (p) => (typeof p.total === 'number' && p.total > p.count ? `${p.count} of ${p.total} songs` : `${p.count} ${p.count === 1 ? 'song' : 'songs'}`);
const linkCover = (link) => link?.cover || link?.tracks?.[0]?.cover;
  const coverBackground = (url, name) => url ? (coverMap[url] ? `url("/cover/${encodeURIComponent(coverMap[url])}") center/cover no-repeat padding-box` : escStyle(url)) : gradient(name);
  const volumeIcon = <><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>{muted ? <><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></> : volume <= 0.01 ? null : volume < 0.5 ? <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/> : <><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></>}</>;
  const icon = (name, size = 20) => <Icon name={name} size={size}>{name === 'volume' ? volumeIcon : null}</Icon>;
  const seekHandlers = () => ({
    onPointerDown: (event) => { event.currentTarget.setPointerCapture(event.pointerId); seekAt(event.currentTarget, event); },
    onPointerMove: (event) => { if (event.buttons) seekAt(event.currentTarget, event); },
    onTouchStart: (event) => { event.preventDefault(); seekAt(event.currentTarget, event.touches[0]); },
    onTouchMove: (event) => { if (event.buttons || event.touches.length) seekAt(event.currentTarget, event.touches[0]); },
  });
  const volumeHandlers = () => ({
    onPointerDown: (event) => { event.currentTarget.setPointerCapture(event.pointerId); setVolumeAt(event.currentTarget, event); },
    onPointerMove: (event) => { if (event.buttons) setVolumeAt(event.currentTarget, event); },
    onTouchStart: (event) => { event.preventDefault(); setVolumeAt(event.currentTarget, event.touches[0]); },
    onTouchMove: (event) => { if (event.touches.length) setVolumeAt(event.currentTarget, event.touches[0]); },
  });
  const upcoming = useMemo(() => {
    const out = [], seen = new Set();
    const add = (index) => {
      if (index < 0 || index >= queue.length || index === currentIndex || seen.has(index)) return;
      seen.add(index); out.push(index);
    };
    if (currentIndex < 0) { queue.forEach((_, index) => add(index)); return out; }
    if (repeat === 2) return out;
    if (shuffle && queue.length > 1) {
      for (let pos = shufflePos; pos < shuffleOrder.length; pos++) add(shuffleOrder[pos]);
      return out;
    }
    for (let index = currentIndex + 1; index < queue.length; index++) add(index);
    if (repeat === 1 && currentIndex === queue.length - 1) {
      for (let index = 0; index < currentIndex; index++) add(index);
    }
    return out;
  }, [queue, currentIndex, shuffle, shuffleOrder, shufflePos, repeat]);

  const trackRow = (tracks, mode, i) => {
    const track = tracks[i];
    const active = queue[currentIndex] && trackKey(queue[currentIndex]) === trackKey(track) && (mode === 'search' || playingPlaylist === view.name);
    return <div className={`${mode === 'search' ? 'srow' : 'row'}${active ? ' playing' : ''}`} key={`${trackKey(track)}-${i}`} role="button" tabIndex={i === 0 ? 0 : -1} aria-label={`Play ${track.t}${track.a ? ` by ${track.a}` : ''}`} onClick={() => mode === 'search' ? playIndex(i, tracks, '') : playIndex(i, tracks, view.name)} onKeyDown={rowKeys(() => mode === 'search' ? playIndex(i, tracks, '') : playIndex(i, tracks, view.name))}>
      {mode === 'search' ? <><button className="rbtn" tabIndex={-1} data-tooltip="Play" aria-label="Play"><Icon name="play" size={16}/></button><div className="rtxt" style={{ flex: 1 }}><b>{track.t}</b><small>{track.a}</small></div><span className="stag">{track.source}</span>{track.full === false ? <span className="stream-only">stream only</span> : <span/>}<span/><span/></> : <><div><span className="trnum">{active ? <span className={`bars${paused ? ' paused' : ''}`}><i/><i/><i/><i/></span> : <><span className="trn">{i + 1}</span><span className="trplay" aria-hidden="true"><Icon name="play" size={16}/></span></>}</span></div><div className="rt"><div className="track-cover" style={{ background: coverBackground(track.cover, track.album || track.t) }} onMouseEnter={() => warmCover(track.cover)}></div><div className="rtxt"><b>{track.t}</b><small>{track.a}</small></div></div><div className="ralb">{track.album || ''}</div><div className="rdura">{fmt(track.ms)}</div></>}
    </div>;
  };
  const trackRows = (tracks, mode) => tracks.map((_, i) => trackRow(tracks, mode, i));

  const renderMain = () => {
    if (view.type === 'playlist')    return <><div id="plhead" style={{ background: `linear-gradient(180deg,hsl(${hue(view.name)},65%,30%),hsl(${(hue(view.name) + 40) % 360},60%,22%) 60%,#12121200)` }}><div id="plx" style={{ background: coverBackground(linkCover(links.find((l) => l.name === view.name)), view.name) }}></div><div className="plinfo"><h1>{view.name}</h1><p>{playlist.length} song{playlist.length === 1 ? '' : 's'}</p></div></div><div id="plactions" className={plStuck ? 'stuck' : ''}><button id="bigplay" onClick={(!!currentTrack && playingPlaylist === view.name) ? togglePlay : playList} data-tooltip={(!!currentTrack && playingPlaylist === view.name) && !paused ? 'Pause' : 'Play'} aria-label={(!!currentTrack && playingPlaylist === view.name) && !paused ? 'Pause' : 'Play'}><Icon name={(!!currentTrack && playingPlaylist === view.name) && !paused ? 'pause' : 'play'} size={24}/><span>{(!!currentTrack && playingPlaylist === view.name) && !paused ? 'Pause' : 'Play'}</span></button><b className="plstick">{view.name}</b><button id="shuf2" className={`aicon ${shuffle ? 'on' : ''}`} aria-pressed={shuffle} onClick={toggleShuffle} data-tooltip="Shuffle" aria-label="Shuffle"><Icon name="shuffle" size={20}/></button><button id="rb2" className={`aicon ${repeat ? 'on' : ''}`} aria-pressed={repeat !== 0} onClick={toggleRepeat} data-tooltip="Repeat" aria-label="Repeat"><Icon name="repeat" size={20}/></button></div><div id="tbl" className={playlist.some((t) => t.album) ? '' : 'no-album'}><div className="tr-head"><span>#</span><span>Title</span><span>Album</span><span className="tdur" aria-label="Duration"><Icon name="clock" size={16}/></span></div>{playlist.length > WINDOW_ROWS ? <WindowList count={playlist.length} renderRow={(i) => trackRow(playlist, 'playlist', i)} /> : trackRows(playlist, 'playlist')}</div></>;
    if (view.type === 'search') return <div id="search-results">{searching ? <div id="homeView"><h2>Searching “{view.query}”…</h2></div> : <><div id="homeView"><h2>Results for “{view.query}”</h2></div><div id="tbl" style={{ paddingTop: 0 }}>{results.length ? <><div className="tr-head"><span></span><span>Title</span><span>Source</span><span></span></div>{results.length > WINDOW_ROWS ? <WindowList count={results.length} renderRow={(i) => trackRow(results, 'search', i)} /> : trackRows(results, 'search')}</> : <div id="empty">No results from any source.</div>}</div></>}</div>;
    const featured = links.length ? Math.max(0, links.findIndex((l) => l.name === (playingPlaylist || lastPlaylist))) : -1;
    const feature = featured < 0 ? null : (() => {
      const p = links[featured];
      const live = !!currentTrack && playingPlaylist === p.name;
      const pausable = live && !paused;
      const label = `${pausable ? 'Pause' : 'Play'} ${p.name}`;
      const eyebrow = live ? (paused ? 'Paused' : 'Now playing') : '';
      return <section id="feature" role="link" tabIndex={0} aria-label={`Open ${p.name}`} style={{ background: `linear-gradient(180deg,hsl(${hue(p.name)},40%,18%),#121212)` }} onClick={() => loadPlaylist(featured)} onKeyDown={onActivate(() => loadPlaylist(featured))}>
        <div className="fcover" style={{ background: coverBackground(linkCover(p), p.name) }}/>
        <div className="finfo">{eyebrow && <small>{eyebrow}</small>}<h1>{p.name}</h1><p>{songCount(p)}</p></div>
        <button className="fplay" data-tooltip={label} aria-label={label} onClick={(e) => { e.stopPropagation(); if (live) togglePlay(); else { loadPlaylist(featured, true); requestAnimationFrame(() => document.getElementById('bigplay')?.focus({ preventScroll: true })); } }}><Icon name={pausable ? 'pause' : 'play'} size={24}/><span>{pausable ? 'Pause' : 'Play'}</span></button>
      </section>;
    })();
    return <div id="homeView">{feature}{links.length > 1 ? <><h2>Your playlists</h2><div className="cardgrid">{links.map((p, i) => i === featured ? null : <article className="card" key={p.url || p.name} role="link" tabIndex={0} aria-label={`Open ${p.name}`} onClick={() => loadPlaylist(i)} onKeyDown={onActivate(() => loadPlaylist(i))}><div className="ccover" style={{ background: coverBackground(linkCover(p), p.name) }} onMouseEnter={() => warmCover(linkCover(p))}><button className="card-play" data-tooltip={`Play ${p.name}`} aria-label={`Play ${p.name}`} onClick={(e) => { e.stopPropagation(); loadPlaylist(i, true); }}><Icon name="play" size={20}/></button></div><b>{p.name || '?'}</b><small>{songCount(p)}</small></article>)}</div></> : links.length ? null : <div className="empty-cta"><h2>Your library is empty</h2><button className="pill-cta" onClick={() => setLinkOpen(true)}><Icon name="add" size={20}/>Add a Spotify link</button></div>}</div>;
  };

  const repeatButton = (fullscreen = false) => <button id={fullscreen ? 'fsRepeat' : 'repeatb'} className={`aicon ${repeat ? 'on' : ''}`} aria-pressed={repeat !== 0} onClick={toggleRepeat} data-tooltip={`Repeat ${repeat === 0 ? 'off' : repeat === 1 ? 'all' : 'one'}`} aria-label={`Repeat ${repeat === 0 ? 'off' : repeat === 1 ? 'all' : 'one'}`}>{repeat === 2 ? <Repeat1 size={fullscreen ? 24 : 20} strokeWidth={2}/> : <Repeat size={fullscreen ? 24 : 20} strokeWidth={2}/>}</button>;
  const controls = (fullscreen = false) => <div className={fullscreen ? 'fs-controls' : ''} id={fullscreen ? 'fsBtns' : 'btns'}><button id={fullscreen ? 'fsShuf' : 'shufb'} className={`aicon ${shuffle ? 'on' : ''}`} aria-pressed={shuffle} onClick={toggleShuffle} data-tooltip="Shuffle" aria-label="Shuffle"><Icon name="shuffle" size={fullscreen ? 24 : 20}/></button><button id={fullscreen ? 'fsprev' : 'prevb'} className="aicon" onClick={previous} disabled={!currentTrack || (currentIndex <= 0 && !(repeat === 1 && queue.length > 1))} data-tooltip="Previous" aria-label="Previous"><Icon name="prev" size={fullscreen ? 24 : 20}/></button><button id={fullscreen ? 'fsPlay' : 'playb'} className={fullscreen ? 'fs-play' : ''} onClick={togglePlay} disabled={!currentTrack} data-tooltip={paused ? 'Play' : 'Pause'} aria-label={paused ? 'Play' : 'Pause'}><Icon name={paused ? 'play' : 'pause'} size={fullscreen ? 24 : 20}/></button><button id={fullscreen ? 'fsnext' : 'nextb'} className="aicon" onClick={next} data-tooltip="Next" aria-label="Next" disabled={!currentTrack || (nextIndex < 0 && !radio)}><Icon name="next" size={fullscreen ? 24 : 20}/></button>{repeatButton(fullscreen)}</div>;
  const volumeRow = (full = false) => <div id={full ? 'fsVol' : undefined} className={full ? 'fs-volume' : 'volume-row'}><button className="aicon" onClick={toggleVolume} data-tooltip={muted ? 'Unmute' : 'Mute'} aria-label={muted ? 'Unmute' : 'Mute'} aria-pressed={muted}><span id={full ? 'volIcon2' : 'volIcon'}>{icon('volume', full ? 24 : 20)}</span></button><div className={full ? 'fs-volume-bar' : ''} id={full ? 'fsVolBar' : 'vol'} {...volumeHandlers()} role="slider" tabIndex={0} aria-label="Volume level" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((muted ? 0 : Math.sqrt(volume)) * 100)} aria-valuetext={`${Math.round((muted ? 0 : Math.sqrt(volume)) * 100)}%`} onKeyDown={(event) => {
    const now = (muted ? 0 : Math.sqrt(volume)) * 100;
    const to = { ArrowRight: now + 5, ArrowUp: now + 5, ArrowLeft: now - 5, ArrowDown: now - 5, PageUp: now + 20, PageDown: now - 20, Home: 0, End: 100 }[event.key];
    if (to === undefined) return;
    event.preventDefault();
    setVolumePercent(to);
  }}><i id={full ? 'fsVolFill' : 'volf'} style={{ width: `${(muted ? 0 : Math.sqrt(volume)) * 100}%` }} /></div></div>;
  const progress = (full = false) => <SeekBar audioRef={audioRef} duration={duration} handlers={seekHandlers()} full={full} decor={narrow && !full} />;

  return <>
    <a id="skip" className="skip" href="#main" onClick={(event) => { event.preventDefault(); document.getElementById('main')?.focus(); }}>Skip to content</a>{currentTrack && <a id="skip2" className="skip" href="#bar" onClick={(event) => { event.preventDefault(); document.getElementById('playb')?.focus(); }}>Skip to player</a>}<header id="top"><button id="libBtn" className={`top-lib${links.length ? '' : ' is-hidden'}`} onClick={toggleSide} data-tooltip={drawerOpen ? 'Close library' : 'Open library'} aria-label={drawerOpen ? 'Close library' : 'Open library'} aria-expanded={drawerOpen}><Icon name="library" size={20}/></button><button id="homeBtn" onClick={goHome} data-tooltip="Home" aria-label="Home"><Icon name="home"/></button><div id="searchwrap" className={query ? 'filled' : ''}><Icon name="search" size={20}/><input id="q" aria-label="Search" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} placeholder={narrow ? 'Search' : 'What do you want to play?'}/><button id="qClear" onClick={() => { setQuery(''); document.querySelector('#q')?.focus(); }} data-tooltip="Clear search" aria-label="Clear search"><Icon name="close" size={16}/></button></div><button id="settingsBtn" onClick={() => setSettingsOpen(true)} data-tooltip="Settings" aria-label="Open settings"><Settings2 size={20} strokeWidth={1.8} aria-hidden="true"/></button>{updateState?.supported && <div id="upd" className={`${updateMessage ? 'on' : 'on icononly'}`}><span id="updtext">{updateMessage || (updateState.available ? `Kotassium ${updateState.latest} is available (${updateStepsText(updateState.version, updateState.latest)})${updateState.can_install === false ? ' — move it to Applications to update' : ''}` : '')}</span><button id="updbtn" className={updateState.available ? 'go' : ''} onClick={updateState.available ? startUpdate : checkUpdate} disabled={updateBusy} data-tooltip={updateState.available ? 'Restart & Update' : 'Check for updates'} aria-label={updateState.available ? 'Restart and install update' : 'Check for updates'}>{updateState.available ? <Download size={16} strokeWidth={2.2} aria-hidden="true"/> : <RefreshCw size={16} strokeWidth={2} className={updateBusy ? 'lucide-spin' : ''} aria-hidden="true"/>}</button>{updateState.available && <button id="updcheck" onClick={checkUpdate} disabled={updateBusy} data-tooltip="Check again" aria-label="Check for updates again"><RotateCw size={16} strokeWidth={1.9} aria-hidden="true"/></button>}</div>}</header>
    {settingsOpen && <div className="settings-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSettingsOpen(false); }}>
      <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
        <header className="settings-head">
          <h2 id="settingsTitle">Settings</h2>
          <button className="settings-close" onClick={() => setSettingsOpen(false)} aria-label="Close settings"><Icon name="close" size={20}/></button>
        </header>
        <div className="settings-content">
          <section className="settings-group">
                        <div className="settings-card">
              <div className="setting-row" onClick={toggleRow}><div className="setting-copy"><b>Track change notifications</b></div><button className={`setting-switch ${notifyTrackChanges ? 'enabled' : ''}`} role="switch" aria-checked={notifyTrackChanges} aria-label="Track change notifications" onClick={() => setNotifyTrackChanges((value) => { const next = !value; try { localStorage.setItem('kot_notify_track_changes', next ? '1' : '0'); } catch {} return next; })}><i/></button></div>
            </div>
          </section>
          <p className="settings-foot">{/^v?\d/.test(versionLabel || '') ? 'Version ' : ''}<span id="appVersion">{versionLabel}</span>{versionNote ? ` · ${versionNote}` : null}</p>
          {updateState?.supported && <section className="settings-group">
            <h3 className="settings-label">Updates</h3>
            <div className="settings-card">
              <div className="setting-row"><div className="setting-copy"><b>Restore previous version</b><small>{updateState.rollback_available ? 'Reinstall the version saved before the last update — the app closes and reopens' : 'No earlier version is saved on this Mac'}</small></div><button id="rollbackBtn" className="setting-act" disabled={!updateState.rollback_available} onClick={async () => { if (!window.confirm('Restore the previous Kotassium version? The app will close and reopen.')) return; try { await postJSON('/api/update/rollback', {}); } catch { toast('could not start rollback'); } }}>Restore</button></div>
            </div>
          </section>}
        </div>
      </section>
    </div>}
    {linkOpen && <div className="link-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setLinkOpen(false); }}>
      <section className="link-dialog" role="dialog" aria-modal="true" aria-labelledby="linkTitle">
        <header className="link-dialog-head"><h2 id="linkTitle">Add a Spotify link</h2><button className="settings-close" onClick={() => setLinkOpen(false)} disabled={busy} aria-label="Close add link dialog"><Icon name="close" size={20}/></button></header>
        <form className="link-form" onSubmit={(event) => { event.preventDefault(); if (!busy) addLink(); }}><label htmlFor="plink" className="sr-only">Playlist, album or track link</label><div className="link-input-wrap"><input id="plink" type="url" value={linkValue} onChange={(event) => setLinkValue(event.target.value)} placeholder="https://open.spotify.com/…" autoComplete="url" required disabled={busy}/></div><div className="link-opt" onClick={toggleRow}><span><b>Download all tracks</b></span><button id="bgdl" type="button" className={`setting-switch ${bgDownload ? 'enabled' : ''}`} role="switch" aria-checked={bgDownload} aria-label="Download all tracks" onClick={() => setBgDownload((value) => !value)} disabled={busy}><i/></button></div><button className="link-submit" type="submit" disabled={busy || !linkValue.trim()}>{busy ? <><i className="link-spinner"/>Adding to library…</> : 'Add'}</button></form>
      </section>
    </div>}
    <div id="mid" className={sideDragWidth !== null ? 'resizing' : ''}>{drawerOpen && narrow && <div className="scrim" onClick={() => setDrawerOpen(false)}/>}<aside id="side" role={drawerOpen && narrow ? 'dialog' : undefined} aria-modal={drawerOpen && narrow ? true : undefined} aria-label="Library" className={`${(sideResizePreview !== null ? sideResizePreview : collapsed) ? 'collapsed' : ''} ${drawerOpen ? 'open' : ''} ${links.length ? '' : 'bare'}`} onTouchStart={(e) => gestureStart(e, 'side')} onTouchMove={(e) => gestureMove(e, 'side')} onTouchEnd={(e) => gestureEnd(e, 'side')} onTouchCancel={(e) => gestureEnd(e, 'side')} onClickCapture={suppressGestureClick}><div id="sideHead"><button id="libToggle" onClick={toggleSide} data-tooltip={narrow ? 'Close library' : collapsed ? 'Expand library' : 'Collapse library'} aria-label={narrow ? 'Close library' : collapsed ? 'Expand library' : 'Collapse library'}><Icon name="library" size={20}/><b>Your library</b></button><button id="addBtn" onClick={addLibraryLink} data-tooltip="Add Spotify link" aria-label="Add Spotify link"><Icon name="add" size={20}/></button></div><div id="sideList">{links.length ? links.map((p, i) => <div className={`pitem ${view.type === 'playlist' && view.name === p.name ? 'active' : ''}`} key={p.url || p.name} data-tooltip={collapsed ? p.name : undefined} role="link" tabIndex={0} aria-label={`Open ${p.name}`} onClick={() => loadPlaylist(i)} onKeyDown={onActivate(() => loadPlaylist(i))}><div className="pcover" data-tooltip={collapsed ? p.name || '?' : undefined} style={{ background: coverBackground(p.cover || p.tracks?.[0]?.cover, p.name) }} onMouseEnter={() => warmCover(p.cover || p.tracks?.[0]?.cover)} onClick={(e) => { if (window.matchMedia('(hover: none)').matches) return; e.stopPropagation(); loadPlaylist(i, true); }}><button className="pcoverPlay" tabIndex={-1} data-tooltip={`Play ${p.name}`} aria-label={`Play ${p.name}`} onClick={(e) => { e.stopPropagation(); loadPlaylist(i, true); }}><Icon name="play" size={20}/></button></div><div className="pmeta"><b>{p.name || '?'}</b><small>{songCount(p)}</small></div></div>) : null}</div></aside><div id="sideResize" role="separator" aria-label="Resize library" aria-orientation="vertical" aria-valuemin={68} aria-valuemax={262} aria-valuenow={sideDragWidth ?? (collapsed ? 68 : 262)} tabIndex={0} onPointerDown={startSidebarResize} onPointerMove={moveSidebarResize} onPointerUp={finishSidebarResize} onPointerCancel={finishSidebarResize} onKeyDown={keySidebarResize}/><main id="main" tabIndex={-1}>{renderMain()}</main></div>
    <footer id="bar" className={currentTrack ? '' : 'idle'} onTouchStart={(e) => gestureStart(e, 'bar')} onTouchMove={(e) => gestureMove(e, 'bar')} onTouchEnd={(e) => gestureEnd(e, 'bar')} onTouchCancel={(e) => gestureEnd(e, 'bar')} onClickCapture={suppressGestureClick}><div className="barfull" style={{ display: 'contents' }}><div id="nowp"><button id="nowc" onClick={narrow ? mobileOpen : toggleDesktop} data-tooltip="Open player" aria-label="Open player" style={{ background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t) : '#282828' }} onMouseEnter={() => warmCover(currentTrack?.cover)} /><div id="nowt" onClick={narrow ? mobileOpen : undefined}><b>{currentTrack?.t || 'Nothing playing'}</b><small>{currentTrack ? currentTrack.a : links.length ? 'Pick a playlist' : ''}</small></div>{currentTrack && <div className="nowsave-wrap"><button id="nowsave" className={inCurrentPlaylist ? 'on' : ''} onClick={toggleSaveMenu} aria-label={inCurrentPlaylist ? 'Saved' : 'Add to playlist'} aria-expanded={saveOpen} data-tooltip={inCurrentPlaylist ? 'Saved' : 'Add to playlist'}><Icon name={inCurrentPlaylist ? 'check' : 'add'} size={16}/></button>{saveOpen && <div className="save-menu" role="dialog" aria-modal="true" aria-label="Add to playlist"><div className="save-head"><b>Add to playlist</b><button className="save-close" onClick={() => setSaveOpen(false)} aria-label="Close"><Icon name="close" size={16}/></button></div><div className="save-list">{links.length ? links.map((l) => { const inIt = !!(saveContains && saveContains[l.url || l.name]); return <button key={l.url || l.name} className={`save-row ${inIt ? 'in' : ''}`} onClick={() => togglePlaylistMembership(l)} aria-pressed={inIt}><span className="save-name">{l.name || '?'}</span><span className="save-mark"><Icon name={inIt ? 'check' : 'add'} size={16}/></span></button>; }) : <div className="save-empty"><p>No playlists yet</p><button className="pill-cta" onClick={() => { setSaveOpen(false); setLinkOpen(true); }}><Icon name="add" size={20}/>Add a Spotify link</button></div>}</div></div>}</div>}</div><div id="ctr">{controls()}{progress()}</div><div id="rside">{volumeRow()}<button id="dfsBtn" disabled={!currentTrack} className={`aicon desktop-fullscreen ${desktopPlayer ? 'is-open' : ''}`} onClick={toggleDesktop} data-tooltip={desktopPlayer ? 'Exit full screen' : 'Full screen'} aria-label={desktopPlayer ? 'Exit full screen' : 'Full screen'}><Icon name={desktopPlayer ? 'exitFullscreen' : 'fullscreen'}/></button></div></div></footer>
    <div id="fs" className={mobilePlayer ? 'on' : ''} role="dialog" aria-modal={mobilePlayer ? true : undefined} aria-label="Now playing" onTouchStart={(e) => gestureStart(e, 'fs')} onTouchMove={(e) => gestureMove(e, 'fs')} onTouchEnd={(e) => gestureEnd(e, 'fs')} onTouchCancel={(e) => gestureEnd(e, 'fs')} onClickCapture={suppressGestureClick}><button id="fsGrip" onClick={mobileClose} aria-label="Close player"/><div id="fsHead"><span id="fsPl">{playingPlaylist || 'Now playing'}</span></div><div id="fsArt" style={{ background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t) : '#282828' }} onMouseEnter={() => warmCover(currentTrack?.cover)}/><div id="fsTxt"><b>{currentTrack?.t || 'Nothing playing'}</b><small>{currentTrack?.a || 'Pick a playlist'}</small></div><div id="fsQueue" style={{ display: upcoming.length ? '' : 'none' }}><div id="fsQhead"><b>Up next</b></div><div id="fsQrows">{mobilePlayer && upcoming.map((i, n) => <div className="fsQrow" key={`${trackKey(queue[i])}-${i}`} role="button" tabIndex={n === 0 ? 0 : -1} aria-label={`Play ${queue[i]?.t || ''}`} onClick={() => playIndex(i)} onKeyDown={rowKeys(() => playIndex(i))}><span className="fsQn">{n + 1}</span><span className="fsQcov" style={{ background: coverBackground(queue[i]?.cover, queue[i]?.t) }}/><span className="fsQt"><b>{queue[i]?.t}</b><small>{queue[i]?.a}</small></span><span className="fsQtime">{fmt(queue[i]?.ms)}</span></div>)}</div></div><div id="fsIsland">{progress(true)}{controls(true)}{volumeRow(true)}</div></div>
    {desktopPlayer && <div id="dfs" role="dialog" aria-modal="true" aria-label="Now playing" className={`open ${desktopIdle ? 'idle' : ''}`} onMouseMove={() => setDesktopIdle(false)}><div id="dfsMain"><div id="dfsTop"><span id="dfsTopTitle">{playingPlaylist || 'Now playing'}</span><button id="dfsExit" onClick={() => setDesktopPlayer(false)} data-tooltip="Exit full screen" aria-label="Exit full screen"><Icon name="exitFullscreen" size={20}/></button></div><div id="dfsArt" style={{ background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t) : '#282828' }}/><div id="dfsInfo"><b id="dfsTitle">{currentTrack?.t || 'Nothing playing'}</b><small id="dfsArtist">{currentTrack?.a || 'Pick a playlist'}</small></div></div><div id="dfsQueue" style={{ display: queue.length ? '' : 'none' }}><div id="dfsQhead"><b>Queue</b><span id="dfsQcount">{queue.length} {queue.length === 1 ? 'track' : 'tracks'}</span></div><div id="dfsQrows">{currentTrack ? <><div className="dfsQsect">Now Playing</div><QueueRow track={currentTrack} active onClick={() => playIndex(currentIndex)} />{upcoming.length > 0 && <div className="dfsQsect">Next Up</div>}{upcoming.map((i) => <QueueRow key={`${trackKey(queue[i])}-${i}`} track={queue[i]} onClick={() => playIndex(i)}/>)}</> : queue.map((track, index) => <QueueRow key={`${trackKey(track)}-${index}`} track={track} onClick={() => playIndex(index)}/>)}</div></div></div>}
    <div id="toast" className="toast-viewport" aria-label="Notifications" aria-live="polite">
      {download && <div className="toast-card toast-download" role="status">
        <span className="toast-icon" aria-hidden="true"><i className="toast-spinner"/></span>
        <div className="toast-body"><b>{download.status === 'done' ? 'Download ready' : download.status === 'queued' ? 'Starting download' : 'Downloading'}</b><span>{download.label || 'Track'}</span><div className="toast-progress" role="progressbar" aria-label="Download progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(download.pct)}><i style={{ width: `${download.pct}%` }}/></div></div>
        <small className="toast-percent">{Math.round(download.pct)}%</small>
      </div>}
      {(upNext || (radio && !nextTrack && currentTrack)) && currentTrack && !desktopPlayer && !upNextDismissed && <div id="upnext" className="toast-card toast-upnext" role="status">
        <span className="toast-icon toast-upnext-icon" aria-hidden="true">♫</span>
        <div className="toast-body"><b>Up next</b><span>{radioSearching ? 'Finding radio tracks…' : `${displayNextTrack?.t || ''}${displayNextTrack?.a ? ` · ${displayNextTrack.a}` : ''}`}</span></div>
        <button className="toast-close" type="button" aria-label="Dismiss up next notification" onClick={() => { upNextGone.current = true; setUpNext(false); setUpNextDismissed(true); }}><Icon name="close" size={16}/></button>
      </div>}
      {toastItems.map((item) => <div key={item.id} className={`toast-card toast-${item.variant}`} role={item.variant === 'error' ? 'alert' : 'status'}>
        <span className="toast-icon" aria-hidden="true">{item.variant === 'success' ? '✓' : item.variant === 'error' ? '!' : '•'}</span>
        <p className="toast-message">{item.message}</p>
        <button className="toast-close" type="button" aria-label="Dismiss notification" onClick={() => dismissToast(item.id)}><Icon name="close" size={16}/></button>
      </div>)}
    </div><audio ref={audioRef} preload="auto" />

  </>;
}

function QueueRow({ track, active = false, onClick }) { return <div className={`dfsQrow ${active ? 'cur' : ''}`} role="button" tabIndex={active ? 0 : -1} aria-label={`Play ${track?.t || ''}`} onClick={onClick} onKeyDown={rowKeys(onClick)}><span className="dfsQcov" style={{ background: track?.cover ? escStyle(track.cover) : gradient(track?.t) }}/><span className="dfsQt"><b>{track?.t}</b><small>{track?.a}</small></span></div>; }

class AppBoundary extends React.Component {
  constructor(props) { super(props); this.state = { failed: false, rollbackError: '' }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.showRecovery(); }
  componentDidUpdate() { if (this.state.failed) this.showRecovery(); }
  showRecovery() {
    const panel = document.getElementById('recovery');
    if (panel) panel.classList.add('visible');
    window.__kotShowRecovery?.();
  }
  rollback = async () => {
    this.setState({ rollbackError: '' });
    try {
      const response = await fetch('/api/update/rollback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      const result = await response.json();
      this.setState({ rollbackError: result.error || 'No recovery instructions were returned.' });
    } catch {
      this.setState({ rollbackError: 'Could not get recovery instructions. Close and reopen the app, then try again.' });
    }
  };
  render() {
    if (this.state.failed) return <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, background: '#090909', color: '#fff', fontFamily: 'system-ui,sans-serif', textAlign: 'center' }}><div><h1 style={{ fontSize: 22 }}>Kotassium couldn’t start</h1><p style={{ color: '#aaa' }}>The player hit a problem. Reload it, or follow the recovery instructions to restore the previous app version if available.</p>{window.__kotRollbackAvailable && <button onClick={this.rollback} style={{ margin: '12px 8px 0', padding: '10px 18px', borderRadius: 24, background: '#1ed760', color: '#07140a', fontWeight: 700 }}>Restore previous version</button>}<button onClick={() => location.reload()} style={{ margin: '12px 8px 0', padding: '10px 18px', borderRadius: 24, background: '#292929', color: '#fff', fontWeight: 700 }}>Reload player</button>{this.state.rollbackError && <p role="status" style={{ color: '#aaa', maxWidth: 560 }}>{this.state.rollbackError}</p>}</div></main>;
    return this.props.children;
  }
}

// Touch + pointer gestures work on Android WebView and desktop browsers.
function bootstrap() {
  createRoot(document.getElementById('root')).render(<AppBoundary><><App/><TooltipLayer/></></AppBoundary>);
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === '127.0.0.1' || location.hostname === 'localhost')) navigator.serviceWorker.register('/sw.js').catch(() => {});
}

bootstrap();
