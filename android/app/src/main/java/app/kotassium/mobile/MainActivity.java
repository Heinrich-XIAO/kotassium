package app.kotassium.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;

/**
 * The whole Android app: a window onto the shared Kotassium server.
 *
 * There is deliberately no UI here. The page is the product; this class only
 * supplies the things a browser tab cannot (an icon, a persistent session, a
 * back button that stays inside the app, and no address bar). If something
 * looks wrong on Android, fix it in web/index.html.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "kotassium";
    private WebView web;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#121212"));

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri url = req.getUrl();
                String base = serverUrl();
                String host = url.getHost() == null ? "" : url.getHost();
                if (base != null && host.equals(Uri.parse(base).getHost())) {
                    return false; // stay in the app
                }
                startActivity(new Intent(Intent.ACTION_VIEW, url)); // everything else: browser
                return true;
            }
        });

        setContentView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        String url = serverUrl();
        if (url == null) {
            askForServer();
        } else {
            load(url);
        }
    }

    /** Saved URL, else the one baked into the build, else null (ask the user). */
    private String serverUrl() {
        SharedPreferences p = getSharedPreferences(PREFS, MODE_PRIVATE);
        String saved = p.getString("url", "");
        if (saved == null || saved.isEmpty()) {
            saved = BuildConfig.KOTASSIUM_URL;
        }
        if (saved == null || saved.isEmpty()) {
            return null;
        }
        if (!saved.startsWith("http")) {
            saved = "https://" + saved;
        }
        return saved.endsWith("/") ? saved : saved + "/";
    }

    private void load(String base) {
        // desktop=1 stops the page's 2s reload-on-change poll: a phone should
        // not reload the UI mid-track just because the server was redeployed.
        web.loadUrl(base + "?desktop=1");
    }

    /** One-time setup, only for APKs built without a baked-in URL. */
    private void askForServer() {
        EditText input = new EditText(this);
        input.setHint("https://music.example.com");
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        new AlertDialog.Builder(this)
                .setTitle("Kotassium server")
                .setMessage("Paste the address of your shared library.")
                .setView(input)
                .setCancelable(false)
                .setPositiveButton("Connect", (d, w) -> {
                    String v = input.getText().toString().trim();
                    if (v.isEmpty()) {
                        askForServer();
                        return;
                    }
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("url", v).apply();
                    load(serverUrl());
                })
                .show();
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
