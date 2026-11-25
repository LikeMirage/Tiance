export type ChatBottomFollower = {
  cancel: () => void;
  isActive: () => boolean;
  request: () => void;
};

type ChatBottomFollowerOptions = {
  canFollow: () => boolean;
  getScrollElement: () => HTMLDivElement | null;
};

const FOLLOW_TIME_CONSTANT_MS = 52;
const MAX_FRAME_DELTA_MS = 34;
const SETTLED_DISTANCE_PX = 0.35;

/**
 * Follows a growing chat bottom with one continuous animation. New content only
 * moves the target; it never starts another competing smooth-scroll operation.
 */
export function createChatBottomFollower({
  canFollow,
  getScrollElement,
}: ChatBottomFollowerOptions): ChatBottomFollower {
  let frameId: number | null = null;
  let previousFrameTime: number | null = null;
  let position = 0;
  let velocity = 0;
  let lastAppliedTop = 0;

  const cancel = () => {
    if (frameId !== null) {
      window.cancelAnimationFrame(frameId);
      frameId = null;
    }
    previousFrameTime = null;
  };

  const step = (frameTime: number) => {
    frameId = null;
    const scrollElement = getScrollElement();
    if (!scrollElement || !canFollow()) {
      previousFrameTime = null;
      return;
    }

    const targetScrollTop = Math.max(
      0,
      scrollElement.scrollHeight - scrollElement.clientHeight,
    );
    const actualTop = scrollElement.scrollTop;
    if (previousFrameTime === null || actualTop !== lastAppliedTop) {
      // Pick up external changes such as a virtual list preserving its anchor.
      position = actualTop;
      velocity = 0;
    }
    const distance = targetScrollTop - position;
    if (distance <= SETTLED_DISTANCE_PX) {
      scrollElement.scrollTop = targetScrollTop;
      previousFrameTime = null;
      return;
    }

    const elapsed = previousFrameTime === null
      ? 1000 / 60
      : Math.min(MAX_FRAME_DELTA_MS, Math.max(0, frameTime - previousFrameTime));
    // Critically damped motion keeps the current speed when the next line arrives.
    // Accumulate subpixels here: scrollTop can round each write to a device pixel.
    const decay = Math.exp(-elapsed / FOLLOW_TIME_CONSTANT_MS);
    const slope = distance / FOLLOW_TIME_CONSTANT_MS - velocity;
    position = targetScrollTop - Math.max(0, (distance + slope * elapsed) * decay);
    velocity = (velocity + slope * elapsed / FOLLOW_TIME_CONSTANT_MS) * decay;
    scrollElement.scrollTop = position;
    lastAppliedTop = scrollElement.scrollTop;
    previousFrameTime = frameTime;
    frameId = window.requestAnimationFrame(step);
  };

  return {
    cancel,
    isActive: () => frameId !== null,
    request: () => {
      if (frameId !== null || !canFollow()) return;
      frameId = window.requestAnimationFrame(step);
    },
  };
}
