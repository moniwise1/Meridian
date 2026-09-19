"use client";

import Link from "next/link";
import { useGlide } from "@/components/glide/useGlide";

export type GlideNavItem = { href: string; label: string };

// A vertical menu whose highlight glides from the page you were on to the
// page you picked. It works because the menus that use it live in a layout
// that stays mounted across navigation (app/layout.tsx for the app,
// app/platform/layout.tsx for the staff console), so the highlight
// survives the page change and can travel instead of reappearing.
//
// Uses the soft ease: this highlight can cross most of the screen, and the
// springy overshoot that suits a short toggle would read as a bounce here.
export default function GlideNav({
  items,
  activeHref,
}: {
  items: GlideNavItem[];
  activeHref: string | null;
}) {
  const { containerRef, indicatorRef } = useGlide<HTMLElement>(activeHref);

  return (
    <nav ref={containerRef} className="relative flex flex-col gap-1">
      <span
        ref={indicatorRef}
        aria-hidden
        className="pointer-events-none absolute left-0 top-0 opacity-0 rounded-[3px] bg-teal-deep shadow-[0_4px_12px_rgba(18,63,61,0.22)] transition-[transform,width,height,opacity] duration-[480ms] ease-glide-soft motion-reduce:transition-none"
      />
      {items.map((item) => {
        const active = item.href === activeHref;
        return (
          <Link
            key={item.href}
            href={item.href}
            data-glide-key={item.href}
            aria-current={active ? "page" : undefined}
            className={`relative z-10 text-[13.5px] px-2.5 py-1.5 rounded-[3px] transition-colors duration-200 ${
              // White only once the highlight has (mostly) arrived underneath.
              active ? "text-white [transition-delay:140ms]" : "text-ink-soft hover:text-ink hover:bg-paper"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
