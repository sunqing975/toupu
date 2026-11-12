import { createContext, useCallback, useContext, useState, type ReactNode } from "react"
import { CircleAlert, CircleCheck } from "lucide-react"

type ToastKind = "success" | "error"
type ToastItem = { id: number; kind: ToastKind; message: string }

const ToastContext = createContext<(kind: ToastKind, message: string) => void>(() => {})

export function useToast() {
  return useContext(ToastContext)
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const push = useCallback((kind: ToastKind, message: string) => {
    const id = Date.now() + Math.random()
    setToasts((items) => [...items, { id, kind, message }])
    window.setTimeout(() => setToasts((items) => items.filter((t) => t.id !== id)), 5000)
  }, [])

  return (
    <ToastContext value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast--${t.kind}`}>
            {t.kind === "success" ? (
              <CircleCheck size={16} aria-hidden />
            ) : (
              <CircleAlert size={16} aria-hidden />
            )}
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext>
  )
}
