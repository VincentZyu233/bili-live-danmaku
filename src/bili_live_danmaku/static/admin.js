const byId = (id) => document.getElementById(id);

const elements = {
  connectionBadge: byId("connectionBadge"),
  notice: byId("notice"),
  cookieState: byId("cookieState"),
  room: byId("room"),
  cookieFile: byId("cookieFile"),
  cookieText: byId("cookieText"),
  cookieFileInput: byId("cookieFileInput"),
  historyLines: byId("historyLines"),
  entryMerge: byId("entryMerge"),
  giftMerge: byId("giftMerge"),
  autoConnect: byId("autoConnect"),
  width: byId("width"),
  height: byId("height"),
  panelRadius: byId("panelRadius"),
  panelPadding: byId("panelPadding"),
  rowGap: byId("rowGap"),
  maxMessages: byId("maxMessages"),
  panelBackground: byId("panelBackground"),
  panelOpacity: byId("panelOpacity"),
  panelOpacityValue: byId("panelOpacityValue"),
  panelBorder: byId("panelBorder"),
  panelBorderOpacity: byId("panelBorderOpacity"),
  panelBorderOpacityValue: byId("panelBorderOpacityValue"),
  showStatus: byId("showStatus"),
  fontFamily: byId("fontFamily"),
  fontSize: byId("fontSize"),
  fontFile: byId("fontFile"),
  textColor: byId("textColor"),
  mutedColor: byId("mutedColor"),
  accentColor: byId("accentColor"),
  previewFrame: byId("previewFrame"),
  previewViewport: byId("previewViewport"),
  overlayUrl: byId("overlayUrl"),
};

let currentConfig = null;
let fontsLoaded = false;

