import type { ProviderCatalogEntry } from "../../../entities/llm-provider/model/providerCatalog";
import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import {
  ContextMenu,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSubmenu,
} from "../../../shared/ui/context-menu";

export type ProviderContextMenuState = {
  providerId: string;
  x: number;
  y: number;
};

export type PendingProviderDelete = {
  providerId: string;
  providerName: string;
};

type ProviderCatalogContextMenuProps = {
  contextMenu: ProviderContextMenuState;
  onClose: () => void;
  onRequestDelete: (pendingDelete: PendingProviderDelete) => void;
  onRevealProvider: (providerId: string) => void;
  onMoveProviderToCategory?: (providerId: string, categoryId: string) => void;
  onStartRename: (providerId: string) => void;
  providers: ProviderCatalogEntry[];
  targetCategories?: ProjectCategory[];
};

export function ProviderCatalogContextMenu({
  contextMenu,
  onClose,
  onRequestDelete,
  onRevealProvider,
  onMoveProviderToCategory,
  onStartRename,
  providers,
  targetCategories = [],
}: ProviderCatalogContextMenuProps) {
  const { t } = useI18n();
  const provider = providers.find(
    (item) => item.provider_id === contextMenu.providerId,
  );
  if (!provider) return null;

  return (
    <ContextMenu onClose={onClose} position={{ x: contextMenu.x, y: contextMenu.y }}>
      <ContextMenuItem
        onSelect={() => {
          onStartRename(provider.provider_id);
          onClose();
        }}
      >
        {t("common.actions.rename")}
      </ContextMenuItem>
      <ContextMenuItem
        onSelect={() => {
          onRevealProvider(provider.provider_id);
          onClose();
        }}
      >
        {t("providerCatalog.context.reveal")}
      </ContextMenuItem>
      {onMoveProviderToCategory && targetCategories.length > 0 ? (
        <ContextMenuSubmenu label={t("projectList.context.moveTo")}>
          {targetCategories.map((category) => (
            <ContextMenuItem
              key={category.category_id}
              onSelect={() => {
                onMoveProviderToCategory(provider.provider_id, category.category_id);
                onClose();
              }}
            >
              {category.name}
            </ContextMenuItem>
          ))}
        </ContextMenuSubmenu>
      ) : null}
      <ContextMenuSeparator />
      <ContextMenuItem
        danger
        onSelect={() => {
          onRequestDelete({
            providerId: provider.provider_id,
            providerName: provider.display_name,
          });
          onClose();
        }}
      >
        {t("common.actions.delete")}
      </ContextMenuItem>
    </ContextMenu>
  );
}
