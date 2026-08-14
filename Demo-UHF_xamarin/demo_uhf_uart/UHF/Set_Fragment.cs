
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

using Android.App;
using Android.Content;
using Android.OS;
using Android.Runtime;
using Android.Util;
using Android.Views;
using Android.Widget;
using Com.Rscja.Deviceapi.Entity;
using demo_uhf_uart;
namespace UHF
{
	public class Set_Fragment : Fragment
	{
        Button btnGetFre;
		Button btnSetFre;
		Button btnGetPower;
		Button btnSetPower;
 
		Spinner spnWorkMode;
		Spinner spnPower;
		MainActivity mContext;
        Spinner spnsession;
        Spinner spnInventoried;
        Button btnsessionset;
        Button btnsessionget;
        CheckBox chbepc;
        public override View OnCreateView(LayoutInflater inflater, ViewGroup container,Bundle savedInstanceState)
		{
            View view = inflater.Inflate (Resource.Layout.Set_Fragment, container, false);
			return view;
		}
		public override void OnActivityCreated(Bundle savedInstanceState) {
			base.OnActivityCreated (savedInstanceState);
		
			mContext = (MainActivity)Activity;
			btnGetFre = View.FindViewById<Button> (Resource.Id.btnGetFre);
			btnSetFre = View.FindViewById<Button> (Resource.Id.btnSetFre);
			btnGetPower = View.FindViewById<Button> (Resource.Id.btnGetPower);
			btnSetPower = View.FindViewById<Button> (Resource.Id.btnSetPower);
			spnWorkMode = View.FindViewById<Spinner> (Resource.Id.spnWorkMode);
			spnPower = View.FindViewById<Spinner> (Resource.Id.spnPower);
            spnsession = View.FindViewById<Spinner>(Resource.Id.spnSession);
            spnInventoried = View.FindViewById<Spinner>(Resource.Id.spnInventoried);
            btnsessionget = View.FindViewById<Button>(Resource.Id.btnGetSession);
            btnsessionset = View.FindViewById<Button>(Resource.Id.btnSetSession);
            chbepc = View.FindViewById<CheckBox>(Resource.Id.checkBox1);
            spnsession.SetSelection(1);
            spnInventoried.SetSelection(0);
         
           
            chbepc.CheckedChange += Chbepc_CheckedChange;

            btnGetFre.Click += delegate {
				GetFre();
			};
			btnSetFre.Click += delegate {
				SetFre();
			};
			btnGetPower.Click += delegate {
				GetPower();
			};
			btnSetPower.Click += delegate {
				SetPower();
			};
            btnsessionget.Click += Btnsessionget_Click;
            btnsessionset.Click += Btnsessionset_Click;
        }

        private void Chbepc_CheckedChange(object sender, CompoundButton.CheckedChangeEventArgs e)
        {
            if (chbepc.Checked)
                mContext.uhfAPI.SetEPCAndTIDMode();
            else
                mContext.uhfAPI.SetEPCMode();
        }

        private void Btnsessionset_Click(object sender, EventArgs e)
        {
            //设置SESSION只针对盘点EPC有效，对返回EPC+TID,EPC+TID+USER无效

            Gen2Entity p = mContext.uhfAPI.Gen2;
            if (p != null)
            {
                int seesionid = spnsession.SelectedItemPosition;
                int inventoried = spnInventoried.SelectedItemPosition;
                if (seesionid < 0 || inventoried < 0)
                {
                    return;
                }
                p.QueryTarget = inventoried;
                p.QuerySession = seesionid;
                if (mContext.uhfAPI.SetGen2(p))
                {
                    Toast.MakeText(mContext, "success!", ToastLength.Short).Show();
                }
                else
                {
                    Toast.MakeText(mContext, "failuer!", ToastLength.Short).Show();
                }
                
            }
            else {
                Toast.MakeText(mContext, "failuer!", ToastLength.Short).Show();
                
            }
           
        }

        private void Btnsessionget_Click(object sender, EventArgs e)
        {
            Gen2Entity p = mContext.uhfAPI.Gen2;
            if (p != null)
            {
                spnsession.SetSelection(p.QuerySession);
                spnInventoried.SetSelection(p.QueryTarget);
                Toast.MakeText(mContext, "success!", ToastLength.Short).Show();
            }
            else
            {
                Toast.MakeText(mContext, "failuer!", ToastLength.Short).Show();
            }
        }

