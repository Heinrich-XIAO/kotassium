package com.bobstevens.kotassium;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;

/** Installs an APK via PackageInstaller (no FileProvider / AndroidX needed). */
public class Installer {
    static void install(Context ctx, File apk) throws Exception {
        PackageInstaller pi = ctx.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams p =
                new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        p.setAppPackageName(ctx.getPackageName());
        int id = pi.createSession(p);
        PackageInstaller.Session s = pi.openSession(id);
        try {
            try (OutputStream out = s.openWrite("update", 0, apk.length());
                 InputStream in = new FileInputStream(apk)) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
            Intent i = new Intent(ctx, InstallResultReceiver.class);
            PendingIntent pe = PendingIntent.getBroadcast(ctx, id, i,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
            s.commit(pe.getIntentSender());
        } catch (Exception e) {
            s.abandon();
            throw e;
        }
    }
}
