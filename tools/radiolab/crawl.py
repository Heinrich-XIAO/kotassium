"""Crawl Spotify radios into the app's radio store (serve_web.RADIO_DB).

The app records every radio a listener plays into the same database, so a
crawl and real listening build one dataset. Seeds come from genre roots,
then from tracks the stored radios recommend but nobody has crawled yet:
half the most-recommended (dense overlap to learn from), half at random
(coverage outside the roots' neighbourhoods).

  venv/bin/python tools/radiolab/crawl.py --max 5000 [--workers 3] [--db PATH] [--shard 1/2]
"""
import argparse, os, random, sys, threading, time, urllib.error, zlib
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import spotify_get as sg

ROOTS = ["Blinding Lights The Weeknd", "Jolene Dolly Parton", "Dynamite BTS", "Strobe deadmau5",
         "Despacito Luis Fonsi", "Do I Wanna Know Arctic Monkeys", "An Ending Ascent Brian Eno",
         "Kesariya Arijit Singh", "Lose Yourself Eminem", "Bohemian Rhapsody Queen", "Take Five Dave Brubeck",
         "Clair de Lune Debussy", "Master of Puppets Metallica", "Megalovania Toby Fox", "Redbone Childish Gambino",
         "Basket Case Green Day", "Three Little Birds Bob Marley", "Essence Wizkid", "Skinny Love Bon Iver",
         "The Thrill Is Gone B.B. King", "Superstition Stevie Wonder", "Plastic Love Mariya Takeuchi",
         "Gurenge LiSA", "Snowman lofi", "Windowlicker Aphex Twin", "One More Time Daft Punk",
         "Tarantula Pendulum", "Oceans Hillsong United", "Nessun dorma Pavarotti", "Time Hans Zimmer",
         "Baby Shark Pinkfong", "Enta Omri Umm Kulthum", "Mojito Jay Chou", "Alors on danse Stromae",
         "Atemlos durch die Nacht Helene Fischer", "Tití Me Preguntó Bad Bunny", "Water Tyla",
         "Mayonaka no Door Miki Matsubara", "Welcome to the Black Parade My Chemical Romance",
         "Only Shallow My Bloody Valentine", "Smells Like Teen Spirit Nirvana", "Mask Off Future",
         "Stayin' Alive Bee Gees", "Nightcall Kavinsky", "Senbonzakura Hatsune Miku", "Hurt Johnny Cash",
         "Vivir Mi Vida Marc Anthony", "Ella Baila Sola Eslabon Armado", "Calm Down Rema", "Pink Venom BLACKPINK"]

FAIL = "CREATE TABLE IF NOT EXISTS crawl_fail (seed TEXT PRIMARY KEY, error TEXT, at REAL)"


def frontier(db, n, rng, shard=(0, 1)):
    """Uncrawled tracks the stored radios recommend, ranked by how often.
    With shard (k, n) only every n-th track by hash, so n crawlers split the work."""
    rows = db.execute("SELECT i.track, COUNT(*) c FROM radio_item i WHERE i.track NOT IN (SELECT seed FROM radio)"
                      " AND i.track NOT IN (SELECT seed FROM crawl_fail) GROUP BY i.track ORDER BY c DESC").fetchall()
    rows = [r for r in rows if zlib.crc32(r[0].encode()) % shard[1] == shard[0]]
    dense = [t for t, _ in rows[: n // 2]]
    rest = [t for t, _ in rows[n // 2:]]
    return dense + rng.sample(rest, min(len(rest), n - len(dense)))


def fetch(prov, seed):
    for i in range(6):
        try:
            return sg.fetch_radio(prov, seed), None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(30 * (i + 1))
                continue
            if e.code in (400, 404):
                return None, f"http {e.code}"
            time.sleep(5)
        except Exception as e:
            err = str(e)[:200]
            if "no radio" in err:
                return None, err
            time.sleep(5)
    return None, "gave up after retries"


def main():
    from serve_web import RADIO_DB
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=RADIO_DB)
    ap.add_argument("--max", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--shard", default="0/1", help="k/n: crawl only this share of the frontier")
    a = ap.parse_args()
    shard = tuple(int(x) for x in a.shard.split("/"))
    db = sg.radio_db(a.db)
    db.execute(FAIL)
    prov, rng, lock = sg.TokenProvider(), random.Random(a.seed), threading.Lock()
    done = [0]

    def one(seed):
        rec, err = fetch(prov, seed)
        with lock:
            if rec and len(rec["items"]):
                sg.record_radio(db, rec, "crawl")
                done[0] += 1
            else:
                with db:
                    db.execute("INSERT OR REPLACE INTO crawl_fail VALUES (?,?,?)", (seed, err or "empty", time.time()))

    have = {s for (s,) in db.execute("SELECT seed FROM radio")}
    roots = []
    for q in ROOTS:
        try:
            hit = sg.spotify_search(prov, q, 1)
            if hit and hit[0]["uri"] not in have:
                roots.append(hit[0]["uri"])
        except Exception as e:
            print("root search failed", q, e, flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, roots))
        while done[0] < a.max:
            with lock:
                batch = frontier(db, min(60, a.max - done[0]), rng, shard)
            if not batch:
                break
            list(ex.map(one, batch))
            n_r, n_t = db.execute("SELECT (SELECT COUNT(*) FROM radio), (SELECT COUNT(*) FROM track)").fetchone()
            print(f"{time.strftime('%H:%M:%S')} +{done[0]} this run, {n_r} radios, {n_t} tracks,"
                  f" {done[0] / max(1, time.time() - t0) * 3600:.0f}/h", flush=True)


if __name__ == "__main__":
    main()
