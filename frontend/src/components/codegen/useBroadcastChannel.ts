/**
 * components/codegen/useBroadcastChannel.ts
 *
 * Generic typed React hook for BroadcastChannel communication.
 * Used to synchronise state between the main app and the codegen
 * popout window without WebSocket or server involvement.
 *
 * Features:
 *   - Type-safe messages via generic parameter
 *   - Automatic cleanup on unmount
 *   - Connection status tracking via heartbeat
 *   - Graceful degradation (no-op if BroadcastChannel unsupported)
 *
 * Usage:
 *   const { lastMessage, postMessage, isConnected } =
 *     useBroadcastChannel<CodegenBroadcastMessage>("idm-codegen");
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** Heartbeat interval in milliseconds. */
const HEARTBEAT_INTERVAL_MS = 2000;

/** Connection is considered lost after this many missed heartbeats. */
const HEARTBEAT_TIMEOUT_MS = 5000;

interface UseBroadcastChannelReturn<T> {
  /** Most recent message received, or null if none yet. */
  lastMessage: T | null;
  /** Send a typed message to all other tabs/windows on this channel. */
  postMessage: (message: T) => void;
  /**
   * Whether a remote peer is alive (based on heartbeat).
   * Useful for the main app to know if the popout window is open.
   */
  isConnected: boolean;
}

/**
 * Hook for typed BroadcastChannel communication.
 *
 * @param channelName - Channel identifier (must match in both windows).
 * @param sendHeartbeat - If true, this instance sends periodic heartbeats.
 *                        Typically enabled in the popout, disabled in main.
 */
export function useBroadcastChannel<T extends { type: string }>(
  channelName: string,
  sendHeartbeat = false,
): UseBroadcastChannelReturn<T> {
  const [lastMessage, setLastMessage] = useState<T | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  const channelRef = useRef<BroadcastChannel | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval>>();
  const timeoutTimerRef = useRef<ReturnType<typeof setTimeout>>();

  // Stable postMessage callback
  const postMessage = useCallback(
    (message: T) => {
      try {
        channelRef.current?.postMessage(message);
      } catch {
        // Channel may be closed — silent fail
      }
    },
    [],
  );

  useEffect(() => {
    // BroadcastChannel may not be available in all environments
    if (typeof BroadcastChannel === "undefined") {
      return;
    }

    const channel = new BroadcastChannel(channelName);
    channelRef.current = channel;

    // Reset connection timeout on any heartbeat received
    const resetTimeout = () => {
      if (timeoutTimerRef.current) clearTimeout(timeoutTimerRef.current);
      setIsConnected(true);
      timeoutTimerRef.current = setTimeout(() => {
        setIsConnected(false);
      }, HEARTBEAT_TIMEOUT_MS);
    };

    // Listen for messages
    channel.onmessage = (event: MessageEvent<T>) => {
      const data = event.data;
      if (data && typeof data === "object" && "type" in data) {
        if (data.type === "heartbeat") {
          resetTimeout();
        } else if (data.type === "popout_ready") {
          resetTimeout();
          setLastMessage(data);
        } else if (data.type === "popout_closed") {
          setIsConnected(false);
          setLastMessage(data);
        } else {
          setLastMessage(data);
        }
      }
    };

    // Send heartbeats if this instance is the popout
    if (sendHeartbeat) {
      heartbeatTimerRef.current = setInterval(() => {
        try {
          channel.postMessage({ type: "heartbeat" } as T);
        } catch {
          // Channel closed
        }
      }, HEARTBEAT_INTERVAL_MS);
    }

    // Cleanup
    return () => {
      if (heartbeatTimerRef.current) clearInterval(heartbeatTimerRef.current);
      if (timeoutTimerRef.current) clearTimeout(timeoutTimerRef.current);
      try {
        channel.close();
      } catch {
        // Already closed
      }
      channelRef.current = null;
    };
  }, [channelName, sendHeartbeat]);

  return { lastMessage, postMessage, isConnected };
}
