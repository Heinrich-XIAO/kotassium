"""Predict a song's Spotify radio from the stored radios around it, offline.

Spotify's radio is roughly a nearest-neighbour list, and it is reciprocal:
when s sits high in y's radio, y is usually in s's. So the radios already
stored say a lot about one we have not fetched - which radios s appears in,
what sits next to it there, what its artist's radios hold - and a learned
track embedding in which every stored radio is its seed's nearest
neighbours. Each candidate track gets features from that neighbourhood
(each fold's embedding and co-occurrence built without the radios that fold
is graded on), a LightGBM LambdaRank model
orders them, and the radio's caps (9 seed-artist slots, 5 per other
artist) pick the 49.

Scoring holds seeds out together with every stored radio of the same song
(any id), so a prediction never sees the radio it is graded on. Spotify
re-rolls about a fifth of a radio every day, so the fair yardstick is
Spotify itself: --fresh refetches the test seeds' radios now (or reads a
previous refetch) and reports the local radio's overlap with them next to
the overlap of Spotify's own stored, older radio.

  radiolab-venv/bin/python tools/radiolab/graph.py --fresh refetch.json --out model.pkl
  radiolab-venv/bin/python tools/radiolab/graph.py --model model.pkl --predict spotify:track:...

LightGBM needs OpenMP on macOS: brew install libomp.
"""
import argparse, json, math, os, pickle, random, re, sqlite3, sys, time
from collections import defaultdict
import numpy as np
import scipy.sparse as sp

ARTIST_CAP, SEED_SLOTS, N = 5, 9, 49
TAU = 50.0
W = [math.exp(-p / TAU) for p in range(64)]
W10 = [math.exp(-p / 10.0) for p in range(64)]


def day_of(ts):
    """Spotify regenerates radios daily; radios from one day agree a little more."""
    return time.strftime("%Y-%m-%d", time.localtime(ts or 0))


def norm_title(s):
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


class Graph:
    """Every stored track radio, indexed both ways."""

    def __init__(self, db_path):
        db = sqlite3.connect(db_path)
        seed_of, self.day = {}, {}
        for rid, seed, seen in db.execute("SELECT id, seed, last_seen FROM radio WHERE seed LIKE 'spotify:track:%'"
                                          " ORDER BY last_seen"):
            seed_of[rid] = seed
            self.day[seed] = day_of(seen)
        items = defaultdict(list)
        for rid, t in db.execute("SELECT radio, track FROM radio_item ORDER BY radio, pos"):
            if rid in seed_of:
                items[rid].append(t)
        self.meta = {}
        for u, n, a, pc, rel in db.execute("SELECT uri, name, artists, playcount, released FROM track"):
            self.meta[u] = (n or "", [x[0] for x in json.loads(a or "[]")], int(pc or 0), str(rel or "")[:4])
        radio = {seed_of[r]: [t for t in v if t != seed_of[r]][:N] for r, v in items.items()}
        self.radio = {s: v for s, v in radio.items() if len(v) >= 40}
        self.inn = defaultdict(list)          # track -> [(seed whose radio holds it, position)]
        self.by_artist = defaultdict(list)    # lead artist -> seeds
        self.by_key = defaultdict(set)        # (title, lead artist) -> seeds: one song, many ids
        self.art_radios = defaultdict(set)    # artist -> seeds whose radio has them
        self.radio_arts = {}
        for s, v in self.radio.items():
            for p, t in enumerate(v):
                self.inn[t].append((s, p))
            self.by_artist[self.lead(s)].append(s)
            self.by_key[self.key(s)].add(s)
            self.radio_arts[s] = {self.lead(t) for t in v}
            for b in self.radio_arts[s]:
                self.art_radios[b].add(s)
        self.indeg = {t: len(v) for t, v in self.inn.items()}
        self.art_pop = {b: len(v) for b, v in self.art_radios.items()}

    def lead(self, u):
        a = self.meta.get(u, ("", []))[1]
        return a[0] if a else None

    def key(self, u):
        return norm_title(self.meta.get(u, ("",))[0]), self.lead(u)

    def banned(self, s):
        return self.by_key.get(self.key(s), set()) | {s}


