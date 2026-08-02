import type { ReactNode } from "react";

import type { GithubSyncCollection } from "../../services/github/githubSyncApi";
import { GithubSyncControl } from "../../features/github-sync/ui/GithubSyncControl";

import {
  OnlineMarketContent,
  OnlineMarketError,
  OnlineMarketSourceForm,
  OnlineMarketToolbar,
  type OnlineMarketBoardClasses,
  type OnlineMarketContentProps,
  type OnlineMarketErrorProps,
  type OnlineMarketSourceFormProps,
  type OnlineMarketToolbarProps,
} from "./OnlineMarketBoardControls";

type OnlineMarketBoardShellProps = {
  auxiliaryClassName: string;
  auxiliary?: ReactNode;
  children: ReactNode;
  classes: OnlineMarketBoardClasses;
  content: Omit<OnlineMarketContentProps, "children" | "classes">;
  error: Omit<OnlineMarketErrorProps, "classes">;
  source: Omit<OnlineMarketSourceFormProps, "classes">;
  toolbar: Omit<OnlineMarketToolbarProps, "classes">;
  syncCollection: GithubSyncCollection;
};

export function OnlineMarketBoardShell({
  auxiliary,
  auxiliaryClassName,
  children,
  classes,
  content,
  error,
  source,
  syncCollection,
  toolbar,
}: OnlineMarketBoardShellProps) {
  return (
    <>
      <OnlineMarketSourceForm
        actions={<GithubSyncControl collection={syncCollection} disabled={source.isLoading} />}
        classes={classes}
        {...source}
      />
      <OnlineMarketToolbar classes={classes} {...toolbar} />
      <div className={auxiliaryClassName}>
        {auxiliary}
        <OnlineMarketError classes={classes} {...error} />
      </div>
      <OnlineMarketContent classes={classes} {...content}>
        {children}
      </OnlineMarketContent>
    </>
  );
}
