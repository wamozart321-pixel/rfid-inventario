package com.inventario.movil

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.Context
import android.net.wifi.WifiManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import kotlin.concurrent.thread

/**
 * Inventario RFID — app de CONSULTA para celulares y tabletas.
 *
 * No lee RFID: solo abre la MISMA pantalla que se ve en el PC
 * (http://SERVIDOR:5000/escritorio) dentro de la aplicación. Por eso no
 * necesita ningún SDK y funciona en cualquier Android.
 *
 * La dirección del servidor se recuerda en el propio teléfono. Si el PC
 * principal cambia de IP, la app lo busca sola en la red: pregunta a cada
 * equipo por /api/quien y se queda con el que responda que es el inventario.
 *
 * FUERA DE LA BODEGA: se puede guardar además una dirección de internet
 * (https://…, la del túnel). Al abrir se prueba primero la de la bodega y,
 * si no contesta, se usa la de afuera; ahí el servidor pide usuario y
 * contraseña, y la sesión queda guardada en el teléfono.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var estado: TextView
    private val ui = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("cfg", Context.MODE_PRIVATE) }

    /** Modo con el que se abre: vacío = mostrador · principal · vendedor. */
    private val modo get() = prefs.getString("modo", "") ?: ""
    private var direccion: String
        get() = prefs.getString("servidor", "") ?: ""
        set(v) = prefs.edit().putString("servidor", v).apply()

    /** Dirección para fuera de la bodega (https://…). Vacía = no se usa. */
    private var afuera: String
        get() = prefs.getString("afuera", "") ?: ""
        set(v) = prefs.edit().putString("afuera", v).apply()

    /** La que se está usando ahora mismo: la de la bodega o la de afuera. */
    private var usandoAfuera = false

    private fun base(d: String) =
        if (d.startsWith("http://") || d.startsWith("https://")) d.trimEnd('/') else "http://$d"

    private val actual get() = if (usandoAfuera) afuera else direccion

    private val destino get() = base(actual) + "/escritorio" +
        when (modo) {
            "principal" -> "?modo=principal"
            "vendedor" -> "?modo=vendedor"
            else -> ""
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        estado = findViewById(R.id.estado)
        web = findViewById(R.id.web)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true      // aquí se recuerda el modo oscuro
            // La pantalla se adapta sola: en una tableta se ve como en el PC y
            // en un celular se acomoda. El zoom de dos dedos queda igual.
            useWideViewPort = true
            loadWithOverviewMode = true
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false
        }
        web.webViewClient = object : WebViewClient() {
            override fun onPageFinished(v: WebView?, url: String?) {
                if (url != null && url.startsWith("http")) estado.visibility = View.GONE
            }
            override fun onReceivedError(v: WebView?, req: WebResourceRequest?,
                                         err: WebResourceError?) {
                if (req?.isForMainFrame == true) noConecta()
            }
        }
        findViewById<Button>(R.id.btnConfig).setOnClickListener { dialogoConfig() }

        if (direccion.isBlank() && afuera.isBlank()) buscarServidor() else abrir()
    }

    /** Primero la bodega (rápido, sin clave); si no contesta, la de afuera. */
    private fun abrir() {
        estado.visibility = View.VISIBLE
        if (afuera.isBlank() || direccion.isBlank()) {
            usandoAfuera = direccion.isBlank()
            estado.text = "Conectando con $actual…"
            web.loadUrl(destino)
            revisarApp()
            return
        }
        estado.text = "Buscando el servidor en la bodega…"
        thread {
            val enBodega = quienEs(base(direccion)) != null
            ui.post {
                usandoAfuera = !enBodega
                estado.text = if (enBodega) "Conectando con $direccion…"
                              else "Fuera de la bodega: conectando por internet…"
                web.loadUrl(destino)
                revisarApp()
            }
        }
    }

    private fun noConecta() {
        estado.visibility = View.VISIBLE
        if (usandoAfuera) {
            // por internet no tiene sentido barrer la red de la casa o del café
            AlertDialog.Builder(this)
                .setTitle("Sin conexión")
                .setMessage("No contesta el servidor por internet ($afuera).\n\n" +
                            "Mira que el celular tenga datos o WiFi y que el PC " +
                            "del inventario esté prendido.")
                .setPositiveButton("Reintentar") { _, _ -> abrir() }
                .setNeutralButton("Ajustes") { _, _ -> dialogoConfig() }
                .setCancelable(false)
                .show()
            return
        }
        if (afuera.isNotBlank()) {
            usandoAfuera = true
            estado.text = "No contesta $direccion.\nProbando por internet…"
            web.loadUrl(destino)
            return
        }
        estado.text = "No contesta $direccion.\nBuscando el servidor en la red…"
        buscarServidor()
    }

    /** Pregunta a toda la red quién es el inventario. Lo mismo que hace el
     *  programa de los otros PCs: el servidor contesta en /api/quien. */
    private fun buscarServidor() {
        estado.visibility = View.VISIBLE
        estado.text = "Buscando el servidor del inventario en la red…"
        thread {
            val base = redLocal()
            if (base == null) {
                ui.post { pedirDireccion("No pude ver la red WiFi. Escribe la dirección:") }
                return@thread
            }
            val pool = Executors.newFixedThreadPool(48)
            val hallados = java.util.Collections.synchronizedList(ArrayList<Pair<String, String>>())
            for (n in 1..254) {
                val ip = "$base$n"
                pool.execute {
                    quienEs("http://$ip:5000")?.let { hallados.add(ip to it) }
                }
            }
            pool.shutdown()
            pool.awaitTermination(25, java.util.concurrent.TimeUnit.SECONDS)
            ui.post {
                when {
                    hallados.size == 1 -> {
                        direccion = hallados[0].first + ":5000"
                        abrir()
                    }
                    hallados.isEmpty() ->
                        pedirDireccion("No encontré el servidor. ¿Está prendido el PC " +
                                       "principal y con el programa abierto?")
                    else -> elegirServidor(hallados)
                }
            }
        }
    }

    private fun redLocal(): String? {
        return try {
            @Suppress("DEPRECATION")
            val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION")
            val ip = wm.connectionInfo.ipAddress
            if (ip == 0) null
            else "%d.%d.%d.".format(ip and 0xff, ip shr 8 and 0xff, ip shr 16 and 0xff)
        } catch (e: Exception) {
            null
        }
    }

    /** ¿En esa dirección está el servidor del inventario? Devuelve el nombre del PC. */
    private fun quienEs(dir: String): String? = try {
        val c = URL("$dir/api/quien").openConnection() as HttpURLConnection
        c.connectTimeout = 900
        c.readTimeout = 900
        val j = JSONObject(c.inputStream.bufferedReader().readText())
        if (j.optBoolean("inventario")) j.optString("nombre", dir) else null
    } catch (e: Exception) {
        null
    }

    private fun elegirServidor(lista: List<Pair<String, String>>) {
        val nombres = lista.map { "${it.second} — ${it.first}" }.toTypedArray()
        AlertDialog.Builder(this)
            .setTitle("¿Cuál es el servidor?")
            .setItems(nombres) { _, i ->
                direccion = lista[i].first + ":5000"
                abrir()
            }
            .setCancelable(false)
            .show()
    }

    private fun pedirDireccion(mensaje: String) {
        val campo = EditText(this).apply {
            hint = "192.168.0.5:5000"
            setText(direccion)
        }
        AlertDialog.Builder(this)
            .setTitle("Dirección del servidor")
            .setMessage(mensaje)
            .setView(campo)
            .setPositiveButton("Conectar") { _, _ ->
                var d = campo.text.toString().trim()
                if (d.isNotBlank()) {
                    if (d.startsWith("https://")) {
                        afuera = d.trimEnd('/')     // es la de internet
                    } else {
                        d = d.removePrefix("http://").trimEnd('/')
                        if (!d.contains(":")) d += ":5000"
                        direccion = d
                    }
                    abrir()
                }
            }
            .setNeutralButton("Buscar otra vez") { _, _ -> buscarServidor() }
            .setCancelable(false)
            .show()
    }

    /** La dirección de internet (la del túnel) para cuando se está fuera. */
    private fun pedirAfuera() {
        val campo = EditText(this).apply {
            hint = "https://inventario.xxxx.ts.net"
            setText(afuera)
        }
        AlertDialog.Builder(this)
            .setTitle("Dirección para fuera de la bodega")
            .setMessage("La que te dieron para entrar por internet. En la bodega se " +
                        "sigue usando la de siempre. Déjala vacía para no usarla.")
            .setView(campo)
            .setPositiveButton("Guardar") { _, _ ->
                var d = campo.text.toString().trim().trimEnd('/')
                if (d.isNotBlank() && !d.startsWith("http")) d = "https://$d"
                afuera = d
                abrir()
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    /** Ajustes: dirección y para qué se usa este teléfono. */
    private fun dialogoConfig() {
        val modos = arrayOf("Mostrador (consultar y modificar)",
                            "PC principal (además, Configuración)",
                            "Vendedor (solo consulta)")
        val claves = arrayOf("", "principal", "vendedor")
        AlertDialog.Builder(this)
            .setTitle("Ajustes")
            .setItems(arrayOf("Cambiar la dirección del servidor",
                              "Buscar el servidor en la red",
                              "Para qué se usa este equipo",
                              "Recargar la pantalla",
                              "Dirección para fuera de la bodega",
                              "Buscar actualización de la app")) { _, i ->
                when (i) {
                    0 -> pedirDireccion("Escribe la dirección del PC principal:")
                    1 -> { usandoAfuera = false; buscarServidor() }
                    2 -> AlertDialog.Builder(this)
                        .setTitle("Para qué se usa este equipo")
                        .setSingleChoiceItems(modos, claves.indexOf(modo)) { d, j ->
                            prefs.edit().putString("modo", claves[j]).apply()
                            d.dismiss()
                            abrir()
                        }.show()
                    3 -> abrir()
                    4 -> pedirAfuera()
                    5 -> revisarApp(forzar = true)
                }
            }
            .show()
    }

    override fun onResume() {
        super.onResume()
        Actualizador.alVolver(this)
        revisarApp()
    }

    /** La app se pone al día sola desde el servidor (android-comun/Actualizador.kt).
     *  Desde afuera se le pasa la sesión, porque allí el servidor pide entrar. */
    private fun revisarApp(forzar: Boolean = false) {
        if (actual.isBlank()) return
        val galleta = if (usandoAfuera) CookieManager.getInstance().getCookie(base(afuera)) else null
        Actualizador.revisar(this, base(actual), galleta, forzar)
    }

    override fun onPause() {
        super.onPause()
        // que la sesión de afuera no se pierda si Android cierra la app
        CookieManager.getInstance().flush()
    }

    @Deprecated("Se necesita el comportamiento clásico del botón atrás")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack()
        else {
            @Suppress("DEPRECATION")
            super.onBackPressed()
        }
    }
}
