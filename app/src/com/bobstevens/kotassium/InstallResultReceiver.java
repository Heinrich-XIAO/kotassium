package com.bobstevens.kotassium;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;

/** Receives the PackageInstaller result: shows the confirm prompt or records the status. */
public class InstallResultReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context ctx, Intent intent) {
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        String msg = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                ctx.startActivity(confirm);
            }
            Loop.updateStatus = "confirm the install prompt";
        } else if (status == PackageInstaller.STATUS_SUCCESS) {
            Loop.updateStatus = "updated";
        } else {
            Loop.updateStatus = "install failed (" + status + "): " + msg
                    + (status == PackageInstaller.STATUS_FAILURE_BLOCKED
                       ? " - allow installs from Kotassium in Settings" : "");
        }
    }
}
