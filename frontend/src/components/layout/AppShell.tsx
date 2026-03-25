import type { ReactNode } from "react";
import { NavBar } from "./NavBar";
import { StatusBar } from "./StatusBar";

interface Props {
  children: ReactNode;
}

export function AppShell({ children }: Props) {
  return (
    <div className="h-screen flex flex-col">
      <NavBar />
      <main className="flex-1 overflow-auto p-6">{children}</main>
      <StatusBar />
    </div>
  );
}
