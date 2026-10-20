import { Fragment, useEffect, useState, type ReactNode } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { useDocumentReadingValue } from "../../../entities/editor/model/documentReadingState";
import { HttpRequestError } from "../../../services/http/httpClient";
import { DocumentOpenFallbackContent } from "../../document-editor-canvas/ui/UnsupportedDocumentContent";
import { checkedPreviewUrl, delimitedPreviewUrl, inspectFilePreview, isDelimitedFile, type FilePreviewInspection } from "../model/filePreview";
import "./file-preview.css";

export function FilePreviewGate({ tab, src: sourceSrc, children, onMissing }: {
  tab: DocumentTab;
  src: string;
  onMissing?: () => void;
  children: (inspection: FilePreviewInspection, checkedSrc: string) => ReactNode;
}) {
  const delimited = isDelimitedFile(tab.title ?? tab.filePath ?? "");
  const [encoding, setEncoding] = useDocumentReadingValue("delimited:encoding", "auto");
  const [delimiter, setDelimiter] = useDocumentReadingValue("delimited:delimiter", "auto");
  const formatKey = delimited ? `${encoding}:${delimiter}` : "";
  const src = delimited ? delimitedPreviewUrl(sourceSrc, encoding, delimiter) : sourceSrc;
  const [attempt, setAttempt] = useState(0);
  const [cancelled, setCancelled] = useState(false);
  const [state, setState] = useState<{
    src: string; attempt: number; formatKey: string; inspection?: FilePreviewInspection; checkedSrc?: string; error?: string;
  }>({ src, attempt, formatKey });
  useEffect(() => {
    if (cancelled) return;
    const controller = new AbortController();
    void inspectFilePreview(src, controller.signal).then(
      (inspection) => {
        if (!controller.signal.aborted) setState((previous) => ({
          src, attempt, inspection, formatKey,
          checkedSrc: inspection.version && previous.inspection?.version === inspection.version && previous.formatKey === formatKey
            ? previous.checkedSrc
            : checkedPreviewUrl(src, inspection),
        }));
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof HttpRequestError && error.status === 404) onMissing?.();
        setState({ src, attempt, formatKey, error: error instanceof Error ? error.message : "文件检查失败。" });
      },
    );
    return () => controller.abort();
    // The callback only reports the result; it is not the file's identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src, attempt, cancelled]);
  const current = state.src === src && state.attempt === attempt ? state : null;
  const inspection = state.inspection;
  const pending = !current;
  const stopped = cancelled || current?.error || inspection?.mode === "blocked";
  const checkedSrc = state.checkedSrc ?? src;
  return (
    <div className="file-preview-session">
      <div className="file-preview-session__bar" role="status">
        {delimited ? <>
          <label>编码 <select aria-label="文本编码" value={encoding} onChange={(event) => {
            setEncoding(event.target.value); setCancelled(false);
          }}>
            <option value="auto">自动识别</option><option value="utf-8-sig">UTF-8</option>
            <option value="gb18030">GBK / GB18030</option><option value="utf-16">UTF-16（BOM）</option>
          </select></label>
          <label>分隔符 <select aria-label="分隔符" value={delimiter} onChange={(event) => {
            setDelimiter(event.target.value); setCancelled(false);
          }}>
            <option value="auto">自动识别</option><option value="comma">逗号</option>
            <option value="tab">制表符</option><option value="semicolon">分号</option><option value="pipe">竖线</option>
          </select></label>
        </> : null}
        <span>{cancelled ? "预览已停止" : current?.error ? "预览失败"
          : inspection?.mode === "blocked" ? "已超过内置预览预算"
            : inspection && !pending ? "文件检查完成" : "正在检查文件与解压开销…"}</span>
        {stopped ? <button type="button" onClick={() => {
          setCancelled(false); setAttempt((value) => value + 1);
        }}>重新检查</button> : <button type="button" onClick={() => setCancelled(true)}>停止预览</button>}
      </div>
      {stopped ? (
        <DocumentOpenFallbackContent activeTab={tab}
          heading={cancelled ? "已停止本次预览" : "无法继续内置预览"}
          detail={current?.error ?? inspection?.message} />
      ) : inspection ? (
        <div className="file-preview-session__content" inert={pending} aria-busy={pending}>
          <Fragment key={`${inspection.version ?? checkedSrc}:${state.formatKey}:${attempt}`}>
            {children(inspection, checkedSrc)}
          </Fragment>
        </div>
      ) : (
        <div className="file-preview-session__waiting">正在准备文件，可以取消或切换到其他文件。</div>
      )}
    </div>
  );
}