class Embedding:
    """A vector per track, trained so every stored radio is its seed's nearest
    neighbours (full softmax over the catalogue, cosine / temperature + a
    per-track bias). A seed without a stored radio still has a vector from the
    radios it appears in, and because the radio is reciprocal that vector
    lands near its own neighbours."""

    def __init__(self, g, excluded, dim=128, epochs=8, temp=0.07, lr=0.01, bs=256, log=None):
        self.temp = temp
        self.cat = sorted({t for t, d in g.indeg.items() if d >= 2} | set(g.radio))
        self.ix = {t: i for i, t in enumerate(self.cat)}
        n = len(self.cat)
        seeds = [y for y in g.radio if y not in excluded]
        rows = np.array([self.ix[y] for y in seeds])
        tr, tc, tw = [], [], []
        for r, y in enumerate(seeds):
            v = [(self.ix[t], W[q]) for q, t in enumerate(g.radio[y]) if t in self.ix]
            tot = sum(w for _, w in v)
            for j, w in v:
                tr.append(r), tc.append(j), tw.append(w / tot)
        tr, tc, tw = np.array(tr), np.array(tc), np.array(tw, np.float32)
        starts = np.searchsorted(tr, np.arange(len(seeds) + 1))
        # torch and LightGBM each bring an OpenMP runtime, and one process
        # holding both segfaults in torch's backward pass: train elsewhere
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(1) as pool:
            self.V, self.b = pool.apply(_fit_embedding, (n, rows, starts, tc, tw, dim, epochs, temp, lr, bs, bool(log)))

    def scores(self, s):
        i = self.ix.get(s)
        return None if i is None else self.V @ self.V[i] / self.temp + self.b

    def neighbours(self, s, k, banned):
        sc = self.scores(s)
        if sc is None:
            return []
        top = np.argpartition(-sc, k + len(banned) + 1)[:k + len(banned) + 1]
        return [self.cat[i] for i in top if self.cat[i] not in banned and self.cat[i] != s][:k]


def _fit_embedding(n, rows, starts, tc, tw, dim, epochs, temp, lr, bs, log):
    import torch
    torch.manual_seed(0)
    rows = torch.from_numpy(rows)
    E = torch.nn.Parameter(torch.randn(n, dim) * 0.1)
    b = torch.nn.Parameter(torch.zeros(n))
    opt = torch.optim.Adam([E, b], lr=lr)
    rng = np.random.default_rng(0)
    for ep in range(epochs):
        t0, tot = time.time(), 0.0
        perm = rng.permutation(len(rows))
        for i in range(0, len(perm), bs):
            bb = perm[i:i + bs]
            ri = np.concatenate([np.full(starts[r + 1] - starts[r], k) for k, r in enumerate(bb)])
            ci = np.concatenate([tc[starts[r]:starts[r + 1]] for r in bb])
            wi = np.concatenate([tw[starts[r]:starts[r + 1]] for r in bb])
            T = torch.zeros(len(bb), n)
            T[torch.from_numpy(ri), torch.from_numpy(ci)] = torch.from_numpy(wi)
            En = torch.nn.functional.normalize(E, dim=1)
            L = En[rows[bb]] @ En.T / temp + b
            L[torch.arange(len(bb)), rows[bb]] = -1e4
            loss = -(T * torch.log_softmax(L, 1)).sum(1).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss.detach()) * len(bb)
        if log:
            print(f"    embedding epoch {ep} loss {tot / len(rows):.3f} {time.time() - t0:.0f}s", flush=True)
    with torch.no_grad():
        return torch.nn.functional.normalize(E, dim=1).numpy(), b.numpy()


