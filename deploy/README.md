# Deploying the shared server

Kotassium is one server. The desktop app and the Android app are windows onto
it; the web page is the app. Nothing else needs deploying.

The machine that runs it holds the library (`~/Music/Kotassium` by default,
`KOTASSIUM_LIB` overrides it), so it needs to be on whenever someone wants to
listen, and it needs disk for the MP3s (~5 MB per track).

## 1. Password

```sh
mkdir -p ~/.config/kotassium
printf 'KOTASSIUM_PASSWORD=%s\n' "$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24)" \
  > ~/.config/kotassium/server.env
chmod 600 ~/.config/kotassium/server.env
```

Without `KOTASSIUM_PASSWORD` every route is open. With it, everything except
`/login`, `/api/health`, the manifest and the service worker needs a session
cookie. Five wrong passwords per IP per minute, then a one-minute lockout.

## 2. Service

```sh
cp deploy/kotassium-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kotassium-web.service
systemctl --user status kotassium-web.service
```

It binds `0.0.0.0:8421` by default. On a trusted LAN or a Tailscale tailnet
that is the whole story: `http://<machine>:8421` works from every device.

## 3a. Public URL with Tailscale Funnel (no domain needed)

```sh
sudo tailscale funnel 8421
```

That prints `https://<machine>.<tailnet>.ts.net`. Requirements:

- Funnel enabled for the tailnet (admin console → DNS/HTTPS certificates, and
  the Funnel toggle under Access controls).
- Root on the machine (the command above).

Funnel is public: anyone with the URL reaches the login page. The password is
what keeps it private. The hostname is stable as long as the machine name and
tailnet do.

## 3b. Public URL with Cloudflare Tunnel (needs a domain on Cloudflare)

```sh
cloudflared tunnel login                 # browser, picks the zone
cloudflared tunnel create kotassium
cloudflared tunnel route dns kotassium music.example.com
cloudflared tunnel run --token "$(cloudflared tunnel token kotassium)"
```

`cloudflared` runs unprivileged. Keep the token in
`~/.config/kotassium/tunnel.env` and a user unit similar to the one above. The
hostname is stable and does not need inbound ports.

## 4. Point the clients at it

- **Web / PWA** — open the URL; Chrome offers *Install app* / *Add to Home
  Screen*.
- **Android** — install `Kotassium-<version>.apk` and paste the URL on first
  launch (or bake it in: `-PkotassiumUrl=https://…`).
- **macOS** — `Kotassium.app` opens the baked URL if the build was made with
  `KOTASSIUM_URL=https://…`; otherwise
  `Kotassium.app/Contents/MacOS/Kotassium --remote https://…`.

## Notes

- `~/.config/kotassium/server.env` is the password; changing it invalidates
  every session (the cookie is an HMAC of the password and `webstate/auth.salt`).
- `~/Music/Kotassium` is the library and the state (`webstate/`). Back it up by
  copying it; nothing else in the repo matters.
- The Android keystore lives in GitHub Actions secrets
  (`ANDROID_KEYSTORE_B64`, `ANDROID_KEYSTORE_PASS`, `ANDROID_KEY_ALIAS`) and in
  `~/.config/kotassium/android.keystore`. Losing it means future APKs cannot
  install over the old ones.
