import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";


type MarketIndex = { source: string };
type MarketSettings<Filters> = { filters: Filters; source: string };

type OnlineMarketSourceOptions<Index extends MarketIndex, Filters> = {
  connectSource: (source: string, signal: AbortSignal) => Promise<Index>;
  defaultSource: string;
  emptyFilters: Filters;
  indexErrorMessage: string;
  isActive: boolean;
  loadIndex: (signal: AbortSignal) => Promise<Index>;
  loadSettings: (signal: AbortSignal) => Promise<MarketSettings<Filters>>;
  resetSource?: (signal: AbortSignal) => Promise<Index>;
  saveFilters: (filters: Filters, signal: AbortSignal) => Promise<unknown>;
  settingsErrorMessage: string;
  sourceKey?: string;
};

export type OnlineMarketSourceState<Index extends MarketIndex, Filters> = {
  connect: () => Promise<boolean>;
  connectTo: (source: string) => Promise<boolean>;
  draftSource: string;
  error: string | null;
  filters: Filters;
  index: Index | null;
  isLoading: boolean;
  refresh: () => Promise<boolean>;
  reset: () => Promise<boolean>;
  setDraftSource: Dispatch<SetStateAction<string>>;
  setFilters: Dispatch<SetStateAction<Filters>>;
  setIndex: Dispatch<SetStateAction<Index | null>>;
  source: string;
};

export function useOnlineMarketSource<Index extends MarketIndex, Filters>(
  options: OnlineMarketSourceOptions<Index, Filters>,
): OnlineMarketSourceState<Index, Filters> {
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const sourceKey = options.sourceKey ?? options.defaultSource;
  const [draftSource, setDraftSource] = useState(options.defaultSource);
  const [source, setSource] = useState(options.defaultSource);
  const sourceRef = useRef(options.defaultSource);
  const [filters, setFilters] = useState<Filters>(options.emptyFilters);
  const [index, setIndex] = useState<Index | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const loadControllerRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const loadedSourceKeyRef = useRef<string | null>(null);
  const filtersReadySourceKeyRef = useRef<string | null>(null);

  const runLoad = useCallback(async (
    request: (signal: AbortSignal) => Promise<Index>,
  ) => {
    const requestId = ++requestIdRef.current;
    loadControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    setIsLoading(true);
    setError(null);
    try {
      const result = await request(controller.signal);
      if (controller.signal.aborted || requestId !== requestIdRef.current) return false;
      setIndex(result);
      setSource(result.source);
      sourceRef.current = result.source;
      setDraftSource(result.source);
      return true;
    } catch (loadError) {
      if (controller.signal.aborted || requestId !== requestIdRef.current) return false;
      setError(
        loadError instanceof Error
          ? loadError.message
          : optionsRef.current.indexErrorMessage,
      );
      return false;
    } finally {
      if (requestId === requestIdRef.current) {
        loadControllerRef.current = null;
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!options.isActive || loadedSourceKeyRef.current === sourceKey) return;
    loadedSourceKeyRef.current = null;
    filtersReadySourceKeyRef.current = null;
    setIndex(null);
    setError(null);
    const controller = new AbortController();
    void (async () => {
      try {
        const settings = await optionsRef.current.loadSettings(controller.signal);
        if (controller.signal.aborted) return;
        setSource(settings.source);
        sourceRef.current = settings.source;
        setDraftSource(settings.source);
        setFilters(settings.filters);
        filtersReadySourceKeyRef.current = sourceKey;
        if (await runLoad((signal) => optionsRef.current.loadIndex(signal))) {
          loadedSourceKeyRef.current = sourceKey;
        }
      } catch (loadError) {
        if (!controller.signal.aborted) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : optionsRef.current.settingsErrorMessage,
          );
        }
      }
    })();
    return () => {
      controller.abort();
      loadControllerRef.current?.abort();
    };
  }, [options.isActive, runLoad, sourceKey]);

  useEffect(() => {
    if (filtersReadySourceKeyRef.current !== sourceKey) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void optionsRef.current.saveFilters(filters, controller.signal).catch(() => undefined);
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [filters, sourceKey]);

  useEffect(() => () => loadControllerRef.current?.abort(), []);

  const connect = useCallback(
    () => runLoad((signal) => optionsRef.current.connectSource(draftSource, signal)),
    [draftSource, runLoad, sourceKey],
  );
  const connectTo = useCallback(async (nextSource: string) => {
    setDraftSource(nextSource);
    const connected = await runLoad(
      (signal) => optionsRef.current.connectSource(nextSource, signal),
    );
    if (!connected) setDraftSource(sourceRef.current);
    return connected;
  }, [runLoad, sourceKey]);
  const refresh = useCallback(
    () => runLoad((signal) => optionsRef.current.loadIndex(signal)),
    [runLoad, sourceKey],
  );
  const reset = useCallback(() => {
    setDraftSource(optionsRef.current.defaultSource);
    return runLoad((signal) => (
      optionsRef.current.resetSource
        ? optionsRef.current.resetSource(signal)
        : optionsRef.current.connectSource(optionsRef.current.defaultSource, signal)
    ));
  }, [runLoad, sourceKey]);

  return {
    connect,
    connectTo,
    draftSource,
    error,
    filters,
    index,
    isLoading,
    refresh,
    reset,
    setDraftSource,
    setFilters,
    setIndex,
    source,
  };
}
