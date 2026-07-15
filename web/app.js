const app = document.getElementById("app");
const TAB_SESSION_MODE_KEY = "mnemosyne:tab-session-mode";
const TAB_SESSION_TOKEN_KEY = "mnemosyne:tab-session-token";

const text = {
  appName: "LING",
  appSubtitle: "Live companion",
  login: "登录",
  register: "注册",
  logout: "退出",
  username: "账号",
  password: "密码",
  nickname: "昵称",
  birthday: "生日",
  signature: "个性签名",
  save: "保存",
  send: "发送",
  waiting: "生成中",
  createPersona: "创建陪伴体",
  wizardTitle: "你希望 TA 以什么样的方式在你身边？",
  optionalDescription: "自由描述",
  directGenerate: "直接生成",
  messagePlaceholder: "说点什么",
  profile: "资料",
  chats: "陪伴体",
  adminConsole: "管理台",
  newChat: "新对话",
  backToChat: "返回聊天",
};

const starterPrompts = [
  "我希望 TA 记得我说过的小事，但不要像客服一样总结我。",
  "聊天可以轻松一点，能吐槽；遇到认真事情时要稳。",
  "TA 可以主动关心我，但不要一直追问，也不要说教。",
  "我不确定具体人设，只希望 TA 能慢慢适应我的情绪节奏。",
];

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  if (!["http:", "https:"].includes(window.location.protocol)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("[PWA] service worker registration failed", err);
    });
  });
}

let state = {
  user: null,
  profile: null,
  selfUse: null,
  options: null,
  expressionAssets: [],
  personas: [],
  deletedPersonas: [],
  personaGrowth: {},
  loadingGrowthPersonaId: null,
  conversations: [],
  archivedConversations: [],
  groupConversations: [],
  archivedGroupConversations: [],
  activePersona: null,
  activeConversationId: null,
  activeGroupConversationId: null,
  activeGroupConversation: null,
  messages: [],
  groupMessages: [],
  view: "chat",
  editingPersona: false,
  profileOpen: false,
  personaPanelOpen: false,
  threadPanelOpen: false,
  deletedPanelOpen: false,
  privacyOpen: false,
  integrationOpen: false,
  groupCreateOpen: false,
  groupSettingsOpen: false,
  editingConversationId: null,
  showArchived: false,
  showArchivedGroups: false,
  conversationSearch: "",
  focusComposer: false,
  composerFocused: false,
  composerDraft: "",
  sending: false,
  voiceConfig: null,
  voicePlaying: null,
  voicePlaybackPhase: null,
  voiceError: null,
  voiceErrorMessageId: null,
  voicePlan: null,
  voicePlanMessageId: null,
  live2dStatus: null,
  presenceStatus: null,
  presenceSaving: false,
  presenceControlError: null,
  consents: [],
  cameraStatus: null,
  screenStatus: null,
  proactiveStatus: null,
  videoCompanionStatus: null,
  companionStatus: null,
  llmStatus: null,
  chatGateSaving: false,
  chatGateError: null,
  llmProbeSaving: false,
  integrationFlagSaving: "",
  integrationFlagError: null,
  integrationConfigSaving: "",
  integrationConfigFeedback: {},
  easyVtuberOpening: false,
  easyVtuberCaptureRequesting: false,
  easyVtuberCaptureActive: false,
  easyVtuberFeedback: "",
  privacyPolicy: null,
  cameraPreviewActive: false,
};

let live2dActionQueue = Promise.resolve();
let live2dExpressionResetTimer = null;
let activeVoicePlayback = null;
let voicePlaybackSequence = 0;
let activeChatStream = null;
let chatStreamSequence = 0;
let companionStatusPollTimer = null;
let companionStatusPollBusy = false;
let companionLifecycleBound = false;
let easyVtuberCaptureStream = null;

function tabSessionMode() {
  try {
    return sessionStorage.getItem(TAB_SESSION_MODE_KEY) === "1";
  } catch {
    return false;
  }
}

function tabSessionToken() {
  try {
    return sessionStorage.getItem(TAB_SESSION_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function prepareAuthMode(isolated) {
  try {
    if (isolated) {
      sessionStorage.setItem(TAB_SESSION_MODE_KEY, "1");
      sessionStorage.removeItem(TAB_SESSION_TOKEN_KEY);
    } else {
      sessionStorage.removeItem(TAB_SESSION_MODE_KEY);
      sessionStorage.removeItem(TAB_SESSION_TOKEN_KEY);
    }
  } catch {
    // Session storage may be unavailable in restricted browser modes.
  }
}

function acceptAuthSession(data, isolated) {
  prepareAuthMode(isolated);
  if (!isolated) return;
  if (!data.tab_session_token) {
    throw new Error("服务端尚未加载独立登录功能，请重启程序后再试。");
  }
  try {
    sessionStorage.setItem(TAB_SESSION_TOKEN_KEY, data.tab_session_token);
  } catch {
    throw new Error("浏览器无法保存本页登录状态，请取消独立登录后重试。");
  }
}

function apiErrorMessage(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => apiErrorMessage(item, "")).filter(Boolean).join("; ") || fallback;
  }
  if (typeof detail === "object") {
    if (typeof detail.error === "string") {
      var metadata = detail.metadata && typeof detail.metadata === "object" ? detail.metadata : null;
      var metaError = metadata && typeof metadata.error === "string" ? metadata.error : "";
      return metaError ? detail.error + ": " + metaError : detail.error;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }
  return String(detail);
}

async function api(path, options = {}) {
  const isolated = tabSessionMode();
  const token = tabSessionToken();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (isolated && token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    ...options,
    credentials: isolated ? "omit" : "same-origin",
    headers,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(apiErrorMessage(data.detail, `HTTP ${res.status}`));
  }
  return data;
}

async function uploadImageFile(path, file) {
  const form = new FormData();
  form.append("file", file);
  const isolated = tabSessionMode();
  const token = tabSessionToken();
  const headers = {};
  if (isolated && token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    method: "POST",
    credentials: isolated ? "omit" : "same-origin",
    headers,
    body: form,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(apiErrorMessage(data.detail, `HTTP ${res.status}`));
  }
  return data.url;
}

async function uploadAvatarFile(file) {
  return uploadImageFile("/api/uploads/avatar", file);
}

async function uploadEmbodimentImageFile(file, kind) {
  return uploadImageFile(`/api/uploads/embodiment-image?kind=${encodeURIComponent(kind)}`, file);
}

function h(tag, attrs = {}, children = []) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (typeof value === "boolean") {
      if (value) el.setAttribute(key, "");
    }
    else if (value !== undefined && value !== null) el.setAttribute(key, value);
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child === null || child === undefined) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

async function bootstrap() {
  try {
    const local = await api("/api/auth/local", { method: "POST" });
    await enterAuthenticatedSession(local, false);
    return;
  } catch (localErr) {
    if (!localSelfUseUnavailable(localErr)) {
      renderLocalStartupError(localErr);
      return;
    }
  }

  try {
    await bootstrapAuthenticated();
  } catch {
    renderAuth("login");
  }
}

function localSelfUseUnavailable(err) {
  return String(err?.message || "").includes("local self-use mode is not enabled");
}

async function bootstrapAuthenticated() {
  const me = await api("/api/me");
  await enterAuthenticatedSession(me, false);
}

async function enterAuthenticatedSession(data, isolated) {
  acceptAuthSession(data, isolated);
  state.user = data.user;
  state.profile = data.profile;
  state.selfUse = data.self_use || { enabled: false };
  await loadMainData({ openLatest: true });
  renderShell();
  scrollChat();
  startCompanionStatusPolling();
}

function renderAuth(mode) {
  const isRegister = mode === "register";
  const form = h("form", { class: "auth-card" });
  const isolatedLogin = h("input", { type: "checkbox" });
  isolatedLogin.checked = tabSessionMode();
  form.append(
    h("p", { class: "eyebrow", text: text.appSubtitle }),
    h("h1", { text: isRegister ? text.register : text.login }),
    h("label", {}, [text.username, h("input", { name: "username", required: "required", autocomplete: "username" })]),
    h("label", {}, [
      text.password,
      h("input", {
        name: "password",
        type: "password",
        required: "required",
        minlength: "8",
        autocomplete: isRegister ? "new-password" : "current-password",
      }),
    ])
  );
  if (isRegister) {
    form.append(h("label", {}, [text.nickname, h("input", { name: "nickname", autocomplete: "nickname" })]));
  }
  form.append(h("label", { class: "auth-session-option" }, [
    isolatedLogin,
    h("span", {}, [
      h("strong", { text: "此标签页独立登录" }),
      h("small", { text: "同一浏览器同时测试多个账号时使用" }),
    ]),
  ]));
  form.append(h("p", {
    class: "auth-guest-note",
    text: "游客体验会在本机保存临时人格、聊天、记忆和上传文件，默认 3 天后自动清除；想保留数据请在资料里转为正式账号。",
  }));
  form.append(
    h("button", { type: "submit", text: isRegister ? text.register : text.login }),
    h("button", {
      type: "button",
      class: "ghost",
      text: isRegister ? text.login : text.register,
      onclick: () => renderAuth(isRegister ? "login" : "register"),
    }),
    h("button", {
      type: "button",
      class: "ghost",
      text: "游客体验（3天）",
      onclick: async () => {
        error.textContent = "";
        try {
          const isolated = isolatedLogin.checked;
          prepareAuthMode(isolated);
          const data = await api(`/api/auth/guest?tab_session=${isolated ? "true" : "false"}`, { method: "POST" });
          acceptAuthSession(data, isolated);
          state.user = data.user;
          state.profile = data.profile;
          await loadMainData({ openLatest: true });
          renderShell();
          scrollChat();
        } catch (err) {
          error.textContent = err.message;
        }
      },
    }),
    h("button", {
      type: "button",
      class: "ghost",
      text: "数据与隐私",
      onclick: () => openPrivacyModal(() => renderAuth(mode)),
    })
  );

  const error = h("p", { class: "error" });
  form.append(error);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.textContent = "";
    const body = Object.fromEntries(new FormData(form).entries());
    try {
      const isolated = isolatedLogin.checked;
      prepareAuthMode(isolated);
      body.tab_session = isolated;
      const data = await api(isRegister ? "/api/auth/register" : "/api/auth/login", {
        method: "POST",
        body: JSON.stringify(body),
      });
      acceptAuthSession(data, isolated);
      state.user = data.user;
      state.profile = data.profile;
      await loadMainData({ openLatest: true });
      renderShell();
      scrollChat();
    } catch (err) {
      error.textContent = err.message;
    }
  });

  app.className = "auth-screen";
  app.replaceChildren(form, ...(state.privacyOpen ? [renderPrivacyModal(() => renderAuth(mode))] : []));
}

function renderLocalStartupError(err) {
  const message = String(err?.message || "").trim() || "本地自用工作区启动失败";
  const card = h("section", { class: "auth-card local-startup-card" }, [
    h("p", { class: "eyebrow", text: "LING local workspace" }),
    h("h1", { text: "没有进入澪的工作区" }),
    h("p", {
      text: "LING 当前按本地自用模式启动；正常情况下会自动进入 embodied workspace，不会出现登录、注册或游客入口。",
    }),
    h("p", { class: "local-startup-detail", text: message }),
    h("div", { class: "local-startup-actions" }, [
      h("button", { type: "button", text: "重试", onclick: bootstrap }),
      h("button", {
        type: "button",
        class: "ghost",
        text: "数据与隐私",
        onclick: () => openPrivacyModal(() => renderLocalStartupError(err)),
      }),
    ]),
  ]);
  app.className = "auth-screen self-use-startup-screen";
  app.replaceChildren(card, ...(state.privacyOpen ? [renderPrivacyModal(() => renderLocalStartupError(err))] : []));
}

async function loadMainData({ openLatest = false } = {}) {
  const selfUse = selfUseMode();
  const [options, expressionAssets, personas, deletedPersonas, conversations, archivedConversations, groupConversations, archivedGroupConversations] = await Promise.all([
    selfUse ? Promise.resolve({ options: {} }) : api("/api/persona-options"),
    api("/api/expression-assets").catch(() => ({ assets: [] })),
    api("/api/personas"),
    selfUse ? Promise.resolve({ personas: [] }) : api("/api/personas/deleted"),
    api("/api/conversations?status=active"),
    api("/api/conversations?status=archived"),
    selfUse ? Promise.resolve({ group_conversations: [] }) : api("/api/group-conversations?status=active"),
    selfUse ? Promise.resolve({ group_conversations: [] }) : api("/api/group-conversations?status=archived"),
  ]);
  await loadVoiceConfig();
  await loadPresenceStatus();
  await loadAwarenessStatus();
  await loadLLMStatus();

  state.options = options.options;
  state.expressionAssets = expressionAssets.assets || [];
  state.personas = personas.personas;
  state.deletedPersonas = deletedPersonas.personas;
  state.conversations = conversations.conversations;
  state.archivedConversations = archivedConversations.conversations;
  state.groupConversations = groupConversations.group_conversations || [];
  state.archivedGroupConversations = archivedGroupConversations.group_conversations || [];
  if (state.activeGroupConversationId) {
    state.activeGroupConversation = [...state.groupConversations, ...state.archivedGroupConversations]
      .find((item) => Number(item.id) === Number(state.activeGroupConversationId)) || state.activeGroupConversation;
  }
  const lastActive = loadLastActive();

  if (state.view === "group" && state.activeGroupConversationId) {
    state.activePersona = null;
  } else if (state.activePersona) {
    const refreshed = state.personas.find((persona) => Number(persona.id) === Number(state.activePersona.id));
    state.activePersona = refreshed || state.personas[0] || null;
  } else if (openLatest && lastActive.personaId) {
    state.activePersona = state.personas.find((persona) => Number(persona.id) === Number(lastActive.personaId)) || null;
  } else if (openLatest && lastActive.conversationId) {
    const conversation = state.conversations.find((item) => Number(item.id) === Number(lastActive.conversationId));
    state.activePersona = state.personas.find((persona) => Number(persona.id) === Number(conversation?.persona_id)) || null;
  } else if (openLatest && state.conversations.length) {
    state.activePersona = state.personas.find((persona) => Number(persona.id) === Number(state.conversations[0].persona_id)) || null;
  } else {
    state.activePersona = state.personas[0] || null;
  }
  state.view = state.activePersona || state.activeGroupConversation ? state.view : "forge";
  if (openLatest && state.personas.length) {
    state.view = state.activePersona ? "chat" : "home";
  }
  if (openLatest && state.activePersona) {
    await openInitialConversation();
  }
  if (selfUseMode()) {
    state.view = state.activePersona ? "chat" : "home";
    state.activeGroupConversationId = null;
    state.activeGroupConversation = null;
  }
  await loadCompanionStatus();
}

async function loadConversationMessages(conversationId) {
  const data = await api(`/api/conversations/${conversationId}/messages`);
  state.messages = data.messages;
}

async function loadGroupMessages(groupConversationId) {
  const data = await api(`/api/group-conversations/${groupConversationId}/messages`);
  state.groupMessages = data.messages;
}

function returnToHome() {
  if (selfUseMode() && state.activePersona) {
    state.view = "chat";
    state.threadPanelOpen = false;
    state.personaPanelOpen = false;
    state.groupSettingsOpen = false;
    renderShell();
    return;
  }
  state.view = "home";
  state.activePersona = null;
  state.activeConversationId = null;
  state.activeGroupConversationId = null;
  state.activeGroupConversation = null;
  state.messages = [];
  state.groupMessages = [];
  state.threadPanelOpen = false;
  state.personaPanelOpen = false;
  state.groupSettingsOpen = false;
  renderShell();
  loadMainData().then(() => renderShell()).catch((err) => {
    state.error = err.message;
    renderShell();
  });
}

function isMobileShell() {
  return Boolean(window.matchMedia?.("(max-width: 1024px), (hover: none) and (pointer: coarse)").matches);
}

async function openConversationItem(item) {
  const persona = state.personas.find((entry) => Number(entry.id) === Number(item.persona_id));
  if (persona) state.activePersona = persona;
  state.activeConversationId = item.id;
  state.activeGroupConversationId = null;
  state.activeGroupConversation = null;
  state.groupMessages = [];
  state.view = "chat";
  state.editingPersona = false;
  state.personaPanelOpen = false;
  state.threadPanelOpen = false;
  await loadConversationMessages(item.id);
  await loadMainData();
  renderShell();
  scrollChat();
}

async function openGroupConversationItem(item) {
  if (selfUseMode()) {
    normalizeSelfUseUiState();
    renderShell();
    return;
  }
  state.activeGroupConversation = item;
  state.activeGroupConversationId = item.id;
  state.activePersona = null;
  state.activeConversationId = null;
  state.messages = [];
  state.view = "group";
  state.editingPersona = false;
  state.personaPanelOpen = false;
  state.threadPanelOpen = false;
  await loadGroupMessages(item.id);
  await loadMainData();
  renderShell();
  scrollChat();
}

async function openPersonaItem(persona) {
  state.activePersona = persona;
  state.activeGroupConversationId = null;
  state.activeGroupConversation = null;
  state.groupMessages = [];
  state.view = "chat";
  state.editingPersona = false;
  state.personaPanelOpen = false;
  state.threadPanelOpen = false;
  await openLatestConversationForPersona(persona.id);
  renderShell();
  scrollChat();
}

async function openPersonaPanel(options = {}) {
  const personaId = Number(state.activePersona?.id);
  if (!personaId) return;
  state.personaPanelOpen = true;
  state.editingPersona = !!options.edit;
  state.loadingGrowthPersonaId = personaId;
  await loadLive2dStatus();
  renderShell();
  try {
    const data = await api(`/api/personas/${personaId}/growth`);
    state.personaGrowth[personaId] = data.growth;
    if (data.growth?.latest_reviewed_change?.unseen) {
      try {
        await api(`/api/personas/${personaId}/growth/viewed`, { method: "POST" });
        clearGrowthNotice(personaId);
      } catch {
        // Keep the notice visible if acknowledgement cannot be persisted.
      }
    }
  } catch {
    // Growth feedback is supplementary; profile details remain usable if it fails.
  } finally {
    if (Number(state.loadingGrowthPersonaId) === personaId) {
      state.loadingGrowthPersonaId = null;
    }
    if (state.personaPanelOpen && Number(state.activePersona?.id) === personaId) renderShell();
  }
}

async function openPersonaGrowthNotice(event, persona = state.activePersona) {
  event?.preventDefault();
  event?.stopPropagation();
  if (persona) state.activePersona = persona;
  await openPersonaPanel();
}

async function openPersonaEditor() {
  await openPersonaPanel({ edit: true });
}

function clearGrowthNotice(personaId) {
  state.personas = state.personas.map((persona) => (
    Number(persona.id) === Number(personaId) ? { ...persona, growth_notice: null } : persona
  ));
  if (Number(state.activePersona?.id) === Number(personaId)) {
    state.activePersona = { ...state.activePersona, growth_notice: null };
  }
}

function clearGrowthAction(personaId) {
  state.personas = state.personas.map((persona) => (
    Number(persona.id) === Number(personaId) ? { ...persona, growth_action: null } : persona
  ));
  if (Number(state.activePersona?.id) === Number(personaId)) {
    state.activePersona = { ...state.activePersona, growth_action: null };
  }
}

async function openLatestConversationForPersona(personaId) {
  const latest = latestConversationForPersona(personaId);
  state.activeConversationId = latest?.id || null;
  if (latest) {
    await loadConversationMessages(latest.id);
  } else {
    state.messages = [];
  }
}

async function openInitialConversation() {
  const lastActive = loadLastActive();
  let conversation = null;
  if (lastActive.conversationId) {
    conversation = state.conversations.find((item) => Number(item.id) === Number(lastActive.conversationId)) || null;
  }
  if (!conversation && state.activePersona) {
    conversation = latestConversationForPersona(state.activePersona.id);
  }
  if (!conversation) {
    conversation = state.conversations[0] || null;
  }
  if (conversation) {
    const persona = state.personas.find((item) => Number(item.id) === Number(conversation.persona_id));
    if (persona) state.activePersona = persona;
    state.activeConversationId = conversation.id;
    await loadConversationMessages(conversation.id);
  } else {
    state.activeConversationId = null;
    state.messages = [];
  }
}

function latestConversationForPersona(personaId) {
  return state.conversations
    .filter((item) => Number(item.persona_id) === Number(personaId))
    .sort((left, right) => Number(right.updated_at || 0) - Number(left.updated_at || 0))[0] || null;
}

function lastActiveKey() {
  return `mnemosyne:last-active:${state.user?.id || "anonymous"}`;
}

function loadLastActive() {
  try {
    return JSON.parse(localStorage.getItem(lastActiveKey()) || "{}");
  } catch {
    return {};
  }
}

function saveLastActive() {
  if (!state.user) return;
  try {
    if (state.view === "group" && state.activeGroupConversationId) {
      localStorage.setItem(
        lastActiveKey(),
        JSON.stringify({
          mode: "group",
          groupConversationId: state.activeGroupConversationId,
        })
      );
      return;
    }
    if (!state.activePersona) return;
    localStorage.setItem(
      lastActiveKey(),
      JSON.stringify({
        mode: "chat",
        personaId: state.activePersona.id,
        conversationId: state.activeConversationId,
      })
    );
  } catch {
    // Local storage may be unavailable in restricted browser modes.
  }
}

