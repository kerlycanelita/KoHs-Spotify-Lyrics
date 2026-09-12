# GitHub-controlled temporary overlay

This mode lets GitHub Actions control the existing local Windows overlay without moving Spotify detection to the cloud.

## Why a self-hosted Windows runner is required

KoH's Spotify Lyrics reads Spotify Desktop through the Windows Global System Media Transport Controls session. A normal GitHub-hosted runner cannot see the media session on your PC.

Configure a **self-hosted Windows x64 runner on the same PC where Spotify Desktop is running**. Run the GitHub runner interactively inside your normal Windows user session. Do not install/run it as a Windows service, because a service session cannot see the interactive user's media session.

Repository path in GitHub:

`Settings -> Actions -> Runners -> New self-hosted runner -> Windows -> x64`

Follow GitHub's generated setup commands. When GitHub asks whether to run the runner as a service, use the interactive runner (`run.cmd`) instead.

## Start

1. Keep Spotify Desktop open on the runner PC.
2. Keep the self-hosted GitHub runner online with `run.cmd`.
3. Open `Actions -> Start overlay -> Run workflow`.
4. Choose 1 to 5 hours. The default is 5 hours.
5. Open the finished workflow run and read its **Summary**. It contains the public `https://...trycloudflare.com/overlay` URL.
6. Paste that URL into TikTok LIVE Studio or another browser-source overlay.

The workflow downloads `cloudflared.exe` automatically and keeps the runtime under:

`%LOCALAPPDATA%\KoHsSpotifyLyricsGitHub\app`

The public URL stays alive after the GitHub job itself finishes. A detached timer automatically calls the project's existing `shutdown_all.py` after the chosen duration.

## Shutdown early

Open:

`Actions -> Shutdown overlay -> Run workflow`

This invokes the existing verified shutdown logic and removes the active-session marker. The Cloudflare URL stops responding once the tunnel is terminated.

## Configuration persistence

The last `config.json` from the GitHub runtime is preserved under `%LOCALAPPDATA%\KoHsSpotifyLyricsGitHub` and restored on the next GitHub start.

## Musixmatch (optional)

If you use the optional Musixmatch fallback, create a repository Actions secret named:

`MUSIXMATCH_API_KEY`

The workflow exposes that secret only as an environment variable to the local runtime; it is not written into the repository.

## Security behavior

The existing tunnel allowlist remains in charge: the public Cloudflare URL exposes only the overlay/read-only resources already permitted by the application. Configuration remains local to the runner PC.