        public override void OnResume() {
			base.OnResume();
			GetFre();
			GetPower();
		}
		private void SetFre()
		{
            sbyte iFre = (sbyte)getMode(spnWorkMode.SelectedItemPosition); ;

            

            if (mContext.uhfAPI.SetFrequencyMode(iFre)) 
			{
				Toast.MakeText (mContext,"success!",ToastLength.Short).Show();
			} 
			else 
			{
				Toast.MakeText (mContext,"failuer!",ToastLength.Short).Show();
			}

		}
		private void GetFre()
		{
			int mode = mContext.uhfAPI.FrequencyMode;

			if (mode != -1)
			{
                int idx=getModeIndex(mode);
				int count = spnWorkMode.Count;
				spnWorkMode.SetSelection(idx > count - 1 ? count - 1 : idx);
			} 
			else
			{
				Toast.MakeText (mContext,"failuer!",ToastLength.Short).Show();
			}
		}
			
		public void GetPower() {
			int iPower = mContext.uhfAPI.Power;
            if (iPower > -1) {
				int position = iPower - 1;
				int count = spnPower.Count;
				spnPower.SetSelection(position > count - 1 ? count - 1 : position);
			}
			else 
			{
				Toast.MakeText (mContext,"failuer!",ToastLength.Short).Show();
			}

		}
		public void SetPower() {
			int iPower = spnPower.SelectedItemPosition + 1;
		
			if (mContext.uhfAPI.SetPower(iPower)) 
			{
				Toast.MakeText (mContext,"success!",ToastLength.Short).Show();
			} 
			else 
			{
				Toast.MakeText (mContext,"failuer!",ToastLength.Short).Show();
			}
        }
   
        private int getModeIndex(int mode)
        {
            switch (mode)
            {
                case 0x01:
                    return 0;// GetString(Resource.String.China_Standard_840_845MHz);
                case 0x02:
                    return 1;//GetString(Resource.String.China_Standard_920_925MHz);
                case 0x04:
                    return 2;//GetString(Resource.String.ETSI_Standard);
                case 0x08:
                    return 3;//GetString(Resource.String.United_States_Standard);
                case 0x16:
                    return 4;//GetString(Resource.String.Korea);
                case 0x32:
                    return 5;//GetString(Resource.String.Japan);
                case 0x33:
                    return 6;//GetString(Resource.String.South_Africa_915_919MHz);
                case 0x34:
                    return 7;//GetString(Resource.String.TAIWAN);
                case 0x35:
                    return 8;//GetString(Resource.String.vietnam_918_923MHz);
                case 0x36:
                    return 9;//GetString(Resource.String.Peru_915_928MHz);
                case 0x37:
                    return 10;//GetString(Resource.String.Russia_860_867MHZ);
                case 0x80:
                    return 11;//GetString(Resource.String.Morocco);
                default:
                    return -1; 
            }
        }
        private int getMode(int index)
        {
            switch (index)
            {
                case 0:
                    return 0x01;// GetString(Resource.String.China_Standard_840_845MHz);
                case 1:
                    return 0x02;//GetString(Resource.String.China_Standard_920_925MHz);
                case 2:
                    return 0x04;//GetString(Resource.String.ETSI_Standard);
                case 3:
                    return 0x08;//GetString(Resource.String.United_States_Standard);
                case 4:
                    return 0x16;//GetString(Resource.String.Korea);
                case 5:
                    return 0x32;//GetString(Resource.String.Japan);
                case 6:
                    return 0x33;//GetString(Resource.String.South_Africa_915_919MHz);
                case 7:
                    return 0x34;//GetString(Resource.String.TAIWAN);
                case 8:
                    return 0x35;//GetString(Resource.String.vietnam_918_923MHz);
                case 9:
                    return 0x36;//GetString(Resource.String.Peru_915_928MHz);
                case 10:
                    return 0x37;//GetString(Resource.String.Russia_860_867MHZ);
                case 11:
                    return 0x80;//GetString(Resource.String.Morocco);
                default:
                    return -1;
            }
        }
    }
}

