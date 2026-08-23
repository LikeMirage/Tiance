import { CaretDown, Check } from "@phosphor-icons/react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import {
  getToolParameterPermissionOption,
  TOOL_PARAMETER_PERMISSION_GROUPS,
  type ToolParameterPermissionType,
} from "../../../entities/tool/model/toolPermissions";

type ToolParameterPermissionPickerProps = {
  onChange: (value: ToolParameterPermissionType | "") => void;
  value: ToolParameterPermissionType | "";
};

export function ToolParameterPermissionPicker({
  onChange,
  value,
}: ToolParameterPermissionPickerProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const selectedOption = getToolParameterPermissionOption(value);
  const selectedGroup = TOOL_PARAMETER_PERMISSION_GROUPS.find((group) =>
    group.options.some((option) => option.value === value),
  ) ?? TOOL_PARAMETER_PERMISSION_GROUPS[0];
  const [isOpen, setIsOpen] = useState(false);
  const [activeGroupId, setActiveGroupId] = useState(selectedGroup.id);
  const [panelStyle, setPanelStyle] = useState({ left: 0, top: 0, width: 540 });

  const activeGroup = TOOL_PARAMETER_PERMISSION_GROUPS.find(
    (group) => group.id === activeGroupId,
  ) ?? TOOL_PARAMETER_PERMISSION_GROUPS[0];

  useLayoutEffect(() => {
    if (!isOpen || !triggerRef.current) return;
    const trigger = triggerRef.current.getBoundingClientRect();
    const width = Math.min(540, Math.max(320, window.innerWidth - 24));
    const height = 300;
    const left = Math.min(
      Math.max(12, trigger.left),
      Math.max(12, window.innerWidth - width - 12),
    );
    const top = trigger.bottom + height + 8 <= window.innerHeight
      ? trigger.bottom + 6
      : Math.max(12, trigger.top - height - 6);
    setPanelStyle({ left, top, width });
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    setActiveGroupId(selectedGroup.id);

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!panelRef.current?.contains(target) && !triggerRef.current?.contains(target)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    };
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, selectedGroup.id]);

  return (
    <>
      <button
        aria-controls={isOpen ? panelId : undefined}
        aria-expanded={isOpen}
        className="tool-dashboard__permission-trigger"
        ref={triggerRef}
        type="button"
        onClick={() => setIsOpen((current) => !current)}
      >
        <span>
          <strong>{selectedOption.label}</strong>
          <small>{selectedOption.description}</small>
        </span>
        <CaretDown aria-hidden="true" size={14} />
      </button>
      {isOpen ? createPortal(
        <div
          aria-label="选择参数权限类型"
          className="tool-dashboard__permission-panel"
          id={panelId}
          ref={panelRef}
          role="dialog"
          style={panelStyle}
        >
          <nav className="tool-dashboard__permission-groups" aria-label="权限分类">
            {TOOL_PARAMETER_PERMISSION_GROUPS.map((group) => (
              <button
                className={group.id === activeGroup.id ? "is-active" : ""}
                key={group.id}
                type="button"
                onClick={() => setActiveGroupId(group.id)}
              >
                <span>{group.label}</span>
                <small>{group.options.length}</small>
              </button>
            ))}
          </nav>
          <div className="tool-dashboard__permission-options">
            {activeGroup.options.map((option) => (
              <button
                className={option.value === value ? "is-selected" : ""}
                key={option.value || "unknown"}
                type="button"
                onClick={() => {
                  onChange(option.value);
                  setIsOpen(false);
                }}
              >
                <span>
                  <strong>{option.label}</strong>
                  <small>{option.description}</small>
                </span>
                {option.value === value ? <Check aria-hidden="true" size={16} weight="bold" /> : null}
              </button>
            ))}
          </div>
        </div>,
        document.body,
      ) : null}
    </>
  );
}
