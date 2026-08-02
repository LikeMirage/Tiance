import { useEffect, useRef } from "react";

type UseDismissableLayerOptions = {
  enabled?: boolean;
  onDismiss: () => void;
};

export function useDismissableLayer<T extends HTMLElement>({
  enabled = true,
  onDismiss,
}: UseDismissableLayerOptions) {
  const layerRef = useRef<T | null>(null);
  const onDismissRef = useRef(onDismiss);

  useEffect(() => {
    onDismissRef.current = onDismiss;
  }, [onDismiss]);

  useEffect(() => {
    if (!enabled) return undefined;

    const isInsideLayer = (target: EventTarget | null) =>
      target instanceof Node && Boolean(layerRef.current?.contains(target));

    const dismissIfOutside = (event: PointerEvent | MouseEvent) => {
      if (isInsideLayer(event.target)) return;
      onDismissRef.current();
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onDismissRef.current();
      }
    };
    const handleWindowBlur = () => {
      onDismissRef.current();
    };

    window.addEventListener("pointerdown", dismissIfOutside, true);
    window.addEventListener("mousedown", dismissIfOutside, true);
    window.addEventListener("contextmenu", dismissIfOutside, true);
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("blur", handleWindowBlur);
    document.addEventListener("pointerdown", dismissIfOutside, true);
    document.addEventListener("mousedown", dismissIfOutside, true);
    document.addEventListener("contextmenu", dismissIfOutside, true);
    document.addEventListener("keydown", handleKeyDown, true);

    return () => {
      window.removeEventListener("pointerdown", dismissIfOutside, true);
      window.removeEventListener("mousedown", dismissIfOutside, true);
      window.removeEventListener("contextmenu", dismissIfOutside, true);
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("blur", handleWindowBlur);
      document.removeEventListener("pointerdown", dismissIfOutside, true);
      document.removeEventListener("mousedown", dismissIfOutside, true);
      document.removeEventListener("contextmenu", dismissIfOutside, true);
      document.removeEventListener("keydown", handleKeyDown, true);
    };
  }, [enabled]);

  return layerRef;
}
