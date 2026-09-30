// This file is where the "connect the website to the backend" part
// actually happens. Every fetch() call below hits a URL that app/main.py
// already defines -- the website doesn't know or care that the backend
// is Python; it only speaks HTTP, which is what makes frontend/backend
// separation work at all.

let sessionId = localStorage.getItem("voice_erp_session") || crypto.randomUUID();
localStorage.setItem("voice_erp_session", sessionId);
let historyScope = "demo";
const historyKey = () => `voice_erp_history_${historyScope}_${sessionId}`;
const historyLimit = 80;
let authRequired = false;
let currentUser = null;
let conversationHistory = [];

const chatLog = document.getElementById("chat-log");
const textInput = document.getElementById("text-input");
const inputRow = document.getElementById("input-row");
const micBtn = document.getElementById("mic-btn");
const contextSelect = document.getElementById("context-select");
const contextLabel = document.getElementById("context-label");
const statusEl = document.getElementById("status");
const healthDot = document.getElementById("health-dot");
const healthLabel = document.getElementById("health-label");
const dashboardKpis = document.getElementById("dashboard-kpis");
const inventorySearch = document.getElementById("inventory-search");
const lowStockOnly = document.getElementById("low-stock-only");
const inventoryList = document.getElementById("inventory-list");
const loginForm = document.getElementById("login-form");
const authUser = document.getElementById("auth-user");
const logoutBtn = document.getElementById("logout-btn");
const signinScreen = document.getElementById("signin-screen");
const appShell = document.getElementById("app-shell");
const signinStatus = document.getElementById("signin-status");
const demoAccess = document.getElementById("demo-access");
const demoBtn = document.getElementById("demo-btn");
const micLabel = document.querySelector(".mic-label");
const reportPeriod = document.getElementById("report-period");
const salesCsvLink = document.getElementById("download-sales-csv");
const salesPdfLink = document.getElementById("download-sales-pdf");
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let speechRecognition = null;
let contextMode = "general";
let contextOptions = { employees: [], inventory: [], sales_periods: [] };

function selectedContextValue() {
  return contextSelect ? contextSelect.value : "";
}

function addMessage(text, kind) {
  const el = document.createElement("div");
  el.className = "msg " + kind;
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  conversationHistory.push({ text, kind });
  conversationHistory = conversationHistory.slice(-historyLimit);
  try {
    localStorage.setItem(historyKey(), JSON.stringify(conversationHistory));
  } catch (err) {
    // Keep the live conversation available if browser storage is full/disabled.
  }
}

function restoreHistory(scope = historyScope) {
  historyScope = scope;
  conversationHistory = [];
  chatLog.replaceChildren();
  try {
    const saved = JSON.parse(localStorage.getItem(historyKey()) || "[]");
    if (!Array.isArray(saved)) return;
    conversationHistory = saved.slice(-historyLimit);
    conversationHistory.forEach(({ text, kind }) => {
      if (typeof text !== "string" || typeof kind !== "string") return;
      const el = document.createElement("div");
      el.className = "msg " + kind;
      el.textContent = text;
      chatLog.appendChild(el);
    });
    chatLog.scrollTop = chatLog.scrollHeight;
  } catch (err) {
    conversationHistory = [];
  }
}

async function apiFetch(url, options = {}) {
  return fetch(url, options);
}

function setStatus(text) {
  statusEl.textContent = text;
}

function showResult(result) {
  if (!result || typeof result !== "object") return;
  const formatValue = (value) => {
    if (Array.isArray(value)) {
      const rows = value.slice(0, 5).map(formatValue);
      if (value.length > 5) rows.push(`${value.length - 5} more`);
      return rows.join("; ");
    }
    if (value && typeof value === "object") {
      return Object.entries(value).map(([key, nested]) => `${key.replaceAll("_", " ")} ${formatValue(nested)}`).join(", ");
    }
    return value;
  };
  const details = Object.entries(result)
    .filter(([key]) => !["ok", "error", "transactions"].includes(key))
    .map(([key, value]) => `${key.replaceAll("_", " ")}: ${formatValue(value)}`)
    .join("  •  ");
  if (details) addMessage(details, "system");
}

