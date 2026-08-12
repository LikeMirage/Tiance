import { useRef, useState } from "react";

import type { UseProviderCatalogResult } from "./useProviderCatalog";
import {
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
  const displayNameInputRef = useRef<HTMLInputElement | null>(null);
  const [draft, setDraft] =
    useState<ProviderCreateFormDraft>(EMPTY_PROVIDER_CREATE_FORM);
  const [error, setError] = useState<string | null>(null);
  const [isDisplayNameInvalid, setIsDisplayNameInvalid] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  const isInteractive = isVisible && !providerCatalog.isCreatingProvider;

  const reset = () => {
    setDraft(EMPTY_PROVIDER_CREATE_FORM);
    setError(null);
    setIsDisplayNameInvalid(false);
  };

  const close = () => {
    setIsVisible(false);
    reset();
  };

  const toggle = () => {
    setIsVisible((current) => !current);
    setError(null);
    setIsDisplayNameInvalid(false);
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
    setIsDisplayNameInvalid(false);
  };

  const submit = async () => {
    const displayName = draft.displayName.trim();

    if (!displayName) {
      setError(null);
      setIsDisplayNameInvalid(true);
      displayNameInputRef.current?.focus();
      return;
    }

    setIsDisplayNameInvalid(false);

    try {
      await providerCatalog.createProvider({
        displayName,
        categoryId,
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
    displayNameInputRef,
    close,
    draft,
    error,
    isDisplayNameInvalid,
    isInteractive,
    isVisible,
    submit,
    toggle,
    updateField,
  };
}