class SecondOrder:
    """cos(C_s, C_t) over co-occurrence rows, from a graph without `excluded` radios."""

    def __init__(self, g, excluded):
        tracks = sorted({t for v in g.radio.values() for t in v} | set(g.radio))
        self.ix = {t: i for i, t in enumerate(tracks)}
        rows, cols = [], []
        r = 0
        for y, v in g.radio.items():
            if y in excluded:
                continue
            for t in [y] + v:
                rows.append(r)
                cols.append(self.ix[t])
            r += 1
        M = sp.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(r, len(tracks)))
        # C = M.T @ M is too big to hold once the store passes ~20k radios;
        # its rows are built on demand and only their norms are kept
        self.M, self.Mt = M, M.T.tocsr()
        self.deg = np.asarray(M.sum(0)).ravel()
        sq = np.zeros(len(tracks), np.float64)
        for i in range(0, len(tracks), 4000):
            R = self.Mt[i:i + 4000] @ M
            sq[i:i + 4000] = np.asarray(R.multiply(R).sum(1)).ravel()
        self.nrm = np.sqrt(np.maximum(sq - self.deg.astype(np.float64) ** 2, 0)) + 1e-6

    def rows(self, idx):
        R = (self.Mt[idx] @ self.M).tocsr()
        diag = sp.csr_matrix((self.deg[idx], (np.arange(len(idx)), idx)), shape=R.shape)
        return R - diag

    def __call__(self, s, cands):
        i = self.ix.get(s)
        if i is None:
            return np.zeros(len(cands), np.float32)
        ci = np.array([self.ix.get(t, i) for t in cands])
        R = self.rows(np.concatenate([[i], ci]))
        dots = np.asarray((R[1:] @ R[0].T).todense()).ravel()
        out = dots / (self.nrm[i] * self.nrm[ci])
        out[ci == i] = 0
        return out.astype(np.float32)


NAMES = ["cooc", "cooc_n", "in_frac", "rev", "art_cooc", "art_frac", "same_lead", "share_art", "log_indeg",
         "log_pc", "nbr_sim", "nbr_art", "year_d", "is_art_seed", "hop2", "art_any", "art_seedr", "art_pop",
         "n_in", "n_art", "n_any", "art_in", "t_crawled", "tri_max", "tri_sum", "top10", "pc_rank", "pc_rel",
         "cooc_day", "rev_day", "n_in_day", "seed_pc", "pc_vs_seed", "indeg_vs_seed", "sim2",
         "emb", "emb_rank"]
LOGS = tuple(NAMES.index(n) for n in ("cooc", "cooc_n", "rev", "art_cooc", "nbr_sim", "nbr_art", "hop2", "tri_sum", "top10",
                                       "cooc_day", "rev_day"))