function updateSalesReportLinks() {
  const period = reportPeriod.value;
  salesCsvLink.href = `/reports/sales?period=${encodeURIComponent(period)}&format=csv`;
  salesPdfLink.href = `/reports/sales?period=${encodeURIComponent(period)}&format=pdf`;
}

async function checkHealth() {
  try {
    const res = await fetch("/health");
    if (!res.ok) throw new Error("health check failed");
    healthDot.classList.add("online");
    healthLabel.textContent = "Backend connected";
  } catch (err) {
    healthLabel.textContent = "Backend unavailable";
  }
}

function detectContext(command) {
  const text = command.toLowerCase();
  if (/attendance|present|clock in|clock out|exam eligibility/.test(text)) return "attendance";
  if (/stock|inventory|units|restock|remove|add .*item/.test(text)) return "inventory";
  if (/sales|revenue/.test(text)) return "sales";
  return "general";
}

function updateContextSelector(command = textInput.value) {
  if (!contextSelect || !contextLabel) return;
  const nextMode = detectContext(command);
  if (nextMode === contextMode && contextSelect.options.length > 1) return;
  contextMode = nextMode;
  const config = {
    general: ["ERP context", "Choose context", []],
    attendance: ["Employee", "Choose employee", contextOptions.employees.map((item) => ({ value: item.employee_id, label: `${item.name} (${item.employee_id})` }))],
    inventory: ["Product", "Choose product", contextOptions.inventory.map((item) => ({ value: item.item_id, label: item.name }))],
    sales: ["Sales period", "Choose period", contextOptions.sales_periods],
  }[contextMode];
  contextLabel.textContent = config[0];
  contextSelect.replaceChildren(new Option(config[1], ""));
  config[2].forEach((item) => contextSelect.add(new Option(item.label, item.value)));
  contextSelect.value = "";
}

function commandWithContext(command) {
  const selected = selectedContextValue();
  if (!selected) return command;
  if (contextMode === "inventory" && !/[A-Za-z]{1,3}-\d{2,5}/.test(command)) {
    return `${command} for item ${selected}`;
  }
  if (contextMode === "sales" && !/(today|this month|last month)/i.test(command)) {
    return `${command} for ${selected}`;
  }
  return command;
}

async function loadContextOptions() {
  if (!currentUser) return;
  try {
    const res = await apiFetch("/erp/options");
    if (!res.ok) throw new Error("options unavailable");
    contextOptions = await res.json();
    updateContextSelector();
  } catch (err) {
    healthLabel.textContent = "Backend options unavailable";
  }
}

function renderDashboard(data) {
  dashboardKpis.replaceChildren();
  const metrics = [
    ["Products", data.product_count],
    ["Units on hand", Number(data.total_units).toLocaleString()],
    ["Need reorder", data.low_stock_count],
  ];
  if (Object.hasOwn(data, "sales_this_month")) {
    metrics.push(["Sales this month", Number(data.sales_this_month).toLocaleString(undefined, { maximumFractionDigits: 0 })]);
  }
  if (Object.hasOwn(data, "attendance_percentage")) {
    metrics.push(["Your attendance", `${data.attendance_percentage}%`]);
  }
  metrics.forEach(([label, value]) => {
    const metric = document.createElement("div");
    metric.className = "dashboard-metric";
    const title = document.createElement("span");
    title.textContent = label;
    const result = document.createElement("strong");
    result.textContent = value;
    metric.append(title, result);
    dashboardKpis.appendChild(metric);
  });
}

async function loadDashboard() {
  try {
    const res = await apiFetch("/dashboard/summary");
    if (!res.ok) throw new Error("Dashboard unavailable");
    renderDashboard(await res.json());
  } catch (err) {
    dashboardKpis.textContent = "Operations snapshot unavailable";
  }
}

