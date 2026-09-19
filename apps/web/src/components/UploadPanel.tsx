import { useRef, useState } from "react";

import { formatBytes } from "../lib/plan";

interface Props {
  busy: boolean;
  onSubmit: (files: { drawings: File; standards: File | null }) => void;
}

export function UploadPanel({ busy, onSubmit }: Props) {
  const [drawings, setDrawings] = useState<File | null>(null);
  const [standards, setStandards] = useState<File | null>(null);

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (drawings) onSubmit({ drawings, standards });
      }}
    >
      <FileSlot
        label="Drawing set"
        hint="Full architectural PDF. We classify every sheet and tell you which ones matter."
        file={drawings}
        onChange={setDrawings}
        required
      />
      <FileSlot
        label="Brand standards"
        hint="Optional for now. The rules engine is not wired up yet."
        file={standards}
        onChange={setStandards}
      />

      <button
        type="submit"
        disabled={!drawings || busy}
        className="w-full rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white transition
                   hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-ink-700 disabled:text-neutral-500"
      >
        {busy ? "Classifying sheets…" : "Upload and classify"}
      </button>
    </form>
  );
}

interface FileSlotProps {
  label: string;
  hint: string;
  file: File | null;
  required?: boolean;
  onChange: (file: File | null) => void;
}

function FileSlot({ label, hint, file, required, onChange }: FileSlotProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const accept = (list: FileList | null) => {
    const next = list?.[0] ?? null;
    if (next && next.type !== "application/pdf" && !next.name.toLowerCase().endsWith(".pdf")) return;
    onChange(next);
  };

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-xs font-medium tracking-wide text-neutral-300 uppercase">
          {label}
          {required && <span className="ml-1 text-blue-400">*</span>}
        </span>
        {file && (
          <button
            type="button"
            onClick={() => {
              onChange(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
            className="text-xs text-neutral-500 hover:text-neutral-300"
          >
            clear
          </button>
        )}
      </div>

      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          accept(e.dataTransfer.files);
        }}
        className={`w-full rounded-md border border-dashed px-3 py-3 text-left transition ${
          dragging ? "border-blue-500 bg-blue-500/10" : "border-ink-600 hover:border-ink-600/80 hover:bg-ink-800"
        }`}
      >
        {file ? (
          <>
            <div className="truncate text-sm text-neutral-100">{file.name}</div>
            <div className="text-xs text-neutral-500">{formatBytes(file.size)}</div>
          </>
        ) : (
          <>
            <div className="text-sm text-neutral-400">Drop a PDF or click to choose</div>
            <div className="mt-0.5 text-xs text-neutral-600">{hint}</div>
          </>
        )}
      </button>

      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(e) => accept(e.target.files)}
      />
    </div>
  );
}
