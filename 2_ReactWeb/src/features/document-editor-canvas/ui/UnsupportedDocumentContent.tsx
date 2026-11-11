import { useEffect, useState } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { createDocumentExternalFileActions } from "../model/documentExternalFileActions";
import type { DocumentExternalFileActions } from "../model/documentExternalFileActions";
import { REFERENCE_UNAVAILABLE } from "../../../entities/editor/model/editorReference";

type DocumentOpenFallbackContentProps = {
  activeTab: DocumentTab;
  detail?: string | null;
  heading: string;
  actions?: DocumentExternalFileActions | null;
  extraAction?: { label: string; run: () => Promise<void> };
  reference?: boolean;
};


export function UnsupportedDocumentContent({ activeTab }: { activeTab: DocumentTab }) {
  return (
    <DocumentOpenFallbackContent
      activeTab={activeTab}
      heading="不支持展示此类文件"
    />
  );
}


export function DocumentOpenFallbackContent({
  activeTab,
  detail = null,
  heading,
  actions,
  extraAction,
  reference = false,
}: DocumentOpenFallbackContentProps) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => { setMissing(false); setActionError(null); }, [activeTab.id, activeTab.referenceResolution]);
  const externalFileActions = actions === undefined ? createDocumentExternalFileActions(activeTab) : actions;

  const runAction = async (action: (() => Promise<void>) | null) => {
    if (!action) return;
    setActionError(null);
    try {
      await action();
    } catch (err) {
      if (reference && err && typeof err === "object" && "status" in err && err.status === 404) setMissing(true);
      else setActionError(err instanceof Error ? err.message : "操作失败。");
    }
  };

  return (
    <div className="doc-editor__unsupported" role="status">
      <div className="doc-editor__unsupported-card">
        <strong>{missing ? REFERENCE_UNAVAILABLE : heading}</strong>
        {detail ? <span>{detail}</span> : null}
        <span className="doc-editor__unsupported-name">{activeTab.title}</span>
        <span className="doc-editor__unsupported-path" title={activeTab.displayPath}>
          {activeTab.displayPath}
        </span>
        {!missing && externalFileActions ? <div className="doc-editor__unsupported-actions">
          <button
            className="doc-editor__unsupported-button"
            disabled={!externalFileActions.revealFile}
            type="button"
            onClick={() => { void runAction(externalFileActions.revealFile); }}
          >
            在文件夹中显示
          </button>
          <button
            className="doc-editor__unsupported-button"
            disabled={!externalFileActions.openNativeFile}
            type="button"
            onClick={() => { void runAction(externalFileActions.openNativeFile); }}
          >
            用默认应用打开
          </button>
          {extraAction ? <button className="doc-editor__unsupported-button" type="button"
            onClick={() => { void runAction(extraAction.run); }}>{extraAction.label}</button> : null}
        </div> : null}
        {actionError ? (
          <span className="doc-editor__unsupported-error">{actionError}</span>
        ) : null}
      </div>
    </div>
  );
}
