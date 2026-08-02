import { useCallback, useEffect, useMemo, useState } from "react";

export type NestedMenuItem<Id extends string = string> = {
  id: Id;
  label: string;
};

export type NestedMenuItemId<Item extends NestedMenuItem> = Item["id"] & string;

export type PersistentNestedMenuConfig<Item extends NestedMenuItem> = {
  defaultItemId: NestedMenuItemId<Item>;
  items: readonly Item[];
  storageKey: string;
};

type UsePersistentNestedMenuSelectionOptions<Item extends NestedMenuItem> =
  PersistentNestedMenuConfig<Item> & {
    isParentActive: boolean;
  };

export function usePersistentNestedMenuSelection<Item extends NestedMenuItem>({
  defaultItemId,
  isParentActive,
  items,
  storageKey,
}: UsePersistentNestedMenuSelectionOptions<Item>) {
  const [activeItemId, setActiveItemId] = useState<NestedMenuItemId<Item>>(() =>
    readStoredItemId({
      defaultItemId,
      items,
      storageKey,
    }),
  );
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    if (hasItemId(items, activeItemId)) {
      return;
    }

    const availableItemId = resolveAvailableItemId(items, defaultItemId);
    setActiveItemId(availableItemId);
    writeStoredItemId(storageKey, availableItemId);
  }, [activeItemId, defaultItemId, items, storageKey]);

  const activeItem = useMemo(
    () => resolveActiveItem(items, activeItemId, defaultItemId),
    [activeItemId, defaultItemId, items],
  );

  const selectItemId = useCallback((itemId: NestedMenuItemId<Item>) => {
    if (!hasItemId(items, itemId)) {
      return;
    }

    setActiveItemId(itemId);
    writeStoredItemId(storageKey, itemId);
  }, [items, storageKey]);

  const selectItem = useCallback((item: Item) => {
    selectItemId(item.id);
  }, [selectItemId]);

  return {
    activeItem,
    activeItemId,
    isHovered,
    isOpen: isParentActive || isHovered,
    selectItem,
    selectItemId,
    setIsHovered,
  };
}

function readStoredItemId<Item extends NestedMenuItem>({
  defaultItemId,
  items,
  storageKey,
}: PersistentNestedMenuConfig<Item>): NestedMenuItemId<Item> {
  if (typeof window === "undefined") return resolveAvailableItemId(items, defaultItemId);

  try {
    const stored = window.localStorage.getItem(storageKey);
    return hasItemId(items, stored) ? stored : resolveAvailableItemId(items, defaultItemId);
  } catch {
    return resolveAvailableItemId(items, defaultItemId);
  }
}

function writeStoredItemId(storageKey: string, itemId: string) {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(storageKey, itemId);
  } catch {
    // Navigation remains usable for the current session when storage is unavailable.
  }
}

function resolveActiveItem<Item extends NestedMenuItem>(
  items: readonly Item[],
  activeItemId: NestedMenuItemId<Item>,
  defaultItemId: NestedMenuItemId<Item>,
): Item {
  const item = items.find((candidate) => candidate.id === activeItemId)
    ?? items.find((item) => item.id === defaultItemId)
    ?? items[0];

  if (!item) {
    throw new Error("Nested menu config must include at least one item.");
  }

  return item;
}

function resolveAvailableItemId<Item extends NestedMenuItem>(
  items: readonly Item[],
  defaultItemId: NestedMenuItemId<Item>,
): NestedMenuItemId<Item> {
  return items.some((item) => item.id === defaultItemId)
    ? defaultItemId
    : items[0]?.id ?? defaultItemId;
}

function hasItemId<Item extends NestedMenuItem>(
  items: readonly Item[],
  value: string | null,
): value is NestedMenuItemId<Item> {
  return items.some((item) => item.id === value);
}
