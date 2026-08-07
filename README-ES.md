<div align="center">

# Layla

**Tu propia IA. En tu equipo. Sin nube. Sin ataduras.**

[English README](README.md) · [Descargar e instalar](https://github.com/PapaKoftes/Layla/releases/latest)

</div>

---

Layla es una **compañera de IA local y privada**. Funciona enteramente en tu equipo con el modelo (GGUF) que elijas — sin cuenta, sin suscripción y sin enviar tus datos a ningún sitio. Recuerda, aprende, tiene muchas herramientas y puede acompañarte tanto en lo personal como en tareas técnicas. Responde en **español** (el código y los términos técnicos se mantienen en inglés, como es habitual al programar).

> **Nota sobre la licencia:** Layla es **de código disponible bajo una licencia no comercial** — gratis para uso personal, educativo y no comercial. Consulta [LICENSE](LICENSE).

---

## Instalación (sin ser programador)

1. Ve a la [página de descargas](https://github.com/PapaKoftes/Layla/releases/latest) y, en **Assets**, descarga **`Source code (zip)`** (o en la [página principal](https://github.com/PapaKoftes/Layla), botón verde **Code → Download ZIP**). **Descomprime** la carpeta donde quieras.
2. Abre la carpeta y **haz doble clic** en **`INSTALL.bat`** (Windows) o **`Install Layla.command`** (Mac). Instala todo y elige un modelo para tu equipo automáticamente — sin compilador, sin permisos de administrador y sin necesidad de tener Python.
3. La **primera vez** descarga su modelo (unos **2–5 GB**, puede tardar **10–40 minutos**). No cierres la ventana. Al terminar, Layla se abre en tu navegador.

**Para volver a abrirla:** haz doble clic en **`START.bat`**.

> Solo necesita internet para esa primera descarga. Después, Layla funciona **100 % sin conexión** — nada de lo que digas sale de tu equipo.

### ¿Tienes una tarjeta NVIDIA? Es automático

El instalador ejecuta **`nvidia-smi`**; si encuentra una tarjeta NVIDIA instala la versión **CUDA** de llama.cpp y ejecuta el modelo en tu GPU (mucho más rápido que en CPU). La versión CUDA trae su propio runtime — **no hay que instalar el CUDA toolkit**, solo tener el **driver de NVIDIA actualizado**. Si la versión GPU no carga (driver antiguo), el instalador vuelve solo a la versión CPU para que la instalación funcione igual.

- **¿Ya la instalaste en CPU y ahora quieres GPU?** Ejecuta una vez: `powershell -ExecutionPolicy Bypass -File install\enable_gpu.ps1` — solo cambia la versión de llama.cpp (tu modelo descargado no se toca) y lo verifica. Para revertir: `install\enable_gpu.ps1 -Off`.

### Alternativa (un solo comando, PowerShell)

```powershell
git clone https://github.com/PapaKoftes/Layla.git
cd Layla
powershell -ExecutionPolicy Bypass -File install\bootstrap.ps1
```

Para que responda en español, el instalador lo configura por ti; también puedes ajustar `response_language` en la Configuración.

---

## Qué esperar

- **Privacidad:** todo ocurre en tu equipo. Nada se envía a la nube.
- **Idioma:** conversa en español; el código y los términos técnicos van en inglés. La **interfaz** también se puede cambiar a español en **Configuración → Idioma de la interfaz**.
- **Velocidad:** en una CPU modesta, las primeras palabras tardan unos segundos y luego fluye. Un modelo más pequeño responde más rápido.
- **Disco:** el modelo recomendado ocupa ~2–5 GB; el instalador elige uno más ligero si te queda poco espacio.

## Si quieres más calidad

Un modelo más grande es más capaz pero más lento. Puedes cambiarlo desde **Configuración → Modelos**, o descargar otro con:

```powershell
.\.venv\Scripts\python.exe agent\install\provision_model.py --prefer balanced
```

Consulta [MODELS.md](MODELS.md) para la lista completa.

---

## Sus seis voces

Layla tiene seis facetas — una constructora, una investigadora, una oyente cálida, una chispa creativa, una crítica y una protectora — y cambia entre ellas según lo que le traigas. Recuerda, crece y es solo tuya.

## Más información

- **Todas las funciones, capturas y detalles técnicos:** [README en inglés](README.md)
- **Modelos y configuración:** [MODELS.md](MODELS.md)
- **Instalación avanzada / solución de problemas:** [install/INSTALL.md](install/INSTALL.md)
- **Acceso remoto** (usar la Layla de tu PC principal desde otro equipo mediante un túnel seguro con autenticación): sección *Connect* de `install/INSTALL.md`.

---

<div align="center">
<sub>Layla · funciona localmente en tu equipo · código disponible en <a href="https://github.com/PapaKoftes/Layla">GitHub</a></sub>
</div>
