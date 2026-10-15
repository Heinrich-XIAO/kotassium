"""Downloads a YouTube video's audio to an m4a file using yt-dlp (runs on-device via Chaquopy)."""
import os


def fetch(video_id, out_dir):
    """Download bestaudio for video_id into out_dir. Returns the file name (not path)."""
    import yt_dlp
    if not video_id or not all(c.isalnum() or c in "-_" for c in video_id) or len(video_id) > 20:
        raise ValueError("bad video id")
    os.makedirs(out_dir, exist_ok=True)
    final = os.path.join(out_dir, "yt_" + video_id + ".m4a")
    if os.path.exists(final) and os.path.getsize(final) > 10000:
        return os.path.basename(final)
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": os.path.join(out_dir, "yt_" + video_id + ".%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download(["https://www.youtube.com/watch?v=" + video_id])
    if not os.path.exists(final) or os.path.getsize(final) < 10000:
        raise RuntimeError("download produced no audio")
    return os.path.basename(final)
