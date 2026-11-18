import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";

export type Tab = { id: string; label: string };

/** WAI-ARIA tabs: one tablist, arrow keys move and select, one panel shown. */
export function Tabs({
  label,
  tabs,
  active,
  onChange,
  children,
}: {
  label: string;
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
  children: (active: string) => ReactNode;
}) {
  const base = useId();
  const buttons = useRef<Record<string, HTMLButtonElement | null>>({});
  const index = Math.max(
    0,
    tabs.findIndex((t) => t.id === active),
  );

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const moves: Record<string, number> = {
      ArrowRight: (index + 1) % tabs.length,
      ArrowLeft: (index - 1 + tabs.length) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    };
    const next = moves[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const tab = tabs[next]!;
    onChange(tab.id);
    buttons.current[tab.id]?.focus();
  }

  const current = tabs[index]!;
  return (
    <div className="tabs-root">
      <div role="tablist" aria-label={label} className="tabs" onKeyDown={onKeyDown}>
        {tabs.map((tab, i) => (
          <button
            key={tab.id}
            id={`${base}-tab-${tab.id}`}
            ref={(el) => {
              buttons.current[tab.id] = el;
            }}
            role="tab"
            type="button"
            aria-selected={i === index}
            aria-controls={i === index ? `${base}-panel-${tab.id}` : undefined}
            tabIndex={i === index ? 0 : -1}
            onClick={() => onChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`${base}-panel-${current.id}`}
        aria-labelledby={`${base}-tab-${current.id}`}
        className="tabpanel"
      >
        {children(current.id)}
      </div>
    </div>
  );
}
