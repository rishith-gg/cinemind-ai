import { create } from "zustand";

export type ToastKind = "error" | "success" | "info";
export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastState {
  toasts: Toast[];
  push: (kind: ToastKind, message: string) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (kind, message) => {
    if (get().toasts.some((t) => t.kind === kind && t.message === message)) return; // dedupe
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts, { id, kind, message }].slice(-5) }));
    if (kind !== "error") setTimeout(() => get().dismiss(id), 4000); // errors stay until dismissed
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

export const toast = {
  error: (m: string) => useToasts.getState().push("error", m),
  success: (m: string) => useToasts.getState().push("success", m),
  info: (m: string) => useToasts.getState().push("info", m),
};
