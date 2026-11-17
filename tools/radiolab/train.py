"""Learn song vectors from audio so a vector search reproduces Spotify radio.

Query tower: a seed's audio features -> 128-d vector. Item side: each
catalogue track's vector is the same kind of projection of its own audio
plus a learned offset (so a track nobody has recommended yet still has a
vector). Training maximises the softmax probability, over the whole
catalogue, of the tracks the seed's real radio played, earlier positions
weighted more. Seeds held out with their radios score the model: the share
of each held-out radio's 49 tracks found in the top 49 of the search.

  radiolab-venv/bin/python tools/radiolab/train.py [--epochs 30] [--dim 128]
"""
import argparse, json, os, sqlite3, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import audio as A

ARTIST_CAP = 5
SEED_SLOTS = 9


def load(radio_db, audio_db):
    adb = sqlite3.connect(audio_db)
    feats = {}
    for uri, e, s, m in adb.execute("SELECT uri, effnet, styles, similar FROM audio WHERE effnet IS NOT NULL"):
        feats[uri] = np.concatenate([np.frombuffer(e, np.float16), np.frombuffer(m, np.float16),
                                     np.frombuffer(s, np.float16)]).astype(np.float32)
    rdb = sqlite3.connect(radio_db)
    radios = {}
    for rid, seed in rdb.execute("SELECT id, seed FROM radio WHERE seed LIKE 'spotify:track:%' ORDER BY last_seen"):
        radios[seed] = rid
    items = {}
    for rid, track in rdb.execute("SELECT radio, track FROM radio_item ORDER BY radio, pos"):
        items.setdefault(rid, []).append(track)
    meta = {u: (n, json.loads(a or "[]")) for u, n, a in rdb.execute("SELECT uri, name, artists FROM track")}
    radios = {s: [t for t in items.get(rid, []) if t != s][:49] for s, rid in radios.items()}
    return feats, {s: r for s, r in radios.items() if len(r) >= 40}, meta


def lead(meta, uri):
    a = meta.get(uri, ("", []))[1]
    return a[0][0] if a else None


def split(radios, feats, meta, frac, rng):
    seeds = sorted(s for s in radios if s in feats)
    rng.shuffle(seeds)
    held = seeds[: int(len(seeds) * frac)]
    train = [s for s in radios if s not in set(held)]
    key = lambda u: (norm_title(meta.get(u, ("", []))[0]), lead(meta, u))
    train_keys = {key(s) for s in train}
    return train, [s for s in held if key(s) not in train_keys]


def norm_title(s):
    import re
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def pick(scores, uris, meta, exclude, n=49, seed_artist=None):
    """Top tracks under the radio's caps; with the seed's artist known, up to
    SEED_SLOTS of theirs go in first, as Spotify's radio places them."""
    order = [uris[i] for i in np.argsort(-scores) if uris[i] not in exclude]
    out = [u for u in order if seed_artist and lead(meta, u) == seed_artist][:SEED_SLOTS]
    per = {seed_artist: len(out)} if seed_artist else {}
    for u in order:
        if len(out) == n:
            break
        a = lead(meta, u)
        if a == seed_artist or per.get(a, 0) >= ARTIST_CAP:
            continue
        per[a] = per.get(a, 0) + 1
        out.append(u)
    return out


def score(held, radios, query_fn, cat_uris, cat_vecs, meta, bias=None, known_artist=False):
    hits = []
    for s in held:
        sc = cat_vecs @ query_fn(s)
        if bias is not None:
            sc = sc + bias
        got = pick(sc, cat_uris, meta, {s}, seed_artist=lead(meta, s) if known_artist else None)
        hits.append(len(set(got) & set(radios[s])) / 49)
    return float(np.mean(hits)), hits


class Adam:
    def __init__(self, params, lr):
        self.p, self.lr, self.t = params, lr, 0
        self.m = [np.zeros_like(x) for x in params]
        self.v = [np.zeros_like(x) for x in params]

    def step(self, grads):
        self.t += 1
        for x, g, m, v in zip(self.p, grads, self.m, self.v):
            m *= 0.9; m += 0.1 * g
            v *= 0.999; v += 0.001 * g * g
            x -= self.lr * (m / (1 - 0.9 ** self.t)) / (np.sqrt(v / (1 - 0.999 ** self.t)) + 1e-8)


