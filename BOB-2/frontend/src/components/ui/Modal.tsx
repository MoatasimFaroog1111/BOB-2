"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

interface ModalProps {
  onClose: () => void;
  children: (titleId: string) => ReactNode;
  panelClassName?: string;
  closeOnBackdropClick?: boolean;
}

/**
 * Accessible dialog shell: role="dialog"/aria-modal, Escape-to-close, and
 * initial focus on the panel. Callers render their own header/body/footer
 * via the children render-prop and attach `titleId` to their heading.
 */
export function Modal({ onClose, children, panelClassName, closeOnBackdropClick = true }: ModalProps) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-6 select-none"
      onMouseDown={(event) => {
        if (closeOnBackdropClick && event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={panelClassName}
      >
        {children(titleId)}
      </div>
    </div>
  );
}