function renderShell() {
  normalizeSelfUseUiState();
  saveLastActive();
  // Most UI actions update a small bit of state and then redraw the shell.  Keep
  // the reader where they were instead of replacing the chat scroller at 0.
  // New messages still explicitly call scrollChat() after rendering.
  const previousChatLog = document.getElementById("chat-log");
  const previousChatScrollTop = previousChatLog ? previousChatLog.scrollTop : null;
  const restoreSearchFocus = document.activeElement?.classList?.contains("conversation-search");
  app.className = `app-shell view-${state.view || "chat"} ${selfUseMode() ? "self-use-shell" : ""} ${state.activePersona || state.activeGroupConversation ? "has-persona" : "no-persona"}`;
  const children = [renderSidebar(), renderMain()];
  if (state.profileOpen) children.push(renderProfileModal());
  if (state.personaPanelOpen) children.push(renderPersonaModal());
  if (state.threadPanelOpen) children.push(renderThreadModal());
  if (state.deletedPanelOpen) children.push(renderDeletedPersonasModal());
  if (state.privacyOpen) children.push(renderPrivacyModal(renderShell));
  if (state.integrationOpen) children.push(renderSelfUseIntegrationModal());
  if (!selfUseMode() && state.groupCreateOpen) children.push(renderGroupCreateModal());
  app.replaceChildren(...children);
  if (previousChatScrollTop !== null) {
    const restoreChatScroll = () => {
      const chatLog = document.getElementById("chat-log");
      if (!chatLog) return;
      const maxScrollTop = Math.max(0, chatLog.scrollHeight - chatLog.clientHeight);
      chatLog.scrollTop = Math.min(previousChatScrollTop, maxScrollTop);
    };
    // Restore synchronously for click-driven redraws, then once more after
    // layout settles.  The second pass protects against font/image reflow.
    restoreChatScroll();
    requestAnimationFrame(restoreChatScroll);
  }
  if (restoreSearchFocus) {
    requestAnimationFrame(() => {
      const input = document.querySelector(".conversation-search");
      if (input) {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
    });
  }
}

function normalizeSelfUseUiState() {
  if (!selfUseMode()) return;
  if (state.view === "forge" || state.view === "group" || state.view === "home") {
    state.view = "chat";
  }
  state.activeGroupConversationId = null;
  state.activeGroupConversation = null;
  state.groupMessages = [];
  state.groupCreateOpen = false;
  state.groupSettingsOpen = false;
}

function renderSidebar() {
  if (selfUseMode()) return renderSelfUseRail();

  return h("aside", { class: "sidebar" }, [
    renderBrand(),
    h("section", { class: "sidebar-section chat-section" }, [
      h("div", { class: "section-head" }, [
        h("strong", { text: text.chats }),
        !selfUseMode()
          ? h("button", {
              type: "button",
              class: "icon-btn",
              title: text.createPersona,
              "aria-label": text.createPersona,
              text: "+",
              onclick: () => {
                state.view = "forge";
                renderShell();
              },
            })
          : null,
      ]),
      renderConversationSearch(),
      renderChatList(),
    ]),
    renderUserEntry(),
    isAdmin()
      ? h("button", {
          type: "button",
          class: "ghost full",
          text: text.adminConsole,
          onclick: () => {
            window.location.href = "/admin";
          },
        })
      : null,
    !selfUseMode()
      ? h("button", { type: "button", class: "ghost full", text: "切换账号（仅本页）", onclick: switchAccountInThisTab })
      : null,
    !selfUseMode()
      ? h("button", { type: "button", class: "ghost full", text: text.logout, onclick: logout })
      : null,
  ]);
}

function selfUseMode() {
  return !!state.selfUse?.enabled;
}

function renderSelfUseRail() {
  const persona = state.activePersona || state.personas?.[0] || null;
  return h("aside", { class: "sidebar self-use-sidebar companion-rail" }, [
    h("button", {
      type: "button",
      class: "rail-brand",
      title: "LING",
      "aria-label": "LING",
      onclick: () => {
        state.view = "chat";
        if (persona) openPersonaItem(persona);
        else renderShell();
      },
    }, [
      h("strong", { text: "LING" }),
      h("small", { text: persona?.name || "Mio" }),
    ]),
    h("nav", { class: "companion-rail-actions", "aria-label": "LING controls" }, [
      h("button", { type: "button", class: "rail-action active", title: "在场", "aria-label": "在场", text: "在", onclick: () => renderShell() }),
      h("button", { type: "button", class: "rail-action", title: "资料", "aria-label": "资料", text: "资", onclick: openPersonaPanel }),
      h("button", {
        type: "button",
        class: "rail-action",
        title: "接入",
        "aria-label": "接入",
        text: "接",
        onclick: () => {
          state.integrationOpen = true;
          renderShell();
        },
      }),
      h("button", {
        type: "button",
        class: "rail-action",
        title: "记录",
        "aria-label": "记录",
        text: "记",
        onclick: () => {
          state.threadPanelOpen = true;
          state.editingConversationId = null;
          renderShell();
        },
      }),
      h("button", {
        type: "button",
        class: "rail-action",
        title: "我",
        "aria-label": "我",
        text: "我",
        onclick: () => {
          state.profileOpen = true;
          renderShell();
        },
      }),
    ]),
    isAdmin()
      ? h("button", {
          type: "button",
          class: "rail-action rail-admin",
          title: text.adminConsole,
          "aria-label": text.adminConsole,
          text: "管",
          onclick: () => {
            window.location.href = "/admin";
          },
        })
      : null,
  ]);
}

function renderSelfUseSidebar() {
  const persona = state.activePersona || state.personas?.[0] || null;
  return h("aside", { class: "sidebar self-use-sidebar" }, [
    renderBrand(),
    h("section", { class: "sidebar-section chat-section" }, [
      h("div", { class: "section-head" }, [
        h("strong", { text: "澪" }),
      ]),
      persona
        ? h("button", {
            type: "button",
            class: `item ${state.activePersona?.id === persona.id ? "active" : ""}`,
            onclick: () => openPersonaItem(persona),
          }, [
            avatar(persona.name || "澪", persona.avatar_url),
            h("span", {}, [
              h("strong", { text: persona.name || "澪" }),
              h("small", { text: persona.summary || "基础设定待填写。" }),
            ]),
          ])
        : h("p", { class: "empty", text: "澪还在初始化。" }),
    ]),
    renderUserEntry(),
    isAdmin()
      ? h("button", {
          type: "button",
          class: "ghost full",
          text: text.adminConsole,
          onclick: () => {
            window.location.href = "/admin";
          },
        })
      : null,
  ]);
}

function renderUserEntry() {
  return h("section", { class: "sidebar-section user-entry-section" }, [
    h("button", {
      type: "button",
      class: "user-entry",
      onclick: () => {
        state.profileOpen = true;
        renderShell();
      },
    }, [
      avatar(state.profile?.nickname || state.user?.username || "U", state.profile?.avatar_url),
      h("span", {}, [
        h("strong", { text: state.profile?.nickname || state.user?.username || "" }),
        h("small", { text: state.profile?.signature || "查看和编辑资料" }),
      ]),
    ]),
  ]);
}

function renderProfileModal() {
  const profile = state.profile || {};
  const selfUse = selfUseMode();
  const birthday = parseBirthday(profile.birthday);
  const nickname = h("input", { name: "nickname", value: profile.nickname || "" });
  const avatarFile = h("input", { name: "avatar_file", type: "file", accept: "image/png,image/jpeg,image/webp,image/gif" });
  const avatarUrl = h("input", { name: "avatar_url", value: profile.avatar_url || "", placeholder: "可选：粘贴图片链接" });
  const gender = selectControl(["", "男", "女", "其他", "保密"], profile.gender || "", ["未设置", "男", "女", "其他", "保密"]);
  const year = selectControl(["", ...yearOptions()], birthday.year, ["年", ...yearOptions()]);
  const month = selectControl(["", ...rangeOptions(1, 12)], birthday.month, ["月", ...rangeOptions(1, 12).map((item) => `${item}月`)]);
  const day = selectControl(["", ...rangeOptions(1, 31)], birthday.day, ["日", ...rangeOptions(1, 31).map((item) => `${item}日`)]);
  const timezone = h("input", {
    name: "timezone",
    value: profile.timezone || browserTimezone(),
    placeholder: "例如 Asia/Shanghai",
    autocomplete: "off",
  });
  const signature = h("input", { name: "signature", value: profile.signature || "" });
  const bio = h("textarea", { name: "bio", rows: "4", maxlength: "1000", placeholder: "简单写一点关于你自己的信息" }, profile.bio || "");
  const status = h("small", { class: "save-status" });

  const syncDays = () => {
    const selectedDay = day.value;
    const maxDay = daysInMonth(year.value, month.value);
    day.replaceChildren(...["", ...rangeOptions(1, maxDay)].map((value, index) => {
      const option = h("option", { value, text: index === 0 ? "日" : `${value}日` });
      if (value === selectedDay || (Number(selectedDay) > maxDay && Number(value) === maxDay)) option.selected = true;
      return option;
    }));
  };
  year.addEventListener("change", syncDays);
  month.addEventListener("change", syncDays);
  syncDays();

  const close = () => {
    state.profileOpen = false;
    renderShell();
  };

  return h("div", { class: "profile-modal-backdrop", onclick: (event) => {
    if (event.target.classList.contains("profile-modal-backdrop")) close();
  } }, [
    h("section", { class: "profile-modal" }, [
      h("div", { class: "profile-modal-head" }, [
        selfUse
          ? h("div", { class: "profile-card-user" }, [
              h("div", {}, [
                h("h3", { text: "我的资料" }),
                h("small", { text: "只填写你希望澪在相处中知道的内容" }),
              ]),
            ])
          : h("div", { class: "profile-card-user" }, [
              avatar(profile.nickname || state.user?.username || "U", profile.avatar_url),
              h("div", {}, [
                h("h3", { text: profile.nickname || state.user?.username || "" }),
                h("small", { text: state.user?.is_guest ? guestExpiryText() : state.user?.username || "" }),
              ]),
            ]),
        h("div", { class: "profile-modal-tools" }, [
          h("button", {
            type: "button",
            class: "ghost compact",
            text: "数据与隐私",
            onclick: () => openPrivacyModal(renderShell),
          }),
          h("button", { type: "button", class: "ghost compact", text: "关闭", onclick: close }),
        ]),
      ]),
      state.user?.is_guest ? renderGuestDataNotice() : null,
      state.user?.is_guest ? renderGuestConvertBox(profile) : null,
      renderAwarenessConsentPanel(),
      h("form", {
        class: "profile-modal-form",
        onsubmit: async (event) => {
          event.preventDefault();
          status.textContent = "";
          try {
            let avatarValue = selfUse ? profile.avatar_url || "" : avatarUrl.value;
            if (!selfUse && avatarFile.files?.[0]) {
              status.textContent = "正在上传头像...";
              avatarValue = await uploadAvatarFile(avatarFile.files[0]);
            }
            const data = await api("/api/profile", {
              method: "PUT",
              body: JSON.stringify({
                nickname: nickname.value,
                avatar_url: avatarValue,
                gender: gender.value,
                birthday: buildBirthday(year.value, month.value, day.value),
                timezone: timezone.value,
                signature: signature.value,
                bio: bio.value,
              }),
            });
            state.profile = data.profile;
            state.profileOpen = false;
            renderShell();
          } catch (err) {
            status.textContent = err.message;
          }
        },
      }, [
        h("label", {}, [selfUse ? "希望澪怎么称呼你" : text.nickname, nickname]),
        ...(!selfUse ? [
          h("label", {}, ["头像图片", avatarFile]),
          h("label", {}, ["图片链接（可选）", avatarUrl]),
        ] : []),
        h("label", {}, ["性别", gender]),
        h("label", {}, ["生日", h("div", { class: "birthday-selects" }, [year, month, day])]),
        h("label", {}, ["时区", timezone]),
        h("label", {}, [text.signature, signature]),
        h("label", {}, ["简介", bio]),
        h("div", { class: "actions modal-actions" }, [
          h("button", { type: "submit", text: text.save }),
          h("button", { type: "button", class: "ghost", text: "取消", onclick: close }),
        ]),
        status,
      ]),
      selfUse ? null : renderAccountDangerZone(),
    ]),
  ]);
}

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

function renderGuestDataNotice() {
  return h("section", { class: "guest-data-notice" }, [
    h("strong", { text: guestExpiryText() }),
    h("p", { text: "游客数据包括当前人格、聊天、记忆和上传头像。到期会自动清除；转为正式账号可保留，账号删除可立即清理。" }),
  ]);
}

function renderAccountDangerZone() {
  const confirmUsername = h("input", {
    name: "account_delete_confirm_username",
    autocomplete: "username",
    placeholder: state.user?.username || "账号名",
  });
  const password = h("input", {
    name: "account_delete_password",
    type: "password",
    autocomplete: "current-password",
    placeholder: "当前密码",
  });
  const status = h("small", { class: "save-status" });
  const deleteButton = h("button", {
    type: "button",
    class: "ghost danger",
    text: "彻底删除账号",
    disabled: "disabled",
    onclick: async () => {
      status.textContent = "";
      try {
        await api("/api/account/delete", {
          method: "POST",
          body: JSON.stringify({
            confirm_username: confirmUsername.value,
            password: state.user?.is_guest ? null : password.value,
          }),
        });
        prepareAuthMode(tabSessionMode());
        resetClientState();
        renderAuth("login");
      } catch (err) {
        status.textContent = err.message;
      }
    },
  });
  const syncButton = () => {
    const usernameOk = confirmUsername.value.trim() === String(state.user?.username || "").trim();
    const passwordOk = state.user?.is_guest || password.value.length > 0;
    if (usernameOk && passwordOk) deleteButton.removeAttribute("disabled");
    else deleteButton.setAttribute("disabled", "disabled");
  };
  confirmUsername.addEventListener("input", syncButton);
  password.addEventListener("input", syncButton);

  return h("details", { class: "profile-danger-zone" }, [
    h("summary", { text: "删除账号" }),
    h("p", { text: "彻底删除后，账号、人格、聊天、记忆和本地上传目录会被移除，无法恢复。建议先导出数据或创建本地备份。" }),
    h("label", {}, ["输入账号名确认", confirmUsername]),
    state.user?.is_guest ? null : h("label", {}, ["输入当前密码", password]),
    deleteButton,
    status,
  ]);
}

async function loadPrivacyPolicy() {
  if (state.privacyPolicy) return state.privacyPolicy;
  const data = await api("/api/privacy");
  state.privacyPolicy = data.policy;
  return state.privacyPolicy;
}

async function openPrivacyModal(renderFn = renderShell) {
  state.privacyOpen = true;
  try {
    await loadPrivacyPolicy();
  } catch {
    state.privacyPolicy = {
      title: "数据与隐私",
      summary: "暂时无法加载隐私说明，请稍后重试。",
      data_categories: [],
      retention: [],
      user_controls: [],
      external_boundaries: [],
    };
  }
  renderFn();
}

function renderPrivacyModal(renderFn = renderShell) {
  const policy = state.privacyPolicy || {
    title: "数据与隐私",
    summary: "正在加载...",
    data_categories: [],
    retention: [],
    user_controls: [],
    external_boundaries: [],
  };
  const close = () => {
    state.privacyOpen = false;
    renderFn();
  };
  const listSection = (title, items) => h("section", { class: "privacy-section" }, [
    h("h4", { text: title }),
    h("ul", {}, (items || []).map((item) => {
      if (typeof item === "string") return h("li", { text: item });
      return h("li", {}, [
        h("strong", { text: item.name || "" }),
        h("span", { text: item.detail || "" }),
      ]);
    })),
  ]);

  return h("div", { class: "profile-modal-backdrop privacy-backdrop", onclick: (event) => {
    if (event.target.classList.contains("privacy-backdrop")) close();
  } }, [
    h("section", { class: "profile-modal privacy-modal" }, [
      h("div", { class: "profile-modal-head" }, [
        h("div", {}, [
          h("p", { class: "eyebrow", text: `版本 ${policy.version || "-"}` }),
          h("h3", { text: policy.title || "数据与隐私" }),
        ]),
        h("button", { type: "button", class: "ghost compact", text: "关闭", onclick: close }),
      ]),
      h("p", { class: "privacy-summary", text: policy.summary || "" }),
      listSection("保存的数据", policy.data_categories),
      listSection("保留与删除", policy.retention),
      listSection("用户控制", policy.user_controls),
      listSection("外部项目边界", policy.external_boundaries),
    ]),
  ]);
}

function renderGuestConvertBox(profile) {
  const username = h("input", { name: "guest_username", autocomplete: "username", placeholder: "设置登录账号" });
  const password = h("input", {
    name: "guest_password",
    type: "password",
    minlength: "8",
    autocomplete: "new-password",
    placeholder: "至少 8 位密码",
  });
  const nickname = h("input", {
    name: "guest_nickname",
    value: profile.nickname && profile.nickname !== "游客" ? profile.nickname : "",
    autocomplete: "nickname",
    placeholder: "昵称（可选）",
  });
  const status = h("small", { class: "save-status" });
  return h("section", { class: "guest-convert" }, [
    h("div", {}, [
      h("strong", { text: "保留游客数据" }),
      h("p", { class: "muted", text: "绑定正式账号后，当前人格、聊天、记忆和头像会继续保留，不再三天后自动清除。" }),
    ]),
    h("form", {
      class: "guest-convert-form",
      onsubmit: async (event) => {
        event.preventDefault();
        status.textContent = "";
        try {
          const data = await api("/api/auth/guest/convert", {
            method: "POST",
            body: JSON.stringify({
              username: username.value,
              password: password.value,
              nickname: nickname.value,
              tab_session: tabSessionMode(),
            }),
          });
          if (tabSessionMode()) acceptAuthSession(data, true);
          state.user = data.user;
          state.profile = data.profile;
          state.profileOpen = false;
          await loadMainData();
          renderShell();
        } catch (err) {
          status.textContent = err.message;
        }
      },
    }, [
      h("label", {}, ["账号", username]),
      h("label", {}, ["密码", password]),
      h("label", {}, ["昵称", nickname]),
      h("button", { type: "submit", text: "转为正式账号" }),
      status,
    ]),
  ]);
}

function renderBrand() {
  return h("div", { class: "brand" }, [
    h("p", { class: "eyebrow", text: "Workspace" }),
    h("h1", { text: text.appName }),
    h("small", { text: text.appSubtitle }),
  ]);
}

function renderConversationSearch() {
  const input = h("input", {
    class: "conversation-search",
    type: "search",
    placeholder: "搜索陪伴体或记录",
    value: state.conversationSearch,
  });
  input.addEventListener("input", () => {
    state.conversationSearch = input.value;
    renderShell();
  });
  return h("div", { class: "conversation-search-wrap" }, [
    input,
    state.conversationSearch
      ? h("button", {
          type: "button",
          class: "search-clear",
          title: "清空搜索",
          "aria-label": "清空搜索",
          text: "×",
          onclick: () => {
            state.conversationSearch = "";
            renderShell();
          },
        })
      : null,
  ]);
}

function renderChatList() {
  const list = h("div", { class: "list chat-list" });
  if (!state.personas.length) {
    list.append(h("p", { class: "empty", text: "还没有陪伴体。点右上角 + 创建一个。" }));
    return list;
  }

  const query = normalizedSearch(state.conversationSearch);
  const entries = homePersonaEntries(query);
  const groupEntries = homeGroupEntries(query);
  for (const entry of groupEntries) list.append(renderSidebarGroupItem(entry));
  for (const entry of entries) list.append(renderSidebarPersonaItem(entry));
  if (!entries.length && !groupEntries.length) {
    list.append(h("p", { class: "empty", text: "没有匹配的陪伴体或记录。" }));
  }

  return list;
}

function renderArchivedConversations(items) {
  const visibleItems = items || [];
  if (!visibleItems.length) return null;
  return h("section", { class: "archive-box" }, [
    h("button", {
      type: "button",
      class: "archive-toggle",
      text: `历史聊天 ${visibleItems.length || state.archivedConversations.length}`,
      onclick: () => {
        state.showArchived = !state.showArchived;
        renderShell();
      },
    }),
    state.showArchived
      ? h("div", { class: "archive-list" }, visibleItems.map(renderArchivedConversationItem))
      : null,
  ]);
}

function renderArchivedConversationItem(item) {
  return h("div", { class: "archived-item" }, [
    avatar(item.persona_name || "忆", item.persona_avatar_url),
    h("span", {}, [
      h("strong", { text: conversationDisplayTitle(item) }),
      h("small", { text: conversationPreview(item) }),
    ]),
    h("button", {
      type: "button",
      class: "ghost compact",
      text: "移回聊天",
      onclick: async () => {
        await api(`/api/conversations/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ status: "active" }),
        });
        state.showArchived = false;
        await loadMainData();
        renderShell();
      },
    }),
  ]);
}

function renderArchivedGroupConversations() {
  const visibleItems = state.archivedGroupConversations || [];
  if (!visibleItems.length) return null;
  return h("section", { class: "archive-box group-archive-box" }, [
    h("button", {
      type: "button",
      class: "archive-toggle",
      text: `历史群聊 ${visibleItems.length}`,
      onclick: () => {
        state.showArchivedGroups = !state.showArchivedGroups;
        renderShell();
      },
    }),
    state.showArchivedGroups
      ? h("div", { class: "archive-list" }, visibleItems.map(renderArchivedGroupConversationItem))
      : null,
  ]);
}

function renderArchivedGroupConversationItem(item) {
  return h("div", { class: "archived-item archived-group-item" }, [
    groupAvatar(item),
    h("span", {}, [
      h("strong", { text: groupConversationTitle(item) }),
      h("small", { text: groupConversationPreview(item) }),
    ]),
    h("button", {
      type: "button",
      class: "ghost compact",
      text: "移回群聊",
      onclick: async () => {
        await api(`/api/group-conversations/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ status: "active" }),
        });
        state.showArchivedGroups = false;
        await loadMainData();
        renderShell();
      },
    }),
  ]);
}

function renderSidebarGroupItem(entry) {
  const group = entry.group;
  return h(
    "button",
    {
      type: "button",
      class: `list-item sidebar-persona-item group-list-item ${Number(state.activeGroupConversationId) === Number(group.id) && state.view === "group" ? "active" : ""}`,
      onclick: () => openGroupConversationItem(group),
    },
    [
      groupAvatar(group),
      h("span", {}, [
        h("span", { class: "conversation-title-row" }, [
          h("strong", {}, [
            entry.pinned ? h("span", { class: "pin-mark", text: "置顶" }) : null,
            groupConversationTitle(group),
          ]),
          h("small", { text: formatListTime(entry.updatedAt) }),
        ]),
        h("small", { text: groupConversationPreview(group) }),
      ]),
      Number(group.unread_count || 0) ? renderUnreadBadge(Number(group.unread_count)) : null,
    ]
  );
}

function renderConversationChatItem(item) {
  const isEditing = Number(state.editingConversationId) === Number(item.id);
  return h("div", { class: `conversation-shell ${isEditing ? "editing" : ""}` }, [
    h(
      "button",
      {
        type: "button",
        class: `list-item conversation-item ${Number(state.activeConversationId) === Number(item.id) ? "active" : ""}`,
        onclick: () => openConversationItem(item),
      },
      [
        avatar(item.persona_name || "忆", item.persona_avatar_url),
        h("span", {}, [
          h("span", { class: "conversation-title-row" }, [
            h("strong", {}, [
              isPinnedConversation(item) ? h("span", { class: "pin-mark", text: "置顶" }) : null,
              conversationDisplayTitle(item),
            ]),
            h("span", { class: "thread-meta" }, [
              h("small", { text: formatListTime(item.updated_at || item.created_at) }),
              Number(item.unread_count || 0) ? renderUnreadBadge(Number(item.unread_count)) : null,
            ]),
          ]),
          h("small", { text: conversationPreview(item) }),
        ]),
      ]
    ),
    h("button", {
      type: "button",
      class: "conversation-more",
      title: "会话设置",
      "aria-label": "会话设置",
      text: "⋯",
      onclick: (event) => {
        event.stopPropagation();
        state.editingConversationId = isEditing ? null : item.id;
        renderShell();
      },
    }),
    isEditing ? renderConversationEditor(item) : null,
  ]);
}

