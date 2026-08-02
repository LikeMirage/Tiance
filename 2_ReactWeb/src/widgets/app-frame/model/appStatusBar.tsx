import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type {
  DependencyList,
  Dispatch,
  PropsWithChildren,
  ReactNode,
  SetStateAction,
} from "react";

export type AppStatusBarContent = {
  left?: ReactNode;
  center?: ReactNode;
  right?: ReactNode;
  visible?: boolean;
};

type AppStatusBarContextValue = {
  resetStatusBar: () => void;
  setStatusBar: Dispatch<SetStateAction<AppStatusBarContent>>;
  statusBar: AppStatusBarContent;
};

const emptyStatusBar: AppStatusBarContent = {};

const AppStatusBarContext = createContext<AppStatusBarContextValue | null>(null);

export function AppStatusBarProvider({ children }: PropsWithChildren) {
  const [statusBar, setStatusBar] = useState<AppStatusBarContent>(emptyStatusBar);
  const resetStatusBar = useCallback(() => {
    setStatusBar(emptyStatusBar);
  }, []);
  const value = useMemo<AppStatusBarContextValue>(() => ({
    resetStatusBar,
    setStatusBar,
    statusBar,
  }), [resetStatusBar, statusBar]);

  return (
    <AppStatusBarContext.Provider value={value}>
      {children}
    </AppStatusBarContext.Provider>
  );
}

export function useAppStatusBar() {
  const value = useContext(AppStatusBarContext);
  if (!value) {
    throw new Error("useAppStatusBar must be used inside AppStatusBarProvider");
  }
  return value;
}

export function usePageStatusBar(
  createStatusBar: () => AppStatusBarContent,
  deps: DependencyList,
) {
  const { resetStatusBar, setStatusBar } = useAppStatusBar();

  useEffect(() => {
    setStatusBar(createStatusBar());
    return resetStatusBar;
  }, [resetStatusBar, setStatusBar, ...deps]);
}