async function loadInventory() {
  if (!currentUser) return;
  const query = new URLSearchParams({
    search: inventorySearch.value.trim(),
    low_stock_only: String(lowStockOnly.checked),
  });
  try {
    const res = await apiFetch(`/erp/inventory?${query}`);
    if (!res.ok) throw new Error("Inventory unavailable");
    const { items } = await res.json();
    inventoryList.replaceChildren();
    if (!items.length) {
      inventoryList.textContent = "No matching products.";
      return;
    }
    items.forEach((item) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "inventory-row";
      row.title = `Check stock for ${item.name}`;
      const product = document.createElement("span");
      product.className = "inventory-product";
      product.textContent = `${item.name} · ${item.item_id}`;
      const quantity = document.createElement("strong");
      quantity.textContent = `${item.quantity} / ${item.reorder_threshold}`;
      const status = document.createElement("span");
      status.className = item.quantity <= item.reorder_threshold ? "stock-status low" : "stock-status";
      status.textContent = item.quantity <= item.reorder_threshold ? "Reorder" : "In range";
      row.append(product, quantity, status);
      row.addEventListener("click", () => sendText(`Check stock for ${item.item_id}`));
      inventoryList.appendChild(row);
    });
  } catch (err) {
    inventoryList.textContent = "Inventory unavailable.";
  }
}

function showWorkspace() {
  signinScreen.hidden = true;
  appShell.hidden = false;
}

function showSignIn() {
  appShell.hidden = true;
  signinScreen.hidden = false;
}

function updateRoleUI(role) {
  document.querySelectorAll("[data-roles]").forEach((element) => {
    element.hidden = !element.dataset.roles.split(" ").includes(role);
  });
}

function activateWorkspace(employee) {
  currentUser = employee;
  authUser.textContent = employee.role === "demo"
    ? "Demo workspace"
    : `${employee.name} · ${employee.role}`;
  updateRoleUI(employee.role);
  showWorkspace();
  restoreHistory(employee.role === "demo" ? "demo" : employee.employee_id);
  if (!conversationHistory.length) {
    addMessage('Hi! Type a command or press Record to speak. Try: "check stock for P-102"', "bot");
  }
}

async function refreshProtectedViews() {
  await Promise.all([loadContextOptions(), loadDashboard(), loadInventory()]);
}

async function initializeAuth() {
  showSignIn();
  try {
    const res = await fetch("/auth/status");
    const status = await res.json();
    authRequired = Boolean(status.enabled);
    loginForm.hidden = !authRequired;
    demoAccess.hidden = !status.demo_enabled;
    signinStatus.classList.remove("error");
    signinStatus.textContent = authRequired
      ? "Use your assigned employee account."
      : "Employee sign-in is not configured for this instance.";
    const me = await apiFetch("/auth/me");
    if (me.ok) {
      const data = await me.json();
      activateWorkspace(data.employee);
      await refreshProtectedViews();
    }
  } catch (err) {
    signinStatus.classList.add("error");
    signinStatus.textContent = "Unable to reach the sign-in service.";
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const employeeId = document.getElementById("login-employee").value.trim();
  const password = document.getElementById("login-password").value;
  setStatus("Signing in...");
  try {
    const res = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employee_id: employeeId, password }),
    });
    const data = await parseJsonResponse(res);
    if (!res.ok) throw new Error(data?.detail || "Sign in failed");
    document.getElementById("login-password").value = "";
    signinStatus.textContent = "";
    setStatus("");
    activateWorkspace(data.employee);
    await refreshProtectedViews();
  } catch (err) {
    setStatus("");
    signinStatus.classList.add("error");
    signinStatus.textContent = err.message;
  }
});

demoBtn.addEventListener("click", async () => {
  demoBtn.disabled = true;
  signinStatus.classList.remove("error");
  signinStatus.textContent = "Opening sample workspace...";
  try {
    const res = await apiFetch("/auth/demo", { method: "POST" });
    const data = await parseJsonResponse(res);
    if (!res.ok) throw new Error(data?.detail || "Demo access is unavailable");
    const me = await apiFetch("/auth/me");
    if (!me.ok) throw new Error("Could not start the demo session");
    activateWorkspace((await me.json()).employee);
    await refreshProtectedViews();
  } catch (err) {
    signinStatus.classList.add("error");
    signinStatus.textContent = err.message;
  } finally {
    demoBtn.disabled = false;
  }
});

