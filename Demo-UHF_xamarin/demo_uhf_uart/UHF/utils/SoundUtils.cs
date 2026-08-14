using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading;
using Android;
using Android.App;
using Android.Content;
using Android.Media;
using Android.OS;
using Android.Runtime;
using Android.Views;
using Android.Widget;

namespace demo_uhf_uart
{
    public class SoundUtils
    {
        private SoundPool soundPool;
        private int soundPoolId_SUCCESS, soundPoolId_FAIL;
        public SoundUtils(Context context)
        {
            soundPool = new SoundPool(10, Stream.Music, 0);
            soundPoolId_SUCCESS = soundPool.Load(context, Resource.Drawable.beep, 1);
            //soundPoolId_FAIL = soundPool.Load(context, Resource.Raw.serror, 1);
        }
    
        private void Fail()
        {
            //第一个参数为id
            //第二个和第三个参数为左右声道的音量控制
            //第四个参数为优先级，由于只有这一个声音，因此优先级在这里并不重要

            //第五个参数为是否循环播放，0为不循环，-1为循环
            //
            //最后一个参数为播放比率，从0.5到2，一般为1，表示正常播放。
            soundPool.Play(soundPoolId_FAIL, 1, 1, 0, 0, 1);

        }
        public void PlaySound()
        {
            //第一个参数为id
            //第二个和第三个参数为左右声道的音量控制
            //第四个参数为优先级，由于只有这一个声音，因此优先级在这里并不重要

            //第五个参数为是否循环播放，0为不循环，-1为循环
            //
            //最后一个参数为播放比率，从0.5到2，一般为1，表示正常播放。
            soundPool.Play(soundPoolId_SUCCESS, 1, 1, 0, 0, 1);

        }

        //---------------------------------------------
        /*
        private Thread thPlaySound = null;
        private bool isStop = false;
        private AutoResetEvent waitPlaySound = new AutoResetEvent(false);
        public void startPlaySoundThread()
        {
            if (thPlaySound == null)
            {
                isStop = false;
                thPlaySound = new Thread(PlaySoundThread);
                thPlaySound.IsBackground = true;
                thPlaySound.Start();
            }
        }
        private void PlaySoundThread()
        {
            while (!isStop)
            {
                waitPlaySound.WaitOne(-1, false);
                if (!isStop)
                {
                    Success();
                }
            }
        }
        public void PlaySound()
        {
            waitPlaySound.Set();
        }
        public void FreeSound() {
            isStop = true;
            waitPlaySound.Set();
            thPlaySound = null;
        }
       */
    }
}