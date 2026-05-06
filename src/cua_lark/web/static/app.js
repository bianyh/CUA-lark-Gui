const state = {
  cases: [],
  selectedCase: null,
  runId: null,
  run: null,
  pollTimer: null,
  mode: "mock",
  visibleLogs: [],
};

const terminalStatuses = new Set(["success", "failed", "error", "cancelled"]);

const els = {
  environmentLine: document.querySelector("#environmentLine"),
  refreshButton: document.querySelector("#refreshButton"),
  openReportButton: document.querySelector("#openReportButton"),
  caseSelect: document.querySelector("#caseSelect"),
  caseSummary: document.querySelector("#caseSummary"),
  mockModeButton: document.querySelector("#mockModeButton"),
  desktopModeButton: document.querySelector("#desktopModeButton"),
  windowKeywordInput: document.querySelector("#windowKeywordInput"),
  maxStepsInput: document.querySelector("#maxStepsInput"),
  maxRetriesInput: document.querySelector("#maxRetriesInput"),
  ocrBackendSelect: document.querySelector("#ocrBackendSelect"),
  loadWaitToggle: document.querySelector("#loadWaitToggle"),
  startButton: document.querySelector("#startButton"),
  stopButton: document.querySelector("#stopButton"),
  statusValue: document.querySelector("#statusValue"),
  taskValue: document.querySelector("#taskValue"),
  durationValue: document.querySelector("#durationValue"),
  modeValue: document.querySelector("#modeValue"),
  runIndicator: document.querySelector("#runIndicator"),
  logStream: document.querySelector("#logStream"),
  logCount: document.querySelector("#logCount"),
  clearLogsButton: document.querySelector("#clearLogsButton"),
  metricsGrid: document.querySelector("#metricsGrid"),
  reportBox: document.querySelector("#reportBox"),
  timelineGrid: document.querySelector("#timelineGrid"),
  toast: document.querySelector("#toast"),
};

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  refreshAll();
  window.lucide?.createIcons();
});

function bindEvents() {
  els.refreshButton.addEventListener("click", refreshAll);
  els.caseSelect.addEventListener("change", () => {
    state.selectedCase = state.cases.find((item) => item.id === els.caseSelect.value) || null;
    renderCaseSummary();
  });
  els.mockModeButton.addEventListener("click", () => setMode("mock"));
  els.desktopModeButton.addEventListener("click", () => setMode("desktop"));
  els.startButton.addEventListener("click", startRun);
  els.stopButton.addEventListener("click", stopRun);
  els.clearLogsButton.addEventListener("click", () => {
    state.visibleLogs = [];
    renderLogs();
  });
  els.openReportButton.addEventListener("click", () => activateTab("report"));
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  });
}

async function refreshAll() {
  await Promise.all([loadHealth(), loadCases(), loadRuns()]);
  window.lucide?.createIcons();
}

async function loadHealth() {
  const data = await requestJson("/api/health");
  const health = data;
  els.environmentLine.textContent =
    `模式=${health.mode} | 模型=${health.openai_model} | API Key=${health.openai_api_key_set ? "已配置" : "未配置"} | OCR=${health.ocr_backend}`;
  els.windowKeywordInput.value = health.window_title_keyword || "飞书";
  els.ocrBackendSelect.value = health.ocr_backend || "none";
  setMode(health.mode === "desktop" ? "desktop" : "mock");
}