function renderConversationEditor(item) {
  const input = h("input", { value: item.title || item.persona_name || "聊天", maxlength: "80" });
  const status = h("small", { class: "save-status" });
  const saveTitle = async () => {
    const title = input.value.trim();
    if (!title) {
      status.textContent = "标题不能为空";
      return;
    }
    try {
      await api(`/api/conversations/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      });
      state.editingConversationId = null;
      await loadMainData();
      renderShell();
    } catch (err) {
      status.textContent = err.message;
    }
  };
  return h("div", { class: "conversation-editor" }, [
    input,
    h("div", { class: "conversation-editor-actions" }, [
      h("button", { type: "button", class: "compact", text: "保存", onclick: saveTitle }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: isPinnedConversation(item) ? "取消置顶" : "置顶",
        onclick: async () => {
          try {
            await api(`/api/conversations/${item.id}`, {
              method: "PATCH",
              body: JSON.stringify({ pinned: !isPinnedConversation(item) }),
            });
            state.editingConversationId = null;
            await loadMainData();
            renderShell();
          } catch (err) {
            status.textContent = err.message;
          }
        },
      }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "移到历史",
        onclick: async () => {
          try {
            await api(`/api/conversations/${item.id}`, {
              method: "PATCH",
              body: JSON.stringify({ status: "archived" }),
            });
            if (Number(state.activeConversationId) === Number(item.id)) {
              state.activeConversationId = null;
              state.messages = [];
            }
            state.editingConversationId = null;
            if (state.threadPanelOpen && state.activePersona) {
              await loadMainData();
              await openLatestConversationForPersona(state.activePersona.id);
              state.view = "chat";
            } else {
              await loadMainData({ openLatest: true });
            }
            renderShell();
          } catch (err) {
            status.textContent = err.message;
          }
        },
      }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "取消",
        onclick: () => {
          state.editingConversationId = null;
          renderShell();
        },
      }),
    ]),
    status,
  ]);
}

function renderSidebarPersonaItem(entry) {
  const persona = entry.persona;
  const conversation = entry.conversation;
  return h(
    "button",
    {
      type: "button",
      class: `list-item sidebar-persona-item ${Number(state.activePersona?.id) === Number(persona.id) && state.view === "chat" ? "active" : ""}`,
      onclick: () => conversation ? openConversationItem(conversation) : openPersonaItem(persona),
    },
    [
      avatar(persona.name, persona.avatar_url),
      h("span", {}, [
        h("span", { class: "conversation-title-row" }, [
          h("strong", {}, [
            entry.pinned ? h("span", { class: "pin-mark", text: "置顶" }) : null,
            persona.name,
          ]),
          h("small", { text: conversation ? formatListTime(entry.updatedAt) : "" }),
        ]),
        h("small", { text: conversation ? conversationPreview(conversation) : persona.summary || "还没开始，点开说第一句" }),
      ]),
      renderPersonaAlerts(entry, true),
    ]
  );
}

function renderHome() {
  const query = normalizedSearch(state.conversationSearch);
  const entries = homePersonaEntries(query);
  const groupEntries = homeGroupEntries(query);

  return h("section", { class: "home-screen" }, [
    h("header", { class: "home-head" }, [
      h("div", {}, [
        h("p", { class: "eyebrow", text: state.user?.is_guest ? "游客体验" : "LING" }),
        h("h2", { text: "陪伴体" }),
        state.user?.is_guest ? h("small", { text: guestExpiryText() }) : null,
      ]),
      h("div", { class: "home-actions" }, [
        isAdmin()
          ? h("button", {
              type: "button",
              class: "ghost compact",
              text: text.adminConsole,
              onclick: () => {
                window.location.href = "/admin";
              },
            })
          : null,
        h("button", {
          type: "button",
          class: "ghost compact home-profile-action",
          text: "资料",
          onclick: () => {
            state.profileOpen = true;
            renderShell();
          },
        }),
        !selfUseMode()
          ? h("button", {
              type: "button",
              class: "ghost compact",
              text: "群聊实验",
              disabled: state.personas.length < 2 ? "disabled" : null,
              onclick: () => {
                state.groupCreateOpen = true;
                renderShell();
              },
            })
          : null,
        state.deletedPersonas.length
          ? h("button", {
              type: "button",
              class: "ghost compact",
              text: "已删除",
              onclick: () => {
                state.deletedPanelOpen = true;
                renderShell();
              },
            })
          : null,
        !selfUseMode()
          ? h("button", {
              type: "button",
              class: "icon-btn",
              title: text.createPersona,
              "aria-label": text.createPersona,
              text: "+",
              onclick: () => {
                state.view = "forge";
                renderShell();
              },
            })
          : null,
      ]),
    ]),
    h("section", {
      class: "home-user-strip",
      role: "button",
      tabindex: "0",
      onclick: () => {
        state.profileOpen = true;
        renderShell();
      },
      onkeydown: (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          state.profileOpen = true;
          renderShell();
        }
      },
    }, [
      avatar(state.profile?.nickname || state.user?.username || "U", state.profile?.avatar_url),
      h("span", {}, [
        h("strong", { text: state.profile?.nickname || state.user?.username || "" }),
        h("small", { text: state.user?.is_guest ? guestExpiryText() : state.profile?.signature || "查看和编辑资料" }),
      ]),
      !selfUseMode()
        ? h("button", {
            type: "button",
            class: "ghost compact",
            text: "退出",
            onclick: (event) => {
              event.stopPropagation();
              logout();
            },
          })
        : null,
    ]),
    h("div", { class: "home-search" }, [renderConversationSearch()]),
    !selfUseMode() && groupEntries.length
      ? h("section", { class: "home-group-section" }, [
          h("div", { class: "section-head" }, [
            h("strong", { text: "群聊" }),
            h("small", { text: "多个人格一起接话" }),
          ]),
          h("div", { class: "home-persona-list group-home-list" }, groupEntries.map(renderHomeGroupCard)),
        ])
      : null,
    renderArchivedGroupConversations(),
    h("div", { class: "home-persona-list" }, [
      ...entries.map(renderHomePersonaCard),
      !entries.length
        ? h("p", { class: "empty", text: query ? "没有匹配的陪伴体。" : "还没有陪伴体，点右上角 + 创建一个。" })
        : null,
    ]),
  ]);
}

function renderHomeGroupCard(entry) {
  const group = entry.group;
  return h("article", {
    class: "home-persona-card home-group-card",
    role: "button",
    tabindex: "0",
    onclick: () => openGroupConversationItem(group),
    onkeydown: (event) => {
      if (event.target !== event.currentTarget) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openGroupConversationItem(group);
      }
    },
  }, [
    groupAvatar(group),
    h("span", { class: "home-card-copy" }, [
      h("span", { class: "home-card-title" }, [
        h("strong", {}, [
          entry.pinned ? h("span", { class: "pin-mark", text: "置顶" }) : null,
          groupConversationTitle(group),
        ]),
        h("small", { text: formatListTime(entry.updatedAt) }),
      ]),
      h("small", { text: groupConversationPreview(group) }),
    ]),
    Number(group.unread_count || 0) ? renderUnreadBadge(Number(group.unread_count)) : null,
  ]);
}

function renderHomePersonaCard(entry) {
  const persona = entry.persona;
  const conversation = entry.conversation;
  const archivedConversation = entry.archivedConversation;
  const openCard = () => conversation ? openConversationItem(conversation) : openPersonaItem(persona);
  return h("article", {
    class: "home-persona-card",
    role: "button",
    tabindex: "0",
    onclick: openCard,
    onkeydown: (event) => {
      if (event.target !== event.currentTarget) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openCard();
      }
    },
  }, [
    avatar(persona.name, persona.avatar_url),
    h("span", { class: "home-card-copy" }, [
      h("span", { class: "home-card-title" }, [
        h("strong", {}, [
          entry.pinned ? h("span", { class: "pin-mark", text: "置顶" }) : null,
          persona.name,
        ]),
        h("small", { text: conversation || archivedConversation ? formatListTime(entry.updatedAt) : "未开聊" }),
      ]),
      conversation
        ? h("small", { text: conversationPreview(conversation) })
        : archivedConversation
          ? h("small", { text: `历史：${conversationPreview(archivedConversation)}` })
          : renderInlinePersonaMeta(persona) || h("small", { text: persona.summary || "点开说第一句" }),
    ]),
    renderPersonaAlerts(entry, false, persona),
  ]);
}

function renderPersonaAlerts(entry, compact = false, growthActionPersona = null) {
  const notices = [];
  if (entry.unreadCount) notices.push(renderUnreadBadge(entry.unreadCount));
  if (entry.persona?.growth_notice) {
    notices.push(
      growthActionPersona
        ? h("button", {
            type: "button",
            class: `growth-notice-badge action ${compact ? "compact" : ""}`.trim(),
            title: "直接查看相处痕迹",
            "aria-label": "直接查看相处痕迹",
            text: compact ? "变化" : "查看变化",
            onclick: (event) => openPersonaGrowthNotice(event, growthActionPersona),
          })
        : h("span", {
            class: `growth-notice-badge ${compact ? "compact" : ""}`.trim(),
            title: "查看资料中的相处痕迹",
            text: compact ? "变化" : "有变化",
          })
    );
  }
  if (entry.persona?.growth_action?.kind === "preference_retry") {
    notices.push(
      growthActionPersona
        ? h("button", {
            type: "button",
            class: `preference-action-badge action ${compact ? "compact" : ""}`.trim(),
            title: "打开相处痕迹重新确认偏好",
            "aria-label": "打开相处痕迹重新确认偏好",
            text: compact ? "待确认" : "偏好需确认",
            onclick: (event) => openPersonaGrowthNotice(event, growthActionPersona),
          })
        : h("span", {
            class: `preference-action-badge ${compact ? "compact" : ""}`.trim(),
            title: "到相处痕迹中重新确认偏好",
            text: compact ? "待确认" : "偏好需确认",
          })
    );
  }
  return notices.length ? h("span", { class: "persona-alert-stack" }, notices) : null;
}

function homePersonaEntries(query) {
  const entries = [];
  for (const persona of state.personas) {
    const threads = state.conversations.filter((item) => Number(item.persona_id) === Number(persona.id));
    const archived = state.archivedConversations.filter((item) => Number(item.persona_id) === Number(persona.id));
    if (query && !matchesPersonaSearch(persona, query) && !threads.some((item) => matchesConversationSearch(item, query)) && !archived.some((item) => matchesConversationSearch(item, query))) {
      continue;
    }
    const recentThreads = [...threads].sort((left, right) => Number(right.updated_at || 0) - Number(left.updated_at || 0));
    const latest = recentThreads.find((item) => Number(item.unread_count || 0) > 0) || recentThreads[0] || null;
    const latestArchived = [...archived].sort((left, right) => Number(right.updated_at || 0) - Number(left.updated_at || 0))[0] || null;
    entries.push({
      persona,
      conversation: latest,
      archivedConversation: latestArchived,
      unreadCount: threads.reduce((total, item) => total + Number(item.unread_count || 0), 0),
      pinned: threads.some(isPinnedConversation),
      pinnedAt: Math.max(0, ...threads.map((item) => Number(item.pinned_at || 0))),
      updatedAt: Number(latest?.updated_at || latestArchived?.updated_at || persona.updated_at || persona.created_at || 0),
    });
  }
  return entries.sort((left, right) => right.pinnedAt - left.pinnedAt || right.updatedAt - left.updatedAt);
}

function homeGroupEntries(query) {
  return state.groupConversations
    .filter((group) => matchesGroupSearch(group, query))
    .map((group) => ({
      group,
      pinned: isPinnedConversation(group),
      pinnedAt: Number(group.pinned_at || 0),
      updatedAt: Number(group.updated_at || group.created_at || 0),
    }))
    .sort((left, right) => right.pinnedAt - left.pinnedAt || right.updatedAt - left.updatedAt);
}

function renderUnreadBadge(count) {
  const value = count > 99 ? "99+" : String(count);
  return h("span", { class: `unread-badge ${count > 9 ? "wide" : ""}`, text: value });
}

function guestExpiryText() {
  const expiresAt = Number(state.user?.guest_expires_at || 0);
  if (!expiresAt) return "游客模式，三天后自动清除数据";
  const seconds = Math.max(0, expiresAt - nowSeconds());
  const days = Math.ceil(seconds / 86400);
  if (days > 1) return `游客模式，约 ${days} 天后自动清除数据`;
  const hours = Math.ceil(seconds / 3600);
  return `游客模式，约 ${Math.max(1, hours)} 小时后自动清除数据`;
}

function renderMain() {
  if (selfUseMode() && state.view === "forge" && state.activePersona) {
    state.view = "chat";
  }
  if (selfUseMode() && state.activePersona) {
    return renderSelfUseWorkspace(state.activePersona);
  }
  if (state.view === "home") {
    return renderHome();
  }

  if (state.view === "forge" || !state.activePersona) {
    if (selfUseMode()) {
      return renderSelfUseMissingCompanion();
    }
    if (state.view === "group" && state.activeGroupConversation) {
      return renderGroupChat();
    }
    return renderWizard();
  }

  return h("section", { class: "workspace" }, [
    h("section", { class: "chat-panel" }, [
      h("header", { class: "chat-header" }, [
        !selfUseMode()
          ? h("button", {
              type: "button",
              class: "ghost compact home-back-btn",
              text: isMobileShell() ? "返回" : "返回主界面",
              onclick: returnToHome,
            })
          : null,
        h("button", {
          type: "button",
          class: "avatar-button",
          title: "查看资料",
          "aria-label": "查看资料",
          onclick: openPersonaPanel,
        }, [avatar(state.activePersona.name, state.activePersona.avatar_url)]),
        h("div", { class: "chat-header-copy" }, [
          h("h2", { text: state.activePersona.name }),
          renderPersonaStatusLine(state.activePersona),
          renderPresencePill(),
          h("p", { text: state.activePersona.summary || (selfUseMode() ? "基础设定待填写。" : "陪伴体会在对话和记忆里继续生长。") }),
        ]),
        h("div", { class: "chat-header-actions" }, [
          h("button", {
            type: "button",
            class: "ghost compact chat-profile-action",
            text: "资料",
            onclick: openPersonaPanel,
          }),
          h("button", {
            type: "button",
            class: "ghost compact chat-new-action",
            text: "记录",
            title: "聊天记录",
            "aria-label": "聊天记录",
            onclick: () => {
              state.threadPanelOpen = true;
              state.editingConversationId = null;
              renderShell();
            },
          }),
        ]),
      ]),
      renderCompanionStage(state.activePersona),
      h("div", { id: "chat-log", class: "chat-log" }, state.messages.length ? renderMessageList(state.messages) : [renderChatEmpty()]),
      renderComposer(),
    ]),
  ]);
}

function renderSelfUseWorkspace(persona) {
  return h("section", { class: "workspace self-use-workspace" }, [
    h("section", { class: "self-use-stage-panel" }, [
      renderCompanionStage(persona),
    ]),
    h("section", { class: "self-use-chat-panel" }, [
      h("header", { class: "self-use-chat-head" }, [
        h("div", {}, [
          h("p", { class: "eyebrow", text: "Session" }),
          h("h2", { text: "当前对话" }),
        ]),
        h("div", { class: "self-use-chat-actions" }, [
          h("button", { type: "button", class: "ghost compact", text: "资料", onclick: openPersonaPanel }),
          h("button", {
            type: "button",
            class: "ghost compact",
            text: "记录",
            onclick: () => {
              state.threadPanelOpen = true;
              state.editingConversationId = null;
              renderShell();
            },
          }),
        ]),
      ]),
      renderSelfUseReadinessPanel(persona),
      h("div", { id: "chat-log", class: "chat-log self-use-chat-log" }, state.messages.length ? renderMessageList(state.messages) : [renderChatEmpty()]),
      renderSelfUseApiGate(),
      renderComposer(),
    ]),
  ]);
}

function selfUseApiReadiness() {
  const readiness = state.companionStatus?.readiness || [];
  const apiItem = readiness.find((item) => item && item.key === "api");
  const gate = state.companionStatus?.chat_gate || {};
  const llm = state.companionStatus?.llm || state.llmStatus || {};
  const selfUse = state.companionStatus?.self_use || state.selfUse || {};
  const configured = Object.prototype.hasOwnProperty.call(gate, "llm_configured") ? !!gate.llm_configured : !!llm.configured;
  const verified = Object.prototype.hasOwnProperty.call(gate, "llm_verified") ? !!gate.llm_verified : !!llm.verified;
  const enabled = Object.prototype.hasOwnProperty.call(gate, "enabled") ? !!gate.enabled : selfUse.chat_enabled !== false;
  const provider = String(gate.provider || llm.provider || "").trim();
  const model = String(gate.model || llm.model || "").trim();
  const missing = (gate.missing || llm.missing || []).filter(Boolean).join(", ");
  return {
    ready: enabled && configured && verified,
    enabled,
    selfUseEnabled: !!gate.self_use_enabled,
    configured,
    verified,
    canEnable: !!gate.can_enable,
    reason: gate.reason || "",
    provider,
    model,
    missing,
    text: gate.text || apiItem?.text || (enabled ? llmStatusText() : "模型未启用"),
  };
}

function renderSelfUseApiGate() {
  if (!selfUseMode()) return null;
  const apiState = selfUseApiReadiness();
  const tone = apiState.ready ? "ok" : apiState.configured ? "waiting" : "off";
  const detail = apiState.ready
    ? [apiState.provider, apiState.model].filter(Boolean).join(" / ") || "模型已可用"
    : apiState.canEnable
      ? "连接已验证，仍保持手动开闸"
    : apiState.configured && !apiState.verified
      ? "路由已配置，先检测连接"
    : apiState.enabled && apiState.missing
      ? `缺少 ${apiState.missing}`
      : "保持关闭，避免未接 API 时误触发模型调用";
  const action = apiState.ready
    ? h("button", { type: "button", class: "ghost compact", text: state.chatGateSaving ? "关闭中..." : "关闭", disabled: state.chatGateSaving, onclick: () => setSelfUseChatGate(false) })
    : apiState.canEnable
      ? h("button", { type: "button", class: "primary compact", text: state.chatGateSaving ? "开启中..." : "开启对话", disabled: state.chatGateSaving, onclick: () => setSelfUseChatGate(true) })
      : apiState.configured && !apiState.verified
        ? h("button", { type: "button", class: "compact", text: state.llmProbeSaving ? "检测中..." : "检测连接", disabled: state.llmProbeSaving, onclick: probeSelfUseLlm })
      : null;
  return h("section", { class: `self-use-api-gate ${tone}` }, [
    h("span", { class: "self-use-api-dot" }),
    h("div", {}, [
      h("strong", { text: apiState.ready ? "对话可用" : "对话暂未启用" }),
      h("small", { text: `${apiState.text} · ${detail}` }),
      state.chatGateError ? h("small", { class: "danger-text", text: state.chatGateError }) : null,
    ]),
    action,
  ]);
}

function renderSelfUseIntegrationModal() {
  if (!selfUseMode()) return null;
  const close = () => {
    state.integrationOpen = false;
    renderShell();
  };
  const refresh = async () => {
    await refreshEmbodimentRuntimeStatus();
    renderShell();
  };
  return h("div", { class: "profile-modal-backdrop", onclick: (event) => {
    if (event.target.classList.contains("profile-modal-backdrop")) close();
  } }, [
    h("section", { class: "profile-modal self-use-integration-modal" }, [
      h("div", { class: "profile-modal-head" }, [
        h("div", {}, [
          h("p", { class: "eyebrow", text: "LING" }),
          h("h3", { text: "接入状态" }),
        ]),
        h("div", { class: "modal-actions" }, [
          h("button", { type: "button", class: "ghost compact", text: "刷新", onclick: refresh }),
          h("button", { type: "button", class: "ghost compact", text: "关闭", onclick: close }),
        ]),
      ]),
      h("div", { class: "self-use-integration-grid" }, [
        renderSelfUseApiSetupCard(),
        renderSelfUseLive2dSetupCard(),
        renderSelfUseVoiceSetupCard(),
        renderSelfUseVideoSetupCard(),
      ]),
    ]),
  ]);
}

function renderSelfUseApiSetupCard() {
  const apiState = selfUseApiReadiness();
  const gate = state.companionStatus?.chat_gate || {};
  const llm = state.companionStatus?.llm || state.llmStatus || {};
  const gateTone = apiState.ready ? "ok" : apiState.configured ? "waiting" : "off";
  const verification = gate.verification || llm.verification || {};
  const rows = [
    ["对话闸门", apiState.enabled ? "已打开" : "手动关闭"],
    ["状态原因", chatGateReasonText(apiState.reason)],
    ["可手动开启", apiState.canEnable ? "可以" : "暂不可以"],
    ["Provider", apiState.provider || "unset"],
    ["Model", apiState.model || "unset"],
    ["Base URL", String(gate.base_url || llm.base_url || "").trim() || (apiState.provider === "ollama" ? "local" : "default")],
    ["Key env", gate.requires_api_key || llm.requires_api_key ? (gate.api_key_env || llm.api_key_env || "missing") : "not required"],
    ["Env state", apiState.missing || (gate.requires_api_key || llm.requires_api_key ? "present" : "local")],
    ["Connection", apiState.verified ? "verified" : (verification.state || "unverified")],
  ];
  const gateAction = apiState.ready
    ? h("button", { type: "button", class: "ghost compact", text: state.chatGateSaving ? "关闭中..." : "关闭对话", disabled: state.chatGateSaving, onclick: () => setSelfUseChatGate(false) })
    : apiState.canEnable
      ? h("button", { type: "button", class: "primary compact", text: state.chatGateSaving ? "开启中..." : "开启对话", disabled: state.chatGateSaving, onclick: () => setSelfUseChatGate(true) })
      : null;
  const probeAction = apiState.configured && !apiState.verified
    ? h("button", { type: "button", class: "compact", text: state.llmProbeSaving ? "检测中..." : "检测连接", disabled: state.llmProbeSaving, onclick: probeSelfUseLlm })
    : null;
  return h("section", { class: `self-use-integration-card ${gateTone}` }, [
    h("div", { class: "self-use-integration-card-head" }, [
      h("div", {}, [
        h("small", { text: "Model route" }),
        h("strong", { text: "API chat" }),
      ]),
      h("span", { class: `awareness-status ${gateTone}`, text: apiState.ready ? "ready" : apiState.enabled ? "waiting" : "off" }),
    ]),
    h("div", { class: "self-use-integration-rows" }, rows.map(([label, value]) => renderSelfUseIntegrationRow(label, value))),
    gateAction || probeAction ? h("div", { class: "self-use-integration-actions" }, [probeAction, gateAction]) : null,
    state.chatGateError ? h("small", { class: "danger-text", text: state.chatGateError }) : null,
    h("small", { class: "muted", text: apiState.ready ? "对话输入会使用当前 chat route。" : "对话入口保持锁定，直到 chat gate 与密钥状态同时就绪。" }),
  ]);
}

function chatGateReasonText(reason) {
  return {
    disabled_by_config: "API 已就绪，仍按自用配置保持关闭",
    missing_api_key: "缺少密钥环境变量",
    llm_not_configured: "模型路由未就绪",
    llm_unverified: "路由已配置，连接尚未验证",
    legacy_mode: "兼容模式",
    ready: "可以对话",
  }[reason] || "未知";
}

function renderSelfUseLive2dSetupCard() {
  const persona = state.activePersona || {};
  const embodiment = personaEmbodimentProfile(persona);
  const enabled = live2dAvailable();
  const connected = live2dConnected();
  const tone = connected ? "ok" : enabled ? "waiting" : "off";
  const actions = state.companionStatus?.live2d_actions || {};
  const currentModel = live2dCurrentModelBinding();
  const availableActions = live2dAvailableActions();
  const actionListId = "live2d-available-actions";
  const configKey = "live2d";
  const configFeedback = integrationConfigFeedback(configKey);
  const vtsUrlInput = h("input", {
    value: state.live2dStatus?.vts_ws_url || "ws://127.0.0.1:8002",
    placeholder: "ws://127.0.0.1:8002",
  });
  const idleExpressionInput = h("input", { list: actionListId, value: actions.idle_expression || "Default", placeholder: "Default" });
  const listeningExpressionInput = h("input", { list: actionListId, value: actions.listening_expression || "Listening", placeholder: "Listening" });
  const thinkingExpressionInput = h("input", { list: actionListId, value: actions.thinking_expression || "Thinking", placeholder: "Thinking" });
  const speakingExpressionInput = h("input", { list: actionListId, value: actions.speaking_expression || "Talking", placeholder: "Talking" });
  const lipSyncParameter = String(state.live2dStatus?.lip_sync_parameter || "MouthOpen");
  const lipSyncParameters = (state.live2dStatus?.available_parameters || []).map((item) => String(item.name || "")).filter(Boolean);
  const lipSyncReady = connected && lipSyncParameters.some((name) => name.toLowerCase() === lipSyncParameter.toLowerCase());
  const lipSyncEnabledInput = h("input", { type: "checkbox" });
  lipSyncEnabledInput.checked = state.live2dStatus?.lip_sync_enabled !== false;
  const lipSyncParameterInput = h("input", { value: lipSyncParameter, placeholder: "MouthOpen" });
  const lipSyncGainInput = h("input", {
    type: "number",
    min: "0.1",
    max: "10",
    step: "0.1",
    value: state.live2dStatus?.lip_sync_gain || 2.2,
  });
  const configStatus = h("small", {
    class: "save-status" + (configFeedback.tone === "error" ? " danger-text" : ""),
    text: configFeedback.text,
  });
  const rows = [
    ["Config", enabled ? "enabled" : "disabled"],
    ["VTube Studio", connected ? "connected" : "offline"],
    ["Current", currentModel.label || "none"],
    ["Models", String(state.live2dStatus?.available_model_count ?? 0)],
    ["Available actions", String(availableActions.length)],
    ["Model id", embodiment.live2dModelId || "unbound"],
    ["Idle", actions.idle_expression || "Default"],
    ["Listen", actions.listening_expression || "Listening"],
    ["Think", actions.thinking_expression || "Thinking"],
    ["Talk", actions.speaking_expression || "Talking"],
    ["Lip sync", lipSyncEnabledInput.checked ? (lipSyncReady ? `${lipSyncParameter} ready` : `${lipSyncParameter} unavailable`) : "disabled"],
  ];
  return h("section", { class: `self-use-integration-card ${tone}` }, [
    h("div", { class: "self-use-integration-card-head" }, [
      h("div", {}, [
        h("small", { text: "Embodiment" }),
        h("strong", { text: "Live2D" }),
      ]),
      h("span", { class: `awareness-status ${tone}`, text: connected ? "ready" : enabled ? "waiting" : "off" }),
    ]),
    h("div", { class: "self-use-integration-rows" }, rows.map(([label, value]) => renderSelfUseIntegrationRow(label, value))),
    h("label", { class: "self-use-integration-field" }, [
      h("small", { text: "VTS WebSocket" }),
      vtsUrlInput,
    ]),
    h("div", { class: "self-use-integration-field-grid" }, [
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Idle action" }), idleExpressionInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Listen action" }), listeningExpressionInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Think action" }), thinkingExpressionInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Talk action" }), speakingExpressionInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Mouth parameter" }), lipSyncParameterInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Mouth gain" }), lipSyncGainInput]),
    ]),
    h("label", { class: "self-use-integration-check" }, [lipSyncEnabledInput, h("span", { text: "音频驱动嘴型" })]),
    h("datalist", { id: actionListId }, availableActions.map((action) => h("option", { value: action }))),
    renderSelfUseActionControls(),
    h("div", { class: "self-use-integration-actions" }, [
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "保存地址",
        disabled: state.integrationConfigSaving === configKey,
        onclick: () => setSelfUseIntegrationConfig({ "live2d.vts_ws_url": vtsUrlInput.value }, configStatus),
      }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "保存动作",
        disabled: state.integrationConfigSaving === configKey,
        onclick: () => setSelfUseIntegrationConfig({
          "live2d.idle_expression": idleExpressionInput.value,
          "live2d.listening_expression": listeningExpressionInput.value,
          "live2d.thinking_expression": thinkingExpressionInput.value,
          "live2d.speaking_expression": speakingExpressionInput.value,
        }, configStatus),
      }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "保存嘴型",
        disabled: state.integrationConfigSaving === configKey,
        onclick: () => setSelfUseIntegrationConfig({
          "live2d.lip_sync_enabled": lipSyncEnabledInput.checked,
          "live2d.lip_sync_parameter": lipSyncParameterInput.value,
          "live2d.lip_sync_gain": lipSyncGainInput.value,
        }, configStatus),
      }),
      h("button", {
        type: "button",
        class: "compact",
        text: connected ? "保存并重连" : "保存并连接",
        disabled: !enabled || state.integrationConfigSaving === configKey,
        title: enabled ? "" : "先启用 Live2D 配置",
        onclick: () => saveLive2dConfigAndConnect(vtsUrlInput.value),
      }),
      h("button", {
        type: "button",
        class: enabled ? "ghost compact" : "compact",
        text: integrationFlagButtonText("live2d", enabled),
        disabled: state.integrationFlagSaving === "live2d",
        onclick: () => setSelfUseIntegrationFlag("live2d", !enabled),
      }),
      h("button", { type: "button", class: "ghost compact", text: "编辑形象", onclick: () => {
        state.integrationOpen = false;
        openPersonaEditor();
      } }),
      connected ? h("button", {
        type: "button",
        class: "ghost compact",
        text: "刷新 VTS 能力",
        onclick: () => live2dRefreshCapabilities(configStatus),
      }) : null,
      enabled ? h("button", { type: "button", class: "compact", text: connected ? "重连" : "连接", onclick: live2dConnect }) : null,
      configStatus,
    ]),
    state.integrationFlagError ? h("small", { class: "danger-text", text: state.integrationFlagError }) : null,
  ]);
}

function live2dAvailableActions() {
  const status = state.live2dStatus || {};
  if (status.capabilities_stale === true) return [];
  const expressions = (status.available_expressions || []).map((item) => {
    const file = String(item.file || item.expressionFile || "").trim();
    if (file.toLowerCase().endsWith(".exp3.json")) return file.slice(0, -10);
    return String(item.name || file).trim();
  });
  const hotkeys = (status.available_hotkeys || []).map((item) => String(item.name || item.hotkeyID || "").trim());
  return [...new Set(["Default", ...expressions, ...hotkeys].filter(Boolean))];
}

function renderSelfUseVoiceSetupCard() {
  const persona = state.activePersona || {};
  const embodiment = personaEmbodimentProfile(persona);
  const voice = { ...(state.voiceConfig || {}), ...(state.companionStatus?.voice || {}) };
  const configured = !!voice.enabled;
  const available = !!voice.available;
  const tone = available ? "ok" : configured ? "waiting" : "off";
  const configKey = "voice";
  const configFeedback = integrationConfigFeedback(configKey);
  const providerInput = h("select", {}, [
    h("option", { value: "openai_tts", text: "openai_tts" }),
  ]);
  providerInput.value = voice.provider || voice.tts_provider || "openai_tts";
  const modelInput = h("input", { value: voice.model || voice.tts_model || "gpt-4o-mini-tts", placeholder: "gpt-4o-mini-tts" });
  const keyEnvInput = h("input", { value: voice.api_key_env || "OPENAI_API_KEY", placeholder: "OPENAI_API_KEY" });
  const voiceIdInput = h("input", { value: voice.voice_id || "alloy", placeholder: "alloy" });
  const formatInput = h("select", {}, [h("option", { value: "mp3", text: "mp3" })]);
  formatInput.value = voice.response_format || "mp3";
  const rateInput = h("input", { type: "number", min: "0.25", max: "4", step: "0.05", value: voice.rate || 1 });
  const chunkInput = h("input", { type: "number", min: "20", max: "500", step: "1", value: voice.max_chunk_length || 80 });
  const instructionsInput = h("textarea", {
    rows: 3,
    value: voice.instructions || "",
    placeholder: "Optional speaking instructions",
  });
  const autoPlayInput = h("input", { type: "checkbox", checked: voice.auto_play !== false });
  const configStatus = h("small", {
    class: "save-status" + (configFeedback.tone === "error" ? " danger-text" : ""),
    text: configFeedback.text,
  });
  const rows = [
    ["Config", configured ? "enabled" : "disabled"],
    ["Provider", voice.provider || voice.tts_provider || "unset"],
    ["Model", voice.model || voice.tts_model || "unset"],
    ["Key env", voice.api_key_env || "OPENAI_API_KEY"],
    ["Voice", embodiment.voiceProfile || voice.voice_id || "unbound"],
    ["Auto play", voice.auto_play === false ? "off" : "on"],
    ["Runtime", available ? "available" : (voice.error || "offline")],
  ];
  return h("section", { class: `self-use-integration-card ${tone}` }, [
    h("div", { class: "self-use-integration-card-head" }, [
      h("div", {}, [
        h("small", { text: "Speech" }),
        h("strong", { text: "Voice" }),
      ]),
      h("span", { class: `awareness-status ${tone}`, text: available ? "ready" : configured ? "waiting" : "off" }),
    ]),
    h("div", { class: "self-use-integration-rows" }, rows.map(([label, value]) => renderSelfUseIntegrationRow(label, value))),
    h("div", { class: "self-use-integration-field-grid" }, [
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Provider" }), providerInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Model" }), modelInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Key env" }), keyEnvInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Voice id" }), voiceIdInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Format" }), formatInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Rate" }), rateInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Chunk length" }), chunkInput]),
    ]),
    h("label", { class: "self-use-integration-field" }, [
      h("small", { text: "Instructions" }),
      instructionsInput,
    ]),
    h("label", { class: "self-use-integration-check" }, [autoPlayInput, h("span", { text: "自动朗读新回复" })]),
    h("div", { class: "self-use-integration-actions" }, [
      h("button", {
        type: "button",
        class: "compact",
        text: "Save voice",
        disabled: state.integrationConfigSaving === configKey,
        onclick: () => setSelfUseIntegrationConfig({
          "voice.tts_provider": providerInput.value,
          "voice.tts_model": modelInput.value,
          "voice.api_key_env": keyEnvInput.value,
          "voice.voice_id": voiceIdInput.value,
          "voice.response_format": formatInput.value,
          "voice.rate": rateInput.value,
          "voice.max_chunk_length": chunkInput.value,
          "voice.instructions": instructionsInput.value,
          "voice.auto_play": autoPlayInput.checked,
        }, configStatus, { feedbackKey: configKey }),
      }),
      h("button", {
        type: "button",
        class: configured ? "ghost compact" : "compact",
        text: integrationFlagButtonText("voice", configured),
        disabled: state.integrationFlagSaving === "voice",
        onclick: () => setSelfUseIntegrationFlag("voice", !configured),
      }),
      h("button", { type: "button", class: "ghost compact", text: "编辑声音绑定", onclick: () => {
        state.integrationOpen = false;
        openPersonaEditor();
      } }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "绑定到澪",
        onclick: () => saveSelfUseEmbodimentBinding({ voice_profile: voiceIdInput.value }, configStatus),
      }),
      configStatus,
    ]),
    h("small", { class: "muted", text: "Edge TTS is disabled. LING speech uses a dedicated high-quality TTS provider such as OpenAI TTS." }),
  ]);
}

function renderSelfUseVideoSetupCard() {
  const status = state.videoCompanionStatus || {};
  const config = status.config || {};
  const stateInfo = videoCompanionState();
  const pathState = videoCompanionPathState(config);
  const sessionActive = !!status.status?.session_active;
  const recent = videoCompanionRecentObservation();
  const summary = videoCompanionActivityText(status.recent_summary, "none");
  const consentSync = videoCompanionActivityText(status.recent_consent_sync, "none");
  const consent = status.status?.consent && typeof status.status.consent === "object" ? status.status.consent : {};
  const grantedConsent = Object.entries(consent).filter(([, granted]) => !!granted).map(([key]) => key);
  const configKey = "video_companion";
  const configFeedback = integrationConfigFeedback(configKey);
  const baseUrlInput = h("input", { value: config.base_url || "http://127.0.0.1:8782", placeholder: "http://127.0.0.1:8782" });
  const wsUrlInput = h("input", { value: config.ws_url || "ws://127.0.0.1:8782/ws", placeholder: "ws://127.0.0.1:8782/ws" });
  const projectPathInput = h("input", { value: config.project_path || "", placeholder: "E:\\视觉\\video-companion" });
  const configStatus = h("small", {
    class: "save-status" + (configFeedback.tone === "error" ? " danger-text" : ""),
    text: configFeedback.text,
  });
  const rows = [
    ["Config", status.enabled ? "enabled" : "disabled"],
    ["Path", pathState.text],
    ["Bridge", status.connected ? "connected" : "offline"],
    ["Session", status.status?.session_state || (sessionActive ? "active" : "idle")],
    ["Authorization", grantedConsent.length ? grantedConsent.join(", ") : "none"],
    ["Observation", recent.text],
    ["Summary writeback", summary],
    ["Consent sync", consentSync],
    ["Base URL", config.base_url || "unset"],
  ];
  return h("section", { class: `self-use-integration-card ${stateInfo.tone}` }, [
    h("div", { class: "self-use-integration-card-head" }, [
      h("div", {}, [
        h("small", { text: "External presence" }),
        h("strong", { text: "Video Companion" }),
      ]),
      h("span", { class: `awareness-status ${stateInfo.tone}`, text: sessionActive ? "session" : stateInfo.text }),
    ]),
    h("div", { class: "self-use-integration-rows" }, rows.map(([label, value]) => renderSelfUseIntegrationRow(label, value))),
    h("div", { class: "self-use-integration-field-grid" }, [
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "Base URL" }), baseUrlInput]),
      h("label", { class: "self-use-integration-field" }, [h("small", { text: "WS URL" }), wsUrlInput]),
      h("label", { class: "self-use-integration-field wide" }, [h("small", { text: "Project path" }), projectPathInput]),
    ]),
    h("div", { class: "self-use-integration-actions" }, [
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "保存地址",
        disabled: state.integrationConfigSaving === configKey,
        onclick: () => setSelfUseIntegrationConfig({
          "video_companion.base_url": baseUrlInput.value,
          "video_companion.ws_url": wsUrlInput.value,
          "video_companion.project_path": projectPathInput.value,
        }, configStatus),
      }),
      h("button", {
        type: "button",
        class: "compact",
        text: "保存并检测",
        disabled: state.integrationConfigSaving === configKey,
        onclick: () => saveVideoCompanionConfigAndCheck({
          "video_companion.base_url": baseUrlInput.value,
          "video_companion.ws_url": wsUrlInput.value,
          "video_companion.project_path": projectPathInput.value,
        }),
      }),
      h("button", {
        type: "button",
        class: status.enabled ? "ghost compact" : "compact",
        text: integrationFlagButtonText("video_companion", status.enabled),
        disabled: state.integrationFlagSaving === "video_companion",
        onclick: () => setSelfUseIntegrationFlag("video_companion", !status.enabled),
      }),
      h("button", { type: "button", class: "ghost compact", text: "打开", onclick: openVideoCompanionPage }),
      h("button", { type: "button", class: "ghost compact", text: "刷新", onclick: async () => {
        await loadAwarenessStatus();
        await loadCompanionStatus();
        renderShell();
      } }),
      configStatus,
    ]),
    state.integrationFlagError ? h("small", { class: "danger-text", text: state.integrationFlagError }) : null,
  ]);
}

function renderSelfUseIntegrationRow(label, value) {
  return h("div", { class: "self-use-integration-row" }, [
    h("small", { text: label }),
    h("strong", { text: String(value || "unset") }),
  ]);
}

function selfUseReadinessItems(persona) {
  if (state.companionStatus?.readiness?.length) {
    return state.companionStatus.readiness.map((item) => ({
      key: item.key || item.label,
      label: item.label || item.key || "",
      ready: !!item.ready,
      required: item.required !== false,
      text: item.text || "",
    }));
  }
  const embodiment = personaEmbodimentProfile(persona);
  const items = [];
  items.push({
    key: "api",
    label: "API",
    required: true,
    ready: llmConfigured(),
    text: llmConfigured() ? "模型已可用" : "未启用，接好 API 后再开放对话",
  });
  items.push({
    key: "visual",
    label: "Visual",
    required: false,
    ready: !!embodiment.visualUrl && embodiment.visualSource !== "avatar_url",
    text: embodiment.visualUrl && embodiment.visualSource !== "avatar_url" ? embodiment.visualLabel : "未绑定 preview / fallback 图像",
  });
  items.push({
    key: "live2d",
    label: "Live2D",
    required: true,
    ready: live2dBindingMatchesCurrent(embodiment),
    text: live2dStatusText(embodiment),
  });
  items.push({
    key: "voice",
    label: "Voice",
    required: true,
    ready: !!embodiment.voiceProfile,
    text: embodiment.voiceProfile || "未绑定声音档案",
  });
  items.push({
    key: "lip_sync",
    label: "Lip sync",
    required: true,
    ready: live2dLipSyncReady(),
    text: live2dLipSyncReady() ? `${state.live2dStatus?.lip_sync_parameter || "MouthOpen"} ready` : "等待 VTube Studio 嘴型参数",
  });
  items.push({
    key: "video",
    label: "Video",
    required: false,
    ready: !!(state.videoCompanionStatus?.enabled && state.videoCompanionStatus?.connected),
    text: videoCompanionStatusText(),
  });
  return items;
}

function openSelfUseIntegration() {
  if (!selfUseMode()) return;
  state.integrationOpen = true;
  renderShell();
}

function readinessActionFor(item) {
  const key = item.key || "";
  if (key === "api") {
    const apiState = selfUseApiReadiness();
    if (apiState.configured && !apiState.verified) {
      return {
        text: state.llmProbeSaving ? "检测中..." : "检测",
        disabled: state.llmProbeSaving,
        onclick: probeSelfUseLlm,
      };
    }
    if (!item.ready && apiState.canEnable) {
      return {
        text: state.chatGateSaving ? "开启中..." : "开启",
        disabled: state.chatGateSaving,
        onclick: () => setSelfUseChatGate(true),
      };
    }
    return { text: "接入", onclick: openSelfUseIntegration };
  }
  if (key === "visual") {
    return { text: item.ready ? "查看" : "绑定", onclick: openPersonaEditor };
  }
  if (key === "live2d") {
    if (!live2dAvailable()) {
      return {
        text: state.integrationFlagSaving === "live2d" ? "启用中..." : "启用",
        disabled: state.integrationFlagSaving === "live2d",
        onclick: () => setSelfUseIntegrationFlag("live2d", true),
      };
    }
    return { text: live2dConnected() ? "设置" : "连接", onclick: live2dConnected() ? openSelfUseIntegration : live2dConnect };
  }
  if (key === "voice") {
    return { text: item.ready ? "查看" : "绑定", onclick: openPersonaEditor };
  }
  if (key === "lip_sync") {
    return { text: item.ready ? "设置" : "接入", onclick: openSelfUseIntegration };
  }
  if (key === "video") {
    const video = state.videoCompanionStatus || {};
    if (!video.enabled) {
      return {
        text: state.integrationFlagSaving === "video_companion" ? "启用中..." : "启用",
        disabled: state.integrationFlagSaving === "video_companion",
        onclick: () => setSelfUseIntegrationFlag("video_companion", true),
      };
    }
    return { text: video.connected ? "打开" : "接入", onclick: video.connected ? openVideoCompanionPage : openSelfUseIntegration };
  }
  return { text: "处理", onclick: openSelfUseIntegration };
}

function renderSelfUseReadinessPanel(persona) {
  const items = selfUseReadinessItems(persona);
  const requiredItems = items.filter((item) => item.required !== false);
  const completeCount = requiredItems.filter((item) => item.ready).length;
  return h("section", { class: "self-use-readiness" }, [
    h("div", { class: "self-use-readiness-head" }, [
      h("div", {}, [
        h("p", { class: "eyebrow", text: "Readiness" }),
        h("strong", { text: `${completeCount}/${requiredItems.length} 核心就绪` }),
      ]),
      h("button", { type: "button", class: "ghost compact", text: "编辑形象", onclick: openPersonaEditor }),
    ]),
    h("div", { class: "self-use-readiness-list" }, items.map((item) => (
      renderSelfUseReadinessItem(item)
    ))),
  ]);
}

function renderSelfUseReadinessItem(item) {
  const action = readinessActionFor(item);
  return h("div", { class: `self-use-readiness-item ${item.ready ? "ready" : "missing"} ${item.required === false ? "optional" : "required"}` }, [
    h("span", { class: "self-use-readiness-dot" }),
    h("div", { class: "self-use-readiness-copy" }, [
      h("strong", { text: item.required === false ? `${item.label} · 可选` : item.label }),
      h("small", { text: item.text }),
    ]),
    h("button", {
      type: "button",
      class: item.ready ? "ghost compact" : "compact",
      text: action.text,
      disabled: action.disabled,
      onclick: action.onclick,
    }),
  ]);
}

function renderSelfUseActionControls() {
  const statusEl = h("small", { class: "save-status" });
  const actions = state.companionStatus?.live2d_actions || {};
  const configured = live2dAvailable();
  const connected = live2dConnected();
  const canTrigger = configured && connected;
  const trigger = async (runtimeState) => {
    statusEl.textContent = "";
    const result = await applyLive2dRuntimeState(runtimeState, { report: true });
    statusEl.textContent = live2dRuntimeResultText(result, runtimeState);
  };
  return h("section", { class: "self-use-action-control" }, [
    h("div", { class: "self-use-action-head" }, [
      h("small", { text: "Live2D actions" }),
      h("span", { class: `awareness-status ${canTrigger ? "ok" : configured ? "waiting" : "off"}`, text: canTrigger ? "connected" : configured ? "waiting" : "off" }),
    ]),
    h("div", { class: "self-use-action-buttons" }, [
      h("button", {
        type: "button",
        class: "ghost compact",
        text: `Idle ${actions.idle_expression || "Default"}`,
        disabled: canTrigger ? null : "disabled",
        title: live2dActionDisabledReason(),
        onclick: () => trigger("idle"),
      }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: `Think ${actions.thinking_expression || "Thinking"}`,
        disabled: canTrigger ? null : "disabled",
        title: live2dActionDisabledReason(),
        onclick: () => trigger("thinking"),
      }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: `Listen ${actions.listening_expression || "Listening"}`,
        disabled: canTrigger ? null : "disabled",
        title: live2dActionDisabledReason(),
        onclick: () => trigger("listening"),
      }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: `Talk ${actions.speaking_expression || "Talking"}`,
        disabled: canTrigger ? null : "disabled",
        title: live2dActionDisabledReason(),
        onclick: () => trigger("speaking"),
      }),
    ]),
    statusEl,
  ]);
}

function live2dActionDisabledReason() {
  if (!live2dAvailable()) return "Live2D is disabled in config.yaml";
  if (!live2dConnected()) return "Connect VTube Studio first";
  return "";
}

function live2dRuntimeResultText(result, fallbackState) {
  if (!result) return live2dActionDisabledReason() || fallbackState;
  if (result.applied) return result.expression ? `applied ${result.expression}` : "applied";
  if (result.expression) return `${result.reason || "not applied"}: ${result.expression}`;
  return result.reason || "not applied";
}

function videoCompanionRecentObservation() {
  const item = state.videoCompanionStatus?.recent_observation || state.companionStatus?.video_companion?.recent_observation || null;
  if (!item) return { text: "none", title: "" };
  const type = String(item.observation_type || "observation").trim();
  const content = String(item.content || "").replace(/\s+/g, " ").trim();
  const freshness = item.fresh === false ? "stale" : item.fresh === true ? "fresh" : "";
  const text = [content ? `${type}: ${content}` : type, freshness].filter(Boolean).join(" · ");
  return {
    text: text.length > 96 ? `${text.slice(0, 93)}...` : text,
    title: text,
  };
}

function videoCompanionActivityText(item, emptyText = "none") {
  if (!item) return emptyText;
  const createdAt = Number(item.created_at || 0);
  const type = String(item.observation_type || "event");
  return createdAt ? `${type} · ${formatListTime(createdAt)}` : type;
}

function renderSelfUseMissingCompanion() {
  return h("section", { class: "workspace" }, [
    h("section", { class: "chat-panel empty-companion-panel" }, [
      h("div", { class: "chat-empty" }, [
        h("p", { class: "eyebrow", text: "LING" }),
        h("h2", { text: "澪还在初始化" }),
        h("p", { text: "本地自用模式应该自动准备澪，而不是进入创建人格流程。请刷新一次，或检查 /api/auth/local。" }),
      ]),
    ]),
  ]);
}

function personaEmbodimentProfile(persona) {
  const statusEmbodiment = Number(state.companionStatus?.persona_id || 0) === Number(persona?.id || 0)
    ? (state.companionStatus?.embodiment || {})
    : {};
  const live2dPreviewUrl = String(persona?.live2d_preview_url || "").trim();
  const fallbackImageUrl = String(persona?.fallback_image_url || "").trim();
  const avatarUrl = String(persona?.avatar_url || "").trim();
  const visual = [
    ["live2d_preview_url", live2dPreviewUrl, "临时静态形象", "preview"],
    ["fallback_image_url", fallbackImageUrl, "Fallback image", "fallback"],
    ["avatar_url", avatarUrl, "Legacy fallback", "legacy"],
  ].find(([, value]) => value);
  return {
    live2dModelId: String(statusEmbodiment.live2d_model_id || persona?.live2d_model_id || "").trim(),
    voiceProfile: String(statusEmbodiment.voice_profile || persona?.voice_profile || "").trim(),
    visualUrl: String(statusEmbodiment.visual_url || (visual ? visual[1] : "") || "").trim(),
    visualSource: String(statusEmbodiment.visual_source || (visual ? visual[0] : "none") || "none"),
    visualLabel: String(statusEmbodiment.visual_label || (visual ? visual[2] : "临时形象待绑定")),
    visualTone: String(statusEmbodiment.visual_tone || (visual ? visual[3] : "missing")),
  };
}

function personaVisualUrl(persona) {
  return personaEmbodimentProfile(persona).visualUrl;
}

function renderCompanionVisual(persona, embodiment) {
  const imageUrl = embodiment.visualUrl;
  const capturedWindow = state.easyVtuberCaptureActive && easyVtuberCaptureStream;
  const currentModel = live2dCurrentModelBinding();
  const live2dLabel = embodiment.live2dModelId
      ? `Bound ${embodiment.live2dModelId}`
      : currentModel.label
        ? `VTS ${currentModel.label}`
      : "EasyVtuber 在外部窗口运行";
  const attrs = capturedWindow
    ? {
      class: "companion-visual live-capture",
      title: "已绑定 EasyVtuber 实时窗口",
      "aria-label": "已绑定 EasyVtuber 实时窗口",
    }
    : {
      type: "button",
      class: `companion-visual ${embodiment.visualTone}`,
      title: "编辑形象",
      "aria-label": "编辑形象",
      onclick: (event) => {
        event.preventDefault();
        event.stopPropagation();
        openPersonaEditor();
      },
    };
  const visual = h(capturedWindow ? "div" : "button", attrs, [
    capturedWindow
      ? h("video", { autoplay: true, muted: true, playsinline: true })
      : imageUrl
      ? h("img", {
          src: imageUrl,
          alt: persona?.name || "LING companion",
          onerror: (event) => {
            event.currentTarget.closest(".companion-visual")?.classList.add("image-error");
          },
        })
      : h("span", { class: "companion-visual-empty" }, [
          h("strong", { text: "Live2D" }),
          h("small", { text: "Bind body" }),
        ]),
    h("span", {
      class: `companion-visual-source ${capturedWindow ? "preview" : embodiment.visualTone}`,
      text: capturedWindow ? "EasyVtuber 实时画面" : embodiment.visualLabel,
    }),
    h("span", { class: "companion-visual-model", text: live2dLabel }),
  ]);
  if (capturedWindow) {
    const video = visual.querySelector("video");
    if (video) {
      video.srcObject = easyVtuberCaptureStream;
      video.muted = true;
      video.playsInline = true;
      video.play().catch(() => {});
    }
  }
  return visual;
}

function renderCompanionStage(persona) {
  const embodiment = personaEmbodimentProfile(persona);
  const runtime = companionRuntimeState();
  const live2dEnabled = live2dAvailable();
  const live2dReady = live2dConnected();
  const statusClass = live2dStatusClass(embodiment);
  return h("section", { class: `companion-stage ${embodiment.visualUrl ? "has-image" : "no-image"}` }, [
    renderCompanionVisual(persona, embodiment),
    h("div", { class: "companion-stage-copy" }, [
      h("p", { class: "eyebrow", text: "LING" }),
      h("h2", { text: persona?.name || "澪" }),
      h("div", { class: `companion-runtime-badge ${runtime.key}` }, [
        h("span", { class: "companion-runtime-dot" }),
        h("strong", { text: runtime.label }),
        h("small", { text: runtime.detail }),
      ]),
      renderPersonaStatusLine(persona || {}),
      h("div", { class: "companion-stage-pills" }, [
        h("span", { class: `live2d-stage-pill ${statusClass}` }, [
          h("span", { class: `live2d-status-dot ${statusClass}` }),
          h("span", { text: live2dEnabled ? live2dStatusText(embodiment) : "Live2D 待接入" }),
        ]),
        h("span", {
          class: `companion-mode-pill ${embodiment.live2dModelId ? "ok" : "off"}`,
          text: embodiment.live2dModelId ? `模型 ${embodiment.live2dModelId}` : "模型未绑定",
        }),
        h("span", { class: `companion-mode-pill ${llmConfigured() ? "ok" : "off"}`, text: llmStatusText() }),
        h("span", {
          class: `companion-mode-pill ${embodiment.voiceProfile ? "ok" : "off"}`,
          text: embodiment.voiceProfile ? `声音 ${embodiment.voiceProfile}` : "声音未绑定",
        }),
        presenceAvailable() ? h("span", { class: "companion-mode-pill", text: presenceStatusText(presenceStatusKey()) }) : null,
      ]),
    ]),
    renderCompanionStageActions({ live2dEnabled, live2dConnected: live2dReady }),
  ]);
}

function renderCompanionStageActions({ live2dEnabled, live2dConnected }) {
  if (!selfUseMode()) {
    return live2dEnabled ? h("div", { class: "companion-stage-actions" }, [
      live2dConnected
        ? h("button", { type: "button", class: "ghost compact", text: "断开", onclick: live2dDisconnect })
        : h("button", { type: "button", class: "compact", text: "连接 Live2D", onclick: live2dConnect }),
      live2dConnected
        ? h("button", { type: "button", class: "ghost compact", text: "微笑", onclick: live2dTestExpression })
        : null,
    ]) : null;
  }

  const statusEl = h("small", {
    class: `save-status companion-stage-action-status${state.presenceControlError ? " danger-text" : ""}`,
    text: state.easyVtuberFeedback || state.presenceControlError || "",
  });
  const apiState = selfUseApiReadiness();
  const video = state.videoCompanionStatus || {};
  const videoActive = !!video.status?.session_active;
  const videoCanControl = !!video.enabled && !!video.connected;
  const actions = [
    h("button", {
      type: "button",
      class: "ghost compact",
      text: state.easyVtuberOpening ? "正在打开..." : "打开 EasyVtuber",
      disabled: state.easyVtuberOpening,
      onclick: openEasyVtuber,
    }),
    h("button", {
      type: "button",
      class: state.easyVtuberCaptureActive ? "ghost compact" : "compact",
      text: state.easyVtuberCaptureRequesting
        ? "正在请求窗口..."
        : state.easyVtuberCaptureActive
          ? "取消窗口绑定"
          : "绑定 EasyVtuber 窗口",
      disabled: state.easyVtuberCaptureRequesting,
      onclick: state.easyVtuberCaptureActive ? stopEasyVtuberWindowCapture : bindEasyVtuberWindow,
    }),
    h("button", { type: "button", class: "ghost compact", text: "编辑形象", onclick: openPersonaEditor }),
    live2dEnabled
      ? live2dConnected
        ? h("button", { type: "button", class: "ghost compact", text: "断开 Live2D", onclick: live2dDisconnect })
        : h("button", { type: "button", class: "compact", text: "连接 Live2D", onclick: live2dConnect })
      : h("button", {
        type: "button",
        class: "compact",
        text: integrationFlagButtonText("live2d", false),
        disabled: state.integrationFlagSaving === "live2d",
        onclick: () => setSelfUseIntegrationFlag("live2d", true),
      }),
    live2dConnected
      ? h("button", { type: "button", class: "ghost compact", text: "微笑", onclick: live2dTestExpression })
      : null,
    apiState.ready
      ? h("button", { type: "button", class: "ghost compact", text: state.chatGateSaving ? "关闭中..." : "关闭对话", disabled: state.chatGateSaving, onclick: () => setSelfUseChatGate(false) })
      : apiState.canEnable
        ? h("button", { type: "button", class: "primary compact", text: state.chatGateSaving ? "开启中..." : "开启对话", disabled: state.chatGateSaving, onclick: () => setSelfUseChatGate(true) })
        : null,
    presenceAvailable()
      ? h("button", {
          type: "button",
          class: "ghost compact",
          text: state.presenceSaving
            ? "切换中..."
            : presenceRuntime().quiet_mode ? "恢复在场" : "安静模式",
          disabled: state.presenceSaving,
          onclick: () => setPresenceQuietMode(!presenceRuntime().quiet_mode),
        })
      : null,
    !video.enabled
      ? h("button", {
        type: "button",
        class: "compact",
        text: integrationFlagButtonText("video_companion", false),
        disabled: state.integrationFlagSaving === "video_companion",
        onclick: () => setSelfUseIntegrationFlag("video_companion", true),
      })
      : videoCanControl
      ? videoActive
        ? h("button", { type: "button", class: "ghost compact", text: "停止视频", onclick: () => stopVideoCompanion(statusEl) })
        : h("button", { type: "button", class: "compact", text: "启动视频", onclick: () => startVideoCompanion(statusEl) })
      : h("button", { type: "button", class: "ghost compact", text: "打开视频", onclick: openVideoCompanionPage }),
    statusEl,
  ].filter(Boolean);
  return h("div", { class: "companion-stage-actions self-use-stage-actions" }, actions);
}

async function openEasyVtuber() {
  if (state.easyVtuberOpening) return;
  state.easyVtuberOpening = true;
  state.easyVtuberFeedback = "";
  renderShell();
  try {
    const result = await api("/api/easyvtuber/open", { method: "POST" });
    state.easyVtuberFeedback = result.already_running ? "已在运行" : "已启动";
  } catch (err) {
    state.easyVtuberFeedback = err.message || "打开失败";
  } finally {
    state.easyVtuberOpening = false;
    renderShell();
  }
}

function stopEasyVtuberWindowCapture() {
  if (easyVtuberCaptureStream) {
    easyVtuberCaptureStream.getTracks().forEach((track) => track.stop());
  }
  easyVtuberCaptureStream = null;
  state.easyVtuberCaptureActive = false;
  state.easyVtuberFeedback = "已取消 EasyVtuber 窗口绑定";
  renderShell();
}

async function bindEasyVtuberWindow() {
  if (state.easyVtuberCaptureRequesting) return;
  if (!navigator.mediaDevices?.getDisplayMedia) {
    state.easyVtuberFeedback = "当前浏览器不支持窗口捕获；请使用 Chrome 或 Edge。";
    renderShell();
    return;
  }
  state.easyVtuberCaptureRequesting = true;
  state.easyVtuberFeedback = "请选择 EasyVtuber 的 Debug Output 窗口";
  renderShell();
  try {
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        displaySurface: "window",
        cursor: "never",
        frameRate: 30,
      },
      audio: false,
      preferCurrentTab: false,
      selfBrowserSurface: "exclude",
    });
    const track = stream.getVideoTracks()[0];
    if (!track) {
      stream.getTracks().forEach((item) => item.stop());
      throw new Error("没有获取到窗口画面");
    }
    if (easyVtuberCaptureStream) {
      easyVtuberCaptureStream.getTracks().forEach((item) => item.stop());
    }
    easyVtuberCaptureStream = stream;
    state.easyVtuberCaptureActive = true;
    state.easyVtuberFeedback = "EasyVtuber 画面已绑定到 LING";
    track.addEventListener("ended", () => {
      if (easyVtuberCaptureStream !== stream) return;
      easyVtuberCaptureStream = null;
      state.easyVtuberCaptureActive = false;
      state.easyVtuberFeedback = "EasyVtuber 窗口共享已结束";
      renderShell();
    }, { once: true });
  } catch (err) {
    const denied = err?.name === "NotAllowedError" || err?.name === "AbortError";
    state.easyVtuberFeedback = denied
      ? "未绑定窗口：请选择 EasyVtuber 的 Debug Output 窗口后确认。"
      : (err?.message || "窗口绑定失败");
  } finally {
    state.easyVtuberCaptureRequesting = false;
    renderShell();
  }
}

function llmConfigured() {
  if (selfUseMode()) return selfUseApiReadiness().ready;
  return !!state.llmStatus?.configured;
}

function chatInputBlocked() {
  return selfUseMode() && !llmConfigured();
}

function llmStatusText() {
  if (selfUseMode()) {
    const apiState = selfUseApiReadiness();
    if (apiState.ready) return apiState.model ? `模型已连接 ${apiState.model}` : "模型已连接";
    if (apiState.configured && !apiState.verified) return "模型待检测";
    if (apiState.verified && !apiState.enabled) return "模型已验证，未启用";
    return apiState.missing ? `模型未连接：${apiState.missing}` : "模型未配置";
  }
  const status = state.llmStatus || {};
  if (status.configured) return status.model ? `模型已连接 ${status.model}` : "模型已连接";
  const missing = Array.isArray(status.missing) && status.missing.length ? status.missing[0] : "API key";
  return `模型未连接：${missing}`;
}

function renderGroupChat() {
  const group = state.activeGroupConversation || {};
  return h("section", { class: "workspace group-workspace" }, [
    h("section", { class: "chat-panel" }, [
      h("header", { class: "chat-header group-chat-header" }, [
        h("button", {
          type: "button",
          class: "ghost compact home-back-btn",
          text: isMobileShell() ? "返回" : "返回主界面",
          onclick: returnToHome,
        }),
        groupAvatar(group),
        h("div", { class: "chat-header-copy" }, [
          h("h2", { text: groupConversationTitle(group) }),
          h("div", { class: "persona-status-line" }, (group.members || []).slice(0, 6).map((member) => (
            h("span", { class: "status-pill", text: member.display_name || member.name || "TA" })
          ))),
          h("p", { text: "群聊模式：大家会视情况接话，也可以保持沉默。" }),
        ]),
        h("div", { class: "chat-header-actions" }, [
          h("button", {
            type: "button",
            class: "ghost compact chat-new-action",
            text: "设置",
            onclick: () => {
              state.groupSettingsOpen = true;
              renderShell();
            },
          }),
          h("button", {
            type: "button",
            class: "ghost compact chat-new-action",
            text: "归档",
            onclick: async () => {
              await api(`/api/group-conversations/${group.id}`, {
                method: "PATCH",
                body: JSON.stringify({ status: "archived" }),
              });
              state.view = "home";
              state.activeGroupConversationId = null;
              state.activeGroupConversation = null;
              state.groupMessages = [];
              state.groupSettingsOpen = false;
              await loadMainData();
              renderShell();
            },
          }),
        ]),
      ]),
      h("div", { id: "chat-log", class: "chat-log group-chat-log" }, state.groupMessages.length ? renderGroupMessageList(state.groupMessages) : [renderGroupChatEmpty()]),
      renderComposer(),
    ]),
    state.groupSettingsOpen ? renderGroupSettingsModal(group) : null,
  ]);
}

function renderGroupSettingsModal(group) {
  const input = h("input", { value: groupConversationTitle(group), maxlength: "80" });
  const status = h("small", { class: "save-status" });
  const close = () => {
    state.groupSettingsOpen = false;
    renderShell();
  };
  const saveTitle = async () => {
    const title = input.value.trim();
    if (!title) {
      status.textContent = "群名不能为空";
      return;
    }
    try {
      await api(`/api/group-conversations/${group.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      });
      await loadMainData();
      state.groupSettingsOpen = false;
      renderShell();
    } catch (err) {
      status.textContent = err.message;
    }
  };
  const archiveGroup = async () => {
    try {
      await api(`/api/group-conversations/${group.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "archived" }),
      });
      state.view = "home";
      state.activeGroupConversationId = null;
      state.activeGroupConversation = null;
      state.groupMessages = [];
      state.groupSettingsOpen = false;
      await loadMainData();
      renderShell();
    } catch (err) {
      status.textContent = err.message;
    }
  };
  return h("div", { class: "profile-modal-backdrop", onclick: (event) => {
    if (event.target.classList.contains("profile-modal-backdrop")) close();
  } }, [
    h("section", { class: "profile-modal group-settings-modal" }, [
      h("div", { class: "profile-modal-head" }, [
        h("h3", { text: "群设置" }),
        h("button", { type: "button", class: "ghost compact", text: "关闭", onclick: close }),
      ]),
      h("div", { class: "group-settings-row" }, [
        h("label", {}, [
          h("span", { text: "群名" }),
          input,
        ]),
        h("button", { type: "button", class: "compact", text: "保存", onclick: saveTitle }),
        h("button", {
          type: "button",
          class: "ghost compact",
          text: isPinnedConversation(group) ? "取消置顶" : "置顶",
          onclick: async () => {
            try {
              await api(`/api/group-conversations/${group.id}`, {
                method: "PATCH",
                body: JSON.stringify({ pinned: !isPinnedConversation(group) }),
              });
              await loadMainData();
              renderShell();
            } catch (err) {
              status.textContent = err.message;
            }
          },
        }),
        h("button", { type: "button", class: "ghost compact danger-soft", text: "移到历史", onclick: archiveGroup }),
      ]),
      h("div", { class: "group-settings-members" }, [
        h("strong", { text: "群成员" }),
        h("div", { class: "group-member-strip" }, (group.members || []).map((member) => (
          h("span", { class: "group-member-pill" }, [
            avatar(member.display_name || member.name || "TA", member.avatar_url),
            h("span", { text: member.display_name || member.name || "TA" }),
          ])
        ))),
      ]),
      status,
    ]),
  ]);
}

function renderGroupChatEmpty() {
  const group = state.activeGroupConversation || {};
  return h("div", { class: "chat-empty" }, [
    groupAvatar(group),
    h("h3", { text: groupConversationTitle(group) }),
    h("p", { text: "发一句话，群里的成员会自己判断谁来接。" }),
    h("div", { class: "chat-empty-actions" }, [
      chatStarterButton("你们一起聊聊看。"),
      chatStarterButton("我今天有点无聊。"),
      chatStarterButton("给我一个新的话题。"),
    ]),
  ]);
}

function renderPersonaModal() {
  const close = () => {
    state.personaPanelOpen = false;
    state.editingPersona = false;
    renderShell();
  };
  return h("div", { class: "profile-modal-backdrop", onclick: (event) => {
    if (event.target.classList.contains("profile-modal-backdrop")) close();
  } }, [
    h("section", { class: "profile-modal persona-modal" }, [
      h("div", { class: "profile-modal-head" }, [
        h("strong", { text: "资料" }),
        h("button", { type: "button", class: "ghost compact", text: "关闭", onclick: close }),
      ]),
      renderPersonaRail(),
    ]),
  ]);
}

function renderThreadModal() {
  const persona = state.activePersona || {};
  const activeThreads = state.conversations.filter((item) => Number(item.persona_id) === Number(persona.id));
  const archivedThreads = state.archivedConversations.filter((item) => Number(item.persona_id) === Number(persona.id));
  const close = () => {
    state.threadPanelOpen = false;
    state.editingConversationId = null;
    renderShell();
  };
  return h("div", { class: "profile-modal-backdrop", onclick: (event) => {
    if (event.target.classList.contains("profile-modal-backdrop")) close();
  } }, [
    h("section", { class: "profile-modal thread-modal" }, [
      h("div", { class: "profile-modal-head" }, [
        h("strong", { text: `${persona.name || "TA"} 的聊天记录` }),
        h("button", { type: "button", class: "ghost compact", text: "关闭", onclick: close }),
      ]),
      h("button", {
        type: "button",
        class: "ghost new-thread-action",
        text: text.newChat,
        onclick: () => {
          state.activeConversationId = null;
          state.messages = [];
          state.threadPanelOpen = false;
          state.editingConversationId = null;
          state.focusComposer = true;
          renderShell();
        },
      }),
      h("div", { class: "thread-list" }, [
        ...activeThreads.map(renderConversationChatItem),
        !activeThreads.length ? h("p", { class: "empty", text: "还没有正在进行的聊天。" }) : null,
        archivedThreads.length ? renderArchivedConversations(archivedThreads) : null,
      ]),
    ]),
  ]);
}

function renderGroupCreateModal() {
  const selected = new Set();
  const titleInput = h("input", { maxlength: "80", placeholder: "群聊标题（可选）" });
  const status = h("small", { class: "save-status" });
  const createButton = h("button", { type: "submit", text: "创建群聊", disabled: "disabled" });
  const close = () => {
    state.groupCreateOpen = false;
    renderShell();
  };
  const updateCreateState = () => {
    createButton.disabled = selected.size < 2;
    status.textContent = selected.size < 2 ? "至少选择 2 个人格。" : `已选择 ${selected.size} 个成员。`;
  };
  const memberButtons = state.personas.map((persona) => {
    const button = h("button", {
      type: "button",
      class: "group-member-choice",
      onclick: () => {
        const id = Number(persona.id);
        if (selected.has(id)) selected.delete(id);
        else if (selected.size < 6) selected.add(id);
        button.classList.toggle("active", selected.has(id));
        updateCreateState();
      },
    }, [
      avatar(persona.name, persona.avatar_url),
      h("span", {}, [
        h("strong", { text: persona.name }),
        h("small", { text: persona.summary || persona.speaking_style || "" }),
      ]),
    ]);
    return button;
  });
  updateCreateState();
  return h("div", { class: "profile-modal-backdrop", onclick: (event) => {
    if (event.target.classList.contains("profile-modal-backdrop")) close();
  } }, [
    h("section", { class: "profile-modal group-create-modal" }, [
      h("div", { class: "profile-modal-head" }, [
        h("strong", { text: "新建群聊" }),
        h("button", { type: "button", class: "ghost compact", text: "关闭", onclick: close }),
      ]),
      h("p", { class: "muted", text: "选择 2-6 个人格。群里不是每个人都会每轮说话，会由调度器判断谁接。" }),
      h("form", {
        class: "group-create-form",
        onsubmit: async (event) => {
          event.preventDefault();
          if (selected.size < 2) return;
          createButton.disabled = true;
          status.textContent = "正在创建群聊...";
          try {
            const data = await api("/api/group-conversations", {
              method: "POST",
              body: JSON.stringify({
                title: titleInput.value.trim() || null,
                persona_ids: [...selected],
              }),
            });
            state.groupCreateOpen = false;
            await loadMainData();
            await openGroupConversationItem(data.group_conversation);
          } catch (err) {
            status.textContent = err.message;
            createButton.disabled = false;
          }
        },
      }, [
        h("label", {}, ["标题", titleInput]),
        h("div", { class: "group-member-grid" }, memberButtons),
        h("div", { class: "actions modal-actions" }, [
          createButton,
          h("button", { type: "button", class: "ghost", text: "取消", onclick: close }),
        ]),
        status,
      ]),
    ]),
  ]);
}

function renderDeletedPersonasModal() {
  const close = () => {
    state.deletedPanelOpen = false;
    renderShell();
  };
  return h("div", { class: "profile-modal-backdrop", onclick: (event) => {
    if (event.target.classList.contains("profile-modal-backdrop")) close();
  } }, [
    h("section", { class: "profile-modal deleted-personas-modal" }, [
      h("div", { class: "profile-modal-head" }, [
        h("strong", { text: "已删除的人格" }),
        h("button", { type: "button", class: "ghost compact", text: "关闭", onclick: close }),
      ]),
      h("p", { class: "muted deleted-personas-note", text: "恢复后，TA 和保留的聊天记录会重新回到主界面。" }),
      h("div", { class: "deleted-personas-list" }, state.deletedPersonas.length
        ? state.deletedPersonas.map((persona) => renderDeletedPersonaItem(persona))
        : [h("p", { class: "empty", text: "没有已删除的人格。" })]),
    ]),
  ]);
}

function renderDeletedPersonaItem(persona) {
  const status = h("small", { class: "save-status" });
  return h("div", { class: "deleted-persona-item" }, [
    avatar(persona.name || "忆", persona.avatar_url),
    h("span", {}, [
      h("strong", { text: persona.name || "未命名" }),
      h("small", { text: persona.summary || persona.relationship || "资料仍被保留" }),
      status,
    ]),
    h("div", { class: "deleted-persona-actions" }, [
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "恢复",
        onclick: async () => {
          status.textContent = "";
          try {
            await api(`/api/personas/${persona.id}/restore`, { method: "POST" });
            await loadMainData();
            state.deletedPanelOpen = false;
            state.view = "home";
            renderShell();
          } catch (err) {
            status.textContent = err.message;
          }
        },
      }),
      h("button", {
        type: "button",
        class: "ghost compact danger",
        text: "永久删除",
        onclick: async () => {
          status.textContent = "";
          const confirmName = window.prompt(`永久删除后无法恢复。请输入「${persona.name || ""}」确认。`);
          if (confirmName === null) return;
          try {
            await api(`/api/personas/${persona.id}/purge`, {
              method: "POST",
              body: JSON.stringify({ confirm_name: confirmName }),
            });
            await loadMainData();
            renderShell();
          } catch (err) {
            status.textContent = err.message;
          }
        },
      }),
    ]),
  ]);
}

function renderPersonaRail() {
  const persona = state.activePersona || {};
  const selfUse = selfUseMode();
  if (state.editingPersona) {
    return h("div", { class: "profile-rail" }, [renderPersonaEditForm(persona)]);
  }
  return h("div", { class: "profile-rail" }, [
    h("section", { class: "rail-section" }, [
      h("div", { class: "section-head" }, [
        h("p", { class: "eyebrow", text: selfUse ? "澪的状态档案" : "联系人资料" }),
        h("button", {
          type: "button",
          class: "ghost compact",
          text: "编辑",
          onclick: () => {
            state.editingPersona = true;
            renderShell();
          },
        }),
      ]),
      h("div", { class: "rail-identity" }, [
        selfUse ? null : avatar(persona.name || "忆", persona.avatar_url),
        h("div", {}, [
          h("h3", { text: persona.name || "未命名" }),
          h("small", { text: persona.relationship || (selfUse ? "相处方式尚未定义" : "未设定") }),
        ]),
      ]), 
      detailLine(selfUse ? "说话节奏" : "说话方式", persona.speaking_style || "会在对话中逐步稳定"),
      detailLine(selfUse ? "当前状态" : "摘要", persona.summary || "还在形成中"),
      renderPersonaExpressionPreference(persona),
      renderLive2dPanel(persona),
      renderPersonaGrowth(persona),
      h("details", { class: "persona-more-details" }, [
        h("summary", { text: selfUse ? "形象与运行绑定" : "更多资料" }),
        detailLine("资料版本", `v${persona.version || 1}`),
        detailLine("Live2D 模型", persona.live2d_model_id || "未接入"),
        detailLine("Live2D 预览图", persona.live2d_preview_url || "未设置"),
        detailLine("Fallback 图像", persona.fallback_image_url || persona.avatar_url || "未设置"),
        detailLine("声音档案", persona.voice_profile || "未设置"),
        detailLine("外貌参考", persona.appearance_description || "暂未确定"),
        detailLine("期望形象", persona.desired_image || "暂未确定"),
        detailLine("适配记录", persona.psychological_fit_notes || "从真实对话和明确反馈中逐步校准。"),
        detailLine("成长方向", persona.growth_notes || profileList(persona.psychological_profile?.growth_direction) || "由对话、记忆和明确反馈逐步形成。"),
      ]),
    ]),
  ]);
}

function expressionPreferenceEnabled(persona) {
  return persona?.expression_preference?.enabled !== false;
}

function expressionPreferenceMode(persona) {
  if (!expressionPreferenceEnabled(persona)) return "off";
  return persona?.expression_preference?.mode || "normal";
}

function applyPersonaExpressionPreference(personaId, preference) {
  const update = (persona) => (
    Number(persona.id) === Number(personaId)
      ? { ...persona, expression_preference: preference }
      : persona
  );
  state.personas = state.personas.map(update);
  if (state.activePersona && Number(state.activePersona.id) === Number(personaId)) {
    state.activePersona = update(state.activePersona);
  }
}

function renderPersonaExpressionPreference(persona) {
  const mode = expressionPreferenceMode(persona);
  const enabled = mode !== "off";
  const status = h("small", { class: "save-status" });
  const modeCopy = {
    off: "已关闭：聊天回复不会再显示轻表达标签。",
    subtle: "克制显示：只在明显需要承接情绪时出现。",
    normal: "正常显示：合适时显示微笑、轻声、点头这类克制提示。",
  };
  const options = [
    ["off", "关闭"],
    ["subtle", "克制"],
    ["normal", "正常"],
  ];
  return h("section", { class: `persona-expression-card ${enabled ? "enabled" : "disabled"}` }, [
    h("div", {}, [
      h("strong", { text: "轻表达" }),
      h("p", {
        text: modeCopy[mode] || modeCopy.normal,
      }),
    ]),
    h("div", { class: "segmented-control expression-mode-control" }, options.map(([value, label]) => h("button", {
      type: "button",
      class: value === mode ? "active" : "",
      text: label,
      disabled: value === mode ? "disabled" : null,
      onclick: async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        status.textContent = "正在保存...";
        try {
          const data = await api(`/api/personas/${persona.id}/expression-preference`, {
            method: "PATCH",
            body: JSON.stringify({ mode: value }),
          });
          applyPersonaExpressionPreference(persona.id, data.expression_preference || {
            enabled: value !== "off",
            mode: value,
            explicit: true,
          });
          renderShell();
        } catch (err) {
          button.disabled = false;
          status.textContent = err.message;
        }
      },
    }))),
    status,
  ]);
}

function renderPersonaGrowth(persona) {
  const selfUse = selfUseMode();
  const personaId = Number(persona.id);
  const growth = state.personaGrowth[personaId];
  const loading = Number(state.loadingGrowthPersonaId) === personaId && !growth;
  const signals = Array.isArray(growth?.signals) ? growth.signals : [];
  const latestChange = growth?.latest_reviewed_change;
  const reviewedChanges = Array.isArray(growth?.reviewed_changes) ? growth.reviewed_changes : [];
  const preferenceRequests = Array.isArray(growth?.preference_requests) ? growth.preference_requests : [];
  return h("section", { class: "persona-growth-glimpse" }, [
    h("div", { class: "persona-growth-head" }, [
      h("strong", { text: selfUse ? "连续成长" : "相处痕迹" }),
      growth?.version ? h("small", { text: `v${growth.version}` }) : null,
    ]),
    h("p", { class: "persona-growth-title", text: loading ? "正在整理最近的变化..." : growth?.headline || (selfUse ? "澪会从真实互动中慢慢形成连续性" : "你们的相处还在慢慢形成") }),
    !loading && signals.length
      ? h("div", { class: "persona-growth-signals" }, signals.map((signal) => h("div", { class: `persona-growth-signal ${signal.kind || ""}` }, [
        h("div", { class: "persona-growth-signal-head" }, [
          h("span", { text: signal.title || "相处变化" }),
          signal.created_at ? h("small", { text: `确认于 ${formatListTime(signal.created_at)}` }) : null,
        ]),
        h("p", { text: signal.text || "" }),
      ])))
      : null,
    latestChange ? renderGrowthFeedback(personaId, latestChange, growth?.feedback_error) : null,
    renderPreferenceRequest(personaId, preferenceRequests, growth?.request_notice, growth?.request_error),
    reviewedChanges.length ? renderReviewedChangeHistory(reviewedChanges) : null,
    h("p", {
      class: "persona-growth-hint",
      text: selfUse
        ? "可以直接说“回复短一点”“少追问”或“先听我说完”；明确反馈会进入连续记忆，不需要先给澪套关系或人格模板。"
        : "想调整相处方式，可以直接说“回复短一点”“少追问”或“先听我说完”；明确反馈会更新并留记录。",
    }),
  ]);
}

function renderPreferenceRequest(personaId, requests, notice = "", errorText = "") {
  const selfUse = selfUseMode();
  const editable = requests.find((request) => (
    request.status === "active_guidance" && request.can_withdraw && request.origin === "direct_entry"
  ));
  const input = h("textarea", {
    rows: "2",
    maxlength: "500",
    placeholder: "例如：难过时先陪我一会儿，不要马上分析原因",
  }, editable?.detail || "");
  const statusText = {
    active_guidance: "当前生效",
    waiting_review: "已转为自动适配",
    confirmed: "已形成变化",
    not_applied: "本次未形成变化",
    needs_review_again: "已转为自动适配",
    withdrawn: "已撤回",
    stopped_in_chat: "已在聊天中停止",
    superseded: "已被更新偏好替代",
    recorded: "已记下",
  };
  return h("section", { class: "persona-growth-request" }, [
    h("strong", { text: selfUse ? "告诉澪你的边界或节奏" : "直接告诉 TA 怎么陪你" }),
    h("p", { text: selfUse ? "这里记录明确反馈，不要求你预先设计澪的人格或关系。" : "你写下的主动偏好会立即影响 TA 的回应方式；与变化反馈形成的补充指导可同时生效，也可分别停止。" }),
    input,
    h("button", {
      type: "button",
      class: "ghost compact",
      text: editable ? "更新当前反馈" : (selfUse ? "交给澪记住" : "让 TA 按这样回应"),
      onclick: () => submitPreferenceRequest(personaId, input.value),
    }),
    notice ? h("small", { text: notice }) : null,
    errorText ? h("small", { class: "error", text: errorText }) : null,
    requests.length ? h("details", { class: "persona-growth-request-history" }, [
      h("summary", { text: `我提交过的偏好（${requests.length}）` }),
      h("div", {}, requests.map((request) => h("article", {}, [
        h("div", {}, [
          h("small", { text: formatListTime(request.updated_at || request.created_at) }),
          h("span", { text: statusText[request.status] || statusText.recorded }),
          request.origin === "growth_feedback"
            ? h("span", { text: `来自 v${request.source_reviewed_version || "?"} 的调整反馈` })
            : request.origin === "chat_feedback"
              ? h("span", { text: "聊天中明确提出" })
              : h("span", { text: "主动设置" }),
        ]),
        h("p", { text: request.detail }),
        request.deactivation_reason ? h("small", { text: request.deactivation_reason }) : null,
        request.result ? h("section", { class: "persona-growth-request-result" }, [
          h("strong", { text: `已在 v${request.result.version} 形成变化` }),
          h("p", { text: (request.result.highlights || []).join("；") || "相处方式完成了一次轻微调整" }),
        ]) : null,
        request.can_retry ? h("button", {
          type: "button",
          class: "ghost compact",
          text: "重新启用",
          onclick: () => retryPreferenceRequest(personaId, request.id),
        }) : null,
        request.can_withdraw ? h("button", {
          type: "button",
          class: "ghost compact",
          text: "停止这条偏好",
          onclick: () => withdrawPreferenceRequest(personaId, request.id),
        }) : null,
      ]))),
    ]) : null,
  ]);
}

function renderReviewedChangeHistory(changes) {
  return h("details", { class: "persona-growth-history" }, [
    h("summary", { text: `已确认变化记录（${changes.length}）` }),
    h("div", { class: "persona-growth-history-list" }, changes.map((change) => h("article", { class: "persona-growth-history-item" }, [
      h("div", { class: "persona-growth-history-head" }, [
        h("strong", { text: `v${change.version}` }),
        change.created_at ? h("small", { text: formatListTime(change.created_at) }) : null,
      ]),
      h("p", { text: (change.highlights || []).join("；") || "相处方式完成了一次轻微调整" }),
      change.feedback?.reaction
        ? h("small", {
            text: change.feedback.reaction === "helpful"
              ? "你的反馈：这样更合适"
              : `你的反馈：还想调整 · ${change.feedback.followup_status === "completed"
                ? `已自动采用${change.feedback.followed_up_at ? `（${formatListTime(change.feedback.followed_up_at)}）` : ""}`
                : "写下具体方式即可自动调整"}`,
          })
        : null,
    ]))),
  ]);
}

async function submitPreferenceRequest(personaId, detail) {
  const value = String(detail || "").trim();
  const growth = state.personaGrowth[personaId] || {};
  if (!value) {
    state.personaGrowth[personaId] = { ...growth, request_error: "请先写下希望调整的相处方式。" };
    renderShell();
    return;
  }
  try {
    await api(`/api/personas/${personaId}/growth/requests`, {
      method: "POST",
      body: JSON.stringify({ detail: value }),
    });
    const data = await api(`/api/personas/${personaId}/growth`);
    state.personaGrowth[personaId] = {
      ...data.growth,
      request_notice: "已生效，TA 接下来的回应会参考这条偏好。",
      request_error: "",
    };
  } catch (err) {
    state.personaGrowth[personaId] = { ...growth, request_error: err.message, request_notice: "" };
  }
  renderShell();
}

async function withdrawPreferenceRequest(personaId, requestId) {
  const growth = state.personaGrowth[personaId] || {};
  try {
    await api(`/api/personas/${personaId}/growth/requests/${requestId}/withdraw`, { method: "POST" });
    const data = await api(`/api/personas/${personaId}/growth`);
    state.personaGrowth[personaId] = {
      ...data.growth,
      request_notice: "已停止，接下来的回应不再使用这条偏好。",
      request_error: "",
    };
    clearGrowthAction(personaId);
  } catch (err) {
    state.personaGrowth[personaId] = { ...growth, request_error: err.message, request_notice: "" };
  }
  renderShell();
}

async function retryPreferenceRequest(personaId, requestId) {
  const growth = state.personaGrowth[personaId] || {};
  try {
    await api(`/api/personas/${personaId}/growth/requests/${requestId}/retry`, { method: "POST" });
    const data = await api(`/api/personas/${personaId}/growth`);
    state.personaGrowth[personaId] = {
      ...data.growth,
      request_notice: "已重新启用，TA 接下来的回应会参考这条偏好。",
      request_error: "",
    };
    clearGrowthAction(personaId);
  } catch (err) {
    state.personaGrowth[personaId] = { ...growth, request_error: err.message, request_notice: "" };
  }
  renderShell();
}

function renderGrowthFeedback(personaId, latestChange, errorText = "") {
  const reaction = latestChange.feedback?.reaction || "";
  const followupCompleted = reaction === "needs_adjustment"
    && latestChange.feedback?.followup_status === "completed";
  const detailInput = reaction === "needs_adjustment"
    ? h("textarea", {
        rows: "2",
        maxlength: "500",
        placeholder: "例如：还是太爱追问，或者安慰时说得太满了",
      }, latestChange.feedback?.detail_text || "")
    : null;
  const message = reaction === "helpful"
    ? "已记下：这次变化更适合你。"
    : reaction === "needs_adjustment"
      ? followupCompleted
        ? `这条反馈已于 ${formatListTime(latestChange.feedback.followed_up_at)} 自动加入当前回应方式；继续补充会即时更新。`
        : latestChange.feedback?.detail_text
          ? "补充已自动加入当前回应方式。"
          : "已记下。写出具体想法后，会自动调整接下来的回应方式。"
      : "";
  return h("section", { class: "persona-growth-feedback" }, [
    h("p", { text: "这次确认后的变化，感觉怎么样？" }),
    h("div", { class: "persona-growth-feedback-actions" }, [
      h("button", {
        type: "button",
        class: `ghost compact ${reaction === "helpful" ? "selected" : ""}`.trim(),
        text: "这样更合适",
        onclick: () => submitGrowthFeedback(personaId, "helpful"),
      }),
      h("button", {
        type: "button",
        class: `ghost compact ${reaction === "needs_adjustment" ? "selected" : ""}`.trim(),
        text: "还想调整",
        onclick: reaction === "needs_adjustment" ? null : () => submitGrowthFeedback(personaId, "needs_adjustment"),
      }),
    ]),
    detailInput ? h("label", { class: "persona-growth-feedback-detail" }, [
      h("span", { text: "具体想调整什么（可选）" }),
      detailInput,
      h("button", {
        type: "button",
        class: "ghost compact",
        text: followupCompleted ? "补充并重新提交" : "保存补充",
        onclick: () => submitGrowthFeedback(personaId, "needs_adjustment", detailInput.value),
      }),
    ]) : null,
    message ? h("small", { text: message }) : null,
    errorText ? h("small", { class: "error", text: errorText }) : null,
  ]);
}

async function submitGrowthFeedback(personaId, reaction, detail = "") {
  const growth = state.personaGrowth[personaId];
  if (!growth?.latest_reviewed_change) return;
  try {
    const data = await api(`/api/personas/${personaId}/growth/feedback`, {
      method: "POST",
      body: JSON.stringify({ reaction, detail }),
    });
    state.personaGrowth[personaId] = {
      ...growth,
      feedback_error: "",
      latest_reviewed_change: { ...growth.latest_reviewed_change, feedback: data.feedback },
      reviewed_changes: (growth.reviewed_changes || []).map((change) => (
        Number(change.version) === Number(data.feedback.reviewed_version)
          ? {
              ...change,
              feedback: data.feedback.reaction === "needs_adjustment"
                ? {
                    reaction: data.feedback.reaction,
                    followup_status: data.feedback.followup_status || "waiting",
                  }
                : { reaction: data.feedback.reaction },
            }
          : change
      )),
    };
  } catch (err) {
    state.personaGrowth[personaId] = { ...growth, feedback_error: err.message };
  }
  renderShell();
}

function detailLine(label, value) {
  return h("div", { class: "detail-line" }, [h("span", { text: label }), h("p", { text: value })]);
}

function renderSelfUseEmbodimentEditor(persona, fields) {
  const embodiment = personaEmbodimentProfile(persona);
  const bindingStatus = h("small", { class: "save-status" });
  const saveBinding = () => saveSelfUseEmbodimentBinding({
    live2d_model_id: fields.live2dModelId.value,
    live2d_preview_url: fields.live2dPreviewUrl.value,
    fallback_image_url: fields.fallbackImageUrl.value,
    voice_profile: fields.voiceProfile.value,
  }, bindingStatus);
  const previewUpload = renderSelfUseEmbodimentImageUpload(
    "预览图",
    "preview",
    fields.live2dPreviewUrl,
    bindingStatus,
  );
  const fallbackUpload = renderSelfUseEmbodimentImageUpload(
    "fallback 图",
    "fallback",
    fields.fallbackImageUrl,
    bindingStatus,
  );
  return h("section", { class: "self-use-embodiment-editor" }, [
    h("div", { class: "self-use-embodiment-editor-head" }, [
      h("div", {}, [
        h("p", { class: "eyebrow", text: "Embodiment binding" }),
        h("strong", { text: "澪的形象与声音" }),
      ]),
      h("span", {
        class: `companion-mode-pill ${embodiment.live2dModelId || embodiment.voiceProfile ? "ok" : "off"}`,
        text: embodiment.live2dModelId || embodiment.voiceProfile ? "已填写部分绑定" : "等待绑定",
      }),
    ]),
    h("div", { class: "self-use-embodiment-preview" }, [
      h("div", { class: `self-use-embodiment-preview-visual ${embodiment.visualTone}` }, [
        embodiment.visualUrl
          ? h("img", { src: embodiment.visualUrl, alt: persona?.name || "LING companion preview" })
          : h("div", { class: "self-use-embodiment-placeholder" }, [
              h("strong", { text: "Live2D" }),
              h("small", { text: "No preview" }),
            ]),
        h("span", { class: `companion-visual-source ${embodiment.visualTone}`, text: embodiment.visualLabel }),
      ]),
      h("div", {}, [
        h("small", { class: "muted", text: "静态图只作为 Live2D 未连接时的 preview / fallback。" }),
        h("small", { class: "muted", text: "实时视频、麦克风和视觉理解仍由外部 Video Companion 负责。" }),
      ]),
    ]),
    h("div", { class: "self-use-embodiment-grid" }, [
      h("label", {}, ["Live2D 模型 ID", fields.live2dModelId]),
      h("div", { class: "embodiment-image-field" }, [
        h("label", {}, ["Live2D 预览图 URL", fields.live2dPreviewUrl]),
        previewUpload,
      ]),
      h("div", { class: "embodiment-image-field" }, [
        h("label", {}, ["Fallback 图像 URL", fields.fallbackImageUrl]),
        fallbackUpload,
      ]),
      h("label", {}, ["Provider voice ID", fields.voiceProfile]),
    ]),
    h("div", { class: "self-use-embodiment-actions" }, [
      h("button", { type: "button", class: "compact", text: "保存形象绑定", onclick: saveBinding }),
      bindingStatus,
    ]),
    renderSelfUseLive2dModelPicker(fields.live2dModelId, bindingStatus),
    renderSelfUseMappingPreview(),
  ]);
}

function renderSelfUseEmbodimentImageUpload(label, kind, urlField, statusEl) {
  const input = h("input", {
    type: "file",
    accept: "image/png,image/jpeg,image/webp,image/gif",
    class: "embodiment-image-file",
    "aria-label": `上传${label}`,
  });
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    statusEl.textContent = `正在上传${label}...`;
    try {
      const url = await uploadEmbodimentImageFile(file, kind);
      urlField.value = url;
      await saveSelfUseEmbodimentBinding({
        [kind === "preview" ? "live2d_preview_url" : "fallback_image_url"]: url,
      }, statusEl);
    } catch (err) {
      statusEl.textContent = err.message || "上传失败";
    } finally {
      input.value = "";
    }
  });
  return h("label", { class: "embodiment-image-upload" }, [
    h("span", { class: "ghost compact upload-label", text: `上传${label}` }),
    input,
  ]);
}

function live2dCurrentModelBinding() {
  const current = state.live2dStatus?.current_model || {};
  const modelId = String(current.modelID || current.modelName || current.vtsModelName || current.modelFileName || "").trim();
  const label = [current.modelName || current.vtsModelName || current.modelFileName || "", current.modelID || ""]
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .join(" / ");
  return {
    id: modelId,
    label,
    loaded: current.modelLoaded !== false,
  };
}

function renderSelfUseLive2dModelPicker(live2dModelIdField, statusEl = null) {
  const current = live2dCurrentModelBinding();
  const count = Number(state.live2dStatus?.available_model_count || 0);
  const statusText = live2dConnected()
    ? current.label
      ? `VTube Studio 当前模型：${current.label}`
      : "已连接 VTube Studio，但没有读取到已加载模型"
    : live2dAvailable()
      ? "Live2D 已启用，先连接 VTube Studio 后可读取当前模型"
      : "Live2D 未启用，仍可先手动填写模型 ID";
  return h("section", { class: "self-use-live2d-model-picker" }, [
    h("div", {}, [
      h("strong", { text: "VTube Studio 当前模型" }),
      h("small", { class: "muted", text: count ? `${statusText} · ${count} models` : statusText }),
    ]),
    h("button", {
      type: "button",
      class: "ghost compact",
      text: "使用并保存当前模型",
      disabled: current.id ? null : "disabled",
      onclick: async () => {
        live2dModelIdField.value = current.id;
        live2dModelIdField.focus();
        await saveSelfUseEmbodimentBinding({ live2d_model_id: current.id }, statusEl);
      },
    }),
    live2dConnected() ? h("button", {
      type: "button",
      class: "ghost compact",
      text: "刷新当前模型",
      onclick: () => live2dRefreshCapabilities(statusEl),
    }) : null,
  ]);
}

async function saveSelfUseEmbodimentBinding(payload, statusEl = null) {
  if (!selfUseMode() || !state.activePersona?.id) return;
  if (statusEl) statusEl.textContent = "保存中...";
  try {
    const data = await api(`/api/personas/${state.activePersona.id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    applyUpdatedPersona(data.persona);
    await refreshEmbodimentRuntimeStatus();
    if (statusEl) statusEl.textContent = "已保存";
    renderShell();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message || "保存失败";
  }
}

function applyUpdatedPersona(persona) {
  if (!persona) return;
  state.activePersona = persona;
  delete state.personaGrowth[Number(persona.id)];
  state.personas = state.personas.map((item) => (
    Number(item.id) === Number(persona.id) ? persona : item
  ));
  state.conversations = state.conversations.map((item) => (
    Number(item.persona_id) === Number(persona.id)
      ? { ...item, persona_name: persona.name, persona_avatar_url: persona.avatar_url }
      : item
  ));
  state.archivedConversations = state.archivedConversations.map((item) => (
    Number(item.persona_id) === Number(persona.id)
      ? { ...item, persona_name: persona.name, persona_avatar_url: persona.avatar_url }
      : item
  ));
}

function renderSelfUseMappingPreview() {
  const actions = state.companionStatus?.live2d_actions || {};
  const expressionMap = actions.expression_map && typeof actions.expression_map === "object" ? actions.expression_map : {};
  const runtimeRows = [
    ["Idle", actions.idle_expression || "Default"],
    ["Listen", actions.listening_expression || "Listening"],
    ["Think", actions.thinking_expression || "Thinking"],
    ["Talk", actions.speaking_expression || "Talking"],
  ];
  const expressionRows = Object.entries(expressionMap).slice(0, 8);
  return h("section", { class: "self-use-mapping-preview" }, [
    h("div", { class: "self-use-mapping-head" }, [
      h("strong", { text: "Live2D 状态映射" }),
      h("small", { text: `${Object.keys(expressionMap).length} expression map` }),
    ]),
    h("div", { class: "self-use-runtime-map" }, runtimeRows.map(([label, value]) => (
      h("span", {}, [
        h("small", { text: label }),
        h("strong", { text: value }),
      ])
    ))),
    expressionRows.length
      ? h("div", { class: "self-use-expression-map" }, expressionRows.map(([label, target]) => (
          h("span", {}, [
            h("small", { text: label }),
            h("strong", { text: String(target || "") }),
          ])
        )))
      : h("small", { class: "muted", text: "还没有配置表情标签到 Live2D 表达的映射。" }),
  ]);
}

function renderPersonaEditForm(persona) {
  const selfUse = selfUseMode();
  const name = h("input", { name: "name", value: persona.name || "", maxlength: "40", placeholder: selfUse ? "澪" : "给 TA 起个名字" });
  const summary = h("textarea", {
    name: "summary",
    rows: "3",
    maxlength: "1000",
    placeholder: selfUse ? "可留空；只写你已经确认的状态" : "TA 给你的整体感觉，或者你希望别人怎么理解 TA",
  }, persona.summary || "");
  const relationship = h("input", {
    name: "relationship",
    value: persona.relationship || "",
    maxlength: "120",
    placeholder: selfUse ? "可留空；只记录真实形成的相处方式" : "朋友、恋人、倾听者、搭档...",
  });
  const speakingStyle = h("textarea", {
    name: "speaking_style",
    rows: "3",
    maxlength: "300",
    placeholder: selfUse ? "可留空；也可以写短句、少追问等明确反馈" : "短句、少说教、会吐槽、温柔一点...",
  }, persona.speaking_style || "");
  const avatarFile = h("input", { name: "avatar_file", type: "file", accept: "image/png,image/jpeg,image/webp,image/gif" });
  const avatarUrl = h("input", { name: "avatar_url", value: persona.avatar_url || "", placeholder: "兼容旧头像：/uploads/... 或 https://..." });
  const live2dModelId = h("input", {
    name: "live2d_model_id",
    value: persona.live2d_model_id || "",
    maxlength: "120",
    placeholder: "例如 mio-main 或 VTube Studio 模型名",
  });
  const live2dPreviewUrl = h("input", {
    name: "live2d_preview_url",
    value: persona.live2d_preview_url || "",
    maxlength: "500",
    placeholder: "Live2D 未连接时显示的预览图 URL",
  });
  const fallbackImageUrl = h("input", {
    name: "fallback_image_url",
    value: persona.fallback_image_url || "",
    maxlength: "500",
    placeholder: "Live2D 和预览图都不可用时的 fallback 图",
  });
  const voiceProfile = h("input", {
    name: "voice_profile",
    value: persona.voice_profile || "",
    maxlength: "200",
    placeholder: "例如 marin 或 voice_...；留空使用 provider 默认声音",
  });
  const appearance = h("textarea", {
    name: "appearance_description",
    rows: "4",
    maxlength: "2000",
    placeholder: selfUse ? "澪目前的形象气质参考" : "TA 目前给人的外貌或气质参考",
  }, persona.appearance_description || "");
  const desired = h("textarea", {
    name: "desired_image",
    rows: "4",
    maxlength: "2000",
    placeholder: selfUse ? "你希望澪的 Live2D 身体呈现什么方向" : "你希望 TA 的头像/形象大概是什么感觉",
  }, persona.desired_image || "");
  const status = h("small", { class: "save-status" });
  const deleteStatus = h("small", { class: "save-status danger-text" });
  const deleteConfirm = h("input", {
    name: "delete_confirm_name",
    maxlength: "40",
    placeholder: `输入“${persona.name || "未命名"}”确认删除`,
    autocomplete: "off",
  });
  const deleteButton = h("button", {
    type: "button",
    class: "danger-button",
    text: selfUseMode() ? "删除已禁用" : "删除陪伴体",
    disabled: "disabled",
    onclick: async () => {
      deleteStatus.textContent = "";
      try {
        await api(`/api/personas/${persona.id}/delete`, {
          method: "POST",
          body: JSON.stringify({ confirm_name: deleteConfirm.value }),
        });
        state.personaPanelOpen = false;
        state.threadPanelOpen = false;
        state.editingPersona = false;
        state.activePersona = null;
        state.activeConversationId = null;
        state.messages = [];
        try {
          localStorage.removeItem(lastActiveKey());
        } catch {
          // Local storage may be unavailable in restricted browser modes.
        }
        await loadMainData();
        state.view = state.personas.length ? "home" : "forge";
        renderShell();
      } catch (err) {
        deleteStatus.textContent = err.message;
      }
    },
  });
  deleteConfirm.addEventListener("input", () => {
    const matched = deleteConfirm.value.trim() === String(persona.name || "").trim();
    if (matched) deleteButton.removeAttribute("disabled");
    else deleteButton.setAttribute("disabled", "disabled");
  });

  return h("section", { class: "rail-section" }, [
    h("div", { class: "section-head" }, [
      h("p", { class: "eyebrow", text: selfUseMode() ? "澪的资料" : "陪伴体资料" }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "取消",
        onclick: () => {
          state.editingPersona = false;
          renderShell();
        },
      }),
    ]),
    h("form", {
      class: "persona-edit-form",
      onsubmit: async (event) => {
        event.preventDefault();
        status.textContent = "";
        try {
          let avatarValue = selfUseMode() ? persona.avatar_url || "" : avatarUrl.value;
          if (!selfUseMode() && avatarFile.files?.[0]) {
            status.textContent = "正在上传头像...";
            avatarValue = await uploadAvatarFile(avatarFile.files[0]);
          }
          const data = await api(`/api/personas/${persona.id}`, {
            method: "PATCH",
            body: JSON.stringify({
              name: name.value,
              summary: summary.value,
              relationship: relationship.value,
              speaking_style: speakingStyle.value,
              avatar_url: avatarValue,
              appearance_description: appearance.value,
              desired_image: desired.value,
              live2d_model_id: live2dModelId.value,
              live2d_preview_url: live2dPreviewUrl.value,
              fallback_image_url: fallbackImageUrl.value,
              voice_profile: voiceProfile.value,
            }),
          });
          applyUpdatedPersona(data.persona);
          await refreshEmbodimentRuntimeStatus();
          state.editingPersona = false;
          state.personaPanelOpen = false;
          renderShell();
        } catch (err) {
          status.textContent = err.message;
        }
      },
    }, [
      selfUseMode()
        ? renderSelfUseEmbodimentEditor(persona, {
            live2dModelId,
            live2dPreviewUrl,
            fallbackImageUrl,
            voiceProfile,
          })
        : null,
      h("label", {}, ["名字", name]),
      h("label", {}, [selfUse ? "相处方式（可留空）" : "关系定位", relationship]),
      h("label", {}, [selfUse ? "说话节奏（可留空）" : "说话方式", speakingStyle]),
      h("label", {}, [selfUse ? "当前状态（可留空）" : "摘要", summary]),
      h("details", { class: "persona-edit-more" }, [
        h("summary", { text: selfUse ? "形象补充" : "形象与更多资料" }),
        ...(!selfUseMode() ? [
          h("label", {}, ["Live2D 模型 ID", live2dModelId]),
          h("label", {}, ["Live2D 预览图", live2dPreviewUrl]),
          h("label", {}, ["Fallback 图像", fallbackImageUrl]),
          h("label", {}, ["声音档案", voiceProfile]),
        ] : []),
        ...(!selfUseMode() ? [
          h("label", {}, ["兼容头像上传", avatarFile]),
          h("label", {}, ["兼容头像链接", avatarUrl]),
        ] : []),
        h("label", {}, [selfUseMode() ? "形象气质参考" : "外貌参考", appearance]),
        h("label", {}, [selfUseMode() ? "Live2D 身体方向" : "期望形象", desired]),
      ]),
      h("div", { class: "actions rail-actions" }, [
        h("button", { type: "submit", text: "保存" }),
        h("button", {
          type: "button",
          class: "ghost",
          text: "取消",
          onclick: () => {
            state.editingPersona = false;
            renderShell();
          },
        }),
      ]),
      status,
      selfUseMode() ? null : h("details", { class: "persona-danger-zone" }, [
        h("summary", { text: "删除这个陪伴体" }),
        h("p", { text: "删除后，TA 和相关聊天会从你的主界面隐藏。记忆与版本历史暂时保留，以便后续支持恢复或数据处理。" }),
        h("label", {}, ["输入名字确认", deleteConfirm]),
        deleteButton,
        deleteStatus,
      ]),
    ]),
  ]);
}

function profileList(value) {
  if (!Array.isArray(value) || !value.length) return "";
  return value.join("；");
}

function selectControl(values, selectedValue, labels = values) {
  const select = h("select");
  values.forEach((value, index) => {
    const option = h("option", { value, text: labels[index] ?? value });
    if (String(value) === String(selectedValue || "")) option.selected = true;
    select.append(option);
  });
  return select;
}

function yearOptions() {
  const current = new Date().getFullYear();
  const years = [];
  for (let year = current; year >= 1920; year -= 1) years.push(String(year));
  return years;
}

function rangeOptions(start, end) {
  const values = [];
  for (let value = start; value <= end; value += 1) values.push(String(value).padStart(2, "0"));
  return values;
}

function parseBirthday(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return { year: "", month: "", day: "" };
  return { year: match[1], month: match[2], day: match[3] };
}

function buildBirthday(year, month, day) {
  if (!year || !month || !day) return "";
  return `${year}-${month}-${day}`;
}

function daysInMonth(year, month) {
  if (!year || !month) return 31;
  return new Date(Number(year), Number(month), 0).getDate();
}

function isAdmin() {
  return state.user?.role === "admin";
}

function renderWizard() {
  const selections = {};
  for (const key of Object.keys(state.options || {})) selections[key] = [];

  const panel = h("section", { class: "wizard" });
  const groups = h("div", { class: "wizard-groups" });
  const description = h("textarea", {
    rows: "6",
    maxlength: "2000",
    placeholder: "可以写：我想和一个冷静、不说教、但会记得我的人聊天。也可以写 TA 给你的感觉、希望的形象，或者你不喜欢怎样被关心。",
  });

  for (const [key, values] of forgeGroups()) {
    const group = h("div", { class: "option-group" }, [
      h("div", { class: "option-title" }, [
        h("h3", { text: groupTitle(key) }),
        h("small", { text: groupHint(key) }),
      ]),
    ]);
    for (const value of values) {
      const chip = h("button", {
        type: "button",
        class: "chip",
        text: value,
        onclick: () => {
          const selected = selections[key];
          const idx = selected.indexOf(value);
          if (idx >= 0) selected.splice(idx, 1);
          else if (selected.length < 2) selected.push(value);
          chip.classList.toggle("active", selected.includes(value));
        },
      });
      group.append(chip);
    }
    groups.append(group);
  }

  const starterList = h("div", { class: "starter-list" });
  for (const prompt of starterPrompts) {
    starterList.append(
      h("button", {
        type: "button",
        class: "starter-chip",
        text: prompt,
        onclick: () => appendDescriptionLine(description, prompt),
      })
    );
  }

  const error = h("p", { class: "error" });
  const fallbackName = h("input", {
    maxlength: "40",
    placeholder: "给 TA 写下一个名字",
    autocomplete: "off",
  });
  const namingFallback = h("section", { class: "naming-fallback", hidden: "hidden" }, [
    h("strong", { text: "这次没有取得合适的名字" }),
    h("p", { class: "muted", text: "可以再次生成，也可以由你先写下一个名字，之后仍然可以在资料里修改。" }),
    h("div", { class: "naming-fallback-actions" }, [
      fallbackName,
      h("button", {
        type: "button",
        class: "ghost",
        text: "用这个名字创建",
        onclick: () => {
          const preferredName = fallbackName.value.trim();
          if (!preferredName) {
            error.textContent = "先写下一个名字，或者点击直接生成再次尝试。";
            fallbackName.focus();
            return;
          }
          submitPersona(preferredName);
        },
      }),
    ]),
  ]);
  async function submitPersona(preferredName = "") {
    create.disabled = true;
    create.textContent = text.waiting;
    error.textContent = "";
    try {
      const data = await api("/api/personas", {
        method: "POST",
        body: JSON.stringify({ selections, description: description.value, preferred_name: preferredName || null }),
      });
      state.personas = [data.persona, ...state.personas.filter((item) => Number(item.id) !== Number(data.persona.id))];
      state.activePersona = data.persona;
      state.activeConversationId = null;
      state.messages = [];
      state.view = "chat";
      state.editingPersona = false;
      state.personaPanelOpen = false;
      state.focusComposer = true;
      renderShell();
    } catch (err) {
      error.textContent = err.message;
      if (err.message.includes("没有取得合适的名字")) {
        namingFallback.removeAttribute("hidden");
        fallbackName.focus();
      }
      create.disabled = false;
      create.textContent = text.directGenerate;
    }
  }
  const create = h("button", {
    type: "button",
    text: text.directGenerate,
    onclick: () => submitPersona(),
  });

  const actions = [create];
  if (state.activePersona) {
    actions.push(
      h("button", {
        type: "button",
        class: "ghost",
        text: "返回主界面",
        onclick: returnToHome,
      })
    );
  }

  const topbar = h("div", { class: "view-topbar" }, [
    state.activePersona
      ? h("button", {
          type: "button",
          class: "ghost compact",
          text: "返回",
          onclick: () => {
            state.view = "home";
            state.editingPersona = false;
            state.personaPanelOpen = false;
            renderShell();
          },
        })
      : h("span", { class: "topbar-placeholder" }),
    state.deletedPersonas.length
      ? h("button", {
          type: "button",
          class: "ghost compact",
          text: "已删除",
          onclick: () => {
            state.deletedPanelOpen = true;
            renderShell();
          },
        })
      : null,
  ]);

  panel.append(
    topbar,
    h("div", { class: "wizard-copy" }, [
      h("p", { class: "eyebrow", text: "初次相遇" }),
      h("h2", { text: text.wizardTitle }),
      h("p", {
        class: "muted",
        text: "点一两个感觉对的提示就够，也可以直接写下期待。第一次见面不必定义清楚，相处中 TA 会更贴近你的节奏。",
      }),
    ]),
    groups,
    h("section", { class: "free-text" }, [
      h("div", { class: "section-head" }, [
        h("strong", { text: text.optionalDescription }),
        h("small", { text: "可空" }),
      ]),
      starterList,
      description,
    ]),
    namingFallback,
    h("div", { class: "actions" }, actions),
    error
  );

  return panel;
}

function appendDescriptionLine(description, value) {
  description.value = description.value.trim() ? `${description.value.trim()}\n${value}` : value;
  description.focus();
}

function forgeGroups() {
  const options = state.options || {};
  return ["atmosphere", "relationship", "style", "boundaries"].map((key) => [key, (options[key] || []).slice(0, 4)]);
}

function renderComposer() {
  const llmBlocked = chatInputBlocked();
  const input = h("textarea", {
    rows: "1",
    maxlength: "8000",
    placeholder: llmBlocked ? llmStatusText() : text.messagePlaceholder,
    disabled: llmBlocked ? "disabled" : null,
  });
  const button = h("button", {
    type: "submit",
    text: llmBlocked ? "未连接" : state.sending && state.view !== "group" ? "打断并发送" : text.send,
    disabled: llmBlocked || (state.sending && state.view === "group") ? "disabled" : null,
  });
  const form = h("form", { class: "composer" }, [input, button]);
  input.value = loadDraft();
  if (selfUseMode()) state.composerDraft = input.value.trim();
  requestAnimationFrame(() => {
    autoResizeTextarea(input);
    if (state.focusComposer) {
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      state.focusComposer = false;
      state.composerFocused = true;
      refreshRuntimeIndicators();
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content || llmBlocked || (state.sending && state.view === "group")) return;
    if (state.view === "group" && !state.activeGroupConversationId) return;
    if (state.view !== "group" && !state.activePersona) return;
    input.value = "";
    clearDraft();
    autoResizeTextarea(input);
    if (state.view === "group") await sendGroupChatMessage(content);
    else await sendChatMessage(content);
  });
  input.addEventListener("focus", () => {
    state.composerFocused = true;
    state.composerDraft = input.value.trim();
    refreshRuntimeIndicators();
  });
  input.addEventListener("blur", () => {
    state.composerFocused = false;
    state.composerDraft = input.value.trim();
    refreshRuntimeIndicators();
  });
  input.addEventListener("input", () => {
    saveDraft(input.value);
    state.composerDraft = input.value.trim();
    autoResizeTextarea(input);
    refreshRuntimeIndicators();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  return form;
}

function draftKey() {
  if (state.view === "group") {
    const groupId = state.activeGroupConversationId || "new";
    return `mnemosyne:group-draft:${groupId}`;
  }
  const personaId = state.activePersona?.id || "none";
  const conversationId = state.activeConversationId || "new";
  return `mnemosyne:draft:${personaId}:${conversationId}`;
}

function loadDraft() {
  try {
    return localStorage.getItem(draftKey()) || "";
  } catch {
    return "";
  }
}

function saveDraft(value) {
  try {
    const key = draftKey();
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // Local storage may be unavailable in restricted browser modes.
  }
}

function setComposerDraft(value) {
  saveDraft(value);
  state.focusComposer = true;
  renderShell();
}

function clearDraft() {
  try {
    localStorage.removeItem(draftKey());
  } catch {
    // Ignore unavailable local storage.
  }
}

function autoResizeTextarea(input) {
  input.style.height = "auto";
  const nextHeight = Math.min(input.scrollHeight, 160);
  input.style.height = `${Math.max(44, nextHeight)}px`;
}

async function apiChatStream(payload, onEvent, { signal } = {}) {
  const isolated = tabSessionMode();
  const token = tabSessionToken();
  const headers = { "Content-Type": "application/json" };
  if (isolated && token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    credentials: isolated ? "omit" : "same-origin",
    headers,
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => ({}));
    throw new Error(apiErrorMessage(data.detail, `HTTP ${res.status}`));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let dataLines = [];
  let finalData = null;
  const dispatch = async () => {
    if (!dataLines.length) return;
    const data = JSON.parse(dataLines.join("\n"));
    await onEvent(eventName, data);
    if (eventName === "final") finalData = data;
    if (eventName === "cancelled") throw new DOMException("Chat stream was interrupted.", "AbortError");
    if (eventName === "error") throw new Error(data.message || "Chat service is temporarily unavailable.");
    eventName = "message";
    dataLines = [];
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split(/\r?\n/);
    buffer = done ? "" : lines.pop();
    for (const line of lines) {
      if (!line) {
        await dispatch();
      } else if (line.startsWith("event:")) {
        eventName = line.slice(6).trim() || "message";
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (done) break;
  }
  await dispatch();
  if (!finalData) throw new Error("Chat stream ended without a final reply.");
  return finalData;
}

function takeCompletedSpeechSentences(buffer, flush = false) {
  const source = String(buffer || "");
  const result = [];
  let lastEnd = 0;
  const sentenceRe = /[^。！？!?\n]+[。！？!?]+(?:[””』」])?/g;
  let match;
  while ((match = sentenceRe.exec(source))) {
    const sentence = match[0].trim();
    if (sentence) result.push(sentence);
    lastEnd = sentenceRe.lastIndex;
  }
  const rest = source.slice(lastEnd);
  if (flush && rest.trim()) result.push(rest.trim());
  return { sentences: result, rest: flush ? "" : rest };
}

function createStreamingVoiceQueue(message, isCurrent = () => true) {
  if (!voiceAutoPlayEnabled()) return null;
  let queue = Promise.resolve();
  let spoken = false;
  let cancelled = false;
  return {
    enqueue(sentence) {
      const text = String(sentence || "").trim();
      if (!text || cancelled || !isCurrent()) return;
      spoken = true;
      queue = queue.then(async () => {
        if (cancelled || !isCurrent()) return;
        const utterance = {
          role: "assistant",
          id: message.id,
          content: text,
          expressions: [],
          status: "sent",
          performance: message.performance || {},
        };
        await playMessageVoice(utterance, null);
        if (cancelled || !isCurrent()) return;
        message.performance = utterance.performance || message.performance;
      });
    },
    get spoken() { return spoken; },
    cancel() { cancelled = true; },
    done() { return queue; },
  };
}

function createChatStreamId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function cancelActiveChatStream() {
  const active = activeChatStream;
  if (!active) return false;
  active.cancelled = true;
  active.voiceQueue?.cancel();
  active.controller.abort();
  interruptVoicePlayback();
  void api(`/api/chat/stream/${encodeURIComponent(active.streamId)}/cancel`, {
    method: "POST",
    keepalive: true,
  }).catch(() => null);
  return true;
}

async function sendChatMessage(content, { retryLocalId = "", retryUserMessageId = null, clientMessageId = "" } = {}) {
  if (!content || !state.activePersona) return;
  if (state.sending) cancelActiveChatStream();
  interruptVoicePlayback();
  const requestPersonaId = Number(state.activePersona.id);
  const outgoingClientMessageId = clientMessageId || (retryUserMessageId ? "" : createClientMessageId());
  const activeRequest = {
    id: ++chatStreamSequence,
    streamId: createChatStreamId(),
    controller: new AbortController(),
    voiceQueue: null,
    cancelled: false,
  };
  activeChatStream = activeRequest;
  const isCurrentRequest = () => activeChatStream === activeRequest && !activeRequest.cancelled;
  const canContinueVoiceQueue = () => !activeRequest.cancelled;
  let appliedReplyExpression = false;
  let autoVoiceMessage = null;
  state.sending = true;
  state.composerFocused = false;
  state.composerDraft = "";
  await applyLive2dRuntimeState("thinking");
  if (retryLocalId) {
    state.messages = state.messages.filter((message) => message.local_id !== retryLocalId);
  }
  if (!retryUserMessageId && !clientMessageId) {
    state.messages.push({ role: "user", content, client_message_id: outgoingClientMessageId, created_at: nowSeconds() });
  }
  if (quietModeRequestedLocally(content)) {
    setLocalPresenceState("quiet");
  } else {
    setLocalPresenceState("thinking");
  }
  renderShell();
  scrollChat();
  try {
    const requestStartedAt = performance.now();
    const streamingMessage = {
      role: "assistant",
      id: -Date.now(),
      content: "",
      expressions: [],
      status: "streaming",
      local_id: `stream-${Date.now()}`,
      created_at: nowSeconds(),
      performance: {},
    };
    let streamingMessageVisible = false;
    let pendingSpeechText = "";
    let voiceQueue = null;
    let firstSpeechText = "";
    const data = await apiChatStream({
      message: content,
      persona_id: state.activePersona.id,
      conversation_id: state.activeConversationId,
      retry_user_message_id: retryUserMessageId,
      client_message_id: outgoingClientMessageId || null,
      stream_id: activeRequest.streamId,
    }, async (eventName, eventData) => {
      if (!isCurrentRequest()) return;
      if (eventName !== "delta") return;
      const delta = String(eventData?.text || "");
      if (!delta) return;
      if (!streamingMessageVisible) {
        state.messages.push(streamingMessage);
        streamingMessageVisible = true;
      }
      streamingMessage.content += delta;
      pendingSpeechText += delta;
      const speech = takeCompletedSpeechSentences(pendingSpeechText);
      pendingSpeechText = speech.rest;
      if (!firstSpeechText && speech.sentences.length) {
        firstSpeechText = speech.sentences[0];
        voiceQueue ||= createStreamingVoiceQueue(streamingMessage, canContinueVoiceQueue);
        activeRequest.voiceQueue = voiceQueue;
        voiceQueue?.enqueue(firstSpeechText);
      }
      renderShell();
      scrollChat();
    }, { signal: activeRequest.controller.signal });
    if (!isCurrentRequest()) return;
    const stillViewingConversation = (
      state.view === "chat"
      && Number(state.activePersona?.id) === requestPersonaId
    );
    if (stillViewingConversation) {
      state.activeConversationId = data.conversation_id;
      if (data.degraded) {
        state.messages.push({
          role: "notice",
          content: data.error_message || "回复暂时没有送达。可以稍后重试。",
          status: data.pending ? "pending" : "error",
          retry_content: content,
          retry_user_message_id: data.pending ? null : data.user_message_id,
          retry_client_message_id: outgoingClientMessageId,
          local_id: `error-${Date.now()}`,
          created_at: nowSeconds(),
        });
      } else {
        if (!streamingMessageVisible) {
          state.messages.push(streamingMessage);
          streamingMessageVisible = true;
        }
        const replyForVoice = String(data.reply || streamingMessage.content || "").trim();
        const remainingSpeechText = firstSpeechText && replyForVoice.startsWith(firstSpeechText)
          ? replyForVoice.slice(firstSpeechText.length).trim()
          : replyForVoice;
        if (remainingSpeechText) {
          voiceQueue ||= createStreamingVoiceQueue(streamingMessage, canContinueVoiceQueue);
          activeRequest.voiceQueue = voiceQueue;
          if (!firstSpeechText || remainingSpeechText !== firstSpeechText) {
            voiceQueue?.enqueue(remainingSpeechText);
          }
        }
        const previousStreamingMessageId = streamingMessage.id;
        if (sameVoiceMessageId(state.voicePlaying, previousStreamingMessageId)) {
          state.voicePlaying = data.assistant_message_id;
        }
        streamingMessage.id = data.assistant_message_id;
        streamingMessage.content = data.reply;
        streamingMessage.expressions = data.expressions || [];
        streamingMessage.status = "sent";
        streamingMessage.performance = {
          ...(data.performance && typeof data.performance === "object" ? data.performance : {}),
          client_total_ms: Math.max(0, Math.round(performance.now() - requestStartedAt)),
        };
        autoVoiceMessage = voiceQueue?.spoken ? null : streamingMessage;
        appliedReplyExpression = await applyMessageExpressionsToLive2d(data.expressions || []);
        await markConversationRead(data.conversation_id);
      }
      applyPresenceRuntime(data.presence);
    }
    await loadMainData();
  } catch (err) {
    if (!isCurrentRequest() || activeRequest.cancelled || err?.name === "AbortError") return;
    if (state.view === "chat" && Number(state.activePersona?.id) === requestPersonaId) {
      state.messages.push({
        role: "notice",
        content: friendlyChatError(err.message),
        status: "error",
        retry_content: content,
        retry_client_message_id: outgoingClientMessageId,
        local_id: `error-${Date.now()}`,
        created_at: nowSeconds(),
      });
    }
    await loadPresenceStatus();
    await applyLive2dRuntimeState("idle");
  }
  if (!isCurrentRequest()) return;
  activeChatStream = null;
  state.sending = false;
  await syncCompanionRuntime({ applyLive2d: !appliedReplyExpression });
  renderShell();
  scrollChat();
  if (autoVoiceMessage && voiceAutoPlayEnabled()) {
    await playMessageVoice(autoVoiceMessage, null);
    scrollChat();
  }
}

async function applyMessageExpressionsToLive2d(expressions) {
  if (!live2dAvailable()) return false;
  if (!live2dConnected()) return false;
  if (!live2dBindingMatchesCurrent(personaEmbodimentProfile(state.activePersona))) return false;
  const expression = (expressions || []).find((item) => item && (item.label || item.expression_type));
  if (!expression) return false;
  return enqueueLive2dAction(async () => {
    try {
      const result = await api("/api/live2d/apply-expression", {
        method: "POST",
        body: JSON.stringify({
          label: expression.label || "",
          expression_type: expression.expression_type || "mood",
        }),
      });
      await loadLive2dStatus();
      if (result.applied) scheduleLive2dExpressionReset();
      return !!result.applied;
    } catch {
      // Expression mapping is a secondary embodiment signal; chat should not fail if it misses.
      return false;
    }
  });
}

function enqueueLive2dAction(action) {
  const queued = live2dActionQueue.then(action, action);
  live2dActionQueue = queued.catch(() => null);
  return queued;
}

function clearLive2dExpressionReset() {
  if (live2dExpressionResetTimer !== null) {
    clearTimeout(live2dExpressionResetTimer);
    live2dExpressionResetTimer = null;
  }
}

function scheduleLive2dExpressionReset() {
  clearLive2dExpressionReset();
  const personaId = Number(state.activePersona?.id || 0);
  live2dExpressionResetTimer = setTimeout(async () => {
    live2dExpressionResetTimer = null;
    const videoActive = !!state.videoCompanionStatus?.status?.session_active;
    if (state.sending || state.voicePlaying || videoActive || Number(state.activePersona?.id || 0) !== personaId) return;
    await applyLive2dRuntimeState("idle", { preserveExpressionTimer: true });
    await syncCompanionRuntime({ applyLive2d: false });
    renderShell();
  }, 1800);
}

function applyLive2dRuntimeState(runtimeState, options = {}) {
  if (!options.preserveExpressionTimer) clearLive2dExpressionReset();
  return enqueueLive2dAction(() => applyLive2dRuntimeStateNow(runtimeState, options));
}

async function applyLive2dRuntimeStateNow(runtimeState, options = {}) {
  if (!live2dAvailable()) return options.report ? { applied: false, reason: "live2d_disabled" } : null;
  const status = state.live2dStatus || {};
  if (!live2dConnected()) {
    return options.report ? { applied: false, reason: status.last_error || "not_connected" } : null;
  }
  if (!live2dBindingMatchesCurrent(personaEmbodimentProfile(state.activePersona))) {
    return options.report ? { applied: false, reason: "model_mismatch" } : null;
  }
  try {
    const result = await api("/api/live2d/apply-runtime-state", {
      method: "POST",
      body: JSON.stringify({ state: runtimeState }),
    });
    await loadLive2dStatus();
    return result;
  } catch {
    // Runtime animation is best-effort and should not interrupt voice playback.
    return options.report ? { applied: false, reason: "request_failed" } : null;
  }
}

function videoCompanionPathState(config) {
  const path = String(config?.project_path || "").trim();
  if (!path) return { tone: "off", text: "外部项目路径未配置" };
  if (config.project_path_exists === false) return { tone: "off", text: `路径不存在：${path}` };
  return { tone: "ok", text: path };
}

async function sendGroupChatMessage(content) {
  if (!content || !state.activeGroupConversationId || state.sending) return;
  const requestGroupId = Number(state.activeGroupConversationId);
  const outgoingClientMessageId = createClientMessageId();
  state.sending = true;
  state.groupMessages.push({
    speaker_type: "user",
    content,
    client_message_id: outgoingClientMessageId,
    created_at: nowSeconds(),
  });
  renderShell();
  scrollChat();
  try {
    const data = await api("/api/group-chat", {
      method: "POST",
      body: JSON.stringify({
        message: content,
        group_conversation_id: requestGroupId,
        client_message_id: outgoingClientMessageId,
      }),
    });
    const stillViewingGroup = state.view === "group" && Number(state.activeGroupConversationId) === requestGroupId;
    if (stillViewingGroup) {
      state.groupMessages = state.groupMessages.filter((message) => message.client_message_id !== outgoingClientMessageId);
      state.groupMessages.push(...(data.messages || []));
      if (data.degraded && !(data.replies || []).length) {
        state.groupMessages.push({
          speaker_type: "system",
          role: "notice",
          content: data.error_message || "这轮群聊暂时没有成功接上。稍后再试一次。",
          status: "error",
          local_id: `group-degraded-${Date.now()}`,
          created_at: nowSeconds(),
        });
      }
      await markGroupConversationRead(requestGroupId);
    }
    await loadMainData();
  } catch (err) {
    if (state.view === "group" && Number(state.activeGroupConversationId) === requestGroupId) {
      state.groupMessages.push({
        speaker_type: "system",
        role: "notice",
        content: friendlyChatError(err.message),
        status: "error",
        local_id: `group-error-${Date.now()}`,
        created_at: nowSeconds(),
      });
    }
  }
  state.sending = false;
  renderShell();
  scrollChat();
}

async function markConversationRead(conversationId) {
  if (!conversationId) return;
  try {
    await api(`/api/conversations/${conversationId}/read`, { method: "POST" });
  } catch {
    // Read markers are a convenience state; failing to update them should not block chat.
  }
}

async function markGroupConversationRead(groupConversationId) {
  if (!groupConversationId) return;
  try {
    await api(`/api/group-conversations/${groupConversationId}/read`, { method: "POST" });
  } catch {
    // Read markers are a convenience state; failing to update them should not block chat.
  }
}

function renderChatEmpty() {
  const persona = state.activePersona || {};
  const llmBlocked = chatInputBlocked();
  return h("div", { class: "chat-empty" }, [
    avatar(persona.name || "澪", persona.avatar_url),
    h("h3", { text: persona.name || "澪" }),
    renderPersonaStatusLine(persona, "center"),
    h("p", { text: llmBlocked ? "模型还没有启用。先保留澪的空白设定，等你接好 API 后再开始对话。" : persona.summary || "从一句自然的话开始。" }),
    llmBlocked ? null : h("div", { class: "chat-empty-actions" }, [
      chatStarterButton("今天有点累。"),
      chatStarterButton("想随便聊聊。"),
      chatStarterButton("陪我想一件事。"),
    ]),
  ]);
}

function chatStarterButton(value) {
  return h("button", {
    type: "button",
    class: "chat-empty-chip",
    text: value,
    onclick: () => setComposerDraft(value),
  });
}

function conversationPreview(item) {
  const content = String(item.last_message || "").trim();
  if (!content) return item.persona_name || "暂无消息";
  if (item.last_message_role === "user" && item.last_message_reply_status === "failed") {
    return `回复未送达 · 你：${content}`.slice(0, 42);
  }
  if (item.last_message_role === "user" && item.last_message_reply_status === "generating") {
    return `等待回复 · 你：${content}`.slice(0, 42);
  }
  const prefix = item.last_message_role === "user" ? "你：" : "";
  return `${prefix}${content}`.slice(0, 42);
}

function conversationDisplayTitle(item) {
  const title = String(item.title || "").trim();
  return title || item.persona_name || "聊天";
}

function groupConversationTitle(group) {
  const title = String(group?.title || "").trim();
  if (title) return title;
  const names = (group?.members || []).map((member) => member.display_name || member.name).filter(Boolean);
  return names.slice(0, 3).join("、") || "群聊";
}

function groupConversationPreview(group) {
  const content = String(group?.last_message || "").trim();
  if (content) return content.slice(0, 42);
  const names = (group?.members || []).map((member) => member.display_name || member.name).filter(Boolean);
  return names.length ? `${names.slice(0, 4).join("、")} 在群里` : "还没有消息";
}

function renderPersonaStatusLine(persona, align = "") {
  const storedRelation = cleanMetaText(persona?.relationship);
  const relation = !storedRelation || storedRelation === "关系未定" ? "未设定" : storedRelation;
  const style = cleanMetaText(persona?.speaking_style) || "未填写";
  const version = persona?.version ? `v${persona.version}` : "v1";
  return h("div", { class: `persona-status-line ${align}`.trim() }, [
    h("span", { class: "status-pill relation", text: relation }),
    persona?.growth_notice ? h("button", {
      type: "button",
      class: "status-pill growth action",
      text: "相处有变化 · 查看",
      onclick: (event) => openPersonaGrowthNotice(event, persona),
    }) : null,
    persona?.growth_action?.kind === "preference_retry" ? h("button", {
      type: "button",
      class: "status-pill preference-action action",
      text: "偏好需重新确认 · 查看",
      onclick: (event) => openPersonaGrowthNotice(event, persona),
    }) : null,
    h("span", { class: "status-pill", text: style }),
    h("span", { class: "status-pill quiet", text: version }),
  ]);
}

function renderInlinePersonaMeta(persona) {
  const relation = cleanMetaText(persona?.relationship);
  const style = cleanMetaText(persona?.speaking_style);
  const value = [relation, style].filter(Boolean).slice(0, 2).join(" · ");
  return value ? h("small", { class: "persona-inline-meta", text: value }) : null;
}

function cleanMetaText(value) {
  const text = String(value || "").trim();
  if (!text || text === "尚未明确" || text === "未设置") return "";
  return text;
}

function isPinnedConversation(item) {
  return Number(item?.pinned_at || 0) > 0;
}

function normalizedSearch(value) {
  return String(value || "").trim().toLowerCase();
}

function matchesConversationSearch(item, query) {
  if (!query) return true;
  return [
    conversationDisplayTitle(item),
    item.persona_name,
    item.title,
    item.last_message,
  ].some((value) => String(value || "").toLowerCase().includes(query));
}

function matchesPersonaSearch(persona, query) {
  if (!query) return true;
  return [
    persona.name,
    persona.summary,
    persona.relationship,
    persona.speaking_style,
  ].some((value) => String(value || "").toLowerCase().includes(query));
}

function matchesGroupSearch(group, query) {
  if (!query) return true;
  return [
    group.title,
    group.last_message,
    ...(group.members || []).map((member) => member.display_name || member.name),
  ].some((value) => String(value || "").toLowerCase().includes(query));
}

function renderMessageList(messages) {
  const nodes = [];
  let lastDateKey = "";
  for (const message of messages) {
    const dateKey = messageDateKey(message.created_at);
    if (dateKey && dateKey !== lastDateKey) {
      nodes.push(renderDateDivider(message.created_at));
      lastDateKey = dateKey;
    }
    nodes.push(renderMessage(message));
    if (message.role === "user" && message.reply_status === "failed") {
      nodes.push(renderFailedReplyNotice(message));
    } else if (isStalledReply(message)) {
      nodes.push(renderStalledReplyNotice(message));
    }
  }
  return nodes;
}

function renderGroupMessageList(messages) {
  const nodes = [];
  let lastDateKey = "";
  for (const message of messages) {
    const dateKey = messageDateKey(message.created_at);
    if (dateKey && dateKey !== lastDateKey) {
      nodes.push(renderDateDivider(message.created_at));
      lastDateKey = dateKey;
    }
    nodes.push(renderGroupMessage(message));
  }
  return nodes;
}

function renderGroupMessage(message) {
  const isUser = message.speaker_type === "user";
  const isNotice = message.speaker_type === "system" || message.role === "notice";
  const speakerName = isUser ? (state.profile?.nickname || "我") : message.speaker_name || groupMemberName(message.speaker_persona_id) || "TA";
  const speakerAvatar = isUser
    ? state.profile?.avatar_url
    : message.speaker_avatar_url || groupMemberAvatar(message.speaker_persona_id);
  const content = String(message.content || "").trim();
  return h("article", { class: `message group-message ${isUser ? "user" : isNotice ? "notice" : "assistant"}` }, [
    !isUser && !isNotice ? avatar(speakerName, speakerAvatar) : null,
    h("div", { class: "message-stack" }, [
      !isUser && !isNotice ? h("small", { class: "group-speaker-name", text: speakerName }) : null,
      h("div", { class: `bubble ${message.status || ""}` }, [content]),
      !isUser && !isNotice && Array.isArray(message.expressions) && message.expressions.length
        ? renderExpressionStrip(message.expressions)
        : null,
      h("div", { class: "message-meta" }, [
        h("small", { class: "message-time", text: formatMessageTime(message.created_at) }),
        h("button", {
          type: "button",
          class: "copy-message",
          text: "复制",
          onclick: () => copyMessageText(message),
        }),
        !isUser && !isNotice ? renderVoiceButton(message) : null,
      ]),
    ]),
    isUser ? avatar(speakerName, speakerAvatar) : null,
  ]);
}

function renderFailedReplyNotice(userMessage) {
  return renderMessage({
    role: "notice",
    content: userMessage.reply_error || "回复暂时没有送达。可以稍后重试。",
    status: "error",
    retry_content: userMessage.content,
    retry_user_message_id: userMessage.id,
    retry_client_message_id: userMessage.client_message_id,
    local_id: `stored-error-${userMessage.id}`,
    created_at: userMessage.created_at,
  });
}

function isStalledReply(message) {
  return (
    message.role === "user"
    && message.reply_status === "generating"
    && Boolean(message.client_message_id)
    && nowSeconds() - Number(message.created_at || 0) >= 120
  );
}

function renderStalledReplyNotice(userMessage) {
  return renderMessage({
    role: "notice",
    content: "这句话还没有等到回复。可以重新尝试一次。",
    status: "pending",
    retry_content: userMessage.content,
    retry_client_message_id: userMessage.client_message_id,
    local_id: `stalled-${userMessage.id}`,
    created_at: userMessage.created_at,
  });
}

function renderDateDivider(value) {
  return h("div", { class: "date-divider" }, [
    h("span", { text: formatMessageDate(value) }),
  ]);
}

function renderMessage(message) {
  const isUser = message.role === "user";
  const isNotice = message.role === "notice";
  const timing = !isUser && !isNotice ? formatMessagePerformance(message.performance) : "";
  const segments = messageSegments(message);
  return h("article", { class: `message ${isUser ? "user" : isNotice ? "notice" : "assistant"}` }, [
    !selfUseMode() && !isUser && !isNotice ? avatar(state.activePersona?.name || "忆", state.activePersona?.avatar_url) : null,
    h("div", { class: "message-stack" }, [
      !isUser && !isNotice && Array.isArray(message.expressions) && message.expressions.length
        ? renderExpressionStrip(message.expressions)
        : null,
      ...segments.map((segment, index) => {
        const children = [segment];
        if (index === segments.length - 1 && ["error", "pending"].includes(message.status) && message.retry_content) {
          children.push(
            h("button", {
              type: "button",
              class: "retry-btn",
              text: "重试",
              onclick: () => sendChatMessage(message.retry_content, {
                retryLocalId: message.local_id,
                retryUserMessageId: message.retry_user_message_id || null,
                clientMessageId: message.retry_client_message_id || "",
              }),
            })
          );
        }
        return h("div", { class: `bubble ${message.status || ""}` }, children);
      }),
      h("div", { class: "message-meta" }, [
        h("small", { class: "message-time", text: formatMessageTime(message.created_at) }),
        timing ? h("small", { class: "message-performance", text: timing }) : null,
        h("button", {
          type: "button",
          class: "copy-message",
          text: "复制",
          onclick: () => copyMessageText(message),
        }),
        !isUser && !isNotice ? renderVoiceButton(message) : null,
      ]),
    ]),
    !selfUseMode() && isUser ? avatar(state.profile?.nickname || "U", state.profile?.avatar_url) : null,
  ]);
}

async function copyMessageText(message) {
  const content = String(message.content || "").trim();
  if (!content) return;
  try {
    await navigator.clipboard.writeText(content);
  } catch {
    const area = h("textarea", { class: "clipboard-fallback" }, content);
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
}

async function loadPresenceStatus() {
  try {
    const data = await api("/api/presence/state");
    state.presenceStatus = data || { enabled: false };
  } catch {
    state.presenceStatus = { enabled: false };
  }
}

function presenceAvailable() {
  return !!(state.presenceStatus && state.presenceStatus.enabled);
}

function presenceRuntime() {
  return presenceAvailable() ? (state.presenceStatus.runtime || {}) : {};
}

function setLocalPresenceState(nextState) {
  if (!presenceAvailable()) return;
  const currentRuntime = presenceRuntime();
  state.presenceStatus = {
    ...state.presenceStatus,
    runtime: {
      ...currentRuntime,
      previous_state: currentRuntime.state || "idle",
      state: nextState,
      quiet_mode: nextState === "quiet" ? true : !!currentRuntime.quiet_mode,
      state_duration_seconds: 0,
    },
  };
}

function applyPresenceRuntime(runtime) {
  if (!runtime || !presenceAvailable()) return;
  state.presenceStatus = {
    ...state.presenceStatus,
    runtime,
  };
}

function quietModeRequestedLocally(content) {
  const text = String(content || "").toLowerCase().replace(/\s+/g, "");
  return [
    "别打扰我",
    "安静一点",
    "先别说话",
    "静一静",
    "别说话",
    "安静",
    "不要吵",
    "别吵",
    "别打扰",
    "让我安静",
    "不要打扰我",
    "先不要说话",
    "quietmode",
    "silentmode",
  ].some((keyword) => text.includes(keyword));
}

function presenceStatusKey() {
  const runtime = presenceRuntime();
  if (runtime.quiet_mode) return "quiet";
  return runtime.state || "idle";
}

function presenceStatusText(key) {
  return {
    idle: "在",
    thinking: "思考中",
    speaking: "回应中",
    quiet: "安静模式",
    sleeping: "休息中",
  }[key] || "在";
}

function renderPresencePill() {
  if (!presenceAvailable()) return null;
  const key = presenceStatusKey();
  return h("div", { class: "presence-pill " + key, title: "Presence: " + key }, [
    h("span", { class: "presence-dot" }),
    h("span", { text: presenceStatusText(key) }),
  ]);
}

async function setPresenceQuietMode(quiet) {
  if (!presenceAvailable() || state.presenceSaving) return;
  state.presenceSaving = true;
  state.presenceControlError = null;
  renderShell();
  try {
    const runtime = await api(quiet ? "/api/presence/quiet-mode" : "/api/presence/normal-mode", {
      method: "POST",
    });
    applyPresenceRuntime(runtime);
    await syncCompanionRuntime({ applyLive2d: true });
  } catch (error) {
    state.presenceControlError = error.message || "Presence 状态切换失败";
  } finally {
    state.presenceSaving = false;
    renderShell();
  }
}

function voicePlaybackDetail() {
  if (state.voicePlaybackPhase === "preparing") return "正在生成语音";
  const plan = state.voicePlan || {};
  const count = Number(plan.chunk_count || (plan.utterances || []).length || 0);
  if (!count) return "正在播放语音";
  const styles = (plan.styles || []).filter(Boolean);
  return styles.length ? `正在播放语音：${count} 段 / ${styles[0]}` : `正在播放语音：${count} 段`;
}

function companionRuntimeState() {
  const video = state.videoCompanionStatus || {};
  const serverRuntime = state.companionStatus?.runtime;
  const presenceKey = presenceAvailable() ? presenceStatusKey() : "";
  const live2dReady = live2dConnected();
  if (video.enabled && video.connected && video.status?.session_active) {
    const recent = videoCompanionRecentObservation();
    return {
      key: "video",
      label: "视频会话中",
      detail: recent.title || "Video Companion 正在接管实时感知",
      ready: true,
    };
  }
  if (state.sending) return { key: "thinking", label: "思考中", detail: "正在组织回应", ready: true };
  if (state.voicePlaying && state.voicePlaybackPhase === "preparing") {
    return { key: "thinking", label: "准备语音", detail: voicePlaybackDetail(), ready: true };
  }
  if (state.voicePlaying) return { key: "speaking", label: "回应中", detail: voicePlaybackDetail(), ready: true };
  if (state.composerFocused && !chatInputBlocked()) {
    return {
      key: "listening",
      label: "倾听中",
      detail: state.composerDraft ? "正在接收你的输入" : "输入框已准备好",
      ready: true,
    };
  }
  if (presenceKey === "quiet") return { key: "quiet", label: "安静模式", detail: "澪会降低主动打扰", ready: true };
  if (presenceKey === "thinking") return { key: "thinking", label: "思考中", detail: "正在组织回应", ready: true };
  if (presenceKey === "speaking") return { key: "speaking", label: "回应中", detail: "正在表达", ready: true };
  if (serverRuntime?.key) {
    return {
      key: serverRuntime.key,
      label: serverRuntime.label || "待机",
      detail: serverRuntime.detail || "",
      ready: serverRuntime.ready !== false,
    };
  }
  if (chatInputBlocked()) return { key: "offline", label: "模型未启用", detail: "接好 API 后再开始对话", ready: false };
  if (live2dReady) return { key: "present", label: "在场", detail: "Live2D 已连接", ready: true };
  if (live2dAvailable()) return { key: "waiting", label: "待连接", detail: "Live2D 已启用但未连接", ready: true };
  return { key: "idle", label: "待机", detail: "基础陪伴状态", ready: true };
}

function refreshRuntimeIndicators() {
  if (!selfUseMode()) return;
  const runtime = companionRuntimeState();
  const badge = document.querySelector(".companion-runtime-badge");
  if (badge) {
    badge.className = `companion-runtime-badge ${runtime.key}`;
    const label = badge.querySelector("strong");
    const detail = badge.querySelector("small");
    if (label) label.textContent = runtime.label || "";
    if (detail) detail.textContent = runtime.detail || "";
  }
}

function runtimeToLive2dState(runtime) {
  const key = String(runtime?.key || "");
  if (key === "thinking") return "thinking";
  if (key === "listening") return "listening";
  if (key === "speaking") return "speaking";
  return "idle";
}

async function syncCompanionRuntime(options = {}) {
  if (!selfUseMode()) return companionRuntimeState();
  if (options.reload) {
    await loadCompanionStatus();
  }
  const runtime = companionRuntimeState();
  refreshRuntimeIndicators();
  if (options.applyLive2d) {
    await applyLive2dRuntimeState(runtimeToLive2dState(runtime));
  }
  return runtime;
}

async function loadAwarenessStatus() {
  try {
    const cameraStatus = selfUseMode()
      ? Promise.resolve({ external_only: true, active: false, config: { enabled: false } })
      : api("/api/camera/status");
    const [consents, camera, screen, proactive, videoCompanion] = await Promise.all([
      api("/api/consents"),
      cameraStatus,
      api("/api/screen/status"),
      api("/api/proactive/status").catch(() => ({ enabled: false })),
      api("/api/video-companion/status").catch(() => ({ enabled: false, connected: false })),
    ]);
    state.consents = consents.consents || [];
    state.cameraStatus = camera;
    state.screenStatus = screen;
    state.proactiveStatus = proactive;
    state.videoCompanionStatus = videoCompanion;
  } catch {
    state.consents = [];
    state.cameraStatus = null;
    state.screenStatus = null;
    state.proactiveStatus = null;
    state.videoCompanionStatus = null;
  }
}

function consentFor(key) {
  return (state.consents || []).find((item) => item.consent_key === key) || {
    consent_key: key,
    granted: false,
    label: awarenessLabel(key),
  };
}

function awarenessLabel(key) {
  return {
    camera: "摄像头感知",
    screen: "屏幕感知",
    proactive: "主动消息",
  }[key] || key;
}

function awarenessState(key) {
  const granted = !!consentFor(key).granted;
  const status = key === "camera"
    ? state.cameraStatus
    : key === "screen"
      ? state.screenStatus
      : state.proactiveStatus;
  const configEnabled = key === "proactive"
    ? !!(status?.config_enabled ?? status?.config?.enabled)
    : !!status?.config?.enabled;
  const active = key === "proactive" ? !!status?.enabled : !!status?.active;

  if (!configEnabled) return { tone: "off", text: granted ? "已授权，配置关闭" : "配置关闭" };
  if (!granted) return { tone: "waiting", text: "等待授权" };
  if (active) return { tone: "ok", text: "已启用" };
  return { tone: "waiting", text: "未就绪" };
}

async function setAwarenessConsent(key, granted, statusEl) {
  if (statusEl) statusEl.textContent = "";
  try {
    await api(granted ? "/api/consents/grant" : "/api/consents/revoke", {
      method: "POST",
      body: JSON.stringify({ consent_key: key }),
    });
    await loadAwarenessStatus();
    await loadCompanionStatus();
    renderShell();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message;
  }
}

async function runAwarenessProbe(key, statusEl) {
  if (statusEl) statusEl.textContent = "";
  try {
    const path = key === "camera" ? "/api/perception/cycle" : "/api/screen/perception-cycle";
    const data = await api(path, { method: "POST" });
    if (statusEl) statusEl.textContent = data.cycle === "disabled" ? "未启用" : "已检查";
    await loadAwarenessStatus();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message;
  }
}

function toggleCameraPreview(statusEl) {
  state.cameraPreviewActive = !state.cameraPreviewActive;
  if (statusEl) {
    statusEl.textContent = state.cameraPreviewActive ? "本机预览已打开" : "本机预览已关闭";
  }
  renderShell();
}

async function runProactiveTick(statusEl) {
  if (statusEl) statusEl.textContent = "";
  try {
    const data = await api("/api/proactive/tick", {
      method: "POST",
      body: JSON.stringify({ dry_run: false }),
    });
    if (data.sent > 0) {
      if (statusEl) statusEl.textContent = "已发送 " + data.sent + " 条";
    } else {
      const firstSkip = (data.skipped || [])[0] || {};
      if (statusEl) statusEl.textContent = firstSkip.reason ? "未发送：" + firstSkip.reason : "暂无可发送";
    }
    await loadAwarenessStatus();
    await loadConversations();
    renderShell();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message;
  }
}

async function startVideoCompanion(statusEl) {
  if (statusEl) statusEl.textContent = "";
  try {
    const personaId = state.activePersona?.id || null;
    const data = await api("/api/video-companion/session/start", {
      method: "POST",
      body: JSON.stringify({ persona_id: personaId }),
    });
    if (statusEl) statusEl.textContent = data.started ? "视频会话已启动" : "视频会话未启动";
    await loadAwarenessStatus();
    await syncCompanionRuntime({ reload: true, applyLive2d: true });
    renderShell();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message;
  }
}

async function stopVideoCompanion(statusEl) {
  if (statusEl) statusEl.textContent = "";
  try {
    const data = await api("/api/video-companion/session/stop", { method: "POST" });
    if (statusEl) statusEl.textContent = data.stopped ? "视频会话已停止" : "视频会话未停止";
    await loadAwarenessStatus();
    await syncCompanionRuntime({ reload: true, applyLive2d: true });
    renderShell();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message;
  }
}

function videoCompanionState() {
  const status = state.videoCompanionStatus || {};
  if (!status.enabled) return { tone: "off", text: "外部服务配置关闭" };
  if (status.connected) return { tone: "ok", text: "外部服务已连接" };
  return { tone: "waiting", text: status.error ? "外部服务未连接" : "等待外部服务" };
}

function videoCompanionStatusText() {
  const status = state.videoCompanionStatus || {};
  if (!status.enabled) return "未启用";
  if (status.connected && status.status?.session_active) return "会话中";
  if (status.connected) return "已连接";
  return "未连接";
}

function openVideoCompanionPage() {
  const status = state.videoCompanionStatus || {};
  const config = status.config || {};
  const url = config.base_url || "http://127.0.0.1:8782";
  window.open(url, "_blank", "noopener,noreferrer");
}

function renderVideoCompanionPanel() {
  const status = state.videoCompanionStatus || {};
  const config = status.config || {};
  const stateInfo = videoCompanionState();
  const sessionActive = !!status.status?.session_active;
  const canControl = !!status.enabled && !!status.connected;
  const statusEl = h("small", { class: "save-status" });

  return h("div", { class: "video-companion-panel" }, [
    h("div", { class: "video-companion-main" }, [
      h("div", { class: "video-companion-title" }, [
        h("strong", { text: "Video Companion" }),
        h("small", { class: "awareness-status " + stateInfo.tone, text: stateInfo.text }),
        config.base_url ? h("small", { class: "muted", text: config.base_url }) : null,
      ]),
      h("div", { class: "awareness-actions" }, [
        h("button", {
          type: "button",
          class: "ghost compact",
          text: "打开视频页",
          title: config.base_url || "http://127.0.0.1:8782",
          onclick: openVideoCompanionPage,
        }),
        h("button", {
          type: "button",
          class: "ghost compact",
          text: sessionActive ? "会话运行中" : "启动会话",
          disabled: !canControl || sessionActive,
          title: canControl ? "" : "需先启动 E:\\视觉\\video-companion 外部服务，并在 config.yaml 开启 video_companion.enabled",
          onclick: () => startVideoCompanion(statusEl),
        }),
        h("button", {
          type: "button",
          class: "ghost compact",
          text: "停止会话",
          disabled: !canControl || !sessionActive,
          title: canControl ? "" : "外部服务未连接",
          onclick: () => stopVideoCompanion(statusEl),
        }),
      ]),
      statusEl,
    ]),
    h("small", {
      class: "muted",
      text: "实时摄像头、麦克风和视频理解由外部项目负责；主项目只做状态检查和会话入口。",
    }),
  ]);
}

function renderAwarenessConsentPanel() {
  return h("section", { class: "awareness-card" }, [
    h("div", { class: "section-head" }, [
      h("strong", { text: "感知与主动性" }),
      h("button", {
        type: "button",
        class: "ghost compact",
        text: "刷新",
        onclick: async () => {
          await loadAwarenessStatus();
          renderShell();
        },
      }),
    ]),
    h("div", { class: "awareness-list" }, [
      selfUseMode() ? renderVideoCompanionCameraConsentRow() : renderAwarenessConsentRow("camera"),
      renderAwarenessConsentRow("screen"),
      renderAwarenessConsentRow("proactive"),
      renderVideoCompanionPanel(),
    ]),
    state.integrationFlagError ? h("small", { class: "danger-text", text: state.integrationFlagError }) : null,
  ]);
}

function renderVideoCompanionCameraConsentRow() {
  const consent = consentFor("camera");
  const status = h("small", { class: "save-status" });
  const checkbox = h("input", { type: "checkbox" });
  checkbox.checked = !!consent.granted;
  checkbox.addEventListener("change", () => setAwarenessConsent("camera", checkbox.checked, status));
  return h("div", { class: "awareness-row" }, [
    h("div", { class: "awareness-row-main" }, [
      h("label", { class: "awareness-toggle" }, [
        checkbox,
        h("span", {}, [
          h("strong", { text: "Video Companion 摄像头授权" }),
          h("small", {
            class: `awareness-status ${checkbox.checked ? "ok" : "waiting"}`,
            text: checkbox.checked ? "已允许外部视频会话读取授权" : "未授权",
          }),
        ]),
      ]),
      status,
    ]),
    h("small", {
      class: "muted",
      text: "摄像头采集、预览和连续视觉理解都在外部 Video Companion 中运行。",
    }),
  ]);
}

function renderAwarenessConsentRow(key) {
  const consent = consentFor(key);
  const stateInfo = awarenessState(key);
  const statusData = key === "camera"
    ? state.cameraStatus
    : key === "screen"
      ? state.screenStatus
      : state.proactiveStatus;
  const configEnabled = key === "proactive"
    ? !!(statusData?.config_enabled ?? statusData?.config?.enabled)
    : !!statusData?.config?.enabled;
  const granted = !!consent.granted;
  const canProbe = configEnabled && granted;
  const canPreviewCamera = key === "camera"
    && canProbe
    && !!statusData?.active
    && !!statusData?.stream?.available;
  const status = h("small", { class: "save-status" });
  const checkbox = h("input", { type: "checkbox" });
  checkbox.checked = granted;
  checkbox.addEventListener("change", () => setAwarenessConsent(key, checkbox.checked, status));

  const actions = [];
  if (selfUseMode() && (key === "screen" || key === "proactive")) {
    actions.push(h("button", {
      type: "button",
      class: configEnabled ? "ghost compact" : "compact",
      text: integrationFlagButtonText(key, configEnabled),
      disabled: !!state.integrationFlagSaving,
      title: key === "screen"
        ? "只启用本机窗口标题/截图元数据边界；仍需单独授权"
        : "只启用主动消息能力；授权与 scheduler 仍单独控制",
      onclick: () => setSelfUseIntegrationFlag(key, !configEnabled),
    }));
  }
  if (key === "camera" || key === "screen") {
    actions.push(h("button", {
      type: "button",
      class: "ghost compact",
      text: "检查一次",
      disabled: !canProbe,
      title: canProbe ? "" : "需先开启配置并授权",
      onclick: () => runAwarenessProbe(key, status),
    }));
  }
  if (key === "camera") {
    actions.push(h("button", {
      type: "button",
      class: "ghost compact",
      text: state.cameraPreviewActive ? "关闭预览" : "本机预览",
      disabled: !canPreviewCamera && !state.cameraPreviewActive,
      title: canPreviewCamera || state.cameraPreviewActive ? "" : "摄像头未可用，无法预览",
      onclick: () => toggleCameraPreview(status),
    }));
  }
  if (key === "proactive") {
    actions.push(h("button", {
      type: "button",
      class: "ghost compact",
      text: "检查一次",
      disabled: !canProbe,
      title: canProbe ? "" : "需先开启配置并授权",
      onclick: () => runProactiveTick(status),
    }));
  }

  const rowChildren = [
    h("div", { class: "awareness-row-main" }, [
      h("label", { class: "awareness-toggle" }, [
        checkbox,
        h("span", {}, [
          h("strong", { text: consent.label || awarenessLabel(key) }),
          h("small", { class: "awareness-status " + stateInfo.tone, text: stateInfo.text }),
        ]),
      ]),
      h("div", { class: "awareness-actions" }, actions),
      status,
    ]),
  ];
  if (key === "camera" && state.cameraPreviewActive) {
    rowChildren.push(renderCameraPreview());
  }
  return h("div", { class: "awareness-row" }, rowChildren);
}

function renderCameraPreview() {
  const streamUrl = "/api/camera/stream?ts=" + Date.now();
  return h("div", { class: "camera-preview" }, [
    h("img", {
      src: streamUrl,
      alt: "摄像头本机预览",
      decoding: "async",
    }),
    h("small", { class: "muted", text: "仅本机预览；当前不保存视频帧，也不上传到外部模型。" }),
  ]);
}

async function loadVoiceConfig() {
  try {
    const data = await api("/api/voice/config");
    state.voiceConfig = data.voice || { enabled: false };
  } catch {
    state.voiceConfig = { enabled: false };
  }
}

async function loadLLMStatus() {
  try {
    const data = await api("/api/llm/status?task=chat");
    state.llmStatus = data.llm || { configured: false };
  } catch {
    state.llmStatus = { configured: false, missing: [] };
  }
}

async function loadCompanionStatus(options = {}) {
  try {
    const query = state.activePersona?.id ? `?persona_id=${encodeURIComponent(state.activePersona.id)}` : "";
    const data = await api(`/api/companion/status${query}`);
    applyCompanionStatus(data);
    return true;
  } catch {
    if (!options.preserveOnError) state.companionStatus = null;
    return false;
  }
}

function companionStatusSignature() {
  const companion = state.companionStatus || {};
  const live2d = state.live2dStatus || {};
  const video = state.videoCompanionStatus || {};
  return JSON.stringify({
    runtime: companion.runtime || null,
    readiness: (companion.readiness || []).map((item) => [item.key, item.ready, item.text]),
    live2d: [
      live2d.enabled,
      live2d.connecting,
      live2d.connected,
      live2d.authenticated,
      live2d.last_error,
      live2d.capabilities_stale,
      live2d.capabilities_updated_at,
      live2d.current_model,
      live2d.lip_sync_enabled,
      live2d.lip_sync_parameter,
      live2d.lip_sync_gain,
      live2d.available_parameter_count,
    ],
    video: [
      video.enabled,
      video.connected,
      video.reason,
      video.status?.session_state,
      video.status?.session_active,
      video.status?.consent,
      video.recent_observation?.id,
      video.recent_observation?.fresh,
      video.recent_summary?.id,
      video.recent_consent_sync?.id,
    ],
  });
}

function startCompanionStatusPolling() {
  stopCompanionStatusPolling();
  if (!selfUseMode()) return;
  bindCompanionLifecycleRefresh();
  companionStatusPollTimer = setInterval(pollCompanionStatus, 8000);
}

function bindCompanionLifecycleRefresh() {
  if (companionLifecycleBound) return;
  companionLifecycleBound = true;
  const refreshWhenVisible = () => {
    if (!document.hidden && selfUseMode()) void pollCompanionStatus();
  };
  document.addEventListener("visibilitychange", refreshWhenVisible);
  window.addEventListener("pageshow", refreshWhenVisible);
  window.addEventListener("online", refreshWhenVisible);
}

function stopCompanionStatusPolling() {
  if (companionStatusPollTimer !== null) {
    clearInterval(companionStatusPollTimer);
    companionStatusPollTimer = null;
  }
  companionStatusPollBusy = false;
}

async function pollCompanionStatus() {
  if (companionStatusPollBusy || !selfUseMode() || document.hidden) return;
  companionStatusPollBusy = true;
  try {
    const loaded = await loadCompanionStatus({ preserveOnError: true });
    if (!loaded) return;
    // Status polling must never replace the chat tree: doing so loses a
    // reader's position whenever the browser regains focus or a runtime label
    // changes.  Explicit user actions still render their own panels.
    refreshRuntimeIndicators();
  } finally {
    companionStatusPollBusy = false;
  }
}

async function setSelfUseChatGate(enabled) {
  if (state.chatGateSaving) return;
  state.chatGateSaving = true;
  state.chatGateError = null;
  renderShell();
  try {
    const data = await api("/api/self-use/chat-gate", {
      method: "POST",
      body: JSON.stringify({ enabled: !!enabled }),
    });
    applySelfUseState(data);
    applyCompanionStatus(data);
    await syncCompanionRuntime({ reload: true, applyLive2d: true });
  } catch (err) {
    state.chatGateError = err.message || "更新对话闸门失败";
  } finally {
    state.chatGateSaving = false;
    renderShell();
  }
}

async function probeSelfUseLlm() {
  if (state.llmProbeSaving) return;
  state.llmProbeSaving = true;
  state.chatGateError = null;
  renderShell();
  try {
    const data = await api("/api/self-use/llm-probe", { method: "POST" });
    applyCompanionStatus(data);
    if (!data.probe?.ok) {
      state.chatGateError = data.probe?.error || "模型连接检测失败";
    }
  } catch (err) {
    state.chatGateError = err.message || "模型连接检测失败";
  } finally {
    state.llmProbeSaving = false;
    renderShell();
  }
}

function integrationFlagButtonText(key, enabled) {
  if (state.integrationFlagSaving === key) return enabled ? "关闭中..." : "启用中...";
  if (key === "live2d") return enabled ? "关闭 Live2D 配置" : "启用 Live2D 配置";
  if (key === "voice") return enabled ? "Disable voice" : "Enable voice";
  if (key === "video_companion") return enabled ? "关闭视频接入" : "启用视频接入";
  if (key === "screen") return enabled ? "关闭屏幕感知" : "启用屏幕感知";
  if (key === "proactive") return enabled ? "关闭主动能力" : "启用主动能力";
  return enabled ? "关闭" : "启用";
}

async function setSelfUseIntegrationFlag(key, enabled) {
  if (state.integrationFlagSaving) return;
  state.integrationFlagSaving = key;
  state.integrationFlagError = null;
  renderShell();
  try {
    const data = await api("/api/self-use/integration-flag", {
      method: "POST",
      body: JSON.stringify({ key, enabled: !!enabled }),
    });
    applySelfUseState(data);
    applyCompanionStatus(data);
    await refreshEmbodimentRuntimeStatus();
  } catch (err) {
    state.integrationFlagError = err.message || "更新接入配置失败";
  } finally {
    state.integrationFlagSaving = "";
    renderShell();
  }
}

function integrationConfigFeedback(key) {
  const item = state.integrationConfigFeedback?.[key];
  if (!item) return { text: "", tone: "" };
  if (typeof item === "string") return { text: item, tone: "" };
  return { text: item.text || "", tone: item.tone || "" };
}

function setIntegrationConfigFeedback(key, text, tone = "") {
  if (!key) return;
  state.integrationConfigFeedback = {
    ...(state.integrationConfigFeedback || {}),
    [key]: { text, tone },
  };
}

function integrationConfigFeedbackKey(values) {
  const keys = Object.keys(values || {});
  if (keys.some((key) => key.startsWith("live2d."))) return "live2d";
  if (keys.some((key) => key.startsWith("video_companion."))) return "video_companion";
  return "config";
}

function applySelfUseState(data) {
  if (!data) return;
  if (data.self_use) state.selfUse = data.self_use;
  if (data.chat_gate && state.companionStatus) {
    state.companionStatus = {
      ...state.companionStatus,
      self_use: data.self_use || state.companionStatus.self_use,
      chat_gate: data.chat_gate,
    };
  }
}

function applyCompanionStatus(data) {
  const companion = data?.companion_status || (data?.readiness && data?.chat_gate ? data : null);
  if (!companion) return;
  state.companionStatus = companion;
  if (companion.self_use) state.selfUse = companion.self_use;
  if (companion.llm) state.llmStatus = companion.llm;
  if (companion.video_companion) state.videoCompanionStatus = companion.video_companion;
  if (companion.live2d) state.live2dStatus = companion.live2d;
}

async function setSelfUseIntegrationConfig(values, statusEl = null, options = {}) {
  const feedbackKey = options.feedbackKey || integrationConfigFeedbackKey(values);
  const renderAfter = options.render !== false;
  state.integrationConfigSaving = feedbackKey;
  setIntegrationConfigFeedback(feedbackKey, "保存中...");
  if (statusEl) statusEl.textContent = "保存中...";
  state.integrationFlagError = null;
  try {
    const data = await api("/api/self-use/integration-config", {
      method: "POST",
      body: JSON.stringify({ values }),
    });
    applyCompanionStatus(data);
    await refreshEmbodimentRuntimeStatus();
    setIntegrationConfigFeedback(feedbackKey, "已保存");
    if (statusEl) statusEl.textContent = "已保存";
    return data;
  } catch (err) {
    const message = err.message || "保存接入参数失败";
    state.integrationFlagError = message;
    setIntegrationConfigFeedback(feedbackKey, message, "error");
    if (statusEl) statusEl.textContent = message;
    return null;
  } finally {
    state.integrationConfigSaving = "";
    if (renderAfter) renderShell();
  }
}

async function saveLive2dConfigAndConnect(vtsWsUrl) {
  const feedbackKey = "live2d";
  const data = await setSelfUseIntegrationConfig(
    { "live2d.vts_ws_url": vtsWsUrl },
    null,
    { feedbackKey, render: false },
  );
  if (!data) {
    renderShell();
    return;
  }
  if (!live2dAvailable()) {
    setIntegrationConfigFeedback(feedbackKey, "已保存；请先启用 Live2D 配置");
    renderShell();
    return;
  }
  await live2dConnect({ feedbackKey });
}

async function saveVideoCompanionConfigAndCheck(values) {
  const feedbackKey = "video_companion";
  const data = await setSelfUseIntegrationConfig(values, null, { feedbackKey, render: false });
  if (!data) {
    renderShell();
    return;
  }
  const video = state.videoCompanionStatus || {};
  if (!video.enabled) {
    setIntegrationConfigFeedback(feedbackKey, "已保存；请先启用 Video Companion 配置");
  } else if (video.connected) {
    setIntegrationConfigFeedback(feedbackKey, video.status?.session_active ? "已保存；外部会话运行中" : "已保存；外部服务已连接");
  } else {
    setIntegrationConfigFeedback(feedbackKey, video.error ? `已保存；未连上：${video.error}` : "已保存；等待外部服务启动");
  }
  renderShell();
}

async function refreshEmbodimentRuntimeStatus() {
  await Promise.all([
    loadVoiceConfig(),
    loadLive2dStatus(),
    loadAwarenessStatus(),
  ]);
  await loadCompanionStatus();
}

function voiceAvailable() {
  return !!(state.voiceConfig && state.voiceConfig.enabled && state.voiceConfig.available);
}

function voiceAutoPlayEnabled() {
  return voiceAvailable() && state.voiceConfig?.auto_play !== false;
}

function voicePlaybackIsCurrent(playback) {
  return !!playback && activeVoicePlayback === playback && !playback.interrupted;
}

function sameVoiceMessageId(left, right) {
  return left !== null && left !== undefined
    && right !== null && right !== undefined
    && String(left) === String(right);
}

function localHttpVoiceStreamingEnabled() {
  const provider = String(state.voiceConfig?.tts_provider || state.voiceConfig?.provider || "").trim().toLowerCase();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  return provider === "local_http" && !!AudioContextClass && typeof ReadableStream !== "undefined";
}

function live2dLipSyncReady() {
  const status = state.live2dStatus || {};
  if (!live2dConnected() || status.lip_sync_enabled === false) return false;
  if (!live2dBindingMatchesCurrent(personaEmbodimentProfile(state.activePersona))) return false;
  const target = String(status.lip_sync_parameter || "MouthOpen").trim().toLowerCase();
  return (status.available_parameters || []).some((item) => String(item.name || "").trim().toLowerCase() === target);
}

async function sendLive2dLipSyncValue(value) {
  try {
    const result = await api("/api/live2d/lip-sync", {
      method: "POST",
      body: JSON.stringify({ value: Math.max(0, Math.min(Number(value) || 0, 1)) }),
    });
    return !!result.applied;
  } catch {
    return false;
  }
}

async function startLive2dLipSync(audio, playback) {
  if (!live2dLipSyncReady()) return null;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return null;

  let context = null;
  try {
    context = new AudioContextClass();
    const source = context.createMediaElementSource(audio);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.45;
    source.connect(analyser);
    analyser.connect(context.destination);
    if (context.state === "suspended") await context.resume();

    const samples = new Uint8Array(analyser.fftSize);
    const gain = Math.max(0.1, Math.min(Number(state.live2dStatus?.lip_sync_gain) || 2.2, 10));
    let stopped = false;
    let closed = false;
    let animationFrame = null;
    let requestBusy = false;
    let lastSentAt = 0;
    let smoothed = 0;
    let consecutiveFailures = 0;

    const tick = (timestamp) => {
      if (stopped || !voicePlaybackIsCurrent(playback)) return;
      analyser.getByteTimeDomainData(samples);
      let energy = 0;
      for (const sample of samples) {
        const normalized = (sample - 128) / 128;
        energy += normalized * normalized;
      }
      const rms = Math.sqrt(energy / samples.length);
      const target = Math.max(0, Math.min((rms - 0.012) * gain, 1));
      smoothed = target > smoothed ? smoothed * 0.25 + target * 0.75 : smoothed * 0.72 + target * 0.28;
      if (!requestBusy && timestamp - lastSentAt >= 80) {
        requestBusy = true;
        lastSentAt = timestamp;
        void sendLive2dLipSyncValue(smoothed).then((applied) => {
          consecutiveFailures = applied ? 0 : consecutiveFailures + 1;
          if (consecutiveFailures >= 3) {
            stopped = true;
            if (animationFrame !== null) cancelAnimationFrame(animationFrame);
            animationFrame = null;
          }
        }).finally(() => {
          requestBusy = false;
        });
      }
      animationFrame = requestAnimationFrame(tick);
    };
    animationFrame = requestAnimationFrame(tick);

    return {
      stop: async () => {
        if (closed) return;
        closed = true;
        stopped = true;
        if (animationFrame !== null) cancelAnimationFrame(animationFrame);
        if (consecutiveFailures < 3) await sendLive2dLipSyncValue(0);
        try { source.disconnect(); } catch {}
        try { analyser.disconnect(); } catch {}
        try { await context.close(); } catch {}
      },
    };
  } catch {
    if (context) {
      try { await context.close(); } catch {}
    }
    return null;
  }
}

function interruptVoicePlayback() {
  const playback = activeVoicePlayback;
  if (!playback) return false;
  playback.interrupted = true;
  if (playback.controller) playback.controller.abort();
  if (playback.lipSync) {
    const lipSync = playback.lipSync;
    playback.lipSync = null;
    void lipSync.stop();
  }
  if (playback.audio) {
    try {
      playback.audio.pause();
      playback.audio.currentTime = 0;
    } catch {
      // The browser may reject seeking before media metadata is available.
    }
  }
  if (playback.streamSources) {
    for (const source of playback.streamSources) {
      try { source.stop(); } catch {}
    }
    playback.streamSources.clear();
  }
  if (playback.streamContext) {
    try { void playback.streamContext.close(); } catch {}
    playback.streamContext = null;
  }
  if (playback.finish) playback.finish();
  state.voicePlaying = null;
  state.voicePlaybackPhase = null;
  state.voicePlan = null;
  state.voicePlanMessageId = null;
  return true;
}

function messageExpressionLabels(message) {
  return (message.expressions || []).map(function(e) {
    return e.label || e.expression_type;
  }).filter(Boolean);
}

async function loadVoiceSpeechPlan(text, expressionLabels, messageId, playback = null) {
  try {
    const plan = await api("/api/voice/speech-plan", {
      method: "POST",
      body: JSON.stringify({
        reply_text: text,
        expression_labels: expressionLabels,
        persona_id: state.activePersona?.id || null,
      }),
    });
    if (playback && !voicePlaybackIsCurrent(playback)) return null;
    state.voicePlan = plan;
    state.voicePlanMessageId = messageId;
    return plan;
  } catch {
    if (!playback || voicePlaybackIsCurrent(playback)) {
      state.voicePlan = null;
      state.voicePlanMessageId = null;
    }
    return null;
  }
}

function incrementalLocalVoiceEnabled(plan) {
  const provider = String(state.voiceConfig?.tts_provider || state.voiceConfig?.provider || "").trim().toLowerCase();
  const chunkCount = Number(plan?.chunk_count || plan?.utterances?.length || 0);
  return provider === "local_http" && chunkCount > 1;
}

async function fetchVoiceChunkAudio(chunkIndex, text, expressionLabels, playback) {
  const isolated = tabSessionMode();
  const token = tabSessionToken();
  const headers = { "Content-Type": "application/json" };
  if (isolated && token) headers.Authorization = `Bearer ${token}`;
  const startedAt = performance.now();
  const res = await fetch(`/api/voice/tts-chunk/${chunkIndex}`, {
    method: "POST",
    credentials: isolated ? "omit" : "same-origin",
    headers,
    body: JSON.stringify({
      reply_text: text,
      expression_labels: expressionLabels,
      persona_id: state.activePersona?.id || null,
    }),
    signal: playback.controller.signal,
  });
  if (!res.ok) {
    const err = await res.json().catch(function() { return {}; });
    throw new Error(err.detail?.error || err.detail || "语音生成失败");
  }
  const blob = await res.blob();
  if (!blob || blob.size === 0) throw new Error("语音数据为空");
  const serverMs = Number(res.headers.get("X-LING-TTS-Generation-Ms"));
  return {
    blob,
    clientMs: Math.max(0, Math.round(performance.now() - startedAt)),
    serverMs: Number.isFinite(serverMs) && serverMs >= 0 ? serverMs : null,
  };
}

function appendAudioBytes(left, right) {
  const combined = new Uint8Array(left.length + right.length);
  combined.set(left, 0);
  combined.set(right, left.length);
  return combined;
}

function parseStreamingWavHeader(bytes) {
  if (bytes.length < 44) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const tag = (offset, length) => String.fromCharCode(...bytes.slice(offset, offset + length));
  if (tag(0, 4) !== "RIFF" || tag(8, 4) !== "WAVE" || tag(36, 4) !== "data") {
    throw new Error("local streaming TTS returned an invalid WAV header");
  }
  const channels = view.getUint16(22, true);
  const sampleRate = view.getUint32(24, true);
  const bitsPerSample = view.getUint16(34, true);
  if (!channels || !sampleRate || bitsPerSample !== 16) {
    throw new Error("local streaming TTS returned an unsupported WAV format");
  }
  return { channels, sampleRate, headerBytes: 44 };
}

async function playStreamingLocalVoice(message, text, expressionLabels, playback, buttonEl) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error("browser does not support streaming audio playback");

  const isolated = tabSessionMode();
  const token = tabSessionToken();
  const headers = { "Content-Type": "application/json" };
  if (isolated && token) headers.Authorization = `Bearer ${token}`;

  const requestStartedAt = performance.now();
  const response = await fetch("/api/voice/tts-stream", {
    method: "POST",
    credentials: isolated ? "omit" : "same-origin",
    headers,
    body: JSON.stringify({
      reply_text: text,
      expression_labels: expressionLabels,
      persona_id: state.activePersona?.id || null,
    }),
    signal: playback.controller.signal,
  });
  if (!voicePlaybackIsCurrent(playback)) return false;
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "local streaming TTS failed");
  }
  if (!response.body) throw new Error("browser did not expose the streaming audio body");

  const context = new AudioContextClass();
  playback.streamContext = context;
  playback.streamSources = new Set();
  let pendingBytes = new Uint8Array();
  let wav = null;
  let nextStartAt = 0;
  let firstAudioScheduled = false;
  let endTimer = null;

  const stopScheduledAudio = () => {
    for (const source of playback.streamSources) {
      try { source.stop(); } catch {}
    }
    playback.streamSources.clear();
  };

  const waitForScheduledAudio = () => new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (endTimer !== null) window.clearTimeout(endTimer);
      playback.finish = null;
      resolve();
    };
    playback.finish = finish;
    const waitMs = Math.max(0, Math.ceil((nextStartAt - context.currentTime) * 1000) + 40);
    endTimer = window.setTimeout(finish, waitMs);
  });

  const schedulePcm = (pcmBytes) => {
    if (!wav || !pcmBytes.length) return;
    const bytesPerFrame = wav.channels * 2;
    const usableLength = pcmBytes.length - (pcmBytes.length % bytesPerFrame);
    if (!usableLength) return;
    const frames = usableLength / bytesPerFrame;
    const buffer = context.createBuffer(wav.channels, frames, wav.sampleRate);
    const view = new DataView(pcmBytes.buffer, pcmBytes.byteOffset, usableLength);
    for (let channel = 0; channel < wav.channels; channel += 1) {
      const output = buffer.getChannelData(channel);
      for (let frame = 0; frame < frames; frame += 1) {
        output[frame] = view.getInt16((frame * wav.channels + channel) * 2, true) / 32768;
      }
    }
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.onended = () => playback.streamSources.delete(source);
    const startAt = Math.max(context.currentTime + 0.06, nextStartAt || 0);
    source.start(startAt);
    nextStartAt = startAt + buffer.duration;
    playback.streamSources.add(source);
    if (!firstAudioScheduled) {
      firstAudioScheduled = true;
      message.performance = {
        ...(message.performance && typeof message.performance === "object" ? message.performance : {}),
        tts_client_ms: Math.max(0, Math.round(performance.now() - requestStartedAt)),
        tts_stream_first_audio_ms: Math.max(0, Math.round(performance.now() - requestStartedAt)),
      };
      state.voicePlaybackPhase = "playing";
      renderShell();
      if (buttonEl) buttonEl.textContent = "播放中...";
      refreshRuntimeIndicators();
      void applyLive2dRuntimeState("speaking");
    }
  };

  try {
    if (context.state === "suspended") await context.resume();
    const reader = response.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!voicePlaybackIsCurrent(playback)) return false;
      if (value?.length) pendingBytes = appendAudioBytes(pendingBytes, value);
      if (!wav) {
        wav = parseStreamingWavHeader(pendingBytes);
        if (!wav) continue;
        pendingBytes = pendingBytes.slice(wav.headerBytes);
      }
      const bytesPerFrame = wav.channels * 2;
      const usableLength = pendingBytes.length - (pendingBytes.length % bytesPerFrame);
      if (usableLength) {
        schedulePcm(pendingBytes.slice(0, usableLength));
        pendingBytes = pendingBytes.slice(usableLength);
      }
    }
    if (!voicePlaybackIsCurrent(playback)) return false;
    if (!firstAudioScheduled) throw new Error("local streaming TTS returned no audio frames");
    await waitForScheduledAudio();
    return !playback.interrupted;
  } finally {
    if (endTimer !== null) window.clearTimeout(endTimer);
    stopScheduledAudio();
    playback.finish = null;
    playback.streamSources = null;
    playback.streamContext = null;
    try { await context.close(); } catch {}
  }
}

