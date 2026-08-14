

using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

using Android.App;
using Android.Content;
using Android.OS;
using Android.Runtime;
using Android.Views;
using Android.Widget;
using System.Threading;
using Android.Media;
using demo_uhf_uart;
using System.Collections;
using Com.Rscja.Deviceapi;
using static Android.Views.View;
using Com.Rscja.Deviceapi.Entity;

namespace UHF
{
    [Activity(Label = "Scan_Fragment")]
    public class Scan_Fragment : Fragment
    {
        MainActivity mContext;
        RadioButton rdoBtn_singleScan;
        RadioButton rdoBtn_continuous;
        Button btnScan;
        Button btnFilter;
        TextView tvTotal;
        Button btnClear;
        bool loopFlag = false;
     
        UIHand handler;
        private List<IDictionary<string, object>> tagList;
        private List<string> epcList=new List<string>();
        ListView LvTags;
        SimpleAdapter adapter;
        PopupWindow popFilter;  
        int startTime = System.Environment.TickCount;
        public override View OnCreateView(LayoutInflater inflater, ViewGroup container, Bundle savedInstanceState)
        {
            View view = inflater.Inflate(Resource.Layout.Scan_Fragment, container, false);
            return view;
        }
        public override void OnActivityCreated(Bundle savedInstanceState)
        {
            base.OnActivityCreated(savedInstanceState);
            mContext = (MainActivity)Activity;
            rdoBtn_singleScan = View.FindViewById<RadioButton>(Resource.Id.rdoBtn_singleScan);
            rdoBtn_continuous = View.FindViewById<RadioButton>(Resource.Id.rdoBtn_continuous);
            rdoBtn_continuous.Checked = true;
            btnScan = View.FindViewById<Button>(Resource.Id.btnScan);
            btnFilter = View.FindViewById<Button>(Resource.Id.btnFilter);
            LvTags = View.FindViewById<ListView>(Resource.Id.LvTags);
            btnClear = View.FindViewById<Button>(Resource.Id.btnClear);
            tvTotal = View.FindViewById<TextView>(Resource.Id.tvTotal);
            tagList = new List<IDictionary<string, object>>();
            adapter = new SimpleAdapter(mContext, tagList, Resource.Layout.listtag_items,
                new String[] { "tagUhfData", "tagLen", "tagCount", "tagRssi" },
                new int[] { Resource.Id.TvTagUii, Resource.Id.TvTagLen, Resource.Id.TvTagCount,
                    Resource.Id.TvTagRssi });
            LvTags.Adapter = adapter;

            btnScan.Click += delegate
            {
                scan();
            };

            btnClear.Click += delegate
            {
                Clear();
            };
            btnFilter.Click += delegate
            {

                AlertDialog.Builder builder = new AlertDialog.Builder( mContext);
                builder.SetTitle("");
                View view = LayoutInflater.From(mContext).Inflate(Resource.Layout.popwindow_filter2, null);
                EditText etptr = view.FindViewById<EditText>(Resource.Id.etPtr);
                EditText etlen = view.FindViewById<EditText>(Resource.Id.etLen);
                EditText etdata = view.FindViewById<EditText>(Resource.Id.etData);
                RadioButton rbepc = view.FindViewById<RadioButton>(Resource.Id.rbEPC);
                RadioButton rbtid = view.FindViewById<RadioButton>(Resource.Id.rbTID);
                RadioButton rbuser = view.FindViewById<RadioButton>(Resource.Id.rbUser);
                Button btnset = view.FindViewById<Button>(Resource.Id.btSet);
                Button btnsetno = view.FindViewById<Button>(Resource.Id.btSetNo);
                Button btnexit= view.FindViewById<Button>(Resource.Id.btExit);
                builder.SetView(view);


                AlertDialog dialog = builder.Create();
                dialog.Show();
                btnset.Click += delegate
                {
                    if (string.IsNullOrEmpty(etptr.Text.Trim().ToString()))
                    {
                        Toast.MakeText(mContext, "Start Address is null", ToastLength.Short).Show();
                        return;
                    }
                    if (string.IsNullOrEmpty(etlen.Text.Trim().ToString()))
                    {
                        Toast.MakeText(mContext, "Length is null", ToastLength.Short).Show();
                        return;
                    }

                    int ptr = int.Parse(etptr.Text.Trim());
                    int len = int.Parse(etlen.Text.Trim());
                    String data = etdata.Text.Trim();
                    if (len > 0)
                    {
                        int bank = RFIDWithUHFUART.InterfaceConsts.BankEPC;
                        if (rbepc.Checked)
                            bank = RFIDWithUHFUART.InterfaceConsts.BankEPC;
                        else if (rbtid.Checked)
                            bank = RFIDWithUHFUART.InterfaceConsts.BankTID;
                        else if (rbuser.Checked)
                            bank = RFIDWithUHFUART.InterfaceConsts.BankUSER;

                        bool re = mContext.uhfAPI.SetFilter(bank, ptr, len, data);
                        if (re)
                        {
                            Toast.MakeText(mContext, "Set Success", ToastLength.Short).Show();
                            dialog.Dismiss();
                            return;
                        }
                        else
                        {
                            Toast.MakeText(mContext, "Set Fail", ToastLength.Short).Show();
                        }
                    }

                };


                btnsetno.Click += delegate
                {
                    int bank;
                    if (rbepc.Checked)
                        bank = RFIDWithUHFUART.InterfaceConsts.BankEPC;
                    else if (rbtid.Checked)
                        bank = RFIDWithUHFUART.InterfaceConsts.BankTID;
                    else if (rbuser.Checked)
                        bank = RFIDWithUHFUART.InterfaceConsts.BankUSER;
                    else
                        bank = RFIDWithUHFUART.InterfaceConsts.BankEPC;

                    bool re = mContext.uhfAPI.SetFilter(bank, 0, 0, "00");
                    if (re)
                    {
                        Toast.MakeText(mContext, "No Set Success", ToastLength.Short).Show();
                        dialog.Dismiss();
                        return;
                    }
                    else
                    {
                        Toast.MakeText(mContext, "No Set Fail", ToastLength.Short).Show();
                    }
                };

                btnexit.Click += delegate { dialog.Dismiss();return; };
            };
            handler = new UIHand(this);
        }


