export function MinimizeIcon() {
  return (
    <svg
      className="window-titlebar__icon"
      viewBox="0 0 10 10"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M1.5 5.5H8.5" />
    </svg>
  );
}

export function MaximizeIcon() {
  return (
    <svg
      className="window-titlebar__icon"
      viewBox="0 0 10 10"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="1.5" y="1.5" width="7" height="7" rx="0.6" />
    </svg>
  );
}

export function RestoreIcon() {
  return (
    <svg
      className="window-titlebar__icon"
      viewBox="0 0 12 12"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M4 1.75H9.25V7" />
      <path d="M2.75 4H8V10.25H2.75Z" />
      <path d="M4 1.75V4H9.25" />
    </svg>
  );
}

export function CloseIcon() {
  return (
    <svg
      className="window-titlebar__icon"
      viewBox="0 0 10 10"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M2 2L8 8" />
      <path d="M8 2L2 8" />
    </svg>
  );
}