async function playVoiceAudioBlob(blob, playback, onStarted = null) {
  const audioUrl = URL.createObjectURL(blob);
  try {
    const audio = new Audio(audioUrl);
    playback.audio = audio;
    const playbackFinished = new Promise(function(resolve) {
      let settled = false;
      const finish = function(value) {
        if (settled) return;
        settled = true;
        playback.finish = null;
        resolve(value);
      };
      playback.finish = function() { finish(); };
      audio.onended = function() { finish(); };
      audio.onerror = function() { finish({ error: new Error("浏览器无法播放此音频") }); };
    });
    await audio.play();
    if (!voicePlaybackIsCurrent(playback)) return;
    playback.lipSync = await startLive2dLipSync(audio, playback);
    if (!voicePlaybackIsCurrent(playback)) return;
    if (onStarted) await onStarted();
    const playbackResult = await playbackFinished;
    if (playbackResult?.error) throw playbackResult.error;
  } finally {
    if (playback.lipSync) {
      const lipSync = playback.lipSync;
      playback.lipSync = null;
      await lipSync.stop();
    }
    playback.audio = null;
    playback.finish = null;
    URL.revokeObjectURL(audioUrl);
  }
}

async function playIncrementalLocalVoice(message, text, expressionLabels, playback, buttonEl) {
  const totalChunks = Number(state.voicePlan?.chunk_count || state.voicePlan?.utterances?.length || 0);
  if (totalChunks < 2) return false;
  let nextAudio = fetchVoiceChunkAudio(0, text, expressionLabels, playback);
  for (let index = 0; index < totalChunks; index += 1) {
    const current = await nextAudio;
    if (!voicePlaybackIsCurrent(playback)) return false;
    if (index + 1 < totalChunks) {
      nextAudio = fetchVoiceChunkAudio(index + 1, text, expressionLabels, playback);
    }
    if (index === 0) {
      message.performance = {
        ...(message.performance && typeof message.performance === "object" ? message.performance : {}),
        tts_client_ms: current.clientMs,
        ...(current.serverMs !== null ? { tts_server_ms: current.serverMs } : {}),
      };
    }
    await playVoiceAudioBlob(current.blob, playback, async () => {
      if (index !== 0) return;
      state.voicePlaybackPhase = "playing";
      renderShell();
      if (buttonEl) buttonEl.textContent = "播放中…";
      refreshRuntimeIndicators();
      await applyLive2dRuntimeState("speaking");
    });
    if (!voicePlaybackIsCurrent(playback)) return false;
  }
  return !playback.interrupted;
}

