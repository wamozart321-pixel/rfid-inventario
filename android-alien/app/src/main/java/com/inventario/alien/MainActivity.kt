package com.inventario.alien

import android.app.Activity
import android.app.AlertDialog
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.widget.*
import com.alien.barcode.BarcodeCallback
import com.alien.barcode.BarcodeReader
import com.alien.rfid.RFID
import com.alien.rfid.RFIDCallback
import com.alien.rfid.RFIDReader
import com.alien.rfid.SearchMode
import com.alien.rfid.Session
import com.alien.rfid.Tag
import com.alien.rfid.Target
import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL
import java.util.Collections
import java.util.concurrent.Executors
import kotlin.concurrent.thread

/**
 * Lector de inventario para la pistola ALIEN ALR-H450 (Android 4.4).
 * Es la misma app de la Chainway C72 pero con el SDK de Alien (com.alien.rfid.*
 * + escáner 2D com.alien.barcode.*). Manda las lecturas al MISMO servidor.
 *
 * Teclas ALR-H450: gatillo/scan = 139 (RFID) · laterales 136/137 (código 2D).
 */
class MainActivity : Activity(), RFIDCallback {

    private var reader: RFIDReader? = null
    private var barcode: BarcodeReader? = null
    private var barError: String? = null
    private var wifiLock: android.net.wifi.WifiManager.WifiLock? = null
    private var tono: android.media.ToneGenerator? = null
    private var inputSkuActivo: EditText? = null
    private var loteSku: String? = null
    private val loteAsociadas = HashSet<String>()
    private val nombres = HashMap<String, String>()
    private val epcSku = HashMap<String, String>()
    private val consultados = HashSet<String>()
    private var resolviendo = false

    // Catálogo local EPC->producto (se descarga UNA vez del servidor): las
    // etiquetas se reconocen AL INSTANTE y sin tocar la red mientras se lee,
    // igual que la demo de Alien. Sin red durante la lectura = ni lentitud
    // ni caídas de WiFi.
    private var catalogo = HashMap<String, Pair<String, String>>()   // epc -> (sku, nombre)
    private var productosId = HashMap<Int, Pair<String, String>>()   // id -> (sku, nombre)
    private var ignorados = HashSet<String>()                        // EPC ajenos
    private var marcaEpc = "AF01"
    private var filtroSku: String? = null
    private lateinit var btnFiltro: Button
    private var leyendo = false
    private val tags = LinkedHashMap<String, Int>()
    private lateinit var adaptador: AdaptadorRepuestos
    private val ui = Handler(Looper.getMainLooper())

    /** Una fila de la lista = un REPUESTO (no una etiqueta suelta). */
    private class FilaRepuesto(val sku: String, val etiqueta: String,
                               val unidades: Int, val veces: Int)

    /** Pinta cada repuesto con la cantidad en NARANJA y las veces leído en BLANCO. */
    private inner class AdaptadorRepuestos :
        ArrayAdapter<FilaRepuesto>(this, R.layout.fila_repuesto) {
        override fun getView(pos: Int, reuso: View?, padre: ViewGroup): View {
            val v = reuso ?: layoutInflater.inflate(R.layout.fila_repuesto, padre, false)
            val f = getItem(pos)
            if (f != null) {
                v.findViewById<TextView>(R.id.fNombre).text = f.etiqueta
                v.findViewById<TextView>(R.id.fCant).text = "${f.unidades}"
                v.findViewById<TextView>(R.id.fVeces).text = "×${f.veces}"
            }
            return v
        }
    }

    private val pendientes = HashMap<String, Int>()
    private val candado = Any()
    private var tasaSeg = 0          // lecturas por segundo (se muestra en pantalla)
    private var cuentaSeg = 0
    private var tUltTasa = 0L
    private val tictac = object : Runnable {
        override fun run() { volcarPendientes(); if (leyendo) ui.postDelayed(this, 250) }
    }

    private lateinit var estado: TextView
    private lateinit var contador: TextView
    private lateinit var sub: TextView
    private lateinit var btnLeer: Button
    private lateinit var bannerDesc: Button
    private lateinit var opciones: View
    private val autoEnviados = HashSet<String>()

    private val prefs by lazy { getSharedPreferences("cfg", MODE_PRIVATE) }
    private val urlServidor get() = prefs.getString("url", "http://192.168.0.2:5000")!!
    private val nombreEquipo get() = prefs.getString("nombre", "ALIEN-01")!!

    // ---- pantalla del INVENTARIO (la misma que se ve en el PC) ----
    private var web: android.webkit.WebView? = null
    private var enInventario = false

