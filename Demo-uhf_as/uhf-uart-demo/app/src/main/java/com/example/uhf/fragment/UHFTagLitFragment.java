package com.example.uhf.fragment;

import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CheckBox;

import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.example.uhf.R;
import com.example.uhf.activity.UHFMainActivity;
import com.example.uhf.adapter.TagLedAdapter;
import com.rscja.deviceapi.entity.FilterEntity;
import com.rscja.deviceapi.entity.InventoryModeEntity;
import com.rscja.deviceapi.entity.UHFTAGInfo;
import com.rscja.deviceapi.interfaces.ConnectionStatus;
import com.rscja.deviceapi.interfaces.IUHF;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

public class UHFTagLitFragment extends KeyDwonFragment {
    private static final String TAG = "UHFTagLitFragment";

    private UHFMainActivity context;
    private Button btnInventory, btnClear;
    private CheckBox cbTagLed;
    private RecyclerView rvTagLed;
    private TagLedAdapter adapter;


    private final Handler handler = new Handler(Looper.getMainLooper());
    private final List<UHFTAGInfo> tagList = new ArrayList<>();
    /**
     * false - stop         停止
     * true  - inventory    盘点
     */
    private boolean inventoryFlag = false;

    // 盘点模式，进入时页面获取，退出页面重新设置
    private InventoryModeEntity inventoryMode = null;


    @Override
    public void onActivityCreated(Bundle savedInstanceState) {
        super.onActivityCreated(savedInstanceState);
        context = (UHFMainActivity) getActivity();
        context.currentFragment = this;
    }

    @Override
    public View onCreateView(LayoutInflater inflater, ViewGroup container, Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_uhf_tag_led, container, false);
        initView(view);
        return view;
    }

    @Override
    public void myOnKeyDwon() {
        toggleInventory();
    }

    @Override
    public void onStart() {
        super.onStart();

        handler.postDelayed(() -> {
            context.mReader.setInventoryCallback(uhftagInfo -> {
                handler.post(() -> adapter.addTagInfo(uhftagInfo));
                context.playSound(1);
            });
        }, 400);

        if (context != null && context.mReader.getConnectStatus() == ConnectionStatus.CONNECTED) {
            new Thread(() -> {
                SystemClock.sleep(100);
                inventoryMode = context.mReader.getEPCAndTIDUserMode();
                Log.d(TAG, "inventoryMode: " + inventoryMode);
            }).start();
        }

    }

    @Override
    public void onStop() {
        super.onStop();

        if (context != null && context.mReader.getConnectStatus() == ConnectionStatus.CONNECTED) {
            new Thread(() -> {
                SystemClock.sleep(100);

                if (inventoryFlag) {
                    context.mReader.stopInventory();
                    inventoryFlag = false;
                    cbTagLed.setEnabled(true);
                    btnInventory.setText(R.string.btnInventory);
                }

                if (inventoryMode != null) {
                    context.mReader.setEPCAndTIDUserMode(inventoryMode);
                }
                // 取消过滤
                context.mReader.setFilter(0, 0, 0, "");
            }).start();
        }
    }

    private void initView(View view) {
        btnInventory = view.findViewById(R.id.btnInventory);
        btnClear = view.findViewById(R.id.btnClear);
        cbTagLed = view.findViewById(R.id.cbTagLed);
        rvTagLed = view.findViewById(R.id.rvTagList);

        btnInventory.setOnClickListener(v -> toggleInventory());
        btnClear.setOnClickListener(v -> toggleClear());
        adapter = new TagLedAdapter(tagList);
        adapter.setTagLedClickListener((position, isChecked) -> {
            if (inventoryFlag) {
                context.showToast(R.string.title_stop_read_card);
                return false;
            }
            return true;
        });
        rvTagLed.setAdapter(adapter);
        rvTagLed.setLayoutManager(new LinearLayoutManager(getContext()));
    }

    private void toggleClear() {
        adapter.clear();
    }

    private void toggleInventory() {
        if (inventoryFlag) {
            stopInventory();
        } else {
            startInventory();
        }
    }

    private void startInventory() {
        // set filter. 设置过滤
        List<FilterEntity> filterList = new ArrayList<>();
        for (int i = 0; i < tagList.size(); i++) {
            UHFTAGInfo uhftagInfo = tagList.get(i);
            if (Objects.equals(uhftagInfo.getExtraData("STATE"), "1")) {
                // reset tag state. 重置标签状态
                uhftagInfo.setExtraData("STATE", "0");
                adapter.notifyItemChanged(i);
            }
            if (Objects.equals(uhftagInfo.getExtraData("CHECKED"), "1")) {
                FilterEntity filterEntity = new FilterEntity(IUHF.Bank_EPC, 32, uhftagInfo.getEPC().length() * 4, uhftagInfo.getEPC());
                filterList.add(filterEntity);
            }
        }
        if (!context.mReader.setFilter(filterList)) {
            context.showToast(R.string.fail);
            return;
        }

        // set inventoryMode param. 设置盘点模式
        if (!context.mReader.setEPCAndTIDUserMode(
                new InventoryModeEntity
                        .Builder()
                        .setMode(cbTagLed.isChecked() ? InventoryModeEntity.MODE_LED_TAG : InventoryModeEntity.MODE_EPC)
                        .build()
        )) {
            context.showToast(R.string.fail);
            return;
        }

        // start inventory. 开始盘点
        if (context.mReader.startInventoryTag()) {
            inventoryFlag = true;
            cbTagLed.setEnabled(false);
            btnInventory.setText(getString(R.string.title_stop));
        }
    }


    private void stopInventory() {
        if (context.mReader.stopInventory()) {
            inventoryFlag = false;
            cbTagLed.setEnabled(true);
            btnInventory.setText(getString(R.string.btnInventory));
        }
    }

}