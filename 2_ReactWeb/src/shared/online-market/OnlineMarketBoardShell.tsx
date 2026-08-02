import type { ReactNode } from "react";

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
};

export function OnlineMarketBoardShell({
  auxiliary,
  auxiliaryClassName,
  children,
  classes,
  content,
  error,
  source,
  toolbar,
}: OnlineMarketBoardShellProps) {
  return (
    <>
      <OnlineMarketSourceForm classes={classes} {...source} />
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