def features(g, s, sim2=None, max_cand=3000, day=None, emb=None):
    """Candidates for s's radio and their features; `day` is the day the radio is wanted for."""
    banned = g.banned(s)
    sa, sart = g.lead(s), set(g.meta.get(s, ("", []))[1])
    cooc, cnt, rev, acooc, acnt, hop2, a_any, a_seed, a_in, tmax, tsum, top10, cday, rday = (
        defaultdict(float) for _ in range(14))
    nin = nart = nday = 0
    for y, p in g.inn.get(s, []):
        if y in banned:
            continue
        nin += 1
        rev[y] += W[p]
        today = g.day.get(y) == day
        if today:
            nday += 1
            rday[y] += W[p]
        for b in g.radio_arts[y]:
            a_in[b] += W[p]
        for q, t in enumerate(g.radio[y]):
            cooc[t] += W[p] * W[q]
            cnt[t] += 1
            if today:
                cday[t] += W[p] * W[q]
            tri = W10[p] * W10[q]
            tsum[t] += tri
            if tri > tmax[t]:
                tmax[t] = tri
            if p < 10 and q < 10:
                top10[t] += 1
    for y in g.by_artist.get(sa, []):
        if y in banned:
            continue
        nart += 1
        acooc[y] += 1
        for b in g.radio_arts[y]:
            a_seed[b] += 1
        for q, t in enumerate(g.radio[y]):
            acooc[t] += W[q]
            acnt[t] += 1
    any_r = [y for y in g.art_radios.get(sa, ()) if y not in banned]
    for y in any_r:
        for b in g.radio_arts[y]:
            a_any[b] += 1
    art_score = defaultdict(float)
    for t, v in cooc.items():
        art_score[g.lead(t)] += v
    for u in sorted(cooc, key=lambda u: -cooc[u])[:15]:
        if u in g.radio and u not in banned:
            for q, t in enumerate(g.radio[u]):
                hop2[t] += cooc[u] * W[q]
    near = emb.neighbours(s, 300, banned) if emb else []
    cand = (set(cooc) | set(rev) | set(acooc) | set(hop2) | set(near)) - banned
    if not cand:
        return [], None
    if len(cand) > max_cand:
        prior = lambda t: cooc.get(t, 0) + 3 * rev.get(t, 0) + acooc.get(t, 0) + hop2.get(t, 0) * 0.3
        cand = sorted(set(cand) - set(near), key=prior, reverse=True)[:max_cand] + [t for t in near if t in cand]
    cl = list(cand)
    # the seed artist's 9 slots favour their best-known tracks
    pcs = sorted((g.meta.get(t, ("", [], 0))[2] for t in cl if g.lead(t) == sa), reverse=True)
    pc_rank = {pc: i for i, pc in reversed(list(enumerate(pcs)))}
    pc_top = pcs[0] if pcs else 0
    norm = math.sqrt(sum(v * v for v in cooc.values())) or 1.0
    sy, spc = g.meta.get(s, ("", [], 0, ""))[3], math.log1p(g.meta.get(s, ("", [], 0))[2])
    sdeg = math.log1p(nin)
    rows = []
    for t in cl:
        m = g.meta.get(t, ("", [], 0, ""))
        lt = g.lead(t)
        nb = sum(cooc.get(u, 0.0) for u in g.radio[t]) / norm if t in g.radio and t not in banned else 0.0
        yd = abs(int(sy) - int(m[3])) if sy.isdigit() and m[3].isdigit() else 10
        rows.append([cooc.get(t, 0.0), cooc.get(t, 0.0) / math.sqrt(g.indeg.get(t, 1)), cnt.get(t, 0) / max(1, nin),
                     rev.get(t, 0.0), acooc.get(t, 0.0), acnt.get(t, 0) / max(1, nart),
                     float(lt == sa), float(bool(set(m[1]) & sart)), math.log1p(g.indeg.get(t, 0)),
                     math.log1p(m[2]), nb, art_score.get(lt, 0.0) / norm, min(yd, 30) / 10.0,
                     float(t in g.by_artist.get(sa, ())), hop2.get(t, 0.0),
                     a_any.get(lt, 0.0) / max(1, len(any_r)), a_seed.get(lt, 0.0) / max(1, nart),
                     math.log1p(g.art_pop.get(lt, 0)), math.log1p(nin), math.log1p(nart), math.log1p(len(any_r)),
                     a_in.get(lt, 0.0) / max(1, nin), float(t in g.radio and t not in banned),
                     tmax.get(t, 0.0), tsum.get(t, 0.0), top10.get(t, 0.0),
                     pc_rank.get(m[2], 60) if lt == sa else 60, m[2] / pc_top if lt == sa and pc_top else 0.0,
                     cday.get(t, 0.0), rday.get(t, 0.0), math.log1p(nday),
                     spc, math.log1p(m[2]) - spc, math.log1p(g.indeg.get(t, 0)) - sdeg, 0.0, 0.0, 0.0])
    X = np.asarray(rows, np.float32)
    if sim2 is not None:
        X[:, NAMES.index("sim2")] = sim2(s, cl)
    sc = emb.scores(s) if emb else None
    if sc is not None:
        ci = np.array([emb.ix.get(t, -1) for t in cl])
        e = np.where(ci >= 0, sc[np.maximum(ci, 0)], np.nan)
        X[:, NAMES.index("emb")] = e
        X[:, NAMES.index("emb_rank")] = np.argsort(np.argsort(-np.nan_to_num(e, nan=-1e9)))
    else:
        X[:, NAMES.index("emb")] = X[:, NAMES.index("emb_rank")] = np.nan
    for j in LOGS:
        X[:, j] = np.log1p(X[:, j] * 10)
    return cl, X


