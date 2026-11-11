import { createContext } from "react";
import type { ReferenceProject } from "./editorReference";

export const ReferenceProjectNavigationContext = createContext<((project: ReferenceProject) => Promise<void>) | null>(null);
