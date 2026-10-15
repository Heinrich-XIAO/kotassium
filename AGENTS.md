# Kotassium — agent conventions

## Release policy

**Always release on changes.** Every change that touches app behavior —
however small (a fix, a tweak, a lane adjustment) — gets a tagged GitHub
Release with a fresh signed APK before the work is considered done.
Never let the release page lag behind the source.

- Tag: `vMAJOR.MINOR.PATCH` (bump patch on fixes, minor on features)
- Build: the no-Gradle recipe in README.md (aapt2 → ecj → d8 → zipalign → apksigner)
- Verify the dex is fresh in the APK before uploading (unzip -p | check class age);
  a stale dex ships a broken app silently
- `gh release create vX.Y.Z build/Kotassium-*.apk --clobber` on re-uploads
- In the final response, always link the newest release and verify it is live
  first (`gh api repos/:owner/:repo/releases/latest`) — never link a release
  you have not confirmed exists

## Stack notes

- APK: WebView + in-process loopback server (127.0.0.1:8421) — no external server
- Sources: YouTube (innertube search + embed playback), Deezer (open API),
  SoundCloud (runtime client_id harvest), Internet Archive
- Spotify account: OAuth PKCE on-device, read-only scopes, tokens stay local
- Known wall: YouTube downloads (poToken/nsig) — playback via embed instead
