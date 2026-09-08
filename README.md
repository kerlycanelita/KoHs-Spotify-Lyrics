# KoH's Spotify Lyrics

[![GitHub](https://img.shields.io/badge/GitHub-Spotify--Lyrics-6f2cff?style=for-the-badge&logo=github)](https://github.com/kerlycanelita/KoHs-Spotify-Lyrics)
[![Issues](https://img.shields.io/badge/Reportar-Issues-a855f7?style=for-the-badge&logo=githubissues)](https://github.com/kerlycanelita/KoHs-Spotify-Lyrics/issues)
[![Discord](https://img.shields.io/badge/Discord-9t2VxEF7UU-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/9t2VxEF7UU)

**Overlay de letra sincronizada de Spotify para directos, con su propio túnel
HTTPS público y sin abrir puertos del router.**


Overlay local para Windows que detecta Spotify Desktop mediante la sesión multimedia del sistema. Muestra los datos de la canción activa inmediatamente y, cuando existe, añade la letra sincronizada real y su traducción automática al español.

## Inicio rápido

0. Descarga `cloudflared.exe` desde
   [Cloudflare](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
   y déjalo en `tools\cloudflared.exe`. El binario no viaja en el repositorio;
   `iniciar.bat` avisa si falta.
1. Instala Python 3.11 o posterior para Windows y activa `Add Python to PATH`.
2. La primera vez, haz doble clic en `configurar-https-tiktok.bat` y acepta la instalación de la autoridad local privada.
3. Haz doble clic en `iniciar.bat`.
4. Mantén abierta la consola durante el directo.
5. El supervisor crea un enlace público `https://…trycloudflare.com/overlay`, lo guarda en `tiktok-url.txt` y lo copia al portapapeles. El BAT puede cerrarse: los servicios continúan en segundo plano hasta ejecutar `shutdown-all.bat`.
6. Pega ese enlace en la fuente **Enlace** de TikTok LIVE Studio. `localhost` no es aceptado por ese formulario.

La configuración continúa disponible solo en <https://localhost:3443/config>.

Cuando termines el LIVE, haz doble clic en `shutdown-all.bat`. Este archivo apaga tanto el túnel público como los servidores locales de la aplicación; valida la ruta de cada proceso antes de detenerlo para no cerrar otros programas.

Como tamaño inicial usa **800 × 300**. El fondo de `/overlay` es transparente y no incluye controles.

## Regla de visibilidad

El backend mantiene visibles el título, el artista, el álbum y la portada mientras Spotify tenga una canción activa. Solo acepta letras con timestamps reales y una coincidencia estricta de canción, artista, álbum y duración. Si únicamente existe texto plano o la coincidencia no es fiable, la zona de letra permanece vacía y la tarjeta de la canción continúa visible.

| Situación | Resultado en `/overlay` |
|---|---|
| Spotify cerrado o no detectado | Transparente |
| Sesión detenida | Transparente |
| Canción pausada | Visible y congelada en la posición real |
| Solo letra plana | Solo metadatos; la letra no se muestra |
| Ningún proveedor tiene texto | Metadatos visibles, sin línea de letra |
| LRC con timestamps válidos | Metadatos y letra sincronizada visibles |
| Cambio de canción | Los metadatos cambian de inmediato y se busca la nueva letra |
| Seek adelante/atrás o reinicio | Se corrige con la posición de Windows en el siguiente ciclo |
| LRCLIB no disponible | Usa caché positiva; sin ella mantiene los metadatos |
| Portada remota no disponible | Usa la portada entregada por Windows |

## Fuentes de letra

El orden es:

1. LRCLIB `/api/get`, usando canción, artista, álbum y duración.
2. LRCLIB `/api/search`, con coincidencia exacta normalizada y tolerancia de duración de 3 segundos para absorber pequeñas diferencias de catálogo.
3. AMLL TTML API, una base comunitaria con timestamps por línea o palabra e índices de Spotify, Apple Music, QQ Music y NetEase.
4. NetEase Cloud Music, que cubre catálogo japonés, doujin y asiático donde LRCLIB suele tener solo texto plano. Exige coincidencia exacta de título y artista y duración a menos de 3 segundos, y descarta las líneas de créditos que NetEase incrusta dentro del propio LRC.
5. Musixmatch oficial, opcional, únicamente para subtítulos sincronizados LRC.
6. Si ninguna fuente ofrece timestamps reales para la grabación correcta, no se muestra letra.

LRCLIB no necesita cuenta. Musixmatch requiere una API key y que el plan de la cuenta permita `matcher.subtitle.get`. Para activarlo:

1. Obtén una clave en la plataforma oficial de Musixmatch.
2. Copia `secrets.example.json` como `secrets.json`.
3. Sustituye el valor de ejemplo y reinicia la aplicación.

También puedes definir la variable de entorno `MUSIXMATCH_API_KEY`. La clave se lee solo en Python, no forma parte de `config.json`, no se envía por WebSocket y nunca llega al JavaScript.

### Por qué Spotify puede enseñar letra sincronizada y el overlay no

Spotify no expone sus letras por ninguna API: las obtiene de **Musixmatch** bajo licencia y las muestra solo dentro de su aplicación. Las fuentes de este overlay son bases distintas, así que hay canciones que Spotify sincroniza y que aquí solo existen como texto plano. Cuando pasa eso, la aplicación cumple la regla y deja la zona de letra vacía en lugar de inventar tiempos.

Si te ocurre con una canción concreta, comprueba primero si LRCLIB la tiene sincronizada en <https://lrclib.net>. Puedes contribuir la versión sincronizada allí y quedará disponible tanto para ti como para el resto.

No se emplean endpoints privados de Spotify ni tokens extraídos de aplicaciones. Spotify Premium no cambia esta limitación porque la API pública de Spotify no ofrece letras. Si todos los proveedores devuelven texto plano o resultados dudosos, el overlay conserva únicamente los metadatos.

## Traducción

Las líneas sincronizadas se traducen al español mediante MyMemory y, si su cuota diaria se agota, mediante un endpoint público no oficial de Google. Las solicitudes de respaldo se espacian y cambian de ruta si reciben un límite temporal. La traducción se muestra debajo de la línea original, se guarda en `cache/translations` y nunca bloquea ni sustituye la letra original si los servicios remotos fallan. La traducción automática puede requerir correcciones en nombres propios, expresiones o frases ambiguas.

Para una solución totalmente local sin cuotas, los proyectos LibreTranslate y Argos Translate son compatibles como alternativa futura, pero requieren instalar modelos de idiomas considerablemente más pesados que esta aplicación.

## Portadas

La portada de Windows se guarda inmediatamente como fallback. En segundo plano se busca una versión mejor en tres proveedores, por orden:

1. **iTunes Search**, que sirve la portada hasta 3000 × 3000 y responde en una sola consulta.
2. **Deezer**, que devuelve 1000 × 1000 cuando Apple no tiene la grabación. Descarta resultados cuya duración se aleje más de 15 segundos para no traer la carátula de una versión en directo o un remix con el mismo título.
3. **MusicBrainz + Cover Art Archive**, en último lugar porque necesita dos peticiones y está limitado a una por segundo.

MusicBrainz pide identificarse con una forma de contacto. Si alguna vez empieza a rechazar las consultas, define la variable de entorno `KOHS_CONTACT` con tu correo o la URL de tu proyecto y se añadirá al `User-Agent`.

Tanto los resultados como las ausencias se almacenan en `cache/artwork` para evitar consultas repetidas. Al arrancar se borran las entradas de `cache/artwork`, `cache/lyrics` y `cache/translations` que lleven más de 30 días sin actualizarse, de modo que la carpeta no crece sin límite.

Las imágenes se muestran en relación 1:1 con `object-fit: cover`; nunca se deforman.

## Configuración

`/config` permite editar y previsualizar:

- Presets Horizontal, Vertical, Compacto, Lyrics y Minimal. En Vertical, el título y los metadatos quedan arriba y las letras debajo.
- Visibilidad de portada, canción, artista, álbum y ambas líneas de letra.
- Posición, offsets, separación, relleno, ancho y altura.
- Colores HEX, RGB y RGBA, incluida transparencia.
- Arial, Inter, Roboto, Montserrat, Poppins, Open Sans, Oswald, Bebas Neue, Nunito, Lato y Raleway.
- Tipografía, tamaño, peso, negrita, cursiva, alineación, espaciado, opacidad, sombra y contorno por texto.
- Forma, tamaño, radio, borde, sombra y opacidad de portada.
- Una pestaña **Cambio** para animación, curva, duración y salida de la canción anterior.
- Una pestaña **Traducción** para activar las líneas en español y configurar por separado su fuente, tamaño, color, alineación, opacidad, sombra y estilo.
- Una pestaña **Letra FX** para la animación y duración del cambio de línea.

Las pestañas **Cambio** y **Letra FX** incluyen un botón **Probar animación**. Los ajustes tipográficos se aplican sin reiniciar animaciones en cada movimiento del deslizador, evitando tirones en la vista previa.

Cada cambio se aplica de inmediato y se guarda de forma atómica en `config.json`. Si el archivo queda inválido, el programa lo respalda con un nombre `config.invalid-FECHA.json` y restaura valores seguros.

La vista previa abre **Spotify actual** de forma predeterminada y enseña sus metadatos reales aunque la canción no tenga letra sincronizada. El botón **Muestra** permite diseñar con una canción ficticia. Ninguno de los dos modos altera la regla de visibilidad de la URL final.

## Arquitectura y rendimiento

- FastAPI sirve localmente por HTTPS solo en `127.0.0.1:3443`.
- `cloudflared` crea un Quick Tunnel con dominio HTTPS público para que TikTok pueda cargar el overlay sin abrir puertos del router.
- Por el túnel solo se permiten el overlay, sus recursos y consultas de lectura. `/config`, los cambios de configuración y la documentación de la API devuelven 404.
- El canal WebSocket `/ws` también viaja por el túnel, porque es de solo lectura y expone exactamente los mismos datos que `/overlay`. Su permiso es explícito: al no pasar por el middleware HTTP, se comprueba dentro del propio endpoint, así que cualquier WebSocket que se añada en el futuro queda bloqueado por defecto.
- La URL pública es temporal. Un supervisor reinicia `cloudflared` si se cierra y deja el dominio nuevo en `tiktok-url.txt`; como los Quick Tunnels no conservan dominio, si esto ocurre también hay que reemplazar el enlace de la fuente de TikTok. `logs/tunnel.log` conserva el diagnóstico.
- La sesión de Spotify se consulta mediante Windows Global System Media Transport Controls.
- Metadatos: aproximadamente una vez por segundo.
- Posición: cuatro veces por segundo; el navegador interpola entre muestras y se resincroniza en cada actualización.
- Las búsquedas de letra, resultados negativos y portadas tienen caché local.
- Un cambio de canción cancela la resolución anterior para evitar resultados cruzados.

Requiere Windows 10 1809 o posterior y una sesión de usuario interactiva. No funciona como servicio de Windows ni bajo la cuenta `SYSTEM`, porque esas sesiones no exponen las APIs multimedia del usuario.

## Diagnóstico

Comprueba <https://localhost:3443/api/health>. Los estados habituales son:

- `spotify_unavailable`: Spotify Desktop no expone una sesión multimedia.
- `loading_lyrics`: los metadatos están visibles mientras se comprueba la letra.
- `no_synced_lyrics`: ningún proveedor devolvió timestamps válidos; los metadatos permanecen visibles.
- `not_playing`: la sesión está detenida; una pausa conserva la última letra si la canción ya era válida.
- `ready`: el overlay está visible.

Si TikTok conserva una captura antigua, elimina y vuelve a crear la fuente usando la dirección actual guardada en `tiktok-url.txt`. No uses `localhost` en TikTok; se reserva para abrir la configuración en tu propio navegador.

## Pruebas

Desde PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Las pruebas cubren parsing LRC, rechazo de texto plano, caché, fallback de proveedor, traducción, migración de configuración y la política de visibilidad ante cambios de canción y ausencia de Spotify.

La secuencia visual del overlay tiene su propia prueba, sin dependencias más allá de Node:

```powershell
node tests\overlay-swap.test.mjs
```

Comprueba que la tarjeta no cambia hasta tener la portada decodificada, que el hueco de la imagen nunca queda vacío, que una canción sin portada no bloquea el cambio y que una portada que llega tarde se coloca sin repetir la animación.

## Secretos

`secrets.example.json` es la plantilla. Cópiala a `secrets.json` y pon ahí tu
clave si vas a usar el proveedor opcional de Musixmatch. `secrets.json`, la
carpeta `certs/` con la autoridad local y `tiktok-url.txt` están excluidos del
repositorio y no deben subirse.

## Créditos

Hecho por **zymekoh**. La letra viene de LRCLIB y del resto de proveedores
listados arriba; Spotify, TikTok y Cloudflare son de sus respectivos dueños.
