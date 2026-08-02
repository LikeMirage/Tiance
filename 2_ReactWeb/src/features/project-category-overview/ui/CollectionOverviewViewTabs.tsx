import {
  ChatsCircle,
  Cpu,
  GlobeHemisphereWest,
  PaintBrushBroad,
  SquaresFour,
  UserFocus,
} from "@phosphor-icons/react";
import { useMemo } from "react";

import type {
  CollectionOverviewView,
} from "../../../entities/workspace/model/workspaceLayoutPreferences";
import { useI18n } from "../../../shared/i18n";
import {
  CollectionViewTabs,
  type CollectionViewTab,
} from "../../../shared/ui/collection-view-tabs/CollectionViewTabs";

type CollectionOverviewViewTabsProps = {
  activeView: CollectionOverviewView;
  disabled?: boolean;
  kind: "provider" | "role" | "theme";
  onChange: (view: CollectionOverviewView) => void;
};

export function CollectionOverviewViewTabs({
  activeView,
  disabled = false,
  kind,
  onChange,
}: CollectionOverviewViewTabsProps) {
  const { t } = useI18n();
  const tabs = useMemo<readonly CollectionViewTab<CollectionOverviewView>[]>(() => {
    const result: CollectionViewTab<CollectionOverviewView>[] = [{
      icon: kind === "role"
        ? <UserFocus size={13} weight="fill" />
        : kind === "theme"
          ? <PaintBrushBroad size={13} weight="fill" />
          : <Cpu size={13} weight="fill" />,
      id: "specialized",
      label: t(
        kind === "role"
          ? "projectOverview.views.roles"
          : kind === "theme"
            ? "projectOverview.views.themes"
            : "projectOverview.views.providers",
      ),
    }];
    if (kind === "theme" || kind === "role" || kind === "provider") {
      result.push({
        icon: <GlobeHemisphereWest size={13} weight="fill" />,
        id: "online",
        label: t(
          kind === "role"
            ? "projectOverview.views.onlineRoles"
            : kind === "provider"
              ? "projectOverview.views.onlineProviders"
              : "projectOverview.views.onlineThemes",
        ),
      });
    }
    result.push({
      icon: <SquaresFour size={13} weight="fill" />,
      id: "projects",
      label: t("projectOverview.views.projects"),
    },
    {
      disabled,
      icon: <ChatsCircle size={13} weight="fill" />,
      id: "conversation",
      label: t("projectOverview.views.conversation"),
    });
    return result;
  }, [disabled, kind, t]);

  return (
    <CollectionViewTabs
      activeView={activeView}
      ariaLabel={t(
        kind === "role"
          ? "projectOverview.views.roleTabsAria"
          : kind === "theme"
            ? "projectOverview.views.themeTabsAria"
            : "projectOverview.views.providerTabsAria",
      )}
      onChange={onChange}
      tabs={tabs}
    />
  );
}
