package com.bobstevens.kotassium;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;

public class MainActivity extends Activity {
    private WebView w;
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        try {
            File root = getExternalFilesDir(null);
            File out = new File(root, "index.html");
            // Always refresh: the served page is this copy, so a stale copy
            // would silently keep old JS (e.g. old sign-in flow) after update.
            InputStream in = getAssets().open("index.html");
            FileOutputStream o = new FileOutputStream(out);
            byte[] buf = new byte[8192]; int n;
            while ((n = in.read(buf)) > 0) o.write(buf, 0, n);
            in.close(); o.close();
            new Loop(getApplicationContext());
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        w = new WebView(this);
        w.getSettings().setJavaScriptEnabled(true);
        w.getSettings().setDomStorageEnabled(true);
        w.getSettings().setMediaPlaybackRequiresUserGesture(false);
        w.getSettings().setMediaPlaybackRequiresUserGesture(false);
        w.setWebViewClient(new WebViewClient() {
            // OAuth must NOT run inside the WebView: it has an isolated cookie
            // jar, so Google sees no device session and forces a full re-login.
            // Open Spotify/Google auth in the system browser (shares the device
            // Google session = one-tap Continue with Google, like Spotify's app).
            // The browser redirects to our 127.0.0.1:5588 loopback listener and
            // the page polls /api/spot/code to complete sign-in.
            private boolean openExternally(String url) {
                String host = "";
                try { host = new java.net.URL(url).getHost(); } catch (Exception ignored) {}
                if (host != null && (host.contains("spotify.com") || host.contains("google.com")
                        || host.contains("gstatic.com") || host.contains("googleusercontent.com"))) {
                    try {
                        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                        startActivity(i);
                    } catch (Exception ignored) {}
                    return true;
                }
                return false;
            }
            @Override public boolean shouldOverrideUrlLoading(WebView v, android.webkit.WebResourceRequest rq) {
                return openExternally(rq.getUrl().toString());
            }
            @Override public boolean shouldOverrideUrlLoading(WebView v, String url) {
                return openExternally(url);
            }
            @Override public android.webkit.WebResourceResponse shouldInterceptRequest(WebView v, android.webkit.WebResourceRequest rq) {
                java.net.URL u;
                try { u = new java.net.URL(rq.getUrl().toString()); } catch (Exception e) { return null; }
                if ("127.0.0.1".equals(u.getHost()) && (u.getPort() == 4381 || u.getPort() == 5588)
                        && u.getPath() != null && u.getPath().contains("/callback")) {
                    String q = u.getQuery() == null ? "" : u.getQuery();
                    for (String kv : q.split("&")) {
                        if (kv.startsWith("code=")) {
                            try { Loop.setSpCode(java.net.URLDecoder.decode(kv.substring(5), "UTF-8")); } catch (Exception ignored) {}
                        }
                    }
                    return new android.webkit.WebResourceResponse("text/html", "UTF-8",
                            new java.io.ByteArrayInputStream("<script>location.replace('http://127.0.0.1:8421/')</script>".getBytes()));
                }
                return null;
            }
        });
        w.loadUrl("http://127.0.0.1:8421/");
        setContentView(w);
    }
    @Override public void onBackPressed() {
        if (w != null && w.canGoBack()) w.goBack(); else super.onBackPressed();
    }
}
