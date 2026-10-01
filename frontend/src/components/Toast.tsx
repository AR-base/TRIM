import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

interface Toast {
  id: number;
  text: string;
  tone: "ok" | "error";
  action?: { label: string; run: () => void };
}

type Push = (t: Omit<Toast, "id">) => void;
const Ctx = createContext<Push>(() => {});

export function useToast(): Push {
  return useContext(Ctx);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const push = useCallback<Push>((t) => {
    const id = next.current++;
    setToasts((all) => [...all.slice(-2), { ...t, id }]);
  }, []);
  const close = (id: number) => setToasts((all) => all.filter((t) => t.id !== id));
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onClose={() => close(t.id)} />
        ))}
      </div>
    </Ctx.Provider>
  );
}

function ToastItem({ toast, onClose }: { toast: Toast; onClose: () => void }) {
  useEffect(() => {
    const h = window.setTimeout(onClose, toast.action ? 9000 : 5000);
    return () => window.clearTimeout(h);
  }, [toast, onClose]);
  return (
    <div className={`toast toast--${toast.tone}`}>
      <span>{toast.text}</span>
      {toast.action && (
        <button
          className="toast__action"
          onClick={() => {
            toast.action!.run();
            onClose();
          }}
        >
          {toast.action.label}
        </button>
      )}
      <button className="toast__close" aria-label="Dismiss" onClick={onClose}>
        ×
      </button>
    </div>
  );
}
