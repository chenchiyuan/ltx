const API_BASE = "/api";
const recentKey = "ltx.recentTasks";
const MAX_IMAGE_CONDITIONS = 4;
const IMAGE_PREVIEW_LABELS = {
  inputImage: "REFERENCE",
  startImage: "START",
  endImage: "END",
};

let selectedTaskId = null;
let mode = "text_to_video";
let referenceMode = "single";
let videoObjectUrl = null;
let nextMiddleReferenceId = 1;
const imagePreviewUrls = new Map();

const els = {
  health: document.querySelector("#healthState"),
  apiKey: document.querySelector("#apiKey"),
  adminToken: document.querySelector("#adminToken"),
  saveKeys: document.querySelector("#saveKeys"),
  form: document.querySelector("#generationForm"),
  prompt: document.querySelector("#prompt"),
  negativePrompt: document.querySelector("#negativePrompt"),
  imageInput: document.querySelector("#imageInput"),
  conditionPanelTitle: document.querySelector("#conditionPanelTitle"),
  referenceSelectionStatus: document.querySelector("#referenceSelectionStatus"),
  singleImageField: document.querySelector("#singleImageField"),
  multiReferenceField: document.querySelector("#multiReferenceField"),
  inputImage: document.querySelector("#inputImage"),
  startImage: document.querySelector("#startImage"),
  endImage: document.querySelector("#endImage"),
  startStrength: document.querySelector("#startStrength"),
  endStrength: document.querySelector("#endStrength"),
  middleReferences: document.querySelector("#middleReferences"),
  addMiddleReference: document.querySelector("#addMiddleReference"),
  profile: document.querySelector("#profile"),
  duration: document.querySelector("#duration"),
  aspectRatio: document.querySelector("#aspectRatio"),
  seed: document.querySelector("#seed"),
  submitGeneration: document.querySelector("#submitGeneration"),
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
    const detail = data?.detail?.error || data?.detail || data?.error || {};
    const code = detail.code || response.status;
    const message = detail.message || response.statusText;
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
  syncProfileAvailability();
}