function showNotice(message, isError = false) {
  elements.notice.textContent = message;
  elements.notice.classList.toggle("error", isError);
  elements.notice.classList.add("visible");
  window.clearTimeout(showNotice.timer);
  showNotice.timer = window.setTimeout(() => elements.notice.classList.remove("visible"), 5000);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // The status text is enough when the body is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

function numberValue(element, fallback) {
  const value = Number(element.value);
  return Number.isFinite(value) ? value : fallback;
}

function collectConfig() {
  const selectedFont = elements.fontFamily.selectedOptions[0];
  return {
    room: elements.room.value.trim(),
    cookie_file: elements.cookieFile.value.trim(),
    history_lines: numberValue(elements.historyLines, 60),
    entry_merge_seconds: numberValue(elements.entryMerge, 5),
    gift_merge_seconds: numberValue(elements.giftMerge, 5),
    auto_connect: elements.autoConnect.checked,
    theme: {
      width: numberValue(elements.width, 480),
      height: numberValue(elements.height, 1080),
      font: {
        family: elements.fontFamily.value || "LXGW WenKai Mono",
        size: numberValue(elements.fontSize, 28),
        url: selectedFont?.dataset.url || null,
      },
      panel_background: elements.panelBackground.value,
      panel_opacity: numberValue(elements.panelOpacity, 0.58),
      panel_radius: numberValue(elements.panelRadius, 28),
      panel_border: elements.panelBorder.value,
      panel_border_opacity: numberValue(elements.panelBorderOpacity, 0.12),
      panel_padding: numberValue(elements.panelPadding, 18),
      row_gap: numberValue(elements.rowGap, 8),
      text_color: elements.textColor.value,
      muted_color: elements.mutedColor.value,
      accent_color: elements.accentColor.value,
      show_status: elements.showStatus.checked,
      max_messages: numberValue(elements.maxMessages, 80),
    },
  };
}

function fillConfig(config) {
  currentConfig = config;
  elements.room.value = config.room || "";
  elements.cookieFile.value = config.cookie_file || "";
  elements.historyLines.value = config.history_lines;
  elements.entryMerge.value = config.entry_merge_seconds;
  elements.giftMerge.value = config.gift_merge_seconds;
  elements.autoConnect.checked = config.auto_connect;
  elements.width.value = config.theme.width;
  elements.height.value = config.theme.height;
  elements.panelRadius.value = config.theme.panel_radius;
  elements.panelPadding.value = config.theme.panel_padding;
  elements.rowGap.value = config.theme.row_gap;
  elements.maxMessages.value = config.theme.max_messages;
  elements.panelBackground.value = config.theme.panel_background;
  elements.panelOpacity.value = config.theme.panel_opacity;
  elements.panelOpacityValue.textContent = Number(config.theme.panel_opacity).toFixed(2);
  elements.panelBorder.value = config.theme.panel_border;
  elements.panelBorderOpacity.value = config.theme.panel_border_opacity;
  elements.panelBorderOpacityValue.textContent = Number(config.theme.panel_border_opacity).toFixed(2);
  elements.showStatus.checked = config.theme.show_status;
  elements.fontSize.value = config.theme.font.size;
  elements.textColor.value = config.theme.text_color;
  elements.mutedColor.value = config.theme.muted_color;
  elements.accentColor.value = config.theme.accent_color;
  selectFont(config.theme.font);
}

function addFontOption(family, url = "", label = family) {
  const option = document.createElement("option");
  option.value = family;
  option.textContent = label;
  option.dataset.url = url;
  elements.fontFamily.append(option);
  return option;
}

function selectFont(font) {
  let option = [...elements.fontFamily.options].find(
    (candidate) => candidate.value === font.family && (candidate.dataset.url || null) === (font.url || null),
  );
  if (!option) {
    option = addFontOption(font.family, font.url || "", `${font.family}（当前）`);
  }
  elements.fontFamily.value = option.value;
  elements.fontFamily.selectedOptions[0].dataset.url = font.url || "";
}

function loadFonts(data, desired) {
  elements.fontFamily.replaceChildren();
  const systems = new Set(data.system || []);
  for (const family of systems) addFontOption(family);
  for (const uploaded of data.uploaded || []) {
    addFontOption(uploaded.family, uploaded.url, `${uploaded.family}（已上传）`);
  }
  if (desired) selectFont(desired);
  fontsLoaded = true;
}

function updateRangeOutputs() {
  elements.panelOpacityValue.textContent = Number(elements.panelOpacity.value).toFixed(2);
  elements.panelBorderOpacityValue.textContent = Number(elements.panelBorderOpacity.value).toFixed(2);
}

function sendPreview() {
  const config = collectConfig();
  resizePreview(config.theme.width, config.theme.height);
  elements.previewFrame.contentWindow?.postMessage(
    { type: "preview-config", config },
    location.origin,
  );
}

function resizePreview(width, height) {
  const viewportWidth = elements.previewViewport.clientWidth - 36;
  const viewportHeight = Math.max(420, window.innerHeight - 300);
  const scale = Math.min(viewportWidth / width, viewportHeight / height, 0.78);
  elements.previewFrame.style.width = `${width}px`;
  elements.previewFrame.style.height = `${height}px`;
  elements.previewFrame.style.transform = `scale(${scale})`;
  const stage = elements.previewFrame.parentElement;
  stage.style.width = `${Math.max(1, width * scale)}px`;
  stage.style.height = `${Math.max(1, height * scale)}px`;
}

async function refreshStatus() {
  try {
    const data = await fetchJson("/api/status");
    const status = data.status;
    elements.connectionBadge.dataset.state = status.state;
    elements.connectionBadge.textContent = status.message || status.state;
    elements.cookieState.textContent = data.cookie_present ? "Cookie：已配置" : "Cookie：匿名模式";
    elements.cookieState.style.color = data.cookie_present ? "#8ce7ae" : "";
  } catch (error) {
    elements.connectionBadge.dataset.state = "error";
    elements.connectionBadge.textContent = "服务不可用";
  }
}

async function saveConfig(showMessage = true) {
  const config = collectConfig();
  const saved = await fetchJson("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  fillConfig(saved);
  sendPreview();
  if (showMessage) showNotice("配置已保存。");
  return saved;
}

async function importCookie() {
  await saveConfig(false);
  let cookie = elements.cookieText.value.trim();
  if (!cookie && elements.cookieFileInput.files?.[0]) {
    cookie = (await elements.cookieFileInput.files[0].text()).trim();
  }
  if (!cookie) {
    showNotice("请先粘贴 Cookie 或选择 Cookie 文件。", true);
    return;
  }
  await fetchJson("/api/cookie", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cookie }),
  });
  elements.cookieText.value = "";
  showNotice("Cookie 已导入，连接正在刷新。");
  await refreshStatus();
}