async function loadCases() {
  const data = await requestJson("/api/cases");
  state.cases = data.cases || [];
  els.caseSelect.innerHTML = "";
  state.cases.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.product} · ${item.id}`;
    els.caseSelect.append(option);
  });
  if (!state.selectedCase && state.cases.length) {
    state.selectedCase = state.cases[0];
  }
  if (state.selectedCase) {
    els.caseSelect.value = state.selectedCase.id;
  }
  renderCaseSummary();
}

async function loadRuns() {
  const data = await requestJson("/api/runs");
  const runs = data.runs || [];
  if (!state.runId && runs.length) {
    const active = runs.find((item) => !terminalStatuses.has(item.status));
    if (active) {
      state.runId = active.id;
      startPolling();
    }
  }
}

function renderCaseSummary() {
  const item = state.selectedCase;
  if (!item) {
    els.caseSummary.innerHTML = `<div class="empty-state">未发现测试用例。</div>`;
    els.taskValue.textContent = "未选择";
    return;
  }
  els.taskValue.textContent = item.id;
  els.caseSummary.innerHTML = `
    <div class="case-title-row">
      <strong>${escapeHtml(item.id)}</strong>
      <span class="case-product">${escapeHtml(item.product)}</span>
    </div>
    <div class="case-meta">
      <div class="case-meta-row">
        <span>路径</span>
        <code>${escapeHtml(item.path)}</code>
      </div>
      <div class="case-meta-row">
        <span>动作</span>
        <code>${escapeHtml(String(item.scripted_action_count))}</code>
      </div>
    </div>
    <p class="case-instruction">${escapeHtml(item.instruction)}</p>
  `;
}

function setMode(mode) {
  state.mode = mode;
  els.mockModeButton.classList.toggle("active", mode === "mock");
  els.desktopModeButton.classList.toggle("active", mode === "desktop");
  els.modeValue.textContent = mode === "mock" ? "Mock" : "Desktop";
}

async function startRun() {
  if (!state.selectedCase) {
    showToast("请先选择测试用例。");
    return;
  }
  const payload = {
    case_id: state.selectedCase.id,
    mock_mode: state.mode === "mock",
    window_title_keyword: els.windowKeywordInput.value.trim() || "飞书",
    max_steps: Number(els.maxStepsInput.value || 15),
    max_retries: Number(els.maxRetriesInput.value || 2),
    ocr_backend: els.ocrBackendSelect.value,
    load_wait_enabled: els.loadWaitToggle.checked,
  };
  try {
    const data = await requestJson("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.runId = data.run.id;
    state.run = data.run;
    state.visibleLogs = [];
    renderRun();
    startPolling();
    showToast("任务已启动。");
  } catch (error) {
    showToast(error.message);
  }
}

async function stopRun() {
  if (!state.runId) {
    return;
  }
  try {
    const data = await requestJson(`/api/runs/${state.runId}/cancel`, { method: "POST" });
    state.run = data.run;
    renderRun();
    showToast("已发送停止请求。");
  } catch (error) {
    showToast(error.message);
  }
}

function startPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
  }
  pollRun();
  state.pollTimer = setInterval(pollRun, 1200);
}

async function pollRun() {
  if (!state.runId) {
    return;
  }
  try {
    const data = await requestJson(`/api/runs/${state.runId}`);
    state.run = data.run;
    renderRun();
    if (terminalStatuses.has(state.run.status)) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      await Promise.all([loadReport(), loadTimeline()]);
    }
  } catch (error) {
    showToast(error.message);
  }
}

function renderRun() {
  const run = state.run;
  if (!run) {
    updateRunningControls(false);
    updateRunIndicator(null);
    return;
  }
  const isActive = !terminalStatuses.has(run.status);
  els.statusValue.textContent = formatStatus(run.status);
  els.statusValue.className = `status-${run.status}`;
  els.taskValue.textContent = run.task_id || "未选择";
  els.durationValue.textContent = `${Number(run.duration_seconds || 0).toFixed(2)}s`;
  els.modeValue.textContent = run.mode === "desktop" ? "Desktop" : "Mock";
  updateRunIndicator(run.status);
  els.openReportButton.disabled = !run.report_available;
  state.visibleLogs = run.logs || [];
  renderLogs();
  renderMetrics(run.metrics || {});
  updateRunningControls(isActive);
}

function renderLogs() {
  const logs = state.visibleLogs;
  els.logCount.textContent = `${logs.length} 条日志`;
  if (!logs.length) {
    els.logStream.innerHTML = `<div class="empty-state">还没有运行日志。</div>`;
    return;
  }
  els.logStream.innerHTML = logs
    .map(
      (item) => `
        <div class="log-line ${stageClass(item.stage)}">
          <span class="log-time">${escapeHtml(item.timestamp)}</span>
          <span class="log-stage">[${escapeHtml(item.stage)}]</span>
          <span class="log-message">${escapeHtml(item.message)}</span>
        </div>
      `,
    )
    .join("");
  els.logStream.scrollTop = els.logStream.scrollHeight;
}

function renderMetrics(metrics) {
  const entries = Object.entries(metrics);
  if (!entries.length) {
    els.metricsGrid.innerHTML = `<div class="empty-state">任务完成后会显示指标。</div>`;
    return;
  }
  els.metricsGrid.innerHTML = entries
    .map(
      ([key, value]) => `
        <div class="metric-tile">
          <span>${escapeHtml(formatMetricLabel(key))}</span>
          <strong>${escapeHtml(String(value))}</strong>
        </div>
      `,
    )
    .join("");
}

async function loadReport() {
  if (!state.runId) {
    return;
  }
  try {
    const data = await requestJson(`/api/runs/${state.runId}/report`);
    els.reportBox.textContent = data.markdown || "报告为空。";
    els.openReportButton.disabled = false;
  } catch {
    els.reportBox.textContent = "报告尚未生成。";
    els.openReportButton.disabled = true;
  }
}

async function loadTimeline() {
  if (!state.runId) {
    return;
  }
  try {
    const data = await requestJson(`/api/runs/${state.runId}/timeline`);
    const images = data.images || [];
    if (!images.length) {
      els.timelineGrid.innerHTML = `<div class="empty-state">暂无截图时间线。</div>`;
      return;
    }
    els.timelineGrid.innerHTML = images
      .map(
        (item) => `
          <figure class="timeline-item">
            <img src="${item.url}" alt="${escapeHtml(item.name)}" loading="lazy" />
            <span>${escapeHtml(item.name)}</span>
          </figure>
        `,
      )
      .join("");
  } catch {
    els.timelineGrid.innerHTML = `<div class="empty-state">截图时间线尚未生成。</div>`;
  }
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === name);
  });
  document.querySelectorAll(".tab-view").forEach((view) => {
    view.classList.remove("active");
  });
  const target = document.querySelector(`#${name}View`);
  if (target) {
    target.classList.add("active");
  }
}

