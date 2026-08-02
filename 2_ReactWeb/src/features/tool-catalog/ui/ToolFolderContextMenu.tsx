import type { ToolFolder, Toolset } from "../../../entities/tool/model/toolset";
import {
  ContextMenu,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSubmenu,
} from "../../../shared/ui/context-menu";
import type { ToolFolderContextMenuState, PendingToolFolderDelete } from "./toolFolderContextMenuTypes";

type ToolFolderContextMenuProps = {
  contextMenu: NonNullable<ToolFolderContextMenuState>;
  folders: ToolFolder[];
  isReadonly: boolean;
  onClose: () => void;
  onMoveToToolset: (folderId: string, targetToolsetId: string) => void;
  onOpenInExplorer: (folderId: string) => void;
  onRequestDelete: (pendingDelete: NonNullable<PendingToolFolderDelete>) => void;
  onStartRename: (folderId: string) => void;
  toolsets: Toolset[];
};

export function ToolFolderContextMenu({
  contextMenu,
  folders,
  isReadonly,
  onClose,
  onMoveToToolset,
  onOpenInExplorer,
  onRequestDelete,
  onStartRename,
  toolsets,
}: ToolFolderContextMenuProps) {
  const folder = folders.find((item) => item.project_id === contextMenu.folderId);
  if (!folder) return null;

  const targetToolsets = toolsets.filter(
    (toolset) =>
      toolset.category_id !== folder.category_id &&
      canModifyToolFolders(toolset),
  );

  return (
    <ContextMenu onClose={onClose} position={{ x: contextMenu.x, y: contextMenu.y }}>
      {!isReadonly ? (
        <ContextMenuItem
          onSelect={() => {
            onStartRename(contextMenu.folderId);
            onClose();
          }}
        >
          重命名
        </ContextMenuItem>
      ) : null}
      <ContextMenuItem
        onSelect={() => {
          onOpenInExplorer(contextMenu.folderId);
          onClose();
        }}
      >
        在资源管理器中打开
      </ContextMenuItem>
      {!isReadonly && targetToolsets.length > 0 ? (
        <>
          <ContextMenuSeparator />
          <ContextMenuSubmenu label="移动至...">
            {targetToolsets.map((toolset) => (
              <ContextMenuItem
                key={toolset.category_id}
                onSelect={() => {
                  onMoveToToolset(contextMenu.folderId, toolset.category_id);
                  onClose();
                }}
              >
                {toolset.name}
              </ContextMenuItem>
            ))}
          </ContextMenuSubmenu>
        </>
      ) : null}
      {!isReadonly ? (
        <>
          <ContextMenuSeparator />
          <ContextMenuItem
            danger
            onSelect={() => {
              onRequestDelete({
                folderId: folder.project_id,
                folderName: folder.name,
              });
              onClose();
            }}
          >
            删除
          </ContextMenuItem>
        </>
      ) : null}
    </ContextMenu>
  );
}

function canModifyToolFolders(toolset: Toolset) {
  return !toolset.readonly;
}
