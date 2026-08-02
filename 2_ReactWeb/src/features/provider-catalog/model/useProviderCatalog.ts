import { useEffect, useRef, useState } from "react";

import type {
  ProviderAuthScheme,
  ProviderCatalogEntry,
  ProviderProtocolFamily,
} from "../../../entities/llm-provider/model/providerCatalog";
import { emitLlmModelCatalogChanged } from "../../../entities/llm-provider/model/modelCatalogEvents";
import {
  dispatchProjectCatalogChanged,
  listenProjectCatalogChanged,
} from "../../../entities/project/model/projectCatalogEvents";
import { createProviderCatalogEntry } from "../../../services/llm/createProviderCatalogEntry";
import { deleteProviderCatalogEntry } from "../../../services/llm/deleteProviderCatalogEntry";
import { getProviderCatalog } from "../../../services/llm/getProviderCatalog";
import { getProviderCatalogOrder } from "../../../services/llm/getProviderCatalogOrder";
import { saveProviderCatalogOrder } from "../../../services/llm/saveProviderCatalogOrder";
import { revealProviderCatalogEntry } from "../../../services/llm/revealProviderCatalogEntry";
import { updateProviderCatalogEntry } from "../../../services/llm/updateProviderCatalogEntry";

type LoadState = "loading" | "ready" | "error";
export type ProviderInsertPosition = "before" | "after";

export type ProviderCreateInput = {
  apiBaseUrl: string;
  authScheme: ProviderAuthScheme;
  displayName: string;
  categoryId?: string | null;
  protocolFamily: ProviderProtocolFamily;
};

function applyStoredProviderOrder(
  items: ProviderCatalogEntry[],
  orderedProviderIds: string[],
): ProviderCatalogEntry[] {
  if (orderedProviderIds.length === 0) {
    return items;
  }

  const itemMap = new Map(
    items.map((item) => [item.provider_id, item] satisfies [string, ProviderCatalogEntry]),
  );
  const orderedItems: ProviderCatalogEntry[] = [];

  orderedProviderIds.forEach((providerId) => {
    const item = itemMap.get(providerId);
    if (!item) {
      return;
    }

    orderedItems.push(item);
    itemMap.delete(providerId);
  });

  items.forEach((item) => {
    if (!itemMap.has(item.provider_id)) {
      return;
    }

    orderedItems.push(item);
    itemMap.delete(item.provider_id);
  });

  return orderedItems;
}

const CHINESE_COLLATOR = new Intl.Collator("zh-Hans-CN-u-co-pinyin", {
  numeric: true,
  sensitivity: "base",
});

const ENGLISH_COLLATOR = new Intl.Collator("en", {
  numeric: true,
  sensitivity: "base",
});

function applyDefaultProviderOrder(items: ProviderCatalogEntry[]) {
  return [...items].sort(compareProvidersByDefaultRule);
}

function compareProvidersByDefaultRule(
  left: ProviderCatalogEntry,
  right: ProviderCatalogEntry,
) {
  const leftCategory = getProviderSortCategory(left);
  const rightCategory = getProviderSortCategory(right);

  if (leftCategory !== rightCategory) {
    return leftCategory - rightCategory;
  }

  const leftText = getProviderSortText(left);
  const rightText = getProviderSortText(right);
  const collator = leftCategory === 0 ? CHINESE_COLLATOR : ENGLISH_COLLATOR;
  const textCompareResult = collator.compare(leftText, rightText);

  if (textCompareResult !== 0) {
    return textCompareResult;
  }

  return ENGLISH_COLLATOR.compare(left.provider_id, right.provider_id);
}

function getProviderSortCategory(provider: ProviderCatalogEntry) {
  const firstCharacter = getProviderSortText(provider).charAt(0);

  if (/[\u3400-\u9fff]/u.test(firstCharacter)) {
    return 0;
  }

  if (/[a-z]/iu.test(firstCharacter)) {
    return 1;
  }

  return 2;
}

function getProviderSortText(provider: ProviderCatalogEntry) {
  return (provider.display_name || provider.provider_id).trim();
}

function resolveInitialProviderItems(
  items: ProviderCatalogEntry[],
  orderedProviderIds: string[],
) {
  const defaultOrderedItems = applyDefaultProviderOrder(items);
  return applyStoredProviderOrder(defaultOrderedItems, orderedProviderIds);
}

