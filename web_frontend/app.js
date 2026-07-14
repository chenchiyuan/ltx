const API_BASE = "/api";
const recentKey = "ltx.recentTasks";

let selectedTaskId = null;
let mode = "text_to_video";
let videoObjectUrl = null;

const els = {
  health: document.querySelector("#healthState"),
  apiKey: document.querySelector("#apiKey"),
  adminToken: document.querySelector("#adminToken"),
  saveKeys: document.querySelector("#saveKeys"),
  form: document.querySelector("#generationForm"),
  prompt: document.querySelector("#prompt"),
  negativePrompt: document.querySelector("#negativePrompt"),
  imageInput: document.querySelector("#imageInput"),
  inputImage: document.querySelector("#inputImage"),
  profile: document.querySelector("#profile"),
  duration: document.querySelector("#duration"),
  aspectRatio: document.querySelector("#aspectRatio"),
  seed: document.querySelector("#seed"),
  formStatus: document.querySelector("#formStatus"),
  taskRows: document.querySelector("#taskRows"),
  selectedTaskTitle: document.querySelector("#selectedTaskTitle"),
  taskDetail: document.querySelector("#taskDetail"),
  videoStage: document.querySelector("#videoStage"),
  refreshTasks: document.querySelector("#refreshTasks"),
  cancelTask: document.querySelector("#cancelTask"),
  loadOps: document.querySelector("#loadOps"),
  dispatchOnce: document.querySelector("#dispatchOnce"),
  loadWorkflows: document.querySelector("#loadWorkflows"),
  opsOutput: document.querySelector("#opsOutput"),
};

function loadKeys() {
  els.apiKey.value = localStorage.getItem("ltx.apiKey") || "";
  els.adminToken.value = localStorage.getItem("ltx.adminToken") || "";
}

function saveKeys() {
  localStorage.setItem("ltx.apiKey", els.apiKey.value.trim());
  localStorage.setItem("ltx.adminToken", els.adminToken.value.trim());
  setStatus("Credentials saved");
}

function authHeaders() {
  const token = els.apiKey.value.trim();
  if (!token) throw new Error("API Key is required");
  return { Authorization: `Bearer ${token}` };
}

function adminHeaders() {
  const token = els.adminToken.value.trim();
  if (!token) throw new Error("Admin Token is required");
  return { "X-Admin-Token": token };
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const code = data?.error?.code || data?.detail?.code || response.status;
    const message = data?.error?.message || data?.detail?.message || response.statusText;
    throw new Error(`${code}: ${message}`);
  }
  return data;
}

function getRecentTasks() {
  try {
    return JSON.parse(localStorage.getItem(recentKey) || "[]");
  } catch {
    return [];
  }
}

function saveRecentTasks(tasks) {
  localStorage.setItem(recentKey, JSON.stringify(tasks.slice(0, 20)));
}

function rememberTask(task) {
  const tasks = getRecentTasks().filter((item) => item.task_id !== task.task_id);
  tasks.unshift(task);
  saveRecentTasks(tasks);
  selectedTaskId = task.task_id;
  renderTasks(tasks);
}

function setStatus(message) {
  els.formStatus.textContent = message;
}

async function checkHealth() {
  try {
    const health = await requestJson("/health");
    els.health.textContent = `${health.status} / ${health.executor.executor_type}`;
    els.health.className = `health ${health.status === "ok" ? "ok" : "bad"}`;
  } catch {
    els.health.textContent = "offline";
    els.health.className = "health bad";
  }
}

function setMode(nextMode) {
  mode = nextMode;
  document.querySelectorAll(".mode").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  els.imageInput.classList.toggle("visible", mode === "image_to_video");
}

async function uploadInputImage(file) {
  const created = await requestJson("/v1/assets/uploads", {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "application/octet-stream",
      size_bytes: file.size,
    }),
  });
  await fetch(`${API_BASE}/v1/assets/${created.asset_id}/content`, {
    method: "PUT",
    headers: authHeaders(),
    body: file,
  }).then((response) => {
    if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
  });
  return created.asset_id;
}

function generationPayload(imageAssetId) {
  const payload = {
    mode,
    prompt: els.prompt.value.trim(),
    negative_prompt: els.negativePrompt.value.trim() || null,
    profile: els.profile.value,
    duration_seconds: Number(els.duration.value || 1),
    aspect_ratio: els.aspectRatio.value,
  };
  if (els.seed.value.trim()) payload.seed = Number(els.seed.value);
  if (imageAssetId) payload.image_asset_id = imageAssetId;
  return payload;
}

async function createGeneration(event) {
  event.preventDefault();
  setStatus("Submitting");
  try {
    let imageAssetId = null;
    if (mode === "image_to_video") {
      const file = els.inputImage.files[0];
      if (!file) throw new Error("Input image is required for image_to_video");
      imageAssetId = await uploadInputImage(file);
    }
    const task = await requestJson("/v1/video-generations", {
      method: "POST",
      headers: {
        ...authHeaders(),
        "Content-Type": "application/json",
        "Idempotency-Key": `web-${Date.now()}`,
      },
      body: JSON.stringify(generationPayload(imageAssetId)),
    });
    rememberTask({ ...task, mode });
    setStatus(`Queued ${task.task_id}`);
    await refreshSelectedTask();
  } catch (error) {
    setStatus(error.message);
  }
}

