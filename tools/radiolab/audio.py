"""Audio vectors for the radio store's tracks, from 30 s previews.

Spotify's own preview (the embed page) rate-limits an IP within a minute, so
previews come from Deezer's public search, matched on the core title, lead
artist and length, with the Deezer id, ISRC and match score kept for audit.
Each preview is decoded with ffmpeg and run through two Essentia
Discogs-EffNet models (ONNX): the style classifier (1280-d embedding and 400
style probabilities) and the track-similarity model (512-d). Vectors are the
mean over 2 s patches and land in webstate/radiolab/audio.db. The same
`embed_file` turns any local audio file into the same vectors.

  python3 -m venv radiolab-venv && radiolab-venv/bin/pip install -r tools/radiolab/requirements.txt
  radiolab-venv/bin/python tools/radiolab/audio.py [--min-count 3] [--limit N]
"""
import argparse, json, os, re, sqlite3, subprocess, sys, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(os.path.expanduser(os.environ.get("KOTASSIUM_LIB", "~/Music/Kotassium")), "webstate", "radiolab")
MODELS = os.path.join(LAB, "models")
MODEL_URL = "https://essentia.upf.edu/models/feature-extractors/discogs-effnet/{}.onnx"
STYLE, SIMILAR = "discogs-effnet-bsdynamic-1", "discogs_track_embeddings-effnet-bs64-1"
SR, NFFT, HOP, MELS, PATCH, PATCH_HOP = 16000, 512, 256, 96, 128, 62
SCHEMA = """CREATE TABLE IF NOT EXISTS audio (uri TEXT PRIMARY KEY, preview TEXT, effnet BLOB, styles BLOB,
            similar BLOB, at REAL, error TEXT, deezer INTEGER, isrc TEXT, match REAL)"""


