import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api";

interface State<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
}

/** Loads data, keeps the last good value while refreshing, and ignores stale responses. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true });
  const seq = useRef(0);
  const refresh = useCallback(async () => {
    const id = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    try {
      const data = await load();
      if (id === seq.current) setState({ data, error: null, loading: false });
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, "unknown", "Something went wrong.");
      if (id === seq.current) setState((s) => ({ ...s, error: err, loading: false }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  return { ...state, refresh };
}
