(() => {
  "use strict";

  const host = document.querySelector("#control-content");
  const frame = document.querySelector("#preview-frame");
  const saveStatus = document.querySelector("#save-status");
  const fontGroups = [
    ["Clásicas y legibles", ["Arial", "Inter", "Roboto", "Open Sans", "Lato", "Noto Sans", "Noto Serif", "Merriweather", "Merriweather Sans", "Libre Baskerville", "Lora", "Vollkorn", "Zilla Slab"]],
    ["Modernas", ["Montserrat", "Poppins", "Nunito", "Raleway", "DM Sans", "Manrope", "Urbanist", "Work Sans", "Rubik", "Lexend", "Space Grotesk", "Archivo", "Archivo Black", "Barlow", "Fira Sans", "Karla", "Ubuntu", "Cabin", "Cairo"]],
    ["Condensadas y streaming", ["Oswald", "Bebas Neue", "Barlow Condensed", "Roboto Condensed", "Anton", "Teko", "Rajdhani", "Saira", "Titillium Web", "Fjalla One", "Kanit", "Prompt"]],
    ["Futuristas y gaming", ["Orbitron", "Chakra Petch", "Exo 2", "Unbounded", "Syncopate", "Russo One", "Black Ops One", "Bungee", "Monoton", "Righteous", "Press Start 2P", "Silkscreen", "Jersey 10", "Graduate", "Space Mono"]],
    ["Elegantes y editoriales", ["Playfair Display", "Cinzel", "Cormorant Garamond", "Bitter", "Abril Fatface", "Alfa Slab One", "Poiret One", "Josefin Sans"]],
    ["Amigables y redondeadas", ["Quicksand", "Comfortaa", "Dosis", "Fredoka", "Maven Pro", "League Spartan", "Lilita One", "Luckiest Guy", "Staatliches"]],
    ["Manuscritas y creativas", ["Amatic SC", "Caveat", "Dancing Script", "Great Vibes", "Indie Flower", "Kaushan Script", "Lobster", "Pacifico", "Permanent Marker", "Satisfy", "Shadows Into Light", "Special Elite", "Yellowtail"]],
  ];
  let config = null;
  let activeTab = "general";
  let textTarget = "current_lyric";
  let saveTimer = 0;
  let saveChain = Promise.resolve();
  let dirty = false;
  let previewSource = "live";

  document.querySelector("#overlay-url").textContent = `${location.origin}/overlay`;

  const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));

  function getPath(path) {
    return path.split(".").reduce((value, key) => value[key], config);
  }

  function setPath(path, value) {
    const keys = path.split(".");
    const last = keys.pop();
    const target = keys.reduce((object, key) => object[key], config);
    target[last] = value;
  }

  function isTextTargetVisible() {
    return Boolean(getPath(`elements.${textTarget}`));
  }

  function hasVisibleTranslation() {
    return Boolean(config.translation.enabled && (config.translation.show_current || config.translation.show_next));
  }

  function hasVisibleLyricOutput() {
    return Boolean(
      config.elements.current_lyric
      || config.elements.next_lyric
      || hasVisibleTranslation()
    );
  }

  const dependencyRules = {
    "card-enabled": () => Boolean(config.layout.card.enabled),
    "card-border": () => Boolean(config.layout.card.enabled && config.layout.card.border_width > 0),
    "card-shadow": () => Boolean(config.layout.card.enabled && config.layout.card.shadow_enabled),
    "artwork-visible": () => Boolean(config.elements.artwork),
    "artwork-rounded": () => Boolean(config.elements.artwork && config.artwork.shape === "rounded"),
    "artwork-border": () => Boolean(config.elements.artwork && config.artwork.border_width > 0),
    "artwork-shadow": () => Boolean(config.elements.artwork && config.artwork.shadow_enabled),
    "text-visible": () => isTextTargetVisible(),
    "text-weight": () => Boolean(isTextTargetVisible() && !getPath(`${textTarget}.bold`)),
    "text-shadow": () => Boolean(isTextTargetVisible() && getPath(`${textTarget}.shadow_enabled`)),
    "text-outline": () => Boolean(isTextTargetVisible() && getPath(`${textTarget}.outline_width`) > 0),
    "translation-enabled": () => Boolean(config.translation.enabled),
    "translation-visible": () => hasVisibleTranslation(),
    "translation-weight": () => Boolean(hasVisibleTranslation() && !config.translated_lyric.bold),
    "translation-shadow": () => Boolean(hasVisibleTranslation() && config.translated_lyric.shadow_enabled),
    "song-animation": () => config.animations.song !== "none",
    "lyrics-available": () => hasVisibleLyricOutput(),
    "lyric-animation": () => Boolean(hasVisibleLyricOutput() && config.animations.lyric !== "none"),
  };

  function dependentGroup(key, message, content) {
    return `<div class="option-children" data-dependency="${key}" data-disabled-message="${escapeHtml(message)}"><div class="dependency-message" role="status">${escapeHtml(message)}</div>${content}</div>`;
  }

  function optionBranch(parent, key, message, children) {
    return `<div class="option-branch"><div class="option-parent">${parent}</div>${dependentGroup(key, message, children)}</div>`;
  }

  function applyDependencyState() {
    host.querySelectorAll("[data-dependency]").forEach((group) => {
      const rule = dependencyRules[group.dataset.dependency];
      const enabled = rule ? Boolean(rule()) : true;
      group.classList.toggle("is-disabled", !enabled);
      group.setAttribute("aria-disabled", String(!enabled));
    });

    host.querySelectorAll("input, select, button").forEach((control) => {
      control.disabled = Boolean(control.closest(".option-children.is-disabled"));
    });

    host.querySelectorAll("[data-text-target]").forEach((button) => {
      const visible = Boolean(getPath(`elements.${button.dataset.textTarget}`));
      button.classList.toggle("is-hidden-target", !visible);
      button.title = visible ? "Elemento visible" : "Elemento oculto en el overlay";
    });
  }

  function section(title, description, content) {
    return `<section class="section"><div class="section-heading"><h2>${title}</h2>${description ? `<p>${description}</p>` : ""}</div>${content}</section>`;
  }

  function toggle(label, path) {
    return `<div class="toggle-row"><label for="${path}">${label}</label><label class="switch"><input id="${path}" type="checkbox" data-path="${path}" ${getPath(path) ? "checked" : ""}><span></span></label></div>`;
  }

  function range(label, path, min, max, step = 1, suffix = "px", full = false) {
    const value = getPath(path);
    return `<div class="field ${full ? "full" : ""}"><label class="field-label" for="${path}"><span>${label}</span><output data-output="${path}">${value}${suffix}</output></label><input id="${path}" type="range" min="${min}" max="${max}" step="${step}" value="${value}" data-path="${path}"></div>`;
  }

  function number(label, path, min, max, suffix = "px") {
    const value = getPath(path);
    return `<div class="field"><label class="field-label" for="${path}"><span>${label}</span><output data-output="${path}">${value}${suffix}</output></label><input id="${path}" type="number" min="${min}" max="${max}" value="${value}" data-path="${path}"></div>`;
  }

  function select(label, path, options, full = false) {
    const value = getPath(path);
    const choices = options.map(([optionValue, optionLabel]) => `<option value="${escapeHtml(optionValue)}" ${value === optionValue ? "selected" : ""}>${escapeHtml(optionLabel)}</option>`).join("");
    return `<div class="field ${full ? "full" : ""}"><label class="field-label" for="${path}"><span>${label}</span></label><select id="${path}" data-path="${path}">${choices}</select></div>`;
  }

  function fontSelect(path) {
    const value = getPath(path);
    const groups = fontGroups.map(([label, groupFonts]) => {
      const options = groupFonts.map((font) => `<option value="${escapeHtml(font)}" ${value === font ? "selected" : ""}>${escapeHtml(font)}</option>`).join("");
      return `<optgroup label="${escapeHtml(label)}">${options}</optgroup>`;
    }).join("");
    return `<div class="field full"><label class="field-label" for="${path}"><span>Tipografía</span><output class="font-count">${fontGroups.reduce((total, [, groupFonts]) => total + groupFonts.length, 0)} fuentes</output></label><select id="${path}" data-path="${path}" data-font-select style="font-family:'${escapeHtml(value)}', Arial, sans-serif">${groups}</select></div>`;
  }

  function toHex(value) {
    if (/^#[0-9a-f]{6}$/i.test(value)) return value;
    if (/^#[0-9a-f]{3}$/i.test(value)) return `#${value.slice(1).split("").map((c) => c + c).join("")}`;
    const match = String(value).match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
    if (!match) return "#ffffff";
    return `#${match.slice(1, 4).map((part) => Number(part).toString(16).padStart(2, "0")).join("")}`;
  }

  function color(label, path, full = false) {
    const value = getPath(path);
    return `<div class="field ${full ? "full" : ""}"><label class="field-label" for="${path}-text"><span>${label}</span></label><div class="color-control"><input type="color" aria-label="Selector para ${escapeHtml(label)}" value="${toHex(value)}" data-path="${path}" data-color-picker><input id="${path}-text" type="text" spellcheck="false" value="${escapeHtml(value)}" data-path="${path}" data-color-text></div></div>`;
  }

  function renderGeneral() {
    const presetNames = [
      ["horizontal", "Horizontal", "Portada y contenido lateral"],
      ["compact", "Compacto", "Información más condensada"],
      ["lyrics", "Lyrics", "La letra toma protagonismo"],
      ["vertical", "Vertical", "Título arriba y letras debajo"],
      ["minimal", "Minimal", "Solo lo esencial"],
    ];
    const presets = `<div class="preset-grid">${presetNames.map(([value, title, detail]) => `<button type="button" data-preset="${value}" class="${config.layout.preset === value ? "active" : ""}"><strong>${title}</strong><small>${detail}</small></button>`).join("")}</div>`;
    const visibility = `<div class="toggle-list">${toggle("Portada", "elements.artwork")}${toggle("Canción", "elements.title")}${toggle("Artista", "elements.artist")}${toggle("Álbum", "elements.album")}${toggle("Letra actual", "elements.current_lyric")}${toggle("Letra siguiente", "elements.next_lyric")}</div>`;
    const layout = `<div class="field-grid">
      ${select("Posición horizontal", "layout.horizontal_position", [["left", "Izquierda"], ["center", "Centro"], ["right", "Derecha"]])}
      ${select("Posición vertical", "layout.vertical_position", [["top", "Arriba"], ["center", "Centro"], ["bottom", "Abajo"]])}
      ${number("Desplazamiento X", "layout.offset_x", -800, 800)}
      ${number("Desplazamiento Y", "layout.offset_y", -800, 800)}
      ${range("Contenido vertical (− sube / + baja)", "layout.content_offset_y", -120, 120, 1, "px", true)}
      ${select("Alineación del contenido", "layout.alignment", [["left", "Izquierda"], ["center", "Centro"], ["right", "Derecha"]], true)}
      ${range("Separación", "layout.gap", 0, 64)}
      ${range("Relleno", "layout.padding", 0, 80)}
      ${range("Ancho máximo", "layout.max_width", 180, 1600, 10)}
      ${range("Altura mínima", "layout.min_height", 0, 800, 1)}
    </div>`;
    const cardBorder = optionBranch(
      range("Grosor del borde", "layout.card.border_width", 0, 10, 1, "px", true),
      "card-border",
      "Aumenta el grosor del borde para configurar su color.",
      `<div class="field-grid">${color("Color del borde", "layout.card.border_color", true)}</div>`,
    );
    const cardShadow = optionBranch(
      toggle("Sombra", "layout.card.shadow_enabled"),
      "card-shadow",
      "Activa la sombra para configurar su color y desenfoque.",
      `<div class="field-grid">${color("Color de sombra", "layout.card.shadow_color")}${range("Desenfoque", "layout.card.shadow_blur", 0, 80)}</div>`,
    );
    const card = optionBranch(
      toggle("Fondo de tarjeta", "layout.card.enabled"),
      "card-enabled",
      "Activa el fondo de tarjeta para editar su apariencia.",
      `<div class="field-grid">${color("Fondo (admite RGBA)", "layout.card.background_color", true)}${range("Radio", "layout.card.radius", 0, 60, 1, "px", true)}</div>${cardBorder}${cardShadow}`,
    );
    host.innerHTML = section("Composición", "Elige una base y después ajusta cada detalle.", presets)
      + section("Elementos visibles", "Ocultarlos no detiene la sincronización interna.", visibility)
      + section("Posición y dimensiones", "El contenido siempre se adapta al tamaño de la fuente URL.", layout)
      + section("Tarjeta", "Puedes dejarla totalmente transparente.", card);
  }

  function renderText() {
    const labels = { title: "Canción", artist: "Artista", album: "Álbum", current_lyric: "Letra actual", next_lyric: "Letra siguiente" };
    const selector = `<div class="segmented">${Object.entries(labels).map(([key, label]) => `<button type="button" data-text-target="${key}" class="${textTarget === key ? "active" : ""}">${label}</button>`).join("")}</div>`;
    const path = textTarget;
    const controls = `<div class="field-grid">
      ${fontSelect(`${path}.font_family`)}
      ${color("Color", `${path}.color`, true)}
      ${range("Tamaño", `${path}.size`, 8, 120)}
      ${range("Espaciado", `${path}.letter_spacing`, -3, 16, .1)}
      ${range("Opacidad", `${path}.opacity`, 0, 1, .05, "")}
      ${select("Alineación", `${path}.align`, [["left", "Izquierda"], ["center", "Centro"], ["right", "Derecha"]], true)}
    </div><div class="toggle-list" style="margin-top:15px">${toggle("Negrita rápida", `${path}.bold`)}${toggle("Cursiva", `${path}.italic`)}</div>${dependentGroup("text-weight", "Desactiva Negrita rápida para elegir un peso personalizado.", `<div class="field-grid">${select("Peso", `${path}.weight`, [[100, "100 · Fino"], [200, "200"], [300, "300"], [400, "400 · Normal"], [500, "500"], [600, "600"], [700, "700 · Negrita"], [800, "800"], [900, "900 · Negro"]], true)}</div>`)}`;
    const shadow = optionBranch(
      toggle("Sombra de texto", `${path}.shadow_enabled`),
      "text-shadow",
      "Activa la sombra de texto para editarla.",
      `<div class="field-grid">${color("Color de sombra", `${path}.shadow_color`)}${range("Desenfoque", `${path}.shadow_blur`, 0, 40)}</div>`,
    );
    const outline = optionBranch(
      range("Grosor del contorno", `${path}.outline_width`, 0, 5, .25, "", true),
      "text-outline",
      "Aumenta el grosor del contorno para elegir su color.",
      `<div class="field-grid">${color("Color del contorno", `${path}.outline_color`, true)}</div>`,
    );
    const visibleControls = optionBranch(
      toggle("Mostrar este texto", `elements.${textTarget}`),
      "text-visible",
      "Muestra este elemento para editar su estilo.",
      controls,
    );
    const effects = dependentGroup("text-visible", "Muestra este elemento para configurar sus efectos.", shadow + outline);
    host.innerHTML = section("Estilo tipográfico", "Cada bloque puede tener una identidad independiente.", selector + visibleControls)
      + section("Sombra y contorno", "Usa valores suaves para conservar la lectura.", effects);
  }

  function renderArtwork() {
    const content = `<div class="field-grid">
      ${select("Forma", "artwork.shape", [["square", "Cuadrada"], ["rounded", "Bordes redondeados"], ["circle", "Circular"]], true)}
      ${range("Tamaño", "artwork.size", 40, 300, 2)}
      ${range("Portada vertical (− sube / + baja)", "artwork.offset_y", -120, 120, 1, "px", true)}
      ${range("Opacidad", "artwork.opacity", 0, 1, .05, "")}
      ${range("Grosor del borde", "artwork.border_width", 0, 12)}
    </div>`;
    const radius = dependentGroup("artwork-rounded", "El radio personalizado solo se usa con Bordes redondeados.", `<div class="field-grid">${range("Radio personalizado", "artwork.radius", 0, 80, 1, "px", true)}</div>`);
    const border = dependentGroup("artwork-border", "Aumenta el grosor del borde para elegir su color.", `<div class="field-grid">${color("Color del borde", "artwork.border_color", true)}</div>`);
    const shadow = dependentGroup("artwork-visible", "Muestra la portada para configurar su sombra.", optionBranch(
      toggle("Sombra de portada", "artwork.shadow_enabled"),
      "artwork-shadow",
      "Activa la sombra de portada para editarla.",
      `<div class="field-grid">${color("Color de sombra", "artwork.shadow_color")}${range("Desenfoque", "artwork.shadow_blur", 0, 60)}</div>`,
    ));
    const artwork = optionBranch(
      toggle("Mostrar portada", "elements.artwork"),
      "artwork-visible",
      "Muestra la portada para habilitar sus opciones.",
      content + radius + border,
    );
    host.innerHTML = section("Portada", "Siempre mantiene relación 1:1 y usa object-fit: cover.", artwork)
      + section("Sombra", "La portada de alta resolución reemplaza automáticamente al fallback.", shadow);
  }

  function renderSongTransition() {
    const animation = select("Animación de entrada y salida", "animations.song", [["fade", "Fundido"], ["slide_left", "Deslizar a la izquierda"], ["slide_right", "Deslizar a la derecha"], ["slide_up", "Deslizar hacia arriba"], ["slide_down", "Deslizar hacia abajo"], ["scale", "Zoom suave"], ["blur", "Desenfoque"], ["flip", "Giro 3D"], ["none", "Sin animación"]], true);
    const details = `<div class="field-grid">
      ${select("Curva de movimiento", "animations.song_easing", [["smooth", "Suave"], ["snappy", "Rápida"], ["linear", "Lineal"], ["bounce", "Rebote"]], true)}
      ${range("Duración del cambio", "animations.song_duration_ms", 0, 3000, 20, " ms", true)}
    </div><div class="toggle-list" style="margin-top:15px">${toggle("Animar la salida de la canción anterior", "animations.song_exit_enabled")}</div>`;
    const content = optionBranch(animation, "song-animation", "Elige una animación para configurar su movimiento y probarla.", details + `<button class="button secondary replay-button" type="button" data-replay="song">▶ Probar animación</button>`);
    host.innerHTML = section("Pase de canción", "La tarjeta anterior sale mientras la nueva entra, sin congelar las actualizaciones de Spotify.", content)
      + section("Consejo", "Entre 350 y 650 ms suele verse fluido en TikTok LIVE Studio.", `<p style="margin:0;color:var(--muted);font-size:11px;line-height:1.6">La vista previa en vivo reproduce el efecto cada vez que Spotify cambia de canción.</p>`);
  }

  function renderTranslation() {
    const controls = `<div class="toggle-list">
      ${toggle("Mostrar traducción actual", "translation.show_current")}
      ${toggle("Traducir también la siguiente línea", "translation.show_next")}
    </div>`;
    const path = "translated_lyric";
    const typography = `<div class="field-grid">
      ${fontSelect(`${path}.font_family`)}
      ${color("Color", `${path}.color`, true)}
      ${range("Tamaño", `${path}.size`, 8, 48)}
      ${range("Espaciado", `${path}.letter_spacing`, -3, 16, .1)}
      ${range("Opacidad", `${path}.opacity`, 0, 1, .05, "")}
      ${select("Alineación", `${path}.align`, [["left", "Izquierda"], ["center", "Centro"], ["right", "Derecha"]], true)}
    </div><div class="toggle-list" style="margin-top:15px">${toggle("Negrita", `${path}.bold`)}${toggle("Cursiva", `${path}.italic`)}</div>${dependentGroup("translation-weight", "Desactiva Negrita para elegir un peso personalizado.", `<div class="field-grid">${select("Peso", `${path}.weight`, [[100, "100 · Fino"], [200, "200"], [300, "300"], [400, "400 · Normal"], [500, "500"], [600, "600"], [700, "700 · Negrita"], [800, "800"], [900, "900 · Negro"]], true)}</div>`)}`;
    const shadow = optionBranch(
      toggle("Sombra", `${path}.shadow_enabled`),
      "translation-shadow",
      "Activa la sombra para configurar su apariencia.",
      `<div class="field-grid">${color("Color de sombra", `${path}.shadow_color`)}${range("Desenfoque", `${path}.shadow_blur`, 0, 40)}</div>`,
    );
    const translationControls = optionBranch(
      toggle("Traducir letras al español", "translation.enabled"),
      "translation-enabled",
      "Activa la traducción para elegir qué líneas mostrar.",
      controls,
    );
    const appearance = dependentGroup("translation-visible", "Activa al menos una línea traducida para editar su estilo.", typography + shadow);
    host.innerHTML = section("Traducción automática", "Se resuelve en segundo plano y se guarda en caché. Un fallo externo nunca oculta ni detiene la letra original.", translationControls)
      + section("Texto traducido", "Aparece en pequeño debajo de la línea original.", appearance);
  }

  function renderEffects() {
    const animation = select("Cambio de letra", "animations.lyric", [["fade", "Fade"], ["slide_up", "Slide up"], ["slide_down", "Slide down"], ["blur", "Blur + fade"], ["none", "Sin animación"]], true);
    const details = `<div class="field-grid">
      ${range("Duración de letra", "animations.lyric_duration_ms", 0, 2000, 20, " ms", true)}
    </div><button class="button secondary replay-button" type="button" data-replay="lyric">▶ Probar animación</button>`;
    const content = dependentGroup(
      "lyrics-available",
      "Muestra una letra o traducción para configurar esta animación.",
      optionBranch(animation, "lyric-animation", "Elige una animación para configurar su duración y probarla.", details),
    );
    host.innerHTML = section("Cambio de línea", "Controla solamente el movimiento de las letras sincronizadas.", content);
  }

  function render() {
    if (!config) return;
    ({ general: renderGeneral, text: renderText, artwork: renderArtwork, song_transition: renderSongTransition, translation: renderTranslation, effects: renderEffects })[activeTab]();
    applyDependencyState();
  }

  function previewNow() {
    frame.contentWindow?.postMessage({ type: "preview-config", config }, location.origin);
  }

  function replayPreview(scope) {
    frame.contentWindow?.postMessage({ type: "preview-replay", scope }, location.origin);
  }

  function markSaving(text = "Guardando…") {
    saveStatus.className = "save-status";
    saveStatus.innerHTML = `<span></span> ${text}`;
  }

  function scheduleSave() {
    dirty = true;
    markSaving();
    previewNow();
    clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      const snapshot = JSON.parse(JSON.stringify(config));
      saveChain = saveChain.catch(() => {}).then(async () => {
        const response = await fetch("/api/config", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(snapshot),
        });
        if (!response.ok) throw new Error(await response.text());
        config = await response.json();
        dirty = false;
        saveStatus.className = "save-status saved";
        saveStatus.innerHTML = "<span></span> Guardado";
      }).catch((error) => {
        console.error(error);
        saveStatus.className = "save-status error";
        saveStatus.innerHTML = "<span></span> No se pudo guardar";
      });
    }, 160);
  }

  function syncPathInputs(path, value, source) {
    host.querySelectorAll(`[data-path="${CSS.escape(path)}"]`).forEach((input) => {
      if (input === source) return;
      if (input.type === "color") input.value = toHex(value);
      else if (input.type === "checkbox") input.checked = Boolean(value);
      else input.value = value;
    });
    const output = host.querySelector(`[data-output="${CSS.escape(path)}"]`);
    if (output) {
      const suffix = path.includes("duration_ms") ? " ms" : ["opacity", "letter_spacing", "outline_width"].some((item) => path.endsWith(item)) ? "" : "px";
      output.textContent = `${value}${suffix}`;
    }
  }

  host.addEventListener("input", (event) => {
    const input = event.target.closest("[data-path]");
    if (!input) return;
    let value;
    if (input.type === "checkbox") value = input.checked;
    else if (["range", "number"].includes(input.type)) value = Number(input.value);
    else if (input.tagName === "SELECT" && typeof getPath(input.dataset.path) === "number") value = Number(input.value);
    else value = input.value;

    if (input.hasAttribute("data-color-text") && !CSS.supports("color", value)) {
      input.classList.add("invalid");
      return;
    }
    input.classList.remove("invalid");
    setPath(input.dataset.path, value);
    syncPathInputs(input.dataset.path, value, input);
    if (input.hasAttribute("data-font-select")) input.style.fontFamily = `'${value}', Arial, sans-serif`;
    applyDependencyState();
    scheduleSave();
  });

  host.addEventListener("click", (event) => {
    const replay = event.target.closest("[data-replay]");
    if (replay) {
      replayPreview(replay.dataset.replay);
      return;
    }
    const preset = event.target.closest("[data-preset]");
    if (preset) {
      config.layout.preset = preset.dataset.preset;
      render();
      scheduleSave();
      return;
    }
    const textButton = event.target.closest("[data-text-target]");
    if (textButton) {
      textTarget = textButton.dataset.textTarget;
      render();
    }
  });

  document.querySelector("#tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-tab]");
    if (!button) return;
    activeTab = button.dataset.tab;
    document.querySelectorAll("#tabs button").forEach((tab) => tab.classList.toggle("active", tab === button));
    render();
  });

  document.querySelector("#preview-source").addEventListener("click", (event) => {
    const button = event.target.closest("[data-preview-source]");
    if (!button) return;
    previewSource = button.dataset.previewSource;
    document.querySelectorAll("#preview-source button").forEach((item) => item.classList.toggle("active", item === button));
    frame.src = `/overlay?preview=1&source=${encodeURIComponent(previewSource)}&v=20260902-swap2`;
  });

  frame.addEventListener("load", previewNow);

  document.querySelector("#reset-button").addEventListener("click", async () => {
    if (!window.confirm("¿Restablecer todos los ajustes visuales?")) return;
    markSaving("Restableciendo…");
    const response = await fetch("/api/config/reset", { method: "POST" });
    if (!response.ok) {
      saveStatus.className = "save-status error";
      saveStatus.innerHTML = "<span></span> No se pudo restablecer";
      return;
    }
    config = await response.json();
    render();
    previewNow();
    saveStatus.className = "save-status saved";
    saveStatus.innerHTML = "<span></span> Restablecido";
  });

  function updateRuntime(state) {
    const title = document.querySelector("#runtime-title");
    const detail = document.querySelector("#runtime-detail");
    const dot = document.querySelector("#runtime-dot");
    const messages = {
      starting: ["Iniciando monitor…", "Esperando la sesión multimedia de Windows.", ""],
      spotify_unavailable: ["Spotify no detectado", "Abre Spotify Desktop y reproduce una canción.", "hidden"],
      loading_lyrics: ["Buscando letra sincronizada…", "Los metadatos ya están visibles mientras se comprueba la letra.", ""],
      no_synced_lyrics: ["Canción sin timestamps válidos", "Se muestran portada y metadatos; la zona de letra queda vacía.", "hidden"],
      not_playing: ["Spotify está pausado o detenido", "La sincronización queda congelada en la posición real.", "hidden"],
      ready: ["Overlay al aire", `${state.track?.title || "Canción"} · ${state.lyrics_provider || "letra sincronizada"}`, "ready"],
      internal_error: ["Error temporal", "El monitor se recuperará automáticamente.", "error"],
    };
    const message = messages[state.status] || ["Monitor activo", state.status, ""];
    title.textContent = message[0];
    detail.textContent = message[1];
    dot.className = `runtime-dot ${message[2]}`;
  }

  function connectStatus() {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${location.host}/ws`);
    socket.addEventListener("message", (event) => {
      if (event.data === "pong") return;
      try {
        const message = JSON.parse(event.data);
        if (message.type === "state") updateRuntime(message);
        if (message.type === "config" && !dirty) {
          config = message.config;
          render();
          previewNow();
        }
      } catch (_) { /* ignore malformed frames */ }
    });
    socket.addEventListener("close", () => window.setTimeout(connectStatus, 1500));
  }

  fetch("/api/config", { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error("No se pudo cargar la configuración");
      return response.json();
    })
    .then((loaded) => {
      config = loaded;
      render();
      saveStatus.className = "save-status saved";
      saveStatus.innerHTML = "<span></span> Guardado";
      connectStatus();
    })
    .catch((error) => {
      host.innerHTML = `<div class="loading-card">${escapeHtml(error.message)}</div>`;
      saveStatus.className = "save-status error";
      saveStatus.innerHTML = "<span></span> Sin conexión";
    });
})();
