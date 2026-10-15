# kotassium-auth — Spotify token-exchange proxy (Vercel)

Holds the Spotify client secret server-side so it never ships in the
Android app. The phone captures the OAuth code via its loopback listener
and POSTs `{ code, code_verifier }` here; this service adds
`client_id` + `client_secret` and exchanges with Spotify.

## Env vars (Vercel dashboard → Settings → Environment Variables)

- `SPOTIFY_CLIENT_ID` — your Spotify app's client ID (public)
- `SPOTIFY_CLIENT_SECRET` — your Spotify app's client secret (**never commit**)

Apply to all environments and redeploy after setting.

## Deploy

New Vercel project from the `kotassium` repo with **Root Directory = `server/`**.
No build step needed (zero-dependency Node function).

## Endpoint

`POST /api/spot/exchange` with JSON `{ code, code_verifier }` →
`200 { access_token, token_type, expires_in, refresh_token, scope }`
on success, Spotify's error passthrough otherwise.

The redirect URI is pinned to `http://127.0.0.1:5588/callback` and must
match the authorize request and the dashboard whitelist exactly.

## Endpoint

`GET /api/spot/resolve?url=<spotify link>` → public playlist/album/track
as `{ type, name, tracks: [{t, a, ms}], count, truncated, partial }`.
No user login involved. Lanes: anonymous web-player token, then spotdl's
public app credentials, then the public embed page (first ~50 tracks,
`partial: true`) when the API lanes are throttled. Private content 404s.
