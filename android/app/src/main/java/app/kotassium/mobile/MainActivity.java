package app.kotassium.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.AssetManager;
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

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * The whole Android app: a window onto Kotassium.
 *
 * There is deliberately no UI here. The page is the product; this class only
 * supplies the things a browser tab cannot (an icon, a persistent session, a
 * back button that stays inside the app, and no address bar). If something
 * looks wrong on Android, fix it in web/index.html.
 *
 * Two ways to get the page, both the same page:
 *   - "local": run serve_web.py inside the APK (Chaquopy) and open loopback.
 *   - "remote": open a shared library on another machine.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "kotassium";
    private static final String MODE_LOCAL = "local";
    private static final String MODE_REMOTE = "remote";
    private static final int PORT = 8421;

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
                String base = currentBase();
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

        String mode = prefs().getString("mode", "");
        if (mode.isEmpty()) {
            // A baked-in URL keeps the old behaviour; otherwise let the user
            // decide whether this phone is the library or just a window.
            if (!BuildConfig.KOTASSIUM_URL.isEmpty()) {
                prefs().edit().putString("mode", MODE_REMOTE).apply();
                load(remoteUrl());
            } else {
                chooseMode();
            }
        } else if (MODE_LOCAL.equals(mode)) {
            startLocal();
        } else {
            String url = remoteUrl();
            if (url == null) {
                askForServer();
            } else {
                load(url);
            }
        }
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    // ------------------------------------------------------------ remote mode

    /** Saved URL, else the one baked into the build, else null (ask the user). */
    private String remoteUrl() {
        String saved = prefs().getString("url", "");
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

    private String currentBase() {
        if (MODE_LOCAL.equals(prefs().getString("mode", ""))) {
            return "http://127.0.0.1:" + PORT + "/";
        }
        return remoteUrl();
    }

    // ------------------------------------------------------------- local mode

    /**
     * Start serve_web.py inside the app and open it. The server runs on
     * loopback, so only this phone can reach it: the page, the library and
     * the downloader are all here, no other machine required.
     */
    private void startLocal() {
        try {
            File base = new File(getFilesDir(), "unpacked");
            unpackWebAssets(base);
            File lib = getExternalFilesDir(null);
            if (lib == null) {
                lib = getFilesDir();
            }
            lib = new File(lib, "Music");

            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
            PyObject mod = Python.getInstance().getModule("kotassium_boot");
            int port = mod.callAttr("start", base.getAbsolutePath(),
                    lib.getAbsolutePath(), PORT).toJava(Integer.class);
            load("http://127.0.0.1:" + port + "/");
        } catch (Throwable t) {
            showError(t);
        }
    }

    /**
     * The page lives in the APK's assets; serve_web reads it from disk, so it
     * is unpacked once per build. This is the only copy of the page: the build
     * copies it from web/ at the repo root.
     */
    private void unpackWebAssets(File base) throws IOException {
        int built = prefs().getInt("assets", -1);
        if (built == BuildConfig.VERSION_CODE) {
            return;
        }
        unpack(getAssets(), "web", new File(base, "web"));
        prefs().edit().putInt("assets", BuildConfig.VERSION_CODE).apply();
    }

    private void unpack(AssetManager am, String asset, File dest) throws IOException {
        String[] children = am.list(asset);
        if (children == null || children.length == 0) {
            File parent = dest.getParentFile();
            if (parent != null) {
                parent.mkdirs();
            }
            try (InputStream in = am.open(asset); OutputStream out = new FileOutputStream(dest)) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                }
            }
            return;
        }
        dest.mkdirs();
        for (String child : children) {
            unpack(am, asset + "/" + child, new File(dest, child));
        }
    }

    // ------------------------------------------------------------------- mode

    private void chooseMode() {
        new AlertDialog.Builder(this)
                .setTitle("Kotassium")
                .setMessage("Play from this phone's own library, or connect to a shared one?")
                .setCancelable(false)
                .setPositiveButton("This phone", (d, w) -> {
                    prefs().edit().putString("mode", MODE_LOCAL).apply();
                    startLocal();
                })
                .setNeutralButton("Shared server", (d, w) -> {
                    prefs().edit().putString("mode", MODE_REMOTE).apply();
                    askForServer();
                })
                .show();
    }

    private void showError(Throwable t) {
        String msg = String.valueOf(t);
        new AlertDialog.Builder(this)
                .setTitle("Could not start the server")
                .setMessage(msg)
                .setCancelable(false)
                .setPositiveButton("Use a server", (d, w) -> {
                    prefs().edit().putString("mode", MODE_REMOTE).apply();
                    askForServer();
                })
                .show();
    }

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
                    prefs().edit().putString("url", v).putString("mode", MODE_REMOTE).apply();
                    load(remoteUrl());
                })
                .show();
    }

    private void load(String base) {
        // desktop=1 stops the page's 2s reload-on-change poll: a phone should
        // not reload the UI mid-track just because the server was redeployed.
        web.loadUrl(base + "?desktop=1");
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
