# Layla — Edición Castilla

Tu compañera de programación con IA, **100 % local y privada**, que responde en **español**.

## Qué es
Layla se ejecuta enteramente en tu portátil — sin nube, sin cuotas y sin enviar tus datos a ningún sitio. La **Edición Castilla** está ajustada para equipos como el tuyo (CPU de gama media, 16 GB de RAM, poco espacio libre en disco) y conversa en español, manteniendo el código y los términos técnicos estándar en inglés (que es lo habitual al programar).

## Instalación (un solo comando)
Requisitos: Windows + conexión a internet (solo para instalar y descargar el modelo).

```powershell
git clone https://github.com/PapaKoftes/Layla.git
cd Layla
powershell -ExecutionPolicy Bypass -File install\castilla.ps1
```

El instalador, sin necesidad de compilador:
1. Instala **Python 3.12** si hace falta.
2. Crea un entorno aislado (`.venv`).
3. Instala las dependencias desde ruedas precompiladas (llama-cpp + torch).
4. **Detecta tu hardware** y descarga el modelo adecuado (**Qwen2.5-Coder-3B**, ~2 GB).
5. Configura Layla para **responder en español**.

## Para iniciarla
```powershell
.\.venv\Scripts\Activate.ps1
cd agent
python serve.py
```
Luego abre **http://127.0.0.1:8000** en tu navegador.

## Qué esperar
- **Velocidad:** ~6–8 tokens/seg en tu CPU (el modelo 3B es rápido y ligero).
- **Idioma:** responde en español; el código y los términos técnicos van en inglés.
- **Privacidad:** todo ocurre en tu portátil. Nada sale de tu equipo.
- **Disco:** el 3B ocupa ~2 GB; el instalador elige un modelo más ligero si te queda poco espacio.

## Si quieres más calidad (y tienes paciencia)
El modelo **7B** es más capaz pero más lento (~3 tokens/seg) y ocupa ~4,7 GB:
```powershell
.\.venv\Scripts\python.exe agent\install\provision_model.py --prefer balanced --spanish
```

## Conectar con el PC principal (opcional)
Para usar la Layla del PC principal desde el portátil mediante un túnel seguro, consulta
`install\INSTALL.md` (sección *Connect*). El acceso remoto exige autenticación por defecto.

## Ayuda
- Guía en inglés: `install/INSTALL.md`
- Notas de la versión: `RELEASE-CASTILLA.md`
