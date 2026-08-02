import {
  CaretDown,
  CaretRight,
  File as PhosphorFile,
  Folder,
  FolderOpen,
} from "@phosphor-icons/react";

export function ChevronRightIcon() {
  return <CaretRight size={12} weight="bold" aria-hidden="true" />;
}

export function ChevronDownIcon() {
  return <CaretDown size={12} weight="bold" aria-hidden="true" />;
}

export function FolderIcon() {
  return <Folder size={14} weight="duotone" aria-hidden="true" />;
}

export function FolderOpenIcon() {
  return <FolderOpen size={14} weight="duotone" aria-hidden="true" />;
}

export function FileIcon() {
  return <PhosphorFile size={14} weight="duotone" aria-hidden="true" />;
}
