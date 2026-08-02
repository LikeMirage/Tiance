import { useCallback, useMemo, useRef, useState } from "react";

import type { useDocumentTabs } from "../../../features/document-tabs/model/useDocumentTabs";

export type UnsavedChangesIntent = "return" | "switch" | "exit";

type DocumentTabsController = Pick<
  ReturnType<typeof useDocumentTabs>,
  "discardTabChanges" | "saveTab" | "selectTab" | "tabs"
>;

type PendingDirtyTab = {
  discard: () => Promise<boolean>;
  label: string;
  save: () => Promise<boolean>;
  select: () => void;
};

type PendingTransition = {
  action: () => void | Promise<void>;
  dirtyTabs: PendingDirtyTab[];
  intent: UnsavedChangesIntent;
  resolve: (didContinue: boolean) => void;
};

type GuardState = {
  error: string | null;
  intent: UnsavedChangesIntent;
  isSaving: boolean;
  labels: string[];
};

export function useWorkspaceUnsavedChangesGuard() {
  const pendingRef = useRef<PendingTransition | null>(null);
  const runIdRef = useRef(0);
  const [state, setState] = useState<GuardState | null>(null);

  const requestTransition = useCallback(async (
    controllers: DocumentTabsController[],
    intent: UnsavedChangesIntent,
    action: () => void | Promise<void>,
  ) => {
    if (pendingRef.current) return false;
    const dirtyTabs = collectDirtyTabs(controllers);
    if (dirtyTabs.length === 0) {
      await action();
      return true;
    }

    return new Promise<boolean>((resolve) => {
      pendingRef.current = { action, dirtyTabs, intent, resolve };
      setState({
        error: null,
        intent,
        isSaving: false,
        labels: dirtyTabs.map((tab) => tab.label),
      });
    });
  }, []);

  const cancel = useCallback(() => {
    const pending = pendingRef.current;
    if (!pending || state?.isSaving) return;
    runIdRef.current += 1;
    pendingRef.current = null;
    setState(null);
    pending.resolve(false);
  }, [state?.isSaving]);

  const finishTransition = useCallback(async (
    pending: PendingTransition,
    runId: number,
  ) => {
    try {
      await pending.action();
      if (runIdRef.current !== runId || pendingRef.current !== pending) return;
      pendingRef.current = null;
      setState(null);
      pending.resolve(true);
    } catch (error) {
      if (runIdRef.current !== runId || pendingRef.current !== pending) return;
      setState((current) => current ? {
        ...current,
        error: error instanceof Error ? error.message : "操作失败，请重试。",
        isSaving: false,
      } : current);
    }
  }, []);

  const saveAndContinue = useCallback(async () => {
    const pending = pendingRef.current;
    if (!pending || state?.isSaving) return;
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    setState((current) => current ? { ...current, error: null, isSaving: true } : current);

    for (const tab of pending.dirtyTabs) {
      const didSave = await tab.save();
      if (runIdRef.current !== runId || pendingRef.current !== pending) return;
      if (!didSave) {
        tab.select();
        setState((current) => current ? {
          ...current,
          error: `保存 ${tab.label} 失败。请重试，或选择不保存。`,
          isSaving: false,
        } : current);
        return;
      }
    }
    await finishTransition(pending, runId);
  }, [finishTransition, state?.isSaving]);

  const discardAndContinue = useCallback(async () => {
    const pending = pendingRef.current;
    if (!pending || state?.isSaving) return;
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;
    setState((current) => current ? { ...current, error: null, isSaving: true } : current);

    for (const tab of pending.dirtyTabs) {
      const didDiscard = await tab.discard();
      if (runIdRef.current !== runId || pendingRef.current !== pending) return;
      if (!didDiscard) {
        tab.select();
        setState((current) => current ? {
          ...current,
          error: `无法放弃 ${tab.label} 的未保存更改。`,
          isSaving: false,
        } : current);
        return;
      }
    }
    await finishTransition(pending, runId);
  }, [finishTransition, state?.isSaving]);

  const modal = useMemo(() => state ? {
    confirmLabel: state.isSaving ? "处理中..." : intentCopy[state.intent].confirm,
    error: state.error,
    fileLabels: state.labels,
    isBusy: state.isSaving,
    onCancel: cancel,
    onConfirm: saveAndContinue,
    onDiscard: discardAndContinue,
    secondaryLabel: intentCopy[state.intent].discard,
    title: intentCopy[state.intent].title,
  } : null, [cancel, discardAndContinue, saveAndContinue, state]);

  return { modal, requestTransition };
}

function collectDirtyTabs(controllers: DocumentTabsController[]): PendingDirtyTab[] {
  return controllers.flatMap((controller) => controller.tabs
    .filter((tab) => tab.isDirty)
    .map((tab) => ({
      discard: () => controller.discardTabChanges(tab.id),
      label: tab.projectFilePath ?? tab.filePath ?? tab.displayPath ?? tab.title,
      save: () => controller.saveTab(tab.id),
      select: () => controller.selectTab(tab.id),
    })));
}

const intentCopy: Record<UnsavedChangesIntent, {
  confirm: string;
  discard: string;
  title: string;
}> = {
  return: {
    confirm: "保存并返回",
    discard: "不保存并返回",
    title: "返回前保存更改",
  },
  switch: {
    confirm: "保存并切换",
    discard: "不保存并切换",
    title: "切换前保存更改",
  },
  exit: {
    confirm: "保存并退出",
    discard: "不保存并退出",
    title: "退出前保存更改",
  },
};