function reorderProviderItems(
  items: ProviderCatalogEntry[],
  activeProviderId: string,
  targetProviderId: string,
  position: ProviderInsertPosition,
): ProviderCatalogEntry[] {
  if (activeProviderId === targetProviderId) {
    return items;
  }

  const draggedItem = items.find((item) => item.provider_id === activeProviderId);
  if (!draggedItem) {
    return items;
  }

  const remainingItems = items.filter(
    (item) => item.provider_id !== activeProviderId,
  );
  const targetIndex = remainingItems.findIndex(
    (item) => item.provider_id === targetProviderId,
  );

  if (targetIndex === -1) {
    return items;
  }

  const insertIndex = position === "after" ? targetIndex + 1 : targetIndex;
  const nextItems = [...remainingItems];
  nextItems.splice(insertIndex, 0, draggedItem);
  return nextItems;
}

function toProviderIds(items: ProviderCatalogEntry[]) {
  return items.map((item) => item.provider_id);
}

export interface UseProviderCatalogResult {
  state: LoadState;
  items: ProviderCatalogEntry[];
  error: string | null;
  createProvider: (input: ProviderCreateInput) => Promise<void>;
  deleteProvider: (providerId: string) => Promise<void>;
  deletingProviderId: string | null;
  isCreatingProvider: boolean;
  renameProvider: (providerId: string, displayName: string) => Promise<void>;
  revealProvider: (providerId: string) => Promise<void>;
  renamingProviderId: string | null;
  updatingProviderProtocolId: string | null;
  selectedProvider: ProviderCatalogEntry | null;
  selectedProviderId: string | null;
  selectProvider: (providerId: string) => void;
  updateProviderProtocol: (
    providerId: string,
    protocolFamily: ProviderProtocolFamily,
  ) => Promise<void>;
  getReorderedProviderIds: (
    activeProviderId: string,
    targetProviderId: string,
    position: ProviderInsertPosition,
  ) => string[];
  previewProviderOrder: (providerIds: string[]) => void;
  persistProviderOrder: (providerIds: string[]) => Promise<void>;
  reload: () => void;
}