async function uploadFont() {
  const file = elements.fontFile.files?.[0];
  if (!file) {
    showNotice("请先选择字体文件。", true);
    return;
  }
  const form = new FormData();
  form.append("file", file);
  const uploaded = await fetchJson("/api/fonts", { method: "POST", body: form });
  const fonts = await fetchJson("/api/fonts");
  loadFonts(fonts, { family: uploaded.family, url: uploaded.url });
  await saveConfig(false);
  showNotice("字体已上传并应用。");
}

async function boot() {
  elements.overlayUrl.textContent = `${location.origin}/overlay`;
  try {
    const [config, fonts] = await Promise.all([fetchJson("/api/config"), fetchJson("/api/fonts")]);
    fillConfig(config);
    loadFonts(fonts, config.theme.font);
    sendPreview();
  } catch (error) {
    showNotice(`配置加载失败：${error.message}`, true);
  }
  await refreshStatus();
}

document.querySelectorAll(".preview-field").forEach((input) => {
  input.addEventListener("input", () => {
    if (input === elements.panelOpacity || input === elements.panelBorderOpacity) updateRangeOutputs();
    if (fontsLoaded) sendPreview();
  });
  input.addEventListener("change", () => {
    if (fontsLoaded) sendPreview();
  });
});

byId("saveBtn").addEventListener("click", () => saveConfig().catch((error) => showNotice(error.message, true)));
byId("openOverlayBtn").addEventListener("click", () => window.open("/overlay", "_blank", "noopener"));
byId("copyOverlayBtn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(`${location.origin}/overlay`);
    showNotice("OBS 浏览器源地址已复制。");
  } catch {
    showNotice("复制失败，请手动选择下方地址。", true);
  }
});
byId("importCookieBtn").addEventListener("click", () => importCookie().catch((error) => showNotice(error.message, true)));
byId("deleteCookieBtn").addEventListener("click", async () => {
  if (!window.confirm("确定删除本地 Cookie 文件？")) return;
  try {
    await fetchJson("/api/cookie", { method: "DELETE" });
    showNotice("Cookie 已删除，当前连接切换为匿名模式。");
    await refreshStatus();
  } catch (error) {
    showNotice(error.message, true);
  }
});
byId("restartBtn").addEventListener("click", async () => {
  try {
    await saveConfig(false);
    await fetchJson("/api/restart", { method: "POST" });
    showNotice("正在重新连接直播间。");
  } catch (error) {
    showNotice(error.message, true);
  }
});
byId("demoBtn").addEventListener("click", async () => {
  try {
    await fetchJson("/api/demo?count=10", { method: "POST" });
    showNotice("已发送一组演示消息。");
  } catch (error) {
    showNotice(error.message, true);
  }
});
byId("previewDemoBtn").addEventListener("click", async () => {
  try {
    await fetchJson("/api/demo?count=10", { method: "POST" });
    showNotice("已发送带本地头像的测试消息。");
  } catch (error) {
    showNotice(error.message, true);
  }
});
byId("uploadFontBtn").addEventListener("click", () => uploadFont().catch((error) => showNotice(error.message, true)));
elements.fontFile.addEventListener("change", () => {
  if (elements.fontFile.files?.length) {
    uploadFont().catch((error) => showNotice(error.message, true));
  }
});
elements.cookieFileInput.addEventListener("change", async () => {
  const file = elements.cookieFileInput.files?.[0];
  if (!file) return;
  elements.cookieText.value = await file.text();
  showNotice(`已读取 ${file.name}，点击“导入 Cookie”写入。`);
});
elements.previewFrame.addEventListener("load", () => sendPreview());
window.addEventListener("resize", () => {
  const config = currentConfig || collectConfig();
  resizePreview(config.theme.width, config.theme.height);
});

void boot();
window.setInterval(refreshStatus, 2000);
