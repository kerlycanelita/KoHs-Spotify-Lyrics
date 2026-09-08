(() => {
  "use strict";

  const parameters = new URLSearchParams(window.location.search);
  const VIRTUAL_WIDTH = 1280;
  const VIRTUAL_HEIGHT = 720;
  const ARTWORK_SWAP_TIMEOUT_MS = 1500;
  const TRANSPARENT_PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
  const previewMode = parameters.get("preview") === "1";
  const samplePreview = previewMode && parameters.get("source") === "sample";
  const elements = {
    card: document.querySelector("#overlay-card"),
    artwork: document.querySelector("#artwork"),
    title: document.querySelector("#track-title"),
    artist: document.querySelector("#artist"),
    album: document.querySelector("#album"),
    currentLyric: document.querySelector("#current-lyric"),
    nextLyric: document.querySelector("#next-lyric"),
    currentTranslation: document.querySelector("#current-translation"),
    nextTranslation: document.querySelector("#next-translation"),
  };

  const sampleState = {
    type: "state",
    revision: 1,
    visible: true,
    status: "ready",
    track: {
      key: "preview-track",
      title: "Luces de medianoche",
      artist: "KoH & The Signals",
      album: "Sesiones en vivo",
      duration_ms: 180000,
      artwork_url: "/static/preview-cover.svg",
    },
    playback: {
      position_ms: 11600,
      duration_ms: 180000,
      is_playing: true,
      is_active: true,
      observed_at_ms: Date.now(),
    },
    lyrics: [
      { time_ms: 0, text: "The city breathes beneath the neon", translation: "La ciudad respira bajo el neón" },
      { time_ms: 4000, text: "Every heartbeat finds its song", translation: "Cada latido encuentra su canción" },
      { time_ms: 8000, text: "Stay here with me a little longer", translation: "Quédate conmigo un poco más" },
      { time_ms: 12000, text: "While the whole world turns around", translation: "Mientras gira el mundo alrededor" },
      { time_ms: 16000, text: "Everything lights up for us", translation: "Todo se ilumina entre los dos" },
    ],
    lyrics_provider: "Vista previa",
    translation_provider: "Vista previa",
  };

  let state = samplePreview ? sampleState : null;
  let config = null;
  let currentTrackKey = null;
  let currentLyricIndex = Number.NaN;
  let currentLyricSignature = "";
  let socket = null;
  let reconnectDelay = 500;
  let statePollInFlight = false;
  let renderedArtworkUrl = "";
  let artworkLoadToken = 0;
  let pendingSwap = null;

  const css = document.documentElement.style;

  function updateViewportScale() {
    const scale = Math.min(
      window.innerWidth / VIRTUAL_WIDTH,
      window.innerHeight / VIRTUAL_HEIGHT,
    );
    css.setProperty("--viewport-scale", String(Math.max(0.01, scale)));
  }

  updateViewportScale();
  window.addEventListener("resize", updateViewportScale, { passive: true });

  function textShadow(style) {
    return style.shadow_enabled
      ? `0 2px ${style.shadow_blur}px ${style.shadow_color}`
      : "none";
  }

  function applyTextStyle(node, style) {
    node.style.color = style.color;
    node.style.fontFamily = `'${style.font_family}', Arial, sans-serif`;
    node.style.fontSize = `${style.size}px`;
    node.style.fontWeight = String(style.bold ? Math.max(style.weight, 700) : style.weight);
    node.style.fontStyle = style.italic ? "italic" : "normal";
    node.style.lineHeight = "1.2";
    node.style.textAlign = style.align;
    node.style.letterSpacing = `${style.letter_spacing}px`;
    node.style.opacity = String(style.opacity);
    node.style.textShadow = textShadow(style);
    node.style.webkitTextStroke = `${style.outline_width}px ${style.outline_color}`;
    node.style.paintOrder = "stroke fill";
  }

  function applyConfig(nextConfig) {
    config = nextConfig;
    const layout = config.layout;
    const card = layout.card;
    const art = config.artwork;
    css.setProperty("--layout-gap", `${layout.gap}px`);
    css.setProperty("--card-padding", `${layout.padding}px`);
    css.setProperty("--card-max-width", `${layout.max_width}px`);
    css.setProperty("--card-min-height", `${layout.min_height}px`);
    css.setProperty("--position-x", `${layout.offset_x}px`);
    css.setProperty("--position-y", `${layout.offset_y}px`);
    css.setProperty("--artwork-size", `${art.size}px`);
    css.setProperty("--artwork-offset-y", `${art.offset_y || 0}px`);
    css.setProperty("--content-offset-y", `${layout.content_offset_y || 0}px`);
    css.setProperty("--song-duration", `${config.animations.song_duration_ms}ms`);
    css.setProperty("--lyric-duration", `${config.animations.lyric_duration_ms}ms`);
    css.setProperty("--song-easing", ({ smooth: "cubic-bezier(.2,.8,.2,1)", snappy: "cubic-bezier(.16,1,.3,1)", linear: "linear", bounce: "cubic-bezier(.34,1.56,.64,1)" })[config.animations.song_easing] || "ease");

    const translations = config.translation.enabled;
    const minimal = layout.preset === "minimal";
    const lineHeight = 1.2;
    let reservedLyricsHeight = 0;
    if (config.elements.current_lyric) {
      reservedLyricsHeight += config.current_lyric.size * lineHeight * 3;
    }
    if (translations && config.translation.show_current) {
      reservedLyricsHeight += config.translated_lyric.size * lineHeight * 3 + 2;
    }
    if (!minimal && config.elements.next_lyric) {
      reservedLyricsHeight += config.next_lyric.size * lineHeight * 2 + 7;
    }
    if (!minimal && translations && config.translation.show_next) {
      reservedLyricsHeight += config.translated_lyric.size * lineHeight * 3 + 2;
    }
    css.setProperty("--lyrics-reserved-height", `${Math.ceil(reservedLyricsHeight)}px`);

    let metadataHeight = 0;
    if (config.elements.title) metadataHeight += config.title.size * lineHeight;
    if (config.elements.artist) metadataHeight += config.artist.size * lineHeight + 2;
    if (config.elements.album) metadataHeight += config.album.size * lineHeight + 1;
    const rowGap = layout.gap * 0.35;
    const contentHeight = metadataHeight + reservedLyricsHeight + rowGap + 8;
    let naturalHeight = contentHeight;
    if (layout.preset === "lyrics") {
      const lyricsArtwork = config.elements.artwork ? Math.min(art.size, 96) : 0;
      naturalHeight += lyricsArtwork + (lyricsArtwork ? layout.gap * 0.7 : 0);
    } else if (layout.preset !== "vertical" && config.elements.artwork) {
      naturalHeight = Math.max(naturalHeight, art.size);
    }
    const stableCardHeight = Math.max(layout.min_height, naturalHeight + layout.padding * 2);
    css.setProperty("--stable-card-height", `${Math.ceil(stableCardHeight)}px`);

    const stage = document.querySelector("#stage");
    stage.style.justifyContent = { left: "flex-start", center: "center", right: "flex-end" }[layout.horizontal_position];
    stage.style.alignItems = { top: "flex-start", center: "center", bottom: "flex-end" }[layout.vertical_position];
    elements.card.style.textAlign = layout.alignment;
    elements.card.style.setProperty("--content-justify", { left: "start", center: "center", right: "end" }[layout.alignment]);
    elements.card.className = `overlay-card preset-${layout.preset}`;
    elements.card.style.background = card.enabled ? card.background_color : "transparent";
    elements.card.style.border = card.enabled ? `${card.border_width}px solid ${card.border_color}` : "none";
    elements.card.style.borderRadius = `${card.radius}px`;
    elements.card.style.boxShadow = card.enabled && card.shadow_enabled
      ? `0 12px ${card.shadow_blur}px ${card.shadow_color}`
      : "none";

    elements.artwork.style.borderRadius = art.shape === "circle" ? "50%" : art.shape === "square" ? "0" : `${art.radius}px`;
    elements.artwork.style.border = `${art.border_width}px solid ${art.border_color}`;
    elements.artwork.style.boxShadow = art.shadow_enabled ? `0 8px ${art.shadow_blur}px ${art.shadow_color}` : "none";
    elements.artwork.style.opacity = String(art.opacity);

    applyTextStyle(elements.title, config.title);
    applyTextStyle(elements.artist, config.artist);
    applyTextStyle(elements.album, config.album);
    applyTextStyle(elements.currentLyric, config.current_lyric);
    applyTextStyle(elements.nextLyric, config.next_lyric);
    applyTextStyle(elements.currentTranslation, config.translated_lyric);
    applyTextStyle(elements.nextTranslation, config.translated_lyric);
    renderState(true, false);
  }

  function effectivePosition() {
    if (!state?.playback) return 0;
    const playback = state.playback;
    let position = Number(playback.position_ms) || 0;
    if (playback.is_playing) {
      position += Math.max(0, Date.now() - Number(playback.observed_at_ms || Date.now()));
    }
    return Math.min(position, Number(playback.duration_ms || Number.MAX_SAFE_INTEGER));
  }

  function findLyricIndex(lines, position) {
    let low = 0;
    let high = lines.length - 1;
    let answer = -1;
    while (low <= high) {
      const middle = (low + high) >> 1;
      if (lines[middle].time_ms <= position) {
        answer = middle;
        low = middle + 1;
      } else {
        high = middle - 1;
      }
    }
    return answer;
  }

  function restartAnimation(node, className, prefix = "lyric-") {
    [...node.classList].filter((name) => name.startsWith(prefix)).forEach((name) => node.classList.remove(name));
    if (!className || className.endsWith("-none")) return;
    void node.offsetWidth;
    node.classList.add(className);
  }

  function animateOutgoingSong() {
    if (!config.animations.song_exit_enabled || config.animations.song === "none") return;
    if (!currentTrackKey || !document.body.classList.contains("overlay-visible")) return;
    const outgoing = elements.card.cloneNode(true);
    outgoing.removeAttribute("id");
    outgoing.querySelectorAll("[id]").forEach((node) => node.removeAttribute("id"));
    [...outgoing.classList].filter((name) => name.startsWith("song-")).forEach((name) => outgoing.classList.remove(name));
    const rectangle = {
      left: elements.card.offsetLeft,
      top: elements.card.offsetTop,
      width: elements.card.offsetWidth,
      height: elements.card.offsetHeight,
    };
    outgoing.classList.add("song-outgoing", `song-exit-${config.animations.song}`);
    outgoing.setAttribute("aria-hidden", "true");
    Object.assign(outgoing.style, {
      position: "fixed",
      left: `${rectangle.left}px`,
      top: `${rectangle.top}px`,
      width: `${rectangle.width}px`,
      height: `${rectangle.height}px`,
      margin: "0",
      transform: window.getComputedStyle(elements.card).transform,
      zIndex: "3",
      pointerEvents: "none",
    });
    document.querySelector("#stage").append(outgoing);
    window.setTimeout(() => outgoing.remove(), config.animations.song_duration_ms + 180);
  }

  function preloadArtwork(url) {
    return new Promise((resolve) => {
      const image = new Image();
      image.decoding = "async";
      image.onload = async () => {
        try { await image.decode(); } catch (_) { /* The decoded image is still usable. */ }
        resolve(true);
      };
      image.onerror = () => resolve(false);
      image.src = url;
    });
  }

  function updateArtwork(track, decodedUrl = "") {
    const enabled = Boolean(config.elements.artwork);
    elements.artwork.hidden = !enabled;
    if (!enabled) return;

    const nextUrl = track?.artwork_url || "";
    if (!nextUrl) {
      // A blank <img> renders the broken-image glyph, so an empty slot keeps a
      // transparent pixel and shows only the placeholder gradient.
      if (elements.artwork.getAttribute("src") !== TRANSPARENT_PIXEL) {
        elements.artwork.src = TRANSPARENT_PIXEL;
      }
      renderedArtworkUrl = "";
      elements.artwork.classList.add("artwork-awaiting");
      return;
    }

    if (nextUrl === renderedArtworkUrl) {
      elements.artwork.classList.remove("artwork-awaiting");
      return;
    }

    if (nextUrl === decodedUrl) {
      // El cambio de canción ya la decodificó: ponerla sin una segunda precarga.
      artworkLoadToken += 1;
      elements.artwork.src = nextUrl;
      renderedArtworkUrl = nextUrl;
      elements.artwork.classList.remove("artwork-awaiting");
      return;
    }

    // The high resolution cover replaces the Windows one for the same song:
    // it is decoded first so the swap cannot show a half painted image.
    const token = ++artworkLoadToken;
    preloadArtwork(nextUrl).then((ready) => {
      if (!ready || token !== artworkLoadToken) return;
      if (state?.track?.artwork_url !== nextUrl) return;
      elements.artwork.src = nextUrl;
      renderedArtworkUrl = nextUrl;
      elements.artwork.classList.remove("artwork-awaiting");
    });
  }

  function cancelTrackSwap() {
    if (!pendingSwap) return;
    window.clearTimeout(pendingSwap.timer);
    pendingSwap = null;
  }

  function beginTrackSwap(trackKey) {
    // The card keeps the previous song untouched until the new cover is ready,
    // so the transition animates real content instead of an empty frame.
    if (!pendingSwap || pendingSwap.key !== trackKey) {
      cancelTrackSwap();
      pendingSwap = {
        key: trackKey,
        url: "",
        timer: window.setTimeout(() => commitTrackSwap(trackKey), ARTWORK_SWAP_TIMEOUT_MS),
      };
    }
    if (!config.elements.artwork) {
      commitTrackSwap(trackKey);
      return;
    }
    const url = state.track?.artwork_url || "";
    if (!url || url === pendingSwap.url) return;
    pendingSwap.url = url;
    preloadArtwork(url).then((ready) => {
      if (!ready || pendingSwap?.key !== trackKey || pendingSwap.url !== url) return;
      commitTrackSwap(trackKey);
    });
  }

  function commitTrackSwap(trackKey) {
    if (state?.track?.key !== trackKey) {
      cancelTrackSwap();
      return;
    }
    const decodedUrl = pendingSwap?.url || "";
    cancelTrackSwap();
    animateOutgoingSong();
    currentTrackKey = trackKey;
    currentLyricIndex = Number.NaN;
    currentLyricSignature = "";
    paintState(true, true, decodedUrl);
    restartAnimation(elements.card, `song-enter-${config.animations.song}`, "song-enter-");
  }

  function renderLyrics(force = false, animate = true) {
    if (!config || pendingSwap) return;
    if (!state?.lyrics?.length) {
      if (!force && currentLyricSignature === "empty") return;
      currentLyricIndex = Number.NaN;
      currentLyricSignature = "empty";
      elements.currentLyric.textContent = "";
      elements.nextLyric.textContent = "";
      elements.currentTranslation.textContent = "";
      elements.nextTranslation.textContent = "";
      return;
    }
    const index = findLyricIndex(state.lyrics, effectivePosition());
    const changedLine = index !== currentLyricIndex;
    const currentLine = index >= 0 ? state.lyrics[index] : null;
    const nextLine = state.lyrics[index + 1] || null;
    const signature = JSON.stringify([
      index,
      currentLine?.text || "",
      nextLine?.text || "",
      currentLine?.translation || "",
      nextLine?.translation || "",
      config.translation.enabled,
      config.translation.show_current,
      config.translation.show_next,
    ]);
    if (!force && signature === currentLyricSignature) return;
    currentLyricIndex = index;
    currentLyricSignature = signature;
    elements.currentLyric.textContent = currentLine?.text || "";
    elements.nextLyric.textContent = nextLine?.text || "";
    elements.currentTranslation.textContent = config.translation.enabled ? currentLine?.translation || "" : "";
    elements.nextTranslation.textContent = config.translation.enabled ? nextLine?.translation || "" : "";
    elements.currentTranslation.hidden = !config.translation.enabled || !config.translation.show_current || !elements.currentTranslation.textContent;
    elements.nextTranslation.hidden = !config.translation.enabled || !config.translation.show_next || !elements.nextTranslation.textContent;
    if (!animate || (!force && !changedLine)) return;
    const animation = `lyric-${config.animations.lyric}`;
    restartAnimation(elements.currentLyric, animation);
    restartAnimation(elements.nextLyric, animation);
    restartAnimation(elements.currentTranslation, animation);
    restartAnimation(elements.nextTranslation, animation);
  }

  function paintState(force, animate, decodedUrl = "") {
    if (force) {
      elements.title.textContent = state.track?.title || "";
      elements.artist.textContent = state.track?.artist || "";
      elements.album.textContent = state.track?.album || "";
    }
    const visibility = config.elements;
    updateArtwork(state.track, decodedUrl);
    elements.title.hidden = !visibility.title;
    elements.artist.hidden = !visibility.artist;
    elements.album.hidden = !visibility.album;
    elements.currentLyric.hidden = !visibility.current_lyric;
    elements.nextLyric.hidden = !visibility.next_lyric;
    renderLyrics(force, animate);
    document.body.classList.remove("overlay-hidden");
    document.body.classList.add("overlay-visible");
    elements.card.setAttribute("aria-hidden", "false");
  }

  function renderState(force = false, animate = true) {
    if (!state || !config) return;
    const shouldShow = samplePreview
      || (previewMode ? Boolean(state.track) : state.visible && Boolean(state.track));
    if (!shouldShow) {
      cancelTrackSwap();
      document.body.classList.remove("overlay-visible");
      document.body.classList.add("overlay-hidden");
      elements.card.setAttribute("aria-hidden", "true");
      return;
    }

    const trackKey = state.track?.key || null;
    if (trackKey !== currentTrackKey) {
      beginTrackSwap(trackKey);
      return;
    }
    if (pendingSwap) return;
    paintState(force, animate);
  }

  function handleMessage(message) {
    if (message.type === "config") {
      applyConfig(message.config);
    } else if (message.type === "state" && !samplePreview) {
      state = message;
      renderState();
    } else if (message.type === "playback" && !samplePreview && state) {
      state.playback = message.playback;
      state.visible = message.visible;
      state.status = message.status;
      renderState(false, true);
    }
  }

  function connect() {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${protocol}://${location.host}/ws`);
    socket.addEventListener("open", () => { reconnectDelay = 500; });
    socket.addEventListener("message", (event) => {
      if (event.data === "pong") return;
      try { handleMessage(JSON.parse(event.data)); } catch (_) { /* ignore malformed frames */ }
    });
    socket.addEventListener("close", () => {
      window.setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.8, 8000);
    });
  }

  async function pollState() {
    if (samplePreview || statePollInFlight || socket?.readyState === WebSocket.OPEN) return;
    statePollInFlight = true;
    try {
      const response = await fetch(`/api/state?now=${Date.now()}`, { cache: "no-store" });
      if (response.ok) handleMessage(await response.json());
    } catch (_) { /* WebSocket or the next poll will recover. */ }
    finally { statePollInFlight = false; }
  }

  window.addEventListener("message", (event) => {
    if (!previewMode || event.origin !== location.origin) return;
    if (event.data?.type === "preview-config" && event.data.config) {
      applyConfig(event.data.config);
    } else if (event.data?.type === "preview-replay" && event.data.scope === "song") {
      animateOutgoingSong();
      restartAnimation(elements.card, `song-enter-${config.animations.song}`, "song-enter-");
    } else if (event.data?.type === "preview-replay" && event.data.scope === "lyric") {
      const animation = `lyric-${config.animations.lyric}`;
      restartAnimation(elements.currentLyric, animation);
      restartAnimation(elements.nextLyric, animation);
      restartAnimation(elements.currentTranslation, animation);
      restartAnimation(elements.nextTranslation, animation);
    }
  });

  Promise.all([
    fetch("/api/config", { cache: "no-store" }).then((response) => response.json()),
    samplePreview ? Promise.resolve(sampleState) : fetch("/api/state", { cache: "no-store" }).then((response) => response.json()),
  ]).then(([loadedConfig, loadedState]) => {
    state = samplePreview ? sampleState : loadedState;
    applyConfig(loadedConfig);
    if (!samplePreview) {
      connect();
      window.setInterval(pollState, 1600);
      window.setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
      }, 15000);
    }
    const updateTimedLyrics = () => {
      if (samplePreview) {
        const elapsed = (Date.now() - sampleState.playback.observed_at_ms) % 20000;
        sampleState.playback.position_ms = 0;
        sampleState.playback.observed_at_ms = Date.now() - elapsed;
      }
      renderLyrics();
    };
    window.setInterval(updateTimedLyrics, 100);
  }).catch(() => {
    document.body.classList.add("overlay-hidden");
  });
})();
