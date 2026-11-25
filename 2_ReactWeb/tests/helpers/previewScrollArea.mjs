// Keep the production scroll viewport and its ref. These preview tests run without a browser.
export function loadPreviewScrollArea(load) {
  return load("src/shared/ui/edge-scrollbar/EdgeScrollArea.tsx", {
    "../../i18n": { useI18n: () => ({ t: key => key }) },
    "./EdgeScrollbar": { EdgeScrollbar: () => null },
  });
}
