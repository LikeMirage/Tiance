import {
  FrameCorners,
  FolderOpen,
  MicrosoftExcelLogo,
  MicrosoftPowerpointLogo,
  MicrosoftWordLogo,
} from "@phosphor-icons/react";

import { PreviewZoomControl } from "../../../shared/ui/preview-zoom-control";
import {
  OFFICE_PREVIEW_MAX_ZOOM,
  OFFICE_PREVIEW_MIN_ZOOM,
} from "./officePreviewUtils";
import type { OfficeKind } from "./officePreviewTypes";

type OfficePreviewToolbarProps = {
  displayPath: string;
  fileName: string;
  officeKind: OfficeKind;
  zoom: number;
  onFitWidth: () => void;
  onOpenNativeFile: (() => void) | null;
  onRevealFile: (() => void) | null;
  onZoomChange: (value: number) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
};

export function OfficePreviewToolbar({
  displayPath,
  fileName,
  officeKind,
  zoom,
  onFitWidth,
  onOpenNativeFile,
  onRevealFile,
  onZoomChange,
  onZoomIn,
  onZoomOut,
}: OfficePreviewToolbarProps) {
  const NativeOpenIcon = nativeOpenIcon(officeKind);
  const showZoomControls = officeKind === "word" || officeKind === "spreadsheet" || officeKind === "presentation";

  return (
    <div className="office-preview__toolbar">
      <div className="office-preview__meta">
        <span className="office-preview__type">{officeKindLabel(officeKind)}</span>
        <span className="office-preview__name">{fileName}</span>
        <span className="office-preview__path" title={displayPath}>{displayPath}</span>
      </div>
      <div className="office-preview__actions" aria-label="Office 预览工具栏">
        {showZoomControls ? (
          <>
            <PreviewZoomControl
              ariaLabel={`${officeKindLabel(officeKind)} 预览缩放`}
              max={OFFICE_PREVIEW_MAX_ZOOM}
              min={OFFICE_PREVIEW_MIN_ZOOM}
              step={0.01}
              value={zoom}
              onDecrease={onZoomOut}
              onIncrease={onZoomIn}
              onValueChange={onZoomChange}
            />
            <button className="office-preview__button" title="重置缩放" type="button" onClick={onFitWidth}>
              <FrameCorners size={15} weight="bold" />
            </button>
          </>
        ) : null}
        <button
          className="office-preview__button"
          disabled={!onRevealFile}
          title="在资源管理器中打开"
          type="button"
          onClick={() => onRevealFile?.()}
        >
          <FolderOpen size={15} weight="bold" />
        </button>
        <button
          className="office-preview__button"
          disabled={!onOpenNativeFile}
          title={nativeOpenTitle(officeKind)}
          type="button"
          onClick={() => onOpenNativeFile?.()}
        >
          <NativeOpenIcon size={15} weight="bold" />
        </button>
      </div>
    </div>
  );
}

function officeKindLabel(kind: OfficeKind) {
  if (kind === "word") return "Word";
  if (kind === "spreadsheet") return "Excel";
  if (kind === "presentation") return "PPT";
  return "Office";
}

function nativeOpenIcon(kind: OfficeKind) {
  if (kind === "spreadsheet") return MicrosoftExcelLogo;
  if (kind === "presentation") return MicrosoftPowerpointLogo;
  return MicrosoftWordLogo;
}

function nativeOpenTitle(kind: OfficeKind) {
  if (kind === "spreadsheet") return "用 Excel / WPS 打开";
  if (kind === "presentation") return "用 PowerPoint / WPS 打开";
  return "用 Word / WPS 打开";
}