async function playMessageVoice(message, buttonEl) {
  if (state.voicePlaying) return;

  const text = String(message.content || "").trim();
  if (!text) return;

  const messageId = message.id;
  const playback = {
    id: ++voicePlaybackSequence,
    messageId,
    interrupted: false,
    controller: new AbortController(),
    audio: null,
    lipSync: null,
    finish: null,
  };
  activeVoicePlayback = playback;
  let voicePlaybackCompleted = false;
  const expressionLabels = messageExpressionLabels(message);
  state.voicePlaying = messageId;
  state.voicePlaybackPhase = "preparing";
  state.voiceError = null;
  state.voiceErrorMessageId = null;
  state.voicePlan = null;
  state.voicePlanMessageId = null;
  try {
    const speechPlan = await loadVoiceSpeechPlan(text, expressionLabels, messageId, playback);
    if (!voicePlaybackIsCurrent(playback)) return;
    await applyLive2dRuntimeState("thinking");
    if (!voicePlaybackIsCurrent(playback)) return;
    renderShell();
    if (buttonEl) {
      buttonEl.textContent = "准备中...";
      buttonEl.disabled = true;
    }

    if (localHttpVoiceStreamingEnabled()) {
      voicePlaybackCompleted = await playStreamingLocalVoice(
        message,
        text,
        expressionLabels,
        playback,
        buttonEl,
      );
      return;
    }

    // Local GPT-SoVITS returns complete MP3 files. For a multi-sentence reply,
    // request the next utterance while the current one is playing instead of
    // waiting for one long synthesis job to finish.
    if (incrementalLocalVoiceEnabled(speechPlan)) {
      voicePlaybackCompleted = await playIncrementalLocalVoice(
        message,
        text,
        expressionLabels,
        playback,
        buttonEl,
      );
      return;
    }

    const isolated = tabSessionMode();
    const token = tabSessionToken();
    const headers = {};
    if (isolated && token) headers.Authorization = `Bearer ${token}`;

    const voiceRequestStartedAt = performance.now();
    const res = await fetch("/api/voice/tts-reply", {
      method: "POST",
      credentials: isolated ? "omit" : "same-origin",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({
        reply_text: text,
        expression_labels: expressionLabels,
        persona_id: state.activePersona?.id || null,
      }),
      signal: playback.controller.signal,
    });
    if (!voicePlaybackIsCurrent(playback)) return;

    if (!res.ok) {
      const err = await res.json().catch(function() { return {}; });
      throw new Error(err.detail || "语音生成失败");
    }

    const audioBlob = await res.blob();
    if (!voicePlaybackIsCurrent(playback)) return;
    if (!audioBlob || audioBlob.size === 0) {
      throw new Error("语音数据为空");
    }

    const serverGenerationMs = Number(res.headers.get("X-LING-TTS-Generation-Ms"));
    message.performance = {
      ...(message.performance && typeof message.performance === "object" ? message.performance : {}),
      tts_client_ms: Math.max(0, Math.round(performance.now() - voiceRequestStartedAt)),
      ...(Number.isFinite(serverGenerationMs) && serverGenerationMs >= 0 ? { tts_server_ms: serverGenerationMs } : {}),
    };

    const audioUrl = URL.createObjectURL(audioBlob);
    try {
      var audio = new Audio(audioUrl);
      playback.audio = audio;

      const playbackFinished = new Promise(function(resolve) {
        let settled = false;
        const finish = function(callback, value) {
          if (settled) return;
          settled = true;
          playback.finish = null;
          callback(value);
        };
        playback.finish = function() { finish(resolve); };
        audio.onended = function() { finish(resolve); };
        audio.onerror = function() {
          finish(resolve, { error: new Error("浏览器无法播放此音频") });
        };
      });
      try {
        await audio.play();
      } catch (error) {
        playback.finish = null;
        throw error;
      }
      if (!voicePlaybackIsCurrent(playback)) return;
      playback.lipSync = await startLive2dLipSync(audio, playback);
      if (!voicePlaybackIsCurrent(playback)) return;
      state.voicePlaybackPhase = "playing";
      renderShell();
      if (buttonEl) buttonEl.textContent = "播放中...";
      refreshRuntimeIndicators();
      await applyLive2dRuntimeState("speaking");
      if (!voicePlaybackIsCurrent(playback)) return;
      const playbackResult = await playbackFinished;
      if (playbackResult?.error) throw playbackResult.error;
      voicePlaybackCompleted = !playback.interrupted;
    } finally {
      if (playback.lipSync) {
        const lipSync = playback.lipSync;
        playback.lipSync = null;
        await lipSync.stop();
      }
      playback.audio = null;
      playback.finish = null;
      URL.revokeObjectURL(audioUrl);
    }
  } catch (err) {
    if (!playback.interrupted) {
      state.voiceError = err.message || "语音播放失败";
      state.voiceErrorMessageId = messageId;
      if (buttonEl) {
        buttonEl.textContent = "播放失败";
        buttonEl.classList.add("voice-error");
      }
    }
  } finally {
    if (activeVoicePlayback === playback) activeVoicePlayback = null;
    if (sameVoiceMessageId(state.voicePlaying, messageId)) {
      state.voicePlaying = null;
      state.voicePlaybackPhase = null;
    }
    if (Number(state.voicePlanMessageId) === Number(messageId)) {
      state.voicePlan = null;
      state.voicePlanMessageId = null;
    }
    if (playback.interrupted) {
      // A newer interaction owns the runtime state and must not be overwritten here.
    } else if (voicePlaybackCompleted && !state.voiceError) {
      await applyLive2dRuntimeState("idle");
      await syncCompanionRuntime({ applyLive2d: false });
    } else {
      await syncCompanionRuntime({ applyLive2d: true });
    }
    if (buttonEl) {
      buttonEl.disabled = false;
      if (state.voicePlaying === null && !state.voiceError) {
        buttonEl.textContent = "播放语音";
      }
    }
    renderShell();
  }
}

