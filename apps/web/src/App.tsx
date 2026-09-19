import { useEffect, useMemo, useState } from "react";

import type { Building, Project } from "@plancheck/schemas";
import * as api from "./api/client";
import { JsonPanel } from "./components/JsonPanel";
import { PlanViewer2D } from "./components/PlanViewer2D";
import { RoomInspector } from "./components/RoomInspector";
import { SheetTable } from "./components/SheetTable";
import { UploadPanel } from "./components/UploadPanel";

type Tab = "plan" | "building" | "project";
type Busy = "idle" | "uploading" | "extracting";

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [building, setBuilding] = useState<Building | null>(null);
  const [selectedPages, setSelectedPages] = useState<Set<number>>(new Set());
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("plan");
  const [busy, setBusy] = useState<Busy>("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [engines, setEngines] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    api.health().then((h) => setEngines(h.engines)).catch(() => setEngines(null));
  }, []);

  const selectedRoom = useMemo(
    () => building?.rooms.find((r) => r.id === selectedRoomId) ?? null,
    [building, selectedRoomId],
  );

  const upload = async (files: { drawings: File; standards: File | null }) => {
    setBusy("uploading");
    setError(null);
    setBuilding(null);
    setSelectedRoomId(null);
    setElapsed(null);
    try {
      const next = await api.createProject(files);
      setProject(next);
      setSelectedPages(new Set(next.sheets.filter((s) => s.use).map((s) => s.page)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("idle");
    }
  };

  const extract = async () => {
    if (!project) return;
    setBusy("extracting");
    setError(null);
    try {
      const result = await api.extractBuilding(project.project_id, [...selectedPages].sort((a, b) => a - b));
      setBuilding(result.building);
      setElapsed(result.elapsed_ms);
      setSelectedRoomId(null);
      setTab("plan");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("idle");
    }
  };

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center justify-between border-b border-ink-800 px-4 py-2.5">
        <div className="flex items-baseline gap-3">
          <h1 className="text-sm font-semibold tracking-tight text-neutral-100">PlanCheck</h1>
          <span className="text-xs text-neutral-600">
            drawings → building.json → 2D
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {engines &&
            Object.entries(engines).map(([name, kind]) => (
              <span
                key={name}
                className="rounded border border-amber-600/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300"
                title={`The ${name} is not implemented yet and returns generated data.`}
              >
                {name}: {kind}
              </span>
            ))}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[360px] shrink-0 flex-col gap-4 overflow-y-auto border-r border-ink-800 p-4">
          <UploadPanel busy={busy === "uploading"} onSubmit={upload} />

          {error && (
            <div className="rounded-md border border-red-600/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {error}
            </div>
          )}

          {project && (
            <>
              <ProjectSummary project={project} />

              <div className="flex min-h-0 flex-1 flex-col">
                <SheetTable
                  sheets={project.sheets}
                  selected={selectedPages}
                  onToggle={(page) =>
                    setSelectedPages((prev) => {
                      const next = new Set(prev);
                      if (!next.delete(page)) next.add(page);
                      return next;
                    })
                  }
                  onSelectRecommended={() =>
                    setSelectedPages(new Set(project.sheets.filter((s) => s.use).map((s) => s.page)))
                  }
                />
              </div>

              <button
                type="button"
                onClick={extract}
                disabled={selectedPages.size === 0 || busy !== "idle"}
                className="shrink-0 rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white transition
                           hover:bg-emerald-500 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-neutral-500"
              >
                {busy === "extracting"
                  ? "Extracting…"
                  : `Extract building.json from ${selectedPages.size} sheet${selectedPages.size === 1 ? "" : "s"}`}
              </button>
            </>
          )}
        </aside>

        <main className="flex min-w-0 flex-1 flex-col">
          <nav className="flex shrink-0 items-center gap-1 border-b border-ink-800 px-3 py-1.5">
            {(["plan", "building", "project"] as const).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                disabled={key !== "project" && !building}
                className={`rounded px-2.5 py-1 text-xs transition disabled:cursor-not-allowed disabled:text-neutral-700 ${
                  tab === key ? "bg-ink-700 text-neutral-100" : "text-neutral-500 hover:text-neutral-300"
                }`}
              >
                {key === "plan" ? "2D plan" : key === "building" ? "building.json" : "project.json"}
              </button>
            ))}
            {elapsed !== null && (
              <span className="ml-auto text-[11px] text-neutral-600">extracted in {elapsed} ms</span>
            )}
          </nav>

          <div className="min-h-0 flex-1">
            {tab === "plan" &&
              (building ? (
                <PlanViewer2D
                  building={building}
                  selectedRoomId={selectedRoomId}
                  onSelectRoom={setSelectedRoomId}
                />
              ) : (
                <Empty>Upload a drawing set, pick sheets, then extract.</Empty>
              ))}

            {tab === "building" &&
              (building ? (
                <JsonPanel value={building} filename="building.json" />
              ) : (
                <Empty>No extraction yet.</Empty>
              ))}

            {tab === "project" &&
              (project ? (
                <JsonPanel value={project} filename="project.json" />
              ) : (
                <Empty>No project yet.</Empty>
              ))}
          </div>
        </main>

        {building && (
          <aside className="w-[300px] shrink-0 overflow-y-auto border-l border-ink-800">
            <RoomInspector building={building} room={selectedRoom} />
            {building.warnings.length > 0 && (
              <div className="border-t border-ink-800 p-4">
                <h4 className="mb-1.5 text-[11px] font-medium tracking-wide text-neutral-500 uppercase">
                  Warnings
                </h4>
                <ul className="space-y-1.5">
                  {building.warnings.map((warning) => (
                    <li key={warning} className="text-[11px] leading-snug text-amber-400/80">
                      {warning}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

function ProjectSummary({ project }: { project: Project }) {
  const counts = project.sheets.reduce<Record<string, number>>((acc, sheet) => {
    acc[sheet.role] = (acc[sheet.role] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="rounded-md border border-ink-700 bg-ink-900 p-3">
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-neutral-400">Project</span>
        <span className="font-mono text-[11px] text-neutral-500">{project.project_id}</span>
      </div>
      <ul className="mt-2 space-y-0.5">
        {project.documents.map((doc) => (
          <li key={doc.kind} className="flex justify-between gap-2 text-[11px]">
            <span className="truncate text-neutral-400">{doc.filename}</span>
            <span className="shrink-0 font-mono text-neutral-600">
              {doc.page_count ? `${doc.page_count}pp` : "—"}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-neutral-600">
        {Object.entries(counts).map(([role, count]) => (
          <span key={role}>
            {count} {role.replace(/_/g, " ")}
          </span>
        ))}
      </div>
      {project.warnings.map((warning) => (
        <p key={warning} className="mt-2 text-[11px] leading-snug text-amber-400/70">
          {warning}
        </p>
      ))}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-8 text-center text-sm text-neutral-600">
      {children}
    </div>
  );
}
