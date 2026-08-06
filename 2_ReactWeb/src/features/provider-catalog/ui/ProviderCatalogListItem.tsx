import { ArrowSquareIn, Check } from "@phosphor-icons/react";
import type { DragEvent, RefObject } from "react";

import type { ProviderCatalogEntry } from "../../../entities/llm-provider/model/providerCatalog";
import { useI18n } from "../../../shared/i18n";
import type {
  ProviderInsertPosition,
  UseProviderCatalogResult,
} from "../model/useProviderCatalog";
import type { ProviderContextMenuState } from "./ProviderCatalogContextMenu";

type ProviderCatalogListItemProps = {
  dragHoverTarget: {
    position: ProviderInsertPosition;
    providerId: string;
  } | null;
  draggingProviderId: string | null;
  isContextMenuTarget: boolean;
  isRenaming: boolean;
  onContextMenu: (state: ProviderContextMenuState) => void;
  onProviderDragEnd: () => void;
  onProviderDragOver: (
    event: DragEvent<HTMLDivElement>,
    targetProviderId: string,
  ) => void;
  onProviderDragStart: (
    event: DragEvent<HTMLDivElement>,
    providerId: string,
  ) => void;
  onOpenProvider?: (providerId: string) => void;
  onRenameProvider: (
    providerId: string,
    currentName: string,
    nextName: string,
  ) => Promise<void>;
  provider: ProviderCatalogEntry;
  providerCatalog: UseProviderCatalogResult;
  registerProviderItem: (providerId: string, node: HTMLDivElement | null) => void;
  renameInputRef: RefObject<HTMLInputElement | null>;
  setRenamingProviderId: (providerId: string | null) => void;
};

export function ProviderCatalogListItem({
  dragHoverTarget,
  draggingProviderId,
  isContextMenuTarget,
  isRenaming,
  onContextMenu,
  onProviderDragEnd,
  onProviderDragOver,
  onProviderDragStart,
  onOpenProvider,
  onRenameProvider,
  provider,
  providerCatalog,
  registerProviderItem,
  renameInputRef,
  setRenamingProviderId,
}: ProviderCatalogListItemProps) {
  const { t } = useI18n();
  const providerId = provider.provider_id;
  const isDragging = draggingProviderId === providerId;
  const isDropBefore =
    dragHoverTarget?.providerId === providerId &&
    draggingProviderId !== providerId &&
    dragHoverTarget.position === "before";
  const isDropAfter =
    dragHoverTarget?.providerId === providerId &&
    draggingProviderId !== providerId &&
    dragHoverTarget.position === "after";

  return (
    <div
      ref={(node) => registerProviderItem(providerId, node)}
      className={
        [
          "provider-catalog-panel__item",
          providerCatalog.selectedProviderId === providerId
            ? "provider-catalog-panel__item--active"
            : "",
          isDropBefore ? "provider-catalog-panel__item--drop-before" : "",
          isDropAfter ? "provider-catalog-panel__item--drop-after" : "",
          isDragging ? "provider-catalog-panel__item--dragging" : "",
          isContextMenuTarget ? "provider-catalog-panel__item--context-target" : "",
          !isRenaming && onOpenProvider
            ? "provider-catalog-panel__item--openable"
            : "",
        ]
          .filter(Boolean)
          .join(" ")
      }
      draggable={!isRenaming}
      onDragStart={(event) => onProviderDragStart(event, providerId)}
      onDragOver={(event) => onProviderDragOver(event, providerId)}
      onDragEnd={onProviderDragEnd}
      onContextMenu={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onContextMenu({ providerId, x: event.clientX, y: event.clientY });
      }}
    >
      {isRenaming ? (
        <div className="provider-catalog-panel__item-main">
          <span className="provider-catalog-panel__rename-field">
            <input
              ref={renameInputRef}
              className="provider-catalog-panel__rename-input"
              defaultValue={provider.display_name}
              onBlur={(event) => {
                void onRenameProvider(providerId, provider.display_name, event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void onRenameProvider(
                    providerId,
                    provider.display_name,
                    event.currentTarget.value,
                  );
                } else if (event.key === "Escape") {
                  setRenamingProviderId(null);
                }
              }}
            />
            <button
              className="provider-catalog-panel__rename-save"
              type="button"
              aria-label={t("providerCatalog.renameSave")}
              onMouseDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
              }}
              onClick={(event) => {
                event.stopPropagation();
                void onRenameProvider(
                  providerId,
                  provider.display_name,
                  renameInputRef.current?.value ?? provider.display_name,
                );
              }}
            >
              <Check className="provider-catalog-panel__rename-save-glyph" weight="bold" />
            </button>
          </span>
        </div>
      ) : (
        <>
          <button
            className="provider-catalog-panel__item-main"
            type="button"
            onClick={() => providerCatalog.selectProvider(providerId)}
            onDoubleClick={() => onOpenProvider?.(providerId)}
          >
            <span className="provider-catalog-panel__item-name">{provider.display_name}</span>
          </button>
          {onOpenProvider ? (
            <button
              className="provider-catalog-panel__item-enter"
              type="button"
              aria-label={t("projectList.enterProject", { project: provider.display_name })}
              title={t("projectList.enterProject", { project: provider.display_name })}
              onClick={(event) => {
                event.stopPropagation();
                onOpenProvider(providerId);
              }}
              onDoubleClick={(event) => event.stopPropagation()}
            >
              <ArrowSquareIn size={15} weight="regular" aria-hidden="true" />
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}
