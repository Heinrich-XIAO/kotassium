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

If anything sits in front of the server, also set `KOTASSIUM_HOSTS` to the
name it is reached by (see section 3); without it the host guard refuses the
forwarded `Host` header.

## 2. Service

```sh
cp deploy/kotassium-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kotassium-web.service
systemctl --user status kotassium-web.service
```

It binds `0.0.0.0:8421` by default. On a trusted LAN or a Tailscale tailnet
that is the whole story: `http://<machine>:8421` works from every device.

## 3. Reaching it from outside the house

Any proxy in front of the server needs its hostname in `KOTASSIUM_HOSTS`, or
the DNS-rebinding guard answers 403:

```sh
echo 'KOTASSIUM_HOSTS=fedora-1.tail8e937f.ts.net' >> ~/.config/kotassium/server.env
systemctl --user restart kotassium-web.service
```

### a. Tailscale Serve — tailnet only (nothing is public)

```sh
sudo tailscale serve --bg 8421
```

Gives `https://<machine>.<tailnet>.ts.net`: real HTTPS certificate, reachable
**only** from devices in your tailnet. No port is opened and nothing is
published to the internet. Needs HTTPS certificates enabled in the admin
console (DNS page) — that is a certificate switch, not an exposure switch.

Family members get in either by accepting a tailnet invite, or by having this
one node shared with them (admin console → Machines → Share), so they never
see your other devices.

Off again with `sudo tailscale serve --https=443 off`.

### b. Tailscale Funnel — public URL, one port only

```sh
sudo tailscale funnel --bg 8421
```

Same hostname, published to the internet. Funnel exposes exactly one port on
one machine — not the tailnet, not other services — and is reversible with
`sudo tailscale funnel --https=443 off`. Requires the Funnel toggle under
Access controls. Anyone with the URL reaches the login page; the password is
the only gate.

### c. Cloudflare Tunnel + Access — public URL behind an identity gate

```sh
cloudflared tunnel login                 # browser, picks the zone
cloudflared tunnel create kotassium
cloudflared tunnel route dns kotassium music.example.com
cloudflared tunnel run --token "$(cloudflared tunnel token kotassium)"
```

`cloudflared` runs unprivileged; keep the token in
`~/.config/kotassium/tunnel.env` and a user unit like the one above. Add a
Cloudflare Access policy (email one-time PIN, listed addresses) so the app is
not reachable by anyone who stumbles on the hostname — then the password is a
second lock instead of the only one.

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