def _mel_filters():
    def hz_to_mel(f):
        f = np.asarray(f, float)
        lin = f / (200.0 / 3)
        return np.where(f >= 1000, 15 + np.log(np.maximum(f, 1e-9) / 1000) / (np.log(6.4) / 27), lin)

    def mel_to_hz(m):
        m = np.asarray(m, float)
        return np.where(m >= 15, 1000 * np.exp((np.log(6.4) / 27) * (m - 15)), m * 200.0 / 3)

    freqs = np.linspace(0, SR / 2, NFFT // 2 + 1)
    edges = mel_to_hz(np.linspace(hz_to_mel(0), hz_to_mel(SR / 2), MELS + 2))
    fb = np.zeros((MELS, len(freqs)))
    for i in range(MELS):
        lo, c, hi = edges[i:i + 3]
        fb[i] = np.maximum(0, np.minimum((freqs - lo) / (c - lo), (hi - freqs) / (hi - c)))
        fb[i] *= 2.0 / (hi - lo)
    return fb.astype(np.float32)


FB = _mel_filters()
WIN = np.hanning(NFFT + 1)[:-1].astype(np.float32)


def patches(pcm):
    n = 1 + (len(pcm) - NFFT) // HOP
    if n < PATCH:
        pcm = np.pad(pcm, (0, NFFT + HOP * (PATCH - 1) - len(pcm)))
        n = PATCH
    frames = np.lib.stride_tricks.as_strided(pcm, (n, NFFT), (pcm.strides[0] * HOP, pcm.strides[0]))
    power = np.abs(np.fft.rfft(frames * WIN, axis=1)) ** 2
    mel = np.log10(1 + 10000 * (power @ FB.T)).astype(np.float32)
    starts = range(0, n - PATCH + 1, PATCH_HOP)
    return np.stack([mel[s:s + PATCH] for s in starts])


def decode(data_or_path, start=None, seconds=None):
    args = ["ffmpeg", "-v", "error"]
    if start is not None:
        args += ["-ss", str(start)]
    args += ["-i", "pipe:0" if isinstance(data_or_path, bytes) else data_or_path]
    if seconds:
        args += ["-t", str(seconds)]
    args += ["-f", "f32le", "-ac", "1", "-ar", str(SR), "pipe:1"]
    out = subprocess.run(args, input=data_or_path if isinstance(data_or_path, bytes) else None,
                         capture_output=True, check=True).stdout
    return np.frombuffer(out, np.float32)


class Embedder:
    def __init__(self):
        import onnxruntime as ort
        os.makedirs(MODELS, exist_ok=True)
        self.sess = {}
        for name in (STYLE, SIMILAR):
            path = os.path.join(MODELS, name + ".onnx")
            if not os.path.exists(path):
                urllib.request.urlretrieve(MODEL_URL.format(name), path + ".part")
                os.replace(path + ".part", path)
            self.sess[name] = ort.InferenceSession(path, providers=["CoreMLExecutionProvider", "CPUExecutionProvider"])

    def _run(self, name, x):
        s = self.sess[name]
        return s.run(None, {s.get_inputs()[0].name: x})

    def __call__(self, pcm):
        x = patches(pcm)
        style = self._run(STYLE, x)
        pad = np.zeros((64, PATCH, MELS), np.float32)
        pad[:min(64, len(x))] = x[:64]
        sim = self._run(SIMILAR, pad)[0][:min(64, len(x))]
        return {"styles": style[0].mean(0), "effnet": style[1].mean(0), "similar": sim.mean(0)}


def embed_file(emb, path):
    """A local file: the 30 s from 30% in, roughly where a preview sits."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                           capture_output=True, text=True).stdout.strip()
    dur = float(probe or 0)
    return emb(decode(path, start=max(0.0, dur * 0.3 if dur > 60 else 0.0), seconds=30))


class Rate:
    def __init__(self, per_s):
        self.gap, self.next, self.lock = 1.0 / per_s, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            self.next = max(self.next + self.gap, now)
            delay = self.next - now
        time.sleep(delay)


DEEZER = Rate(8)


def _words(s):
    return set(re.sub(r"[^\w]+", " ", (s or "").lower().replace("$", "s")).split())


def core_title(name):
    return re.split(r" - |\s[\(\[]", name or "")[0].strip() or name


VERSION = {"remix", "live", "edit", "mix", "version", "instrumental", "karaoke", "cover", "style", "acoustic",
           "remaster", "remastered", "sped", "slowed", "extended", "demo", "tribute", "originally"}


def best_match(cands, name, artists, dur_ms):
    """artists: every credited name, since Deezer may credit another first."""
    want_t, want_a, full = _words(core_title(name)), set().union(*map(_words, artists)), _words(name)
    best = (0.0, None)
    for c in cands:
        got_t = _words(core_title(c.get("title") or ""))
        title = len(want_t & got_t) / max(1, len(want_t | got_t))
        got_a = _words((c.get("artist") or {}).get("name") or "")
        art = len(want_a & got_a) / max(1, len(got_a))
        if title < 0.5 or art < 0.5 or not c.get("preview"):
            continue
        extra = len((_words(c.get("title")) - full) & VERSION)
        length = 1.0 if not dur_ms else max(0.0, 1 - abs(c.get("duration", 0) - dur_ms / 1000) / 30)
        sc = title + art + length - 0.75 * extra
        if sc > best[0]:
            best = (sc, c)
    return best


def fetch_preview(track):
    uri, name, artists, dur_ms = track
    err = "no match"
    for q in (f"{core_title(name)} {artists[0] if artists else ''}", core_title(name)):
        try:
            DEEZER.wait()
            url = "https://api.deezer.com/search?" + urllib.parse.urlencode({"q": q, "limit": 10})
            d = json.loads(urllib.request.urlopen(url, timeout=20).read())
            if "error" in d:
                time.sleep(5)
                err = str(d["error"])[:150]
                continue
            sc, c = best_match(d.get("data") or [], name, artists, dur_ms)
            if c:
                data = urllib.request.urlopen(c["preview"], timeout=30).read()
                return uri, c, sc, data, None
        except Exception as e:
            err = str(e)[:150]
            time.sleep(3)
    return uri, None, 0.0, None, err


def audio_db():
    os.makedirs(LAB, exist_ok=True)
    db = sqlite3.connect(os.path.join(LAB, "audio.db"), timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(SCHEMA)
    return db


def f16(v):
    return np.asarray(v, np.float16).tobytes()


def main():
    sys.path.insert(0, ROOT)
    from serve_web import RADIO_DB
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-count", type=int, default=3, help="embed tracks recommended at least this often, plus seeds")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rate", type=float, default=9.5, help="Deezer API requests per second (their limit is 10)")
    a = ap.parse_args()
    DEEZER.gap = 1.0 / a.rate
    rdb, adb = sqlite3.connect(RADIO_DB, timeout=30), audio_db()
    done = {u for (u,) in adb.execute("SELECT uri FROM audio")}
    meta = {u: (n, json.loads(a or "[]"), d) for u, n, a, d in rdb.execute("SELECT uri, name, artists, duration_ms FROM track")}
    todo = [u for (u,) in rdb.execute(
        "SELECT track FROM radio_item GROUP BY track HAVING COUNT(*) >= ? OR track IN (SELECT seed FROM radio)"
        " ORDER BY track IN (SELECT seed FROM radio) DESC, COUNT(*) DESC", (a.min_count,)) if u not in done and u in meta]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(todo)} tracks to embed ({len(done)} already)", flush=True)
    jobs = [(u, meta[u][0], [n for _, n in meta[u][1]], meta[u][2]) for u in todo]
    emb, t0, n, ok = Embedder(), time.time(), 0, 0
    with ThreadPoolExecutor(a.workers) as ex:
        for uri, c, sc, data, err in ex.map(fetch_preview, jobs):
            row = (uri, None, None, None, None, time.time(), err, None, None, 0.0)
            if data:
                try:
                    v = emb(decode(data))
                    row = (uri, c["preview"], f16(v["effnet"]), f16(v["styles"]), f16(v["similar"]), time.time(), None,
                           c["id"], c.get("isrc"), sc)
                    ok += 1
                except Exception as e:
                    row = (uri, c["preview"], None, None, None, time.time(), f"decode: {str(e)[:150]}", c["id"],
                           c.get("isrc"), sc)
            adb.execute("INSERT OR REPLACE INTO audio VALUES (?,?,?,?,?,?,?,?,?,?)", row)
            n += 1
            if n % 200 == 0:
                adb.commit()
                print(f"{time.strftime('%H:%M:%S')} {n}/{len(todo)} matched {ok / n:.0%} {n / (time.time() - t0):.1f}/s",
                      flush=True)
    adb.commit()


if __name__ == "__main__":
    main()
