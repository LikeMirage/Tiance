import { CaretLeft, CaretRight, ClockCounterClockwise, DownloadSimple, MagnifyingGlass } from "@phosphor-icons/react";
import { useEffect, useId, useRef, useState } from "react";
import { createEditorRecordsReader } from "../../../shared/desktop/editorBrowser";
import type { EditorWebRecordKind, EditorWebRecordsPage } from "../../../shared/types/desktopShell";

const visitTime = new Intl.DateTimeFormat(undefined, {
  month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
});

const menuTitles = { history: "浏览历史", downloads: "下载" };
type PageRequest = { query: string; cursors: (string | null)[] };
type PageResult = { request: PageRequest; page?: EditorWebRecordsPage; error?: string };

function RecordsPanel({ id, kind, onSelect }: {
  id: string;
  kind: EditorWebRecordKind;
  onSelect: (target: string) => void;
}) {
  const [request, setRequest] = useState<PageRequest>({ query: "", cursors: [null] });
  const [result, setResult] = useState<PageResult>();
  const [readPage] = useState(() => createEditorRecordsReader(kind));
  const current = result?.request === request ? result : undefined;
  const page = current?.page;
  const pageNumber = request.cursors.length;

  useEffect(() => {
    let active = true;
    const cursor = request.cursors[request.cursors.length - 1];
    const query = request.query.trim();
    const read = () => {
      void readPage(query, cursor).then(
        page => { if (active) setResult({ request, page }); },
        reason => {
          if (active) setResult({ request, error: reason instanceof Error ? reason.message : "无法读取记录。" });
        },
      );
    };
    // Debounce typing on the first page. Flipping through matches reads immediately.
    let timer: number | undefined;
    if (query && !cursor) timer = window.setTimeout(read, 200);
    else read();
    return () => { active = false; window.clearTimeout(timer); };
  }, [readPage, request]);

  return <section id={id} className="editor-web__history" role="dialog" aria-label={menuTitles[kind]}>
    <header>
      <span>{menuTitles[kind]}</span>
      <label className="editor-web__history-search">
        <MagnifyingGlass aria-hidden="true" size={14} />
        <input type="search" aria-label={kind === "history" ? "搜索浏览历史" : "搜索下载记录"}
          placeholder={kind === "history" ? "搜索标题或网址" : "搜索文件名或路径"} value={request.query} autoFocus
          onChange={e => setRequest({ query: e.target.value, cursors: [null] })}
          onKeyDown={e => { if (e.key === "Enter" && !e.nativeEvent.isComposing) e.preventDefault(); }} />
      </label>
    </header>
    {page?.recentOnly && <small className="editor-web__recent-limit">当前可查最近 100 条，重启天策可查看全部。</small>}
    {page?.items.length ? <ul>{page.items.map((entry, index) => <li key={index}>
      <button type="button" className="editor-web__visit" title={entry.target} onClick={() => onSelect(entry.target)}>
        <span>{entry.title || entry.target}</span>
        <time dateTime={new Date(entry.time).toISOString()}>{visitTime.format(entry.time)}</time>
        <small>{entry.target}</small>
      </button>
    </li>)}</ul> : <p role="status">{!current ? "正在读取…" : current.error ||
      (request.query.trim() ? (kind === "downloads" ? "没有匹配的下载记录" : "没有匹配的浏览记录")
        : kind === "downloads" ? "暂无已完成的下载" : "暂无浏览记录")}
      {current?.error && <button type="button" className="editor-web__records-retry"
        onClick={() => setRequest({ ...request })}>重试</button>}
    </p>}
    {(pageNumber > 1 || page?.nextCursor) && <footer>
      <button type="button" aria-label="上一页" title="上一页" disabled={pageNumber === 1}
        onClick={() => setRequest({ ...request, cursors: request.cursors.slice(0, -1) })}><CaretLeft /></button>
      <span aria-live="polite">第 {pageNumber} 页</span>
      <button type="button" aria-label="下一页" title="下一页" disabled={!page?.nextCursor}
        onClick={() => {
          if (page?.nextCursor) setRequest({ ...request, cursors: [...request.cursors, page.nextCursor] });
        }}><CaretRight /></button>
    </footer>}
  </section>;
}

export function EditorWebHistory({ onNavigate, onOpenFile }: { onNavigate: (url: string) => void; onOpenFile: (path: string) => void }) {
  const [open, setOpen] = useState<EditorWebRecordKind | null>(null);
  const container = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) {
      if (event.target instanceof Node && !container.current?.contains(event.target)) setOpen(null);
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape" && !event.isComposing) {
        event.preventDefault();
        setOpen(null);
        trigger.current?.focus();
      }
    }
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return <div ref={container} className="editor-web__list-buttons">
    {(["downloads", "history"] as const).map(menu => (
      <button key={menu} type="button" aria-label={menuTitles[menu]} title={menuTitles[menu]} aria-haspopup="dialog"
        aria-expanded={open === menu} aria-controls={open === menu ? panelId : undefined}
        onClick={e => {
          trigger.current = e.currentTarget;
          setOpen(open === menu ? null : menu);
        }}>{menu === "downloads" ? <DownloadSimple /> : <ClockCounterClockwise />}</button>
    ))}
    {open && <RecordsPanel key={open} id={panelId} kind={open} onSelect={target => {
      setOpen(null);
      trigger.current?.focus();
      if (open === "downloads") onOpenFile(target);
      else onNavigate(target);
    }} />}
  </div>;
}
