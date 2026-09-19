"use client";

import { useLayoutEffect, useRef } from "react";

// The engine behind every "gliding" control in the app: one highlight
// element that slides to whichever option is active, instead of each option
// painting its own background (which can only snap).
//
// Options mark themselves with data-glide-key. On every change of
// `activeKey` this measures the matching option and moves the indicator
// onto it; the CSS transition on the indicator does the gliding. It also
// re-measures when anything resizes (a label wrapping, the window
// narrowing, options loading in later), so the highlight never ends up
// sitting beside the thing it's supposed to be under.
//
// Positions are written straight onto the indicator's style rather than
// through React state: nothing else needs to re-render when it moves, and
// it lands in the same frame the new option is painted.
export function useGlide<C extends HTMLElement = HTMLDivElement>(activeKey: string | null) {
  const containerRef = useRef<C>(null);
  const indicatorRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const indicator = indicatorRef.current;
    if (!container || !indicator) return;

    const place = () => {
      const target =
        activeKey == null
          ? null
          : container.querySelector<HTMLElement>(`[data-glide-key="${CSS.escape(activeKey)}"]`);
      if (!target) {
        indicator.style.opacity = "0";
        return;
      }
      // The very first placement (on page load, or when the active option
      // only just appeared) must not animate - otherwise the highlight
      // visibly flies in from the top-left corner. Only real switches glide.
      const firstPlacement = indicator.style.opacity !== "1";
      if (firstPlacement) indicator.style.transition = "none";
      indicator.style.transform = `translate(${target.offsetLeft}px, ${target.offsetTop}px)`;
      indicator.style.width = `${target.offsetWidth}px`;
      indicator.style.height = `${target.offsetHeight}px`;
      indicator.style.opacity = "1";
      if (firstPlacement) {
        void indicator.offsetWidth; // commit the jump before transitions come back on
        indicator.style.transition = "";
      }
    };

    place();
    const observer = new ResizeObserver(place);
    observer.observe(container);
    container.querySelectorAll("[data-glide-key]").forEach((option) => observer.observe(option));
    return () => observer.disconnect();
  }, [activeKey]);

  return { containerRef, indicatorRef };
}
