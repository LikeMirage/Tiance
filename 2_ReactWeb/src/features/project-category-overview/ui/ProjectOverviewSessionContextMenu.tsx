import type { ProjectOverviewSession } from "../../../entities/project/model/project";
import {
  ContextMenu,
  ContextMenuItem,
  ContextMenuSeparator,
} from "../../../shared/ui/context-menu";
import { useI18n } from "../../../shared/i18n";
import type { ProjectOverviewSessionContextMenuState } from "../model/useProjectOverviewSessionActions";

type ProjectOverviewSessionContextMenuProps = {
  busy: boolean;
  contextMenu: ProjectOverviewSessionContextMenuState;
  onClose: () => void;
  onRequestDelete: (projectId: string, session: ProjectOverviewSession) => void;
  onRequestRename: (projectId: string, session: ProjectOverviewSession) => void;
  onTogglePinned: (projectId: string, session: ProjectOverviewSession) => void;
  session: ProjectOverviewSession;
};

export function ProjectOverviewSessionContextMenu({
  busy,
  contextMenu,
  onClose,
  onRequestDelete,
  onRequestRename,
  onTogglePinned,
  session,
}: ProjectOverviewSessionContextMenuProps) {
  const { t } = useI18n();

  return (
    <ContextMenu onClose={onClose} position={{ x: contextMenu.x, y: contextMenu.y }}>
      <ContextMenuItem
        disabled={busy}
        onSelect={() => {
          onTogglePinned(contextMenu.projectId, session);
          onClose();
        }}
      >
        {t(session.pinned ? "common.actions.unpin" : "common.actions.pin")}
      </ContextMenuItem>
      <ContextMenuItem
        disabled={busy}
        onSelect={() => {
          onRequestRename(contextMenu.projectId, session);
          onClose();
        }}
      >
        {t("common.actions.rename")}
      </ContextMenuItem>
      <ContextMenuSeparator />
      <ContextMenuItem
        danger
        disabled={busy}
        onSelect={() => {
          onRequestDelete(contextMenu.projectId, session);
          onClose();
        }}
      >
        {t("common.actions.delete")}
      </ContextMenuItem>
    </ContextMenu>
  );
}
