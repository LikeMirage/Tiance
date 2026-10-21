import { createContext } from "react";

// A mounted loading indicator can report to the enclosing initial-load surface.
export const LoadingBoundaryContext = createContext<(() => () => void) | null>(null);
