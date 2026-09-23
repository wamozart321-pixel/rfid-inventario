package com.inventario.alien

import android.app.Activity
import android.app.AlertDialog
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Intent
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * La app se pone al día sola desde el servidor del inventario.
 *
 * ESTE ARCHIVO ES EL MISMO EN LAS TRES APPS (C72, Alien y celular): el
 * original está en android-comun/ y se copia cambiando solo el «package».
 *
 * Al abrir (y cada media hora) pregunta al servidor en /api/apps/versiones.
 * Si tiene una versión más nueva de ESTA app, ofrece actualizar: la descarga
 * y Android muestra su pantalla de «Actualizar». Sin permiso de empresa,
 * Android no deja instalar sin ese toque, así que es lo más automático posible.
 *
 * Sirve desde Android 4.4 (la Alien) hasta el último: en los nuevos la APK se
 * le pasa al instalador por ApkProvider (abajo); en los viejos, como archivo.
 */
object Actualizador {
    const val ARCHIVO = "actualizacion.apk"
    private const val TIPO_APK = "application/vnd.android.package-archive"
    private var ultimaRevision = 0L
    @Volatile private var revisando = false
    private val ui = Handler(Looper.getMainLooper())

    /** Dónde se guarda la descarga. Android 7+: privado (lo sirve ApkProvider).
     *  Antes: en el almacenamiento de la app, que el instalador sí puede leer. */
    private fun archivo(act: Activity): File =
        if (Build.VERSION.SDK_INT >= 24) File(File(act.cacheDir, "apk").apply { mkdirs() }, ARCHIVO)
        else File(act.getExternalFilesDir(null) ?: act.cacheDir, ARCHIVO)

    @Suppress("DEPRECATION")
    fun miVersion(act: Activity): Long {
        val p = act.packageManager.getPackageInfo(act.packageName, 0)
        return if (Build.VERSION.SDK_INT >= 28) p.longVersionCode else p.versionCode.toLong()
    }

