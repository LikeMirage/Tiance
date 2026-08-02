import {
  Fragment,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { useI18n } from "../../../shared/i18n";
import { getModelCapabilityLabel } from "../../../shared/i18n/modelCapabilityLabels";
import {
  filterLlmModelProviderGroups,
  groupLlmModelsByProvider,
  type LlmModelProviderGroup,
} from "../model/llmModelCatalogQuery";
import {
  getLlmModelPickerOptionKey,
  type LlmModelPickerOption,
} from "../model/llmModelPickerOption";

import "./llm-model-picker.css";

type LlmModelPickerPlacement = "above" | "below";
type LlmModelPickerVariant = "field" | "inline";

const MODEL_PICKER_PANEL_HEIGHT = 300;

type LlmModelPickerProps = {
  allowClear?: boolean;
  ariaLabel: string;
  className?: string;
  clearLabel?: string;
  disabled?: boolean;
  error?: string | null;
  loading?: boolean;
  onChange: (value: string, option: LlmModelPickerOption | null) => void;
  onOpen?: () => void;
  onOpenChange?: (open: boolean) => void;
  open?: boolean;
  options: readonly LlmModelPickerOption[];
  placeholder?: string;
  placement?: LlmModelPickerPlacement;
  rootRef?: RefObject<HTMLDivElement | null>;
  value: string;
  variant?: LlmModelPickerVariant;
};

export function LlmModelPicker({
  allowClear = false,
  ariaLabel,
  className,
  clearLabel = "关闭",
  disabled = false,
  error = null,
  loading = false,
  onChange,
  onOpen,
  onOpenChange,
  open,
  options,
  placeholder = "选择模型",
  placement = "below",
  rootRef,
  value,
  variant = "field",
}: LlmModelPickerProps) {
  const { t } = useI18n();
  const generatedId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const internalRootRef = useRef<HTMLDivElement | null>(null);
  const containerRef = rootRef ?? internalRootRef;
  const isControlledOpen = open !== undefined;
  const [internalOpen, setInternalOpen] = useState(false);
  const [panelStyle, setPanelStyle] = useState<CSSProperties | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeProviderId, setActiveProviderId] = useState<string | null>(null);
  const wasOpenRef = useRef(false);
  const isOpen = isControlledOpen ? open : internalOpen;
  const selectedOption = useMemo(
    () => options.find((option) => getLlmModelPickerOptionKey(option) === value) ?? null,
    [options, value],
  );
  const providerGroups = useMemo(() => groupLlmModelsByProvider(options), [options]);
  const filteredGroups = useMemo(
    () => filterLlmModelProviderGroups(providerGroups, searchQuery),
    [providerGroups, searchQuery],
  );
  const resolvedProviderId =
    activeProviderId && filteredGroups.some((group) => group.providerId === activeProviderId)
      ? activeProviderId
      : filteredGroups[0]?.providerId ?? null;
  const activeGroup =
    filteredGroups.find((group) => group.providerId === resolvedProviderId) ?? null;
  const selectedLabel = selectedOption?.modelLabel ?? placeholder;
  const selectedMeta = selectedOption ? selectedOption.providerLabel : null;
  const shouldShowClear = allowClear && value;
  const initialProviderId = selectedOption?.providerId ?? providerGroups[0]?.providerId ?? null;

  useEffect(() => {
    const justOpened = isOpen && !wasOpenRef.current;
    wasOpenRef.current = isOpen;

    if (!isOpen) {
      setPanelStyle(null);
      return;
    }

    if (justOpened) {
      setSearchQuery("");
      setActiveProviderId(initialProviderId);
    }
  }, [initialProviderId, isOpen]);

  useLayoutEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const updatePanelPosition = () => {
      const trigger = triggerRef.current;
      const panel = panelRef.current;
      if (!trigger || !panel) {
        return;
      }

      const triggerRect = trigger.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const edgePadding = 8;
      const gap = 6;
      const targetWidth = Math.min(
        Math.max(triggerRect.width, variant === "inline" ? 500 : 520),
        viewportWidth - edgePadding * 2,
      );
      const availableHeight = Math.max(160, viewportHeight - edgePadding * 2);
      const panelHeight = Math.min(MODEL_PICKER_PANEL_HEIGHT, availableHeight);
      const left = Math.min(
        Math.max(edgePadding, triggerRect.left),
        Math.max(edgePadding, viewportWidth - targetWidth - edgePadding),
      );
      const top = placement === "above"
        ? Math.max(edgePadding, triggerRect.top - panelHeight - gap)
        : Math.min(
            triggerRect.bottom + gap,
            Math.max(edgePadding, viewportHeight - panelHeight - edgePadding),
          );

      setPanelStyle({
        left,
        top,
        visibility: "visible",
        width: targetWidth,
        height: panelHeight,
        minHeight: panelHeight,
        maxHeight: panelHeight,
      });
    };

    updatePanelPosition();
    window.addEventListener("resize", updatePanelPosition);
    window.addEventListener("scroll", updatePanelPosition, true);
    return () => {
      window.removeEventListener("resize", updatePanelPosition);
      window.removeEventListener("scroll", updatePanelPosition, true);
    };
  }, [
    activeGroup?.models.length,
    filteredGroups.length,
    isOpen,
    placement,
    shouldShowClear,
    variant,
  ]);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      searchInputRef.current?.focus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [isOpen]);

  useEffect(() => {
    if (isControlledOpen || !isOpen) {
      return undefined;
    }

    const handleMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        containerRef.current?.contains(target) ||
        panelRef.current?.contains(target)
      ) {
        return;
      }
      setInternalOpen(false);
    };
    window.addEventListener("mousedown", handleMouseDown);
    return () => window.removeEventListener("mousedown", handleMouseDown);
  }, [containerRef, isControlledOpen, isOpen]);

  const setOpen = (nextOpen: boolean) => {
    if (disabled && nextOpen) {
      return;
    }
    if (nextOpen && !isOpen) {
      onOpen?.();
    }
    if (!isControlledOpen) {
      setInternalOpen(nextOpen);
    }
    onOpenChange?.(nextOpen);
  };

  const close = () => setOpen(false);

  const selectModel = (option: LlmModelPickerOption) => {
    onChange(getLlmModelPickerOptionKey(option), option);
    close();
  };

  const clearModel = () => {
    onChange("", null);
    close();
  };

  const handlePanelKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }

    if (event.key === "Enter" && event.target === searchInputRef.current) {
      const firstModel = activeGroup?.models[0] ?? filteredGroups[0]?.models[0] ?? null;
      if (firstModel) {
        event.preventDefault();
        selectModel(firstModel);
      }
    }
  };

  const panelId = `${generatedId}-panel`;
  const searchId = `${generatedId}-search`;
  const panel = isOpen && typeof document !== "undefined"
    ? createPortal(
        <div
          id={panelId}
          ref={panelRef}
          className="llm-model-picker__panel"
          role="dialog"
          aria-label={`${ariaLabel}列表`}
          style={panelStyle ?? { left: 0, top: 0, visibility: "hidden" }}
          onKeyDown={handlePanelKeyDown}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <div className="llm-model-picker__search-row">
            <input
              id={searchId}
              ref={searchInputRef}
              className="llm-model-picker__search"
              type="search"
              value={searchQuery}
              placeholder="搜索模型或供应商"
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </div>

          {renderPanelContent({
            activeGroup,
            clearLabel,
            disabled,
            error,
            filteredGroups,
            loading,
            onClear: clearModel,
            onSelect: selectModel,
            resolvedProviderId,
            searchQuery,
            selectedValue: value,
            setActiveProviderId,
            shouldShowClear: Boolean(shouldShowClear),
            t,
          })}
        </div>,
        document.body,
      )
    : null;

  return (
    <div
      ref={containerRef}
      className={[
        "llm-model-picker",
        `llm-model-picker--${variant}`,
        `llm-model-picker--${placement}`,
        isOpen ? "llm-model-picker--open" : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
    >
      {panel}
      <button
        ref={triggerRef}
        className="llm-model-picker__trigger"
        type="button"
        aria-controls={isOpen ? panelId : undefined}
        aria-expanded={isOpen}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => setOpen(!isOpen)}
      >
        <span
          className={[
            "llm-model-picker__trigger-main",
            selectedOption ? "" : "llm-model-picker__trigger-main--placeholder",
          ].filter(Boolean).join(" ")}
        >
          {selectedLabel}
        </span>
        {variant === "field" && selectedMeta ? (
          <span className="llm-model-picker__trigger-provider">{selectedMeta}</span>
        ) : null}
        <span className="llm-model-picker__caret" aria-hidden="true" />
      </button>
    </div>
  );
}