def pick(g, cands, scores, s):
    """The 49 under the radio's caps: the seed artist's 9 first, 5 per other artist."""
    sa = g.lead(s)
    order = [cands[i] for i in np.argsort(-scores)]
    out = [u for u in order if g.lead(u) == sa][:SEED_SLOTS]
    per = {}
    for u in order:
        if len(out) == N:
            break
        a = g.lead(u)
        if a == sa or per.get(a, 0) >= ARTIST_CAP:
            continue
        per[a] = per.get(a, 0) + 1
        out.append(u)
    return out


def split(g, n_test, n_val, seed=0, first=()):
    """Held-out test and validation seeds (`first` go to test), the rest train."""
    seeds = sorted(g.radio)
    random.Random(seed).shuffle(seeds)
    first = [s for s in first if s in g.radio]
    seeds = first + [s for s in seeds if s not in set(first)]
    held = seeds[: n_test + n_val]
    held_keys = {g.key(s) for s in held}
    train = [s for s in seeds[n_test + n_val:] if g.key(s) not in held_keys]
    return seeds[:n_test], seeds[n_test:n_test + n_val], train


def build(g, group, sim2, day=None, emb=None):
    out = []
    for s in group:
        cl, X = features(g, s, sim2, day=(day or {}).get(s, g.day.get(s)), emb=emb)
        truth = set(g.radio[s])
        y = None if X is None else np.array([c in truth for c in cl], np.float32)
        out.append((s, cl, X, y))
    return out


def refetch(seeds, path):
    """Spotify's radio for each seed as it is now, saved as {seed: {items, revision}}."""
    from concurrent.futures import ThreadPoolExecutor
    import spotify_get as sg
    prov = sg.TokenProvider()

    def one(s):
        for i in range(4):
            try:
                r = sg.fetch_radio(prov, s)
                return s, {"items": [it["track"]["uri"] for it in r["items"]], "revision": r["revision"],
                           "day": day_of(time.time())}
            except Exception:
                time.sleep(10 * (i + 1))
        return s, None
    with ThreadPoolExecutor(3) as ex:
        out = {s: r for s, r in ex.map(one, seeds) if r}
    with open(path, "w") as f:
        json.dump(out, f)
    return out


def predict(g, saved, s):
    cl, X = features(g, s, SecondOrder(g, g.banned(s)), day=day_of(time.time()), emb=saved.get("emb"))
    return [] if X is None else pick(g, cl, saved["model"].predict(X), s)


