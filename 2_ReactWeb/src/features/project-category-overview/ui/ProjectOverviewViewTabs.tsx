import { ChatsCircle, GlobeHemisphereWest, SquaresFour } from "@phosphor-icons/react";
import { useMemo } from "react";

import type {
  ProjectOverviewView,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import { useI18n } from "../../../shared/i18n";
import type { ProjectMarketScope } from "../../project-market/model/projectMarket";
import {
  CollectionViewTabs,
  type CollectionViewTab,
} from "../../../shared/ui/collection-view-tabs/CollectionViewTabs";

type ProjectOverviewViewTabsProps = {
  activeView: ProjectOverviewView;
  disabled?: boolean;
  marketScope: ProjectMarketScope | null;
  onChange: (view: ProjectOverviewView) => void;
};

export function ProjectOverviewViewTabs({
  activeView,
  disabled = false,
  marketScope,
  onChange,
}: ProjectOverviewViewTabsProps) {
  const { t } = useI18n();
  const tabs = useMemo<readonly CollectionViewTab<ProjectOverviewView>[]>(() => [
    {
      icon: <SquaresFour size={13} weight="fill" />,
      id: "projects",
      label: t("projectOverview.views.projects"),
    },
    ...(marketScope ? [{
      icon: <GlobeHemisphereWest size={13} weight="fill" />,
      id: "online" as const,
      label: t(marketScope === "knowledge"
        ? "projectOverview.views.onlineKnowledge"
        : marketScope === "experience"
          ? "projectOverview.views.onlineExperience"
          : "projectOverview.views.onlineProjects"),
    }] : []),
    {
      disabled,
      icon: <ChatsCircle size={13} weight="fill" />,
      id: "conversation",
      label: t("projectOverview.views.conversation"),
    },
  ], [disabled, marketScope, t]);

  return (
    <CollectionViewTabs
      activeView={activeView}
      ariaLabel={t("projectOverview.views.tabsAria")}
      onChange={onChange}
      tabs={tabs}
    />
  );
}
