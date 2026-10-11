"use client";

import { NODES } from "@/lib/engine";
import { useNode } from "@/lib/useNode";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/statement", label: "Statement" },
  { href: "/live", label: "Live" },
  { href: "/compare", label: "Compare" },
];

export default function SiteNav({ active }: { active?: string }) {
  const { node, setNode } = useNode();

  return (
    <nav className="pointer-events-none fixed top-5 left-1/2 z-30 w-full max-w-[min(94vw,56rem)] -translate-x-1/2 px-3">
      <div
        className="pointer-events-auto flex items-center justify-between gap-3 rounded-full px-5 py-2 shadow-[0_8px_28px_rgba(40,124,115,0.12)] ring-1 ring-white/50"
        style={{
          background:
            "linear-gradient(135deg, #dcebdd 0%, #c8dec9 55%, #b8d8d0 100%)",
        }}
      >
        <a
          href="/"
          className="rounded-full px-4 py-2 font-display text-sm text-dark-teal transition duration-300 hover:bg-white/50"
        >
          GridZero
        </a>
        <div className="hidden items-center gap-0.5 sm:flex">
          {links.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className={
                active === link.href
                  ? "rounded-full bg-white/70 px-3.5 py-2 text-sm text-dark-teal"
                  : "rounded-full px-3.5 py-2 text-sm text-sage-text transition duration-300 hover:bg-white/55 hover:text-dark-teal"
              }
            >
              {link.label}
            </a>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-dark-teal">
          <span className="hidden sm:inline">Home</span>
          <select
            value={node}
            onChange={(e) => setNode(e.target.value)}
            className="rounded-full bg-white/80 px-3 py-1.5 text-sm text-dark-teal outline-none"
            aria-label="Home node"
          >
            {NODES.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
      </div>
    </nav>
  );
}
