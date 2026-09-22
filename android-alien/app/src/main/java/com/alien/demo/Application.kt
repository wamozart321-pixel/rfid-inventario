package com.alien.demo

import android.content.Context

/**
 * Réplica de la Application de la demo de Alien. El SDK RFID podría buscar el
 * contexto por este nombre exacto (com.alien.demo.Application.getContext());
 * así queda satisfecho aunque no lo necesite. Se declara como android:name en
 * el manifest, de modo que Android la crea al arrancar la app.
 */
class Application : android.app.Application() {
    override fun onCreate() {
        super.onCreate()
        mContext = applicationContext
    }
    companion object {
        @JvmStatic
        private var mContext: Context? = null
        @JvmStatic
        fun getContext(): Context? = mContext
    }
}
