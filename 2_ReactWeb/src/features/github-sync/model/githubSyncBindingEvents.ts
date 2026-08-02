import type {
  GithubSyncBinding,
  GithubSyncCollection,
} from "../../../services/github/githubSyncApi";

const EVENT_NAME = "tiance:github-sync-binding-changed";

type BindingChange = {
  binding: GithubSyncBinding | null;
  collection: GithubSyncCollection;
};

export function dispatchGithubSyncBindingChanged(change: BindingChange) {
  window.dispatchEvent(new CustomEvent<BindingChange>(EVENT_NAME, { detail: change }));
}

export function subscribeGithubSyncBindingChanged(
  listener: (change: BindingChange) => void,
) {
  const handle = (event: Event) => listener((event as CustomEvent<BindingChange>).detail);
  window.addEventListener(EVENT_NAME, handle);
  return () => window.removeEventListener(EVENT_NAME, handle);
}
