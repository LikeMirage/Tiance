import { getThemeCssVariables } from "./themeCssVariables";
import type { ThemeDefinition } from "./themeTypes";

let themeTransitionLockVersion = 0;

export function applyTheme(theme: ThemeDefinition): void {
  const root = document.documentElement;
  lockThemeTransitions(root);
  const variables = getThemeCssVariables(theme);

  root.dataset.theme = theme.id;
  root.dataset.themeMode = theme.mode;
  root.dataset.themeMermaid = theme.integrations.mermaid;
  root.dataset.themeShiki = theme.integrations.shiki;
  root.dataset.bootThemeMode = theme.mode;
  root.style.colorScheme = theme.mode;

  for (const [name, value] of Object.entries(variables)) {
    root.style.setProperty(name, value);
  }
}

function lockThemeTransitions(root: HTMLElement): void {
  const lockVersion = ++themeTransitionLockVersion;
  root.dataset.themeTransitionLock = "true";

  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(() => {
      if (lockVersion === themeTransitionLockVersion) {
        delete root.dataset.themeTransitionLock;
      }
    });
  });
}
