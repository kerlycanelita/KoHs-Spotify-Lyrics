# KoH's Spotify Lyrics

[![GitHub](https://img.shields.io/badge/GitHub-Spotify--Lyrics-6f2cff?style=for-the-badge&logo=github)](https://github.com/kerlycanelita/KoHs-Spotify-Lyrics)
[![Issues](https://img.shields.io/badge/Report-Issues-a855f7?style=for-the-badge&logo=githubissues)](https://github.com/kerlycanelita/KoHs-Spotify-Lyrics/issues)
[![Discord](https://img.shields.io/badge/Join-Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/9t2VxEF7UU)

**A synced Spotify lyrics overlay for live streams, with its own public HTTPS
tunnel and no router ports to open.**

A local Windows overlay that detects Spotify Desktop through the system media
session. It shows the active track's data immediately and, where one exists,
adds the real synced lyric line and its automatic Spanish translation.

## Quick start

0. Download `cloudflared.exe` from
   [Cloudflare](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
   and leave it at `tools\cloudflared.exe`. The binary does not travel in the
   repository; `iniciar.bat` warns if it is missing.
1. Install Python 3.11 or later for Windows and tick `Add Python to PATH`.
2. The first time, double-click `configurar-https-tiktok.bat` and accept the
   installation of the private local certificate authority.
3. Double-click `iniciar.bat`.
4. Keep the console open during the stream.
5. The supervisor creates a public `https://…trycloudflare.com/overlay` link,
   saves it to `tiktok-url.txt` and copies it to the clipboard. The BAT window
   can be closed: the services keep running in the background until
   `shutdown-all.bat` is run.
6. Paste that link into TikTok LIVE Studio's **Link** source. `localhost` is not
   accepted by that form.

Configuration stays available only at <https://localhost:3443/config>.

When the stream is over, double-click `shutdown-all.bat`. It shuts down both the
public tunnel and the application's local servers, and validates each process's
path before stopping it so that other programs are left alone.

Use **800 × 300** as the initial size. The `/overlay` background is transparent
and carries no controls.

## Visibility rule

The backend keeps the title, artist, album and artwork visible for as long as
Spotify has an active track. It only accepts lyrics with real timestamps and a
strict match on song, artist, album and duration. If all that exists is plain
text, or the match is not reliable, the lyric area stays empty and the track card
stays visible.

| Situation | Result in `/overlay` |
|---|---|
| Spotify closed or not detected | Transparent |
| Session stopped | Transparent |
| Track paused | Visible and frozen at the real position |
| Plain-text lyrics only | Metadata only; no lyric shown |
| No provider has any text | Metadata visible, no lyric line |
| LRC with valid timestamps | Metadata and synced lyric visible |
| Track change | Metadata changes at once and the new lyric is looked up |
| Seek forward/back or restart | Corrected from the Windows position on the next cycle |
| LRCLIB unavailable | Uses the positive cache; without it, keeps the metadata |
| Remote artwork unavailable | Uses the artwork Windows provides |

## Lyric sources

In order:

1. **LRCLIB `/api/get`**, using song, artist, album and duration.
2. **LRCLIB `/api/search`**, with a normalised exact match and a 3-second
   duration tolerance to absorb small catalogue differences.
3. **AMLL TTML API**, a community database with per-line or per-word timestamps
   and indexes for Spotify, Apple Music, QQ Music and NetEase.
4. **NetEase Cloud Music**, which covers Japanese, doujin and Asian catalogue
   where LRCLIB usually has plain text only. It demands an exact title and
   artist match and a duration within 3 seconds, and discards the credit lines
   NetEase embeds inside the LRC itself.
5. **Musixmatch official**, optional, for synced LRC subtitles only.
6. If no source offers real timestamps for the correct recording, no lyric is
   shown.

LRCLIB needs no account. Musixmatch needs an API key and an account plan that
allows `matcher.subtitle.get`. To enable it:

1. Get a key from Musixmatch's official platform.
2. Copy `secrets.example.json` to `secrets.json`.
3. Replace the example value and restart the application.

The `MUSIXMATCH_API_KEY` environment variable works too. The key is read only in
Python: it is not part of `config.json`, is never sent over the WebSocket, and
never reaches the JavaScript.

### Why Spotify can show a synced lyric and this overlay cannot

Spotify does not expose its lyrics through any API. It licenses them from
**Musixmatch** and shows them only inside its own application. This overlay's
sources are different databases, so there are tracks Spotify syncs that exist
here as plain text only. When that happens, the application follows the rule and
leaves the lyric area empty instead of inventing timings.

If it happens on a specific track, check first whether LRCLIB has it synced at
<https://lrclib.net>. You can contribute the synced version there, and it becomes
available both to you and to everyone else.

No private Spotify endpoints and no tokens extracted from applications are used.
Spotify Premium does not change this limitation, because Spotify's public API
does not offer lyrics. If every provider returns plain text or doubtful results,
the overlay keeps the metadata alone.

## Translation

Synced lines are translated into Spanish through MyMemory and, once its daily
quota runs out, through an unofficial public Google endpoint. The fallback
requests are spaced out and change route if they hit a temporary limit. The
translation is shown below the original line, is stored in `cache/translations`,
and never blocks or replaces the original lyric if the remote services fail.
Machine translation can need corrections on proper nouns, idioms and ambiguous
phrasing.

For a fully local solution with no quotas, LibreTranslate and Argos Translate are
compatible as a future alternative, but they require installing language models
considerably heavier than this application.

## Artwork

The Windows artwork is stored immediately as a fallback. In the background, a
better version is looked up across three providers, in order:

1. **iTunes Search**, which serves artwork up to 3000 × 3000 and answers in a
   single query.
2. **Deezer**, which returns 1000 × 1000 when Apple does not have the recording.
   It discards results whose duration is more than 15 seconds away, so it does
   not bring back the cover of a live version or a remix with the same title.
3. **MusicBrainz + Cover Art Archive**, last because it needs two requests and is
   limited to one per second.

MusicBrainz asks callers to identify themselves with a contact. If it ever starts
rejecting queries, set the `KOHS_CONTACT` environment variable to your email or
your project URL and it will be added to the `User-Agent`.

Both hits and misses are stored in `cache/artwork` to avoid repeated queries. On
start-up, entries in `cache/artwork`, `cache/lyrics` and `cache/translations`
that have not been updated in more than 30 days are deleted, so the folder does
not grow without limit.

Images are shown at a 1:1 ratio with `object-fit: cover`; they are never
distorted.

## Configuration

`/config` edits and previews:

- Horizontal, Vertical, Compact, Lyrics and Minimal presets. In Vertical, the
  title and metadata sit above and the lyrics below.
- Visibility of artwork, song, artist, album and both lyric lines.
- Position, offsets, spacing, padding, width and height.
- HEX, RGB and RGBA colours, transparency included.
- Arial, Inter, Roboto, Montserrat, Poppins, Open Sans, Oswald, Bebas Neue,
  Nunito, Lato and Raleway.
- Typeface, size, weight, bold, italic, alignment, spacing, opacity, shadow and
  outline, per text.
- Artwork shape, size, radius, border, shadow and opacity.
- A **Change** tab for the animation, curve, duration and exit of the previous
  track.
- A **Translation** tab to enable the Spanish lines and configure their font,
  size, colour, alignment, opacity, shadow and style separately.
- A **Lyric FX** tab for the line-change animation and its duration.

The **Change** and **Lyric FX** tabs include a **Test animation** button.
Typographic settings are applied without restarting animations on every slider
movement, which keeps the preview from stuttering.

Every change applies immediately and is saved atomically to `config.json`. If the
file ends up invalid, the program backs it up as `config.invalid-DATE.json` and
restores safe values.

The preview opens **current Spotify** by default and shows its real metadata even
when the track has no synced lyric. The **Sample** button allows designing
against a fictional track. Neither mode alters the visibility rule of the final
URL.

## Architecture and performance

- FastAPI serves locally over HTTPS on `127.0.0.1:3443` only.
- `cloudflared` creates a Quick Tunnel with a public HTTPS domain so TikTok can
  load the overlay without opening router ports.
- Only the overlay, its resources and read queries are allowed through the
  tunnel. `/config`, configuration changes and the API documentation return 404.
- The `/ws` WebSocket channel also travels through the tunnel, because it is
  read-only and exposes exactly the same data as `/overlay`. Its permission is
  explicit: since it does not pass through the HTTP middleware, it is checked
  inside the endpoint itself, so any WebSocket added in the future is blocked by
  default.
- The public URL is temporary. A supervisor restarts `cloudflared` if it closes
  and leaves the new domain in `tiktok-url.txt`; since Quick Tunnels do not keep
  a domain, when this happens the link in the TikTok source has to be replaced
  too. `logs/tunnel.log` keeps the diagnostics.
- The Spotify session is queried through Windows Global System Media Transport
  Controls.
- Metadata: roughly once per second.
- Position: four times per second; the browser interpolates between samples and
  resynchronises on every update.
- Lyric lookups, negative results and artwork are cached locally.
- A track change cancels the previous resolution, to avoid crossed results.

Requires Windows 10 1809 or later and an interactive user session. It does not
work as a Windows service or under the `SYSTEM` account, because those sessions
do not expose the user's media APIs.

## Diagnostics

Check <https://localhost:3443/api/health>. The usual states are:

- `spotify_unavailable`: Spotify Desktop is not exposing a media session.
- `loading_lyrics`: metadata is visible while the lyric is being checked.
- `no_synced_lyrics`: no provider returned valid timestamps; metadata stays
  visible.
- `not_playing`: the session is stopped; a pause keeps the last lyric if the
  track was already valid.
- `ready`: the overlay is visible.

If TikTok keeps an old capture, delete and recreate the source using the current
address saved in `tiktok-url.txt`. Do not use `localhost` in TikTok; it is
reserved for opening the configuration in your own browser.

## Tests

From PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

The tests cover LRC parsing, plain-text rejection, caching, provider fallback,
translation, configuration migration, and the visibility policy across track
changes and Spotify being absent.

The overlay's visual sequence has its own test, with no dependency beyond Node:

```powershell
node tests\overlay-swap.test.mjs
```

It checks that the card does not change until the artwork has been decoded, that
the image slot is never left empty, that a track without artwork does not block
the change, and that artwork arriving late is placed without replaying the
animation.

## Secrets

`secrets.example.json` is the template. Copy it to `secrets.json` and put your
key there if you are going to use the optional Musixmatch provider.
`secrets.json`, the `certs/` folder holding the local authority, and
`tiktok-url.txt` are excluded from the repository and must not be uploaded.

## Credits

Made by **zymekoh**. Lyrics come from LRCLIB and the other providers listed
above; Spotify, TikTok and Cloudflare belong to their respective owners.

The application's own interface and its `.bat` scripts are in Spanish, which is
the language of the streams it was built for.
