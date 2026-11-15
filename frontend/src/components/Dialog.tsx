import { useEffect, useRef, type ReactNode } from "react"
import { X } from "lucide-react"

// 原生 <dialog>：自带焦点困住与 Esc 关闭。
export function Dialog({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  // Native close events are queued. A prop-driven close (e.g. market switch)
  // must not propagate back as a user dismissal of the newly opened dialog.
  const desiredOpen = useRef(open)
  desiredOpen.current = open

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className="dialog"
      onClose={() => {
        if (desiredOpen.current && !ref.current?.open) onClose()
      }}
      onClick={(e) => {
        if (e.target === ref.current) ref.current.close()
      }}
    >
      <div className="dialog__head">
        <span>{title}</span>
        <button className="btn btn--ghost" aria-label="关闭" onClick={() => ref.current?.close()}>
          <X size={16} aria-hidden />
        </button>
      </div>
      <div className="dialog__body">{children}</div>
    </dialog>
  )
}
