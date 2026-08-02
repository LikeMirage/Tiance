import { FolderOpen } from "@phosphor-icons/react";
import type { CSSProperties } from "react";

type WorkspaceStatusPathProps = {
  label: string;
  maxWidth: number;
  onReveal: () => void;
};

export function WorkspaceStatusPath({ label, maxWidth, onReveal }: WorkspaceStatusPathProps) {
  return (
    <button
      className="workspace-status-path"
      type="button"
      title={label}
      style={{ "--workspace-status-path-max-width": `${maxWidth}px` } as CSSProperties}
      onClick={onReveal}
    >
      <FolderOpen size={14} weight="bold" />
      <span>{label}</span>
    </button>
  );
}
