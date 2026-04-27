import { create } from 'zustand';

type Theme = 'dark' | 'light';

interface UiState {
  theme: Theme;
  toggleTheme: () => void;
}

const stored = (localStorage.getItem('theme') as Theme | null) ?? 'dark';

export const useUiStore = create<UiState>((set) => ({
  theme: stored,
  toggleTheme: () =>
    set((state) => {
      const next = state.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('theme', next);
      if (next === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
      return { theme: next };
    }),
}));
