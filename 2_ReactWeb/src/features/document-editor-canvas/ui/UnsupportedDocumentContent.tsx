import { useState } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { createDocumentExternalFileActions } from "../model/documentExternalFileActions";

export function UnsupportedDocumentContent({ activeTab }: { activeTab: DocumentTab }) {
  const [actionError, setActionError] = useState<string | null>(null);
  const externalFileActions = createDocumentExternalFileActions(activeTab);

  const runAction = async (action: (() => Promise<void>) | null) => {
    if (!action) return;
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "操作失败。");
    }
  };

  return (
    <div className="doc-editor__unsupported" role="status">
      <div className="doc-editor__unsupported-card">
        <strong>不支持展示此类文件</strong>
        <span className="doc-editor__unsupported-name">{activeTab.title}</span>
        <span className="doc-editor__unsupported-path" title={activeTab.displayPath}>
          {activeTab.displayPath}
        </span>
        <div className="doc-editor__unsupported-actions">
          <button
            className="doc-editor__unsupported-button"
            disabled={!externalFileActions.openNativeFile}
            type="button"
            onClick={() => { void runAction(externalFileActions.openNativeFile); }}
          >
            用系统默认程序打开
          </button>
          <button
            className="doc-editor__unsupported-button"
            disabled={!externalFileActions.revealFile}
            type="button"
            onClick={() => { void runAction(externalFileActions.revealFile); }}
          >
            在资源管理器中显示
          </button>
        </div>
        {actionError ? (
          <span className="doc-editor__unsupported-error">{actionError}</span>
        ) : null}
      </div>
    </div>
  );
}