def main():
    import lightgbm as lgb
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(here)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    ap.add_argument("--fresh", help="JSON {seed: {items: [...]}} of radios refetched later, to grade against")
    ap.add_argument("--test", type=int, default=1000)
    ap.add_argument("--val", type=int, default=500)
    ap.add_argument("--train", type=int, default=8000)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--emb-epochs", type=int, default=8, help="0 skips the learned embedding")
    ap.add_argument("--iters", type=int, default=400)
    ap.add_argument("--out", help="save the trained model (and its held-out predictions beside it)")
    ap.add_argument("--model", help="a saved model, for --predict")
    ap.add_argument("--predict", nargs="*", help="seed track URIs to make a local radio for")
    a = ap.parse_args()
    if not a.db:
        from serve_web import RADIO_DB
        a.db = RADIO_DB
    t0 = time.time()
    g = Graph(a.db)
    if a.predict:
        with open(a.model, "rb") as f:
            saved = pickle.load(f)
        for s in a.predict:
            print(f"{g.meta.get(s, (s,))[0]} -", ", ".join(g.meta.get(t, (t,))[0] for t in predict(g, saved, s)))
        return
    fresh = {}
    fresh_day = None
    if a.fresh and os.path.exists(a.fresh):
        fresh = json.load(open(a.fresh))
        fresh_day = day_of(os.path.getmtime(a.fresh))
    test, val, train = split(g, a.test, a.val, first=sorted(fresh))
    if a.fresh and not fresh:
        fresh = refetch(test, a.fresh)
    train = train[: a.train]
    print(f"{len(g.radio)} radios, test {len(test)} val {len(val)} train {len(train)}", flush=True)
    # second-order similarity never sees the radios it scores: the held-out
    # seeds share one fold, the training seeds are spread over the others
    held = set().union(*(g.banned(s) for s in test + val))
    groups = [(test + val, held)]
    for f in range(a.folds):
        part = train[f::a.folds]
        groups.append((part, set().union(*(g.banned(s) for s in part))))
    built, kept = {}, None
    for group, excl in groups:
        so = SecondOrder(g, excl)
        emb = Embedding(g, excl, epochs=a.emb_epochs, bs=128, log=print) if a.emb_epochs else None
        for row in build(g, group, so, {t: fresh[t].get("day", fresh_day) for t in fresh}, emb):
            built[row[0]] = row
        kept = kept or emb  # the held-out fold's: trained without the radios it is graded on
        del so
        print(f"  features for {len(group)} seeds, {time.time() - t0:.0f}s", flush=True)
    T = [built[s] for s in train if built[s][2] is not None]
    X = np.concatenate([r[2] for r in T])
    y = np.concatenate([r[3] for r in T])
    model = lgb.LGBMRanker(objective="lambdarank", n_estimators=a.iters, learning_rate=0.05, num_leaves=63,
                           min_child_samples=50, lambdarank_truncation_level=64, verbose=-1)
    model.fit(X, y, group=[len(r[3]) for r in T])
    print(f"fit on {len(y)} rows, {time.time() - t0:.0f}s", flush=True)
    preds = {s: ([] if built[s][2] is None else pick(g, built[s][1], model.predict(built[s][2]), s))
             for s in test + val}

    def acc(group, truth):
        return float(np.mean([len(set(preds[s]) & truth(s)) / len(truth(s)) for s in group]))
    stored = lambda s: set(g.radio[s])
    print(f"val {acc(val, stored):.3f}  test (radio as stored) {acc(test, stored):.3f}")
    if a.fresh:
        ft = [s for s in test if s in fresh]
        fr = lambda s: set(fresh[s]["items"]) - {s}
        spot = float(np.mean([len(stored(s) & fr(s)) / len(fr(s)) for s in ft]))
        loc = acc(ft, fr)
        print(f"against the radio refetched later: local {loc:.3f}, Spotify's earlier radio {spot:.3f},"
              f" local/Spotify {loc / spot:.3f}")
        deg = lambda s: sum(1 for y, _ in g.inn.get(s, []) if y not in g.banned(s))
        for lo, hi in [(0, 3), (3, 10), (10, 20), (20, 40), (40, 80), (80, 10 ** 9)]:
            b = [s for s in ft if lo <= deg(s) < hi]
            if b:
                sb = float(np.mean([len(stored(s) & fr(s)) / len(fr(s)) for s in b]))
                print(f"  in {lo}-{hi} other radios: n={len(b)} local {acc(b, fr):.3f} Spotify {sb:.3f}")
    if a.out:
        with open(a.out, "wb") as f:
            pickle.dump({"model": model, "names": NAMES, "emb": kept}, f)
        json.dump(preds, open(os.path.splitext(a.out)[0] + "_preds.json", "w"))


if __name__ == "__main__":
    main()
