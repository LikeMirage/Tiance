import {
  ChatsCircle,
  GlobeHemisphereWest,
  SquaresFour,
  Wrench,
} from "@phosphor-icons/react";
import { useMemo } from "react";

import type {
  ToolOverviewView,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import { useI18n } from "../../../shared/i18n";
import {
  CollectionViewTabs,
  type CollectionViewTab,
} from "../../../shared/ui/collection-view-tabs/CollectionViewTabs";

type ToolOverviewViewTabsProps = {
  activeView: ToolOverviewView;
  disabled?: boolean;
  onChange: (view: ToolOverviewView) => void;
};

export function ToolOverviewViewTabs({
  activeView,
  disabled = false,
  onChange,
}: ToolOverviewViewTabsProps) {
  const { t } = useI18n();
  const tabs = useMemo<readonly CollectionViewTab<ToolOverviewView>[]>(() => [
    {
      icon: <Wrench size={13} weight="fill" />,
      id: "tools",
      label: t("projectOverview.views.tools"),
    },
    {
      icon: <GlobeHemisphereWest size={13} weight="fill" />,
      id: "online",
      label: t("projectOverview.views.onlineTools"),
    },
    {
      icon: <SquaresFour size={13} weight="fill" />,
      id: "projects",
      label: t("projectOverview.views.projects"),
    },
    {
      disabled,
      icon: <ChatsCircle size={13} weight="fill" />,
      id: "conversation",
      label: t("projectOverview.views.conversation"),
    },
  ], [disabled, t]);

  return (
    <CollectionViewTabs
      activeView={activeView}
      ariaLabel={t("projectOverview.views.toolTabsAria")}
      onChange={onChange}
      tabs={tabs}
    />
  );
}