logoutBtn.addEventListener("click", async () => {
  try { await apiFetch("/auth/logout", { method: "POST" }); } catch (err) { /* local logout still applies */ }
  currentUser = null;
  chatLog.replaceChildren();
  conversationHistory = [];
  contextOptions = { employees: [], inventory: [], sales_periods: [] };
  dashboardKpis.replaceChildren();
  inventoryList.replaceChildren();
  signinStatus.textContent = "You have signed out.";
  showSignIn();
});

let inventorySearchTimer;
inventorySearch.addEventListener("input", () => {
  clearTimeout(inventorySearchTimer);
  inventorySearchTimer = setTimeout(loadInventory, 180);
});
lowStockOnly.addEventListener("change", loadInventory);
reportPeriod.addEventListener("change", updateSalesReportLinks);

document.getElementById("clear-history").addEventListener("click", () => {
  localStorage.removeItem(historyKey());
  sessionId = crypto.randomUUID();
  localStorage.setItem("voice_erp_session", sessionId);
  conversationHistory = [];
  chatLog.replaceChildren();
  addMessage("Conversation cleared. What would you like to do next?", "system");
});

textInput.addEventListener("input", () => updateContextSelector());

async function parseJsonResponse(res) {
  const text = await res.text();
  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch (err) {
    return { error: text };
  }
}

// --- Text pipeline: browser -> POST /voice/text -> FastAPI -> dialog_manager.py ---
async function sendText(text) {
  const trimmed = text.trim();
  if (!trimmed) return;
  updateContextSelector(trimmed);
  addMessage(trimmed, "user");
  textInput.value = "";
  setStatus("Thinking\u2026");
  const requestText = commandWithContext(trimmed);

  try {
    const res = await apiFetch("/voice/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        text: requestText,
        employee_id: contextMode === "attendance" ? selectedContextValue() || null : null,
      }),
    });
    const data = await parseJsonResponse(res);
    if (!res.ok) {
      throw new Error((data && data.error) || ("Server responded with " + res.status));
    }
    addMessage(data.reply, "bot");
    showResult(data.result);
    if (data.reply && window.speechSynthesis && text.startsWith("(voice")) {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(data.reply));
    }
  } catch (err) {
    addMessage(
      "Couldn't reach the server. Is `uvicorn app.main:app --reload` still running? (" + err.message + ")",
      "bot error"
    );
  } finally {
    setStatus("");
  }
}

inputRow.addEventListener("submit", (e) => {
  e.preventDefault();
  sendText(textInput.value);
});

// --- Voice pipeline: browser mic -> POST /voice/audio -> STT -> ... -> TTS wav back ---
let mediaRecorder = null;
let audioChunks = [];
let recording = false;

async function startMicRecorder() {
  if (recording) {
    mediaRecorder?.stop();
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    audioChunks = [];
    mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      sendRecording();
    };
    mediaRecorder.start();
    recording = true;
    micBtn.classList.add("recording");
    micLabel.textContent = "Stop";
    setStatus("Listening\u2026 click Stop when done");
  } catch (err) {
    addMessage(
      "Couldn't access the microphone: " + err.message + " (check your browser's mic permission for this page)",
      "bot error"
    );
  }
}

async function toggleRecording() {
  await startMicRecorder();
}

function stopRecordingUI() {
  recording = false;
  micBtn.classList.remove("recording");
  micLabel.textContent = "Speak";
}

micBtn.addEventListener("click", toggleRecording);

function fallbackToMicRecorder() {
  speechRecognition = null;
  recording = false;
  micBtn.classList.remove("recording");
  micLabel.textContent = "Speak";
  setStatus("");
  addMessage(
    "Browser speech is unavailable in this context. Falling back to the microphone recorder instead.",
    "system"
  );
  startMicRecorder();
}

