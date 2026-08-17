"use client";

import { ReactNode, useEffect } from "react";
import { createPortal } from "react-dom";

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-dv-text-primary/40 backdrop-blur-sm p-4">
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-lg rounded-dv-lg border border-dv-border-subtle bg-dv-surface shadow-dv-lg"
      >
        <div className="flex items-center justify-between border-b border-dv-border-subtle px-6 py-4">
          <h2 className="font-display text-lg font-semibold text-dv-text-primary">{title}</h2>
          <button
            onClick={onClose}
            aria-label="Schliessen"
            className="rounded-dv-pill p-1 text-dv-text-muted hover:bg-dv-surface-secondary hover:text-dv-text-primary"
          >
            ✕
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>,
    document.body
  );
}
