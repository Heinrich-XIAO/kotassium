// POST /api/spot/exchange  { code, code_verifier }
// Exchanges a Spotify PKCE authorization code for tokens, adding the
// client secret server-side so it never ships in the Android app.
// Env: SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET (never commit these).
// The redirect URI is pinned here and must match the authorize call
// and the dashboard whitelist exactly.
const REDIRECT_URI = "http://127.0.0.1:5588/callback";

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.status(405).json({ error: "method_not_allowed" });
    return;
  }
  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch (e) { body = {}; }
  }
  if (!body || typeof body !== "object") body = {};
  const code = typeof body.code === "string" ? body.code : "";
  const verifier = typeof body.code_verifier === "string" ? body.code_verifier : "";
  if (!code || !verifier || code.length > 2000 || verifier.length > 500) {
    res.status(400).json({ error: "invalid_request", error_description: "code and code_verifier required" });
    return;
  }
  const clientId = process.env.SPOTIFY_CLIENT_ID || "";
  const clientSecret = process.env.SPOTIFY_CLIENT_SECRET || "";
  if (!clientId || !clientSecret) {
    res.status(500).json({ error: "server_misconfigured", error_description: "Spotify credentials not set on server" });
    return;
  }
  const form = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: REDIRECT_URI,
    client_id: clientId,
    client_secret: clientSecret,
    code_verifier: verifier,
  });
  let r;
  try {
    r = await fetch("https://accounts.spotify.com/api/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    });
  } catch (e) {
    res.status(502).json({ error: "upstream_unreachable" });
    return;
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    res.status(r.status).json({
      error: data.error || "exchange_failed",
      error_description: data.error_description || "token exchange failed",
    });
    return;
  }
  res.status(200).json({
    access_token: data.access_token,
    token_type: data.token_type || "Bearer",
    expires_in: data.expires_in || 3600,
    refresh_token: data.refresh_token || "",
    scope: data.scope || "",
  });
};