    /** Deja el inventario listo la primera vez que se entra, no al arrancar:
     *  así la app abre igual de rápido para quien solo viene a leer. */
    @android.annotation.SuppressLint("SetJavaScriptEnabled")
    private fun prepararWeb() {
        if (web != null) return
        val w = findViewById<android.webkit.WebView>(R.id.webInventario)
        val est = findViewById<TextView>(R.id.webEstado)
        w.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true          // el modo oscuro se recuerda aquí
            // que se vea COMO EN EL PC y se pueda acercar con dos dedos
            useWideViewPort = true
            loadWithOverviewMode = true
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false
        }
        w.webViewClient = object : android.webkit.WebViewClient() {
            override fun onPageFinished(v: android.webkit.WebView?, url: String?) {
                est.visibility = android.view.View.GONE
            }
            override fun onReceivedError(v: android.webkit.WebView?,
                                         req: android.webkit.WebResourceRequest?,
                                         err: android.webkit.WebResourceError?) {
                est.visibility = android.view.View.VISIBLE
                est.text = "No se pudo abrir el inventario en $urlServidor\n" +
                           "Revisa que el PC servidor esté prendido y en la misma red (⚙)."
            }
        }
        web = w
    }

    private fun mostrarInventario(si: Boolean) {
        enInventario = si
        findViewById<android.view.View>(R.id.pantallaInventario).visibility =
            if (si) android.view.View.VISIBLE else android.view.View.GONE
        findViewById<android.view.View>(R.id.pantallaLeer).visibility =
            if (si) android.view.View.GONE else android.view.View.VISIBLE
        findViewById<Button>(R.id.tabLeer).backgroundTintList =
            android.content.res.ColorStateList.valueOf(
                android.graphics.Color.parseColor(if (si) "#37474F" else "#F5A623"))
        findViewById<Button>(R.id.tabLeer).setTextColor(
            android.graphics.Color.parseColor(if (si) "#FFFFFF" else "#14181D"))
        findViewById<Button>(R.id.tabInventario).backgroundTintList =
            android.content.res.ColorStateList.valueOf(
                android.graphics.Color.parseColor(if (si) "#F5A623" else "#37474F"))
        findViewById<Button>(R.id.tabInventario).setTextColor(
            android.graphics.Color.parseColor(if (si) "#14181D" else "#FFFFFF"))
        if (si) {
            if (leyendo) detener()      // no se lee a ciegas mientras se consulta
            prepararWeb()
            val destino = "$urlServidor/escritorio"
            if (web?.url == null) web?.loadUrl(destino)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        estado = findViewById(R.id.estado)
        contador = findViewById(R.id.contador)
        sub = findViewById(R.id.sub)
        btnLeer = findViewById(R.id.btnLeer)
        opciones = findViewById(R.id.opciones)
        val lista = findViewById<ListView>(R.id.lista)
        adaptador = AdaptadorRepuestos()
        lista.adapter = adaptador

        // ocultar/mostrar los botones para ver más productos (pantalla chica)
        opciones.visibility = if (prefs.getBoolean("opc", true)) View.VISIBLE else View.GONE
        findViewById<Button>(R.id.btnOpc).setOnClickListener {
            val ver = opciones.visibility != View.VISIBLE
            opciones.visibility = if (ver) View.VISIBLE else View.GONE
            prefs.edit().putBoolean("opc", ver).apply()
        }

        btnLeer.setOnClickListener { if (leyendo) detener() else iniciar() }
        findViewById<Button>(R.id.tabLeer).setOnClickListener { mostrarInventario(false) }
        findViewById<Button>(R.id.tabInventario).setOnClickListener { mostrarInventario(true) }
        lista.setOnItemClickListener { _, _, pos, _ ->
            val sku = skusMostrados.getOrNull(pos) ?: return@setOnItemClickListener
            detalleRepuesto(sku)
        }
        findViewById<Button>(R.id.btnLimpiar).setOnClickListener { tags.clear(); refrescar() }
        findViewById<Button>(R.id.btnDesc).setOnClickListener { mostrarDesconocidos() }
        bannerDesc = findViewById(R.id.bannerDesc)
        bannerDesc.setOnClickListener { mostrarDesconocidos() }
        btnFiltro = findViewById(R.id.btnFiltro)
        btnFiltro.setOnClickListener { dialogoFiltro() }
        findViewById<Button>(R.id.btnEnviar).setOnClickListener { enviar() }
        findViewById<Button>(R.id.btnAsociar).setOnClickListener { dialogoAsociar() }
        findViewById<Button>(R.id.btnConfig).setOnClickListener { dialogoConfig() }
        findViewById<Button>(R.id.btnCodigo).setOnClickListener { escanearCodigo() }

        try { tono = android.media.ToneGenerator(android.media.AudioManager.STREAM_MUSIC, 90) } catch (_: Throwable) {}
        sujetarWifi()
        cargarCatalogoLocal()
        refrescarCatalogo()
        conectarLector()
    }

    // --------------------------------------------- catálogo local (sin red al leer)
    private fun archivoCatalogo() = java.io.File(filesDir, "catalogo.json")

    private fun aplicarCatalogo(o: JSONObject) {
        val cat = HashMap<String, Pair<String, String>>()
        val pro = HashMap<Int, Pair<String, String>>()
        val ign = HashSet<String>()
        o.optJSONObject("tags")?.let { t ->
            val it2 = t.keys()
            while (it2.hasNext()) {
                val epc = it2.next()
                val a = t.optJSONArray(epc) ?: continue
                cat[epc] = Pair(a.optString(0), a.optString(1))
            }
        }
        o.optJSONObject("productos")?.let { p ->
            val it2 = p.keys()
            while (it2.hasNext()) {
                val id = it2.next()
                val a = p.optJSONArray(id) ?: continue
                id.toIntOrNull()?.let { pro[it] = Pair(a.optString(0), a.optString(1)) }
            }
        }
        o.optJSONArray("ignorados")?.let { for (i in 0 until it.length()) ign.add(it.optString(i)) }
        marcaEpc = o.optString("marca", "AF01")
        catalogo = cat; productosId = pro; ignorados = ign
    }

    private fun cargarCatalogoLocal() {
        try {
            val f = archivoCatalogo()
            if (f.exists()) aplicarCatalogo(JSONObject(f.readText()))
        } catch (_: Throwable) {}
    }

    /** Baja el catálogo del servidor en segundo plano (al abrir la app y tras asociar). */
    private fun refrescarCatalogo() {
        thread {
            try {
                val c = URL("$urlServidor/api/tags/todos").openConnection() as HttpURLConnection
                c.connectTimeout = 6000; c.readTimeout = 30000
                val txt = c.inputStream.bufferedReader().readText()
                val o = JSONObject(txt)
                try { archivoCatalogo().writeText(txt) } catch (_: Throwable) {}
                ui.post {
                    aplicarCatalogo(o)
                    if (!leyendo) { pintar() }
                }
            } catch (_: Exception) {}
        }
    }

    /** Reconoce un EPC con el catálogo local (o el formato AF01+id). true = producto conocido. */
    private fun reconocer(epc: String): Boolean {
        if (nombres[epc] != null) return true
        var p = catalogo[epc]
        if (p == null && epc.length == 24 && epc.startsWith(marcaEpc)) {
            val id = epc.substring(4, 10).toIntOrNull(16)
            if (id != null) p = productosId[id]
        }
        if (p == null) return false
        epcSku[epc] = p.first
        nombres[epc] = "${p.second} (${p.first})"
        return true
    }

    private fun agregarAlCatalogo(epc: String, sku: String, nombre: String) {
        catalogo[epc] = Pair(sku, nombre)
        epcSku[epc] = sku
        nombres[epc] = "$nombre ($sku)"
    }

    // pitido corto al detectar una etiqueta nueva (se puede apagar en ⚙)
    private fun pitar() {
        if (!prefs.getBoolean("beep", true)) return
        try { tono?.startTone(android.media.ToneGenerator.TONE_PROP_BEEP, 70) } catch (_: Throwable) {}
    }

    // Mantiene el WiFi activo: el lector RFID a plena potencia lo interfiere y
    // el sistema tiende a soltarlo ("searching for wifi networks").
    private fun sujetarWifi() {
        try {
            val wm = applicationContext.getSystemService(WIFI_SERVICE) as android.net.wifi.WifiManager
            wifiLock = wm.createWifiLock(
                android.net.wifi.WifiManager.WIFI_MODE_FULL_HIGH_PERF, "inventario-alien"
            ).apply { setReferenceCounted(false); acquire() }
        } catch (_: Throwable) {}
    }

    // ------------------------------------------------ lector RFID + escáner 2D
    private fun conectarLector() {
        thread {
            var msgRfid = "✖"
            try {
                val r = RFID.open()
                // Configuración de VELOCIDAD MÁXIMA: modo DUAL, sesión S0 (las
                // etiquetas responden SIN PARAR, no se callan tras contestar como
                // en S1 — esto multiplica las lecturas por segundo), target A,
                // Q=3 y SIN leer TID.
                try { r.searchMode = SearchMode.DUAL } catch (_: Throwable) {}
                try { r.session = Session.S0 } catch (_: Throwable) {}
                try { r.target = Target.A } catch (_: Throwable) {}
                try { r.q = 3 } catch (_: Throwable) {}
                try { r.acqTID = false } catch (_: Throwable) {}
                // El SDK duerme 10 ms por CADA etiqueta que saca del búfer
                // (tope ~100/s). Se baja a 1 ms para llegar a cientos por segundo.
                try {
                    val campo = r.javaClass.getDeclaredField("c")
                    campo.isAccessible = true
                    if (campo.type == Int::class.javaPrimitiveType && campo.getInt(r) == 10)
                        campo.setInt(r, 1)
                } catch (_: Throwable) {}
                // potencia MÁXIMA por defecto (como la demo); ajustable en ⚙
                try { r.power = prefs.getInt("potencia", r.maxPower) } catch (_: Throwable) {}
                reader = r; msgRfid = "✔"
            } catch (e: Throwable) {
                val m = e.message ?: ""
                if (m.contains("use by other", true) || m.contains("busy", true))
                    ui.post { dialogoAviso("Lector ocupado",
                        "Cierra la app de demostración de Alien (u otra que use el lector) y vuelve a abrir esta app.") }
            }
            val okBar = try {
                val b = BarcodeReader(applicationContext)
                try { b.setAllSymbologies(true) } catch (_: Throwable) {}
                barcode = b; true
            } catch (e: Throwable) { barError = e.message ?: e.toString(); false }
            val mr = msgRfid
            ui.post {
                estado.text = "RFID $mr · Código 2D ${if (okBar) "✔" else "✖"} · $nombreEquipo"
            }
        }
    }

    // callback continuo del SDK: SOLO acumula (llega cientos de veces/seg)
    override fun onTagRead(t: Tag) {
        val epc = try { t.getEPC()?.uppercase() } catch (_: Throwable) { null } ?: return
        if (epc.isEmpty()) return
        synchronized(candado) { pendientes[epc] = (pendientes[epc] ?: 0) + 1 }
    }

    private fun volcarPendientes() {
        val lote: Map<String, Int>
        synchronized(candado) {
            if (pendientes.isEmpty()) return
            lote = HashMap(pendientes); pendientes.clear()
        }
        // medidor de lecturas por segundo
        cuentaSeg += lote.values.sum()
        val ahora = System.currentTimeMillis()
        if (tUltTasa == 0L) tUltTasa = ahora
        else if (ahora - tUltTasa >= 1000) {
            tasaSeg = (cuentaSeg * 1000L / (ahora - tUltTasa)).toInt()
            cuentaSeg = 0; tUltTasa = ahora
        }
        val f = filtroSku
        var cambio = false
        var nuevo = false
        for ((epc, n) in lote) {
            if (epc in ignorados) continue                 // ajeno: ni contarlo
            val conocido = reconocer(epc)                  // catálogo local: SIN red
            if (f != null) {
                if (conocido && epcSku[epc] != f) continue // de otro producto
                if (!conocido && epc in consultados) continue
            }
            if (epc !in tags) nuevo = true                 // etiqueta nunca vista
            tags[epc] = (tags[epc] ?: 0) + n
            cambio = true
            val sku = loteSku
            if (sku != null && loteAsociadas.add(epc)) asociarEnLote(epc, sku)
        }
        if (nuevo) pitar()
        if (cambio) pintar()                               // nada de red mientras se lee
    }

    private fun iniciar() {
        val r = reader ?: return toast("Lector no inicializado")
        try {
            synchronized(candado) { pendientes.clear() }
            tasaSeg = 0; cuentaSeg = 0; tUltTasa = 0L
            r.inventory(this)                 // scan continuo -> onTagRead(...)
            leyendo = true
            btnLeer.text = "■ DETENER"
            estado.text = "Leyendo…"
            ui.removeCallbacks(tictac); ui.postDelayed(tictac, 250)
        } catch (e: Throwable) { toast("No se pudo iniciar: " + (e.message ?: "")) }
    }

    private fun detener() {
        try { reader?.stop() } catch (_: Throwable) {}
        leyendo = false
        ui.removeCallbacks(tictac)
        volcarPendientes()
        resolverNombres()      // ya sin leer: consulta al servidor lo no reconocido
        btnLeer.text = "▶ LEER"
        val sku = loteSku
        if (sku != null) {
            loteSku = null
            estado.text = "✔ Lote terminado: ${loteAsociadas.size} etiquetas → $sku"
            toast("✔ ${loteAsociadas.size} etiquetas asociadas a $sku")
            refrescarCatalogo()
        } else estado.text = "Detenido · ${tags.size} EPC únicos"
    }

    private fun asociarEnLote(epc: String, sku: String) {
        estado.text = "LOTE $sku · asociadas: ${loteAsociadas.size} · gatillo para terminar"
        thread {
            try {
                val r = post("$urlServidor/api/tags", JSONObject().put("epc", epc).put("sku", sku))
                if (!r.optBoolean("ok")) ui.post { loteAsociadas.remove(epc); toast("✖ ${r.optString("error")}") }
                else ui.post {
                    consultados.remove(epc)
                    agregarAlCatalogo(epc, r.optString("sku", sku), r.optString("nombre", sku))
                    pintar()
                }
            } catch (e: Exception) { ui.post { loteAsociadas.remove(epc); toast("Error de red: ${e.message}") } }
        }
    }

    private fun refrescar() { pintar(); if (!leyendo) resolverNombres() }

    private val skusMostrados = ArrayList<String>()

    private fun pintar() {
        val f = filtroSku
        val visibles = tags.entries.filter { nombres[it.key] != null && (f == null || epcSku[it.key] == f) }
        val descon = if (f == null) tags.keys.count { nombres[it] == null } else 0
        // el número GRANDE naranja = etiquetas RECONOCIDAS (productos), como en
        // la C72. El subtítulo muestra el total leído y los desconocidos, para
        // ver el avance al instante mientras el servidor devuelve los nombres.
        contador.text = "${visibles.size}"
        val vel = if (leyendo && tasaSeg > 0) "   ·   ⚡ $tasaSeg/s" else ""
        sub.text = if (f == null)
            "📡 ${tags.size} leídas$vel" + (if (descon > 0) "   ·   ¿? $descon desconocidos" else "")
        else "de este producto$vel"
        bannerDesc.visibility = if (descon == 0) View.GONE else View.VISIBLE
        if (descon > 0) bannerDesc.text = "¿? Desconocidos: $descon — tocar para revisar"

        // Una fila POR REPUESTO: se juntan todas sus etiquetas.
        //   naranja = cuántas unidades (etiquetas distintas) se han leído
        //   blanco  = cuántas veces las ha visto el lector en total
        val porSku = LinkedHashMap<String, IntArray>()
        val rotulo = HashMap<String, String>()
        for (e in visibles) {
            val sku = epcSku[e.key] ?: continue
            val a = porSku.getOrPut(sku) { IntArray(2) }
            a[0]++; a[1] += e.value
            if (sku !in rotulo) rotulo[sku] = nombres[e.key] ?: sku
        }
        adaptador.clear(); skusMostrados.clear()
        for ((sku, a) in porSku) {
            skusMostrados.add(sku)
            adaptador.add(FilaRepuesto(sku, rotulo[sku] ?: sku, a[0], a[1]))
        }
    }

    /** Tocar un repuesto: detalle con sus etiquetas una por una. */
    private fun detalleRepuesto(sku: String) {
        val epcs = tags.keys.filter { epcSku[it] == sku }
        if (epcs.isEmpty()) return
        val veces = epcs.map { tags[it] ?: 0 }.sum()
        val txt = StringBuilder("Cantidad leída: ${epcs.size}\nVeces leído: $veces\n\nEtiquetas:\n")
        for (e in epcs.take(40)) txt.append("• $e   ×${tags[e]}\n")
        if (epcs.size > 40) txt.append("… y ${epcs.size - 40} más")
        AlertDialog.Builder(this).setTitle(nombres[epcs[0]] ?: sku)
            .setMessage(txt.toString()).setPositiveButton("Cerrar", null).show()
    }

    private fun resolverNombres() {
        if (leyendo) return          // JAMÁS usar la red mientras se está leyendo
        val faltan = tags.keys.filter { it !in nombres && it !in consultados }
        if (faltan.isEmpty() || resolviendo) return
        resolviendo = true
        thread {
            try {
                val r = post("$urlServidor/api/resolver", JSONObject().put("epcs", JSONArray(faltan)))
                ui.post {
                    val f = filtroSku
                    val nuevosDesc = ArrayList<String>()
                    for (epc in faltan) {
                        consultados.add(epc)
                        val o = r.optJSONObject(epc)
                        if (o != null) {
                            agregarAlCatalogo(epc, o.optString("sku"), o.optString("nombre"))
                            if (f != null && epcSku[epc] != f) tags.remove(epc)
                        } else {
                            if (f != null) tags.remove(epc)
                            else if (autoEnviados.add(epc)) nuevosDesc.add(epc)
                        }
                    }
                    resolviendo = false; pintar()
                    if (nuevosDesc.isNotEmpty()) enviarDesconocidos(nuevosDesc)
                }
            } catch (e: Exception) { ui.post { resolviendo = false } }
        }
    }

    // ------------------------------------------------ escáner 2D (Honeywell)
    private val barcodeCb = BarcodeCallback { dato ->
        try { barcode?.stop() } catch (_: Throwable) {}
        val d = dato?.trim()
        if (!d.isNullOrEmpty()) ui.post { pitar(); onBarcode(d) }
    }

    private fun escanearCodigo() {
        val b = barcode ?: run {
            estado.text = "Escáner 2D no disponible: " + (barError ?: "?")
            return toast("Escáner 2D no disponible" + (barError?.let { ": $it" } ?: ""))
        }
        try { b.start(barcodeCb) } catch (e: Throwable) { toast("No se pudo escanear: " + (e.message ?: "")) }
    }

    private fun onBarcode(dato: String) {
        val campo = inputSkuActivo
        if (campo != null) {
            campo.setText(dato)
            thread {
                try {
                    val r = getJsonObj("$urlServidor/api/buscar_producto?codigo=" +
                            java.net.URLEncoder.encode(dato, "UTF-8"))
                    ui.post {
                        if (r.optBoolean("ok")) {
                            val sku = r.optString("sku")
                            inputSkuActivo?.setText(sku)
                            estado.text = "✔ ${r.optString("nombre")}"
                            toast("✔ ${r.optString("nombre")} ($sku)")
                        } else toast("✖ Código $dato: no corresponde a ningún producto")
                    }
                } catch (_: Exception) { ui.post { toast("Código: $dato (sin conexión para identificarlo)") } }
            }
        } else {
            thread {
                var titulo = "Código leído"; var mensaje = dato; var sku = dato
                try {
                    val r = getJsonObj("$urlServidor/api/buscar_producto?codigo=" +
                            java.net.URLEncoder.encode(dato, "UTF-8"))
                    if (r.optBoolean("ok")) {
                        sku = r.optString("sku"); titulo = "Producto reconocido"
                        mensaje = "${r.optString("nombre")}\n\nReferencia: $sku"
                    }
                } catch (_: Exception) {}
                ui.post {
                    AlertDialog.Builder(this).setTitle(titulo).setMessage(mensaje)
                        .setPositiveButton("Asociar tags a este producto") { _, _ -> dialogoAsociar(sku) }
                        .setNegativeButton("Cerrar", null).show()
                }
            }
        }
    }

    // ------------------------------------------------ teclas físicas
    // Alien ALR-H450: gatillo/scan = 139 (RFID) · laterales 136/137 (código 2D).
    private val teclasGatillo = setOf(139, 280, 291, 293, 294, 311, 312, 313, 315)
    private val teclasEscaner = setOf(136, 137, 142, 249, 250, 251, 252)

    // Gatillo IGUAL que la demo de Alien: se lee MIENTRAS está apretado y al
    // soltarlo se detiene. (El botón ▶ de la pantalla sigue siendo de prender/apagar.)
    @Deprecated("El gatillo necesita el comportamiento clásico del botón atrás")
    override fun onBackPressed() {
        val w = web
        if (enInventario && w != null && w.canGoBack()) { w.goBack(); return }
        if (enInventario) { mostrarInventario(false); return }
        @Suppress("DEPRECATION")
        super.onBackPressed()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode in teclasEscaner) { if (event?.repeatCount == 0) escanearCodigo(); return true }
        if (keyCode in teclasGatillo) { if (event?.repeatCount == 0 && !leyendo) iniciar(); return true }
        if (keyCode != KeyEvent.KEYCODE_BACK && keyCode != KeyEvent.KEYCODE_VOLUME_UP &&
            keyCode != KeyEvent.KEYCODE_VOLUME_DOWN)
            estado.text = "tecla física: $keyCode (avísame este número si un botón no hace nada)"
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode in teclasGatillo) { if (leyendo) detener(); return true }
        return super.onKeyUp(keyCode, event)
    }

    // ------------------------------------------------ red
    private fun enviar() {
        val f = filtroSku
        val lista = if (f == null) tags.keys.toList() else tags.keys.filter { epcSku[it] == f }
        if (lista.isEmpty()) return toast("No hay lecturas")
        estado.text = "Enviando ${lista.size} EPC…"
        thread {
            try {
                val body = JSONObject().apply { put("dispositivo", nombreEquipo); put("epcs", JSONArray(lista)) }
                val resp = post("$urlServidor/api/lecturas", body)
                ui.post {
                    estado.text = "Servidor: ${resp.optInt("nuevos")} nuevos de ${resp.optInt("recibidos")} (sesión ${resp.optInt("sesion_id")})"
                    toast("Enviado ✔")
                }
            } catch (e: Exception) { ui.post { estado.text = "Error de red: ${e.message}" } }
        }
    }

    private fun dialogoAsociar(skuInicial: String? = null) {
        val input = EditText(this).apply { hint = "SKU del producto"; setText(skuInicial ?: "") }
        val cont = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(40, 20, 40, 0); addView(input)
            if (barcode != null) addView(Button(context).apply {
                text = "▦ Escanear código de barras"; setOnClickListener { escanearCodigo() }
            })
        }
        inputSkuActivo = input
        AlertDialog.Builder(this).setTitle("Asociar tags a un producto")
            .setMessage("Escribe o escanea el SKU. \"Leer y asociar\" = 1 etiqueta. \"EN LOTE\" = todas las que leas hasta soltar el gatillo.")
            .setView(cont).setOnDismissListener { inputSkuActivo = null }
            .setNeutralButton("EN LOTE (varias)") { _, _ ->
                val sku = input.text.toString().trim()
                if (sku.isEmpty()) { toast("Escribe o escanea el SKU primero"); return@setNeutralButton }
                loteAsociadas.clear(); loteSku = sku; tags.clear(); refrescar(); iniciar()
                estado.text = "LOTE $sku · pasa el lector por las etiquetas; gatillo para terminar"
            }
            .setPositiveButton("Leer y asociar") { _, _ ->
                val sku = input.text.toString().trim()
                if (sku.isEmpty()) { toast("Escribe o escanea el SKU primero"); return@setPositiveButton }
                ui.post { estado.text = "Acerca la etiqueta RFID al lector…" }
                thread {
                    try {
                        var epc: String? = null
                        val limite = System.currentTimeMillis() + 6000
                        while (epc == null && System.currentTimeMillis() < limite) {
                            epc = leerUnTag()
                        }
                        if (epc == null) {
                            ui.post { estado.text = "No se leyó ningún tag"; toast("No se leyó ningún tag. Acércalo más e intenta de nuevo.") }
                            return@thread
                        }
                        val r = post("$urlServidor/api/tags", JSONObject().put("epc", epc).put("sku", sku))
                        ui.post {
                            if (r.optBoolean("ok")) {
                                estado.text = "✔ Tag asociado a $sku"; toast("✔ $epc → $sku"); consultados.remove(epc)
                                agregarAlCatalogo(epc, r.optString("sku", sku), r.optString("nombre", sku))
                            } else {
                                val err = r.optString("error"); estado.text = "✖ $err"
                                toast(if (err == "SKU no existe")
                                    "El SKU $sku no está dado de alta. Créalo primero en la web (Productos)."
                                else "Error: $err")
                            }
                        }
                    } catch (e: Exception) { ui.post { estado.text = "Error: ${e.message}"; toast("Error: ${e.message}") } }
                }
            }
            .setNegativeButton("Cancelar", null).show()
    }

    // lee un solo tag (para asociar): lectura puntual del EPC
    private fun leerUnTag(): String? {
        return try {
            val res = reader?.read() ?: return null
            if (res.isSuccess) (res.data as? Tag)?.getEPC()?.uppercase() else null
        } catch (_: Throwable) { null }
    }

    // ------------------------------------------------ modo "solo un producto"
    private fun dialogoFiltro() {
        if (filtroSku != null) {
            filtroSku = null; btnFiltro.text = "◎ LEER SOLO UN PRODUCTO"
            estado.text = "Modo libre: cuenta todo lo registrado"; pintar(); return
        }
        val input = EditText(this).apply { hint = "SKU del producto" }
        val cont = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(40, 20, 40, 0); addView(input)
            if (barcode != null) addView(Button(context).apply {
                text = "▦ Escanear código de barras"; setOnClickListener { escanearCodigo() }
            })
        }
        inputSkuActivo = input
        AlertDialog.Builder(this).setTitle("Leer solo un producto")
            .setMessage("El contador solo sumará etiquetas de ese producto; lo demás (incluidos los desconocidos) se ignora por completo.")
            .setView(cont).setOnDismissListener { inputSkuActivo = null }
            .setPositiveButton("Activar") { _, _ ->
                val cod = input.text.toString().trim()
                if (cod.isEmpty()) { toast("Escribe o escanea el SKU primero"); return@setPositiveButton }
                estado.text = "Buscando $cod…"
                thread {
                    var sku = cod; var nombre = ""
                    try {
                        val r = getJsonObj("$urlServidor/api/buscar_producto?codigo=" +
                                java.net.URLEncoder.encode(cod, "UTF-8"))
                        if (r.optBoolean("ok")) { sku = r.optString("sku", cod); nombre = r.optString("nombre", "") }
                    } catch (_: Exception) {}
                    ui.post {
                        filtroSku = sku; tags.clear()
                        btnFiltro.text = "◎ SOLO: $sku — tocar para quitar"
                        estado.text = if (nombre.isNotEmpty()) "Contando solo: $nombre" else "Contando solo $sku"
                        pintar()
                    }
                }
            }
            .setNegativeButton("Cancelar", null).show()
    }

    // ------------------------------------------------ desconocidos
    private fun mostrarDesconocidos() {
        estado.text = "Consultando desconocidos…"
        thread {
            try {
                val arr = getJson("$urlServidor/api/desconocidos")
                ui.post {
                    if (arr.length() == 0) { estado.text = "Sin desconocidos pendientes ✔"; toast("Nada pendiente: todo identificado"); return@post }
                    estado.text = "${arr.length()} desconocidos pendientes"
                    val items = (0 until arr.length()).map {
                        val o = arr.getJSONObject(it); "${o.getString("epc")}   ×${o.optInt("veces")}"
                    }.toTypedArray()
                    AlertDialog.Builder(this).setTitle("EPC desconocidos (${arr.length()})")
                        .setItems(items) { _, i -> dialogoResolverEpc(arr.getJSONObject(i).getString("epc")) }
                        .setNegativeButton("Cerrar", null).show()
                }
            } catch (e: Exception) { ui.post { estado.text = "Error de red: ${e.message}" } }
        }
    }

    private fun dialogoResolverEpc(epc: String) {
        val input = EditText(this).apply { hint = "SKU del producto" }
        val cont = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(40, 20, 40, 0); addView(input)
            if (barcode != null) addView(Button(context).apply {
                text = "▦ Escanear código de barras"; setOnClickListener { escanearCodigo() }
            })
        }
        inputSkuActivo = input
        AlertDialog.Builder(this).setTitle("EPC sin producto").setMessage(epc)
            .setView(cont).setOnDismissListener { inputSkuActivo = null }
            .setPositiveButton("Asociar") { _, _ ->
                val sku = input.text.toString().trim()
                if (sku.isEmpty()) { toast("Escribe o escanea el SKU primero"); return@setPositiveButton }
                thread {
                    try {
                        val r = post("$urlServidor/api/tags", JSONObject().put("epc", epc).put("sku", sku))
                        ui.post {
                            if (r.optBoolean("ok")) {
                                consultados.remove(epc)
                                agregarAlCatalogo(epc, r.optString("sku", sku), r.optString("nombre", sku))
                                refrescar(); estado.text = "✔ $epc → $sku"; toast("✔ Asociado")
                            } else toast("✖ ${r.optString("error")}")
                        }
                    } catch (e: Exception) { ui.post { toast("Error: ${e.message}") } }
                }
            }
            .setNeutralButton("Ignorar (ajeno)") { _, _ ->
                thread {
                    try {
                        val r = post("$urlServidor/api/ignorar", JSONObject().put("epc", epc))
                        ui.post {
                            if (r.optBoolean("ok")) { estado.text = "EPC ignorado"; toast("Ignorado: no volverá a aparecer") }
                            else toast("✖ ${r.optString("error")}")
                        }
                    } catch (e: Exception) { ui.post { toast("Error: ${e.message}") } }
                }
            }
            .setNegativeButton("Cancelar", null).show()
    }

    // ------------------------------------------------ configuración
    private fun dialogoConfig() {
        val cont = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(40, 20, 40, 0) }
        val inUrl = EditText(this).apply { hint = "URL servidor"; setText(urlServidor) }
        val inNom = EditText(this).apply { hint = "Nombre equipo"; setText(nombreEquipo) }
        val r = reader
        val pmin = try { r?.minPower ?: 5 } catch (_: Throwable) { 5 }
        val pmax = try { r?.maxPower ?: 30 } catch (_: Throwable) { 30 }
        val actual = prefs.getInt("potencia", pmax).coerceIn(pmin, pmax)
        val lblPot = TextView(this).apply { text = "Alcance RFID: $actual" }
        val barPot = SeekBar(this).apply {
            max = pmax - pmin; progress = actual - pmin
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar?, p: Int, u: Boolean) { lblPot.text = "Alcance RFID: ${pmin + p}" }
                override fun onStartTrackingTouch(sb: SeekBar?) {}
                override fun onStopTrackingTouch(sb: SeekBar?) {}
            })
        }
        val btnBuscar = Button(this).apply { text = "🔍 Buscar el servidor en la red"; setOnClickListener { buscarServidores(inUrl) } }
        val chkBeep = CheckBox(this).apply { text = "🔊 Pitido al leer"; isChecked = prefs.getBoolean("beep", true) }
        val aviso = TextView(this).apply {
            text = "Máxima = más alcance. Solo si el WiFi se llega a caer al leer, baja un poco la potencia."
            textSize = 12f
        }
        cont.addView(inUrl); cont.addView(btnBuscar); cont.addView(inNom); cont.addView(lblPot); cont.addView(barPot); cont.addView(chkBeep); cont.addView(aviso)
        AlertDialog.Builder(this).setTitle("Configuración").setView(cont)
            .setPositiveButton("Guardar") { _, _ ->
                var u = inUrl.text.toString().trim().trimEnd('/')
                if (u.isNotEmpty() && !u.startsWith("http")) u = "http://$u"
                val pot = pmin + barPot.progress
                prefs.edit().putString("url", u).putString("nombre", inNom.text.toString().trim())
                    .putInt("potencia", pot).putBoolean("beep", chkBeep.isChecked).apply()
                thread { try { reader?.power = pot } catch (_: Throwable) {} }
                estado.text = "Config guardada · alcance $pot"
                refrescarCatalogo()
            }.setNegativeButton("Cancelar", null).show()
    }

    // ------------------------------------------------ autodetección del servidor
    private fun buscarServidores(inUrl: EditText) {
        val base = prefijoRed() ?: return toast("Sin red WiFi")
        val dlg = AlertDialog.Builder(this).setTitle("Buscando servidor…")
            .setMessage("Revisando ${base}1-254").setNegativeButton("Cerrar", null).show()
        val hallados = Collections.synchronizedList(ArrayList<Pair<String, String>>())
        val pool = Executors.newFixedThreadPool(16)   // suave: no saturar el WiFi
        val restantes = java.util.concurrent.atomic.AtomicInteger(254)
        for (n in 1..254) {
            val ip = "$base$n"
            pool.execute {
                val nombre = quienEs(ip)
                if (nombre != null) hallados.add(Pair(ip, nombre))
                if (restantes.decrementAndGet() == 0) ui.post {
                    dlg.dismiss(); pool.shutdown()
                    if (hallados.isEmpty()) { toast("No se encontró el servidor. ¿Está prendido y con el programa?"); return@post }
                    val items = hallados.map { "🖥 ${it.second}  —  ${it.first}" }.toTypedArray()
                    AlertDialog.Builder(this).setTitle("Elige el servidor")
                        .setItems(items) { _, i -> inUrl.setText("http://${hallados[i].first}:5000") }
                        .setNegativeButton("Cancelar", null).show()
                }
            }
        }
    }

    private fun prefijoRed(): String? {
        try {
            for (ni in Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp || ni.isLoopback) continue
                for (a in Collections.list(ni.inetAddresses)) {
                    if (a is Inet4Address && !a.isLoopbackAddress) {
                        val ip = a.hostAddress ?: continue
                        if (ip.startsWith("192.") || ip.startsWith("10.") || ip.startsWith("172."))
                            return ip.substring(0, ip.lastIndexOf('.') + 1)
                    }
                }
            }
        } catch (_: Throwable) {}
        return null
    }

    private fun quienEs(ip: String): String? {
        try {
            val c = URL("http://$ip:5000/api/quien").openConnection() as HttpURLConnection
            c.connectTimeout = 900; c.readTimeout = 900
            if (c.responseCode == 200) {
                val txt = c.inputStream.bufferedReader().readText(); c.disconnect()
                val o = JSONObject(txt)
                if (o.optBoolean("inventario")) return o.optString("nombre", ip)
            }
            c.disconnect()
        } catch (_: Throwable) {}
        return null
    }

    private fun enviarDesconocidos(epcs: List<String>) {
        thread {
            try { post("$urlServidor/api/lecturas", JSONObject().apply { put("dispositivo", nombreEquipo); put("epcs", JSONArray(epcs)) }) }
            catch (_: Exception) {}
        }
    }

    private fun getJson(url: String): JSONArray {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 6000; c.readTimeout = 8000
        return JSONArray(c.inputStream.bufferedReader().readText())
    }
    private fun getJsonObj(url: String): JSONObject {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 6000; c.readTimeout = 8000
        val txt = (if (c.responseCode < 400) c.inputStream else c.errorStream).bufferedReader().readText()
        return JSONObject(txt)
    }
    private fun post(url: String, body: JSONObject): JSONObject {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = "POST"; c.connectTimeout = 6000; c.readTimeout = 8000
        c.doOutput = true; c.setRequestProperty("Content-Type", "application/json")
        OutputStreamWriter(c.outputStream).use { it.write(body.toString()) }
        val txt = (if (c.responseCode < 400) c.inputStream else c.errorStream).bufferedReader().readText()
        return JSONObject(txt)
    }

    private fun dialogoAviso(t: String, m: String) =
        AlertDialog.Builder(this).setTitle(t).setMessage(m).setPositiveButton("OK", null).show()
    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_SHORT).show()

    override fun onDestroy() {
        try { detener() } catch (_: Throwable) {}
        try { barcode?.stop() } catch (_: Throwable) {}
        try { reader?.close() } catch (_: Throwable) {}
        try { wifiLock?.release() } catch (_: Throwable) {}
        try { tono?.release() } catch (_: Throwable) {}
        super.onDestroy()
    }
}
