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
const gradient = (name) => { const h = hue(name); return `linear-gradient(135deg,hsl(${h},70%,38%),hsl(${(h + 40) % 360},60%,20%))`; };
const escStyle = (url) => `url("${String(url || '').replace(/["'<>)]/g, (c) => encodeURIComponent(c))}") center/cover no-repeat`;
function Icon({ name, size = 20, children }) {
  const viewBox = ['add', 'play', 'pause', 'prev', 'next'].includes(name) ? '0 0 16 16' : '0 0 24 24';
  const p = {
    library: <><path d="M3 3h2.5v18H3zM7 3h2.5v18H7zM11 3.6L21.6 5v14L11 20.4z" fill="currentColor" stroke="none" /></>,
    home: <path d="M12 3l9 8h-2.5v9h-5v-6h-3v6h-5v-9H3z" fill="currentColor" stroke="none" />,
    search: <><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></>,
    close: <><path d="m5 5 14 14M19 5 5 19"/></>,
    browse: <path d="M3 4.5h13v2H3zM3 8.25h13v2H3zM3 12h18v7.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19.5z" fill="currentColor" stroke="none" />,
    add: <path d="M8 1.5a.75.75 0 0 1 1.5 0v5h5a.75.75 0 0 1 0 1.5h-5v5a.75.75 0 0 1-1.5 0V8H3a.75.75 0 0 1 0-1.5h5v-5z" fill="currentColor" stroke="none" />,
    play: <path d="M3 1.713a.7.7 0 0 1 1.05-.607l10.89 6.288a.7.7 0 0 1 0 1.212L4.05 14.894A.7.7 0 0 1 3 14.288V1.713z" transform="translate(0.6 0)" fill="currentColor" stroke="none" />,
    pause: <path d="M4.8 3a.7.7 0 0 0-.7.7v10.6a.7.7 0 0 0 .7.7h1.6a.7.7 0 0 0 .7-.7V3.7a.7.7 0 0 0-.7-.7H5.7zm4.8 0a.7.7 0 0 0-.7.7v10.6a.7.7 0 0 0 .7.7h1.6a.7.7 0 0 0 .7-.7V3.7a.7.7 0 0 0-.7-.7h-1.6z" transform="translate(0 -1)" fill="currentColor" stroke="none" />,
    prev: <path d="M3.3 1a.7.7 0 0 1 .7.7v5.15l9.95-5.744a.7.7 0 0 1 1.05.606v12.575a.7.7 0 0 1-1.05.607L4 9.149V14.3a.7.7 0 0 1-.7.7H1.7a.7.7 0 0 1-.7-.7V1.7a.7.7 0 0 1 .7-.7h1.6z" fill="currentColor" stroke="none" />,
    next: <path d="M12.7 1a.7.7 0 0 0-.7.7v5.15L2.05 1.107A.7.7 0 0 0 1 1.712v12.575a.7.7 0 0 0 1.05.607L12 9.149V14.3a.7.7 0 0 0 .7.7h1.6a.7.7 0 0 0 .7-.7V1.7a.7.7 0 0 0-.7-.7h-1.6z" fill="currentColor" stroke="none" />,
    shuffle: <><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></>,
    repeat: <><path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/></>,
    volume: <><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></>,
    fullscreen: <><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></>,
    exitFullscreen: <><polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/><line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.4 1.1-1.4 2.4-1.7-.7a8 8 0 0 1-1.8 1l-.3 1.8h-2.8l-.3-1.8a8 8 0 0 1-1.8-1l-1.7.7-1.4-2.4L7.1 15a8 8 0 0 1 0-2l-1.4-1.1 1.4-2.4 1.7.7a8 8 0 0 1 1.8-1l.3-1.8h2.8l.3 1.8a8 8 0 0 1 1.8 1l1.7-.7 1.4 2.4-1.4 1.1a8 8 0 0 1 0 2Z" transform="translate(-1 -2) scale(1.08)"/></>
  };
  return <svg width={size} height={size} viewBox={viewBox} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children || p[name]}</svg>;
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
    const show = (event) => {
      const node = event.target?.closest?.('[data-tooltip]');
      if (!node || !node.dataset.tooltip || node.disabled) return;
      target = node;
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
      clearTimeout(timer); target = null; setTooltip(null);
    };
    document.addEventListener('mouseover', show);
    document.addEventListener('mouseout', hide);
    document.addEventListener('focusin', show);
    document.addEventListener('focusout', hide);
    return () => {
      clearTimeout(timer);
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

function App() {
  useEffect(() => { window.__kotReactReady?.(); }, []);
  const audioRef = useRef(null);
  const cacheRef = useRef(null);
  if (!cacheRef.current) {
    try { cacheRef.current = JSON.parse(localStorage.getItem('kot_ytcache') || '{}'); } catch { cacheRef.current = {}; }
  }
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
  const [radio, setRadio] = useState(false);
  const [shuffle, setShuffle] = useState(() => { try { return localStorage.getItem('kot_shuf') === '1'; } catch { return false; } });
  const [repeat, setRepeat] = useState(() => { try { const value = localStorage.getItem('kot_repeat'); return value === null ? 1 : Number(value); } catch { return 1; } });
  const [shuffleOrder, setShuffleOrder] = useState([]);
  const [shufflePos, setShufflePos] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
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
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkValue, setLinkValue] = useState('');
  const [bgDownload, setBgDownload] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toastText, setToastText] = useState('');
  const [upNext, setUpNext] = useState(false);
  const upNextGone = useRef(false);
  const [toastDismissed, setToastDismissed] = useState(false);
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
  const toastTimer = useRef(0);
  const toastGesture = useRef({ active: false, startX: 0, startY: 0, deltaX: 0, dismissed: false, previousOpacity: '' });
  const dragStart = useRef(null);
  const mobileGesture = useRef({ startX: 0, startY: 0, target: null, queueScrollTop: 0, moved: false, openedBySwipe: false, closeTimer: 0 });
  const suppressTapUntil = useRef(0);
  const lastUpNextTrack = useRef('');
  const currentTrack = currentIndex >= 0 ? queue[currentIndex] : null;
  const duration = actualDuration || (currentTrack?.ms ? currentTrack.ms / 1000 : 0);
  const toast = useCallback((message) => {
    toastGesture.current.dismissed = false;
    setToastDismissed(false);
    setToastText(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastText(''), 3000);
  }, []);
  const toastPointerStart = (event) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    const node = event.currentTarget;
    toastGesture.current = { ...toastGesture.current, active: true, startX: event.clientX, startY: event.clientY, deltaX: 0, dismissed: false, previousOpacity: node.style.opacity || '' };
    node._drag = true;
    try { node.setPointerCapture(event.pointerId); } catch {}
    if (node.id === 'toast') clearTimeout(toastTimer.current);
  };
  const toastPointerMove = (event) => {
    const gesture = toastGesture.current;
    if (!gesture.active) return;
    const dx = event.clientX - gesture.startX, dy = event.clientY - gesture.startY;
    if (Math.abs(dx) < 5 && Math.abs(dy) < 5) return;
    if (dx <= 0 || Math.abs(dx) <= Math.abs(dy)) {
      gesture.active = false; event.currentTarget._drag = false;
      if (event.currentTarget.id === 'toast') toastTimer.current = setTimeout(() => setToastText(''), 3000);
      return;
    }
    event.preventDefault();
    gesture.deltaX = dx;
    event.currentTarget.style.transition = 'none';
    event.currentTarget.style.transform = `translateX(${dx}px)`;
    event.currentTarget.style.opacity = String(Math.max(0, 1 - dx / 140));
  };
  const toastPointerEnd = (event) => {
    const gesture = toastGesture.current;
    if (!gesture.active) return;
    gesture.active = false;
    const node = event.currentTarget;
    node.style.transition = 'transform .25s cubic-bezier(.2,.8,.2,1),opacity .25s';
    if (gesture.deltaX > 70) {
      gesture.dismissed = true;
      node.style.transform = 'translateX(150%)';
      node.style.opacity = '0';
      setTimeout(() => {
        node.style.transform = ''; node.style.transition = ''; node._drag = false;
        if (node.id === 'upnext') { upNextGone.current = true; setUpNext(false); }
        else { setToastDismissed(true); setToastText(''); }
      }, 250);
    } else {
      node.style.transform = ''; node.style.opacity = gesture.previousOpacity; node._drag = false;
      if (node.id === 'toast') toastTimer.current = setTimeout(() => setToastText(''), 3000);
    }
  };
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
  const loadPlaylist = useCallback(async (i, play = false, suppliedLinks = links) => {
    const item = suppliedLinks[i];
    if (!item) return;
    const req = ++requestRef.current;
    const key = item.url || item.name || '';
    try {
      const warmed = key && warmedPlaylists.current.get(key);
      let full = warmed ? await warmed : null;
      if (req !== requestRef.current) return;
      if (!full?.tracks?.length) {
        warmedPlaylists.current.delete(key);
        full = await API(`/api/links/get?url=${encodeURIComponent(item.url || '')}`);
        if (req !== requestRef.current) return;
      }
      if (full?.error) full = item;
      const tracks = (full?.tracks || item.tracks || []).filter((t) => t?.t);
      setPlaylist(tracks); setView({ type: 'playlist', name: item.name || 'Playlist' });
      setDrawerOpen(false);
      if (play && tracks.length) {
        const choice = full?.choice;
        const warmedIndex = choice ? tracks.findIndex((t) => trackKey(t) === trackKey(choice)) : -1;
        if (key && warmedIndex >= 0) {
          const warmed = prefetchJobsRef.current.get(trackKey(choice));
          if (warmed && await warmed === false) prefetchJobsRef.current.delete(trackKey(choice));
          if (req !== requestRef.current) return;
        }
        const index = warmedIndex >= 0 ? warmedIndex : (shuffle ? Math.floor(Math.random() * tracks.length) : 0);
        startQueueRef.current(tracks, item.name || 'Playlist', index);
      }
    } catch { toast('Could not open playlist'); }
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
    const response = await API(`/api/search?src=youtube&q=${encodeURIComponent(q)}`);
    const target = (Number(track.ms) || 0) / 1000;
    const videos = (response.results || []).filter((r) => r.source === 'youtube').map((r, i) => ({ ...r, _order: i, _delta: target && r.dur ? Math.abs(r.dur - target) : Infinity }))
      .sort((a, b) => a._delta - b._delta || a._order - b._order).slice(0, 8);
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
    } catch (error) {
      if (epoch !== playbackEpoch.current) return;
      if (candidateIndex + 1 < candidates.length) return startResolvedTrack(track, candidates, candidateIndex + 1, cacheKey, false, epoch);
      if (cached) {
        delete cacheRef.current[cacheKey];
        try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {}
        if (candidateIndex === 0) return playTrackRef.current?.({ ...track, source: '', id: '' });
      }
      toast(error.message || `Could not fetch ${track.t || 'track'}`);
    }
  }, [asInteractive, downloadId, toast]);

  const playTrack = useCallback(async (track) => {
    if (!track) return;
    upNextGone.current = false;
    setUpNextDismissed(false);
    const epoch = ++playbackEpoch.current;
    setCurrentTime(0); setActualDuration(0); setPaused(true);
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
    const pending = asInteractive((async () => {
      try {
        const knownId = track.id && (track.source === 'youtube' || track.source === 'newgrounds' || track.source === 'soundcloud');
        const cachedId = !track.source && cacheRef.current[key];
        // Prefetching must not be the thing that pays for source discovery:
        // an id the track already carries needs no search, and a remembered
        // one names a file ytdl can answer locally.
        const candidates = knownId ? [track] : cachedId ? [{ source: 'youtube', id: cachedId, dur: 0 }] : await findCandidates(track);
        if (!candidates[0]?.id) { prefetchRef.current.delete(key); return; }
        cacheRef.current[key] = candidates[0].id;
        try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {}
        await runDownload(candidates[0].id, track.t);
        return undefined;
      } catch {
        prefetchRef.current.delete(key);
        return false;
      }
    })());
    prefetchJobsRef.current.set(key, pending);
    return pending;
  }, [asInteractive, findCandidates, runDownload]);
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
      const remember = (id) => { cacheRef.current[key] = id; try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {} };
      const forget = () => { if (!knownId && cacheRef.current[key]) { delete cacheRef.current[key]; try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {} } };
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
  }, [findCandidates, runDownload, toast]);

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
    const shouldShow = !!(actualDuration && currentTime > 0 && actualDuration - currentTime <= 30 && (nextTrack || radio));
    if (!shouldShow) {
      setUpNextDismissed(false); upNextGone.current = false; setUpNext(false);
    } else if (!upNextGone.current) {
      setUpNext(true);
    }
  }, [actualDuration, currentTime, nextTrack, currentTrack, radio]);

  useEffect(() => {
    let alive = true;
    loadLinks();
    API('/api/cover/index').then((m) => { if (alive && m && typeof m === 'object') { coverCacheRef.current = m; setCoverMap(m); } }).catch(() => {});
    if (/[?&]desktop=1/.test(location.search)) setTimeout(() => pollUpdate(), 1500);
    else {
      let mtime = 0;
      const check = () => API('/api/mtime').then((j) => { if (mtime && j.mtime && j.mtime !== mtime) location.reload(); mtime = j.mtime || mtime; }).catch(() => {});
      check(); const timer = setInterval(check, 2000);
      return () => { alive = false; clearInterval(timer); clearTimeout(toastTimer.current); };
    }
    return () => { alive = false; clearTimeout(toastTimer.current); };
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
      else if (st.state === 'error') setUpdateMessage(st.error || 'update failed');
      else if (st.available) setUpdateMessage(`Kotassium ${st.latest || 'A Kotassium update'} is available (${updateStepsText(st.version, st.latest)})${st.can_install === false ? ' — move it to Applications to update' : ''}`);
      else if (updateCheckManual.current && !st.error) {
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
    const onTime = () => setCurrentTime(audio.currentTime || 0);
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
          if (pending.cached) { delete cacheRef.current[pending.cacheKey]; try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {} }
          else {
            const actualKey = `${queue[currentIndex]?.t || ''}|${queue[currentIndex]?.a || ''}`;
            cacheRef.current[actualKey] = pending.id;
            try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {}
          }
          audio.pause(); audio.removeAttribute('src'); audio.load();
          startResolvedTrack(queue[currentIndex], pending.candidates, pending.index + 1, pending.cacheKey, false, playbackEpoch.current);
          return;
        }
        if (expected && Math.abs(actual - expected) > Math.max(8, expected * 0.2) && pending.cached) {
          delete cacheRef.current[pending.cacheKey];
          try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {}
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
    audio.addEventListener('timeupdate', onTime); audio.addEventListener('play', onPlay); audio.addEventListener('pause', onPause);
    audio.addEventListener('loadedmetadata', onMeta); audio.addEventListener('ended', onEnded); audio.addEventListener('error', onError);
    return () => { audio.removeEventListener('timeupdate', onTime); audio.removeEventListener('play', onPlay); audio.removeEventListener('pause', onPause); audio.removeEventListener('loadedmetadata', onMeta); audio.removeEventListener('ended', onEnded); audio.removeEventListener('error', onError); };
  }, [queue, currentIndex, repeat, next, playTrack, startResolvedTrack, radio, fetchRadio, shufflePos, shuffleOrder]);

  useEffect(() => {
    if (!currentTrack) return;
    const state = paused ? 'paused' : 'playing';
    const key = `${trackKey(currentTrack)}|${state}`;
    const now = Date.now();
    if (key !== lastNowPlaying.current.key || now - lastNowPlaying.current.at >= 2500 || duration !== lastNowPlaying.current.duration) {
      lastNowPlaying.current = { key, at: now, duration };
      const payload = { t: currentTrack.t || '', a: currentTrack.a || '', album: currentTrack.album || '', cover: currentTrack.cover || '', ms: Math.round(duration * 1000) || currentTrack.ms || 0, pos: Math.round(currentTime * 1000), state };
      postJSON('/api/nowplaying', payload).catch(() => {});
    }
    if ('mediaSession' in navigator && typeof MediaMetadata !== 'undefined') {
      try { navigator.mediaSession.metadata = new MediaMetadata({ title: currentTrack.t || '?', artist: currentTrack.a || '', album: currentTrack.album || '' }); } catch {}
    }
  }, [currentTrack, currentTime, duration, paused]);
  useEffect(() => {
    if (!('mediaSession' in navigator)) return;
    try {
      navigator.mediaSession.setActionHandler('play', () => { if (audioRef.current) audioRef.current.play().catch(() => {}); }); navigator.mediaSession.setActionHandler('pause', () => audioRef.current?.pause());
      navigator.mediaSession.setActionHandler('nexttrack', () => next()); navigator.mediaSession.setActionHandler('previoustrack', () => previous());
    } catch {}
  }, [togglePlay, next, previous]);
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.code === 'Space' && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName || '')) {
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
      dragging: owner === 'fs' && !queue, inQueue: !!queue,
      baseY: owner === 'fs' ? 0 : window.innerHeight, queueScrollTop: queue?.scrollTop || 0,
    };
  };
  const gestureMove = (event, owner) => {
    const g = mobileGesture.current;
    if (g.owner !== owner) return;
    const touch = event.touches[0], dx = touch.clientX - g.startX, dy = touch.clientY - g.startY;
    g.lastX = touch.clientX; g.lastY = touch.clientY; g.lastAt = Date.now();
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
    const elapsed = Math.max(1, Date.now() - g.lastAt);
    const vx = (touch.clientX - g.lastX) / elapsed, vy = (touch.clientY - g.lastY) / elapsed;
    if (g.dragging && g.moved) suppressTapUntil.current = Date.now() + 400;
    if (owner === 'bar' && g.dragging) {
      const fs = document.getElementById('fs');
      if (fs && (g.positionY < window.innerHeight * 0.5 || vy < -0.6)) {
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
  const toggleDesktop = useCallback(() => {
    if (!desktopPlayer && (window.innerWidth <= 820 || !currentTrack)) return;
    setDesktopPlayer((value) => !value);
    setDesktopIdle(false);
  }, [desktopPlayer, currentTrack]);
  const pollUpdate = useCallback(() => API('/api/update').then((st) => { setUpdateState(st); if (st.supported) setUpdateMessage(st.available ? `Kotassium ${st.latest} is available` : ''); return st; }).catch(() => {}), []);
  const updateSteps = useCallback((current, latest) => {
    const from = String(current || '').match(/\d+/g), to = String(latest || '').match(/\d+/g);
    if (!from || !to) return 'a new version';
    const a = from.slice(0, 3).map(Number), b = to.slice(0, 3).map(Number);
    while (a.length < 3) a.push(0);
    while (b.length < 3) b.push(0);
    const count = a[0] !== b[0] || a[1] !== b[1] ? 1 : Math.max(1, b[2] - a[2]);
    return `${count} version${count === 1 ? '' : 's'} forward`;
  }, []);
  const checkUpdate = useCallback(async () => { updateCheckManual.current = true; clearTimeout(updateStatusTimer.current); setUpdateBusy(true); setUpdateMessage('Checking for updates…'); try { const st = await postJSON('/api/update/check', {}); setUpdateState(st); if (st.state === 'checking') setUpdateMessage('Checking for updates…'); else if (st.state === 'error') { updateCheckManual.current = false; setUpdateMessage(st.error || 'update failed'); } else if (st.available) { updateCheckManual.current = false; setUpdateMessage(`Kotassium ${st.latest || 'A Kotassium update'} is available (${updateStepsText(st.version, st.latest)})${st.can_install === false ? ' — move it to Applications to update' : ''}`); } else if (!st.error) { updateCheckManual.current = false; setUpdateMessage(`Kotassium ${st.version || ''} is up to date`); updateStatusTimer.current = setTimeout(() => setUpdateMessage(''), 4000); } } catch { updateCheckManual.current = false; toast('could not check for updates'); } finally { setUpdateBusy(false); } }, [toast]);
  const startUpdate = useCallback(async () => { setUpdateBusy(true); try { await postJSON('/api/update', {}); const st = await pollUpdate(); if (st?.state === 'installing' || st?.state === 'downloading') setUpdateMessage(st.state === 'downloading' ? `downloading update ${Math.round(st.pct || 0)}%` : 'installing update…'); } catch { toast('could not start the update'); } finally { setUpdateBusy(false); } }, [pollUpdate, toast]);

  const imageStyle = (url, name) => ({ background: url ? resolveCover(url) : gradient(name) });
  const coverBackground = (url, name) => url ? (coverMap[url] ? `url("/cover/${encodeURIComponent(coverMap[url])}") center/cover no-repeat` : escStyle(url)) : gradient(name);
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

  const trackRows = (tracks, mode) => tracks.map((track, i) => {
    const active = queue[currentIndex] && trackKey(queue[currentIndex]) === trackKey(track) && (mode === 'search' || playingPlaylist === view.name);
    return <div className={`${mode === 'search' ? 'srow' : 'row'}${active ? ' playing' : ''}`} key={`${trackKey(track)}-${i}`} onClick={() => mode === 'search' ? playIndex(i, tracks, '') : playIndex(i, tracks, view.name)}>
      {mode === 'search' ? <><button className="rbtn" data-tooltip="Play"><Icon name="play" size={15}/></button><div className="rtxt" style={{ flex: 1 }}><b>{track.t}</b><small>{track.a}</small></div><span className="stag">{track.source}</span>{track.full === false ? <span className="stream-only">stream only</span> : <span/>}<span/><span/></> : <><div><span className="trnum">{active ? <span className="bars"><i/><i/><i/><i/></span> : i + 1}</span></div><div className="rt"><div className="track-cover" style={{ background: coverBackground(track.cover, track.album || track.t) }} onMouseEnter={() => warmCover(track.cover)}></div><div className="rtxt"><b>{track.t}</b><small>{track.a}</small></div></div><div className="ralb">{track.album || ''}</div><div className="rdura">{fmt(track.ms)}</div></>}
    </div>;
  });

  const renderMain = () => {
    if (view.type === 'playlist')    return <><div id="plhead" style={{ background: `linear-gradient(180deg,hsl(${hue(view.name)},65%,30%),hsl(${(hue(view.name) + 40) % 360},60%,22%) 60%,#12121200)` }}><div id="plx" style={imageStyle(null, view.name)}>{(view.name || '?').charAt(0)}</div><div className="plinfo"><small>Public Playlist</small><h1>{view.name}</h1><p>{playlist.length} song{playlist.length === 1 ? '' : 's'}</p></div></div><div id="plactions" className={plStuck ? 'stuck' : ''}><button id="bigplay" onClick={playList} data-tooltip="Play"><Icon name="play" size={28}/></button><b className="plstick">{view.name}</b><button id="shuf2" className={`aicon ${shuffle ? 'on' : ''}`} onClick={toggleShuffle} data-tooltip="Shuffle"><Icon name="shuffle" size={20}/></button><button id="rb2" className={`aicon ${repeat ? 'on' : ''}`} onClick={toggleRepeat} data-tooltip="Repeat"><Icon name="repeat" size={24}/></button></div><div id="tbl"><div className="tr-head"><span>#</span><span>Title</span><span>Album</span><span style={{ textAlign: 'right', color: '#b3b3b3' }}>Duration</span></div>{trackRows(playlist, 'playlist')}</div></>;
    if (view.type === 'search') return <div id="search-results">{searching ? <div id="homeView"><h2>Searching “{view.query}”…</h2></div> : <><div id="homeView"><h2>Results for “{view.query}”</h2></div><div id="tbl" style={{ paddingTop: 0 }}>{results.length ? <><div className="tr-head"><span></span><span>Title</span><span>Source</span><span></span></div>{trackRows(results, 'search')}</> : <div id="empty">No results from any source.</div>}</div></>}</div>;
    return <div id="homeView"><h2>Your playlists</h2>{links.length ? <div className="cardgrid">{links.map((p, i) => <article className="card" key={p.url || p.name} onClick={() => loadPlaylist(i)}><div className="ccover" style={{ background: coverBackground(p.cover || p.tracks?.[0]?.cover, p.name) }} onMouseEnter={() => warmCover(p.cover || p.tracks?.[0]?.cover)}><button id="cardPlay" className="card-play" data-tooltip={`Play ${p.name}`} onClick={(e) => { e.stopPropagation(); loadPlaylist(i, true); }}><Icon name="play" size={20}/></button></div><b>{p.name || '?'}</b><small>{p.total || p.count} songs</small></article>)}</div> : <div id="empty">No playlists yet - add one with the + button.</div>}</div>;
  };

  const repeatButton = (fullscreen = false) => <button id={fullscreen ? 'fsRepeat' : 'repeatb'} className={`aicon ${repeat ? 'on' : ''}`} onClick={toggleRepeat} data-tooltip={`Repeat ${repeat === 0 ? 'off' : repeat === 1 ? 'all' : 'one'}`} aria-label={`Repeat ${repeat === 0 ? 'off' : repeat === 1 ? 'all' : 'one'}`}>{repeat === 2 ? <Repeat1 size={fullscreen ? 24 : 18} strokeWidth={2}/> : <Repeat size={fullscreen ? 24 : 18} strokeWidth={2}/>}</button>;
  const controls = (fullscreen = false) => <div className={fullscreen ? 'fs-controls' : ''} id={fullscreen ? 'fsBtns' : 'btns'}><button id={fullscreen ? 'fsShuf' : 'shufb'} className={`aicon ${shuffle ? 'on' : ''}`} onClick={toggleShuffle} data-tooltip="Shuffle"><Icon name="shuffle" size={fullscreen ? 24 : 20}/></button><button id={fullscreen ? 'fsprev' : 'prevb'} className="aicon" onClick={previous} disabled={!currentTrack || (currentIndex <= 0 && !(repeat === 1 && queue.length > 1))} data-tooltip="Previous"><Icon name="prev" size={fullscreen ? 24 : 20}/></button><button id={fullscreen ? 'fsPlay' : 'playb'} className={fullscreen ? 'fs-play' : ''} onClick={togglePlay} disabled={!currentTrack} data-tooltip={paused ? 'Play' : 'Pause'}><Icon name={paused ? 'play' : 'pause'} size={fullscreen ? 26 : 16}/></button><button id={fullscreen ? 'fsnext' : 'nextb'} className="aicon" onClick={next} data-tooltip="Next" disabled={!currentTrack || (nextIndex < 0 && !radio)}><Icon name="next" size={fullscreen ? 24 : 20}/></button>{repeatButton(fullscreen)}</div>;
  const volumeRow = (full = false) => <div id={full ? 'fsVol' : undefined} className={full ? 'fs-volume' : 'volume-row'}><button className="aicon" onClick={toggleVolume} data-tooltip="Volume"><span id={full ? 'volIcon2' : 'volIcon'}>{icon('volume', full ? 24 : 20)}</span></button><div className={full ? 'fs-volume-bar' : ''} id={full ? 'fsVolBar' : 'vol'} {...volumeHandlers()}><i id={full ? 'fsVolFill' : 'volf'} style={{ width: `${(muted ? 0 : Math.sqrt(volume)) * 100}%` }} /></div></div>;
  const progress = (full = false) => <div className={full ? 'fs-seek' : ''} id={full ? 'fsSeek' : 'prow'}><span className="ptime" id={full ? 'fsCur' : 'curt'}>{secs(currentTime)}</span><div className={full ? 'fs-progress' : ''} id={full ? 'fsProg' : 'prog'} {...seekHandlers()}><i id={full ? 'fsProgf' : 'progf'} style={{ width: `${duration ? Math.min(100, currentTime / duration * 100) : 0}%` }} /></div><span className="ptime" id={full ? 'fsTot' : 'tott'}>{secs(duration)}</span></div>;

  return <>
    <header id="top"><button id="libBtn" className="top-lib" onClick={toggleSide} data-tooltip={collapsed ? 'Expand library' : 'Collapse library'}><Icon name="library" size={18}/></button><button id="homeBtn" onClick={goHome} data-tooltip="Home"><Icon name="home"/></button><div id="searchwrap" className={query ? 'filled' : ''}><Icon name="search" size={18}/><input id="q" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} placeholder="What do you want to play?"/><button id="qClear" onClick={() => { setQuery(''); document.querySelector('#q')?.focus(); }} data-tooltip="Clear search"><Icon name="close" size={14}/></button><span id="qDiv"/><button id="qBrowse" onClick={goHome} data-tooltip="Browse playlists"><Icon name="browse"/></button></div><button id="settingsBtn" onClick={() => setSettingsOpen(true)} data-tooltip="Settings" aria-label="Open settings"><Settings2 size={21} strokeWidth={1.8} aria-hidden="true"/></button>{updateState?.supported && <div id="upd" className={`${updateMessage ? 'on' : 'on icononly'}`}><span id="updtext">{updateMessage || (updateState.available ? `Kotassium ${updateState.latest} is available (${updateStepsText(updateState.version, updateState.latest)})${updateState.can_install === false ? ' — move it to Applications to update' : ''}` : '')}</span>{updateState.rollback_available && <button id="rollbackBtn" onClick={async () => { if (!window.confirm('Restore the previous Kotassium version? The app will close and reopen.')) return; try { await postJSON('/api/update/rollback', {}); } catch { toast('could not start rollback'); } }} data-tooltip="Restore previous version" aria-label="Restore previous version"><RotateCw size={14}/></button>}<button id="updbtn" className={updateState.available ? 'go' : ''} onClick={updateState.available ? startUpdate : checkUpdate} disabled={updateBusy} data-tooltip={updateState.available ? 'Restart & Update' : 'Check for updates'} aria-label={updateState.available ? 'Restart and install update' : 'Check for updates'}>{updateState.available ? <Download size={16} strokeWidth={2.2} aria-hidden="true"/> : <RefreshCw size={15} strokeWidth={2} className={updateBusy ? 'lucide-spin' : ''} aria-hidden="true"/>}</button>{updateState.available && <button id="updcheck" onClick={checkUpdate} disabled={updateBusy} data-tooltip="Check again" aria-label="Check for updates again"><RotateCw size={15} strokeWidth={1.9} aria-hidden="true"/></button>}</div>}</header>
    {settingsOpen && <div className="settings-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setSettingsOpen(false); }}>
      <section className="settings-dialog" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
        <header className="settings-head">
          <h2 id="settingsTitle">Settings</h2>
          <button className="settings-close" onClick={() => setSettingsOpen(false)} aria-label="Close settings"><Icon name="close" size={18}/></button>
        </header>
        <div className="settings-content">
          <section className="settings-group">
            <h3 className="settings-label">Playback</h3>
            <div className="settings-card">
              <div className="setting-row"><div className="setting-copy"><b>Output level</b></div><div className="setting-volume"><input aria-label="Output level" type="range" min="0" max="100" value={Math.round((muted ? 0 : Math.sqrt(volume)) * 100)} style={{ '--range-progress': `${(muted ? 0 : Math.sqrt(volume)) * 100}%` }} onChange={(event) => setVolumePercent(event.target.value)}/><span>{Math.round((muted ? 0 : Math.sqrt(volume)) * 100)}%</span></div></div>
              <div className="setting-row"><div className="setting-copy"><b>Shuffle</b><small>Start playlists in a random order</small></div><button className={`setting-switch ${shuffle ? 'enabled' : ''}`} role="switch" aria-checked={shuffle} aria-label="Shuffle playback" onClick={toggleShuffle}><i/></button></div>
              <div className="setting-row"><div className="setting-copy"><b>Repeat</b><small>What happens at the end of a queue</small></div><div className="setting-seg" role="radiogroup" aria-label="Repeat mode">{[['Off', 0], ['Queue', 1], ['One', 2]].map(([label, value]) => <button key={value} type="button" role="radio" aria-checked={repeat === value} className={repeat === value ? 'on' : ''} onClick={() => { setRepeat(value); try { localStorage.setItem('kot_repeat', String(value)); } catch {} }}>{label}</button>)}</div></div>
            </div>
          </section>
          <section className="settings-group">
            <h3 className="settings-label">Workspace</h3>
            <div className="settings-card">
              <div className="setting-row"><div className="setting-copy"><b>Compact library</b><small>Show playlist covers only in the sidebar</small></div><button className={`setting-switch ${collapsed ? 'enabled' : ''}`} role="switch" aria-checked={collapsed} aria-label="Compact library" onClick={() => setCollapsed((value) => { const next = !value; try { localStorage.setItem('kot_side_collapsed', next ? '1' : '0'); } catch {} return next; })}><i/></button></div>
            </div>
          </section>
        </div>
        <footer className="settings-foot"><button onClick={() => setSettingsOpen(false)}>Done</button></footer>
      </section>
    </div>}
    {linkOpen && <div className="link-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setLinkOpen(false); }}>
      <section className="link-dialog" role="dialog" aria-modal="true" aria-labelledby="linkTitle" aria-describedby="linkDescription">
        <header className="link-dialog-head"><span className="link-dialog-mark"><Icon name="add" size={19}/></span><button className="settings-close" onClick={() => setLinkOpen(false)} disabled={busy} aria-label="Close add link dialog"><Icon name="close" size={18}/></button></header>
        <div className="link-dialog-copy"><span className="link-eyebrow">Your library <i/> New link</span><h2 id="linkTitle">Add to your library</h2><p id="linkDescription">Bring in a Spotify playlist, album, or track. Paste its link below and we’ll get it ready to play.</p></div>
        <form className="link-form" onSubmit={(event) => { event.preventDefault(); if (!busy) addLink(); }}><label htmlFor="plink">Spotify link</label><div className="link-input-wrap"><input id="plink" type="url" value={linkValue} onChange={(event) => setLinkValue(event.target.value)} placeholder="https://open.spotify.com/…" autoComplete="url" required disabled={busy}/><span className="link-input-icon"><Icon name="browse" size={17}/></span></div><small className="link-hint">Playlist, album, or track links are all welcome.</small><label className="link-opt" htmlFor="bgdl"><input id="bgdl" type="checkbox" checked={bgDownload} onChange={(event) => setBgDownload(event.target.checked)} disabled={busy}/><span><b>Download every track</b><small>Queues the whole playlist in the background - one at a time, behind anything you play.</small></span></label><button className="link-submit" type="submit" disabled={busy || !linkValue.trim()}>{busy ? <><i className="link-spinner"/>Adding to library…</> : <>Add link <span>↗</span></>}</button></form>
      </section>
    </div>}
    <div id="mid" className={sideDragWidth !== null ? 'resizing' : ''}><aside id="side" className={`${(sideResizePreview !== null ? sideResizePreview : collapsed) ? 'collapsed' : ''} ${drawerOpen ? 'open' : ''}`} onTouchStart={(e) => gestureStart(e, 'side')} onTouchMove={(e) => gestureMove(e, 'side')} onTouchEnd={(e) => gestureEnd(e, 'side')} onTouchCancel={(e) => gestureEnd(e, 'side')} onClickCapture={suppressGestureClick}><div id="sideHead"><button id="libToggle" onClick={toggleSide} data-tooltip={collapsed ? 'Expand library' : 'Collapse library'} aria-label={collapsed ? 'Expand library' : 'Collapse library'}><Icon name="library" size={18}/><b>Your Library</b></button><button id="addBtn" onClick={addLibraryLink} data-tooltip="Add Spotify link" aria-label="Add Spotify link"><Icon name="add" size={17}/></button></div><div id="sideList">{links.length ? links.map((p, i) => <div className={`pitem ${view.type === 'playlist' && view.name === p.name ? 'active' : ''}`} key={p.url || p.name} data-tooltip={p.name} onClick={() => loadPlaylist(i)}><div className="pcover" data-tooltip={p.name || '?'} style={{ background: coverBackground(p.cover || p.tracks?.[0]?.cover, p.name) }} onMouseEnter={() => warmCover(p.cover || p.tracks?.[0]?.cover)} onClick={(e) => { e.stopPropagation(); loadPlaylist(i, true); }}><button className="pcoverPlay" data-tooltip={`Play ${p.name}`} onClick={(e) => { e.stopPropagation(); loadPlaylist(i, true); }}><Icon name="play" size={18}/></button></div><div className="pmeta"><b>{p.name || '?'}</b><small>{typeof p.total === 'number' && p.total > p.count ? `${p.count} of ${p.total} songs` : `${p.count} songs${p.partial ? ' (partial)' : ''}`}</small></div></div>) : <div id="empty"><h3>Your library is empty</h3><p>Click + above and paste a Spotify link.</p></div>}</div></aside><div id="sideResize" role="separator" aria-label="Resize library" aria-orientation="vertical" aria-valuemin={68} aria-valuemax={262} aria-valuenow={sideDragWidth ?? (collapsed ? 68 : 262)} tabIndex={0} onPointerDown={startSidebarResize} onPointerMove={moveSidebarResize} onPointerUp={finishSidebarResize} onPointerCancel={finishSidebarResize} onKeyDown={keySidebarResize}/><main id="main">{renderMain()}</main></div>
    <footer id="bar" onTouchStart={(e) => gestureStart(e, 'bar')} onTouchMove={(e) => gestureMove(e, 'bar')} onTouchEnd={(e) => gestureEnd(e, 'bar')} onTouchCancel={(e) => gestureEnd(e, 'bar')} onClickCapture={suppressGestureClick}><div className="barfull" style={{ display: 'contents' }}><div id="nowp"><button id="nowc" onClick={mobileOpen} data-tooltip="Open player" style={{ background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t) : '#282828' }} onMouseEnter={() => warmCover(currentTrack?.cover)} /><div id="nowt"><b>{currentTrack?.t || 'Choose a playlist to listen'}</b><small>{currentTrack?.a || 'nothing playing'}</small></div></div><div id="ctr">{controls()}{progress()}</div><div id="rside">{volumeRow()}<button id="dfsBtn" disabled={!currentTrack} className="aicon desktop-fullscreen" onClick={toggleDesktop} data-tooltip={desktopPlayer ? 'Exit full screen' : 'Full screen'} aria-label={desktopPlayer ? 'Exit full screen' : 'Full screen'}><Icon name={desktopPlayer ? 'exitFullscreen' : 'fullscreen'}/></button></div></div></footer>
    <div id="fs" className={mobilePlayer ? 'on' : ''} onTouchStart={(e) => gestureStart(e, 'fs')} onTouchMove={(e) => gestureMove(e, 'fs')} onTouchEnd={(e) => gestureEnd(e, 'fs')} onTouchCancel={(e) => gestureEnd(e, 'fs')} onClickCapture={suppressGestureClick}><div id="fsGrip" onClick={mobileClose}/><div id="fsHead"><span id="fsPl">{playingPlaylist || 'Now playing'}</span></div><div id="fsArt" style={{ background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t) : '#282828' }} onMouseEnter={() => warmCover(currentTrack?.cover)}/><div id="fsTxt"><b>{currentTrack?.t || 'Choose a playlist to listen'}</b><small>{currentTrack?.a || 'nothing playing'}</small></div><div id="fsQueue" style={{ display: upcoming.length ? '' : 'none' }}><div id="fsQhead"><b>Up next</b><span id="fsQcount">{upcoming.length} {upcoming.length === 1 ? 'track' : 'tracks'}</span></div><div id="fsQrows">{upcoming.map((i, n) => <div className="fsQrow" key={`${trackKey(queue[i])}-${i}`} onClick={() => playIndex(i)}><span className="fsQn">{n + 1}</span><span className="fsQcov" style={{ background: coverBackground(queue[i]?.cover, queue[i]?.t) }}/><span className="fsQt"><b>{queue[i]?.t}</b><small>{queue[i]?.a}</small></span><span className="fsQtime">{fmt(queue[i]?.ms)}</span></div>)}</div></div><div id="fsIsland">{progress(true)}{controls(true)}{volumeRow(true)}</div></div>
    {desktopPlayer && <div id="dfs" className={`open ${desktopIdle ? 'idle' : ''}`} onMouseMove={() => setDesktopIdle(false)}><div id="dfsMain"><div id="dfsTop"><span id="dfsTopTitle">{playingPlaylist || 'Now playing'}</span><button id="dfsExit" onClick={() => setDesktopPlayer(false)} data-tooltip="Exit full screen"><Icon name="exitFullscreen" size={18}/></button></div><div id="dfsArt" style={{ background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t) : '#282828' }}/><div id="dfsInfo"><b id="dfsTitle">{currentTrack?.t || 'Choose a playlist to listen'}</b><small id="dfsArtist">{currentTrack?.a || 'nothing playing'}</small></div></div><div id="dfsQueue" style={{ display: queue.length ? '' : 'none' }}><div id="dfsQhead"><b>Queue</b><span id="dfsQcount">{queue.length} {queue.length === 1 ? 'track' : 'tracks'}</span></div><div id="dfsQrows">{currentTrack ? <><div className="dfsQsect">Now Playing</div><QueueRow track={currentTrack} active onClick={() => playIndex(currentIndex)} />{upcoming.length > 0 && <div className="dfsQsect">Next Up</div>}{upcoming.map((i) => <QueueRow key={`${trackKey(queue[i])}-${i}`} track={queue[i]} onClick={() => playIndex(i)}/>)}</> : queue.map((track, index) => <QueueRow key={`${trackKey(track)}-${index}`} track={track} onClick={() => playIndex(index)}/>)}</div></div></div>}
    <div id="toast" className={toastText && !toastDismissed ? 'visible' : ''} onPointerDown={toastPointerStart} onPointerMove={toastPointerMove} onPointerUp={toastPointerEnd} onPointerCancel={toastPointerEnd}>{toastText}</div>{(upNext || (radio && !nextTrack && currentTrack)) && currentTrack && !desktopPlayer && <div id="upnext" className={`tcard ${(upNext || (radio && !nextTrack)) && !upNextDismissed ? 'visible' : ''}`} onPointerDown={toastPointerStart} onPointerMove={toastPointerMove} onPointerUp={toastPointerEnd} onPointerCancel={toastPointerEnd}><span className="upnext-label">Up next</span><span className="upnext-art" style={{ background: coverBackground(displayNextTrack?.cover, displayNextTrack?.t) }}/><span className="upnext-copy"><b>{radioSearching ? 'Finding radio tracks…' : displayNextTrack?.t}</b><small>{radioSearching ? 'Radio' : displayNextTrack?.a}</small></span></div>}{download && <div id="dl" className="on"><span id="dllabel">{download.status === 'done' ? 'ready' : 'downloading'} {download.label}</span><div id="dlbar"><i id="dlfill" style={{ width: `${download.pct}%` }}/></div><span id="dlpct">{Math.round(download.pct)}%</span></div>}<audio ref={audioRef} preload="auto" />

  </>;
}

function QueueRow({ track, active = false, onClick }) { return <div className={`dfsQrow ${active ? 'cur' : ''}`} onClick={onClick}><span className="dfsQcov" style={{ background: track?.cover ? escStyle(track.cover) : gradient(track?.t) }}/><span className="dfsQt"><b>{track?.t}</b><small>{track?.a}</small></span></div>; }

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
