#!/usr/bin/env python3
"""playerd.py - resident music daemon: play <query> | queue <query> | next | stop
Instant for cached songs, ~2-4s cold, prefetches the queue while the current song plays."""
import json, os, re, socket, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spotify_get import (norm, spotify_search, search_and_pick, TokenProvider,
                         YTDLP, GOV, log)

HOST, PORT = "127.0.0.1", 6606
LIB = os.path.expanduser("~/Music/searches")
os.makedirs(LIB, exist_ok=True)
STATE = {"player_pid": None, "queue": [], "lock": threading.Lock(),
         "current": None, "provider": None}

def cached_file(artist, title):
    key = norm(f"{artist} {title}")
    for f in os.listdir(LIB):
        if norm(f.rsplit(".", 1)[0]) == key:
            return os.path.join(LIB, f)
    return None

def bg_cache(vid, artist, title, album):
    name = re.sub(r'[/\\:*?"<>|]', "", f"{artist} - {title}").strip()
    out = os.path.join(LIB, name + ".mp3")
    if os.path.exists(out):
        return
    tmp = os.path.join(LIB, f".bg_{vid}.%(ext)s")
    try:
        subprocess.run([YTDLP, "-f", "bestaudio[ext=m4a]/bestaudio", "--no-playlist",
                        "--quiet", "--no-warnings", "-o", tmp,
                        f"https://www.youtube.com/watch?v={vid}"], timeout=240,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for f in os.listdir(LIB):
            if f.startswith(f".bg_{vid}."):
                src = os.path.join(LIB, f)
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-codec:a", "libmp3lame",
                                "-b:a", "192k", "-metadata", f"title={title}",
                                "-metadata", f"artist={artist}", "-metadata", f"album={album or ''}",
                                out], timeout=120)
                os.remove(src)
                log(f"cached: {name}")
    except Exception as e:
        log(f"bg cache failed: {e}")

def kill_player():
    pid = STATE["player_pid"]
    if pid:
        try: os.kill(pid, 15)
        except Exception: pass
    STATE["player_pid"] = None

def _start_player(path, artist, title):
    kill_player()
    p = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    STATE["player_pid"] = p.pid
    STATE["current"] = f"{artist} - {title}"
    threading.Timer(0.4, _maybe_prefetch_next).start()

def _play_job(artist, title, dur, album):
    path = cached_file(artist, title)
    t0 = time.time()
    if path:
        log(f"instant from cache: {artist} - {title}")
        _start_player(path, artist, title)
        return
    ladder = search_and_pick(artist, title, dur)
    if not ladder:
        log(f"no match: {artist} - {title}"); return
    vid, _ = ladder[0]
    r = subprocess.run([YTDLP, "--get-url", "-f", "bestaudio[ext=m4a]/bestaudio",
                        "--no-playlist", "--quiet", "--no-warnings",
                        f"https://www.youtube.com/watch?v={vid}"],
                       capture_output=True, text=True, timeout=60)
    url = (r.stdout or "").strip().splitlines()[0] if r.stdout else ""
    if not url:
        log(f"no stream url for {artist} - {title}"); return
    kill_player()
    p = subprocess.Popen(["ffplay", "-nodisp", "-loglevel", "quiet", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    STATE["player_pid"] = p.pid
    STATE["current"] = f"{artist} - {title}"
    log(f"streaming {artist} - {title} (sound at {time.time()-t0:.1f}s)")
    threading.Thread(target=bg_cache, args=(vid, artist, title, album), daemon=True).start()
    threading.Timer(0.4, _maybe_prefetch_next).start()

def _maybe_prefetch_next():
    with STATE["lock"]:
        if STATE["queue"]:
            artist, title, dur, album = STATE["queue"][0]
            if not cached_file(artist, title):
                ladder = search_and_pick(artist, title, dur)
                if ladder:
                    vid, _ = ladder[0]
                    threading.Thread(target=bg_cache, args=(vid, artist, title, album),
                                     daemon=True).start()
                    log(f"prefetching next: {artist} - {title}")

def _queue_job(artist, title, dur, album):
    path = cached_file(artist, title)
    if not path:
        ladder = search_and_pick(artist, title, dur)
        if ladder:
            vid, _ = ladder[0]
            threading.Thread(target=bg_cache, args=(vid, artist, title, album), daemon=True).start()
            log(f"queued + prefetching: {artist} - {title}")
            return
    log(f"queued (already cached): {artist} - {title}")

def handle(cmd, arg):
    provider = STATE["provider"]
    if cmd == "stop":
        kill_player()
        STATE["queue"] = []
        STATE["current"] = None
        return "stopped"
    if cmd == "next":
        with STATE["lock"]:
            if STATE["queue"]:
                artist, title, dur, album = STATE["queue"].pop(0)
            else:
                return "queue empty"
    elif cmd in ("play", "queue"):
        cands = spotify_search(provider, arg)
        if not cands:
            return f"no spotify results: {arg}"
        chosen = cands[0]
        if cmd == "next":
            with STATE["lock"]:
                STATE["queue"].insert(0, (chosen["artist"], chosen["title"], chosen["dur"], chosen["album"]))
            artist, title, dur, album = chosen["artist"], chosen["title"], chosen["dur"], chosen["album"]
        elif cmd == "queue":
            with STATE["lock"]:
                STATE["queue"].append((chosen["artist"], chosen["title"], chosen["dur"], chosen["album"]))
            threading.Thread(target=_queue_job, args=(chosen["artist"], chosen["title"],
                                                      chosen["dur"], chosen["album"]), daemon=True).start()
            return f"queued: {chosen['artist']} - {chosen['title']}"
        else:  # play
            threading.Thread(target=_play_job, args=(chosen["artist"], chosen["title"],
                                                     chosen["dur"], chosen["album"]), daemon=True).start()
            return f"playing: {chosen['artist']} - {chosen['title']}"
    else:
        return f"unknown cmd {cmd}"
    threading.Thread(target=_play_job, args=(artist, title, dur, album), daemon=True).start()
    return f"next -> {artist} - {title}"

def serve():
    STATE["provider"] = TokenProvider()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT)); srv.listen(8)
    log(f"daemon on {HOST}:{PORT}")
    while True:
        conn, _ = srv.accept()
        try:
            data = conn.recv(4096).decode().strip()
            cmd, _, arg = data.partition(" ")
            resp = handle(cmd, arg.strip())
        except Exception as e:
            resp = f"error: {e}"
        conn.sendall((resp + "\n").encode())
        conn.close()

def client(cmd, arg):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(30)
    s.connect((HOST, PORT))
    s.sendall(f"{cmd} {arg}".encode())
    print(s.recv(65536).decode().strip())
    s.close()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        serve()
    elif len(sys.argv) > 1:
        client(sys.argv[1], " ".join(sys.argv[2:]))
    else:
        print("usage: playerd.py serve | play|queue|next|stop [query]")
