"""Glue between the Android shell and serve_web.

The shell cannot set environment variables in the app process, so it passes
the two paths here and this module configures serve_web *before* importing it
(serve_web reads its paths at import time). There is no UI and no second
implementation here: it starts the same server the desktop runs.
"""
import os


def start(base, lib, port):
    os.environ["KOTASSIUM_BASE"] = base
    os.environ["KOTASSIUM_LIB"] = lib
    # Android cannot exec a yt-dlp binary and has no ffmpeg, so the download
    # runs in-process and keeps yt-dlp's own container (usually m4a).
    os.environ["KOTASSIUM_YTDLP"] = "inproc"
    import serve_web
    # Downloads run in this process, so Android freezes them with the screen
    # off. ServeService holds a wake lock while one runs; this hook is the
    # on/off switch. It is a no-op until the service is up (it never fails).
    from app.kotassium.mobile import ServeService
    serve_web.JOB_HOOK = ServeService.setBusy
    return serve_web.serve_local(int(port))
