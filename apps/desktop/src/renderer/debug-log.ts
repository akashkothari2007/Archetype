export type LogKind = 'net' | 'console';
export type LogLevel = 'log' | 'info' | 'warn' | 'error' | 'debug';

export type LogEntry = {
  id: number
  t: number
  kind: LogKind
  level: LogLevel
  text: string
  detail?: string
  method?: string
  url?: string
  status?: number
  ms?: number
  pending?: boolean
};

const MAX = 800;
const BODY = 12_000;
const entries: LogEntry[] = [];
const listeners = new Set<() => void>();
let seq = 0;
let installed = false;
let scheduled = false;
let recording = false;

export function logEntries(): readonly LogEntry[] {
  return entries;
}

export function subscribeLogs(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function clearLogs() {
  entries.length = 0;
  notify();
}

export function resetDebugLog() {
  entries.length = 0;
  seq = 0;
  listeners.clear();
  scheduled = false;
}

export function shortUrl(url: string): string {
  try {
    const parsed = new URL(url, 'http://127.0.0.1');
    const path = parsed.pathname.replace(/^\/api\/desktop/, '') + parsed.search;
    return path || url;
  } catch {
    return url;
  }
}

export function formatArg(value: unknown): string {
  if (value instanceof Error) return value.stack || value.message;
  if (typeof value === 'string') return value.length > BODY ? value.slice(0, BODY) + '…' : value;
  if (typeof value === 'number' || typeof value === 'boolean' || value == null) return String(value);
  try {
    const json = JSON.stringify(value);
    if (json && json !== '{}') return json.length > BODY ? json.slice(0, BODY) + '…' : json;
  } catch {}
  return String(value);
}

export function formatArgs(args: unknown[]): string {
  let out = '';
  for (let i = 0; i < args.length; i++) {
    if (i) out += ' ';
    out += formatArg(args[i]);
    if (out.length > BODY) return out.slice(0, BODY) + '…';
  }
  return out;
}

export function recordConsole(level: LogLevel, args: unknown[]) {
  if (recording) return;
  recording = true;
  try {
    add({
      kind: 'console',
      level,
      text: formatArgs(args) || level,
    });
  } finally {
    recording = false;
  }
}

export function beginNetwork(method: string, url: string, request?: string): number {
  const id = ++seq;
  add({
    id,
    kind: 'net',
    level: 'log',
    method,
    url,
    pending: true,
    text: shortUrl(url),
    detail: request ? `→ ${request}` : undefined,
  });
  return id;
}

export function endNetwork(id: number, info: {status?: number; ms: number; body?: string; error?: string}) {
  const entry = entries.find(item => item.id === id);
  const failed = !!(info.error || (info.status && info.status >= 400));
  const status = info.error ? 'ERR' : String(info.status ?? '');
  const url = shortUrl(entry?.url || '');
  const method = entry?.method || 'GET';
  const text = `${url} ${status} ${Math.round(info.ms)}ms`;
  const parts = [entry?.detail, info.body ? `← ${info.body}` : '', info.error || ''].filter(Boolean);
  if (entry) {
    entry.text = text;
    entry.status = info.status;
    entry.ms = Math.round(info.ms);
    entry.pending = false;
    entry.level = failed ? 'error' : 'log';
    entry.detail = parts.length ? parts.join('\n') : undefined;
    notify();
    return;
  }
  add({
    kind: 'net',
    level: failed ? 'error' : 'log',
    method,
    status: info.status,
    ms: Math.round(info.ms),
    text,
    detail: parts.length ? parts.join('\n') : undefined,
  });
}

function add(partial: Omit<LogEntry, 'id' | 't' | 'level'> & Partial<Pick<LogEntry, 'id' | 't' | 'level'>>) {
  entries.push({
    id: partial.id ?? ++seq,
    t: partial.t ?? Date.now(),
    level: partial.level ?? 'log',
    kind: partial.kind,
    text: partial.text,
    detail: partial.detail,
    method: partial.method,
    url: partial.url,
    status: partial.status,
    ms: partial.ms,
    pending: partial.pending,
  });
  if (entries.length > MAX) entries.splice(0, entries.length - MAX);
  notify();
}

function notify() {
  if (scheduled) return;
  scheduled = true;
  const flush = () => {
    scheduled = false;
    listeners.forEach(fn => fn());
  };
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(flush);
  else queueMicrotask(flush);
}

function skipUrl(url: string) {
  return /\/@vite\/|\/@fs\/|\/@react-refresh|\/node_modules\/|\/src\/renderer\//.test(url);
}

function describeBody(body: unknown): string | undefined {
  if (body == null) return;
  if (typeof body === 'string') return body.length > BODY ? body.slice(0, BODY) + '…' : body;
  if (body instanceof FormData) return `[form ${[...body.keys()].join(', ')}]`;
  if (body instanceof URLSearchParams) return body.toString();
  if (body instanceof Blob) return `[blob ${body.size}b ${body.type}]`;
  if (body instanceof ArrayBuffer) return `[arraybuffer ${body.byteLength}b]`;
  if (ArrayBuffer.isView(body)) return `[bytes ${body.byteLength}b]`;
  try { return formatArg(body); } catch { return '[body]'; }
}

function textish(type: string) {
  return /json|text|xml|javascript|urlencoded|svg/i.test(type);
}

async function peekBody(response: Response): Promise<string | undefined> {
  const type = response.headers.get('content-type') || '';
  if (!textish(type)) {
    const len = response.headers.get('content-length');
    return `[${type || 'binary'}${len ? ` ${len}b` : ''}]`;
  }
  try {
    const reader = response.clone().body?.getReader();
    if (!reader) {
      const text = await response.clone().text();
      return text.length > BODY ? text.slice(0, BODY) + '…' : text;
    }
    const decoder = new TextDecoder();
    let out = '';
    for (;;) {
      const {done, value} = await reader.read();
      if (done) break;
      out += decoder.decode(value, {stream: true});
      if (out.length >= BODY) {
        reader.cancel().catch(() => {});
        return out.slice(0, BODY) + '…';
      }
    }
    return out;
  } catch {
    return;
  }
}

function patchFetch() {
  const original = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : null;
    const url = request ? request.url : String(input);
    if (skipUrl(url)) return original(input, init);
    const method = (init?.method || request?.method || 'GET').toUpperCase();
    const id = beginNetwork(method, url, describeBody(init?.body ?? null));
    const started = performance.now();
    try {
      const response = await original(input, init);
      const body = await peekBody(response);
      endNetwork(id, {status: response.status, ms: performance.now() - started, body});
      return response;
    } catch (error) {
      endNetwork(id, {ms: performance.now() - started, error: error instanceof Error ? error.message : String(error)});
      throw error;
    }
  };
}

