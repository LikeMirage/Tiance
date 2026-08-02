import { useRef, useState } from "react";

import type { UseProviderCatalogResult } from "./useProviderCatalog";
import {
  deriveProviderDisplayName,
  EMPTY_PROVIDER_CREATE_FORM,
  type ProviderCreateFormDraft,
} from "./providerCreateForm";

type UseProviderCreateFormInput = {
  categoryId?: string | null;
  onCreated: () => void;
  providerCatalog: UseProviderCatalogResult;
};

export function useProviderCreateForm({
  categoryId,
  onCreated,
  providerCatalog,
}: UseProviderCreateFormInput) {
  const apiBaseUrlInputRef = useRef<HTMLInputElement | null>(null);
  const [draft, setDraft] =
    useState<ProviderCreateFormDraft>(EMPTY_PROVIDER_CREATE_FORM);
  const [error, setError] = useState<string | null>(null);
  const [isApiBaseUrlInvalid, setIsApiBaseUrlInvalid] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  const isInteractive = isVisible && !providerCatalog.isCreatingProvider;

  const reset = () => {
    setDraft(EMPTY_PROVIDER_CREATE_FORM);
    setError(null);
    setIsApiBaseUrlInvalid(false);
  };

  const close = () => {
    setIsVisible(false);
    reset();
  };

  const toggle = () => {
    setIsVisible((current) => !current);
    setError(null);
    setIsApiBaseUrlInvalid(false);
  };

  const updateField = <Field extends keyof ProviderCreateFormDraft>(
    field: Field,
    value: ProviderCreateFormDraft[Field],
  ) => {
    setDraft((current) => ({
      ...current,
      [field]: value,
    }));
    setError(null);
    if (field === "apiBaseUrl") {
      setIsApiBaseUrlInvalid(false);
    }
  };

  const submit = async () => {
    const displayName = draft.displayName.trim();
    const apiBaseUrl = draft.apiBaseUrl.trim();
    const resolvedDisplayName = displayName || deriveProviderDisplayName(apiBaseUrl);

    if (!displayName && !apiBaseUrl) {
      close();
      return;
    }

    if (!apiBaseUrl) {
      setError(null);
      setIsApiBaseUrlInvalid(true);
      apiBaseUrlInputRef.current?.focus();
      return;
    }

    setIsApiBaseUrlInvalid(false);

    try {
      await providerCatalog.createProvider({
        apiBaseUrl,
        authScheme: draft.authScheme,
        displayName: resolvedDisplayName,
        categoryId,
        protocolFamily: draft.protocolFamily,
      });
      onCreated();
      close();
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "新增供应商失败。",
      );
    }
  };

  return {
    apiBaseUrlInputRef,
    close,
    draft,
    error,
    isApiBaseUrlInvalid,
    isInteractive,
    isVisible,
    submit,
    toggle,
    updateField,
  };
}
