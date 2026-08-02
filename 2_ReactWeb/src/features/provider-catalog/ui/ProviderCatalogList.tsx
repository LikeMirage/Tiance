import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type RefObject,
} from "react";

import type { ProviderCatalogEntry } from "../../../entities/llm-provider/model/providerCatalog";
import type { ProjectCategory } from "../../../entities/project/model/project";
import { useI18n } from "../../../shared/i18n";
import type { useOverlayScrollbar } from "../../../shared/model/overlay-scrollbar/useOverlayScrollbar";
import type {
  ProviderInsertPosition,
  UseProviderCatalogResult,
} from "../model/useProviderCatalog";
import {
  ProviderCatalogContextMenu,
  type PendingProviderDelete,
  type ProviderContextMenuState,
} from "./ProviderCatalogContextMenu";
import { ProviderDeleteConfirmModal } from "./ProviderDeleteConfirmModal";
import { ProviderCatalogListItem } from "./ProviderCatalogListItem";

type ProviderCatalogScrollbar = ReturnType<typeof useOverlayScrollbar>;

type ProviderCatalogListProps = {
  dragHoverTarget: {
    position: ProviderInsertPosition;
    providerId: string;
  } | null;
  draggingProviderId: string | null;
  filteredProviders: ProviderCatalogEntry[];
  onListDragOver: (event: DragEvent<HTMLDivElement>) => void;
  onListDrop: (event: DragEvent<HTMLDivElement>) => void;
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
  onMoveProviderToCategory?: (providerId: string, categoryId: string) => void;
  providerCatalog: UseProviderCatalogResult;
  providerScrollbar: ProviderCatalogScrollbar;
  registerProviderItem: (providerId: string, node: HTMLDivElement | null) => void;
  targetCategories?: ProjectCategory[];
};

