# Kotassium

Personal-use music player for Android. Everything runs on-device: search across
YouTube (playback), SoundCloud, Deezer and Internet Archive, an in-process
loopback server, Spotify account sign-in (OAuth PKCE, read-only), and passive
downloading — songs cache while you listen.

## Install

Grab `Kotassium-v4.apk` from [Releases](../../releases) and sideload it
(allow unknown apps). No Play Store, no Tailscale, no server.

## Build from source

Raw Android toolchain (no Gradle):

```
aapt2 compile --dir app/res -o res.zip
aapt2 link -o base.apk -I android.jar --manifest app/AndroidManifest.xml -A app/assets res.zip
java -jar ecj.jar -source 8 -target 8 -cp android.jar -d classes app/src/com/bobstevens/kotassium/*.java
d8 --release --lib android.jar --output . classes/com/bobstevens/kotassium/*.class
zip -j base.apk classes.dex
zipalign -f 4 base.apk aligned.apk
apksigner sign --ks keystore --out Kotassium.apk aligned.apk
```

## The engine (desktop)

The Python engine (`spotify_get.py`, `playerd.py`, `serve_pwa.py`,
`spotify_port.py`) is the desktop sibling: multi-source resolution with
duration-fingerprint matching, adaptive rate governor, headless token
harvesting, account porting. Included here for reference.

## Honest limitations

- YouTube *downloads* need the extractor lane (poToken wall) — YouTube tracks
  stream via the embed player instead. SoundCloud/Deezer/Archive tracks
  download fully.
- Deezer full-audio needs your own account cookie (`arl`).
- Personal use only.

