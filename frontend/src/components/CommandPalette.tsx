import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { classNames } from "../lib/format";
import { IconCommand, IconSearch } from "./Icons";

export type CommandItem = {
  id: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  keywords?: string;
  run: () => void;
};

// A single Ctrl/Cmd+K palette that lets clients jump anywhere or trigger a
// quick action without hunting through nav — the whole point being fewer
// clicks per task, not a prettier menu.
export function CommandPalette({ items }: { items: CommandItem[] }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isCombo = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      if (isCombo) {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActive(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((i) =>
      `${i.label} ${i.hint || ""} ${i.keywords || ""}`.toLowerCase().includes(q)
    );
  }, [items, query]);

  useEffect(() => setActive(0), [query]);

  function choose(item: CommandItem) {
    setOpen(false);
    item.run();
  }

  if (!open) {
    return (
      <button
        type="button"
        className="btn-secondary hidden gap-2 text-slate-400 sm:inline-flex"
        onClick={() => setOpen(true)}
        title="Quick actions (Ctrl+K)"
      >
        <IconSearch width={15} height={15} />
        <span className="hidden lg:inline">Quick jump…</span>
        <kbd className="ml-1 rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400 dark:border-slate-700 dark:bg-slate-800">
          Ctrl K
        </kbd>
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-[80] flex items-start justify-center bg-slate-900/40 px-4 pt-[12vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="glass w-full max-w-lg animate-pop-in overflow-hidden rounded-2xl shadow-glow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-200/60 px-4 py-3 dark:border-slate-700/60">
          <IconSearch width={16} height={16} className="shrink-0 text-brand-500" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, filtered.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter" && filtered[active]) {
                choose(filtered[active]);
              }
            }}
            placeholder="Jump to a page or run an action…"
            className="w-full bg-transparent text-sm text-slate-800 outline-none placeholder:text-slate-400 dark:text-slate-100"
          />
          <kbd className="shrink-0 rounded border border-slate-300 bg-white/60 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400 dark:border-slate-700 dark:bg-slate-800">
            Esc
          </kbd>
        </div>
        <div className="max-h-80 overflow-y-auto p-2">
          {filtered.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-slate-400">No matches.</div>
          ) : (
            filtered.map((item, i) => (
              <button
                key={item.id}
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(item)}
                className={classNames(
                  "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition",
                  i === active
                    ? "bg-brand-gradient text-white shadow-glow"
                    : "text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
                )}
              >
                {item.icon && (
                  <span className={classNames("shrink-0", i === active ? "text-white" : "text-brand-500")}>
                    {item.icon}
                  </span>
                )}
                <span className="min-w-0 flex-1 truncate font-medium">{item.label}</span>
                {item.hint && (
                  <span className={classNames("shrink-0 text-xs", i === active ? "text-white/80" : "text-slate-400")}>
                    {item.hint}
                  </span>
                )}
              </button>
            ))
          )}
        </div>
        <div className="flex items-center gap-1.5 border-t border-slate-200/60 px-4 py-2 text-[11px] text-slate-400 dark:border-slate-700/60">
          <IconCommand width={12} height={12} /> Ctrl+K to toggle · ↑↓ to navigate · Enter to select
        </div>
      </div>
    </div>
  );
}
