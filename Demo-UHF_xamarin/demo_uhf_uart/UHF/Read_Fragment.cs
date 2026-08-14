
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Android.Media;
using Android.App;
using Android.Content;
using Android.OS;
using Android.Runtime;
using Android.Views;
using Android.Widget;
using Com.Rscja.Deviceapi.Entity;
using Com.Rscja.Deviceapi;
using demo_uhf_uart;

namespace UHF
{
	[Activity (Label = "Read_Fragment")]			
	public class Read_Fragment : Fragment
	{
		 
		 
		MainActivity mContext;
		EditText edtTxtAddress_R;
		EditText edtTxtLeng_R;
		EditText edtTxtPassword_R;
		EditText edtTxtData_R;
		Button btnReadData;
		Spinner spnBank_R;
		public override View OnCreateView(LayoutInflater inflater, ViewGroup container,Bundle savedInstanceState)
		{
			View view = inflater.Inflate (Resource.Layout.ReadData_Fragment,container,false);
			return view;
		}
		public override void OnActivityCreated(Bundle savedInstanceState) {
			base.OnActivityCreated (savedInstanceState);

			mContext = (MainActivity)Activity;
		 
			edtTxtAddress_R=(EditText)View.FindViewById(Resource.Id.edtTxtAddress_R);
			edtTxtLeng_R=(EditText)View.FindViewById(Resource.Id.edtTxtLeng_R);
			edtTxtPassword_R=(EditText)View.FindViewById(Resource.Id.edtTxtPassword_R);
			edtTxtData_R=(EditText)View.FindViewById(Resource.Id.edtTxtData_R);
			btnReadData=(Button)View.FindViewById(Resource.Id.btnReadData);
			spnBank_R=(Spinner)View.FindViewById(Resource.Id.spnBank_R);
            spnBank_R.SetSelection(1);  

            btnReadData.Click += delegate {
				read();
			};
		 
		}
        private void read()
        {
            try
            {
                string ptrStr = edtTxtAddress_R.Text.Trim();
                if (ptrStr == string.Empty)
                {
                    Toast.MakeText(mContext, "Please input the address!", ToastLength.Short).Show();
                    return;
                }
                else if (!Comm.IsNumber(ptrStr))
                {
                    Toast.MakeText(mContext, "Address must be a decimal data!", ToastLength.Short).Show();
                    return;
                }

                string cntStr = edtTxtLeng_R.Text.Trim();
                if (cntStr == string.Empty)
                {
                    Toast.MakeText(mContext, "Length cannot be empty", ToastLength.Short).Show();
                    return;
                }
                else if (!Comm.IsNumber(cntStr))
                {
                    Toast.MakeText(mContext, "Length must be a decimal data!", ToastLength.Short).Show();
                    return;
                }

                string pwdStr = edtTxtPassword_R.Text.Trim();
                if (pwdStr != string.Empty)
                {
                    if (pwdStr.Length != 8)
                    {
                        Toast.MakeText(mContext, "The length of the access password must be 8!", ToastLength.Short).Show();
                        return;
                    }
                    else if (!Comm.isHex(pwdStr))
                    {
                        Toast.MakeText(mContext, "Please enter the hexadecimal number content!", ToastLength.Short).Show();
                        return;
                    }
                }
                else
                {
                    pwdStr = "00000000";
                }

                int bank = spnBank_R.SelectedItemPosition;
                string entity = mContext.uhfAPI.ReadData(pwdStr, bank, int.Parse(ptrStr), int.Parse(cntStr));
                if (!string.IsNullOrEmpty(entity))
                {

                    edtTxtData_R.Text = entity;
                    mContext.soundUtils.PlaySound();
                }
                else
                {
                    edtTxtData_R.Text = "";
                    Toast.MakeText(mContext, "Read failure!", ToastLength.Short).Show();
                }
            }
            catch
            {
            }
        }

 
	}
}