function renderTasks(tasks) {
  els.taskRows.innerHTML = "";
  if (!tasks.length) {
    els.taskRows.innerHTML = '<div class="metric-line">No recent tasks</div>';
    return;
  }
  for (const task of tasks) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `task-row ${task.task_id === selectedTaskId ? "active" : ""}`;
    row.innerHTML = `
      <span><strong>${task.task_id}</strong><span>${task.mode || task.profile || "video"} · attempts ${task.attempt_count ?? 0}</span></span>
      <span class="status-pill ${task.status || ""}">${task.status || "queued"}</span>
    `;
    row.addEventListener("click", async () => {
      selectedTaskId = task.task_id;
      renderTasks(getRecentTasks());
      await refreshSelectedTask();
    });
    els.taskRows.appendChild(row);
  }
}

function renderTaskDetail(task) {
  els.selectedTaskTitle.textContent = task.task_id;
  els.taskDetail.innerHTML = `
    <div>Status: ${task.status}</div>
    <div>Progress: ${task.progress?.stage || "-"} / ${task.progress?.percent ?? 0}%</div>
    <div>Attempts: ${task.attempt_count}</div>
    <div>Error: ${task.error || "-"}</div>
  `;
}

async function refreshSelectedTask() {
  if (!selectedTaskId) return;
  try {
    const task = await requestJson(`/v1/video-generations/${selectedTaskId}`, { headers: authHeaders() });
    const tasks = getRecentTasks().map((item) => (item.task_id === task.task_id ? { ...item, ...task } : item));
    saveRecentTasks(tasks);
    renderTasks(tasks);
    renderTaskDetail(task);
    if (task.status === "succeeded") await loadResult(task.task_id);
  } catch (error) {
    els.taskDetail.textContent = error.message;
  }
}

async function refreshAllTasks() {
  const tasks = getRecentTasks();
  for (const task of tasks) {
    selectedTaskId = selectedTaskId || task.task_id;
    try {
      const latest = await requestJson(`/v1/video-generations/${task.task_id}`, { headers: authHeaders() });
      Object.assign(task, latest);
    } catch (error) {
      task.error = error.message;
    }
  }
  saveRecentTasks(tasks);
  renderTasks(tasks);
  await refreshSelectedTask();
}

async function loadResult(taskId) {
  const result = await requestJson(`/v1/video-generations/${taskId}/result`, { headers: authHeaders() });
  const output = result.outputs[0];
  if (!output) return;
  const response = await fetch(`${API_BASE}/v1/assets/${output.asset_id}/content`, { headers: authHeaders() });
  if (!response.ok) throw new Error(`Download failed: ${response.status}`);
  const blob = await response.blob();
  if (videoObjectUrl) URL.revokeObjectURL(videoObjectUrl);
  videoObjectUrl = URL.createObjectURL(blob);
  els.videoStage.innerHTML = "";
  const video = document.createElement("video");
  video.controls = true;
  video.src = videoObjectUrl;
  els.videoStage.appendChild(video);
}

async function cancelSelectedTask() {
  if (!selectedTaskId) return;
  try {
    await requestJson(`/v1/video-generations/${selectedTaskId}/cancel`, {
      method: "POST",
      headers: authHeaders(),
    });
    await refreshSelectedTask();
  } catch (error) {
    els.taskDetail.textContent = error.message;
  }
}

function renderOps(data) {
  if (Array.isArray(data.workers)) {
    els.opsOutput.innerHTML = data.workers
      .map((worker) => {
        const profiles = worker.capabilities?.profiles?.join("/") || "-";
        const gpuIndices = worker.capabilities?.gpu_indices?.join(",") || worker.gpu_index;
        const gpuCount = worker.capabilities?.gpu_count || 1;
        const runtime = worker.capabilities?.execution || "-";
        const health = worker.capabilities?.comfyui_healthy ? "ComfyUI ok" : "ComfyUI pending";
        return `<div class="metric-line">${worker.worker_name} · ${worker.status} · ${profiles} · ${gpuCount} GPU [${gpuIndices}] · ${runtime} · ${health}</div>`;
      })
      .join("");
    return;
  }
  els.opsOutput.innerHTML = `<div class="metric-line">${JSON.stringify(data)}</div>`;
}

async function loadOps() {
  try {
    renderOps(await requestJson("/admin/workers", { headers: adminHeaders() }));
  } catch (error) {
    els.opsOutput.innerHTML = `<div class="metric-line">${error.message}</div>`;
  }
}

async function dispatchOnce() {
  try {
    renderOps(await requestJson("/internal/dispatch/run-once", { method: "POST", headers: adminHeaders() }));
  } catch (error) {
    els.opsOutput.innerHTML = `<div class="metric-line">${error.message}</div>`;
  }
}

async function loadWorkflows() {
  try {
    const data = await requestJson("/admin/workflow-templates", { headers: adminHeaders() });
    els.opsOutput.innerHTML = data.profiles
      .map((profile) => `<div class="metric-line">${profile.profile} · estimated ${profile.estimated_gpu_seconds}s · ${profile.workflow_version_id}</div>`)
      .join("");
  } catch (error) {
    els.opsOutput.innerHTML = `<div class="metric-line">${error.message}</div>`;
  }
}

document.querySelectorAll(".mode").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});
els.saveKeys.addEventListener("click", saveKeys);
els.form.addEventListener("submit", createGeneration);
els.refreshTasks.addEventListener("click", refreshAllTasks);
els.cancelTask.addEventListener("click", cancelSelectedTask);
els.loadOps.addEventListener("click", loadOps);
els.dispatchOnce.addEventListener("click", dispatchOnce);
els.loadWorkflows.addEventListener("click", loadWorkflows);

loadKeys();
setMode(mode);
renderTasks(getRecentTasks());
checkHealth();
setInterval(checkHealth, 10000);
setInterval(refreshAllTasks, 5000);
