import type { DragEvent } from "react";

import {
  parseProjectFileDragData,
  PROJECT_FILE_DRAG_MIME_TYPE,
} from "../../../entities/project/model/projectFileDragData";
import type { ChatComposerInputState } from "./ChatComposerTypes";

export function handleChatComposerProjectFileDrop(
  event: DragEvent<HTMLElement>,
  input: ChatComposerInputState,
): boolean {
  const projectFile = parseProjectFileDragData(
    event.dataTransfer.getData(PROJECT_FILE_DRAG_MIME_TYPE),
  );
  if (projectFile) {
    input.onDropProjectFile?.(projectFile);
    return true;
  }
  return false;
}

export function hasDraggedProjectFile(event: DragEvent<HTMLElement>) {
  return Array.from(event.dataTransfer.types).includes(PROJECT_FILE_DRAG_MIME_TYPE);
}
