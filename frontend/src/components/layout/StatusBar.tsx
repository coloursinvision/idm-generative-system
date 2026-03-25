import { useEffect, useState } from "react";
import { getHealth } from "../../api/client";

export function StatusBar() {
  const [status, setStatus] = useState<"ok" | "error" | "loading">("loading");
  const [version, setVersion] = useState("");

  useEffect(() => {
    let mounted = true;

    const check = async () => {
      try {
        const data = await getHealth();
        if (mounted) {
          setStatus(data.status === "ok" ? "ok" : "error");
          setVersion(data.version);
        }
      } catch {
        if (mounted) setStatus("error");
      }
    };

    check();
    const interval = setInterval(check, 30_000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const dot =
    status === "ok"
      ? "bg-accent-green"
      : status === "error"
        ? "bg-accent-red"
        : "bg-text-muted animate-pulse";

  return (
    <footer className="border-t border-surface-3 bg-surface-1 px-4 py-1.5 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <div className={`w-1.5 h-1.5 ${dot}`} />
        <span className="text-[10px] tracking-[0.15em] text-text-muted uppercase">
          {status === "ok"
            ? "API CONNECTED"
            : status === "error"
              ? "API OFFLINE"
              : "CONNECTING"}
        </span>
      </div>
      {version && (
        <span className="text-[10px] tracking-[0.15em] text-text-muted">
          v{version}
        </span>
      )}
    </footer>
  );
}
