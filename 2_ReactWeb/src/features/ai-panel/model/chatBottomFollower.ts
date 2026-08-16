export type ChatBottomFollower = {
  cancel: () => void;
  isActive: () => boolean;
  request: () => void;
};

type ChatBottomFollowerOptions = {
  canFollow: () => boolean;
  getScrollElement: () => HTMLDivElement | null;
};

const FOLLOW_TIME_CONSTANT_MS = 72;
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
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      scrollElement.scrollTop = targetScrollTop;
      previousFrameTime = null;
      return;
    }
    const distance = targetScrollTop - scrollElement.scrollTop;
    if (Math.abs(distance) <= SETTLED_DISTANCE_PX) {
      scrollElement.scrollTop = targetScrollTop;
      previousFrameTime = null;
      return;
    }

    const elapsed = previousFrameTime === null
      ? 1000 / 60
      : Math.min(MAX_FRAME_DELTA_MS, Math.max(0, frameTime - previousFrameTime));
    const progress = 1 - Math.exp(-elapsed / FOLLOW_TIME_CONSTANT_MS);
    scrollElement.scrollTop += distance * progress;
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
