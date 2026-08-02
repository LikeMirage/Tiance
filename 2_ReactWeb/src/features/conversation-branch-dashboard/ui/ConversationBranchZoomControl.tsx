import { CornersOut } from "@phosphor-icons/react";
import { Panel, useReactFlow, useViewport } from "@xyflow/react";

import { RangeSlider } from "../../../shared/ui/range-slider";

type ConversationBranchZoomControlProps = {
  maxZoom: number;
  minZoom: number;
};

export function ConversationBranchZoomControl({
  maxZoom,
  minZoom,
}: ConversationBranchZoomControlProps) {
  const { fitView, zoomTo } = useReactFlow();
  const { zoom } = useViewport();

  return (
    <Panel className="conversation-branch-zoom" position="bottom-left">
      <span className="conversation-branch-zoom__hint">
        按住 Ctrl+滚动 便捷调节大小
      </span>
      <button
        className="conversation-branch-zoom__fit"
        type="button"
        aria-label="显示全部分支"
        title="显示全部分支"
        onClick={() => void fitView({
          duration: 240,
          maxZoom: Math.min(maxZoom, 1),
          minZoom,
          padding: 0.18,
        })}
      >
        <CornersOut size={16} weight="regular" aria-hidden="true" />
      </button>
      <RangeSlider
        ariaLabel="调整会话分支图缩放"
        className="conversation-branch-zoom__slider"
        max={maxZoom}
        min={minZoom}
        step={0.01}
        value={zoom}
        onValueChange={(value) => void zoomTo(value)}
      />
    </Panel>
  );
}
