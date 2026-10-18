package com.bobstevens.kotassium;

import android.content.Context;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import android.content.Intent;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URL;
import java.net.URLEncoder;
import java.net.URLDecoder;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Fully on-device backend: loopback-only HTTP server (127.0.0.1) + all source lanes. */
public class Loop {
    static final String UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36";
    static String scCid = "";
    static final Map<String, String> CACHE = new ConcurrentHashMap<>();
    static File libDir;
    static File coverDir;
    static File coverMapFile;
    ServerSocket server;
    ServerSocket oauthServer;

    // ---- self-update (checks/downloads via the Vercel proxy, installs via PackageInstaller) ----
    static final String UPDATE_BASE = "https://kotassium-auth.vercel.app";
    static volatile String updateStatus = "";
    static android.content.Context appCtx;

    static String currentVersion() {
        try { return appCtx.getPackageManager().getPackageInfo(appCtx.getPackageName(), 0).versionName; }
        catch (Exception e) { return "0"; }
    }

    static boolean newerVersion(String a, String b) {
        String[] x = a.split("\\."), y = b.split("\\.");
        for (int i = 0; i < Math.max(x.length, y.length); i++) {
            int p = i < x.length ? parseIntSafe(x[i]) : 0;
            int q = i < y.length ? parseIntSafe(y[i]) : 0;
            if (p != q) return p > q;
        }
        return false;
    }

    static int parseIntSafe(String s) {
        try { return Integer.parseInt(s.replaceAll("[^0-9]", "")); } catch (Exception e) { return 0; }
    }