        public override void OnPause()
        {
            StopInventory();
            base.OnPause();
        }
       
        public void scan()
        {
            if (btnScan.Text == "Stop")
            {
                StopInventory(); // 停止识别
                return;
            }
            if (!loopFlag)
            {
                if (rdoBtn_continuous.Checked)
                { //连续扫描标签
                    if (mContext.uhfAPI.StartInventoryTag())
                    {
                        startTime = System.Environment.TickCount;
                        loopFlag = true;
                        btnScan.Text = "Stop";
                        rdoBtn_singleScan.Enabled = false;
                        rdoBtn_continuous.Enabled = false;
                        btnFilter.Enabled = false;
                        btnClear.Enabled = false;
                        ContinuousRead();
                    }
                    else
                    {
                        Toast.MakeText(mContext, "failuer", ToastLength.Short).Show();
                    }
                }
                else
                {
                    //单步扫描标签
                    UHFTAGInfo info = mContext.uhfAPI.InventorySingleTag();
                    if (info!=null)
                    {
                        AddEPCToList(info);
                    }
                    else
                    {
                        Toast.MakeText(mContext, "failuer", ToastLength.Short);
                    }
                }
            }
        }
        private void Clear()
        {
            tvTotal.Text = "0";//.setText("0");
            tagList.Clear();
            epcList.Clear();
            LvTags.Adapter = null;
            adapter.NotifyDataSetChanged();
        }

        private void ContinuousRead()
        {
            Thread th = new Thread(new ThreadStart(delegate
            {
                while (loopFlag)
                {
                    UHFTAGInfo info = mContext.uhfAPI.ReadTagFromBuffer();
                    if (info != null)
                    {
                        Message msg = handler.ObtainMessage();
                        msg.Obj = info;
                        handler.SendMessage(msg);
                    }
                    else {
                        Thread.Sleep(2);
                    }
                }
            }));
            th.IsBackground = true;
            th.Start();
        }
        private void StopInventory()
        {
            if (loopFlag)
            {
                mContext.uhfAPI.StopInventory();
                loopFlag = false;
                btnScan.Text = "Scan";
                rdoBtn_singleScan.Enabled = true;
                rdoBtn_continuous.Enabled = true;
                btnFilter.Enabled = true;
                btnClear.Enabled = true;
            }
        }

        private class UIHand : Handler
        {
            Scan_Fragment scanFragment;
            public UIHand(Scan_Fragment _scanFragment)
            {
                scanFragment = _scanFragment;
            }
            public override void HandleMessage(Message msg)
            {
                try
                {
                    scanFragment.AddEPCToList((UHFTAGInfo)msg.Obj);
                }
                catch (Exception)
                {

                }

            }
        }



        private void AddEPCToList(UHFTAGInfo info)
        {
            if (!string.IsNullOrEmpty(info.EPC))
            {
               
                string data = mergeTidEpc(info.Tid, info.EPC, info.User);

                int s = System.Environment.TickCount;
                int index = checkIsExist(info.EPC);
                Android.Util.Log.Debug("zz","time="+(System.Environment.TickCount - s) );

                if (index == -1)
                {
                    JavaDictionary<string, object> map = new JavaDictionary<string, object>();
                    map.Add("tagEPC", info.EPC);
                    map.Add("tagUhfData", data);
                    map.Add("tagCount", "1");
                    map.Add("tagRssi", info.Rssi);
                    tagList.Add(map);
                    epcList.Add(info.EPC);
                }
                else
                {
                    int tagcount = int.Parse(tagList[index]["tagCount"].ToString()) + 1;
                    tagList[index]["tagCount"] = tagcount.ToString();
                    tagList[index]["tagUhfData"] = data;
                }

                mContext.soundUtils.PlaySound();
                if (System.Environment.TickCount - startTime > 500)
                {
                    
                    tvTotal.Text = adapter.Count.ToString();
                   
                  startTime = System.Environment.TickCount;
                  adapter = new SimpleAdapter(mContext, tagList, Resource.Layout.listtag_items,
                  new String[] { "tagUhfData", "tagLen", "tagCount", "tagRssi" },
                  new int[] { Resource.Id.TvTagUii, Resource.Id.TvTagLen, Resource.Id.TvTagCount,
                                     Resource.Id.TvTagRssi });
                  LvTags.Adapter = adapter;
                     
                }

            }
        }
        public int checkIsExist(string strEPC)
        {
            int existFlag = -1;
     
      
            for (int i = 0; i < epcList.Count; i++)
            {
                string tempStr = epcList[i];
                if (strEPC == tempStr)
                {
                    existFlag = i;
                    break;
                }
            }
            return existFlag;
        }

 


        private string mergeTidEpc(string tid, string epc, string user)
        {
            string data = "EPC:" + epc;
            if (!string.IsNullOrEmpty(tid) && !tid.Equals("0000000000000000") && !tid.Equals("000000000000000000000000"))
            {
                data += "\nTID:" + tid;
            }
            if (user != null && user.Length > 0)
            {
                data += "\nUSER:" + user;
            }
            return data;
        }


     




    }
}

