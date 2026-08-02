import {
  Books,
  Cpu,
  Folders,
  GearSix,
  LightbulbFilament,
  PaintBrushBroad,
  UsersThree,
  Wrench,
} from "@phosphor-icons/react";

import type { HoverSidebarIconKey } from "../model/sidebarItems";

type HoverSidebarIconProps = {
  iconKey: HoverSidebarIconKey;
};

export function HoverSidebarIcon({ iconKey }: HoverSidebarIconProps) {
  switch (iconKey) {
    case "overview":
      return <OverviewIcon />;
    case "knowledge":
      return <KnowledgeIcon />;
    case "experience":
      return <ExperienceIcon />;
    case "roles":
      return <RolesIcon />;
    case "models":
      return <ModelsIcon />;
    case "themes":
      return <ThemesIcon />;
    case "tools":
      return <ToolsIcon />;
    case "settings":
      return <SettingsIcon />;
  }
}

function OverviewIcon() {
  return <Folders className="hover-sidebar__glyph" weight="bold" aria-hidden="true" />;
}

function KnowledgeIcon() {
  return <Books className="hover-sidebar__glyph" weight="bold" aria-hidden="true" />;
}

function ExperienceIcon() {
  return <LightbulbFilament className="hover-sidebar__glyph" weight="bold" aria-hidden="true" />;
}

function RolesIcon() {
  return <UsersThree className="hover-sidebar__glyph" weight="bold" aria-hidden="true" />;
}

function ModelsIcon() {
  return <Cpu className="hover-sidebar__glyph" weight="bold" aria-hidden="true" />;
}

function ThemesIcon() {
  return <PaintBrushBroad className="hover-sidebar__glyph" weight="bold" aria-hidden="true" />;
}

function ToolsIcon() {
  return <Wrench className="hover-sidebar__glyph" weight="bold" aria-hidden="true" />;
}

function SettingsIcon() {
  return <GearSix className="hover-sidebar__glyph" weight="bold" aria-hidden="true" />;
}
