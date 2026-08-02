import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type WheelEvent,
} from "react";

import { ExcelPreview } from "./ExcelPreview";
import type { ExcelSelectionImageReferencePayload } from "./excelSelectionImage";
import { OfficePreviewToolbar } from "./OfficePreviewToolbar";
import type { OfficeKind, PresentationSlideImageReferencePayload } from "./officePreviewTypes";
import {
  clampOfficeZoom,
  resolveOfficeKind,
} from "./officePreviewUtils";
import { PresentationPreview } from "./PresentationPreview";
import { WordPreview } from "./WordPreview";
import "./office-preview.css";

type OfficePreviewProps = {
  displayPath: string;
  fileName: string;
  onCreatePresentationSlideImageReference?: ((payload: PresentationSlideImageReferencePayload) => Promise<void>) | null;
  onCreateSpreadsheetRangeImageReference?: ((payload: ExcelSelectionImageReferencePayload) => Promise<void>) | null;
  onMissing?: (() => void) | null;
  onOpenNativeFile?: (() => Promise<void>) | null;
  onRevealFile?: (() => Promise<void>) | null;
  src: string | null;
};

export function OfficePreview({
  displayPath,
  fileName,
  onCreatePresentationSlideImageReference = null,
  onCreateSpreadsheetRangeImageReference = null,
  onMissing = null,
  onOpenNativeFile = null,
  onRevealFile = null,
  src,
}: OfficePreviewProps) {
  const officeKind = useMemo(() => resolveOfficeKind(fileName), [fileName]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [isContentLoadingVisible, setIsContentLoadingVisible] = useState(() =>
    isLoadableOfficeKind(officeKind) && Boolean(src),
  );
  const [zoom, setZoom] = useState(1);
  const zoomIn = useCallback(() => setZoom((value) => clampOfficeZoom(value + 0.1)), []);
  const zoomOut = useCallback(() => setZoom((value) => clampOfficeZoom(value - 0.1)), []);
  const zoomByWheel = useCallback((deltaY: number) => {
    setZoom((value) => clampOfficeZoom(value + (deltaY < 0 ? 0.1 : -0.1)));
  }, []);

  const runFileAction = useCallback(async (action: (() => Promise<void>) | null) => {
    if (!action) return;
    setActionError(null);
    try {
      await action();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "文件操作失败。");
    }
  }, []);

  const handleWheel = useCallback((event: WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey || (officeKind !== "word" && officeKind !== "spreadsheet")) return;

    event.preventDefault();
    zoomByWheel(event.deltaY);
  }, [officeKind, zoomByWheel]);

  useEffect(() => {
    setIsContentLoadingVisible(isLoadableOfficeKind(officeKind) && Boolean(src));
  }, [officeKind, src]);

  return (
    <div
      className={isContentLoadingVisible ? "office-preview office-preview--content-loading" : "office-preview"}
      onWheel={handleWheel}
    >
      <OfficePreviewToolbar
        displayPath={displayPath}
        fileName={fileName}
        officeKind={officeKind}
        zoom={zoom}
        onFitWidth={() => setZoom(1)}
        onOpenNativeFile={onOpenNativeFile ? () => runFileAction(onOpenNativeFile) : null}
        onRevealFile={onRevealFile ? () => runFileAction(onRevealFile) : null}
        onZoomChange={(value) => setZoom(clampOfficeZoom(value))}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
      />

      {actionError ? (
        <div className="office-preview__status office-preview__status--error">{actionError}</div>
      ) : null}

      {officeKind === "word" ? (
        <WordPreview
          onLoadingVisibleChange={setIsContentLoadingVisible}
          onMissing={onMissing}
          src={src}
          zoom={zoom}
        />
      ) : officeKind === "spreadsheet" ? (
        <ExcelPreview
          displayPath={displayPath}
          fileName={fileName}
          onLoadingVisibleChange={setIsContentLoadingVisible}
          onMissing={onMissing}
          onCreateSelectionImageReference={onCreateSpreadsheetRangeImageReference}
          src={src}
          zoom={zoom}
          onWheelZoom={zoomByWheel}
        />
      ) : officeKind === "presentation" ? (
        <PresentationPreview
          displayPath={displayPath}
          fileName={fileName}
          onLoadingVisibleChange={setIsContentLoadingVisible}
          onMissing={onMissing}
          onCreateSlideImageReference={onCreatePresentationSlideImageReference}
          src={src}
          zoom={zoom}
          onZoomChange={setZoom}
        />
      ) : (
        <div className="office-preview__empty">暂不支持此 Office 文件格式。</div>
      )}
    </div>
  );
}

function isLoadableOfficeKind(officeKind: OfficeKind) {
  return officeKind === "word" || officeKind === "spreadsheet" || officeKind === "presentation";
}
