import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X, AlertTriangle } from 'lucide-react';
import { cn } from '../../lib/utils';
import { Button } from './button';

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  description?: React.ReactNode;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  closeOnBackdrop?: boolean;
}

const sizes = { sm: 'max-w-md', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' };

export const Modal: React.FC<ModalProps> = ({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  closeOnBackdrop = true,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  // Keep the latest onClose without making it an effect dependency: parents pass an
  // inline arrow (new identity every render), and re-running the effect on each
  // keystroke re-scheduled the "focus first element" timeout — stealing focus from
  // whatever the user was typing into (the Add Asset modal "closing itself" bug).
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current();
    };
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // focus first focusable element — ONCE per open, never on parent re-renders
    const t = setTimeout(() => {
      const el = panelRef.current?.querySelector<HTMLElement>(
        'input, select, textarea, button:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      el?.focus();
    }, 30);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
      clearTimeout(t);
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === 'string' ? title : 'Dialog'}
    >
      <div
        className="absolute inset-0 bg-ink/30 backdrop-blur-[2px] animate-fade-in"
        onClick={closeOnBackdrop ? onClose : undefined}
      />
      <div
        ref={panelRef}
        className={cn(
          'relative w-full animate-scale-in rounded-2xl border border-line bg-surface shadow-modal',
          sizes[size]
        )}
      >
        {(title || description) && (
          <div className="flex items-start justify-between gap-4 border-b border-line-soft px-6 py-4">
            <div>
              {title && <h2 className="text-base font-bold text-ink">{title}</h2>}
              {description && <p className="mt-0.5 text-[13px] text-muted">{description}</p>}
            </div>
            <button
              onClick={onClose}
              aria-label="Close dialog"
              className="rounded-lg p-1.5 text-faint transition-colors hover:bg-line-soft hover:text-ink focus-ring"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}
        {children && <div className="max-h-[70vh] overflow-y-auto scrollbar-thin px-6 py-5">{children}</div>}
        {footer && (
          <div className="flex items-center justify-end gap-2.5 border-t border-line-soft px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};

export interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  loading?: boolean;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  loading = false,
}) => (
  <Modal
    open={open}
    onClose={onClose}
    size="sm"
    title={
      <span className="flex items-center gap-2">
        {destructive && (
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-danger-100">
            <AlertTriangle className="h-4 w-4 text-danger" />
          </span>
        )}
        {title}
      </span>
    }
    footer={
      <>
        <Button variant="outline" onClick={onClose} disabled={loading}>
          {cancelLabel}
        </Button>
        <Button
          variant={destructive ? 'danger' : 'primary'}
          onClick={() => void onConfirm()}
          loading={loading}
        >
          {confirmLabel}
        </Button>
      </>
    }
  >
    <div className="text-sm text-muted">{message}</div>
  </Modal>
);

export default Modal;