function renderVoiceButton(message) {
  if (!voiceAvailable()) return null;

  var isPlaying = sameVoiceMessageId(state.voicePlaying, message.id);
  var hasError = !isPlaying && sameVoiceMessageId(state.voiceErrorMessageId, message.id) && !!state.voiceError;
  var label = isPlaying ? "播放中..." : "播放语音";

  var btn = h("button", {
    type: "button",
    class: "voice-play-btn" + (hasError ? " voice-error" : ""),
    text: label,
    disabled: isPlaying ? "disabled" : null,
    onclick: function(event) {
      event.stopPropagation();
      playMessageVoice(message, event.currentTarget);
    },
  });

  if (hasError) {
    btn.textContent = "播放失败";
    btn.title = state.voiceError || "语音播放失败";
  }

  return btn;
}

async function loadLive2dStatus() {
  try {
    const data = await api("/api/live2d/status");
    state.live2dStatus = data;
  } catch {
    state.live2dStatus = { enabled: false, connected: false };
  }
}

function live2dAvailable() {
  return !!(state.live2dStatus && state.live2dStatus.enabled);
}

function live2dConnected() {
  var s = state.live2dStatus || {};
  return !!(s.enabled && s.connected && s.authenticated && !s.last_error && s.capabilities_stale !== true);
}