    static void downloadTo(String url, File f) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000); c.setReadTimeout(60000);
        c.setInstanceFollowRedirects(true);
        c.setRequestProperty("User-Agent", UA);
        if (c.getResponseCode() >= 400) throw new Exception("download http " + c.getResponseCode());
        FileOutputStream o = new FileOutputStream(f);
        InputStream in = c.getInputStream();
        byte[] buf = new byte[65536]; int n;
        while ((n = in.read(buf)) > 0) o.write(buf, 0, n);
        in.close(); o.close();
        if (f.length() < 10000) throw new Exception("download too small (" + f.length() + " bytes)");
    }

    static int fetchSongCount(String link) {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(link).openConnection();
            c.setRequestMethod("GET");
            c.setInstanceFollowRedirects(true);
            c.setConnectTimeout(15000); c.setReadTimeout(30000);
            c.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36");
            int sc = c.getResponseCode();
            InputStream in = sc >= 400 ? c.getErrorStream() : c.getInputStream();
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            if (in != null) { byte[] buf = new byte[65536]; int n; while ((n = in.read(buf)) > 0) b.write(buf, 0, n); in.close(); }
            String h = b.toString("UTF-8");
            Matcher m = Pattern.compile("<meta name=\"music:song_count\" content=\"(\\d+)\"").matcher(h);
            if (m.find()) return Integer.parseInt(m.group(1));
        } catch (Exception e) {
        }
        return -1;
    }

    static File linksFile() {
        return new File(libDir.getParentFile(), "links.json");
    }

    static synchronized JSONArray readLinks() {
        try {
            File f = linksFile();
            if (f.exists()) return new JSONArray(new String(fileBytes(f), "UTF-8"));
        } catch (Exception ignored) {}
        return new JSONArray();
    }

    static synchronized void writeLinks(JSONArray a) {
        try {
            FileOutputStream o = new FileOutputStream(linksFile());
            o.write(a.toString().getBytes("UTF-8")); o.close();
        } catch (Exception ignored) {}
    }

    // Saved links: url -> resolved track list. Cap 50 entries, newest first.
    static synchronized void saveLink(String url, JSONObject resolved) {
        try {
            JSONArray all = readLinks();
            JSONArray next = new JSONArray();
            JSONObject e = new JSONObject();
            e.put("url", url);
            e.put("name", resolved.optString("name", url));
            e.put("count", resolved.optJSONArray("tracks") == null ? 0 : resolved.optJSONArray("tracks").length());
            if (!resolved.isNull("total")) e.put("total", resolved.optInt("total"));
            e.put("partial", resolved.optBoolean("partial", false));
            e.put("tracks", resolved.optJSONArray("tracks") == null ? new JSONArray() : resolved.optJSONArray("tracks"));
            e.put("ts", System.currentTimeMillis());
            next.put(e);
            for (int i = 0; i < all.length() && next.length() < 50; i++) {
                if (!url.equals(all.getJSONObject(i).optString("url"))) next.put(all.getJSONObject(i));
            }
            writeLinks(next);
        } catch (Exception ignored) {}
    }

    static synchronized JSONObject findLink(String url) {
        if (url == null) return null;
        JSONArray all = readLinks();
        for (int i = 0; i < all.length(); i++) {
            try {
                if (url.equals(all.getJSONObject(i).optString("url"))) return all.getJSONObject(i);
            } catch (Exception ignored) {}
        }
        return null;
    }

    static synchronized void dropLink(String url) {
        JSONArray all = readLinks();
        JSONArray next = new JSONArray();
        for (int i = 0; i < all.length(); i++) {
            try {
                if (!url.equals(all.getJSONObject(i).optString("url"))) next.put(all.getJSONObject(i));
            } catch (Exception ignored) {}
        }
        writeLinks(next);
    }

    public Loop(Context ctx) throws Exception {
        appCtx = ctx.getApplicationContext();
        if (!Python.isStarted()) Python.start(new AndroidPlatform(appCtx));
        libDir = new File(ctx.getExternalFilesDir(null), "Music");
        if (!libDir.exists()) libDir.mkdirs();
        coverDir = new File(ctx.getExternalFilesDir(null), "covers");
        if (!coverDir.exists()) coverDir.mkdirs();
        coverMapFile = new File(ctx.getExternalFilesDir(null), "covers.json");
        server = new ServerSocket(8421, 64, InetAddress.getByName("127.0.0.1"));
        Thread t = new Thread(() -> {
            while (true) {
                try {
                    final Socket s = server.accept();
                    new Thread(() -> handle(s)).start();
                } catch (Exception ignored) {}
            }
        });
        t.setDaemon(true);
        t.start();
        // OAuth callback listener on the Spotify-registered loopback URI port.
        // The system browser (which shares the device Google session) redirects
        // here after login; the WebView page polls /api/spot/code to finish.
        oauthServer = new ServerSocket(5588, 16, InetAddress.getByName("127.0.0.1"));
        Thread o = new Thread(() -> {
            while (true) {
                try {
                    final Socket s = oauthServer.accept();
                    new Thread(() -> handle(s)).start();
                } catch (Exception ignored) {}
            }
        });
        o.setDaemon(true);
        o.start();
    }

    static String http(String url, String method, String body) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestMethod(method);
        c.setInstanceFollowRedirects(false);
        c.setRequestProperty("User-Agent", UA);
        c.setConnectTimeout(15000); c.setReadTimeout(30000);
        if (body != null && !body.isEmpty()) {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            c.getOutputStream().write(body.getBytes("UTF-8"));
        }
        int code = c.getResponseCode();
        String loc = c.getHeaderField("Location");
        if ((code == 301 || code == 302) && loc != null) return http(loc, "GET", null);
        InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        if (in != null) { byte[] buf = new byte[8192]; int n; while ((n = in.read(buf)) > 0) b.write(buf, 0, n); in.close(); }
        return code + "\n" + b.toString("UTF-8");
    }

    // ---- lanes ----

    static String deezerSearch(String q) throws Exception {
        String r = http("https://api.deezer.com/search?q=" + URLEncoder.encode(q, "UTF-8") + "&limit=8", "GET", null);
        JSONObject d = new JSONObject(body(r));
        JSONArray out = new JSONArray();
        JSONArray data = d.optJSONArray("data");
        if (data != null) for (int i = 0; i < data.length(); i++) {
            JSONObject t = data.getJSONObject(i);
            JSONObject o = new JSONObject();
            o.put("source", "deezer"); o.put("title", t.optString("title"));
            o.put("artist", t.optJSONObject("artist") == null ? "" : t.optJSONObject("artist").optString("name"));
            o.put("dur", t.optInt("duration")); o.put("id", String.valueOf(t.optLong("id")));
            o.put("preview", t.optString("preview")); o.put("full", false);
            JSONObject alb = t.optJSONObject("album");
            if (alb != null) o.put("cover", coverLocal(alb.optString("cover")));
            out.put(o);
        }
        return out.toString();
    }

    static String iaSearch(String q) throws Exception {
        String r = http("https://archive.org/advancedsearch.php?q=" + URLEncoder.encode(q + " AND mediatype:audio", "UTF-8")
                + "&fl%5B%5D=identifier&fl%5B%5D=title&rows=8&output=json", "GET", null);
        JSONArray docs = new JSONObject(body(r)).getJSONObject("response").optJSONArray("docs");
        JSONArray out = new JSONArray();
        if (docs != null) for (int i = 0; i < docs.length(); i++) {
            JSONObject o = new JSONObject();
            o.put("source", "archive");
            o.put("title", docs.getJSONObject(i).optString("title", docs.getJSONObject(i).optString("identifier")));
            o.put("artist", ""); o.put("dur", 0);
            o.put("id", docs.getJSONObject(i).optString("identifier")); o.put("full", true);
            out.put(o);
        }
        return out.toString();
    }

    static synchronized String scCid() throws Exception {
        if (scCid.length() > 20) return scCid;
        String home = body(http("https://soundcloud.com/", "GET", null));
        Matcher m = Pattern.compile("https://a-v2\\.sndcdn\\.com/assets/[^\"]+\\.js").matcher(home);
        List<String> chunks = new ArrayList<>();
        while (m.find()) chunks.add(m.group());
        for (String u : chunks) {
            String js = body(http(u, "GET", null));
            Matcher c = Pattern.compile("client_id:\"([a-zA-Z0-9]{28,40})\"").matcher(js);
            if (c.find()) { scCid = c.group(1); return scCid; }
        }
        throw new Exception("no soundcloud client_id");
    }

    static String scSearch(String q) throws Exception {
        String r = http("https://api-v2.soundcloud.com/search/tracks?q=" + URLEncoder.encode(q, "UTF-8")
                + "&client_id=" + scCid() + "&limit=8", "GET", null);
        JSONArray col = new JSONObject(body(r)).optJSONArray("collection");
        JSONArray out = new JSONArray();
        if (col != null) for (int i = 0; i < col.length(); i++) {
            JSONObject t = col.getJSONObject(i);
            JSONObject o = new JSONObject();
            o.put("source", "soundcloud"); o.put("title", t.optString("title"));
            o.put("artist", t.optJSONObject("user") == null ? "" : t.optJSONObject("user").optString("username"));
            o.put("dur", t.optInt("duration") / 1000);
            o.put("id", String.valueOf(t.optLong("id"))); o.put("full", true);
            out.put(o);
        }
        return out.toString();
    }

    static String scResolve(String id) throws Exception {
        String r = http("https://api-v2.soundcloud.com/tracks/" + id + "?client_id=" + scCid(), "GET", null);
        JSONObject t = new JSONObject(body(r));
        JSONObject media = t.optJSONObject("media");
        JSONArray trans = media == null ? null : media.optJSONArray("transcodings");
        if (trans == null) throw new Exception("no transcodings (DRM?)");
        for (int i = 0; i < trans.length(); i++) {
            JSONObject tr = trans.getJSONObject(i);
            if (tr.optString("format", "").contains("progressive")) {
                String u = tr.optString("url") + "&client_id=" + scCid();
                return new JSONObject(body(http(u, "GET", null))).optString("url");
            }
        }
        throw new Exception("hls only (unsupported)");
    }

    static String ytSearch(String q) throws Exception {
        String body = "{\"context\":{\"client\":{\"clientName\":\"WEB\",\"clientVersion\":\"2.20241126.01.00\",\"hl\":\"en\",\"gl\":\"US\"}},\"query\":"
                + JSONObject.quote(q) + "}";
        JSONObject d = new JSONObject(body(http(
                "https://www.youtube.com/youtubei/v1/search?prettyPrint=false", "POST", body)));
        JSONArray out = new JSONArray();
        List<JSONObject> vids = new ArrayList<>();
        collectVids(d, vids);
        for (JSONObject v : vids) {
            JSONObject o = new JSONObject();
            try {
                o.put("source", "youtube");
                o.put("title", v.optJSONObject("title").optJSONArray("runs").optJSONObject(0).optString("text"));
                o.put("artist", v.optJSONObject("ownerText") == null ? "" :
                        v.optJSONObject("ownerText").optJSONArray("runs").optJSONObject(0).optString("text"));
                o.put("dur", 0); o.put("id", v.optString("videoId")); o.put("full", false);
                out.put(o);
            } catch (Exception ignored) {}
        }
        return out.toString();
    }

    static void collectVids(Object o, List<JSONObject> acc) {
        if (o instanceof JSONObject) {
            JSONObject j = (JSONObject) o;
            if (j.has("videoRenderer")) { try { acc.add(j.getJSONObject("videoRenderer")); } catch (Exception ignored) {} }
            java.util.Iterator<String> ks = j.keys();
            while (ks.hasNext()) collectVids(j.opt(ks.next()), acc);
        } else if (o instanceof JSONArray) {
            JSONArray a = (JSONArray) o;
            for (int i = 0; i < a.length(); i++) collectVids(a.opt(i), acc);
        }
    }

    static String body(String r) { return r.substring(r.indexOf('\n') + 1); }

    static String norm(String s) {
        StringBuilder b = new StringBuilder();
        for (char c : s.toLowerCase().toCharArray())
            if (Character.isLetterOrDigit(c)) b.append(c);
            else if (b.length() > 0 && b.charAt(b.length() - 1) != ' ') b.append(' ');
        return b.toString().trim();
    }

    static byte[] fileBytes(File f) throws Exception {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        FileInputStream in = new FileInputStream(f);
        byte[] buf = new byte[65536]; int n;
        while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
        in.close();
        return b.toByteArray();
    }

    static File dlFile(String src, String id, String url) throws Exception {
        File f = new File(libDir, src + "_" + id + ".mp3");
        if (f.exists() && f.length() > 10000) return f;
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestProperty("User-Agent", UA);
        c.setInstanceFollowRedirects(true);
        FileOutputStream o = new FileOutputStream(f);
        InputStream in = c.getInputStream();
        byte[] buf = new byte[65536]; int n;
        while ((n = in.read(buf)) > 0) o.write(buf, 0, n);
        in.close(); o.close();
        return f;
    }


    // ---- spotify account (on-device oauth, pkce, no secret) ----
    static String spVerifier = "";
    static volatile String spCode = "";
    static String spAccess = "", spRefresh = "";
    static final String SP_CID = "a002af185506487cacb11899ea371376";
    static final String SP_REDIRECT = "http://127.0.0.1:5588/callback";
    static String spCid = SP_CID;

    static boolean validCid(String cid) {
        return cid != null && cid.matches("[A-Za-z0-9]{16,64}");
    }

    static String cidFile() {
        return new File(libDir.getParentFile(), "spotify_client_id.txt").getAbsolutePath();
    }

    static synchronized String activeCid() {
        if (validCid(spCid) && !spCid.equals(SP_CID)) return spCid;
        try {
            File f = new File(cidFile());
            if (f.exists()) {
                byte[] b = fileBytes(f);
                String s = new String(b, "UTF-8").trim();
                if (validCid(s)) { spCid = s; return spCid; }
            }
        } catch (Exception ignored) {}
        return SP_CID;
    }

    static synchronized void setCid(String cid) {
        if (!validCid(cid)) return;
        spCid = cid;
        try {
            FileOutputStream o = new FileOutputStream(cidFile());
            o.write(cid.getBytes("UTF-8")); o.close();
        } catch (Exception ignored) {}
    }

    static String spotAuthUrl(String cid) throws Exception {
        byte[] rnd = new byte[48];
        new java.security.SecureRandom().nextBytes(rnd);
        spVerifier = android.util.Base64.encodeToString(rnd, android.util.Base64.URL_SAFE | android.util.Base64.NO_WRAP | android.util.Base64.NO_PADDING);
        String challenge = android.util.Base64.encodeToString(
                java.security.MessageDigest.getInstance("SHA-256").digest(spVerifier.getBytes("UTF-8")),
                android.util.Base64.URL_SAFE | android.util.Base64.NO_WRAP | android.util.Base64.NO_PADDING);
        String state = android.util.Base64.encodeToString(rnd, android.util.Base64.URL_SAFE).substring(0, 16);
        spCode = "";
        if (validCid(cid)) setCid(cid);
        String useCid = activeCid();
        return "https://accounts.spotify.com/authorize?response_type=code&client_id=" + useCid
                + "&redirect_uri=" + URLEncoder.encode(SP_REDIRECT, "UTF-8")
                + "&scope=" + URLEncoder.encode("user-library-read playlist-read-private playlist-read-collaborative", "UTF-8")
                + "&code_challenge=" + challenge + "&code_challenge_method=S256&state=" + state;
    }

    // Token exchange goes through our Vercel proxy, which adds the client
    // secret server-side. The secret never ships in this app, so there is
    // nothing secret on the phone to steal (client ID is public by design).
    static final String SP_PROXY = "https://kotassium-auth.vercel.app/api/spot/exchange";

    static void keepAlive(boolean on) {
        if (appCtx == null) return;
        Intent i = new Intent(appCtx, AuthKeepAlive.class);
        try {
            if (on) appCtx.startForegroundService(i);
            else appCtx.stopService(i);
        } catch (Exception ignored) {}
    }

    static String spotExchange(String code) throws Exception {
        JSONObject req = new JSONObject();
        req.put("code", code);
        req.put("code_verifier", spVerifier);
        byte[] payload = req.toString().getBytes("UTF-8");
        HttpURLConnection c = (HttpURLConnection) new URL(SP_PROXY).openConnection();
        c.setRequestMethod("POST");
        c.setRequestProperty("Content-Type", "application/json");
        c.setConnectTimeout(20000); c.setReadTimeout(30000);
        c.setDoOutput(true);
        c.getOutputStream().write(payload);
        int sc = c.getResponseCode();
        InputStream in = sc >= 400 ? c.getErrorStream() : c.getInputStream();
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        if (in != null) { byte[] buf = new byte[8192]; int n; while ((n = in.read(buf)) > 0) b.write(buf, 0, n); in.close(); }
        JSONObject t = new JSONObject(b.toString("UTF-8"));
        spAccess = t.optString("access_token");
        spRefresh = t.optString("refresh_token", spRefresh);
        if (!spAccess.isEmpty()) return "ok";
        return t.toString();
    }

    static String spotApi(String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setConnectTimeout(15000); c.setReadTimeout(30000);
        c.setRequestProperty("Authorization", "Bearer " + spAccess);
        c.setRequestProperty("User-Agent", UA);
        int sc = c.getResponseCode();
        InputStream in = sc >= 400 ? c.getErrorStream() : c.getInputStream();
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        if (in != null) { byte[] buf = new byte[8192]; int n; while ((n = in.read(buf)) > 0) b.write(buf, 0, n); in.close(); }
        String body = b.toString("UTF-8");
        if (sc >= 400) throw new Exception("spotify http " + sc + ": " + body);
        return body;
    }

    static String spotEnumerate() throws Exception {
        JSONObject manifest = new JSONObject();
        JSONArray pls = new JSONArray();
        String next = "https://api.spotify.com/v1/me/playlists?limit=50";
        while (next != null) {
            JSONObject d = new JSONObject(spotApi(next));
            JSONArray items = d.optJSONArray("items");
            if (items != null) for (int i = 0; i < items.length(); i++) {
                JSONObject p = items.getJSONObject(i);
                JSONObject po = new JSONObject();
                po.put("name", p.optString("name")); po.put("id", p.optString("id"));
                po.put("total", p.optJSONObject("tracks") == null ? 0 : p.optJSONObject("tracks").optInt("total"));
                pls.put(po);
            }
            next = d.optJSONObject("next") == null ? null : d.optString("next");
        }
        JSONArray liked = new JSONArray();
        next = "https://api.spotify.com/v1/me/tracks?limit=50";
        while (next != null) {
            JSONObject d = new JSONObject(spotApi(next));
            JSONArray items = d.optJSONArray("items");
            if (items != null) for (int i = 0; i < items.length(); i++) {
                JSONObject tr = items.getJSONObject(i).optJSONObject("track");
                if (tr == null || tr.optString("name").isEmpty()) continue;
                JSONObject o = new JSONObject();
                o.put("t", tr.optString("name"));
                JSONArray arts = tr.optJSONArray("artists");
                StringBuilder an = new StringBuilder();
                if (arts != null) for (int k = 0; k < arts.length(); k++) {
                    if (k > 0) an.append(", ");
                    an.append(arts.getJSONObject(k).optString("name"));
                }
                o.put("a", an.toString()); o.put("ms", tr.optLong("duration_ms"));
                liked.put(o);
            }
            next = d.optJSONObject("next") == null ? null : d.optString("next");
        }
        manifest.put("playlists", pls);
        manifest.put("liked", liked);
        manifest.put("generated", System.currentTimeMillis());
        FileOutputStream o = new FileOutputStream(new File(libDir.getParentFile(), "manifest.json"));
        o.write(manifest.toString().getBytes("UTF-8")); o.close();
        return manifest.toString();
    }

    public static void setSpCode(String c) { spCode = c == null ? "" : c; }

    // ---- routing ----

    static synchronized JSONObject readCoverMap() {
        try {
            if (coverMapFile != null && coverMapFile.exists())
                return new JSONObject(new String(fileBytes(coverMapFile), "UTF-8"));
        } catch (Exception ignored) {}
        return new JSONObject();
    }
    static synchronized void writeCoverMap(JSONObject m) {
        try {
            FileOutputStream o = new FileOutputStream(coverMapFile);
            o.write(m.toString().getBytes("UTF-8")); o.close();
        } catch (Exception ignored) {}
    }
    static String coverLocal(String url) {
        if (url == null || url.isEmpty() || url.startsWith("/cover/")) return url;
        try {
            JSONObject m = readCoverMap();
            if (m.has(url)) return "/cover/" + m.optString(url);
        } catch (Exception ignored) {}
        return url;
    }
    static void applyCoverLocalToArray(JSONArray arr) {
        if (arr == null) return;
        for (int i = 0; i < arr.length(); i++) {
            try {
                JSONObject o = arr.getJSONObject(i);
                if (o.has("cover")) o.put("cover", coverLocal(o.optString("cover")));
                if (o.has("tracks") && o.optJSONArray("tracks") != null) applyCoverLocalToArray(o.optJSONArray("tracks"));
            } catch (Exception ignored) {}
        }
    }

    void handle(Socket s) {
        try {
            InputStream in = s.getInputStream();
            String req = "", line;
            java.io.BufferedReader br = new java.io.BufferedReader(new java.io.InputStreamReader(in, "UTF-8"));
            while ((line = br.readLine()) != null && !line.isEmpty()) req += line + "\n";
            if (req.isEmpty()) { s.close(); return; }
            String[] first = req.split("\n")[0].split(" ");
            String method = first.length > 0 ? first[0] : "GET";
            String uri = first.length > 1 ? first[1] : "/";
            String path = uri;
            Map<String, String> params = new HashMap<>();
            int qm = uri.indexOf('?');
            if (qm >= 0) {
                path = uri.substring(0, qm);
                for (String kv : uri.substring(qm + 1).split("&")) {
                    int eq = kv.indexOf('=');
                    if (eq > 0) params.put(URLDecoder.decode(kv.substring(0, eq), "UTF-8"),
                            URLDecoder.decode(kv.substring(eq + 1), "UTF-8"));
                }
            }
            // read request body if present
            String bodyStr = "";
            int cl = 0;
            for (String hl : req.split("\n")) {
                if (hl.toLowerCase().startsWith("content-length:")) {
                    try { cl = Integer.parseInt(hl.substring(hl.indexOf(':')+1).trim()); } catch (Exception ignored) {}
                }
            }
            if (cl > 0) {
                StringBuilder bb = new StringBuilder();
                for (int i = 0; i < cl; i++) {
                    int c = br.read();
                    if (c < 0) break;
                    bb.append((char) c);
                }
                bodyStr = bb.toString();
            }
            byte[] resp;
            String type = "text/html; charset=utf-8";
            Map<String, String> extra = new HashMap<>();
            if (path.equals("/") || path.equals("/index.html")) {
                String html = CACHE.get("index");
                if (html == null) {
                    html = new String(fileBytes(new File(libDir.getParentFile(), "index.html")), "UTF-8");
                    CACHE.put("index", html);
                }
                resp = html.getBytes("UTF-8");
            } else if (path.equals("/api/search")) {
                String q = params.get("q"), src = params.containsKey("src") ? params.get("src") : "all";
                JSONArray out = new JSONArray();
                JSONObject errs = new JSONObject();
                if (!src.equals("deezer") && !src.equals("archive")) {
                    try {
                        JSONArray a = new JSONArray(ytSearch(q));
                        for (int i = 0; i < a.length() && i < 5; i++) out.put(a.getJSONObject(i));
                    } catch (Exception e) { errs.put("youtube", e.toString().substring(0, Math.min(90, e.toString().length()))); }
                }
                if (!src.equals("youtube") && !src.equals("archive")) {
                    try {
                        JSONArray a = new JSONArray(deezerSearch(q));
                        for (int i = 0; i < a.length(); i++) out.put(a.getJSONObject(i));
                    } catch (Exception e) { errs.put("deezer", e.toString().substring(0, Math.min(90, e.toString().length()))); }
                }
                if (src.equals("all") || src.equals("soundcloud")) try {
                    JSONArray a = new JSONArray(scSearch(q));
                    for (int i = 0; i < a.length(); i++) out.put(a.getJSONObject(i));
                } catch (Exception e) { errs.put("soundcloud", e.toString().substring(0, Math.min(90, e.toString().length()))); }
                if (src.equals("all") || src.equals("archive")) try {
                    JSONArray a = new JSONArray(iaSearch(q));
                    for (int i = 0; i < a.length(); i++) out.put(a.getJSONObject(i));
                } catch (Exception e) { errs.put("archive", e.toString().substring(0, Math.min(90, e.toString().length()))); }
                resp = ("{\"results\":" + out.toString() + ",\"errors\":" + errs.toString() + "}").getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/selftest")) {
                JSONObject st = new JSONObject();
                try { JSONArray a = new JSONArray(ytSearch("test")); st.put("youtube", "ok (" + a.length() + ")"); }
                catch (Exception e) { st.put("youtube", "FAIL: " + e.toString().substring(0, Math.min(80, e.toString().length()))); }
                try { JSONArray a = new JSONArray(deezerSearch("daft punk")); st.put("deezer", "ok (" + a.length() + ")"); }
                catch (Exception e) { st.put("deezer", "FAIL: " + e.toString().substring(0, Math.min(80, e.toString().length()))); }
                try { JSONArray a = new JSONArray(scSearch("test")); st.put("soundcloud", "ok (" + a.length() + ")"); }
                catch (Exception e) { st.put("soundcloud", "FAIL: " + e.toString().substring(0, Math.min(80, e.toString().length()))); }
                try { JSONArray a = new JSONArray(iaSearch("test")); st.put("archive", "ok (" + a.length() + ")"); }
                catch (Exception e) { st.put("archive", "FAIL: " + e.toString().substring(0, Math.min(80, e.toString().length()))); }
                resp = st.toString().getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/play")) {
                String src = params.get("src"), id = params.containsKey("id") ? params.get("id") : "";
                if (src.equals("youtube")) {
                    resp = ("<html><body style='background:#000;margin:0;display:grid;place-items:center;height:100vh'>"
                            + "<iframe width='100%' height='60%' src='https://www.youtube-nocookie.com/embed/" + id
                            + "?autoplay=1' style='border:0' allow='autoplay; encrypted-media' allowfullscreen></iframe></body></html>")
                            .getBytes("UTF-8");
                } else if (src.equals("deezer")) {
                    File f = dlFile("deezer", id, params.get("preview"));
                    resp = fileBytes(f); type = "audio/mpeg";
                } else if (src.equals("soundcloud")) {
                    File f = dlFile("soundcloud", id, scResolve(id));
                    resp = fileBytes(f); type = "audio/mpeg";
                } else if (src.equals("archive")) {
                    resp = new byte[0];
                    extra.put("Location", "https://archive.org/download/" + id + "/" + id + "_vbr.mp3");
                    extra.put("__code", "302");
                } else {
                    resp = new byte[0]; type = "text/plain";
                }
            } else if (path.equals("/api/download")) {
                String src = params.get("src"), id = params.containsKey("id") ? params.get("id") : "";
                String name = params.containsKey("name") ? params.get("name") : id;
                if (src.equals("youtube")) {
                    resp = "{\"error\":\"youtube downloads need the extractor lane\"}".getBytes("UTF-8");
                    type = "application/json";
                } else {
                    String url;
                    if (src.equals("soundcloud")) url = scResolve(id);
                    else if (src.equals("archive")) url = "https://archive.org/download/" + id + "/" + id + "_vbr.mp3";
                    else if (src.equals("deezer")) url = params.containsKey("preview") ? params.get("preview") : "";
                    else url = "";
                    File f = dlFile(src, id, url);
                    resp = fileBytes(f); type = "audio/mpeg";
                    extra.put("Content-Disposition", "attachment; filename=\""
                            + name.replaceAll("[^A-Za-z0-9 ()-]", "") + ".mp3\"");
                }
            } else if (path.equals("/api/recommend")) {
                String vid = params.containsKey("seed") ? params.get("seed") : "";
                String artist = params.containsKey("artist") ? params.get("artist") : "";
                JSONArray out = new JSONArray();
                if (!vid.isEmpty()) {
                    try {
                        String body = "{\"context\":{\"client\":{\"clientName\":\"WEB\",\"clientVersion\":\"2.20241126.01.00\",\"hl\":\"en\",\"gl\":\"US\"}},\"videoId\":"
                                + JSONObject.quote(vid) + "}";
                        JSONObject d = new JSONObject(body(http(
                                "https://www.youtube.com/youtubei/v1/next?prettyPrint=false", "POST", body)));
                        List<JSONObject> vids = new ArrayList<>();
                        collectVids(d, vids);
                        for (JSONObject v : vids) {
                            try {
                                JSONObject o = new JSONObject();
                                o.put("source", "youtube");
                                o.put("title", v.optJSONObject("title").optJSONArray("runs").optJSONObject(0).optString("text"));
                                o.put("artist", v.optJSONObject("ownerText") == null ? "" :
                                        v.optJSONObject("ownerText").optJSONArray("runs").optJSONObject(0).optString("text"));
                                o.put("dur", 0); o.put("id", v.optString("videoId")); o.put("full", false);
                                if (!v.optString("videoId").equals(vid)) out.put(o);
                            } catch (Exception ignored) {}
                            if (out.length() >= 6) break;
                        }
                    } catch (Exception ignored) {}
                }
                if (out.length() == 0 && !artist.isEmpty()) {
                    try {
                        String r = http("https://api.deezer.com/search?q=" + URLEncoder.encode(artist, "UTF-8") + "&limit=1", "GET", null);
                        JSONArray data = new JSONObject(body(r)).optJSONArray("data");
                        if (data != null && data.length() > 0) {
                            long aid = data.getJSONObject(0).optLong("artist", 0) != 0
                                    ? data.getJSONObject(0).getJSONObject("artist").optLong("id") : 0;
                            if (aid != 0) {
                                String rel = http("https://api.deezer.com/artist/" + aid + "/related", "GET", null);
                                JSONArray ra = new JSONObject(body(rel)).optJSONArray("data");
                                int added = 0;
                                if (ra != null) for (int i = 0; i < ra.length() && added < 4; i++) {
                                    long rid = ra.getJSONObject(i).optLong("id");
                                    if (rid == 0) continue;
                                    String top = http("https://api.deezer.com/artist/" + rid + "/top?limit=2", "GET", null);
                                    JSONArray tt = new JSONObject(body(top)).optJSONArray("data");
                                    if (tt != null) for (int k = 0; k < tt.length() && added < 4; k++) {
                                        JSONObject tk = tt.getJSONObject(k);
                                        JSONObject o = new JSONObject();
                                        o.put("source", "deezer"); o.put("title", tk.optString("title"));
                                        o.put("artist", tk.optJSONObject("artist") == null ? "" : tk.optJSONObject("artist").optString("name"));
                                        o.put("dur", tk.optInt("duration")); o.put("id", String.valueOf(tk.optLong("id")));
                                        o.put("preview", tk.optString("preview")); o.put("full", false);
                                        JSONObject alb = tk.optJSONObject("album");
                                        if (alb != null) o.put("cover", coverLocal(alb.optString("cover")));
                                        out.put(o); added++;
                                    }
                                }
                            }
                        }
                    } catch (Exception ignored) {}
                }
                resp = ("{\"results\":" + out.toString() + "}").getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/spot/playlist")) {
                String next = "https://api.spotify.com/v1/playlists/" + params.get("id") + "/tracks?limit=100";
                JSONArray tracks = new JSONArray();
                while (next != null) {
                    JSONObject d = new JSONObject(spotApi(next));
                    JSONArray items = d.optJSONArray("items");
                    if (items != null) for (int i = 0; i < items.length(); i++) {
                        JSONObject tr = items.getJSONObject(i).optJSONObject("track");
                        if (tr == null || tr.optString("name").isEmpty()) continue;
                        JSONObject o = new JSONObject();
                        o.put("t", tr.optString("name"));
                        JSONArray arts = tr.optJSONArray("artists");
                        StringBuilder an = new StringBuilder();
                        if (arts != null) for (int k = 0; k < arts.length(); k++) {
                            if (k > 0) an.append(", ");
                            an.append(arts.getJSONObject(k).optString("name"));
                        }
                        o.put("a", an.toString()); o.put("ms", tr.optLong("duration_ms"));
                        tracks.put(o);
                    }
                    next = d.optJSONObject("next") == null ? null : d.optString("next");
                }
                resp = ("{\"tracks\":" + tracks.toString() + "}").getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/check")) {
                String key = norm((params.containsKey("a") ? params.get("a") : "") + " " + (params.containsKey("t") ? params.get("t") : ""));
                String found = "";
                File[] fs = libDir.listFiles();
                if (fs != null) for (File f : fs) if (f.getName().endsWith(".mp3")
                        && norm(f.getName().replaceAll("\\.mp3$", "")).equals(key)) { found = f.getName(); break; }
                resp = ("{\"path\":" + (found.isEmpty() ? "null" : "\"" + found + "\"") + "}").getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/callback")) {
                String c = params.containsKey("code") ? params.get("code") : "";
                String err = params.containsKey("error") ? params.get("error") : "";
                if (!c.isEmpty()) spCode = c;
                String msg = !c.isEmpty() ? "Signed in — return to Kotassium."
                        : ("Sign-in " + (!err.isEmpty() ? err : "cancelled") + " — return to Kotassium and retry.");
                resp = ("<html><body style='background:#121212;color:#fff;font-family:sans-serif;display:grid;place-items:center;height:100vh;margin:0'>"
                        + "<div style='text-align:center'><h2>Kotassium</h2><p>" + msg + "</p></div></body></html>").getBytes("UTF-8");
            } else if (path.equals("/api/update/check")) {
                JSONObject jo = new JSONObject();
                String cur = currentVersion();
                jo.put("current", cur);
                try {
                    JSONObject latest = new JSONObject(body(http(UPDATE_BASE + "/api/update/latest", "GET", null)));
                    String lv = latest.optString("version");
                    jo.put("latest", lv);
                    jo.put("available", !lv.isEmpty() && newerVersion(lv, cur));
                    jo.put("apk_url", latest.optString("apk_url"));
                } catch (Exception e) {
                    jo.put("available", false);
                    jo.put("error", String.valueOf(e.getMessage()));
                }
                resp = jo.toString().getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/spot/resolve")) {
                // Paste-a-link: public playlist/album/track links resolved by the
                // Vercel proxy (no login, no Premium). Phone never sees secrets.
                // Successful resolves are saved locally, so a link is entered once.
                try {
                    String link = params.get("url");
                    if (link == null || !link.matches("(?i)https?://\\S+") || link.length() > 2000)
                        throw new Exception("need an http(s) link");
                    String r = body(http(UPDATE_BASE + "/api/spot/resolve?url=" + URLEncoder.encode(link, "UTF-8"), "GET", null));
                    JSONObject jr = new JSONObject(r); // validate JSON
                    if (!jr.has("error") && jr.has("tracks")) {
                        // Partial results: try the true total straight from the playlist
                        // page. The phone's residential IP passes Spotify's bot check
                        // far more often than datacenter IPs.
                        if (jr.optBoolean("partial", false) && jr.isNull("total")
                                && "playlist".equals(jr.optString("type"))) {
                            int t = fetchSongCount(link);
                            if (t > 0) jr.put("total", t);
                        }
                        applyCoverLocalToArray(jr.optJSONArray("tracks"));
                        saveLink(link, jr);
                        r = jr.toString();
                    }
                    resp = r.getBytes("UTF-8");
                } catch (Exception e) {
                    resp = ("{\"error\":\"resolve_failed\",\"error_description\":" + JSONObject.quote(String.valueOf(e.getMessage())) + "}").getBytes("UTF-8");
                }
                type = "application/json";
            } else if (path.equals("/api/links")) {
                JSONArray out = new JSONArray();
                try {
                    JSONArray all = readLinks();
                    for (int i = 0; i < all.length(); i++) {
                        JSONObject e = all.getJSONObject(i);
                        JSONObject o = new JSONObject();
                        o.put("url", e.optString("url")); o.put("name", e.optString("name"));
                        o.put("count", e.optInt("count")); o.put("ts", e.optLong("ts"));
                        if (!e.isNull("total")) o.put("total", e.optInt("total"));
                        o.put("partial", e.optBoolean("partial", false));
                        out.put(o);
                    }
                } catch (Exception ignored) {}
                resp = ("{\"links\":" + out.toString() + "}").getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/links/get")) {
                try {
                    JSONObject e = findLink(params.get("url"));
                    if (e == null) throw new Exception("not saved");
                    applyCoverLocalToArray(e.optJSONArray("tracks"));
                    resp = e.toString().getBytes("UTF-8");
                } catch (Exception ex) {
                    resp = ("{\"error\":\"not_found\"}").getBytes("UTF-8");
                }
                type = "application/json";
            } else if (path.equals("/api/links/drop")) {
                try {
                    dropLink(params.get("url"));
                    resp = "{\"ok\":true}".getBytes("UTF-8");
                } catch (Exception ex) {
                    resp = ("{\"error\":" + JSONObject.quote(String.valueOf(ex.getMessage())) + "}").getBytes("UTF-8");
                }
                type = "application/json";
            } else if (path.equals("/api/update/apply")) {
                JSONObject jo = new JSONObject();
                try {
                    String url = params.get("url");
                    if (url == null || !url.startsWith(UPDATE_BASE + "/api/update/apk")) throw new Exception("bad update url");
                    File f = new File(appCtx.getExternalFilesDir(null), "update.apk");
                    downloadTo(url, f);
                    updateStatus = "installing...";
                    Installer.install(appCtx, f);
                    jo.put("ok", true);
                } catch (Exception e) {
                    jo.put("ok", false);
                    jo.put("error", String.valueOf(e.getMessage()));
                }
                resp = jo.toString().getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/ytdl")) {
                // Downloads a YouTube video's audio on-device (yt-dlp via Chaquopy) into the music folder.
                JSONObject jo = new JSONObject();
                try {
                    String vid = params.containsKey("id") ? params.get("id") : "";
                    PyObject mod = Python.getInstance().getModule("downloader");
                    String file = mod.callAttr("fetch", vid, libDir.getAbsolutePath()).toString();
                    jo.put("file", file);
                } catch (Throwable e) {
                    jo.put("error", String.valueOf(e.getMessage()));
                }
                resp = jo.toString().getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/update/status")) {
                resp = ("{\"status\":" + JSONObject.quote(updateStatus) + "}").getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/spot/auth")) {
                keepAlive(true);
                resp = spotAuthUrl(params.containsKey("client_id") ? params.get("client_id") : null).getBytes("UTF-8");
                type = "text/plain";
            } else if (path.equals("/api/spot/client")) {
                if (params.containsKey("client_id") && validCid(params.get("client_id"))) setCid(params.get("client_id"));
                JSONObject jo = new JSONObject();
                try {
                    jo.put("client_id", activeCid());
                    jo.put("is_default", activeCid().equals(SP_CID));
                    jo.put("redirect_uri", SP_REDIRECT);
                } catch (Exception ignored) {}
                resp = jo.toString().getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/spot/code")) {
                // consume the code: a code is single-use, so never hand it out twice
                String c = spCode;
                if (!c.isEmpty()) spCode = "";
                resp = ("{\"code\":\"" + c + "\"}").getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/spot/exchange")) {
                try {
                    String r = spotExchange(params.get("code"));
                    if (r.equals("ok")) keepAlive(false);
                    resp = (r.equals("ok") ? "{\"ok\":true}" : r).getBytes("UTF-8");
                } catch (Exception e) {
                    resp = ("{\"error\":\"exchange_failed\",\"error_description\":" + JSONObject.quote(String.valueOf(e.getMessage())) + "}").getBytes("UTF-8");
                }
                type = "application/json";
            } else if (path.equals("/api/spot/enumerate")) {
                try {
                    resp = spotEnumerate().getBytes("UTF-8");
                } catch (Exception e) {
                    resp = ("{\"error\":\"enumerate_failed\",\"error_description\":" + JSONObject.quote(String.valueOf(e.getMessage())) + "}").getBytes("UTF-8");
                }
                type = "application/json";
            } else if (path.equals("/api/manifest")) {
                File mf = new File(libDir.getParentFile(), "manifest.json");
                resp = mf.exists() ? fileBytes(mf) : "{}".getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/library")) {
                JSONArray out = new JSONArray();
                File[] fs = libDir.listFiles();
                if (fs != null) for (File f : fs) if (f.getName().endsWith(".mp3")) {
                    JSONObject o = new JSONObject();
                    o.put("name", f.getName().replaceAll("\\.mp3$", ""));
                    o.put("size", f.length());
                    out.put(o);
                }
                resp = ("{\"library\":" + out.toString() + "}").getBytes("UTF-8");
                type = "application/json";
            } else if (path.equals("/api/cover/cache")) {
                try {
                    JSONObject j = new JSONObject(bodyStr);
                    String url = j.optString("url", "");
                    String data = j.optString("data", "");
                    if (url.isEmpty() || data.isEmpty()) throw new Exception("missing");
                    java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
                    byte[] hb = md.digest(url.getBytes("UTF-8"));
                    StringBuilder hex = new StringBuilder();
                    for (int i = 0; i < 8; i++) hex.append(String.format("%02x", hb[i]));
                    String key = hex.toString();
                    String ext = "jpg";
                    String low = url.toLowerCase();
                    if (low.contains(".png")) ext = "png";
                    else if (low.contains(".webp")) ext = "webp";
                    else if (low.contains(".gif")) ext = "gif";
                    String b64 = data;
                    int comma = b64.indexOf(',');
                    if (comma >= 0) b64 = b64.substring(comma + 1);
                    byte[] bytes = java.util.Base64.getDecoder().decode(b64);
                    File out = new File(coverDir, key + "." + ext);
                    FileOutputStream fos = new FileOutputStream(out);
                    fos.write(bytes); fos.close();
                    JSONObject m = readCoverMap();
                    m.put(url, key + "." + ext);
                    writeCoverMap(m);
                    resp = ("{\"ok\":true,\"key\":\""+key+"\",\"file\":\""+key+"."+ext+"\"}").getBytes("UTF-8");
                } catch (Exception e) {
                    resp = ("{\"error\":\""+e.toString().replace("\"","")+"\"}").getBytes("UTF-8");
                }
                type = "application/json";
            } else if (path.startsWith("/cover/")) {
                String name = path.substring("/cover/".length());
                name = name.replaceAll("[^A-Za-z0-9._-]", "");
                File f = new File(coverDir, name);
                if (f.exists()) {
                    resp = fileBytes(f);
                    String ext = name.toLowerCase();
                    if (ext.endsWith(".png")) type = "image/png";
                    else if (ext.endsWith(".webp")) type = "image/webp";
                    else if (ext.endsWith(".gif")) type = "image/gif";
                    else type = "image/jpeg";
                } else {
                    resp = new byte[0]; type = "text/plain";
                }
            } else if (path.startsWith("/lib/")) {
                File f = new File(libDir, path.substring(5));
                resp = f.exists() ? fileBytes(f) : new byte[0];
                type = f.getName().endsWith(".m4a") ? "audio/mp4" : "audio/mpeg";
            } else {
                resp = new byte[0]; type = "text/plain";
            }
            OutputStream o = s.getOutputStream();
            String code = extra.containsKey("__code") ? extra.get("__code") : "200 OK";
            StringBuilder head = new StringBuilder("HTTP/1.1 " + code + "\r\n");
            head.append("Content-Type: ").append(type).append("\r\n");
            head.append("Content-Length: ").append(resp.length).append("\r\n");
            head.append("Connection: close\r\n");
            for (Map.Entry<String, String> e : extra.entrySet())
                if (!e.getKey().equals("__code")) head.append(e.getKey()).append(": ").append(e.getValue()).append("\r\n");
            head.append("\r\n");
            o.write(head.toString().getBytes("UTF-8"));
            o.write(resp);
            o.flush();
            s.close();
        } catch (Exception ignored) {
            // answer with a real error so the audio element / page fail fast instead of hanging
            try {
                s.getOutputStream().write("HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".getBytes("UTF-8"));
                s.getOutputStream().flush();
            } catch (Exception ignored3) {}
            try { s.close(); } catch (Exception ignored2) {}
        }
    }
}
