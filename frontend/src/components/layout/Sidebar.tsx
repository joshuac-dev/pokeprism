import { NavLink } from 'react-router-dom';
import { PlusCircle, History, Brain, Shield } from 'lucide-react';

const NAV = [
  { to: '/', label: 'New Simulation', icon: PlusCircle },
  { to: '/history', label: 'History', icon: History },
  { to: '/memory', label: 'Memory', icon: Brain },
  { to: '/coverage', label: 'Coverage', icon: Shield },
];

export default function Sidebar() {
  return (
    <aside className="w-56 shrink-0 bg-app-bg-secondary border-r border-app-border flex flex-col">
      <div className="p-4 border-b border-app-border">
        <span className="text-lg font-bold text-blue-500 dark:text-blue-400 tracking-tight">PokéPrism</span>
      </div>
      <nav className="flex-1 p-3 space-y-1">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-app-primary text-ctp-base'
                  : 'text-app-text-muted hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800'
              }`
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}
