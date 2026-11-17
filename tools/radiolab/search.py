"""Radio for any audio file by vector search, with the model train.py saved.

The file's 30 s from 30% in is embedded like a preview, the query tower maps
it to a song vector, and the 49 nearest catalogue tracks (at most five per
artist, as Spotify's radio allows) are the radio.

  radiolab-venv/bin/python tools/radiolab/search.py ~/Music/Kotassium/song.mp3 [-n 49]
"""
import argparse, json, os, sqlite3, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import audio as A
from train import ARTIST_CAP


def load_model(path=os.path.join(A.LAB, "model.npz")):
    m = np.load(path)
    return {k: m[k] for k in m.files}


def song_vector(m, feat):
    x = ((feat - m["mu"]) / m["sd"]) @ m["P"]
    return np.maximum(0, x @ m["W1"] + m["b1"]) @ m["W2"]


def radio(m, feat, meta, n=49, exclude=()):
    scores = m["vecs"] @ song_vector(m, feat) + m["bias"]
    out, per = [], {}
    for i in np.argsort(-scores):
        u = str(m["uris"][i])
        artist = (meta.get(u, ("", [[None, ""]]))[1] or [[None, ""]])[0][0]
        if u in exclude or per.get(artist, 0) >= ARTIST_CAP:
            continue
        per[artist] = per.get(artist, 0) + 1
        out.append((u, float(scores[i])))
        if len(out) == n:
            break
    return out


def main():
    from serve_web import RADIO_DB
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("-n", type=int, default=49)
    a = ap.parse_args()
    m, emb = load_model(), A.Embedder()
    meta = {u: (n, json.loads(ar or "[]")) for u, n, ar in sqlite3.connect(RADIO_DB).execute(
        "SELECT uri, name, artists FROM track")}
    for f in a.files:
        v = A.embed_file(emb, f)
        feat = np.concatenate([v["effnet"], v["similar"], v["styles"]]).astype(np.float32)
        print(f"\n{os.path.basename(f)}")
        for k, (u, sc) in enumerate(radio(m, feat, meta, a.n), 1):
            name, artists = meta.get(u, (u, []))
            print(f"{k:3}. {name} - {', '.join(x for _, x in artists)}   ({sc:.2f})")


if __name__ == "__main__":
    main()
