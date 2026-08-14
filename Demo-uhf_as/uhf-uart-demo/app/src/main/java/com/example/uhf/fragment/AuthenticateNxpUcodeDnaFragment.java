package com.example.uhf.fragment;

import android.os.Bundle;

import androidx.fragment.app.Fragment;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.RadioButton;
import android.widget.Spinner;

import com.example.uhf.R;
import com.example.uhf.activity.UHFMainActivity;
import com.example.uhf.tools.StringUtils;
import com.rscja.deviceapi.RFIDWithUHFUART;
import com.rscja.deviceapi.entity.FilterEntity;
import com.rscja.utility.StringUtility;


public class AuthenticateNxpUcodeDnaFragment extends KeyDwonFragment implements View.OnClickListener {


    private CheckBox cb_filter;
    private EditText etPtr_filter;
    private EditText etLen_filter;
    private EditText etData_filter;
    private RadioButton rbEPC_filter;
    private RadioButton rbTID_filter;
    private RadioButton rbUser_filter;


    private EditText EtAccessPwd;
    private EditText EtData;
    private Button btnAuthenticate;
    private UHFMainActivity mContext;
    private EditText EtReslutData;
    private Spinner spKeyId;
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

    }

    @Override
    public View onCreateView(LayoutInflater inflater, ViewGroup container,
                             Bundle savedInstanceState) {
        // Inflate the layout for this fragment
        View view= inflater.inflate(R.layout.fragment_authenticate_nxp_ucode_dna, container, false);
        initView(view);
        return view;
    }
    @Override
    public void onActivityCreated(Bundle savedInstanceState) {
        super.onActivityCreated(savedInstanceState);
        mContext = (UHFMainActivity) getActivity();
        mContext.currentFragment = this;
    }
    private void initView(   View view) {
        cb_filter = view.findViewById(R.id.cb_filter);
        etPtr_filter =  view.findViewById(R.id.etPtr_filter);
        etLen_filter =  view.findViewById(R.id.etLen_filter);
        etData_filter = view. findViewById(R.id.etData_filter);
        rbEPC_filter =  view.findViewById(R.id.rbEPC_filter);
        rbTID_filter =  view.findViewById(R.id.rbTID_filter);
        rbUser_filter =  view.findViewById(R.id.rbUser_filter);

        spKeyId =  view.findViewById(R.id.spKeyId);
        spKeyId.setSelection(0);
        EtAccessPwd =  view.findViewById(R.id.EtAccessPwd);
        EtData =  view.findViewById(R.id.EtData);
        btnAuthenticate =  view.findViewById(R.id.btnAuthenticate);
        btnAuthenticate.setOnClickListener(this);
        EtReslutData =  view.findViewById(R.id.EtReslutData);
    }

    @Override
    public void onClick(View view) {
        switch (view.getId()) {
            case R.id.btnAuthenticate:

                try {
                    String strPWD = EtAccessPwd.getText().toString().trim();// 访问密码
                    if (StringUtils.isNotEmpty(strPWD)) {
                        if (strPWD.length() != 8) {
                            mContext.showToast(R.string.uhf_msg_addr_must_len8);
                            return;
                        } else if (!mContext.vailHexInput(strPWD)) {
                            mContext.showToast(R.string.rfid_mgs_error_nohex);
                            return;
                        }
                    } else {
                        strPWD = "00000000";
                    }

                    String strData = EtData.getText().toString().trim();// 要写入的内容
                    if (StringUtils.isEmpty(strData)) {
                        mContext.showToast("data can not be empty");
                        return;
                    } else if (!mContext.vailHexInput(strData)) {
                        mContext.showToast(R.string.rfid_mgs_error_nohex);
                        return;
                    }


                    FilterEntity filter = null;
                    if (cb_filter.isChecked()) { // 指定标签
                        if (etPtr_filter.getText().toString().isEmpty()) {
                            etPtr_filter.setText("0");
                        }
                        if (etLen_filter.getText().toString().isEmpty()) {
                            mContext.showToast(getString(R.string.uhf_msg_filter_len_not_null));
                            return;
                        }

                        int filterPtr = Integer.parseInt(etPtr_filter.getText().toString());
                        String filterData = etData_filter.getText().toString();
                        int filterCnt = Integer.parseInt(etLen_filter.getText().toString());
                        int filterBank = RFIDWithUHFUART.Bank_EPC;
                        if (rbEPC_filter.isChecked()) {
                            filterBank = RFIDWithUHFUART.Bank_EPC;
                        } else if (rbTID_filter.isChecked()) {
                            filterBank = RFIDWithUHFUART.Bank_TID;
                        } else if (rbUser_filter.isChecked()) {
                            filterBank = RFIDWithUHFUART.Bank_USER;
                        }
                        filter = new FilterEntity(filterBank, filterPtr, filterCnt, filterData);
                    }
                    int keyId = spKeyId.getSelectedItemPosition();
                    String result = mContext.mReader.authenticateNxpUcodeDna(strPWD, filter, (byte) keyId, strData);
                    if (result != null) {
                        EtReslutData.setText(result);
                        mContext.showToast("success");
                        mContext.playSound(1);
                    } else {
                        EtReslutData.setText("");
                        mContext.playSound(2);
                        mContext.showToast("fail");
                    }
                }catch (Exception ex){
                    EtReslutData.setText("");
                    mContext.playSound(2);
                    mContext.showToast(ex.getMessage());
                }
                break;
        }
    }
}