export function ProviderCatalogList({
  dragHoverTarget,
  draggingProviderId,
  filteredProviders,
  onListDragOver,
  onListDrop,
  onProviderDragEnd,
  onProviderDragOver,
  onProviderDragStart,
  onOpenProvider,
  onMoveProviderToCategory,
  providerCatalog,
  providerScrollbar,
  registerProviderItem,
  targetCategories,
}: ProviderCatalogListProps) {
  const { t } = useI18n();
  const [contextMenu, setContextMenu] = useState<ProviderContextMenuState | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingProviderDelete | null>(null);
  const [renamingProviderId, setRenamingProviderId] = useState<string | null>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const isCommittingRenameRef = useRef(false);
  const visibleProviderIdsKey = filteredProviders
    .map((provider) => provider.provider_id)
    .join("\n");

  useEffect(() => {
    setContextMenu(null);
  }, [visibleProviderIdsKey]);

  useEffect(() => {
    if (!renamingProviderId) return;
    const frameId = window.requestAnimationFrame(() => {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [renamingProviderId]);

  const commitProviderRename = async (
    providerId: string,
    currentName: string,
    nextName: string,
  ) => {
    if (isCommittingRenameRef.current) return;
    const displayName = nextName.trim();
    if (!displayName || displayName === currentName) {
      setRenamingProviderId(null);
      return;
    }

    isCommittingRenameRef.current = true;
    try {
      await providerCatalog.renameProvider(providerId, displayName);
      setRenamingProviderId(null);
    } catch {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    } finally {
      isCommittingRenameRef.current = false;
    }
  };

  return (
    <>
      <div className="provider-catalog-panel__body-shell">
        <div
          ref={providerScrollbar.scrollRef}
          className="provider-catalog-panel__body"
          onScroll={providerScrollbar.handleScroll}
          onDragOver={onListDragOver}
          onDrop={onListDrop}
        >
          {renderProviderCatalogBody({
            contextMenuProviderId: contextMenu?.providerId ?? null,
            dragHoverTarget,
            draggingProviderId,
            filteredProviders,
            onContextMenu: setContextMenu,
            onProviderDragEnd,
            onProviderDragOver,
            onProviderDragStart,
            onOpenProvider,
            onRenameProvider: commitProviderRename,
            providerCatalog,
            registerProviderItem,
            renameInputRef,
            renamingProviderId,
            setRenamingProviderId,
            t,
          })}
        </div>

        {providerScrollbar.isVisible ? (
          <div
            className={
              providerScrollbar.isActive
                ? "provider-catalog-panel__scrollbar provider-catalog-panel__scrollbar--active"
                : "provider-catalog-panel__scrollbar"
            }
            aria-hidden="true"
            onPointerDown={providerScrollbar.handleTrackPointerDown}
          >
            <div
              className="provider-catalog-panel__scrollbar-thumb"
              style={{
                height: `${providerScrollbar.thumbHeight}px`,
                transform: `translateY(${providerScrollbar.thumbTop}px)`,
              }}
              onPointerCancel={providerScrollbar.handleThumbPointerCancel}
              onPointerDown={providerScrollbar.handleThumbPointerDown}
              onPointerMove={providerScrollbar.handleThumbPointerMove}
              onPointerUp={providerScrollbar.handleThumbPointerUp}
            />
          </div>
        ) : null}
      </div>

      {contextMenu ? (
        <ProviderCatalogContextMenu
          contextMenu={contextMenu}
          onClose={() => setContextMenu(null)}
          onRequestDelete={setPendingDelete}
          onRevealProvider={(providerId) => {
            void providerCatalog.revealProvider(providerId).catch(() => undefined);
          }}
          onMoveProviderToCategory={onMoveProviderToCategory}
          onStartRename={(providerId) => {
            providerCatalog.selectProvider(providerId);
            setRenamingProviderId(providerId);
          }}
          providers={providerCatalog.items}
          targetCategories={targetCategories}
        />
      ) : null}

      {pendingDelete ? (
        <ProviderDeleteConfirmModal
          deletingProviderId={providerCatalog.deletingProviderId}
          pendingDelete={pendingDelete}
          onCancel={() => setPendingDelete(null)}
          onConfirm={(pending) => {
            void providerCatalog.deleteProvider(pending.providerId)
              .then(() => setPendingDelete(null))
              .catch(() => undefined);
          }}
        />
      ) : null}
    </>
  );
}

type ProviderCatalogBodyInput = Omit<
  ProviderCatalogListProps,
  "onListDragOver" | "onListDrop" | "providerScrollbar"
> & {
  contextMenuProviderId: string | null;
  onContextMenu: (state: ProviderContextMenuState) => void;
  onRenameProvider: (
    providerId: string,
    currentName: string,
    nextName: string,
  ) => Promise<void>;
  onOpenProvider?: (providerId: string) => void;
  renameInputRef: RefObject<HTMLInputElement | null>;
  renamingProviderId: string | null;
  setRenamingProviderId: (providerId: string | null) => void;
  t: ReturnType<typeof useI18n>["t"];
};

function renderProviderCatalogBody({
  contextMenuProviderId,
  dragHoverTarget,
  draggingProviderId,
  filteredProviders,
  onContextMenu,
  onProviderDragEnd,
  onProviderDragOver,
  onProviderDragStart,
  onOpenProvider,
  onRenameProvider,
  providerCatalog,
  registerProviderItem,
  renameInputRef,
  renamingProviderId,
  setRenamingProviderId,
  t,
}: ProviderCatalogBodyInput) {
  if (providerCatalog.state === "loading") {
    return <div className="provider-catalog-panel__status">{t("providerCatalog.loading")}</div>;
  }

  if (providerCatalog.state === "error") {
    return (
      <div className="provider-catalog-panel__status provider-catalog-panel__status--error">
        <span>{providerCatalog.error ?? t("providerCatalog.loadFailed")}</span>
        <button
          className="provider-catalog-panel__status-action"
          type="button"
          onClick={providerCatalog.reload}
        >
          {t("common.actions.retry")}
        </button>
      </div>
    );
  }

  if (providerCatalog.items.length === 0) {
    return <div className="provider-catalog-panel__status">{t("providerCatalog.empty")}</div>;
  }

  if (filteredProviders.length === 0) {
    return <div className="provider-catalog-panel__status">{t("providerCatalog.emptySearch")}</div>;
  }

  return (
    <nav
      className={
        draggingProviderId === null
          ? "provider-catalog-panel__list"
          : "provider-catalog-panel__list provider-catalog-panel__list--dragging"
      }
      aria-label={t("providerCatalog.list")}
    >
      {filteredProviders.map((provider) => (
        <ProviderCatalogListItem
          key={provider.provider_id}
          dragHoverTarget={dragHoverTarget}
          draggingProviderId={draggingProviderId}
          isContextMenuTarget={contextMenuProviderId === provider.provider_id}
          isRenaming={renamingProviderId === provider.provider_id}
          onContextMenu={onContextMenu}
          onProviderDragEnd={onProviderDragEnd}
          onProviderDragOver={onProviderDragOver}
          onProviderDragStart={onProviderDragStart}
          onOpenProvider={onOpenProvider}
          onRenameProvider={onRenameProvider}
          provider={provider}
          providerCatalog={providerCatalog}
          registerProviderItem={registerProviderItem}
          renameInputRef={renameInputRef}
          setRenamingProviderId={setRenamingProviderId}
        />
      ))}
    </nav>
  );
}
