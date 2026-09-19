import * as api from "./api.js";
import * as store from "./state.js";
import { renderSheet, enablePanZoom, layerCounts, LAYERS } from "./sheet2d.js";

const $ = (id) => document.getElementById(id);
const hiddenLayers = new Set();

function setStatus(text) {
  const el = $("status");
  if (!text) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = text;
}

function fileNames(input, list) {
  list.replaceChildren();
  for (const f of input.files) {
    const li = document.createElement("li");
    li.textContent = f.name;
    list.appendChild(li);
  }
}

function wireDrop(drop, input, list) {
  drop.addEventListener("dragover", (e) => { e.preventDefault(); });
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    input.files = e.dataTransfer.files;
    fileNames(input, list);
  });
  input.addEventListener("change", () => fileNames(input, list));
}

function renderTable(project) {
  const tbody = $("sheet-table").querySelector("tbody");
  tbody.replaceChildren();
  for (const sheet of project.sheets || []) {
    const tr = document.createElement("tr");
    const use = document.createElement("input");
    use.type = "checkbox";
    use.checked = sheet.use;
    use.addEventListener("change", async () => {
      await api.patchSheet(project.project_id, sheet.sheet_id, { use: use.checked });
      const updated = await api.getProject(project.project_id);
      store.set({ project: updated });
    });
    tr.innerHTML = `
      <td>${sheet.page}</td>
      <td>${sheet.sheet_no || ""}</td>
      <td>${sheet.title || ""}</td>
      <td>${sheet.role}</td>
      <td>${sheet.scale_text || ""}</td>
      <td></td>
      <td class="reason">${sheet.reason || ""}</td>`;
    tr.children[5].appendChild(use);
    tbody.appendChild(tr);
  }
  $("btn-extract").disabled = !(project.sheets || []).some((s) => s.use);
}

function fillSheetPicker(project) {
  const select = $("sheet-picker");
  const current = select.value;
  select.replaceChildren();
  for (const sheet of project.sheets || []) {
    if (!sheet.geometry_file) continue;
    const opt = document.createElement("option");
    opt.value = sheet.sheet_id;
    opt.textContent = `${sheet.sheet_no || sheet.sheet_id}  p.${sheet.page}`;
    select.appendChild(opt);
  }
  if ([...select.options].some((o) => o.value === current)) select.value = current;
}

async function showSheet(sheetId) {
  const { projectId } = store.get();
  if (!projectId || !sheetId) return;
  const geom = await api.getSheet(projectId, sheetId);
  const svg = $("sheet-svg");
  renderSheet(svg, geom, hiddenLayers);
  enablePanZoom(svg);
  const counts = layerCounts(geom);
  $("counts").textContent = Object.entries(counts)
    .map(([k, n]) => `${n} ${k}`)
    .join(" · ");
  const toggles = $("layer-toggles");
  toggles.replaceChildren();
  for (const [, layer] of LAYERS) {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = !hiddenLayers.has(layer);
    box.addEventListener("change", () => {
      if (box.checked) hiddenLayers.delete(layer);
      else hiddenLayers.add(layer);
      renderSheet(svg, geom, hiddenLayers);
    });
    label.append(box, ` ${layer}`);
    toggles.appendChild(label);
  }
}

function renderSpaceTypes(model) {
  const ul = $("space-types");
  ul.replaceChildren();
  for (const st of model.space_types || []) {
    const li = document.createElement("li");
    li.textContent = `${st.name}  ${st.area_sqft} sqft / ${st.area_m2} m²  ×${st.instance_count}`;
    ul.appendChild(li);
  }
}

async function runJob(start) {
  const { job_id } = await start();
  await api.pollJob(job_id, (job) => {
    store.set({ job });
    setStatus(`${job.state}  ${Math.round((job.progress || 0) * 100)}%  ${job.message || ""}`);
  });
}

function showTab(name) {
  store.set({ tab: name });
  for (const btn of document.querySelectorAll(".tabs button")) {
    btn.classList.toggle("active", btn.dataset.tab === name);
  }
  for (const section of document.querySelectorAll("section.tab")) {
    section.hidden = section.id !== `tab-${name}`;
  }
}

wireDrop($("drop-drawings"), $("file-drawings"), $("list-drawings"));
wireDrop($("drop-standards"), $("file-standards"), $("list-standards"));

for (const btn of document.querySelectorAll(".tabs button")) {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
}

$("btn-create").addEventListener("click", async () => {
  const drawings = [...$("file-drawings").files];
  const standards = [...$("file-standards").files];
  if (!drawings.length) {
    setStatus("Add at least one drawings PDF.");
    return;
  }
  setStatus("Creating project…");
  const created = await api.createProject(drawings, standards);
  store.set({ projectId: created.project_id });
  await api.pollJob(created.job_id, (job) => {
    setStatus(`${job.state}  ${Math.round((job.progress || 0) * 100)}%  ${job.message || ""}`);
  });
  const project = await api.getProject(created.project_id);
  store.set({ project });
  renderTable(project);
  fillSheetPicker(project);
  setStatus(`Classified ${project.sheets.length} pages.`);
});

$("btn-extract").addEventListener("click", async () => {
  const { projectId } = store.get();
  await runJob(() => api.startExtract(projectId, "auto"));
  const project = await api.getProject(projectId);
  store.set({ project });
  fillSheetPicker(project);
  setStatus("Extract finished.");
  if ($("sheet-picker").value) await showSheet($("sheet-picker").value);
});

$("sheet-picker").addEventListener("change", (e) => showSheet(e.target.value));

$("btn-model").addEventListener("click", async () => {
  const { projectId } = store.get();
  await runJob(() => api.startModel(projectId));
  const model = await api.getModel(projectId);
  store.set({ model });
  renderSpaceTypes(model);
});

$("btn-rules").addEventListener("click", async () => {
  const { projectId } = store.get();
  await runJob(() => api.startRules(projectId));
});

$("btn-check").addEventListener("click", async () => {
  const { projectId } = store.get();
  await runJob(() => api.startCheck(projectId));
});
