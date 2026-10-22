package app.kotassium.mobile;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

/**
 * Keeps the local server alive while the phone sleeps.
 *
 * In "This phone" mode the server, the music and the downloads all run in
 * this process. Without a foreground service Android freezes the app the
 * moment the screen turns off: downloads stop mid-transfer and the page
 * cannot fetch. The persistent notification is the price Android charges
 * for a process that is allowed to outlive the screen.
 *
 * The wake and Wi-Fi locks are held only while a download actually runs
 * (serve_web.JOB_HOOK -> ServeService.setBusy, wired by kotassium_boot.py),
 * so an idle library costs no battery.
 */
public class ServeService extends Service {
    private static final String CHANNEL = "kotassium";
    private static final int NOTIFICATION_ID = 1;

    /** The running instance, so the server thread can reach the locks. */
    private static ServeService instance;

    private NotificationManager notifications;
    private PowerManager.WakeLock wake;
    private WifiManager.WifiLock wifi;
    private boolean busy = false;

    /**
     * Called from the server (any thread) when a download starts or ends.
     * True holds the locks, False lets the CPU sleep again.
     */
    public static void setBusy(boolean active) {
        ServeService s = instance;
        if (s == null) {
            return; // remote mode, or the service was never started
        }
        synchronized (s) {
            s.apply(active);
        }
        s.notifications.notify(NOTIFICATION_ID, s.notification(active));
    }

    /** Take or drop the locks. Caller holds this instance's monitor. */
    private void apply(boolean active) {
        busy = active;
        if (active) {
            if (!wake.isHeld()) wake.acquire();
            if (!wifi.isHeld()) wifi.acquire();
        } else {
            if (wake.isHeld()) wake.release();
            if (wifi.isHeld()) wifi.release();
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        instance = this;
        notifications = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL, getString(R.string.serve_channel),
                    NotificationManager.IMPORTANCE_LOW);
            channel.setShowBadge(false);
            notifications.createNotificationChannel(channel);
        }
        PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
        wake = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "kotassium:serve");
        wake.setReferenceCounted(false);
        // HIGH_PERF, not LOW_LATENCY (API 29+): the point is to stop Wi-Fi
        // powering down mid-transfer, not to shave latency. Deprecated in
        // API 29 but still the only way to say this on minSdk 24.
        @SuppressWarnings("deprecation")
        WifiManager wm = (WifiManager) getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);
        wifi = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "kotassium:serve");
        wifi.setReferenceCounted(false);
        startForeground(NOTIFICATION_ID, notification(false));
    }

    @SuppressWarnings("deprecation") // no-channel builder for API 24/25
    private Notification notification(boolean busy) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);
        return b.setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(getString(busy ? R.string.serve_busy : R.string.serve_text))
                .setOngoing(true)
                .build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Every startForegroundService() must be answered with startForeground()
        // (a second one included) or the system kills the app. START_NOT_STICKY:
        // the activity starts the service, and a dead server must not resurrect
        // as a zombie notification.
        boolean active;
        synchronized (this) {
            active = busy;
        }
        startForeground(NOTIFICATION_ID, notification(active));
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        // Never leave the CPU awake after the app is gone. Drop the locks
        // directly instead of going through setBusy(): re-posting the
        // notification here would resurrect it behind a dead service.
        synchronized (this) {
            apply(false);
        }
        instance = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null; // started, not bound
    }
}
