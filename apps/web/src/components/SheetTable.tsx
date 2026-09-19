import type { Sheet, SheetRole } from "@plancheck/schemas";

interface Props {
  sheets: Sheet[];
  selected: Set<number>;
  onToggle: (page: number) => void;
  onSelectRecommended: () => void;
}

/** Roles worth extracting, in the order the pipeline relies on them. */
const ROLE_STYLE: Record<SheetRole, { label: string; className: string }> = {
  floor_plan: { label: "floor plan", className: "bg-emerald-500/15 text-emerald-300" },
  enlarged_plan: { label: "enlarged", className: "bg-teal-500/15 text-teal-300" },
  unit_plan: { label: "unit plan", className: "bg-blue-500/15 text-blue-300" },
  schedule: { label: "schedule", className: "bg-amber-500/15 text-amber-300" },
  code_matrix: { label: "code", className: "bg-purple-500/15 text-purple-300" },
  elevation: { label: "elevation", className: "bg-ink-700 text-neutral-400" },
  section: { label: "section", className: "bg-ink-700 text-neutral-400" },
  detail: { label: "detail", className: "bg-ink-700 text-neutral-400" },
  site: { label: "site", className: "bg-ink-700 text-neutral-400" },
  roof: { label: "roof", className: "bg-ink-700 text-neutral-400" },
  edge_of_slab: { label: "slab", className: "bg-ink-700 text-neutral-400" },
  index: { label: "index", className: "bg-ink-700 text-neutral-400" },
  unknown: { label: "unknown", className: "bg-ink-700 text-neutral-500" },
};

export function SheetTable({ sheets, selected, onToggle, onSelectRecommended }: Props) {
  const recommended = sheets.filter((s) => s.use).length;

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-medium tracking-wide text-neutral-300 uppercase">
          Sheets · {selected.size} of {sheets.length} selected
        </h2>
        <button
          type="button"
          onClick={onSelectRecommended}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          Select {recommended} recommended
        </button>
      </div>

      <ul className="min-h-0 flex-1 overflow-y-auto rounded-md border border-ink-700 bg-ink-900 text-sm">
        {sheets.map((sheet) => {
          const isSelected = selected.has(sheet.page);
          const role = ROLE_STYLE[sheet.role];
          return (
            <li key={sheet.page} className="border-b border-ink-800 last:border-b-0">
              <label
                className={`flex cursor-pointer gap-3 px-3 py-2 transition hover:bg-ink-800 ${
                  isSelected ? "bg-blue-500/5" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => onToggle(sheet.page)}
                  className="mt-1 size-3.5 shrink-0 accent-blue-500"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2">
                    <span className="w-8 shrink-0 text-xs text-neutral-600">p{sheet.page}</span>
                    <span className="shrink-0 font-mono text-xs text-neutral-300">
                      {sheet.sheet_no ?? "—"}
                    </span>
                    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${role.className}`}>
                      {role.label}
                    </span>
                    {sheet.scale && (
                      <span className="shrink-0 font-mono text-[10px] text-neutral-500">
                        {sheet.scale}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 truncate text-xs text-neutral-400">
                    {sheet.title ?? "Untitled sheet"}
                  </div>
                  {/* The stated reason is the point of this view: it shows what we
                      are ignoring and why, rather than silently dropping pages. */}
                  <div className="mt-0.5 text-[11px] leading-snug text-neutral-600">
                    {sheet.reason}
                  </div>
                </div>
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
