const stage = document.querySelector("#stage");
const panel = document.querySelector("#panel");
const statusEl = document.querySelector("#status");
const pinnedEl = document.querySelector("#pinned");
const messagesEl = document.querySelector("#messages");

const state = {
  config: null,
  status: null,
  messages: [],
  pinned: new Map(),
  loadedFonts: new Set(),
  socket: null,
  reconnectTimer: null,
  heartbeatTimer: null,
};

function hexToRgba(value, alpha) {
  let hex = String(value || "#0b0d12").replace("#", "").trim();
  if (hex.length === 3) {
    hex = hex
      .split("")
      .map((char) => char + char)
      .join("");
  }
  if (!/^[0-9a-f]{6}$/i.test(hex)) {
    hex = "0b0d12";
  }
  const number = Number.parseInt(hex, 16);
  const red = (number >> 16) & 255;
  const green = (number >> 8) & 255;
  const blue = number & 255;
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function proxied(url) {
  if (!url) return "";
  if (url.startsWith("/")) return url;
  return `/media?url=${encodeURIComponent(url)}`;
}

function fontValue(font) {
  const family = String(font?.family || "Microsoft YaHei UI").replaceAll('"', "");
  return `"${family}", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif`;
}

async function applyFont(font) {
  if (font?.url && !state.loadedFonts.has(font.url)) {
    try {
      const face = new FontFace(font.family, `url("${font.url}")`);
      await face.load();
      document.fonts.add(face);
      state.loadedFonts.add(font.url);
    } catch (error) {
      console.warn("字体加载失败", error);
    }
  }
  document.documentElement.style.setProperty("--font-family", fontValue(font));
}

function applyConfig(config) {
  if (!config) return;
  state.config = config;
  const theme = config.theme;
  const root = document.documentElement.style;
  root.setProperty("--font-size", `${theme.font.size}px`);
  root.setProperty("--panel-bg", hexToRgba(theme.panel_background, theme.panel_opacity));
  root.setProperty("--panel-radius", `${theme.panel_radius}px`);
  root.setProperty("--panel-border", hexToRgba(theme.panel_border, theme.panel_border_opacity));
  root.setProperty("--panel-padding", `${theme.panel_padding}px`);
  root.setProperty("--row-gap", `${theme.row_gap}px`);
  root.setProperty("--text-color", theme.text_color);
  root.setProperty("--muted-color", theme.muted_color);
  root.setProperty("--accent-color", theme.accent_color);
  void applyFont(theme.font);
  updateStatus();
  updatePanelVisibility();
}

function updateStatus(status = state.status) {
  state.status = status;
  if (!status) return;
  const show = state.config?.theme.show_status || status.state !== "connected";
  statusEl.hidden = !show;
  statusEl.dataset.state = status.state;
  const room = status.real_room_id ? ` · ${status.real_room_id}` : "";
  const rate = status.message_rate > 0 ? ` · ${status.message_rate.toFixed(1)}/秒` : "";
  statusEl.textContent = `${status.message}${room}${rate}`;
  updatePanelVisibility();
}

function updatePanelVisibility() {
  const statusVisible = statusEl && !statusEl.hidden;
  panel.hidden = state.messages.length === 0 && state.pinned.size === 0 && !statusVisible;
}

function makeEmote(fragment) {
  const wrapper = document.createElement("span");
  wrapper.className = "emote-wrap";
  const fallback = document.createElement("span");
  fallback.className = "emote-fallback";
  fallback.textContent = fragment.text || "";
  if (!fragment.url) {
    fallback.style.display = "inline";
    wrapper.append(fallback);
    return wrapper;
  }
  const image = document.createElement("img");
  image.className = "emote";
  image.alt = fragment.text || "表情";
  image.src = proxied(fragment.url);
  image.addEventListener("error", () => wrapper.classList.add("failed"));
  wrapper.append(image, fallback);
  return wrapper;
}

function makeParts(message) {
  const parts = document.createElement("span");
  parts.className = "parts";
  for (const fragment of message.parts || []) {
    if (fragment.type === "emote") {
      parts.append(makeEmote(fragment));
      continue;
    }
    const span = document.createElement("span");
    span.className = fragment.verb ? "part-text verb" : "part-text";
    span.textContent = fragment.text || "";
    parts.append(span);
  }
  if (message.count > 1) {
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = ` ×${message.count}`;
    parts.append(count);
  }
  return parts;
}

function makeAvatar(url) {
  if (!url) return null;
  const avatar = document.createElement("img");
  avatar.className = "avatar";
  avatar.alt = "";
  avatar.src = proxied(url);
  avatar.addEventListener("error", () => avatar.remove());
  return avatar;
}

function createMessageElement(message) {
  const row = document.createElement("article");
  row.className = `message ${message.kind}`;
  row.dataset.id = message.id;
  if (message.user_color) {
    row.style.setProperty("--user-color", message.user_color);
  }

  const avatar = makeAvatar(message.avatar_url);
  if (avatar) row.append(avatar);
  else row.classList.add("no-avatar");

  const body = document.createElement("div");
  body.className = "message-body";

  if (message.kind === "entry" || message.kind === "like") {
    const inline = document.createElement("div");
    inline.className = "ambient-line";
    const name = document.createElement("span");
    name.className = "username";
    name.textContent = message.user || "";
    inline.append(name, document.createTextNode(" "), makeParts(message));
    body.append(inline);
  } else {
    const head = document.createElement("div");
    head.className = "message-head";
    const name = document.createElement("span");
    name.className = "username";
    name.textContent = message.user || "";
    head.append(name);
    if (message.amount) {
      const amount = document.createElement("span");
      amount.className = "amount";
      amount.textContent = message.amount;
      head.append(amount);
    }
    body.append(head, makeParts(message));
  }

  row.append(body);
  return row;
}

function trimMessages() {
  const limit = state.config?.theme.max_messages || 80;
  while (state.messages.length > limit) {
    const old = state.messages.shift();
    messagesEl.querySelector(`[data-id="${CSS.escape(old.id)}"]`)?.remove();
  }
}

function appendMessage(message, animate = true) {
  if (!message) return;
  if (message.kind === "paid") {
    appendPinned(message);
    return;
  }
  const element = createMessageElement(message);
  if (!animate) element.style.animation = "none";
  state.messages.push(message);
  messagesEl.append(element);
  trimMessages();
  updatePanelVisibility();
}

function appendPinned(message) {
  const existing = state.pinned.get(message.id);
  if (existing) clearTimeout(existing.timer);
  const element = createMessageElement(message);
  pinnedEl.prepend(element);
  const timer = window.setTimeout(
    () => {
      element.remove();
      state.pinned.delete(message.id);
      updatePanelVisibility();
    },
    Math.max(2_000, message.dwell_ms || 60_000),
  );
  state.pinned.set(message.id, { element, timer });
  while (state.pinned.size > 5) {
    const oldestId = state.pinned.keys().next().value;
    const oldest = state.pinned.get(oldestId);
    clearTimeout(oldest.timer);
    oldest.element.remove();
    state.pinned.delete(oldestId);
  }
  updatePanelVisibility();
}

function clearMessages() {
  for (const item of state.pinned.values()) clearTimeout(item.timer);
  state.pinned.clear();
  state.messages.length = 0;
  pinnedEl.replaceChildren();
  messagesEl.replaceChildren();
  updatePanelVisibility();
}

function showHistory(history) {
  clearMessages();
  for (const message of history || []) appendMessage(message, false);
  if (history?.length) {
    const separator = document.createElement("div");
    separator.className = "history-separator";
    messagesEl.append(separator);
  }
  updatePanelVisibility();
}

function handleEnvelope(envelope) {
  if (envelope.type === "snapshot") {
    applyConfig(envelope.payload.config);
    showHistory(envelope.payload.history);
    updateStatus(envelope.payload.status);
    return;
  }
  if (envelope.type === "config") {
    applyConfig(envelope.payload);
    return;
  }
  if (envelope.type === "status") {
    updateStatus(envelope.payload);
    return;
  }
  if (envelope.type === "history") {
    showHistory(envelope.payload);
    return;
  }
  if (envelope.type === "clear") {
    showHistory([]);
    return;
  }
  if (envelope.type === "event") {
    appendMessage(envelope.payload);
  }
}

function connect() {
  clearTimeout(state.reconnectTimer);
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws`);
  state.socket = socket;
  socket.addEventListener("open", () => {
    clearInterval(state.heartbeatTimer);
    state.heartbeatTimer = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 20_000);
  });
  socket.addEventListener("message", (event) => {
    try {
      const envelope = JSON.parse(event.data);
      if (envelope.type !== "pong") handleEnvelope(envelope);
    } catch (error) {
      console.warn("无法解析服务端消息", error);
    }
  });
  socket.addEventListener("close", () => {
    clearInterval(state.heartbeatTimer);
    state.reconnectTimer = window.setTimeout(connect, 1_500);
  });
  socket.addEventListener("error", () => socket.close());
}

window.addEventListener("message", (event) => {
  if (event.origin !== location.origin) return;
  if (event.data?.type === "preview-config") {
    applyConfig(event.data.config);
  }
});

connect();
