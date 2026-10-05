import { create } from "zustand";

const KEY = "cinemind.currentProject";

function load(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null; // storage can be blocked; the app works without it
  }
}

interface CurrentProject {
  id: string | null;
  set: (id: string | null) => void;
}

export const useCurrentProject = create<CurrentProject>((set) => ({
  id: load(),
  set: (id) => {
    try {
      if (id) localStorage.setItem(KEY, id);
      else localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    set({ id });
  },
}));
