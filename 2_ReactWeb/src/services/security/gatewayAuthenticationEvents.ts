type GatewayAuthenticationRequiredListener = () => void;

const authenticationRequiredListeners = new Set<GatewayAuthenticationRequiredListener>();

export function notifyGatewayAuthenticationRequired() {
  authenticationRequiredListeners.forEach((listener) => listener());
}

export function subscribeGatewayAuthenticationRequired(
  listener: GatewayAuthenticationRequiredListener,
) {
  authenticationRequiredListeners.add(listener);
  return () => authenticationRequiredListeners.delete(listener);
}
