import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from "react";
import type { PropsWithChildren } from "react";
import {
  acquireDesktopShellBridge,
  canStartDesktopShellNativeDrag,
  canStartDesktopShellNativeResize,
  closeDesktopShell,
  getDesktopShellBounds,
  getDesktopShellSnapshot,
  minimizeDesktopShell,
  moveDesktopShellWindow,
  persistDesktopShellWindowSizePreferences,
  restoreDesktopShellForDrag,
  selectDesktopShellProjectFolder,
  setDesktopShellBounds,
  startDesktopShellNativeDrag,
  startDesktopShellNativeResize,
  subscribeDesktopShell,
  toggleMaximizeDesktopShell,
} from "./desktopShellStore";
import type {
  DesktopShellContextValue,
  NativeWindowResizeEdge,
  WindowBounds,
} from "../../../shared/types/desktopShell";

const DesktopShellContext = createContext<DesktopShellContextValue | null>(null);

export function DesktopShellProvider({ children }: PropsWithChildren) {
  const shellSnapshot = useSyncExternalStore(
    subscribeDesktopShell,
    getDesktopShellSnapshot,
    getDesktopShellSnapshot,
  );
  const { capabilities, state } = shellSnapshot;

  useEffect(() => {
    return acquireDesktopShellBridge();
  }, []);

  const minimize = useCallback(async () => {
    await minimizeDesktopShell();
  }, []);

  const toggleMaximize = useCallback(async () => {
    await toggleMaximizeDesktopShell();
  }, []);

  const close = useCallback(async () => {
    await closeDesktopShell();
  }, []);

  const getBounds = useCallback(async () => {
    return getDesktopShellBounds();
  }, []);

  const setBounds = useCallback(
    async (bounds: WindowBounds) => {
      return setDesktopShellBounds(bounds);
    },
    [],
  );

  const persistWindowSizePreferences = useCallback(async () => {
    await persistDesktopShellWindowSizePreferences();
  }, []);

  const moveWindow = useCallback(async (x: number, y: number) => {
    return moveDesktopShellWindow(x, y);
  }, []);

  const startNativeDrag = useCallback(
    async (
      cursorScreenX: number,
      cursorScreenY: number,
      anchorRatio: number,
      dragOffsetY: number,
    ) => {
      return startDesktopShellNativeDrag(
        cursorScreenX,
        cursorScreenY,
        anchorRatio,
        dragOffsetY,
      );
    },
    [],
  );

  const startNativeResize = useCallback((
    edge: NativeWindowResizeEdge,
    cursorScreenX: number,
    cursorScreenY: number,
  ) => {
    return startDesktopShellNativeResize(edge, cursorScreenX, cursorScreenY);
  }, []);

  const restoreForDrag = useCallback(
    async (
      cursorScreenX: number,
      cursorScreenY: number,
      anchorRatio: number,
      dragOffsetY: number,
    ) => {
      return restoreDesktopShellForDrag(
        cursorScreenX,
        cursorScreenY,
        anchorRatio,
        dragOffsetY,
      );
    },
    [],
  );

  const value = useMemo(
    () => ({
      state,
      minimize,
      toggleMaximize,
      close,
      getBounds,
      canStartNativeDrag:
        state.available &&
        capabilities.nativeWindowDragSupported &&
        canStartDesktopShellNativeDrag(),
      canStartNativeResize:
        state.available &&
        capabilities.nativeWindowResizeMode === "api" &&
        capabilities.nativeWindowResizeSupported &&
        canStartDesktopShellNativeResize(),
      nativeResizeMode: state.available ? capabilities.nativeWindowResizeMode : "none",
      persistWindowSizePreferences,
      selectProjectFolder: selectDesktopShellProjectFolder,
      setBounds,
      moveWindow,
      startNativeDrag,
      startNativeResize,
      restoreForDrag,
    }),
    [
      capabilities,
      close,
      getBounds,
      minimize,
      moveWindow,
      persistWindowSizePreferences,
      restoreForDrag,
      setBounds,
      state,
      startNativeDrag,
      startNativeResize,
      toggleMaximize,
    ],
  );

  return <DesktopShellContext.Provider value={value}>{children}</DesktopShellContext.Provider>;
}

export function useDesktopShell() {
  const context = useContext(DesktopShellContext);

  if (!context) {
    throw new Error("useDesktopShell must be used within DesktopShellProvider.");
  }

  return context;
}
