import { useMemo, useState } from "react";

interface Props {
  value: unknown;
  filename: string;
}

/** Raw artifact view. The JSON is the contract between engines, so seeing it
 *  verbatim matters more than a prettier summary. */
export function JsonPanel({ value, filename }: Props) {
  const [copied, setCopied] = useState(false);
  const text = useMemo(() => JSON.stringify(value, null, 2), [value]);

  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-ink-800 px-3 py-1.5">
        <span className="font-mono text-xs text-neutral-500">
          {filename} · {(text.length / 1024).toFixed(1)} KB
        </span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => {
              void navigator.clipboard.writeText(text);
              setCopied(true);
              setTimeout(() => setCopied(false), 1200);
            }}
            className="rounded px-2 py-1 text-xs text-neutral-400 hover:bg-ink-700 hover:text-neutral-200"
          >
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            onClick={download}
            className="rounded px-2 py-1 text-xs text-neutral-400 hover:bg-ink-700 hover:text-neutral-200"
          >
            Download
          </button>
        </div>
      </div>
      <pre className="min-h-0 flex-1 overflow-auto p-3 font-mono text-xs leading-relaxed text-neutral-300">
        {text}
      </pre>
    </div>
  );
}
