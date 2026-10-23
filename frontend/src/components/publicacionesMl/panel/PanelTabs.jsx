import { useEffect, useId, useRef } from 'react';
import styles from './panel.module.css';

/**
 * A panel's tab strip and the open tab's body, as a tablist: Arrow keys / Home / End move between tabs and the
 * strip keeps the open one in view. Which tabs exist and which one is open belong to the caller.
 *
 * @param {object} props
 * @param {Array<{ key: string, label: string }>} props.tabs The tabs to draw, in order.
 * @param {string} props.activeKey The open tab's key (one of `tabs`).
 * @param {(key: string) => void} props.onTabChange
 * @param {string} props.label The tablist's accessible name.
 * @param {import('react').ReactNode} props.children The open tab's body.
 */
export default function PanelTabs({ tabs, activeKey, onTabChange, label, children }) {
  const tabRefs = useRef({});
  const stripRef = useRef(null);
  const panelId = useId();

  // The strip scrolls sideways when the tabs outgrow a narrow panel: keep the
  // open one in view (the URL can open a tab that sits past the edge). Only the
  // strip moves -- `scrollIntoView` could scroll the page or the panel as well.
  useEffect(() => {
    const strip = stripRef.current;
    const tabNode = tabRefs.current[activeKey];
    if (!strip || !tabNode) return;
    const start = tabNode.offsetLeft;
    const end = start + tabNode.offsetWidth;
    if (start < strip.scrollLeft) strip.scrollLeft = start;
    else if (end > strip.scrollLeft + strip.clientWidth) strip.scrollLeft = end - strip.clientWidth;
  }, [activeKey]);

  // Arrow keys / Home / End move between tabs, as a tablist does.
  const handleTabKeyDown = (event) => {
    const index = tabs.findIndex((entry) => entry.key === activeKey);
    let next = null;
    if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
    else if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
    else if (event.key === 'Home') next = tabs[0];
    else if (event.key === 'End') next = tabs[tabs.length - 1];
    if (!next) return;
    event.preventDefault();
    onTabChange(next.key);
    tabRefs.current[next.key]?.focus();
  };

  return (
    <>
      <div ref={stripRef} className={styles.tabs} role="tablist" aria-label={label} onKeyDown={handleTabKeyDown}>
        {tabs.map((entry) => (
          <button
            key={entry.key}
            ref={(node) => {
              tabRefs.current[entry.key] = node;
            }}
            type="button"
            role="tab"
            id={`${panelId}-tab-${entry.key}`}
            aria-selected={entry.key === activeKey}
            aria-controls={`${panelId}-tabpanel`}
            tabIndex={entry.key === activeKey ? 0 : -1}
            className={styles.tab}
            onClick={() => onTabChange(entry.key)}
          >
            {entry.label}
          </button>
        ))}
      </div>
      <div className={styles.body} role="tabpanel" id={`${panelId}-tabpanel`} aria-labelledby={`${panelId}-tab-${activeKey}`}>
        {children}
      </div>
    </>
  );
}
