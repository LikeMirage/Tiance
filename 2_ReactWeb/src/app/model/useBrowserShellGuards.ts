import { useEffect } from "react";

const BLOCKED_FUNCTION_KEYS = new Set(["F1", "F5", "F6", "F7", "F10", "F11"]);
const BLOCKED_PRIMARY_SHORTCUT_KEYS = new Set([
  "0",
  "+",
  "-",
  "=",
  "d",
  "e",
  "h",
  "j",
  "l",
  "p",
  "r",
  "u",
]);

function isBlockedBrowserShortcut(event: KeyboardEvent) {
  if (event.key === "F12") {
    return false;
  }

  if (BLOCKED_FUNCTION_KEYS.has(event.key)) {
    return true;
  }

  if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
    return true;
  }

  const key = event.key.toLowerCase();
  const hasPrimaryModifier = event.ctrlKey || event.metaKey;

  if (
    hasPrimaryModifier &&
    BLOCKED_PRIMARY_SHORTCUT_KEYS.has(key)
  ) {
    return true;
  }

  if (hasPrimaryModifier && event.shiftKey && ["i", "j", "c"].includes(key)) {
    return true;
  }

  if (event.altKey && ["arrowleft", "arrowright"].includes(key)) {
    return true;
  }

  return ["browserback", "browserforward", "browserrefresh"].includes(key);
}

export function useBrowserShellGuards() {
  useEffect(() => {
    const preventContextMenu = (event: MouseEvent) => {
      event.preventDefault();
    };

    const preventBrowserShortcut = (event: KeyboardEvent) => {
      if (event.defaultPrevented) {
        return;
      }

      if (!isBlockedBrowserShortcut(event)) {
        return;
      }

      event.preventDefault();
    };

    document.addEventListener("contextmenu", preventContextMenu, {
      capture: true,
    });
    window.addEventListener("keydown", preventBrowserShortcut);

    return () => {
      document.removeEventListener("contextmenu", preventContextMenu, {
        capture: true,
      });
      window.removeEventListener("keydown", preventBrowserShortcut);
    };
  }, []);
}