function toggleBrowserSpeech() {
  if (speechRecognition) {
    speechRecognition.stop();
    return;
  }

  if (!SpeechRecognition || !window.isSecureContext) {
    fallbackToMicRecorder();
    return;
  }

  try {
    speechRecognition = new SpeechRecognition();
    speechRecognition.lang = "en-US";
    speechRecognition.interimResults = false;
    speechRecognition.continuous = false;
    speechRecognition.onstart = () => {
      recording = true;
      micBtn.classList.add("recording");
      micLabel.textContent = "Stop";
      setStatus("Listening... speak your command");
    };
    speechRecognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript.trim();
      if (transcript) {
        addMessage('(voice) "' + transcript + '"', "user");
        sendTextWithVoiceReply(transcript);
      }
    };
    speechRecognition.onerror = (event) => {
      const errorText = event.error || "network";
      addMessage(
        "Browser speech recognition failed: " + errorText + ". Falling back to microphone recording.",
        "bot error"
      );
      fallbackToMicRecorder();
    };
    speechRecognition.onend = () => {
      recording = false;
      speechRecognition = null;
      micBtn.classList.remove("recording");
      micLabel.textContent = "Speak";
      setStatus("");
    };
    speechRecognition.start();
  } catch (err) {
    addMessage("Browser speech recognition could not start: " + err.message + ". Falling back to the mic recording button.", "bot error");
    fallbackToMicRecorder();
  }
}

async function sendTextWithVoiceReply(text) {
  const originalInput = textInput.value;
  textInput.value = "";
  setStatus("Processing voice command...");
  updateContextSelector(text);
  const requestText = commandWithContext(text);
  try {
    const res = await apiFetch("/voice/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, text: requestText, employee_id: contextMode === "attendance" ? selectedContextValue() || null : null }),
    });
    const data = await parseJsonResponse(res);
    if (!res.ok) {
      throw new Error((data && data.error) || ("Server responded with " + res.status));
    }
    addMessage(data.reply, "bot");
    showResult(data.result);
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(data.reply));
    }
  } catch (err) {
    addMessage("Couldn't process the voice command: " + err.message, "bot error");
  } finally {
    textInput.value = originalInput;
    setStatus("");
  }
}

document.querySelectorAll(".example-command").forEach((button) => {
  button.addEventListener("click", () => sendText(button.dataset.command));
});

async function sendRecording() {
  stopRecordingUI();
  addMessage("(voice message)", "user");
  setStatus("Transcribing\u2026");

  const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
  const formData = new FormData();
  formData.append("session_id", sessionId);
  if (contextMode === "attendance" && selectedContextValue()) formData.append("employee_id", selectedContextValue());
  formData.append("file", audioBlob, "recording.webm");

  try {
    const res = await apiFetch("/voice/audio", { method: "POST", body: formData });
    const contentType = res.headers.get("Content-Type") || "";

    if (contentType.includes("audio")) {
      // Full pipeline succeeded: STT -> NLU -> ERP -> TTS all ran, and this
      // response IS the spoken reply as a .wav file.
      const transcript = res.headers.get("X-Transcript");
      const replyText = res.headers.get("X-Reply-Text");
      if (transcript) addMessage('Heard: "' + transcript + '"', "system");
      addMessage(replyText || "(spoken reply)", "bot");
      const audioBuf = await res.blob();
      new Audio(URL.createObjectURL(audioBuf)).play();
    } else {
      // STT or TTS wasn't fully set up (see README) -- backend falls back
      // to a JSON error/partial response instead of crashing.
      const data = await parseJsonResponse(res);
      if (data && data.error) {
        addMessage("Voice error: " + data.error, "bot error");
      } else {
        const fallbackData = data || {};
        if (fallbackData.transcript) addMessage('Heard: "' + fallbackData.transcript + '"', "system");
        addMessage(fallbackData.reply || JSON.stringify(fallbackData), "bot");
        showResult(fallbackData.result);
        if (fallbackData.tts_error) addMessage("(text-to-speech unavailable: " + fallbackData.tts_error + ")", "system");
      }
    }
  } catch (err) {
    addMessage("Connection error: " + err.message, "bot error");
  } finally {
    setStatus("");
  }
}

checkHealth();
updateSalesReportLinks();
initializeAuth();
