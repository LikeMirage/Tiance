import { Component, Suspense, useEffect, useState } from "react";
import type { ErrorInfo, ReactNode } from "react";

import type { DocumentTab } from "../../../entities/editor/model/editorDocument";
import { useMinimumLoading } from "../../../shared/model/loading/useMinimumLoading";
import { LoadingStrip } from "../../../shared/ui/loading-strip";

const EDITOR_CONTENT_MINIMUM_LOADING_MS = 260;

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

export function PreviewMountGate({
  ariaLabel,
  children,
  gateKey,
}: {
  ariaLabel: string;
  children: ReactNode;
  gateKey: string;
}) {
  const [isReadyToMount, setIsReadyToMount] = useState(false);
  const isLoadingVisible = useMinimumLoading(!isReadyToMount, EDITOR_CONTENT_MINIMUM_LOADING_MS);

  useEffect(() => {
    let firstFrame = 0;
    let secondFrame = 0;
    let isCancelled = false;

    setIsReadyToMount(false);
    firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        if (!isCancelled) {
          setIsReadyToMount(true);
        }
      });
    });

    return () => {
      isCancelled = true;
      window.cancelAnimationFrame(firstFrame);
      window.cancelAnimationFrame(secondFrame);
    };
  }, [gateKey]);

  if (isLoadingVisible) {
    return (
      <LoadingStrip
        ariaLabel={ariaLabel}
        mode="fill"
        surface="dark"
        visual="ring"
      />
    );
  }

  return <>{children}</>;
}

export function EditorLazyBoundary({ children, resetKey }: { children: ReactNode; resetKey: string }) {
  return (
    <EditorContentErrorBoundary resetKey={resetKey}>
      <Suspense fallback={<LoadingStrip ariaLabel="正在加载预览组件" mode="fill" surface="dark" visual="ring" />}>
        {children}
      </Suspense>
    </EditorContentErrorBoundary>
  );
}

type EditorContentErrorBoundaryProps = {
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
    console.error("Document preview crashed.", error, errorInfo);
  }

  componentDidUpdate(previousProps: EditorContentErrorBoundaryProps) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.errorMessage) {
      this.setState({ errorMessage: null });
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
