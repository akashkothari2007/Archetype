/** Fetch client — one function per PlanCheck endpoint. */

async function json(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${url}: ${body}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export function createProject(drawings, standards) {
  const fd = new FormData();
  for (const f of drawings) fd.append("drawings", f);
  for (const f of standards) fd.append("standards", f);
  return json("/api/projects", { method: "POST", body: fd });
}

export function listProjects() {
  return json("/api/projects");
}

export function getProject(id) {
  return json(`/api/projects/${id}`);
}

export function patchSheet(projectId, sheetId, body) {
  return json(`/api/projects/${projectId}/sheets/${sheetId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function startExtract(projectId, pages = "auto") {
  return json(`/api/projects/${projectId}/extract`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pages }),
  });
}

export function getSheet(projectId, sheetId) {
  return json(`/api/projects/${projectId}/sheets/${sheetId}`);
}

export function rasterUrl(projectId, sheetId) {
  return `/api/projects/${projectId}/sheets/${sheetId}/raster.png`;
}

export function startModel(projectId) {
  return json(`/api/projects/${projectId}/model`, { method: "POST" });
}

export function getModel(projectId) {
  return json(`/api/projects/${projectId}/model`);
}

export function startRules(projectId) {
  return json(`/api/projects/${projectId}/rules`, { method: "POST" });
}

export function getRules(projectId) {
  return json(`/api/projects/${projectId}/rules`);
}

export function startCheck(projectId) {
  return json(`/api/projects/${projectId}/check`, { method: "POST" });
}

export function getMismatches(projectId) {
  return json(`/api/projects/${projectId}/mismatches`);
}

export function startAgent(projectId) {
  return json(`/api/projects/${projectId}/agent`, { method: "POST" });
}

export function getProposedEdits(projectId) {
  return json(`/api/projects/${projectId}/proposed-edits`);
}

export function getJob(jobId) {
  return json(`/api/jobs/${jobId}`);
}

export async function pollJob(jobId, onProgress) {
  for (;;) {
    const job = await getJob(jobId);
    if (onProgress) onProgress(job);
    if (job.state === "done") return job;
    if (job.state === "error") throw new Error(job.error || "job failed");
    await new Promise((r) => setTimeout(r, 400));
  }
}
