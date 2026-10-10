// Change notifications are display invalidations, not persisted facts. Use a
// WebSocket so idle subscriptions cannot occupy the browser's HTTP/1 slots.
// Retry only while subscribed; consumers reconcile after a reconnection.
export const EVENT_SOCKET_RECONNECT_DELAY_MS = 3_000;

export function watchEventSocket(
  url: string,
  handlers: {
    onMessage: (data: string) => void;
    onDisconnect?: () => void;
    onReconnect?: () => void;
  },
) {
  const socketUrl = new URL(url);
  socketUrl.protocol = socketUrl.protocol === "https:" ? "wss:" : "ws:";
  let stopped = false;
  let hasConnected = false;
  let socket: WebSocket | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const connect = () => {
    if (stopped) return;
    const current = new WebSocket(socketUrl.toString());
    socket = current;
    current.onopen = () => {
      if (stopped || current !== socket) return;
      const reconnected = hasConnected;
      hasConnected = true;
      if (reconnected) handlers.onReconnect?.();
    };
    current.onmessage = (event: MessageEvent<string>) => {
      if (!stopped && current === socket) handlers.onMessage(event.data);
    };
    current.onclose = () => {
      if (stopped || current !== socket) return;
      socket = null;
      retryTimer = setTimeout(() => {
        retryTimer = null;
        connect();
      }, EVENT_SOCKET_RECONNECT_DELAY_MS);
      handlers.onDisconnect?.();
    };
  };
  connect();

  return () => {
    stopped = true;
    if (retryTimer !== null) clearTimeout(retryTimer);
    const current = socket;
    socket = null;
    current?.close();
  };
}