function updateRunningControls(isActive) {
  els.startButton.disabled = isActive;
  els.stopButton.disabled = !isActive;
}

function updateRunIndicator(status) {
  if (!els.runIndicator) {
    return;
  }
  const normalized = status || "idle";
  els.runIndicator.className = `run-indicator is-${normalized}`;
  const label = formatStatus(status);
  const labelEl = els.runIndicator.querySelector("strong");
  if (labelEl) {
    labelEl.textContent = label;
  }
}

function formatStatus(status) {
  const mapping = {
    queued: "排队中",
    running: "运行中",
    cancel_requested: "停止中",
    cancelled: "已停止",
    success: "成功",
    failed: "失败",
    error: "异常",
  };
  return mapping[status] || status || "空闲";
}

function formatMetricLabel(key) {
  const mapping = {
    step_attempts: "步骤尝试",
    step_success_rate: "步骤成功率",
    successful_steps: "成功步骤",
    failed_steps: "失败步骤",
    retries: "重试次数",
    load_wait_rounds: "加载等待",
    load_timeouts: "加载超时",
    replans: "重规划",
    max_steps: "最大步骤",
    max_retries: "最大重试",
  };
  return mapping[key] || key;
}

function stageClass(stage) {
  const text = String(stage || "").toLowerCase();
  if (text.includes("异常") || text.includes("失败") || text.includes("error")) {
    return "stage-error";
  }
  if (text.includes("规划") || text.includes("思考") || text.includes("重规划")) {
    return "stage-planning";
  }
  if (text.includes("校验") || text.includes("总验")) {
    return "stage-validation";
  }
  if (text.includes("结果") || text.includes("完成") || text.includes("总进度")) {
    return "stage-success";
  }
  return "";
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `请求失败：${response.status}`);
  }
  return data;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    els.toast.hidden = true;
  }, 3200);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
