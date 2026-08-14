package com.example.uhf.adapter;

import android.graphics.Color;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.CheckBox;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import com.example.uhf.AppContext;
import com.example.uhf.R;
import com.example.uhf.tools.CheckUtils;
import com.example.uhf.tools.ToastUtil;
import com.rscja.deviceapi.entity.UHFTAGInfo;

import java.util.List;
import java.util.Objects;

public class TagLedAdapter extends RecyclerView.Adapter<TagLedAdapter.ViewHolder> {
    private static final String TAG = "TagLedAdapter";
    List<UHFTAGInfo> tagList;

    // 当前选择过滤（已勾选）的标签个数
    private int checkedCount = 0;
    private final int CHECK_COUNT_MAX = 8;

    private OnTagLedClickListener mOnTagLedClickListener;

    public TagLedAdapter(List<UHFTAGInfo> list) {
        this.tagList = list;
    }

    public void setTagLedClickListener(OnTagLedClickListener listener) {
        this.mOnTagLedClickListener = listener;
    }

    @NonNull
    @Override
    public ViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View view = LayoutInflater.from(parent.getContext()).inflate(R.layout.item_tag_led, parent, false);
        return new ViewHolder(view);
    }

    @Override
    public void onBindViewHolder(@NonNull ViewHolder holder, int position) {
        holder.itemView.setTag(position);
        UHFTAGInfo uhftagInfo = tagList.get(position);
//        String tagStr = "";
//        if (StringUtility.isEmpty(uhftagInfo.getTid())) {
//            tagStr = uhftagInfo.getEPC();
//        } else {
//            tagStr = "EPC: " + uhftagInfo.getEPC() + "\nTID: " + uhftagInfo.getTid();
//        }
        holder.tvTag.setText(uhftagInfo.getEPC());
        holder.tvTagCount.setText(String.valueOf(uhftagInfo.getCount()));
        holder.tvTagState.setText(Objects.equals(tagList.get(position).getExtraData("STATE"), "1") ? "✅" : "");
        if (Objects.equals(tagList.get(position).getExtraData("CHECKED"), "1")) {
            holder.cbTagLed.setChecked(true);
            holder.tagItem.setBackgroundColor(AppContext.getInstance().getColor(R.color.lightblue3));
        } else {
            holder.cbTagLed.setChecked(false);
            holder.tagItem.setBackgroundColor(Color.TRANSPARENT);
        }

        holder.cbTagLed.setOnClickListener(v -> {
            int adapterPosition = holder.getAdapterPosition();

            // 不允许修改
            if (mOnTagLedClickListener != null
                    && !mOnTagLedClickListener.onTagLedClick(adapterPosition, holder.cbTagLed.isChecked())
            ) {
                holder.cbTagLed.setChecked(Objects.equals(tagList.get(adapterPosition).getExtraData("CHECKED"), "1"));
                return;
            }

            if (holder.cbTagLed.isChecked()) {
                checkedCount++;
            } else {
                checkedCount--;
            }

            if (checkedCount > CHECK_COUNT_MAX) {
                ToastUtil.show(R.string.msg_max_select_tag_8);
                checkedCount = CHECK_COUNT_MAX;
                holder.cbTagLed.setChecked(false);
                return;
            } else if (checkedCount < 0) {
                checkedCount = 0;
                holder.cbTagLed.setChecked(false);
            }

            tagList.get(adapterPosition).setExtraData("CHECKED", holder.cbTagLed.isChecked() ? "1" : "0");
            holder.tagItem.setBackgroundColor(holder.cbTagLed.isChecked() ? AppContext.getInstance().getColor(R.color.lightblue4) : Color.TRANSPARENT);
        });
    }

    public void addTagInfo(UHFTAGInfo uhftagInfo) {
        boolean[] exists = new boolean[1];
        int index = CheckUtils.getInsertIndex(tagList, uhftagInfo, exists);
        if (exists[0]) {
            tagList.get(index).setExtraData("STATE", "1");
            tagList.get(index).setCount(tagList.get(index).getCount() + uhftagInfo.getCount());
            notifyItemChanged(index);
        } else {
            uhftagInfo.setExtraData("STATE", "1");
            tagList.add(index, uhftagInfo);
            notifyDataSetChanged();
        }
    }

    @Override
    public int getItemCount() {
        return tagList.size();
    }

    public void clear() {
        tagList.clear();
        checkedCount = 0;
        notifyDataSetChanged();
    }


    static class ViewHolder extends RecyclerView.ViewHolder {
        LinearLayout tagItem;
        final CheckBox cbTagLed;
        final TextView tvTag;
        final TextView tvTagCount;
        final TextView tvTagState;

        public ViewHolder(@NonNull View itemView) {
            super(itemView);
            tagItem = itemView.findViewById(R.id.ll_tag_item);
            tvTag = itemView.findViewById(R.id.tv_tag);
            cbTagLed = itemView.findViewById(R.id.cb_tag_led);
            tvTagCount = itemView.findViewById(R.id.tv_tag_count);
            tvTagState = itemView.findViewById(R.id.tv_tag_state);
        }
    }

    public interface OnTagLedClickListener {
        /**
         * 标签LED点击事件
         *
         * @param position  标签位置
         * @param isChecked 是否选中
         * @return 是否处理
         */
        boolean onTagLedClick(int position, boolean isChecked);
    }

}
