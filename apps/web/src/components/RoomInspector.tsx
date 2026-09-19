import type { Building, Room } from "@plancheck/schemas";
import { isLowConfidence, metricLabel } from "../lib/plan";

interface Props {
  building: Building;
  room: Room | null;
}

export function RoomInspector({ building, room }: Props) {
  if (!room) {
    return (
      <div className="p-4 text-sm text-neutral-600">
        Click a room in the plan to see its measurements and where they came from.
      </div>
    );
  }

  const unitType = building.unit_types.find((u) => u.id === room.unit_type_id);
  const openings = building.openings.filter((o) => room.opening_ids.includes(o.id));

  return (
    <div className="space-y-4 p-4 text-sm">
      <header>
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-medium text-neutral-100">{room.label}</h3>
          <span className="font-mono text-xs text-neutral-500">{room.id}</span>
        </div>
        <div className="mt-0.5 font-mono text-xs text-neutral-500">{room.type}</div>
      </header>

      <Confidence room={room} />

      <Section title="Metrics">
        {Object.keys(room.metrics).length === 0 ? (
          <p className="text-xs text-neutral-600">
            Nothing measurable was extracted for this room.
          </p>
        ) : (
          <dl className="space-y-1">
            {Object.entries(room.metrics).map(([key, metric]) =>
              metric ? (
                <div key={key} className="flex items-baseline justify-between gap-3">
                  <dt className="text-xs text-neutral-400">{metricLabel(key)}</dt>
                  <dd className="font-mono text-xs text-neutral-200">
                    {metric.value.toFixed(2)} {metric.unit}
                    <span className="ml-2 text-neutral-600">
                      {Math.round(metric.confidence * 100)}%
                    </span>
                  </dd>
                </div>
              ) : null,
            )}
          </dl>
        )}
      </Section>

      {unitType && (
        <Section title="Blast radius">
          <p className="text-xs leading-relaxed text-neutral-400">
            This room is one instance of{" "}
            <span className="text-neutral-200">{unitType.label}</span>, which repeats{" "}
            <span className="font-medium text-amber-300">{unitType.count} times</span> across the
            building. Any violation here is {unitType.count} violations.
          </p>
        </Section>
      )}

      <Section title="Provenance">
        <dl className="space-y-1 text-xs">
          <Row label="Page" value={`p${room.source.page}`} />
          <Row label="Sheet" value={room.source.sheet_no ?? "—"} />
          <Row label="Tier" value={room.source.tier ?? "—"} />
          <Row label="Method" value={room.source.method} />
        </dl>
      </Section>

      {openings.length > 0 && (
        <Section title={`Openings (${openings.length})`}>
          <ul className="space-y-1 text-xs">
            {openings.map((opening) => (
              <li key={opening.id} className="flex justify-between gap-3">
                <span className="text-neutral-400">
                  {opening.kind}
                  {opening.tag ? ` ${opening.tag}` : ""}
                </span>
                <span className="font-mono text-neutral-300">
                  {opening.width_ft ? `${opening.width_ft.toFixed(2)} ft` : "width n/a"}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Violations">
        <p className="text-xs text-neutral-600">
          {room.violation_ids.length === 0
            ? "The compliance engine is not built yet, so nothing has been checked."
            : `${room.violation_ids.length} open`}
        </p>
      </Section>
    </div>
  );
}

function Confidence({ room }: { room: Room }) {
  const low = isLowConfidence(room);
  const pct = Math.round(room.confidence * 100);

  return (
    <div
      className={`rounded-md border px-3 py-2 ${
        low ? "border-amber-600/40 bg-amber-500/5" : "border-ink-700 bg-ink-900"
      }`}
    >
      <div className="flex items-baseline justify-between">
        <span className="text-xs text-neutral-400">Confidence</span>
        <span className={`font-mono text-xs ${low ? "text-amber-300" : "text-neutral-200"}`}>
          {pct}%
        </span>
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-ink-700">
        <div
          className={`h-full rounded-full ${low ? "bg-amber-500" : "bg-emerald-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {low && (
        <p className="mt-2 text-[11px] font-medium text-amber-300">Needs review</p>
      )}
      {room.confidence_notes.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {room.confidence_notes.map((note) => (
            <li key={note} className="text-[11px] leading-snug text-neutral-500">
              · {note}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="mb-1.5 text-[11px] font-medium tracking-wide text-neutral-500 uppercase">
        {title}
      </h4>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-neutral-500">{label}</dt>
      <dd className="font-mono text-neutral-300">{value}</dd>
    </div>
  );
}
