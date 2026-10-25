import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';

const API = (path) => fetch(path).then((r) => r.json());
const postJSON = (path, data) => fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then((r) => r.json());
const trackKey = (t) => `${t?.t || ''}|${t?.a || ''}`;
const fmt = (ms) => { const n = Math.round((Number(ms) || 0) / 1000); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')}`; };
const secs = (s) => `${Math.floor((Number(s) || 0) / 60)}:${String(Math.round(s || 0) % 60).padStart(2, '0')}`;
const hue = (name) => { let h = 0; for (const c of String(name || '?')) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h % 360; };
const gradient = (name) => { const h = hue(name); return `linear-gradient(135deg,hsl(${h},70%,38%),hsl(${(h + 40) % 360},60%,20%))`; };
const escStyle = (url) => `url("${String(url || '').replace(/["'<>)]/g, (c) => encodeURIComponent(c))}") center/cover no-repeat`;
function Icon({ name, size = 20, children }) {
  const p = {
    library: <><path d="M3 3h2.5v18H3zM7 3h2.5v18H7zM11 3.6L21.6 5v14L11 20.4z" fill="currentColor" stroke="none" /></>,
    home: <path d="M12 3l9 8h-2.5v9h-5v-6h-3v6h-5v-9H3z" fill="currentColor" stroke="none" />,
    search: <><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></>,
    close: <><path d="m5 5 14 14M19 5 5 19"/></>,
    browse: <path d="M3 4.5h13v2H3zM3 8.25h13v2H3zM3 12h18v7.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19.5z" fill="currentColor" stroke="none" />,
    add: <path d="M8 1.5a.75.75 0 0 1 1.5 0v5h5a.75.75 0 0 1 0 1.5h-5v5a.75.75 0 0 1-1.5 0V8H3a.75.75 0 0 1 0-1.5h5v-5z" fill="currentColor" stroke="none" />,
    play: <path d="M4 2.5 14 8 4 13.5z" fill="currentColor" stroke="none" />,
    pause: <path d="M5 3h2.5v10H5zM10 3h2.5v10H10z" fill="currentColor" stroke="none" />,
    prev: <path d="M3.3 1a.7.7 0 0 1 .7.7v5.15l9.95-5.744a.7.7 0 0 1 1.05.606v12.575a.7.7 0 0 1-1.05.607L4 9.149V14.3a.7.7 0 0 1-.7.7H1.7a.7.7 0 0 1-.7-.7V1.7a.7.7 0 0 1 .7-.7z" fill="currentColor" stroke="none" />,
    next: <path d="M12.7 1a.7.7 0 0 0-.7.7v5.15L2.05 1.107A.7.7 0 0 0 1 1.712v12.575a.7.7 0 0 0 1.05.607L12 9.149V14.3a.7.7 0 0 0 .7.7h1.6a.7.7 0 0 0 .7-.7V1.7a.7.7 0 0 0-.7-.7z" fill="currentColor" stroke="none" />,
    shuffle: <><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></>,
    repeat: <><path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/></>,
    volume: <><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></>,
    fullscreen: <><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children || p[name]}</svg>;
}

function App() {
  const audioRef = useRef(null);
  const cacheRef = useRef(null);
  if (!cacheRef.current) {
    try { cacheRef.current = JSON.parse(localStorage.getItem('kot_ytcache') || '{}'); } catch { cacheRef.current = {}; }
  }
  const coverCacheRef = useRef({});
  const jobsRef = useRef(new Map());
  const prefetchRef = useRef(new Set());
  const prefetchJobsRef = useRef(new Map());
  const requestRef = useRef(0);
  const playbackEpoch = useRef(0);
  const lastNowPlaying = useRef({ key: '', at: 0, duration: 0 });
  const warmedPlaylists = useRef(new Map());
  const [links, setLinks] = useState([]);
  const [view, setView] = useState({ type: 'home' });
  const [playlist, setPlaylist] = useState([]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [queue, setQueue] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [playingPlaylist, setPlayingPlaylist] = useState('');
  const [radio, setRadio] = useState(false);
  const [collapsedPlayer, setCollapsedPlayer] = useState(false);
  const [volumeBeforeMute, setVolumeBeforeMute] = useState(1);
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
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkValue, setLinkValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [toastText, setToastText] = useState('');
  const [upNext, setUpNext] = useState(false);
  const [toastDismissed, setToastDismissed] = useState(false);
  const [download, setDownload] = useState(null);
  const [mobilePlayer, setMobilePlayer] = useState(false);
  const [desktopPlayer, setDesktopPlayer] = useState(false);
  const [desktopIdle, setDesktopIdle] = useState(false);
  const [coverMap, setCoverMap] = useState({});
  const [updateState, setUpdateState] = useState(null);
  const [updateMessage, setUpdateMessage] = useState('');
  const [updateBusy, setUpdateBusy] = useState(false);
  const toastTimer = useRef(0);
  const toastGesture = useRef({ active: false, startX: 0, startY: 0, deltaX: 0, dismissed: false, previousOpacity: '' });
  const dragStart = useRef(null);
  const currentTrack = currentIndex >= 0 ? queue[currentIndex] : null;
  const duration = actualDuration || (currentTrack?.ms ? currentTrack.ms / 1000 : 0);

  const toast = useCallback((message) => {
    toastGesture.current.dismissed = false;
    setToastDismissed(false);
    setToastText(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToastText(''), 3000);
  }, []);
  const toastTouchStart = (event) => {
    const touch = event.touches[0];
    toastGesture.current = { ...toastGesture.current, active: true, startX: touch.clientX, startY: touch.clientY, deltaX: 0, previousOpacity: '1' };
    clearTimeout(toastTimer.current);
  };
  const toastTouchMove = (event) => {
    const gesture = toastGesture.current;
    if (!gesture.active) return;
    const touch = event.touches[0];
    const dx = touch.clientX - gesture.startX, dy = touch.clientY - gesture.startY;
    if (dx <= 0 || Math.abs(dx) <= Math.abs(dy)) return;
    event.preventDefault();
    gesture.deltaX = dx;
    event.currentTarget.style.transition = 'none';
    event.currentTarget.style.transform = `translateX(${dx}px)`;
    event.currentTarget.style.opacity = String(Math.max(0, 1 - dx / 140));
  };
  const toastTouchEnd = (event) => {
    const gesture = toastGesture.current;
    if (!gesture.active) return;
    gesture.active = false;
    const node = event.currentTarget;
    node.style.transition = 'transform .25s cubic-bezier(.2,.8,.2,1),opacity .25s';
    if (gesture.deltaX > 70) {
      gesture.dismissed = true;
      node.style.transform = 'translateX(150%)';
      node.style.opacity = '0';
      setTimeout(() => { node.style.transform = ''; node.style.transition = ''; setToastDismissed(true); }, 250);
    } else {
      node.style.transform = '';
      node.style.opacity = gesture.previousOpacity;
      toastTimer.current = setTimeout(() => setToastText(''), 3000);
    }
  };
  const resolveCover = useCallback((url) => {
    if (!url) return '';
    return coverMap[url] ? escStyle(`/cover/${coverMap[url]}`) : escStyle(url);
  }, [coverMap]);
  const warmCover = useCallback((url) => {
    if (!url || url.startsWith('/cover/') || coverCacheRef.current[url]) return;
    coverCacheRef.current[url] = 'pending';
    fetch(url, { mode: 'cors' }).then((r) => { if (!r.ok) throw new Error('cover fetch failed'); return r.blob(); })
      .then((blob) => new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = reject; reader.readAsDataURL(blob); }))
      .then((data) => postJSON('/api/cover/cache', { url, data }).then((j) => { if (j?.file) { coverCacheRef.current[url] = j.file; setCoverMap((m) => ({ ...m, [url]: j.file })); } }))
      .catch(() => { coverCacheRef.current[url] = null; });
  }, []);

  const loadLinks = useCallback(() => API('/api/links').then((j) => { const rows = j.links || []; setLinks(rows); return rows; }), []);
  const startQueueRef = useRef(null);
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
    if (shuf && q.length > 1) {
      if (pos < order.length) return order[pos];
      return -1;
    }
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

  const playTrackRef = useRef(null);
  const findCandidates = useCallback(async (track) => {
    const q = `${track.a ? `${track.a} ` : ''}${track.t || ''}`;
    const response = await API(`/api/search?src=youtube&q=${encodeURIComponent(q)}`);
    const target = (Number(track.ms) || 0) / 1000;
    const videos = (response.results || []).filter((r) => r.source === 'youtube').map((r, i) => ({ ...r, _order: i, _delta: target && r.dur ? Math.abs(r.dur - target) : Infinity }))
      .sort((a, b) => a._delta - b._delta || a._order - b._order).slice(0, 8);
    if (videos.length) return videos;
    if (track.source === 'newgrounds' && track.id) return [{ ...track, source: 'newgrounds' }];
    const ng = await API(`/api/search?src=newgrounds&q=${encodeURIComponent(q)}&t=${encodeURIComponent(track.t || '')}&a=${encodeURIComponent(track.a || '')}`);
    return (ng.results || []).filter((r) => r.source === 'newgrounds').slice(0, 6);
  }, []);

  const startResolvedTrack = useCallback(async (track, candidates, candidateIndex, cacheKey, cached = false, epoch = playbackEpoch.current) => {
    const audio = audioRef.current;
    if (!audio || !track || epoch !== playbackEpoch.current) return;
    const candidate = candidates[candidateIndex];
    if (!candidate) { toast(`Could not find a matching source for ${track.t || 'track'}`); return; }
    try {
      const result = await downloadId(candidate.id, track.t, false);
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
  }, [downloadId, toast]);

  const playTrack = useCallback(async (track) => {
    if (!track) return;
    const epoch = ++playbackEpoch.current;
    setCurrentTime(0); setActualDuration(0); setPaused(true);
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause(); audio.removeAttribute('src'); audio.load();
    if (track.source === 'youtube' || track.source === 'newgrounds' || !track.source || track.source === 'local') {
      const key = trackKey(track);
      const cached = cacheRef.current[key];
      try {
        let candidates;
        if (track.source === 'newgrounds' && track.id) candidates = [{ ...track, source: 'newgrounds' }];
        else if (track.source === 'youtube' && track.id) candidates = [{ ...track }];
        else candidates = await findCandidates(track);
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
  }, [findCandidates, startResolvedTrack, toast]);
  playTrackRef.current = playTrack;

  const startQueue = useCallback((tracks, name = '', index = 0) => {
    if (!tracks?.length || index < 0) return;
    const nextQueue = tracks.slice();
    const order = shuffle ? nextQueue.map((_, i) => i).filter((i) => i !== index).sort(() => Math.random() - 0.5) : [];
    setQueue(nextQueue); setPlayingPlaylist(name); setCurrentIndex(index); setShuffleOrder(order); setShufflePos(0);
    playTrack(nextQueue[index]);
  }, [shuffle, playTrack]);
  startQueueRef.current = startQueue;

  const playIndex = useCallback((i, sourceQueue = queue, name = playingPlaylist, advanceShuffle = false) => {
    if (!sourceQueue[i]) return;
    const order = shuffle ? sourceQueue.map((_, n) => n).filter((n) => n !== i).sort(() => Math.random() - 0.5) : [];
    setQueue(sourceQueue); setPlayingPlaylist(name); setCurrentIndex(i); setShuffleOrder(advanceShuffle ? shuffleOrder : order); setShufflePos(advanceShuffle ? shufflePos + 1 : 0);
    playTrack(sourceQueue[i]);
  }, [queue, playingPlaylist, shuffle, shuffleOrder, shufflePos, playTrack]);

  const playList = useCallback(async () => {
    if (!playlist.length) return;
    const link = links.find((item) => item.name === view.name);
    const key = link?.url || link?.name || '';
    const warmup = key && warmedPlaylists.current.get(key);
    const full = warmup ? await warmup : null;
    const choiceIndex = full?.choice ? playlist.findIndex((track) => trackKey(track) === trackKey(full.choice)) : -1;
    if (key && choiceIndex >= 0) {
      const warmed = prefetchJobsRef.current.get(trackKey(full.choice));
      if (warmed && await warmed === false) prefetchJobsRef.current.delete(trackKey(full.choice));
    }
    const index = choiceIndex >= 0 ? choiceIndex : (shuffle ? Math.floor(Math.random() * playlist.length) : 0);
    startQueue(playlist, view.name || '', index);
  }, [playlist, view, shuffle, startQueue, links]);

  const fetchRadio = useCallback(async () => {
    const seed = queue[currentIndex];
    if (!seed) return;
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
      setQueue(extendedQueue); setRadio(false); setCurrentIndex(first);
        setPlayingPlaylist(playingPlaylist);
        playTrack(fresh[0]);
      } else setRadio(false);
    } catch { toast('radio failed'); setRadio(false); }
  }, [queue, currentIndex, toast, playingPlaylist, shuffle, playTrack]);
  const next = useCallback(() => {
    if (!queue.length) return;
    let n = chooseNext();
    if (shuffle && repeat !== 2 && shufflePos < shuffleOrder.length) {
      playIndex(n, queue, playingPlaylist, true);
      return;
    }
    if (n >= 0 && (n !== currentIndex || !radio || repeat === 2)) { playIndex(n); return; }
    if (radio) fetchRadio();
  }, [queue, chooseNext, shuffle, repeat, shufflePos, shuffleOrder, playingPlaylist, playIndex, currentIndex, radio, fetchRadio]);

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
      setShuffleOrder(queue.map((_, i) => i).filter((i) => i !== currentIndex).sort(() => Math.random() - 0.5)); setShufflePos(0);
    } else { setShuffleOrder([]); setShufflePos(0); }
  }, [shuffle, queue, currentIndex]);
  const toggleRepeat = useCallback(() => setRepeat((r) => { const v = (r + 1) % 3; try { localStorage.setItem('kot_repeat', String(v)); } catch {} return v; }), []);
  const toggleRadio = useCallback(() => setRadio((value) => !value), []);
  const previous = useCallback(() => {
    if (currentTime > 3) { if (audioRef.current) audioRef.current.currentTime = 0; return; }
    if (currentIndex > 0) playIndex(currentIndex - 1);
    else if (repeat === 1 && queue.length > 1) playIndex(queue.length - 1);
  }, [currentTime, currentIndex, repeat, queue.length, playIndex]);
  const toggleVolume = useCallback(() => setMuted((wasMuted) => {
    if (!wasMuted) {
      setVolumeBeforeMute(volume);
      if (volume === 0) setVolume(1);
      return true;
    }
    if (volume === 0) setVolume(volumeBeforeMute || 1);
    return false;
  }), [volume, volumeBeforeMute]);
  const setVolumeAt = useCallback((element, event) => {
    const rect = element.getBoundingClientRect();
    const clientX = event.clientX;
    const value = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    setVolume(value * value); setVolumeBeforeMute(value * value); setMuted(false);
    try { localStorage.setItem('kot_vol', String(value)); } catch {}
  }, []);
  const seekAt = useCallback((element, event) => {
    if (!audioRef.current?.duration) return;
    const rect = element.getBoundingClientRect();
    audioRef.current.currentTime = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * audioRef.current.duration;
  }, []);

  const prefetchTrack = useCallback((track) => {
    if (!track || (track.source && track.source !== 'youtube' && track.source !== 'newgrounds')) return Promise.resolve();
    const key = trackKey(track);
    if (prefetchJobsRef.current.has(key)) return prefetchJobsRef.current.get(key);
    prefetchRef.current.add(key);
    const pending = (async () => {
      try {
        const candidates = track.id && track.source === 'youtube' ? [track] : await findCandidates(track);
        if (!candidates[0]?.id) { prefetchRef.current.delete(key); return; }
        cacheRef.current[key] = candidates[0].id;
        try { localStorage.setItem('kot_ytcache', JSON.stringify(cacheRef.current)); } catch {}
        await runDownload(candidates[0].id, track.t);
        return undefined;
      } catch {
        prefetchRef.current.delete(key);
        return false;
      }
    })();
    prefetchJobsRef.current.set(key, pending);
    return pending;
  }, [findCandidates, runDownload]);
  prefetchTrackRef.current = prefetchTrack;

  // The next-track identity is derived from the queue state, so changes to the
  // queue, current item, shuffle order, or repeat mode always reconsider it.
  const nextIndex = chooseNext();
  const nextTrack = nextIndex >= 0 && nextIndex !== currentIndex ? queue[nextIndex] : null;
  const displayNextTrack = nextTrack || (radio && currentIndex >= 0 ? queue[currentIndex] : null);
  useEffect(() => { if (nextTrack) prefetchTrack(nextTrack); }, [nextTrack, prefetchTrack]);
  useEffect(() => {
    if (shuffle && repeat === 1 && queue.length > 1 && currentIndex >= 0 && shufflePos >= shuffleOrder.length) {
      setShuffleOrder(queue.map((_, i) => i).filter((i) => i !== currentIndex).sort(() => Math.random() - 0.5));
      setShufflePos(0);
    }
  }, [shuffle, repeat, queue, currentIndex, shufflePos, shuffleOrder.length]);
  useEffect(() => {
    setUpNext(!!(duration && currentTime > 0 && duration - currentTime <= 30 && nextTrack));
  }, [duration, currentTime, nextTrack]);

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
    if (audioRef.current) audioRef.current.volume = muted ? 0 : volume;
  }, [volume, muted]);

  useEffect(() => {
    links.forEach((link) => {
      const key = link.url || link.name || '';
      if (!key || warmedPlaylists.current.has(key)) return;
      const warmup = API(`/api/links/get?url=${encodeURIComponent(link.url || '')}`).then((full) => {
        const tracks = (full?.tracks || []).filter((t) => t?.t);
        if (!tracks.length) return null;
        const choice = shuffle ? tracks[Math.floor(Math.random() * tracks.length)] : tracks[0];
        const result = { ...full, tracks, choice };
        warmedPlaylists.current.set(key, Promise.resolve(result));
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
    wake(); window.addEventListener('mousemove', wake); window.addEventListener('keydown', wake);
    window.addEventListener('pointerdown', wake); window.addEventListener('blur', blur);
    const escape = (event) => { if (event.key === 'Escape') setDesktopPlayer(false); };
    window.addEventListener('keydown', escape);
    return () => { clearTimeout(timer); window.removeEventListener('mousemove', wake); window.removeEventListener('keydown', wake); window.removeEventListener('pointerdown', wake); window.removeEventListener('blur', blur); window.removeEventListener('keydown', escape); };
  }, [desktopPlayer]);

  useEffect(() => {
    if (!updateState || !['checking', 'downloading', 'installing'].includes(updateState.state)) return;
    const timer = setTimeout(async () => {
      const st = await API('/api/update').catch(() => null);
      if (!st) return;
      setUpdateState(st);
      if (st.state === 'downloading') setUpdateMessage(`downloading update ${Math.round(st.pct || 0)}%`);
      else if (st.state === 'installing') setUpdateMessage('installing update…');
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
    const onEnded = () => { if (repeat === 2) { audio.currentTime = 0; audio.play(); } else next(); };
    const onError = () => { if (audio.currentSrc) toast('Audio source could not be played'); };
    audio.addEventListener('timeupdate', onTime); audio.addEventListener('play', onPlay); audio.addEventListener('pause', onPause);
    audio.addEventListener('loadedmetadata', onMeta); audio.addEventListener('ended', onEnded); audio.addEventListener('error', onError);
    return () => { audio.removeEventListener('timeupdate', onTime); audio.removeEventListener('play', onPlay); audio.removeEventListener('pause', onPause); audio.removeEventListener('loadedmetadata', onMeta); audio.removeEventListener('ended', onEnded); audio.removeEventListener('error', onError); };
  }, [queue, currentIndex, repeat, next, playTrack, startResolvedTrack]);

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

  const search = useCallback(async () => {
    const q = query.trim(); if (!q) return;
    setView({ type: 'search', query: q }); setResults([]);
    try { const j = await API(`/api/search?q=${encodeURIComponent(q)}`); setResults((j.results || []).map((t) => ({ t: t.title, a: t.artist, source: t.source, id: t.id, preview: t.preview, ms: (t.dur || 0) * 1000, cover: t.cover || '', album: '' }))); }
    catch { toast('Search failed'); }
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
      const ix = updated.findIndex((p) => p.url === url || p.name === j.name);
      if (ix >= 0) await loadPlaylist(ix, false, updated);
    } catch (error) { toast(`could not open: ${error.message || 'network error'}`); }
    finally { clearInterval(resolving); setBusy(false); }
  }, [linkValue, loadLinks, loadPlaylist, toast]);

  const goHome = useCallback(() => { setQuery(''); setView({ type: 'home' }); }, []);
  const togglePlayerBar = useCallback(() => setCollapsedPlayer((value) => !value), []);
  const toggleSide = useCallback(() => {
    if (window.matchMedia('(max-width:820px)').matches) setDrawerOpen((x) => !x);
    else setCollapsed((x) => { const v = !x; try { localStorage.setItem('kot_side_collapsed', v ? '1' : '0'); } catch {} return v; });
  }, []);
  const toggleDesktop = useCallback(() => { setDesktopPlayer((v) => !v); setDesktopIdle(false); }, []);
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
  const checkUpdate = useCallback(async () => { setUpdateBusy(true); try { const st = await postJSON('/api/update/check', {}); setUpdateState(st); if (st.state === 'checking') setUpdateMessage('Checking for updates…'); else if (st.available) setUpdateMessage(`Kotassium ${st.latest} is available (${updateSteps(st.version, st.latest)})`); else if (!st.error) setUpdateMessage(`Kotassium ${st.version || ''} is up to date`); } catch { toast('could not check for updates'); } finally { setUpdateBusy(false); } }, [toast, updateSteps]);
  const startUpdate = useCallback(async () => { setUpdateBusy(true); try { await postJSON('/api/update', {}); const st = await pollUpdate(); if (st?.state === 'installing' || st?.state === 'downloading') setUpdateMessage(st.state === 'downloading' ? `downloading update ${Math.round(st.pct || 0)}%` : 'installing update…'); } catch { toast('could not start the update'); } finally { setUpdateBusy(false); } }, [pollUpdate, toast]);

  const imageStyle = (url, name) => ({ background: url ? resolveCover(url) : gradient(name) });
  const coverBackground = (url, name) => url ? (coverMap[url] ? `url("/cover/${encodeURIComponent(coverMap[url])}") center/cover no-repeat` : escStyle(url)) : gradient(name);
  const volumeIcon = <><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>{muted || volume === 0 ? <><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></> : volume < 0.25 ? <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/> : <><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></>}</>;
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
    if (currentIndex < 0) return queue.map((_, i) => i);
    if (repeat === 2) return [];
    const out = [];
    if (shuffle && shuffleOrder.length) out.push(...shuffleOrder.slice(shufflePos));
    else for (let i = currentIndex + 1; i < queue.length; i++) out.push(i);
    if (repeat === 1 && !shuffle && currentIndex === queue.length - 1) for (let i = 0; i < currentIndex; i++) out.push(i);
    return [...new Set(out)].filter((i) => i !== currentIndex);
  }, [queue, currentIndex, shuffle, shuffleOrder, shufflePos, repeat]);

  const trackRows = (tracks, mode) => tracks.map((track, i) => {
    const active = queue[currentIndex] && trackKey(queue[currentIndex]) === trackKey(track) && (mode === 'search' || playingPlaylist === view.name);
    return <div className={`${mode === 'search' ? 'srow' : 'row'}${active ? ' playing' : ''}`} key={`${trackKey(track)}-${i}`} onClick={() => mode === 'search' ? playIndex(i, tracks, '') : playIndex(i, tracks, view.name)}>
      {mode === 'search' ? <><button className="rbtn" title="Play"><Icon name="play" size={15}/></button><div className="rtxt" style={{ flex: 1 }}><b>{track.t}</b><small>{track.a}</small></div><span className="stag">{track.source}</span>{track.source === 'deezer' && <span className="stream-only">preview</span>}</> : <><div><span className="trnum">{active ? '♫' : i + 1}</span></div><div className="rt"><div className="track-cover" style={{ background: coverBackground(track.cover, track.album || track.t) }} onMouseEnter={() => warmCover(track.cover)}></div><div className="rtxt"><b>{track.t}</b><small>{track.a}</small></div></div><div className="ralb">{track.album || ''}</div><div className="rdura">{fmt(track.ms)}</div></>}
    </div>;
  });

  const renderMain = () => {
    if (view.type === 'playlist')    return <><div id="plhead" style={{ background: `linear-gradient(180deg,hsl(${hue(view.name)},65%,30%),hsl(${(hue(view.name) + 40) % 360},60%,22%) 60%,#12121200)` }}><div id="plx" style={imageStyle(null, view.name)}>{(view.name || '?').charAt(0)}</div><div className="plinfo"><small>Public Playlist</small><h1>{view.name}</h1><p>{playlist.length} songs</p></div></div><div id="plactions"><button id="bigplay" onClick={playList} title="Play"><Icon name="play" size={28}/></button><button className={`aicon ${shuffle ? 'on' : ''}`} onClick={toggleShuffle} title="Shuffle"><Icon name="shuffle"/></button><button className={`aicon ${repeat ? 'on' : ''}`} onClick={toggleRepeat} title="Repeat"><Icon name="repeat" size={24}/>{repeat === 2 && <small className="repeat-one">1</small>}</button></div><div id="tbl"><div className="tr-head"><span>#</span><span>Title</span><span>Album</span><span>Duration</span></div>{trackRows(playlist, 'playlist')}</div></>;
    if (view.type === 'search') return <div id="search-results"><div id="homeView"><h2>Results for “{view.query}”</h2></div><div id="tbl"><div className="tr-head search-head"><span></span><span>Title</span><span>Source</span></div>{results.length ? trackRows(results, 'search') : <div id="empty">No results from any source.</div>}</div></div>;
    return <div id="homeView"><h2>Your playlists</h2>{links.length ? <div className="cardgrid">{links.map((p, i) => <article className="card" key={p.url || p.name} onClick={() => loadPlaylist(i)}><div className="ccover" style={{ background: coverBackground(p.cover, p.name) }} onMouseEnter={() => warmCover(p.cover)}><button id="cardPlay" className="card-play" title={`Play ${p.name}`} onClick={(e) => { e.stopPropagation(); loadPlaylist(i, true); }}><Icon name="play" size={20}/></button></div><b>{p.name || '?'}</b><small>{p.total || p.count} songs{p.partial ? ' (partial)' : ''}</small></article>)}</div> : <div id="empty">No playlists yet - add one with the + button.</div>}</div>;
  };

  const repeatButton = (fullscreen = false) => <button id={fullscreen ? 'fsRepeat' : 'repeatb'} className={`aicon ${repeat ? 'on' : ''}`} onClick={toggleRepeat} title={repeat === 2 ? 'Repeat one' : 'Repeat'}><Icon name="repeat" size={22}/>{repeat === 2 && <small className="repeat-one">1</small>}</button>;
  const controls = (fullscreen = false) => <div className={fullscreen ? 'fs-controls' : ''} id={fullscreen ? 'fsBtns' : 'btns'}><button id={fullscreen ? 'fsShuf' : 'shufb'} className={`aicon ${shuffle ? 'on' : ''}`} onClick={toggleShuffle} title="Shuffle"><Icon name="shuffle" size={19}/></button><button id={fullscreen ? 'fsprev' : 'prevb'} className="aicon" onClick={previous} disabled={!currentTrack || (currentIndex <= 0 && !(repeat === 1 && queue.length > 1))} title="Previous"><Icon name="prev" size={17}/></button><button id={fullscreen ? 'fsPlay' : 'playb'} className={fullscreen ? 'fs-play' : ''} onClick={togglePlay} disabled={!currentTrack} title={paused ? 'Play' : 'Pause'}><Icon name={paused ? 'play' : 'pause'} size={fullscreen ? 26 : 17}/></button><button id={fullscreen ? 'fsnext' : 'nextb'} className="aicon" onClick={next} title="Next" disabled={!currentTrack || (nextIndex < 0 && !radio)}><Icon name="next" size={17}/></button>{repeatButton(fullscreen)}{!fullscreen && <><button className={`aicon ${radio ? 'on' : ''}`} onClick={toggleRadio} title={radio ? 'Turn radio off' : 'Start radio'} aria-label="Radio"><Icon name="browse" size={18}/></button><button className="aicon" onClick={togglePlayerBar} title={collapsedPlayer ? 'Expand player' : 'Collapse player'} aria-label={collapsedPlayer ? 'Expand player' : 'Collapse player'}><Icon name={collapsedPlayer ? 'play' : 'next'} size={14}/></button></>}</div>;
  const volumeRow = (full = false) => <div id={full ? 'fsVol' : undefined} className={full ? 'fs-volume' : 'volume-row'}><button className="aicon" onClick={toggleVolume} title="Volume"><span id={full ? 'volIcon2' : 'volIcon'}>{icon('volume', full ? 23 : 19)}</span></button><div className={full ? 'fs-volume-bar' : ''} id={full ? 'fsVolBar' : 'vol'} {...volumeHandlers()}><i id={full ? 'fsVolFill' : 'volf'} style={{ width: `${(muted ? 0 : Math.sqrt(volume)) * 100}%` }} /></div></div>;
  const progress = (full = false) => <div className={full ? 'fs-seek' : ''} id={full ? 'fsSeek' : 'prow'}><span className="ptime" id={full ? 'fsCur' : 'curt'}>{secs(currentTime)}</span><div className={full ? 'fs-progress' : ''} id={full ? 'fsProg' : 'prog'} {...seekHandlers()}><i id={full ? 'fsProgf' : 'progf'} style={{ width: `${duration ? Math.min(100, currentTime / duration * 100) : 0}%` }} /></div><span className="ptime" id={full ? 'fsTot' : 'tott'}>{secs(duration)}</span></div>;

  return <>
    <header id="top"><button id="libBtn" className="top-lib" onClick={toggleSide} title={collapsed ? 'Expand library' : 'Collapse library'}><Icon name="library"/></button><button id="homeBtn" onClick={goHome} title="Home"><Icon name="home"/></button><div id="searchwrap" className={query ? 'filled' : ''}><Icon name="search" size={18}/><input id="q" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} placeholder="What do you want to play?"/><button id="qClear" onClick={() => { setQuery(''); document.querySelector('#q')?.focus(); }} title="Clear search"><Icon name="close" size={14}/></button><span id="qDiv"/><button id="qBrowse" onClick={goHome} title="Browse playlists"><Icon name="browse"/></button></div>{updateState?.supported && <div id="upd" className={`${updateMessage ? 'on' : 'on icononly'}`}><span id="updtext">{updateMessage || (updateState.available ? `Kotassium ${updateState.latest} is available (${updateSteps(updateState.version, updateState.latest)})${updateState.can_install === false ? ' — move it to Applications to update' : ''}` : '')}</span><button id="updbtn" className={updateState.available ? 'go' : ''} onClick={updateState.available ? startUpdate : checkUpdate} disabled={updateBusy} title={updateState.available ? 'Restart & Update' : 'Check for updates'}>{updateState.available ? '↓' : '⟳'}</button>{updateState.available && <button id="updcheck" onClick={checkUpdate} disabled={updateBusy} title="Check again">↻</button>}</div>}</header>
    <div id="mid"><aside id="side" className={`${collapsed ? 'collapsed' : ''} ${drawerOpen ? 'open' : ''}`}><div id="sideHead"><b><Icon name="library" size={18}/>Your Library</b><button id="addBtn" onClick={() => setLinkOpen((v) => !v)} title="Add Spotify link"><Icon name="add" size={17}/></button></div><div id="sideList">{links.length ? links.map((p, i) => <div className={`pitem ${view.type === 'playlist' && view.name === p.name ? 'active' : ''}`} key={p.url || p.name} title={p.name} onClick={() => loadPlaylist(i)}><div className="pcover" title={p.name || '?'} style={{ background: coverBackground(p.cover, p.name) }} onMouseEnter={() => warmCover(p.cover)}><button className="pcoverPlay" title={`Play ${p.name}`} onClick={(e) => { e.stopPropagation(); loadPlaylist(i, true); }}><Icon name="play" size={18}/></button></div><div className="pmeta"><b>{p.name || '?'}</b><small>{typeof p.total === 'number' && p.total > p.count ? `${p.count} of ${p.total} songs${p.partial ? ' (partial)' : ''}` : `${p.count} songs${p.partial ? ' (partial)' : ''}`}</small></div></div>) : <div id="empty"><h3>Your library is empty</h3><p>Click + above and paste a Spotify link.</p></div>}</div>{linkOpen && <div id="addBox"><input value={linkValue} onChange={(e) => setLinkValue(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && addLink()} placeholder="Paste a Spotify playlist, album or track link"/><button onClick={addLink} disabled={busy}>Add</button></div>}</aside><main id="main">{renderMain()}</main></div>
    <footer id="bar" className={collapsedPlayer ? 'collapsed' : ''} onTouchStart={(e) => { dragStart.current = e.touches[0].clientY; }} onTouchEnd={(e) => { if (dragStart.current - e.changedTouches[0].clientY > 45 && window.matchMedia('(max-width:820px)').matches) setMobilePlayer(true); dragStart.current = null; }}><div id="thumbstrip">{collapsedPlayer && <button className="collbtn" title="Expand player" onClick={togglePlayerBar}>⌃</button>}{collapsedPlayer && queue.map((track, index) => <button key={`${trackKey(track)}-${index}`} className={`thumb ${currentIndex === index ? 'cur' : ''}`} title={`${track.t} — ${track.a}`} onClick={() => playIndex(index)} style={imageStyle(track.cover, track.t)} />)}</div><div className="barfull" style={{ display: 'contents' }}><div id="nowp"><button id="nowc" onClick={() => setMobilePlayer(true)} title="Open player" style={{ background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t) : '#282828' }} onMouseEnter={() => warmCover(currentTrack?.cover)} /><div id="nowt"><b>{currentTrack?.t || 'Choose a playlist to listen'}</b><small>{currentTrack?.a || 'nothing playing'}</small></div></div><div id="ctr">{controls()}{progress()}</div><div id="rside">{volumeRow()}<button id="dfsBtn" disabled={!currentTrack} className="aicon desktop-fullscreen" onClick={toggleDesktop} title="Full screen"><Icon name="fullscreen"/></button></div></div></footer>
    <div id="fs" className={mobilePlayer ? 'on' : ''} onTouchStart={(e) => { dragStart.current = e.touches[0].clientY; }} onTouchEnd={(e) => { if (e.changedTouches[0].clientY - (dragStart.current || 0) > 80) setMobilePlayer(false); dragStart.current = null; }}><div id="fsGrip" onClick={() => setMobilePlayer(false)}/><div id="fsHead"><span id="fsPl">{playingPlaylist || 'Now playing'}</span></div><div id="fsArt" style={{ background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t) : '#282828' }} onMouseEnter={() => warmCover(currentTrack?.cover)}/><div id="fsTxt"><b>{currentTrack?.t || 'Choose a playlist to listen'}</b><small>{currentTrack?.a || 'nothing playing'}</small></div><div id="fsQueue"><div id="fsQhead"><b>Up next</b><span id="fsQcount">{upcoming.length} {upcoming.length === 1 ? 'track' : 'tracks'}</span></div>{upcoming.map((i, n) => <div className="fsQrow" key={`${trackKey(queue[i])}-${i}`} onClick={() => playIndex(i)}><span className="fsQn">{n + 1}</span><span className="fsQcov" style={{ background: coverBackground(queue[i]?.cover, queue[i]?.t) }}/><span className="fsQt"><b>{queue[i]?.t}</b><small>{queue[i]?.a}</small></span><span className="fsQtime">{fmt(queue[i]?.ms)}</span></div>)}</div><div id="fsIsland">{progress(true)}{controls(true)}{volumeRow(true)}</div></div>
    {desktopPlayer && <div id="dfs" className={`open ${desktopIdle ? 'idle' : ''}`} onMouseMove={() => setDesktopIdle(false)}><div id="dfsMain"><div id="dfsTop"><span id="dfsTopTitle">{playingPlaylist || 'Now playing'}</span><button id="dfsExit" onClick={() => setDesktopPlayer(false)} title="Exit full screen">×</button></div><div id="dfsArt" style={{ background: currentTrack ? coverBackground(currentTrack.cover, currentTrack.t) : '#282828' }}/><div id="dfsInfo"><b id="dfsTitle">{currentTrack?.t}</b><small id="dfsArtist">{currentTrack?.a}</small></div></div><div id="dfsQueue"><div id="dfsQhead"><b>Queue</b><span id="dfsQcount">{queue.length} tracks</span></div><div id="dfsQrows">{currentTrack && <div className="dfsQsect">Now playing</div>}{currentTrack && <QueueRow track={currentTrack} active onClick={() => playIndex(currentIndex)} />}{upcoming.map((i) => <QueueRow key={`${trackKey(queue[i])}-${i}`} track={queue[i]} onClick={() => playIndex(i)}/>)}</div></div></div>}
    <div id="toast" className={toastText && !toastDismissed ? 'visible' : ''} onTouchStart={toastTouchStart} onTouchMove={toastTouchMove} onTouchEnd={toastTouchEnd} onClick={() => { if (!toastGesture.current.dismissed) { setToastDismissed(true); } }}>{toastText}</div>{upNext && currentTrack && <div id="upnext" className={`tcard ${upNext && !toastDismissed ? 'visible' : ''}`} onTouchStart={toastTouchStart} onTouchMove={toastTouchMove} onTouchEnd={toastTouchEnd} onClick={() => { if (!toastGesture.current.dismissed) { setToastDismissed(true); } }}><span className="upnext-label">Up next</span><span className="upnext-art" style={{ background: coverBackground(displayNextTrack?.cover, displayNextTrack?.t) }}/><span className="upnext-copy"><b>{radio && !nextTrack ? 'Finding radio tracks…' : displayNextTrack?.t}</b><small>{radio && !nextTrack ? 'Radio' : displayNextTrack?.a}</small></span></div>}{download && <div id="dl" className="on"><span id="dllabel">{download.status === 'done' ? 'ready' : 'downloading'} {download.label}</span><div id="dlbar"><i id="dlfill" style={{ width: `${download.pct}%` }}/></div><span id="dlpct">{Math.round(download.pct)}%</span></div>}<audio ref={audioRef} preload="auto" />

  </>;
}

function QueueRow({ track, active = false, onClick }) { return <div className={`dfsQrow ${active ? 'cur' : ''}`} onClick={onClick}><span className="dfsQcov" style={{ background: track?.cover ? escStyle(track.cover) : gradient(track?.t) }}/><span className="dfsQt"><b>{track?.t}</b><small>{track?.a}</small></span></div>; }

// Touch + pointer gestures work on Android WebView and desktop browsers.
function bootstrap() {
  createRoot(document.getElementById('root')).render(<App/>);
  if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === '127.0.0.1' || location.hostname === 'localhost')) navigator.serviceWorker.register('/sw.js').catch(() => {});
}

bootstrap();
