package com.bobstevens.kotassium;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;

/**
 * Keeps the app process alive while the user is in the browser completing Spotify
 * sign-in. Android freezes backgrounded processes, which left the loopback callback
 * listener unserviced (browser: "127.0.0.1 timed out"). Foreground services are not frozen.
 */
public class AuthKeepAlive extends Service {
    static final String CHANNEL = "signin";
    static final int NOTE_ID = 1;

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Sign-in", NotificationManager.IMPORTANCE_LOW));
        }
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        Notification n = b.setContentTitle("Kotassium")
                .setContentText("Waiting for Spotify sign-in...")
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTE_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(NOTE_ID, n);
        }
        // hard cap so it can never run indefinitely
        new Handler(Looper.getMainLooper()).postDelayed(this::stopSelf, 5 * 60 * 1000L);
        return START_NOT_STICKY;
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
