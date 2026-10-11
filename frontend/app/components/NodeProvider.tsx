"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { NODES } from "@/lib/engine";

const KEY = "gridzero-node";

const NodeContext = createContext<{ node: string; setNode: (n: string) => void }>({
  node: "A",
  setNode: () => {},
});

export function NodeProvider({ children }: { children: ReactNode }) {
  const [node, setNodeState] = useState("A");

  useEffect(() => {
    const saved = window.localStorage.getItem(KEY);
    if (saved && (NODES as readonly string[]).includes(saved)) setNodeState(saved);
  }, []);

  function setNode(next: string) {
    setNodeState(next);
    window.localStorage.setItem(KEY, next);
  }

  return <NodeContext.Provider value={{ node, setNode }}>{children}</NodeContext.Provider>;
}

export function useNode() {
  return useContext(NodeContext);
}
