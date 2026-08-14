using Android.App;
using Android.OS;
using Android.Support.V7.App;
using Android.Runtime;
using Android.Widget;
using static Android.Views.View;
using Android.Views;
using Com.Rscja.Barcode;
using System;
 
using Com.Rscja.Deviceapi.Entity;
using System.Threading;
using static Com.Rscja.Barcode.BarcodeDecoder;

namespace demo_barcode2D
{
    [Activity(Label = "@string/app_name", Theme = "@style/AppTheme", MainLauncher = true)]
    public class MainActivity : AppCompatActivity, IOnClickListener
    {
        private Button btnStopScan;  
        private Button btnStartScan;
        private TextView tvData;
        private BarcodeDecoder barcodeDecoder = BarcodeFactory.Instance.BarcodeDecoder;
 
        protected override void OnCreate(Bundle savedInstanceState)
        {
            base.OnCreate(savedInstanceState);
            // Set our view from the "main" layout resource
            SetContentView(Resource.Layout.activity_main);
            btnStopScan = FindViewById<Button>(Resource.Id.btnStop);
            btnStartScan = FindViewById<Button>(Resource.Id.btnScan);
            tvData = FindViewById<TextView>(Resource.Id.tvData);
            btnStopScan.SetOnClickListener(this);
            btnStartScan.SetOnClickListener(this);
            open();
        }

        protected override void OnDestroy()
        {
            close();
            base.OnDestroy();
        }

        public void OnClick(View v)
        {
            switch (v.Id) {
                case Resource.Id.btnScan:
                    scan();
                    break;
                case Resource.Id.btnStop:
                    stop();
                    break;
            }
        }

        public void open() {
            barcodeDecoder.Open(this);
            barcodeDecoder.SetDecodeCallback(new DecodeCallback(this));
            Thread.Sleep(1000);
        }

        public void close() {
            barcodeDecoder.Close();
        }

        public void scan() {
            barcodeDecoder.StartScan();
        }

        public void stop() {
            barcodeDecoder.StopScan();
        }
 
     
        class DecodeCallback : Java.Lang.Object, IDecodeCallback
        {
            MainActivity mainActivity;
            public DecodeCallback(MainActivity mainActivity) {
                this.mainActivity = mainActivity;
            }
            public void OnDecodeComplete(BarcodeEntity entity)
            {
                if (entity.BarcodeData == null)
                {
                    mainActivity.tvData.Text = "fail";
                }
                else
                {
                    mainActivity.tvData.Text = entity.BarcodeData;
                }              
            }
        }
    }
}