    /**
     * base: la dirección del servidor (http://192.168.0.5:5000 o la de afuera).
     * galleta: la sesión, si se entra desde afuera (si no, null).
     * forzar: mirar ya y avisar también si no hay nada nuevo.
     */
    fun revisar(act: Activity, base: String, galleta: String? = null, forzar: Boolean = false) {
        val ahora = System.currentTimeMillis()
        if (revisando || base.isBlank()) return
        if (esperandoPermiso(act)) return        // ya está descargada: la sigue alVolver
        if (!forzar && ahora - ultimaRevision < 30 * 60_000L) return
        revisando = true
        thread {
            var hay = false
            try {
                val c = URL(base.trimEnd('/') + "/api/apps/versiones").openConnection() as HttpURLConnection
                c.connectTimeout = 2500
                c.readTimeout = 5000
                if (!galleta.isNullOrBlank()) c.setRequestProperty("Cookie", galleta)
                if (c.responseCode == 200) {
                    // solo cuenta como revisado si el servidor contestó: si se
                    // abrió fuera de la WiFi, se vuelve a probar en cuanto se pueda
                    ultimaRevision = ahora
                    val apps = JSONObject(c.inputStream.bufferedReader().readText()).getJSONArray("apps")
                    val mia = miVersion(act)
                    for (i in 0 until apps.length()) {
                        val a = apps.getJSONObject(i)
                        if (a.optString("paquete") != act.packageName) continue
                        val vc = a.optLong("version_code")
                        if (vc <= mia) break
                        hay = true
                        val luego = act.getSharedPreferences("actualizador", 0).getLong("luego_$vc", 0)
                        if (forzar || ahora - luego > 4 * 3600_000L)
                            ui.post { preguntar(act, base, galleta, a) }
                        break
                    }
                }
            } catch (e: Exception) {
                // sin servidor ahora mismo: se mirará la próxima vez
            } finally {
                revisando = false
            }
            if (forzar && !hay) ui.post {
                Toast.makeText(act, "La app ya está al día", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun preguntar(act: Activity, base: String, galleta: String?, a: JSONObject) {
        if (act.isFinishing) return
        val vc = a.optLong("version_code")
        val actual = try {
            act.packageManager.getPackageInfo(act.packageName, 0).versionName
        } catch (e: Exception) { "?" }
        AlertDialog.Builder(act)
            .setTitle("Hay una versión nueva de la app")
            .setMessage("Versión ${a.optString("version")} (ahora tienes la $actual).\n\n" +
                        "Se descarga del servidor y Android te pedirá confirmar con " +
                        "«Actualizar». No se pierde nada de lo guardado.")
            .setPositiveButton("Actualizar") { _, _ -> descargar(act, base, galleta, a) }
            .setNegativeButton("Luego") { _, _ ->
                act.getSharedPreferences("actualizador", 0).edit()
                    .putLong("luego_$vc", System.currentTimeMillis()).apply()
            }
            .show()
    }

    private fun descargar(act: Activity, base: String, galleta: String?, a: JSONObject) {
        val aviso = AlertDialog.Builder(act)
            .setTitle("Descargando la actualización…")
            .setMessage("0 %")
            .setCancelable(false)
            .show()
        val destino = archivo(act)
        val total = a.optLong("bytes")
        thread {
            // hasta 3 intentos: al caminar por la bodega el WiFi puede cambiar de
            // antena a mitad de descarga y cortarla
            var error: String? = null
            for (intento in 1..3) {
                error = bajarUnaVez(base, galleta, a, destino, total) { pct ->
                    ui.post { aviso.setMessage(if (intento == 1) "$pct %" else "$pct %  (reintento $intento)") }
                }
                if (error == null) break
                Thread.sleep(1500L * intento)
            }
            if (Build.VERSION.SDK_INT < 24) destino.setReadable(true, false)
            ui.post {
                aviso.dismiss()
                if (error != null) {
                    Toast.makeText(act, "No se pudo descargar: $error", Toast.LENGTH_LONG).show()
                } else {
                    instalar(act)
                }
            }
        }
    }

    /** Una descarga completa. Devuelve null si salió bien, o qué falló. */
    private fun bajarUnaVez(base: String, galleta: String?, a: JSONObject, destino: File,
                            total: Long, progreso: (Int) -> Unit): String? = try {
        val c = URL(base.trimEnd('/') + a.optString("url")).openConnection() as HttpURLConnection
        c.connectTimeout = 5000
        c.readTimeout = 30000
        if (!galleta.isNullOrBlank()) c.setRequestProperty("Cookie", galleta)
        var hecho = 0L
        var ultimoPct = -1
        c.inputStream.use { ent ->
            destino.outputStream().use { sal ->
                val buf = ByteArray(64 * 1024)
                while (true) {
                    val n = ent.read(buf)
                    if (n < 0) break
                    sal.write(buf, 0, n)
                    hecho += n
                    val pct = if (total > 0) (100 * hecho / total).toInt() else 0
                    if (pct != ultimoPct) {
                        ultimoPct = pct
                        progreso(pct)
                    }
                }
            }
        }
        Log.i("Actualizador", "descargados $hecho de $total bytes")
        if (total > 0 && hecho != total) "la descarga quedó incompleta" else null
    } catch (e: Exception) {
        Log.w("Actualizador", "falló la descarga", e)
        e.message ?: "sin conexión con el servidor"
    }

    private fun instalar(act: Activity) {
        if (Build.VERSION.SDK_INT >= 26 && !act.packageManager.canRequestPackageInstalls()) {
            // Android 8+: la primera vez hay que dejar que ESTA app instale cosas.
            // Se apunta en el teléfono (no en memoria): al dar el permiso, Android
            // 11+ REINICIA la app, y al volver tiene que seguir donde iba.
            act.getSharedPreferences("actualizador", 0).edit().putBoolean("falta_permiso", true).apply()
            AlertDialog.Builder(act)
                .setTitle("Falta un permiso (solo la primera vez)")
                .setMessage("En la pantalla que se abre, activa «Permitir de esta fuente» " +
                            "y vuelve atrás: la actualización sigue sola.")
                .setPositiveButton("Abrir") { _, _ ->
                    act.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                             Uri.parse("package:" + act.packageName)))
                }
                .setNegativeButton("Cancelar", null)
                .show()
            return
        }
        act.getSharedPreferences("actualizador", 0).edit().putBoolean("falta_permiso", false).apply()
        val uri = if (Build.VERSION.SDK_INT >= 24)
            Uri.parse("content://${act.packageName}.apk/$ARCHIVO")
        else Uri.fromFile(archivo(act))
        act.startActivity(Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, TIPO_APK)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    private fun esperandoPermiso(act: Activity) =
        act.getSharedPreferences("actualizador", 0).getBoolean("falta_permiso", false) &&
            archivo(act).exists()

    /** Llamar en onResume: si se volvió de dar el permiso, se sigue instalando
     *  (una sola vez: si luego se cancela el instalador, no insiste). */
    fun alVolver(act: Activity) {
        if (!esperandoPermiso(act)) return
        if (Build.VERSION.SDK_INT < 26 || act.packageManager.canRequestPackageInstalls()) {
            instalar(act)
        } else {
            // volvió sin darlo: se olvida, y la próxima revisión vuelve a ofrecerla
            act.getSharedPreferences("actualizador", 0).edit().putBoolean("falta_permiso", false).apply()
        }
    }
}

/** Le pasa al instalador de Android la APK descargada, y SOLO esa. */
class ApkProvider : ContentProvider() {
    private fun apk() = File(File(context!!.cacheDir, "apk"), Actualizador.ARCHIVO)

    override fun onCreate() = true
    override fun getType(uri: Uri) = "application/vnd.android.package-archive"
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor =
        ParcelFileDescriptor.open(apk(), ParcelFileDescriptor.MODE_READ_ONLY)

    override fun query(uri: Uri, projection: Array<out String>?, selection: String?,
                       selectionArgs: Array<out String>?, sortOrder: String?): Cursor {
        val c = MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE))
        c.addRow(arrayOf<Any>(Actualizador.ARCHIVO, apk().length()))
        return c
    }

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?,
                        selectionArgs: Array<out String>?) = 0
}
