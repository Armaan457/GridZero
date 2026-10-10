"use client";

import { useEffect, useRef, useState } from "react";

const PATH_A = "M 318 78 H 390 V 188 H 478";
const PATH_B = "M 214 248 V 348 H 458";

type Roof = "slate" | "peach" | "sage";

const roofFill: Record<Roof, { a: string; b: string; chim: string; stroke: string }> = {
  slate: { a: "#a7b0bc", b: "#7f8896", chim: "#8b95a3", stroke: "#6d7684" },
  peach: { a: "#f0b48e", b: "#d8875e", chim: "#e39a72", stroke: "#c46f48" },
  sage: { a: "#8fbe9c", b: "#5e916e", chim: "#7aa88a", stroke: "#4a7358" },
};

function House3D({
  x,
  y,
  roof,
  scale = 1,
}: {
  x: number;
  y: number;
  roof: Roof;
  scale?: number;
}) {
  const c = roofFill[roof];
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`}>
      <ellipse cx="46" cy="86" rx="44" ry="14" fill="#cfe8b8" stroke="#9cc48a" strokeWidth="1.6" />
      <ellipse cx="46" cy="84" rx="38" ry="10" fill="#d9efc4" stroke="#b4d8a0" strokeWidth="1" />
      <circle cx="10" cy="78" r="7" fill="#6fbe72" stroke="#4d8f52" strokeWidth="1.2" />
      <circle cx="8" cy="74" r="5.5" fill="#86cc80" stroke="#5ea35a" strokeWidth="1" />
      <rect x="9" y="80" width="2" height="6" rx="1" fill="#8a6840" stroke="#6a4e2e" strokeWidth="0.6" />
      <circle cx="82" cy="76" r="8" fill="#5eaa62" stroke="#3f7d44" strokeWidth="1.2" />
      <circle cx="86" cy="72" r="5" fill="#79c478" stroke="#4d8f52" strokeWidth="1" />
      <rect x="81" y="80" width="2.2" height="7" rx="1" fill="#8a6840" stroke="#6a4e2e" strokeWidth="0.6" />

      <path
        d="M18 70 L18 42 Q18 34 28 34 L64 34 Q74 34 74 42 L74 70 Z"
        fill="#fff8f0"
        stroke="#c9bba8"
        strokeWidth="1.8"
      />
      <path d="M18 70 L18 42 Q18 36 24 36 L24 70 Z" fill="#efe6d8" stroke="#d4c8b6" strokeWidth="0.8" />
      <rect x="28" y="44" width="9" height="9" rx="2" fill="#ffe08c" stroke="#d4b24a" strokeWidth="1.2" />
      <rect x="55" y="44" width="9" height="9" rx="2" fill="#ffe08c" stroke="#d4b24a" strokeWidth="1.2" />
      <rect x="41" y="54" width="10" height="16" rx="2" fill="#d2a57a" stroke="#a87b52" strokeWidth="1.2" />

      <path d="M16 40 L46 16 L76 40 L64 36 L28 36 Z" fill={c.a} stroke={c.stroke} strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M16 40 L46 16 L28 36 Z" fill={c.b} stroke={c.stroke} strokeWidth="1.2" strokeLinejoin="round" />
      <rect x="58" y="14" width="6" height="14" rx="1.5" fill={c.chim} stroke={c.stroke} strokeWidth="1.2" />
      <rect x="56.5" y="12" width="9" height="4" rx="1.2" fill={c.b} stroke={c.stroke} strokeWidth="1" />
    </g>
  );
}

export default function NeighborhoodFlow() {
  const pathARef = useRef<SVGPathElement>(null);
  const pathBRef = useRef<SVGPathElement>(null);
  const [progress, setProgress] = useState(0);
  const [beadsA, setBeadsA] = useState<{ x: number; y: number }[]>([]);
  const [beadsB, setBeadsB] = useState<{ x: number; y: number }[]>([]);

  useEffect(() => {
    const root = document.getElementById("hero-pin");
    if (!root) return;

    const onScroll = () => {
      const rect = root.getBoundingClientRect();
      const travel = Math.max(1, root.offsetHeight - window.innerHeight);
      const next = Math.min(1, Math.max(0, -rect.top / travel));
      setProgress(next);

      const pa = pathARef.current;
      const pb = pathBRef.current;
      if (pa) {
        const len = pa.getTotalLength();
        setBeadsA(
          [0.3, 0.58, 0.84].filter((s) => next > s).map((s) => pa.getPointAtLength(len * s)),
        );
      }
      if (pb) {
        const len = pb.getTotalLength();
        setBeadsB(
          [0.25, 0.5, 0.78].filter((s) => next > s).map((s) => pb.getPointAtLength(len * s)),
        );
      }
    };

    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);

  const draw = progress;

  return (
    <div className="relative w-full">
      <svg
        viewBox="20 0 720 470"
        className="h-auto w-full"
        role="img"
        aria-label="Neighborhood. Scroll to send energy along both pipes at once."
      >
        <defs>
          <filter id="gold-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <path
          d={PATH_A}
          fill="none"
          stroke="#f6e7b4"
          strokeWidth="11"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d={PATH_B}
          fill="none"
          stroke="#f6e7b4"
          strokeWidth="11"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          ref={pathARef}
          d={PATH_A}
          fill="none"
          stroke="#ffd24a"
          strokeWidth="7.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          filter="url(#gold-glow)"
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - draw}
        />
        <path
          ref={pathBRef}
          d={PATH_B}
          fill="none"
          stroke="#ffd24a"
          strokeWidth="7.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          filter="url(#gold-glow)"
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - draw}
        />

        {beadsA.map((p, i) => (
          <circle key={`a-${i}`} cx={p.x} cy={p.y} r="6" fill="#fff4b0" stroke="#f5c84c" strokeWidth="2" filter="url(#gold-glow)" />
        ))}
        {beadsB.map((p, i) => (
          <circle key={`b-${i}`} cx={p.x} cy={p.y} r="6" fill="#fff4b0" stroke="#f5c84c" strokeWidth="2" filter="url(#gold-glow)" />
        ))}

        {draw > 0.96 && (
          <>
            <polygon points="492,188 474,179 474,197" fill="#ffd24a" filter="url(#gold-glow)" />
            <polygon points="472,348 454,339 454,357" fill="#ffd24a" filter="url(#gold-glow)" />
          </>
        )}

        <House3D x={50} y={18} roof="slate" />
        <House3D x={230} y={8} roof="peach" />
        <House3D x={150} y={178} roof="slate" />
        <House3D x={40} y={330} roof="peach" />
        <House3D x={480} y={148} roof="sage" />
        <House3D x={610} y={100} roof="peach" />
        <House3D x={620} y={250} roof="sage" />
        <House3D x={460} y={318} roof="peach" />
      </svg>
    </div>
  );
}