function live2dBindingMatchesCurrent(embodiment = null) {
  if (state.live2dStatus?.capabilities_stale === true) return false;
  const modelId = String(embodiment?.live2dModelId || "").trim().toLowerCase();
  const current = state.live2dStatus?.current_model || {};
  if (!modelId || current.modelLoaded === false) return false;
  return [current.modelID, current.modelName, current.vtsModelName, current.modelFileName]
    .map((value) => String(value || "").trim().toLowerCase())
    .filter(Boolean)
    .includes(modelId);
}

function live2dStatusText(embodiment = null) {
  var s = state.live2dStatus || {};
  if (!s.enabled) return "未启用";
  if (s.connecting) return "正在连接 VTube Studio";
  if (embodiment && !embodiment.live2dModelId) return "模型未绑定";
  if (!s.websockets_available && !s.connected) return "需安装 websockets 库 (pip install websockets)";
  if (!s.connected) return "未连接 VTube Studio";
  if (!s.authenticated) return "认证失败";
  if (s.last_error) return "已连接（" + s.last_error + "）";
  if (s.capabilities_stale === true) return "已连接，模型与动作状态需刷新";
  if (embodiment && !live2dCurrentModelBinding().label) return "已连接，当前未加载模型";
  if (embodiment && !live2dBindingMatchesCurrent(embodiment)) {
    return `当前 ${live2dCurrentModelBinding().label || "模型"} 与绑定 ${embodiment.live2dModelId} 不一致`;
  }
  return "已连接";
}

