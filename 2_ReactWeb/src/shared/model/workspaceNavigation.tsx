import { createContext, useContext, type ReactNode } from "react";

type WorkspaceNavigation = {
  openGithubSettings: () => void;
};

const WorkspaceNavigationContext = createContext<WorkspaceNavigation | null>(null);

export function WorkspaceNavigationProvider({
  children,
  value,
}: {
  children: ReactNode;
  value: WorkspaceNavigation;
}) {
  return (
    <WorkspaceNavigationContext.Provider value={value}>
      {children}
    </WorkspaceNavigationContext.Provider>
  );
}

export function useWorkspaceNavigation() {
  const navigation = useContext(WorkspaceNavigationContext);
  if (!navigation) {
    throw new Error("Workspace navigation is unavailable.");
  }
  return navigation;
}
