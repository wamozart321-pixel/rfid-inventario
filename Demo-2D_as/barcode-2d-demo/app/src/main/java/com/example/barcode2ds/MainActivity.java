package com.example.barcode2ds;

import android.app.Activity;
import android.app.ProgressDialog;
import android.os.AsyncTask;
import android.os.Process;

import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;

import com.rscja.barcode.BarcodeDecoder;
import com.rscja.barcode.BarcodeFactory;
import com.rscja.deviceapi.entity.BarcodeEntity;


public class MainActivity extends Activity {
    String TAG = "MainActivity_2D";

    Button btnScan;
    Button btnStop;
    TextView tvData;

    BarcodeDecoder barcodeDecoder = BarcodeFactory.getInstance().getBarcodeDecoder();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        btnScan = (Button) findViewById(R.id.btnScan);
        tvData = (TextView) findViewById(R.id.tvData);
        btnStop = (Button) findViewById(R.id.btnStop);
        btnScan.setOnClickListener(v -> start());
        btnStop.setOnClickListener(v -> stop());
        new InitTask().execute();
    }

    @Override
    protected void onDestroy() {
        Log.i(TAG, "onDestroy");
        close();
        super.onDestroy();
        android.os.Process.killProcess(Process.myPid());
    }


    public class InitTask extends AsyncTask<String, Integer, Boolean> {
        ProgressDialog mypDialog;

        @Override
        protected Boolean doInBackground(String... params) {
            open();
            return true;
        }

        @Override
        protected void onPostExecute(Boolean result) {
            super.onPostExecute(result);
            mypDialog.cancel();
        }

        @Override
        protected void onPreExecute() {
            super.onPreExecute();
            mypDialog = new ProgressDialog(MainActivity.this);
            mypDialog.setProgressStyle(ProgressDialog.STYLE_SPINNER);
            mypDialog.setMessage("init...");
            mypDialog.setCanceledOnTouchOutside(false);
            mypDialog.setCancelable(false);
            mypDialog.show();
        }
    }

    private void start() {
        barcodeDecoder.startScan();
    }

    private void stop() {
        barcodeDecoder.stopScan();
    }

    private void open() {
        barcodeDecoder.open(this);

            /*TODO
            BarcodeUtility.getInstance().setPrefix(this,"");
            BarcodeUtility.getInstance().setSuffix(this,"");
            BarcodeUtility.getInstance().enablePlaySuccessSound(this,true); //success Sound
            BarcodeUtility.getInstance().enableVibrate(this,true);//vibrate
            BarcodeUtility.getInstance().enableEnter(this,true);//addition enter

            BarcodeUtility.getInstance().enableContinuousScan(this,true);//Continuous scanning
            BarcodeUtility.getInstance().setContinuousScanIntervalTime(this,100);//Unit: milliseconds
            BarcodeUtility.getInstance().setContinuousScanTimeOut(this,9999);//Unit: milliseconds
            */

        barcodeDecoder.setDecodeCallback(new BarcodeDecoder.DecodeCallback() {
            @Override
            public void onDecodeComplete(BarcodeEntity barcodeEntity) {
                if (barcodeEntity.getResultCode() == BarcodeDecoder.DECODE_SUCCESS) {
                    tvData.setText("data:" + barcodeEntity.getBarcodeData());
                } else {
                    tvData.setText("fail");
                }
            }
        });
    }

    private void close() {
        barcodeDecoder.close();
    }


}