function setReferenceMode(nextMode) {
  referenceMode = nextMode;
  document.querySelectorAll("[data-reference-mode]").forEach((button) => {
    const active = button.dataset.referenceMode === referenceMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const multi = referenceMode === "multi";
  els.singleImageField.hidden = multi;
  els.multiReferenceField.hidden = !multi;
  els.conditionPanelTitle.textContent = multi ? "上传首尾帧" : "上传参考图";
  if (multi) els.profile.value = "vip";
  updateReferenceSelectionStatus();
  syncProfileAvailability();
}

function syncProfileAvailability() {
  els.profile.disabled = mode === "image_to_video" && referenceMode === "multi";
}

function updateRangeOutput(input) {
  const output = document.querySelector(`output[for="${input.id}"]`);
  if (output) output.value = Number(input.value).toFixed(2);
}

function updateImagePreview(input) {
  const preview = document.querySelector(`[data-preview-for="${input.id}"]`);
  if (!preview) return;
  const previousUrl = imagePreviewUrls.get(input.id);
  if (previousUrl) URL.revokeObjectURL(previousUrl);
  imagePreviewUrls.delete(input.id);
  preview.innerHTML = "";

  const file = input.files[0];
  if (!file) {
    const fallback = document.createElement("span");
    fallback.textContent = IMAGE_PREVIEW_LABELS[input.id] || "MIDDLE";
    preview.appendChild(fallback);
    updateReferenceSelectionStatus();
    return;
  }

  const objectUrl = URL.createObjectURL(file);
  imagePreviewUrls.set(input.id, objectUrl);
  const image = document.createElement("img");
  image.src = objectUrl;
  image.alt = file.name;
  preview.appendChild(image);
  updateReferenceSelectionStatus();
}

function middleReferenceRows() {
  return [...els.middleReferences.querySelectorAll(".middle-reference")];
}

function updateReferenceSelectionStatus() {
  if (referenceMode === "single") {
    els.referenceSelectionStatus.textContent = `已选择 ${els.inputImage.files.length}/1`;
    return;
  }
  const requiredSelected = Number(Boolean(els.startImage.files[0]))
    + Number(Boolean(els.endImage.files[0]));
  const middleSelected = middleReferenceRows().filter((row) => row.querySelector(".middle-image").files[0]).length;
  els.referenceSelectionStatus.textContent = `必选帧 ${requiredSelected}/2 · 中间帧 ${middleSelected}/2`;
}

function updateAddReferenceState() {
  els.addMiddleReference.disabled = middleReferenceRows().length >= MAX_IMAGE_CONDITIONS - 2;
}

function addMiddleReference() {
  if (middleReferenceRows().length >= MAX_IMAGE_CONDITIONS - 2) return;
  const referenceId = nextMiddleReferenceId++;
  const inputId = `middleImage${referenceId}`;
  const strengthId = `middleStrength${referenceId}`;
  const defaultPosition = middleReferenceRows().length === 0 ? 50 : 75;
  const card = document.createElement("article");
  card.className = "reference-card middle-reference";
  card.dataset.referenceId = String(referenceId);
  card.innerHTML = `
    <div class="reference-card-head">
      <strong>中间帧</strong>
      <button class="icon-button" type="button" title="移除中间帧" aria-label="移除中间帧">×</button>
    </div>
    <div class="reference-preview" data-preview-for="${inputId}"><span>MIDDLE</span></div>
    <label>
      图片
      <input id="${inputId}" class="middle-image" type="file" accept="image/png,image/jpeg,image/webp" />
    </label>
    <div class="reference-parameters">
      <label>
        位置 %
        <input class="middle-position" type="number" min="1" max="99" value="${defaultPosition}" />
      </label>
      <label>
        强度
        <span class="range-control">
          <input id="${strengthId}" class="middle-strength" type="range" min="0" max="1" step="0.05" value="0.7" />
          <output for="${strengthId}">0.70</output>
        </span>
      </label>
    </div>
  `;

  const fileInput = card.querySelector(".middle-image");
  const strengthInput = card.querySelector(".middle-strength");
  fileInput.addEventListener("change", () => updateImagePreview(fileInput));
  strengthInput.addEventListener("input", () => updateRangeOutput(strengthInput));
  card.querySelector(".icon-button").addEventListener("click", () => {
    const objectUrl = imagePreviewUrls.get(inputId);
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    imagePreviewUrls.delete(inputId);
    card.remove();
    updateAddReferenceState();
    updateReferenceSelectionStatus();
  });
  els.middleReferences.appendChild(card);
  updateAddReferenceState();
  updateReferenceSelectionStatus();
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

function generationPayload({ imageAssetId = null, imageConditions = null } = {}) {
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
  if (imageConditions) payload.image_conditions = imageConditions;
  return payload;
}

function multiReferenceDescriptors() {
  const startFile = els.startImage.files[0];
  const endFile = els.endImage.files[0];
  if (!startFile) throw new Error("首帧图片不能为空");
  if (!endFile) throw new Error("尾帧图片不能为空");

  const middle = middleReferenceRows().map((row) => {
    const file = row.querySelector(".middle-image").files[0];
    const position = Number(row.querySelector(".middle-position").value);
    if (!file) throw new Error("已添加的中间帧必须选择图片");
    if (!Number.isFinite(position) || position <= 0 || position >= 100) {
      throw new Error("中间帧位置必须在 1% 到 99% 之间");
    }
    return {
      file,
      position,
      strength: Number(row.querySelector(".middle-strength").value),
    };
  });
  const positions = middle.map((item) => item.position);
  if (new Set(positions).size !== positions.length) throw new Error("中间帧位置不能重复");

  return [
    { file: startFile, position: "start", strength: Number(els.startStrength.value) },
    ...middle.sort((left, right) => left.position - right.position),
    { file: endFile, position: "end", strength: Number(els.endStrength.value) },
  ];
}

async function prepareImagePayload() {
  if (mode !== "image_to_video") return {};
  if (referenceMode === "single") {
    const file = els.inputImage.files[0];
    if (!file) throw new Error("图生视频需要输入图片");
    setStatus("Uploading input image");
    return { imageAssetId: await uploadInputImage(file) };
  }

  const references = multiReferenceDescriptors();
  setStatus(`Uploading ${references.length} reference images`);
  const assetIds = await Promise.all(references.map((reference) => uploadInputImage(reference.file)));
  const imageConditions = references.map((reference, index) => ({
    asset_id: assetIds[index],
    position: typeof reference.position === "number" ? `${reference.position}%` : reference.position,
    strength: reference.strength,
  }));
  return { imageConditions };
}

async function createGeneration(event) {
  event.preventDefault();
  setStatus("Submitting");
  els.submitGeneration.disabled = true;
  try {
    const imagePayload = await prepareImagePayload();
    const task = await requestJson("/v1/video-generations", {
      method: "POST",
      headers: {
        ...authHeaders(),
        "Content-Type": "application/json",
        "Idempotency-Key": `web-${Date.now()}`,
      },
      body: JSON.stringify(generationPayload(imagePayload)),
    });
    rememberTask({ ...task, mode });
    setStatus(`Queued ${task.task_id}`);
    await refreshSelectedTask();
  } catch (error) {
    setStatus(error.message);
  } finally {
    els.submitGeneration.disabled = false;
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
document.querySelectorAll("[data-reference-mode]").forEach((button) => {
  button.addEventListener("click", () => setReferenceMode(button.dataset.referenceMode));
});
for (const input of [els.inputImage, els.startImage, els.endImage]) {
  input.addEventListener("change", () => updateImagePreview(input));
}
for (const input of [els.startStrength, els.endStrength]) {
  input.addEventListener("input", () => updateRangeOutput(input));
}
els.addMiddleReference.addEventListener("click", addMiddleReference);
els.saveKeys.addEventListener("click", saveKeys);
els.form.addEventListener("submit", createGeneration);
els.refreshTasks.addEventListener("click", refreshAllTasks);
els.cancelTask.addEventListener("click", cancelSelectedTask);
els.loadOps.addEventListener("click", loadOps);
els.dispatchOnce.addEventListener("click", dispatchOnce);
els.loadWorkflows.addEventListener("click", loadWorkflows);

loadKeys();
setMode(mode);
setReferenceMode(referenceMode);
updateAddReferenceState();
renderTasks(getRecentTasks());
checkHealth();
setInterval(checkHealth, 10000);
setInterval(refreshAllTasks, 5000);
