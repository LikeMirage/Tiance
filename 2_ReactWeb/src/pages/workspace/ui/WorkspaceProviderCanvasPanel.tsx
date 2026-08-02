import { memo } from "react";

import {
  ProviderCanvasPanel,
  type ProviderCanvasPanelProps,
} from "../../../features/provider-canvas/ui/ProviderCanvasPanel";

export const WorkspaceProviderCanvasPanel = memo(function WorkspaceProviderCanvasPanel(
  props: ProviderCanvasPanelProps,
) {
  return <ProviderCanvasPanel {...props} />;
});
