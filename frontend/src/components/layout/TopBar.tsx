import { Sun, Moon } from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';

export default function TopBar({ title }: { title: string }) {
  const { theme, toggleTheme } = useUiStore();

  return (
    <header className="h-12 flex items-center justify-between px-6 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shrink-0">
      <h1 className="text-sm font-semibold text-slate-700 dark:text-slate-100 tracking-wide uppercase">{title}</h1>
      <button
        onClick={toggleTheme}
        className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        aria-label="Toggle theme"
      >
        {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
      </button>
    </header>
  );
}
