package com.example.uhf.tools;

import android.annotation.SuppressLint;
import android.inputmethodservice.Keyboard;
import android.os.Build;
import android.os.Environment;
import android.text.TextUtils;
import android.util.Log;
import android.util.Xml;

import com.example.uhf.AppContext;

import org.xmlpull.v1.XmlPullParser;
import org.xmlpull.v1.XmlSerializer;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.io.Writer;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
import java.util.List;

import jxl.Cell;
import jxl.Workbook;
import jxl.write.Label;
import jxl.write.WritableSheet;
import jxl.write.WritableWorkbook;
import jxl.write.WriteException;
import jxl.write.biff.RowsExceededException;

/**
 * Created by Administrator on 2017-5-22.
 */

public class FileUtils {
    static String TAG = "FileUtils";
    public static String ADDR = "btaddress";
    public static String NAME = "btname";
    public static String filePath = Environment.getExternalStorageDirectory() + File.separator + "BTDeviceList.xml";

    public static void saveXmlList(List<String[]> data) {
        try {
            File file = new File(filePath);
            if (file.exists()) {
                file.delete();
            }
            FileOutputStream fos = new FileOutputStream(file);
            // 获得一个序列化工具
            XmlSerializer serializer = Xml.newSerializer();
            serializer.setOutput(fos, "utf-8");
            // 设置文件头
            serializer.startDocument("utf-8", true);
            serializer.startTag(null, "root");
            for (int i = 0; i < data.size(); i++) {
                serializer.startTag(null, "bt");
                // 蓝牙地址
                serializer.startTag(null, ADDR);
                serializer.text(data.get(i)[0]);
                serializer.endTag(null, ADDR);
                // 蓝牙名称
                serializer.startTag(null, NAME);
                serializer.text(data.get(i)[1]);
                serializer.endTag(null, NAME);
                serializer.endTag(null, "bt");
            }
            serializer.endTag(null, "root");
            serializer.endDocument();
            fos.close();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    public static ArrayList<String[]> readXmlList() {
        ArrayList<String[]> list = new ArrayList<String[]>();
        try {
            File path = new File(filePath);
            if (!path.exists()) {
                return list;
            }
            FileInputStream fis = new FileInputStream(path);

            // 获得pull解析器对象

            XmlPullParser parser = Xml.newPullParser();
            // 指定解析的文件和编码格式
            parser.setInput(fis, "utf-8");
            int eventType = parser.getEventType(); // 获得事件类型
            String addr = null;
            String name = null;
            while (eventType != XmlPullParser.END_DOCUMENT) {
                String tagName = parser.getName(); // 获得当前节点的名称
                switch (eventType) {
                    case XmlPullParser.START_TAG: // 当前等于开始节点
                        if ("root".equals(tagName)) { //
                        } else if ("bt".equals(tagName)) { //
                        } else if (ADDR.equals(tagName)) { // <name>
                            addr = parser.nextText();
                        } else if (NAME.equals(tagName)) { // <age>
                            name = parser.nextText();
                        }
                        break;
                    case XmlPullParser.END_TAG: // </persons>
                        if ("bt".equals(tagName)) {
                            Log.i(TAG, "addr---" + addr);
                            Log.i(TAG, "name---" + name);
                            String[] str = new String[2];
                            str[0] = addr;
                            str[1] = name;
                            list.add(str);
                        }
                        break;
                    default:
                        break;
                }
                eventType = parser.next(); // 获得下一个事件类型
            }
        } catch (Exception e) {
            e.printStackTrace();
        } finally {
        }
        return list;
    }

    public static void clearXmlList() {
        List<String[]> list = readXmlList();
        list.clear();
        saveXmlList(list);
    }

    public static void writeFile(String fileName, List<String> data, boolean append) {
        /*int index = fileName.lastIndexOf(File.separator);
        Log.e("TEST", "index = " + index);
        if (index != -1) {
            File filePath = new File(fileName.substring(0, index));
            Log.e("TEST", "filePath = " + filePath);
            if (!filePath.exists()) {
                filePath.mkdirs();
            }
        }

        File file = new File(fileName);
        try {
            boolean created = file.createNewFile();
        } catch (IOException e) {
            e.printStackTrace();
        }
        if (!file.exists()) {
            try {
                file.createNewFile();
                Runtime runtime = Runtime.getRuntime();
                runtime.exec("chmod 0666 " + file);
            } catch (Exception ex) {
                ex.printStackTrace();
            }
        }
        FileOutputStream fileOutputStream = null;
        try {
            Log.e("TEST", "文件路径");
            // Log.e("TEST", "data.size() = " + data.size());
            fileOutputStream = new FileOutputStream(file, append);
            *//*String epc = "epc data\t";
            String tid = "tid data\t";
            String user = "user data\t";
            fileOutputStream.write(epc.getBytes());*//*
            Log.e("TEST", "data.size() = " + data.size());
            for (int i = 0; i < data.size(); i++) {
                String datas = data.get(i);
                Label label1 = new Label(i%3, i/3 + 1, data.get(i));
                fileOutputStream.write(label1.getBytes());
            }
        } catch (Exception e) {
            e.printStackTrace();
        } finally {
            try {
                fileOutputStream.flush();
                fileOutputStream.close();
            } catch (Exception e) {
            }
        }*/
        Log.e("TEST", "进入写入文件路径");
        try {
            WritableWorkbook workbook = Workbook.createWorkbook(new File(fileName));
            WritableSheet sheet = workbook.createSheet("Sheet1", 0);
            for (int i = 0; i < data.size(); i++) {
                if (i == 0) {
                    Label label = new Label(0, 0, "EPC Data");
                    sheet.addCell(label);
                    Label label1 = new Label(1, 0, "TID Data");
                    sheet.addCell(label1);
                    Label label2 = new Label(2, 0, "USER Data");
                    sheet.addCell(label2);
                }
                Label label = new Label(i%3, i/3+1, data.get(i));
                sheet.addCell(label);
            }
            workbook.write();
            workbook.close();
        } catch (IOException e) {
            e.printStackTrace();
        } catch (RowsExceededException e) {
            e.printStackTrace();
        } catch (WriteException e) {
            e.printStackTrace();
        }
    }

    private static String readInStream(FileInputStream inStream) {
        if(inStream==null)
            return null;
        try {
            ByteArrayOutputStream outStream = new ByteArrayOutputStream();
            byte[] buffer = new byte[512];
            int length = -1;
            while ((length = inStream.read(buffer)) != -1) {
                outStream.write(buffer, 0, length);
            }

            outStream.close();
            inStream.close();
            return outStream.toString();
        } catch (IOException e) {
            Log.e(TAG, e.getMessage());
        }
        return null;
    }

    /**
     * 读取文件内容
     *
     * @param path
     * @return
     */
    public static String readFile(String path) {

        FileInputStream fin = null;
        try {
            fin = new FileInputStream(path);
        } catch (FileNotFoundException e) {
            // TODO Auto-generated catch block
            e.printStackTrace();
            Log.e(TAG, e.getMessage());
        }

        return readInStream(fin);
    }

    /**
     * 保存crash到文件
     */
    @SuppressLint("SimpleDateFormat")
    public static void saveCrashFile(Throwable throwable) {
        try {
            File crashPathFile = new File(AppContext.DEFAULT_PATH + "error/");
            if (!crashPathFile.exists()) { // 创建文件夹
                crashPathFile.mkdirs();
            } else {
                File[] files = crashPathFile.listFiles();
                if (files != null && files.length > 20) {
                    Log.i(TAG, "files.length=" + files.length);
                    List<File> fileList = Arrays.asList(crashPathFile.listFiles());
                    Collections.sort(fileList, new Comparator<File>() {
                        @Override
                        public int compare(File o1, File o2) {
                            if (o1.isDirectory() && o2.isFile())
                                return -1;
                            if (o1.isFile() && o2.isDirectory())
                                return 1;
                            return o1.getName().compareTo(o2.getName());
                        }
                    });
//                    for (int k=0;k<fileList.size();k++) {
//                        LogUtils.d(TAG, "files.name="+fileList.get(k).getName());
//                    }
                    int c = files.length - 20;
                    for (int k = 0; k < c; k++) {
                        Log.i(TAG, "删除文件 files.name=" + fileList.get(k).getName());
                        fileList.get(k).delete();
                    }
                }

            }
            SimpleDateFormat df = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
            String time = df.format(new Date());

            SimpleDateFormat df2 = new SimpleDateFormat("yyyyMMdd");
            String time2 = df2.format(new Date());

            StringBuilder sb = new StringBuilder();
            sb.append("DateTime: ")
                    .append(time)
                    .append("\n");
            sb.append("DeviceInfo: ")
                    .append(Build.MANUFACTURER)
                    .append(" ")
                    .append(Build.MODEL)
                    .append("\n");
            sb.append("AppVersion: ")
                    .append(AppContext.getInstance().getVerName())
                    .append("_")
                    .append(AppContext.getInstance().getVerCode())
                    .append("\n");

            Writer writer = new StringWriter();
            PrintWriter pw = new PrintWriter(writer);
            throwable.printStackTrace(pw);
            Throwable cause = throwable.getCause();
            while (cause != null) {
                cause.printStackTrace(pw);
                cause = cause.getCause();
            }
            pw.close();
            String result = writer.toString();
            sb.append("Exception: \n");
            sb.append(result);
            Log.i(TAG, result); // 打印输出，方便开发调试
            // 记录异常到特定文件中
            File crashFile = new File(crashPathFile, "UHF-serial-" + time2 + ".txt");
            crashFile.setReadOnly();
            try {
                writer = new FileWriter(crashFile, true);
                writer.write(sb.toString());
                writer.write("\n");
                writer.flush();
                writer.close();
            } catch (IOException e) {
                Log.e(TAG, "Exception1  " + e.getMessage());
            }

        } catch (Exception exception) {
            Log.e(TAG, "Exception2  " + exception.getMessage());
        }

    }
}