function renderPanelContent({
  activeGroup,
  clearLabel,
  disabled,
  error,
  filteredGroups,
  loading,
  onClear,
  onSelect,
  resolvedProviderId,
  searchQuery,
  selectedValue,
  setActiveProviderId,
  shouldShowClear,
  t,
}: {
  activeGroup: LlmModelProviderGroup | null;
  clearLabel: string;
  disabled: boolean;
  error: string | null;
  filteredGroups: LlmModelProviderGroup[];
  loading: boolean;
  onClear: () => void;
  onSelect: (option: LlmModelPickerOption) => void;
  resolvedProviderId: string | null;
  searchQuery: string;
  selectedValue: string;
  setActiveProviderId: (providerId: string) => void;
  shouldShowClear: boolean;
  t: ReturnType<typeof useI18n>["t"];
}) {
  if (error) {
    return <div className="llm-model-picker__state">{error}</div>;
  }

  if (loading && filteredGroups.length === 0) {
    return <div className="llm-model-picker__state">模型加载中</div>;
  }

  if (filteredGroups.length === 0) {
    return (
      <div className="llm-model-picker__state">
        {searchQuery.trim() ? "没有匹配模型" : "没有已添加模型"}
      </div>
    );
  }

  return (
    <div className="llm-model-picker__body">
      <div className="llm-model-picker__providers" role="listbox" aria-label="供应商">
        {filteredGroups.map((group) => (
          <button
            key={group.providerId}
            className={[
              "llm-model-picker__provider",
              group.providerId === resolvedProviderId
                ? "llm-model-picker__provider--active"
                : "",
            ].filter(Boolean).join(" ")}
            type="button"
            role="option"
            aria-selected={group.providerId === resolvedProviderId}
            onClick={() => setActiveProviderId(group.providerId)}
          >
            <span className="llm-model-picker__provider-label">{group.providerLabel}</span>
            <span className="llm-model-picker__provider-count">{group.models.length}</span>
          </button>
        ))}
      </div>

      <div className="llm-model-picker__models" role="listbox" aria-label="模型">
        {shouldShowClear ? (
          <button
            className="llm-model-picker__model llm-model-picker__model--clear"
            type="button"
            role="option"
            aria-selected={selectedValue === ""}
            onClick={onClear}
          >
            <span className="llm-model-picker__model-main">
              <span className="llm-model-picker__model-label">{clearLabel}</span>
              <span className="llm-model-picker__model-id">不指定模型</span>
            </span>
          </button>
        ) : null}
        {activeGroup?.models.map((model) => {
          const modelKey = getLlmModelPickerOptionKey(model);
          return (
            <Fragment key={modelKey}>
              <button
                className={[
                  "llm-model-picker__model",
                  modelKey === selectedValue ? "llm-model-picker__model--selected" : "",
                  model.isUnavailable ? "llm-model-picker__model--unavailable" : "",
                ].filter(Boolean).join(" ")}
                type="button"
                role="option"
                aria-selected={modelKey === selectedValue}
                disabled={disabled}
                onClick={() => onSelect(model)}
              >
                <span className="llm-model-picker__model-main">
                  <span className="llm-model-picker__model-label">{model.modelLabel}</span>
                  {model.modelLabel !== model.modelId ? (
                    <span className="llm-model-picker__model-id">{model.modelId}</span>
                  ) : null}
                </span>
                <span className="llm-model-picker__model-meta">
                  {model.isUnavailable ? (
                    <span className="llm-model-picker__badge">不可用</span>
                  ) : null}
                  {model.familyGroup ? (
                    <span className="llm-model-picker__badge">{model.familyGroup}</span>
                  ) : null}
                  {model.capabilityTags?.slice(0, 4).map((tag) => (
                    <span key={tag} className="llm-model-picker__badge">
                      {getModelCapabilityLabel(tag, t)}
                    </span>
                  ))}
                </span>
              </button>
              {model.annotation ? (
                <aside className="llm-model-picker__model-annotation">
                  <p>{model.annotation.summary}</p>
                  {model.annotation.notes?.length ? (
                    <ul>
                      {model.annotation.notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  ) : null}
                </aside>
              ) : null}
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}
