import { Component, Suspense } from "react";
import type { ErrorInfo, ReactNode } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { LoadingStrip } from "../../../shared/ui/loading-strip";
import { useDocumentRevealRequest } from "../../../entities/editor/model/documentRevealContext";

export function buildEditorContentResetKey(tab: DocumentTab) {
  return [
    tab.id,
    tab.kind,
    tab.assetVersion ?? "",
    tab.mtimeMs ?? "",
    tab.filePath ?? "",
    tab.projectFilePath ?? "",
    hashContent(tab.content),
  ].join(":");
}

function hashContent(content: string) {
  let hash = 0;
  for (let index = 0; index < content.length; index += 1) {
    hash = Math.imul(31, hash) + content.charCodeAt(index) | 0;
  }
  return `${content.length}:${hash.toString(36)}`;
}

export function EditorLazyBoundary({ children, resetKey }: { children: ReactNode; resetKey: string }) {
  const revealRequest = useDocumentRevealRequest();
  return (
    <EditorContentErrorBoundary resetKey={resetKey} onError={revealRequest?.fail}>
      <Suspense fallback={<LoadingStrip ariaLabel="正在加载预览组件" mode="fill" surface="dark" visual="ring" />}>
        {children}
      </Suspense>
    </EditorContentErrorBoundary>
  );
}

type EditorContentErrorBoundaryProps = {
  onError?: (error: unknown) => void;
  children: ReactNode;
  resetKey: string;
};

type EditorContentErrorBoundaryState = {
  errorMessage: string | null;
};

class EditorContentErrorBoundary extends Component<
  EditorContentErrorBoundaryProps,
  EditorContentErrorBoundaryState
> {
  state: EditorContentErrorBoundaryState = {
    errorMessage: null,
  };

  static getDerivedStateFromError(error: unknown): EditorContentErrorBoundaryState {
    return {
      errorMessage: error instanceof Error ? error.message : "未知错误",
    };
  }

  componentDidCatch(error: unknown, errorInfo: ErrorInfo) {
    this.props.onError?.(error);
    console.error("Document preview crashed.", error, errorInfo);
  }

  componentDidUpdate(previousProps: EditorContentErrorBoundaryProps) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.errorMessage) {
      this.setState({ errorMessage: null });
    } else if (previousProps.onError !== this.props.onError && this.state.errorMessage) {
      this.props.onError?.(new Error(this.state.errorMessage));
    }
  }

  render() {
    if (this.state.errorMessage) {
      return (
        <div className="doc-editor__preview-error" role="alert">
          <strong>预览加载失败</strong>
          <span>{this.state.errorMessage}</span>
        </div>
      );
    }

    return this.props.children;
  }
}
