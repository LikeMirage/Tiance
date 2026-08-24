import {
  ChatsCircle,
  FilePlus,
  FolderOpen,
  Plus,
} from "@phosphor-icons/react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { createPortal } from "react-dom";

type AddCategory = "file" | "project" | "conversation";

type ChatComposerAddMenuProps = {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  onSelectFiles: () => Promise<void>;
};

const PANEL_HEIGHT = 216;

const CATEGORIES: Array<{
  icon: typeof FilePlus;
  id: AddCategory;
  label: string;
}> = [
  { id: "file", label: "文件", icon: FilePlus },
  { id: "project", label: "项目", icon: FolderOpen },
  { id: "conversation", label: "会话", icon: ChatsCircle },
];

export function ChatComposerAddMenu({
  isOpen,
  onOpenChange,
  onSelectFiles,
}: ChatComposerAddMenuProps) {
  const generatedId = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [activeCategory, setActiveCategory] = useState<AddCategory>("file");
  const [panelStyle, setPanelStyle] = useState<CSSProperties | null>(null);

  useEffect(() => {
    if (!isOpen) {
      setPanelStyle(null);
      return;
    }
    setActiveCategory("file");
  }, [isOpen]);

  useLayoutEffect(() => {
    if (!isOpen) return undefined;

    const updatePanelPosition = () => {
      const trigger = triggerRef.current;
      if (!trigger) return;

      const triggerRect = trigger.getBoundingClientRect();
      const edgePadding = 8;
      const gap = 6;
      const width = Math.min(440, window.innerWidth - edgePadding * 2);
      const height = Math.min(PANEL_HEIGHT, window.innerHeight - edgePadding * 2);
      const left = Math.min(
        Math.max(edgePadding, triggerRect.left),
        Math.max(edgePadding, window.innerWidth - width - edgePadding),
      );
      const top = Math.max(edgePadding, triggerRect.top - height - gap);

      setPanelStyle({
        height,
        left,
        maxHeight: height,
        minHeight: height,
        top,
        visibility: "visible",
        width,
      });
    };

    updatePanelPosition();
    window.addEventListener("resize", updatePanelPosition);
    window.addEventListener("scroll", updatePanelPosition, true);
    return () => {
      window.removeEventListener("resize", updatePanelPosition);
      window.removeEventListener("scroll", updatePanelPosition, true);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return undefined;

    const handleMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (triggerRef.current?.contains(target) || panelRef.current?.contains(target)) return;
      onOpenChange(false);
    };
    window.addEventListener("mousedown", handleMouseDown);
    return () => window.removeEventListener("mousedown", handleMouseDown);
  }, [isOpen, onOpenChange]);

  const handlePanelKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    onOpenChange(false);
    triggerRef.current?.focus();
  };

  const panelId = `${generatedId}-panel`;
  const panel = isOpen && typeof document !== "undefined"
    ? createPortal(
        <div
          id={panelId}
          ref={panelRef}
          className="chat-composer-add-menu__panel"
          role="dialog"
          aria-label="添加到对话"
          style={panelStyle ?? { left: 0, top: 0, visibility: "hidden" }}
          onKeyDown={handlePanelKeyDown}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <div className="chat-composer-add-menu__head">
            <strong>添加到对话</strong>
            <span>选择要加入当前输入的内容</span>
          </div>
          <div className="chat-composer-add-menu__body">
            <div className="chat-composer-add-menu__categories" role="tablist" aria-label="内容类型">
              {CATEGORIES.map((category) => {
                const Icon = category.icon;
                const isActive = activeCategory === category.id;
                return (
                  <button
                    key={category.id}
                    className={[
                      "chat-composer-add-menu__category",
                      isActive ? "chat-composer-add-menu__category--active" : "",
                    ].filter(Boolean).join(" ")}
                    type="button"
                    role="tab"
                    aria-selected={isActive}
                    onClick={() => setActiveCategory(category.id)}
                  >
                    <Icon size={15} weight="regular" aria-hidden="true" />
                    <span>{category.label}</span>
                  </button>
                );
              })}
            </div>
            <div className="chat-composer-add-menu__options" role="tabpanel">
              {activeCategory === "file" ? (
                <button
                  className="chat-composer-add-menu__option"
                  type="button"
                  onClick={() => {
                    onOpenChange(false);
                    void onSelectFiles();
                  }}
                >
                  <FilePlus size={18} weight="regular" aria-hidden="true" />
                  <span className="chat-composer-add-menu__option-copy">
                    <strong>从资源管理器中选择文件</strong>
                    <span>选择一个或多个本机文件，添加到当前输入内容</span>
                  </span>
                  <span className="chat-composer-add-menu__badge">多选</span>
                </button>
              ) : null}
              {activeCategory === "project" ? (
                <button className="chat-composer-add-menu__option" type="button" disabled>
                  <FolderOpen size={18} weight="regular" aria-hidden="true" />
                  <span className="chat-composer-add-menu__option-copy">
                    <strong>添加项目</strong>
                    <span>将项目作为上下文添加到当前对话</span>
                  </span>
                  <span className="chat-composer-add-menu__badge">暂未开放</span>
                </button>
              ) : null}
              {activeCategory === "conversation" ? (
                <button className="chat-composer-add-menu__option" type="button" disabled>
                  <ChatsCircle size={18} weight="regular" aria-hidden="true" />
                  <span className="chat-composer-add-menu__option-copy">
                    <strong>添加会话</strong>
                    <span>引用另一会话中的内容与上下文</span>
                  </span>
                  <span className="chat-composer-add-menu__badge">暂未开放</span>
                </button>
              ) : null}
            </div>
          </div>
        </div>,
        document.body,
      )
    : null;

  return (
    <>
      {panel}
      <button
        ref={triggerRef}
        className={[
          "ai-panel__composer-add",
          isOpen ? "ai-panel__composer-add--open" : "",
        ].filter(Boolean).join(" ")}
        type="button"
        aria-controls={isOpen ? panelId : undefined}
        aria-expanded={isOpen}
        aria-label="添加到对话"
        title="添加到对话"
        onClick={() => onOpenChange(!isOpen)}
      >
        <Plus aria-hidden="true" size={17} weight="regular" />
      </button>
    </>
  );
}