export function useProviderCatalog(): UseProviderCatalogResult {
  const itemsRef = useRef<ProviderCatalogEntry[]>([]);
  const [items, setItems] = useState<ProviderCatalogEntry[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [isCreatingProvider, setIsCreatingProvider] = useState(false);
  const [deletingProviderId, setDeletingProviderId] = useState<string | null>(null);
  const [renamingProviderId, setRenamingProviderId] = useState<string | null>(null);
  const [updatingProviderProtocolId, setUpdatingProviderProtocolId] =
    useState<string | null>(null);
  const [requestKey, setRequestKey] = useState(0);
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

  useEffect(() => listenProjectCatalogChanged(() => {
    setRequestKey((current) => current + 1);
  }), []);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setState("loading");
      setError(null);

      try {
        const [catalogResponse, orderResponse] = await Promise.all([
          getProviderCatalog(),
          getProviderCatalogOrder(),
        ]);

        if (cancelled) {
          return;
        }

        const orderedItems = resolveInitialProviderItems(
          catalogResponse.items,
          orderResponse.provider_ids,
        );

        setItems(orderedItems);
        setSelectedProviderId((current) => {
          if (current && orderedItems.some((item) => item.provider_id === current)) {
            return current;
          }

          return orderedItems[0]?.provider_id ?? null;
        });
        setState("ready");
      } catch (loadError) {
        if (cancelled) {
          return;
        }

        const message =
          loadError instanceof Error ? loadError.message : "Unknown request failure.";
        setError(message);
        setState("error");
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const persistProviderOrderSilently = async (providerIds: string[]) => {
    try {
      await saveProviderCatalogOrder({ provider_ids: providerIds });
    } catch {
      // Keep the current UI order even if persistence fails during a side effect.
    }
  };

  return {
    state,
    items,
    error,
    createProvider: async (input) => {
      setIsCreatingProvider(true);
      try {
        const createdProvider = await createProviderCatalogEntry({
          api_base_url: input.apiBaseUrl,
          auth_scheme: input.authScheme,
          display_name: input.displayName,
          category_id: input.categoryId,
          protocol_family: input.protocolFamily,
        });

        const remainingItems = itemsRef.current.filter(
          (item) => item.provider_id !== createdProvider.provider_id,
        );
        const nextItems = [createdProvider, ...remainingItems];
        const nextProviderIds = toProviderIds(nextItems);
        setItems(nextItems);
        setSelectedProviderId(createdProvider.provider_id);
        dispatchProjectCatalogChanged();
        void persistProviderOrderSilently(nextProviderIds);
      } finally {
        setIsCreatingProvider(false);
      }
    },
    deleteProvider: async (providerId) => {
      const provider = items.find((item) => item.provider_id === providerId);
      if (!provider) {
        throw new Error("供应商不存在。");
      }
      const nextSelectedProviderId =
        items.find((item) => item.provider_id !== providerId)?.provider_id ?? null;
      setError(null);
      setDeletingProviderId(providerId);
      try {
        await deleteProviderCatalogEntry(providerId);

        const nextItems = itemsRef.current.filter(
          (item) => item.provider_id !== providerId,
        );
        const nextProviderIds = toProviderIds(nextItems);
        setItems(nextItems);
        setSelectedProviderId((current) =>
          current === providerId ? nextSelectedProviderId : current,
        );
        dispatchProjectCatalogChanged();
        emitLlmModelCatalogChanged({ providerId });
        void persistProviderOrderSilently(nextProviderIds);
      } catch (deleteError) {
        setError(
          deleteError instanceof Error ? deleteError.message : "删除供应商失败。",
        );
        throw deleteError;
      } finally {
        setDeletingProviderId((current) => (current === providerId ? null : current));
      }
    },
    deletingProviderId,
    isCreatingProvider,
    renameProvider: async (providerId, displayName) => {
      const normalizedDisplayName = displayName.trim();
      if (!normalizedDisplayName) {
        throw new Error("供应商名称不能为空。");
      }

      const provider = items.find((item) => item.provider_id === providerId);
      if (!provider) {
        throw new Error("供应商不存在。");
      }
      setError(null);
      setRenamingProviderId(providerId);
      try {
        const updatedProvider = await updateProviderCatalogEntry(providerId, {
          display_name: normalizedDisplayName,
        });

        setItems((currentItems) =>
          currentItems.map((item) =>
            item.provider_id === updatedProvider.provider_id ? updatedProvider : item,
          ),
        );
        dispatchProjectCatalogChanged();
        emitLlmModelCatalogChanged({ providerId });
      } catch (renameError) {
        setError(
          renameError instanceof Error ? renameError.message : "供应商重命名失败。",
        );
        throw renameError;
      } finally {
        setRenamingProviderId((current) => (current === providerId ? null : current));
      }
    },
    revealProvider: async (providerId) => {
      setError(null);
      try {
        await revealProviderCatalogEntry(providerId);
      } catch (revealError) {
        setError(
          revealError instanceof Error
            ? revealError.message
            : "无法在资源管理器中打开供应商目录。",
        );
        throw revealError;
      }
    },
    renamingProviderId,
    updatingProviderProtocolId,
    selectedProvider:
      items.find((item) => item.provider_id === selectedProviderId) ?? null,
    selectedProviderId,
    selectProvider: setSelectedProviderId,
    updateProviderProtocol: async (providerId, protocolFamily) => {
      setUpdatingProviderProtocolId(providerId);
      try {
        const updatedProvider = await updateProviderCatalogEntry(providerId, {
          protocol_family: protocolFamily,
        });

        setItems((currentItems) =>
          currentItems.map((item) =>
            item.provider_id === updatedProvider.provider_id ? updatedProvider : item,
          ),
        );
        emitLlmModelCatalogChanged({ providerId });
      } finally {
        setUpdatingProviderProtocolId(null);
      }
    },
    getReorderedProviderIds: (activeProviderId, targetProviderId, position) =>
      toProviderIds(
        reorderProviderItems(items, activeProviderId, targetProviderId, position),
      ),
    previewProviderOrder: (providerIds) => {
      setItems((currentItems) => applyStoredProviderOrder(currentItems, providerIds));
    },
    persistProviderOrder: async (providerIds) => {
      const response = await saveProviderCatalogOrder({ provider_ids: providerIds });
      setItems((currentItems) =>
        applyStoredProviderOrder(currentItems, response.provider_ids),
      );
    },
    reload: () => setRequestKey((current) => current + 1),
  };
}
