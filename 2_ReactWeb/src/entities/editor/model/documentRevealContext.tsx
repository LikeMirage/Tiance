import { createContext, useContext } from "react";
import type { DocumentRevealRequest } from "./documentReveal";

export const DocumentRevealContext = createContext<DocumentRevealRequest | null>(null);
export const useDocumentRevealRequest = () => useContext(DocumentRevealContext);
