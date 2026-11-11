import type { DragEvent } from "react";

import {
  parseProjectFileDragData,
  PROJECT_FILE_DRAG_MIME_TYPE,
} from "../../../entities/project/model/projectFileDragData";
import type { ChatComposerInputState } from "./ChatComposerTypes";
import { getDesktopFileDragData } from "../../desktop-shell/model/desktopFileDrag";
import { parseProjectDragData, PROJECT_DRAG_MIME_TYPE } from "../../../entities/project/model/projectDragData";
import { referenceComposerProject } from "../model/composerProjectReference";

export function hasChatComposerReferenceDrag(event: DragEvent<HTMLElement>, input: ChatComposerInputState): boolean {
  return hasDraggedProjectFile(event)
    || Boolean(input.onReferenceExternalPath && Array.from(event.dataTransfer.types).includes(PROJECT_DRAG_MIME_TYPE));
}

export function handleChatComposerReferenceDrop(event: DragEvent<HTMLElement>, input: ChatComposerInputState): boolean {
  if (Array.from(event.dataTransfer.types).includes(PROJECT_DRAG_MIME_TYPE)) {
    const project = parseProjectDragData(event.dataTransfer.getData(PROJECT_DRAG_MIME_TYPE));
    return project !== null && referenceComposerProject(project, input.onReferenceExternalPath);
  }
  return handleChatComposerProjectFileDrop(event, input);
}

export function handleChatComposerProjectFileDrop(
  event: DragEvent<HTMLElement>,
  input: ChatComposerInputState,
): boolean {
  const projectFile = parseProjectFileDragData(
    event.dataTransfer.getData(PROJECT_FILE_DRAG_MIME_TYPE) || getDesktopFileDragData(PROJECT_FILE_DRAG_MIME_TYPE) || "",
  );
  if (projectFile) {
    input.onDropProjectFile?.(projectFile);
    return true;
  }
  return false;
}

export function hasDraggedProjectFile(event: DragEvent<HTMLElement>) {
  return Array.from(event.dataTransfer.types).includes(PROJECT_FILE_DRAG_MIME_TYPE)
    || getDesktopFileDragData(PROJECT_FILE_DRAG_MIME_TYPE) !== null;
}