function live2dStatusClass(embodiment = null) {
  var s = state.live2dStatus || {};
  if (!s.enabled) return "off";
  if (s.connecting) return "waiting";
  if (s.connected && s.authenticated && !s.last_error && s.capabilities_stale !== true && (!embodiment || live2dBindingMatchesCurrent(embodiment))) return "ok";
  return "error";
}

async function live2dConnect(options = {}) {
  const feedbackKey = options.feedbackKey || "";
  if (feedbackKey) setIntegrationConfigFeedback(feedbackKey, "正在连接 VTube Studio...");
  try {
    var data = await api("/api/live2d/connect", { method: "POST" });
    state.live2dStatus = data.status;
    if (feedbackKey) {
      setIntegrationConfigFeedback(feedbackKey, live2dConnected() ? "已连接 VTube Studio" : live2dStatusText());
    }
    renderShell();
  } catch (err) {
    state.live2dStatus = (state.live2dStatus || {});
    state.live2dStatus.last_error = err.message;
    state.live2dStatus.connected = false;
    if (feedbackKey) setIntegrationConfigFeedback(feedbackKey, err.message || "连接 VTube Studio 失败", "error");
    renderShell();
  }
}

async function live2dDisconnect() {
  try {
    var data = await api("/api/live2d/disconnect", { method: "POST" });
    state.live2dStatus = data.status;
    renderShell();
  } catch (err) {
    state.live2dStatus = (state.live2dStatus || {});
    state.live2dStatus.last_error = err.message;
    renderShell();
  }
}

async function live2dRefreshCapabilities(statusEl = null) {
  if (statusEl) statusEl.textContent = "正在读取 VTube Studio...";
  try {
    const data = await api("/api/live2d/refresh", { method: "POST" });
    state.live2dStatus = data.status;
    await loadCompanionStatus();
    if (statusEl) statusEl.textContent = "已刷新模型与动作";
    renderShell();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message || "刷新 VTube Studio 失败";
  }
}

async function live2dTestExpression() {
  try {
    await api("/api/live2d/apply-expression", {
      method: "POST",
      body: JSON.stringify({ label: "微笑", expression_type: "mood" }),
    });
  } catch (err) {
    alert("测试失败：" + (err.message || "未知错误"));
  }
}

function renderLive2dPanel(persona) {
  if (!live2dAvailable()) return null;

  var st = state.live2dStatus || {};
  var connected = live2dConnected();
  var statusLabel = live2dStatusText();
  var statusCls = live2dStatusClass();
  var capabilityLabel = connected
    ? "已加载热键 " + (st.available_hotkey_count || 0) + " 个，表情 " + (st.available_expression_count || 0) + " 个"
    : "";

  return h("section", { class: "persona-expression-card" }, [
    h("div", {}, [
      h("strong", { text: "Live2D 形象" }),
      h("p", { text: "连接到 VTube Studio，让 TA 通过表情和动作回应你。" }),
    ]),
    h("div", { class: "live2d-status-row" }, [
      h("span", { class: "live2d-status-dot " + statusCls }),
      h("small", { text: statusLabel }),
    ]),
    connected ? h("small", { class: "muted", text: capabilityLabel }) : null,
    st.last_error && !connected ? h("small", { class: "error", text: st.last_error }) : null,
    h("div", { class: "live2d-actions" }, [
      connected
        ? h("button", { type: "button", class: "ghost compact", text: "断开", onclick: live2dDisconnect })
        : h("button", { type: "button", class: "compact", text: "连接 VTube Studio", onclick: live2dConnect }),
      connected
        ? h("button", { type: "button", class: "compact", text: "测试表情 微笑", onclick: live2dTestExpression })
        : null,
    ]),
  ]);
}

function messageSegments(message) {
  const content = String(message.content || "").trim();
  // A complete server reply must remain one message bubble.  Splitting it here
  // only creates several bubbles at the same instant; it is not streaming.
  return [content];
}

function splitAssistantContent(content) {
  const text = String(content || "").replace(/\n{3,}/g, "\n\n").trim();
  if (text.length <= 72 && !text.includes("\n")) return [text];
  const rawParts = text
    .split(/(?<=[。！？!?~～])\s+|(?<=[。！？!?~～])|[\r\n]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const parts = rawParts.length ? rawParts : [text];
  const segments = [];
  let current = "";
  for (const part of parts) {
    if (!current) {
      current = part;
      continue;
    }
    if ((current + part).length <= 56) {
      current += part;
    } else {
      segments.push(current);
      current = part;
    }
  }
  if (current) segments.push(current);
  return segments.flatMap((segment) => splitLongSegment(segment, 92)).slice(0, 8);
}

function splitLongSegment(text, maxLength) {
  if (text.length <= maxLength) return [text];
  const pieces = [];
  let rest = text;
  while (rest.length > maxLength) {
    let cut = Math.max(rest.lastIndexOf("，", maxLength), rest.lastIndexOf("、", maxLength), rest.lastIndexOf("；", maxLength));
    if (cut < 28) cut = maxLength;
    pieces.push(rest.slice(0, cut + 1).trim());
    rest = rest.slice(cut + 1).trim();
  }
  if (rest) pieces.push(rest);
  return pieces;
}

function renderExpressionStrip(expressions) {
  return h("div", { class: "expression-strip" }, expressions.slice(0, 3).map((item) => (
    renderExpressionPill(item)
  )));
}

function renderExpressionPill(item) {
  const asset = expressionAssetFor(item);
  const type = asset?.expression_type || item.expression_type || item.type || "gesture";
  const label = asset?.display_text || item.label || item.source_text || "";
  const icon = asset?.icon || "";
  const assetKind = asset?.asset_kind || "text_badge";
  const intensity = asset?.intensity ? `intensity-${asset.intensity}` : "intensity-1";
  return h("span", {
    class: `expression-pill ${type} ${assetKind} ${intensity}`,
    title: asset?.description || label,
  }, [
    icon ? h("span", { class: "expression-icon", text: icon }) : null,
    h("span", { text: label }),
  ]);
}

function expressionAssetFor(item) {
  const type = String(item.expression_type || item.type || "").trim();
  const label = String(item.label || "").trim();
  return (state.expressionAssets || []).find((asset) => (
    String(asset.expression_type || "") === type && String(asset.label || "") === label
  ));
}

function replaceLocalMessage(localId, replacement) {
  state.messages = state.messages.map((message) => message.local_id === localId ? replacement : message);
}

function friendlyChatError(message) {
  const text = String(message || "");
  if (text.includes("429") || text.includes("Too Many Requests") || text.includes("服务暂时")) {
    return "服务现在有点拥堵，刚才这句话已经留在当前会话里。稍后再试一次就好。";
  }
  return "刚才没有成功发出去。稍后再试一次。";
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function createClientMessageId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
}

function formatMessageTime(value) {
  if (!value) return "";
  const date = new Date(Number(value) * 1000);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatMessagePerformance(metrics) {
  if (!selfUseMode() || !metrics || typeof metrics !== "object") return "";
  const toMs = (value) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) && numeric >= 0 ? numeric : 0;
  };
  const total = toMs(metrics.client_total_ms || metrics.total_ms);
  if (total < 100) return "";
  const model = toMs(metrics.model_ms);
  const preparation = toMs(metrics.preparation_ms);
  const tts = toMs(metrics.tts_client_ms || metrics.tts_server_ms);
  const formatSeconds = (milliseconds) => `${(milliseconds / 1000).toFixed(milliseconds >= 10000 ? 0 : 1)}s`;
  const parts = [`响应 ${formatSeconds(total)}`];
  if (model >= 100) parts.push(`模型 ${formatSeconds(model)}`);
  if (preparation >= 300) parts.push(`准备 ${formatSeconds(preparation)}`);
  if (tts >= 100) parts.push(`语音 ${formatSeconds(tts)}`);
  return parts.join(" · ");
}

function messageDateKey(value) {
  if (!value) return "";
  const date = new Date(Number(value) * 1000);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

function formatMessageDate(value) {
  if (!value) return "";
  const date = new Date(Number(value) * 1000);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "今天";
  if (date.toDateString() === yesterday.toDateString()) return "昨天";
  if (date.getFullYear() === today.getFullYear()) {
    return date.toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
  }
  return date.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" });
}

function formatListTime(value) {
  if (!value) return "";
  const date = new Date(Number(value) * 1000);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  if (sameDay) return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  const sameYear = date.getFullYear() === now.getFullYear();
  if (sameYear) return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
  return date.toLocaleDateString("zh-CN", { year: "2-digit", month: "2-digit", day: "2-digit" });
}

function avatar(name, url) {
  const initial = avatarText(name);
  const el = h("div", { class: "avatar", text: url ? "" : initial });
  if (url) {
    el.append(h("img", { src: url, alt: String(name || "avatar") }));
  }
  return el;
}

function groupAvatar(group) {
  const members = group?.members || [];
  const first = members[0] || {};
  const second = members[1] || {};
  return h("div", { class: "group-avatar" }, [
    avatar(first.display_name || first.name || "群", first.avatar_url),
    avatar(second.display_name || second.name || "+", second.avatar_url),
  ]);
}

function groupMemberName(personaId) {
  const member = (state.activeGroupConversation?.members || []).find((item) => Number(item.persona_id) === Number(personaId));
  return member?.display_name || member?.name || "";
}

function groupMemberAvatar(personaId) {
  const member = (state.activeGroupConversation?.members || []).find((item) => Number(item.persona_id) === Number(personaId));
  return member?.avatar_url || "";
}

function avatarText(name) {
  const text = String(name || "").trim();
  if (!text) return "忆";
  if (/^[A-Za-z0-9_\-\s]+$/.test(text)) return text.replace(/\s+/g, "").slice(0, 2).toUpperCase();
  return text.slice(0, 1);
}

function groupTitle(key) {
  return {
    atmosphere: "氛围",
    relationship: "关系",
    style: "说话方式",
    boundaries: "边界",
  }[key] || key;
}

function groupHint(key) {
  return {
    atmosphere: "TA 在场时的感觉",
    relationship: "你们大概怎么相处",
    style: "回复的节奏和语气",
    boundaries: "先划清不舒服的地方",
  }[key] || "";
}

async function logout() {
  const isolated = tabSessionMode();
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  resetClientState();
  prepareAuthMode(false);
  bootstrap();
}

async function switchAccountInThisTab() {
  if (tabSessionMode() && tabSessionToken()) {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  }
  prepareAuthMode(true);
  resetClientState();
  renderAuth("login");
}

function resetClientState() {
  stopCompanionStatusPolling();
  interruptVoicePlayback();
  clearLive2dExpressionReset();
  if (easyVtuberCaptureStream) {
    easyVtuberCaptureStream.getTracks().forEach((track) => track.stop());
    easyVtuberCaptureStream = null;
  }
  state = {
    user: null,
    profile: null,
    selfUse: null,
    options: null,
    expressionAssets: [],
    personas: [],
    deletedPersonas: [],
    personaGrowth: {},
    loadingGrowthPersonaId: null,
    conversations: [],
    archivedConversations: [],
    groupConversations: [],
    archivedGroupConversations: [],
    activePersona: null,
    activeConversationId: null,
    activeGroupConversationId: null,
    activeGroupConversation: null,
    messages: [],
    groupMessages: [],
    view: "chat",
    editingPersona: false,
    profileOpen: false,
    personaPanelOpen: false,
    threadPanelOpen: false,
    deletedPanelOpen: false,
    privacyOpen: false,
    integrationOpen: false,
    groupCreateOpen: false,
    groupSettingsOpen: false,
    editingConversationId: null,
    showArchived: false,
    showArchivedGroups: false,
    conversationSearch: "",
    focusComposer: false,
    composerFocused: false,
    composerDraft: "",
    sending: false,
    voiceConfig: null,
    voicePlaying: null,
    voicePlaybackPhase: null,
    voiceError: null,
    voiceErrorMessageId: null,
    voicePlan: null,
    voicePlanMessageId: null,
    live2dStatus: null,
    presenceStatus: null,
    presenceSaving: false,
    presenceControlError: null,
    consents: [],
    cameraStatus: null,
    screenStatus: null,
    proactiveStatus: null,
    videoCompanionStatus: null,
    companionStatus: null,
    llmStatus: null,
    chatGateSaving: false,
    chatGateError: null,
    llmProbeSaving: false,
    integrationFlagSaving: "",
    integrationFlagError: null,
    integrationConfigSaving: "",
    integrationConfigFeedback: {},
    easyVtuberOpening: false,
    easyVtuberCaptureRequesting: false,
    easyVtuberCaptureActive: false,
    easyVtuberFeedback: "",
    privacyPolicy: null,
    cameraPreviewActive: false,
  };
}

function scrollChat() {
  requestAnimationFrame(() => {
    const log = document.getElementById("chat-log");
    if (log) log.scrollTop = log.scrollHeight;
  });
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (state.privacyOpen) {
    state.privacyOpen = false;
    if (state.user) renderShell();
    else renderAuth("login");
    return;
  }
  if (state.profileOpen || state.personaPanelOpen || state.threadPanelOpen || state.deletedPanelOpen || state.groupCreateOpen) {
    state.profileOpen = false;
    state.personaPanelOpen = false;
    state.threadPanelOpen = false;
    state.deletedPanelOpen = false;
    state.groupCreateOpen = false;
    state.editingPersona = false;
    renderShell();
    return;
  }
  if (state.view === "forge" && state.activePersona) {
    state.view = "chat";
    state.editingPersona = false;
    renderShell();
  }
});

registerServiceWorker();
bootstrap();
