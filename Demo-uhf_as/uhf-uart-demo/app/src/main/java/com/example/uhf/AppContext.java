package com.example.uhf;

import android.app.Application;
import android.os.SystemClock;
import android.util.Log;

import com.example.uhf.tools.FileUtils;
import com.example.uhf.tools.ToastUtil;


/**
 * 全局应用程序类：用于保存和调用全局应用配置
 */
public class AppContext extends Application implements Thread.UncaughtExceptionHandler {
    private static final String TAG = "AppContext";

    public static final String DEFAULT_PATH = "/sdcard/uhf/";

    private static AppContext mApp;

    public static AppContext getInstance() {
        return mApp;
    }

    @Override
    public void onCreate() {
        super.onCreate();

        mApp = this;
        Thread.setDefaultUncaughtExceptionHandler(this);

        ToastUtil.init(mApp);
    }

    @Override
    public synchronized void uncaughtException(Thread thread, Throwable throwable) {
        Log.e("FileUtils", "uncaughtException throwable:" + throwable);
        new Thread(() -> {
            FileUtils.saveCrashFile(throwable);
            SystemClock.sleep(200);
            System.exit(0);
        }).start();
    }

    public String getVerName() {
        try {
            return this.getPackageManager().getPackageInfo(this.getPackageName(), 0).versionName;
        } catch (Exception ignored) {
        }
        return "";
    }

    public int getVerCode() {
        try {
            return this.getPackageManager().getPackageInfo(this.getPackageName(), 0).versionCode;
        } catch (Exception ignored) {
        }
        return 0;
    }
}
