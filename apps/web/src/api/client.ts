import type { Building, ExtractResponse, Project } from "@plancheck/schemas";

const BASE = "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function unwrap<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;

  // FastAPI puts the message in `detail`, which is either a string or a
  // validation error array.
  let message = response.statusText;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") message = body.detail;
    else if (Array.isArray(body?.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* non-JSON error body, keep the status text */
  }
  throw new ApiError(message, response.status);
}

export async function health(): Promise<{
  status: string;
  schema_version: string;
  engines: Record<string, string>;
  toolchain: Record<string, boolean>;
}> {
  return unwrap(await fetch(`${BASE}/health`));
}

/** Upload a drawing set (and optionally a standards manual) and classify it. */
export async function createProject(files: {
  drawings: File;
  standards?: File | null;
}): Promise<Project> {
  const form = new FormData();
  form.append("drawings", files.drawings);
  if (files.standards) form.append("standards", files.standards);

  return unwrap(await fetch(`${BASE}/projects`, { method: "POST", body: form }));
}

export async function getProject(projectId: string): Promise<Project> {
  return unwrap(await fetch(`${BASE}/projects/${projectId}`));
}

/** Run E1 over the given pages. Pass "auto" for every sheet marked usable. */
export async function extractBuilding(
  projectId: string,
  pages: number[] | "auto",
): Promise<ExtractResponse> {
  return unwrap(
    await fetch(`${BASE}/projects/${projectId}/extract`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pages }),
    }),
  );
}

export async function getBuilding(projectId: string): Promise<Building> {
  return unwrap(await fetch(`${BASE}/projects/${projectId}/building`));
}
