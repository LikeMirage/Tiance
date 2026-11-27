import type { Icon } from "@phosphor-icons/react";
import { useId, type ReactNode } from "react";
import { EdgeScrollArea } from "../../../shared/ui/edge-scrollbar";

export function ChatComposerCategoryLayout<Category extends string>({
  label, categories, activeCategory, onSelect, children,
}: {
  label: string;
  categories: readonly { id: Category; label: string; icon: Icon }[];
  activeCategory: Category;
  onSelect: (category: Category) => void;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div className="chat-composer-add-menu__body">
      <EdgeScrollArea className="chat-composer-add-menu__categories" role="tablist"
        aria-label={label} aria-orientation="vertical">
        {categories.map(({ id: category, label: name, icon: CategoryIcon }, index) => (
          <button key={category} type="button" role="tab" id={`${id}-${category}`}
            className={`chat-composer-add-menu__category${activeCategory === category ? " chat-composer-add-menu__category--active" : ""}`}
            aria-selected={activeCategory === category} aria-controls={`${id}-options`}
            tabIndex={activeCategory === category ? 0 : -1}
            onClick={() => onSelect(category)}
            onKeyDown={event => {
              if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
              event.preventDefault();
              const offset = event.key === "ArrowUp" ? -1 : 1;
              const next = categories[(index + offset + categories.length) % categories.length];
              event.currentTarget.ownerDocument.getElementById(`${id}-${next.id}`)?.focus();
              onSelect(next.id);
            }}>
            <CategoryIcon size={15} weight="regular" aria-hidden="true" />
            <span>{name}</span>
          </button>
        ))}
      </EdgeScrollArea>
      <EdgeScrollArea className="chat-composer-add-menu__options" role="tabpanel" id={`${id}-options`}
        aria-labelledby={`${id}-${activeCategory}`}>
        {children}
      </EdgeScrollArea>
    </div>
  );
}