function patchXhr() {
  const meta = new WeakMap<XMLHttpRequest, {method: string; url: string; t: number; id: number}>();
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(this: XMLHttpRequest, method: string, url: string | URL, ...rest: unknown[]) {
    meta.set(this, {method: String(method).toUpperCase(), url: String(url), t: 0, id: 0});
    return (open as (...args: unknown[]) => void).apply(this, [method, url, ...rest]);
  } as typeof XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function(this: XMLHttpRequest, body?: Document | XMLHttpRequestBodyInit | null) {
    const item = meta.get(this);
    if (item && !skipUrl(item.url)) {
      item.t = performance.now();
      item.id = beginNetwork(item.method, item.url, describeBody(body));
      this.addEventListener('loadend', () => {
        const response = this.responseType === '' || this.responseType === 'text' ? String(this.responseText || '').slice(0, BODY) : `[${this.responseType || 'binary'}]`;
        endNetwork(item.id, {
          status: this.status || undefined,
          ms: performance.now() - item.t,
          body: response,
          error: this.status === 0 ? 'network error' : undefined,
        });
      });
    }
    return send.call(this, body);
  };
}

function patchConsole() {
  (['log', 'info', 'warn', 'error', 'debug'] as const).forEach(level => {
    const original = console[level].bind(console);
    console[level] = (...args: unknown[]) => {
      original(...args);
      recordConsole(level, args);
    };
  });
}

export function installDebugLog() {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  patchFetch();
  patchXhr();
  patchConsole();
  window.addEventListener('error', event => {
    recordConsole('error', [event.message, event.filename ? `${event.filename}:${event.lineno}` : '']);
  });
  window.addEventListener('unhandledrejection', event => {
    recordConsole('error', ['unhandledrejection', event.reason]);
  });
}
