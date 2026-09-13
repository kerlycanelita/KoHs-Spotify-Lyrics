# KoH's Spotify Lyrics

Overlay local de letras sincronizadas de Spotify para Windows, pensado para TikTok LIVE Studio y OBS.

Detecta Spotify Desktop mediante la sesión multimedia de Windows, muestra metadata, portada y letras sincronizadas cuando están disponibles, y expone el overlay mediante un enlace HTTPS temporal de Cloudflare sin abrir puertos del router.

## Inicio rápido

Requisitos:

- Windows 10 1809 o superior.
- Spotify Desktop abierto en la misma sesión de Windows.
- Python 3.11 o superior.
- Conexión a Internet durante el primer inicio.

Clona el repositorio:

```powershell
git clone https://github.com/kerlycanelita/KoHs-Spotify-Lyrics.git
cd KoHs-Spotify-Lyrics
```

Después ejecuta:

```text
iniciar.bat
```

El inicializador se encarga automáticamente de:

1. Detectar una instalación compatible de Python.
2. Crear `.venv` si todavía no existe.
3. Instalar o actualizar las dependencias de `requirements.txt`.
4. Descargar la versión oficial de `cloudflared.exe` si falta.
5. Limpiar una sesión anterior que haya quedado abierta.
6. Iniciar FastAPI localmente en `127.0.0.1:3000`.
7. Crear un Quick Tunnel HTTPS de Cloudflare.
8. Guardar la URL pública en `tiktok-url.txt` y copiarla al portapapeles.
9. Abrir la configuración local en el navegador.

No necesitas instalar certificados locales ni descargar `cloudflared` manualmente.

## URLs

Configuración local:

```text
http://127.0.0.1:3000/config
```

Estado del servidor:

```text
http://127.0.0.1:3000/api/health
```

El overlay público tendrá una dirección similar a:

```text
https://xxxxx.trycloudflare.com/overlay
```

Ese es el enlace que debes pegar en TikTok LIVE Studio u OBS como fuente de navegador.

El dominio de Quick Tunnel es temporal y puede cambiar después de reiniciar el servicio.

## Apagar todo

Cuando termines, ejecuta:

```text
shutdown-all.bat
```

El apagado usa `shutdown_all.py` cuando Python está disponible. Si el entorno de Python fue borrado o quedó dañado, existe un apagado de emergencia que intenta cerrar únicamente los procesos registrados por esta aplicación.

## Logs

Si algo falla durante el inicio, revisa:

```text
logs/launcher.log
logs/launcher-error.log
logs/server.log
logs/tunnel.log
```

El inicializador también muestra las últimas líneas relevantes cuando el servidor o el túnel no consiguen arrancar.

## Cómo funciona

- FastAPI sirve la aplicación solo en `127.0.0.1:3000` mediante HTTP local.
- `cloudflared` conecta ese servidor local con un dominio público HTTPS de `trycloudflare.com`.
- La configuración permanece local; el túnel público solo permite el overlay, sus recursos y las consultas de lectura necesarias.
- El WebSocket del overlay viaja por el mismo túnel para actualizar la canción y las letras en tiempo real.
- Spotify se consulta mediante Windows Global System Media Transport Controls.
- El proyecto necesita una sesión interactiva de Windows; no está diseñado para ejecutarse como servicio `SYSTEM`.

## Letras

El proyecto intenta obtener letras sincronizadas desde varias fuentes y solo muestra líneas que tengan timestamps válidos para la grabación correcta. Si una fuente ofrece únicamente texto plano o el resultado no es confiable, se mantiene la metadata de la canción pero no se inventan tiempos.

El fallback opcional de Musixmatch puede configurarse creando `secrets.json` a partir de `secrets.example.json` y añadiendo una API key compatible. `secrets.json` está ignorado por Git.

## Configuración visual

La página `/config` permite ajustar, entre otras cosas:

- Layout y presets del overlay.
- Portada, título, artista y álbum.
- Letra original y traducción.
- Tipografía, tamaño, peso, alineación, sombra y contorno.
- Colores, transparencia y espaciado.
- Animaciones de cambio de canción y efectos de letra.

Los cambios se guardan en `config.json`.

## Diagnóstico

Puedes comprobar rápidamente el backend con PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/api/health
```

Estados comunes:

- `spotify_unavailable`: Spotify Desktop no está exponiendo una sesión multimedia.
- `loading_lyrics`: la canción fue detectada y se están buscando letras.
- `no_synced_lyrics`: no se encontró una versión sincronizada fiable.
- `not_playing`: la sesión está detenida.
- `ready`: el overlay está listo.

## Desarrollo y pruebas

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Prueba visual del cambio de canción:

```powershell
node tests\overlay-swap.test.mjs
```

## Archivos generados localmente

Estos archivos o carpetas no deben subirse al repositorio:

```text
.venv/
tools/cloudflared.exe
tiktok-url.txt
logs/
runtime/
secrets.json
```

## Créditos

Proyecto de **zymekoh**. Spotify, TikTok, Cloudflare y los proveedores de letras pertenecen a sus respectivos propietarios.
