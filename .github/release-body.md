## Kotassium

One library, served from one place. Every client is a window onto
the same web app, so a fix lands everywhere at once.

### macOS

Download the DMG for your Mac and drag **Kotassium** into
**Applications**:

- `Kotassium-*-arm64.dmg` — Apple Silicon (M1 and later)
- `Kotassium-*-x86_64.dmg` — Intel

The app is **unsigned and not notarized**. On first launch macOS
will refuse to open it. Either right-click the app → **Open** →
**Open**, or run:

```sh
xattr -dr com.apple.quarantine /Applications/Kotassium.app
```

Once installed it checks this page on launch and updates itself:
a **Restart & Update** pill appears when a newer DMG is available,
verified against `SHA256SUMS`.

### Android

`Kotassium-*.apk` — open it on the phone and allow installing from
this source when prompted. With no server address baked in, the
first launch offers **This phone** (the app runs the library
itself; no other machine needed) or **Shared server**. Or just open
the library URL in Chrome and choose **Add to Home Screen** (the
same app, no download).

Android never updates an app installed from a file, so use
[Obtainium](https://github.com/ImranR98/Obtainium) to be told about
each release:
[add this repo](https://apps.obtainium.imranr.dev/redirect?r=obtainium://add/https://github.com/Heinrich-XIAO/kotassium).

### Server

macOS downloads need `ffmpeg` on the PATH (`brew install ffmpeg`);
`yt-dlp` is bundled inside the app. Library and state live in
`~/Music/Kotassium` on the machine running the server.