def main():
    from serve_web import RADIO_DB
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--dim", type=int, default=128)
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--l2", type=float, default=1e-4)
    ap.add_argument("--offset-l2", type=float, default=1e-3)
    ap.add_argument("--pos-tau", type=float, default=20.0)
    ap.add_argument("--held", type=float, default=0.1)
    ap.add_argument("--pca", type=int, default=256)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(A.LAB, "model.npz"))
    ap.add_argument("--radio-db", default=RADIO_DB)
    ap.add_argument("--audio-db", default=os.path.join(A.LAB, "audio.db"))
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    feats, radios, meta = load(a.radio_db, a.audio_db)
    train, held = split(radios, feats, meta, a.held, rng)
    val, test = held[: len(held) // 2], held[len(held) // 2:]
    train_q = [s for s in train if s in feats]
    seen = {t for s in train for t in radios[s]} | set(train)
    cat_uris = sorted(u for u in seen if u in feats)
    idx = {u: i for i, u in enumerate(cat_uris)}
    ceiling = np.mean([len(set(radios[s]) & set(cat_uris)) / 49 for s in test])
    print(f"{len(radios)} track radios, {len(feats)} tracks with audio, train seeds with audio {len(train_q)},"
          f" validation {len(val)}, test {len(test)}, catalogue {len(cat_uris)}, test ceiling {ceiling:.3f}", flush=True)

    X = np.stack([feats[u] for u in cat_uris])
    mu, sd = X.mean(0), X.std(0) + 1e-4
    Z0 = (X - mu) / sd
    evals, evecs = np.linalg.eigh(Z0.T @ Z0 / len(Z0))
    P = evecs[:, ::-1][:, :a.pca].astype(np.float32)
    print(f"PCA {a.pca} keeps {evals[::-1][:a.pca].sum() / evals.sum():.1%} of the variance", flush=True)
    std = lambda v: (v - mu) / sd
    norm = lambda v: std(v) @ P
    Xc = Z0 @ P

    counts = np.zeros(len(cat_uris), np.float32)
    for s in train:
        for t in radios[s]:
            if t in idx:
                counts[idx[t]] += 1
    pop = np.log1p(counts)
    raw_sim = Z0[:, 1280:1792] / np.linalg.norm(Z0[:, 1280:1792], axis=1, keepdims=True)
    q_raw = lambda s: (lambda v: v / np.linalg.norm(v))(std(feats[s])[1280:1792])
    base_pop, _ = score(test, radios, lambda s: np.zeros(1), cat_uris, np.zeros((len(cat_uris), 1)), meta, bias=pop)
    base_raw, _ = score(test, radios, q_raw, cat_uris, raw_sim, meta)
    print(f"baseline most-recommended tracks {base_pop:.3f}; untrained Discogs similarity {base_raw:.3f}", flush=True)

    # Targets: each training seed's radio as a distribution over the catalogue.
    w = np.exp(-np.arange(49) / a.pos_tau).astype(np.float32)
    T_rows = [(idx[s] if s in idx else None, feats[s], [(idx[t], w[p]) for p, t in enumerate(radios[s]) if t in idx])
              for s in train_q]
    T_rows = [r for r in T_rows if r[2]]
    Q = np.stack([norm(r[1]) for r in T_rows])
    D_in, H, d, N = Xc.shape[1], a.hidden, a.dim, len(cat_uris)
    sc = lambda *shape: (rng.standard_normal(shape) / np.sqrt(shape[0])).astype(np.float32)
    W1, b1, W2 = sc(D_in, H), np.zeros(H, np.float32), sc(H, d)
    G, E, bias = sc(D_in, d), np.zeros((N, d), np.float32), np.zeros(N, np.float32)
    params = [W1, b1, W2, G, E, bias]
    opt = Adam(params, a.lr)

    def query(x):
        h = np.maximum(0, x @ W1 + b1)
        return h, h @ W2

    best, best_state, B = -1, None, 256
    for ep in range(a.epochs):
        t0 = time.time()
        order = rng.permutation(len(T_rows))
        loss_sum = 0.0
        for start in range(0, len(order), B):
            bi = order[start:start + B]
            x = Q[bi]
            h, q = query(x)
            V = Xc @ G + E
            S = q @ V.T + bias
            Y = np.zeros_like(S)
            for r, k in enumerate(bi):
                ii, ww = zip(*T_rows[k][2])
                Y[r, list(ii)] = ww
                if T_rows[k][0] is not None:
                    S[r, T_rows[k][0]] = -1e9
            Y /= Y.sum(1, keepdims=True)
            S -= S.max(1, keepdims=True)
            Z = np.exp(S)
            Z /= Z.sum(1, keepdims=True)
            loss_sum += float(-(Y * np.log(Z + 1e-12)).sum())
            dS = (Z - Y) / len(bi)
            dq = dS @ V
            dV = dS.T @ q
            dbias = dS.sum(0)
            dW2 = h.T @ dq
            dh = (dq @ W2.T) * (h > 0)
            dW1, db1 = x.T @ dh, dh.sum(0)
            dG = Xc.T @ dV
            dE = dV + a.offset_l2 * E
            opt.step([dW1 + a.l2 * W1, db1, dW2 + a.l2 * W2, dG + a.l2 * G, dE, dbias])
        V = Xc @ G + E
        acc, _ = score(val, radios, lambda s: query(norm(feats[s]))[1], cat_uris, V, meta, bias=bias)
        print(f"epoch {ep + 1} loss {loss_sum / len(T_rows):.3f} validation {acc:.3f} ({time.time() - t0:.0f}s)", flush=True)
        if acc > best:
            best, best_state = acc, [p.copy() for p in params]
    W1, b1, W2, G, E, bias = best_state
    V = Xc @ G + E
    q_model = lambda s: query(norm(feats[s]))[1]
    test_acc, _ = score(test, radios, q_model, cat_uris, V, meta, bias=bias)
    test_art, _ = score(test, radios, q_model, cat_uris, V, meta, bias=bias, known_artist=True)
    raw_art, _ = score(test, radios, q_raw, cat_uris, raw_sim, meta, known_artist=True)
    print(f"with the seed's artist known: untrained Discogs {raw_art:.3f}, model {test_art:.3f}", flush=True)

    # The artist tag also finds the stored radios of that artist's other songs.
    by_artist = {}
    for s0 in train:
        ar = lead(meta, s0)
        if ar:
            c = by_artist.setdefault(ar, np.zeros(len(cat_uris), np.float32))
            for p0, t in enumerate(radios[s0]):
                if t in idx:
                    c[idx[t]] += w[p0]
    zero = np.zeros(len(cat_uris), np.float32)
    def mixed(held_set, lam):
        hits = []
        for s0 in held_set:
            prior = np.log1p(by_artist.get(lead(meta, s0), zero))
            sc0 = V @ q_model(s0) + bias + lam * prior
            got = pick(sc0, cat_uris, meta, {s0}, seed_artist=lead(meta, s0))
            hits.append(len(set(got) & set(radios[s0])) / 49)
        return float(np.mean(hits))
    lam = max([0.5, 1, 2, 4, 8, 16], key=lambda l: mixed(val, l))
    only = np.mean([len(set(pick(np.log1p(by_artist.get(lead(meta, s0), zero)) + 1e-6 * pop, cat_uris, meta, {s0},
                                 seed_artist=lead(meta, s0))) & set(radios[s0])) / 49 for s0 in test])
    print(f"with the artist's other stored radios: those radios alone {only:.3f}, plus the audio model"
          f" {mixed(test, lam):.3f} (weight {lam} chosen on validation);"
          f" test seeds whose artist has other radios {np.mean([lead(meta, s0) in by_artist for s0 in test]):.0%}",
          flush=True)
    np.savez(a.out, W1=W1, b1=b1, W2=W2, G=G, E=E, bias=bias, mu=mu, sd=sd, P=P, uris=np.array(cat_uris),
             vecs=V.astype(np.float32), held=np.array(held))
    print(f"test {test_acc:.3f} at best validation {best:.3f} (test ceiling {ceiling:.3f}); saved {a.out}", flush=True)


if __name__ == "__main__":
    main()
