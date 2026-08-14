
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
using demo_uhf_uart;
namespace UHF
{
	[Activity (Label = "Write_Fragment")]			
	public class Write_Fragment : Fragment
	{
	 
		MainActivity mContext;
		EditText edtTxtAddress_W;
		EditText edtTxtLeng_W;
		EditText edtTxtPassword_W;
		EditText edtTxtData_W;
		Button btnWriteData;
		Spinner spnBank_W;
		public override View OnCreateView(LayoutInflater inflater, ViewGroup container,Bundle savedInstanceState)
		{
			View view = inflater.Inflate(Resource.Layout.WriteData_Fragment,container,false);
			return view;
		}
		public override void OnActivityCreated(Bundle savedInstanceState) {
			base.OnActivityCreated (savedInstanceState);

			mContext = (MainActivity)Activity;

			edtTxtAddress_W = (EditText)View.FindViewById (Resource.Id.edtTxtAddress_W);
			edtTxtLeng_W = (EditText)View.FindViewById (Resource.Id.edtTxtLeng_W);
			edtTxtPassword_W= (EditText)View.FindViewById (Resource.Id.edtTxtPassword_W);
			edtTxtData_W = (EditText)View.FindViewById (Resource.Id.edtTxtData_W);
			btnWriteData = (Button)View.FindViewById (Resource.Id.btnWriteData);
			spnBank_W = (Spinner)View.FindViewById (Resource.Id.spnBank_W);

            spnBank_W.SetSelection(3);
            btnWriteData.Click += delegate {
				write() ;
			};
 
		}

        private void write()
        {
            try
            {
                string ptrStr = edtTxtAddress_W.Text.Trim();
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

                string cntStr = edtTxtLeng_W.Text.Trim();
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

                string pwdStr = edtTxtPassword_W.Text.Trim();
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


                string strData = edtTxtData_W.Text.Trim();// 要写入的内容

                if (strData == string.Empty)
                {
                    Toast.MakeText(mContext, "Write data can not be empty!", ToastLength.Short).Show();
                    return;
                }
                else if (!Comm.isHex(strData))
                {
                    Toast.MakeText(mContext, "Please enter the hexadecimal number content!", ToastLength.Short).Show();
                    return;
                }
                else if ((strData.Length) % 4 != 0)
                {
                    Toast.MakeText(mContext, "Write data of the length of the string must be in multiples of four!", ToastLength.Short).Show();
                    return;
                }


                int bank = spnBank_W.SelectedItemPosition;
                bool result = mContext.uhfAPI.WriteData(pwdStr, bank, int.Parse(ptrStr), int.Parse(cntStr), strData);// 返回的UII
                if (result)
                {
                    Toast.MakeText(mContext, "Write data successfully!", ToastLength.Short).Show();
                    mContext.soundUtils.PlaySound();
                }
                else
                {
                    Toast.MakeText(mContext, "Write data failure!", ToastLength.Short).Show();
                }
            }
            catch
            {
            }
        }

 
	}
}

