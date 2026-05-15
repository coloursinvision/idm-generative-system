import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/advisor", label: "ADVISOR" },
  { to: "/composer", label: "COMPOSER" },
  { to: "/effects", label: "EFFECTS" },
  { to: "/generator", label: "GENERATOR" },
  { to: "/guide/po33", label: "PO-33" },
  { to: "/guide/ep133", label: "EP-133" },
  { to: "/codegen", label: "CODEGEN" },
  { to: "/tuning", label: "TUNING" },
] as const;

export function NavBar() {
  return (
    <nav className="border-b border-surface-3 bg-surface-1">
      <div className="flex items-center justify-between px-4 py-0">
        {/* Logo */}
        <div className="flex items-center gap-3 py-3">
          <span className="font-display text-base font-bold tracking-tight text-text-primary">
            IDM
          </span>
          <span className="text-[10px] tracking-[0.3em] text-text-muted uppercase">
            GENERATIVE SYSTEM
          </span>
        </div>

        {/* Tabs */}
        <div className="flex">
          {TABS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `px-4 py-3 font-mono text-[11px] font-medium uppercase tracking-[0.15em] border-b-2 transition-colors duration-100 ${
                  isActive
                    ? "text-accent-green border-accent-green"
                    : "text-text-muted border-transparent hover:text-text-secondary"
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </div>
      </div>
    </nav>
  );
}
