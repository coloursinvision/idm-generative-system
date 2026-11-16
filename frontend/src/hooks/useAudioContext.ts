import { useCallback, useEffect, useRef } from "react";

/**
 * WebKit-specific `AudioContext` state - present on Safari (desktop + iOS)
 * but absent from the standard lib.dom.d.ts `AudioContextState` union.
 * Narrowed via a string-level predicate below so callers do not need to cast.
 */
type NonRunningState = "suspended" | "interrupted";

function isNonRunningState(state: string): state is NonRunningState {
  return state === "suspended" || state === "interrupted";
}

/**
 * AudioContext lifecycle shared by the sequencer hooks. Each caller owns one
 * lazily created context, kept running across the WebKit gesture and
 * tab-restore rules and closed on unmount.
 *
 * @param logPrefix - prefix of the warning logged when a tab-restore resume fails
 * @param onCreate  - runs on every new context before its first resume, e.g. to
 *                    build a node graph; pass a stable function (useCallback)
 */
export function useAudioContext(
  logPrefix: string,
  onCreate?: (ctx: AudioContext) => void
) {
  const audioCtxRef = useRef<AudioContext | null>(null);

  useEffect(() => {
    return () => {
      if (audioCtxRef.current) audioCtxRef.current.close();
    };
  }, []);

  /**
   * Visibility-change listener - resumes the AudioContext on tab-restore
   * (including BFCache restore on Safari). The cleanup `useEffect` above only
   * fires on unmount, so a context left in `"suspended"` or WebKit-specific
   * `"interrupted"` state after backgrounding would otherwise stay non-running
   * and produce silent playback on the next PLAY click.
   */
  useEffect(() => {
    const handleVisibilityChange = async () => {
      const ctx = audioCtxRef.current;
      if (
        document.visibilityState === "visible" &&
        ctx &&
        ctx.state !== "running" &&
        ctx.state !== "closed"
      ) {
        try {
          await ctx.resume();
        } catch (err) {
          console.warn(`${logPrefix} resume on visibility restore failed:`, err);
        }
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () =>
      document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, [logPrefix]);

  /**
   * Lazily creates the AudioContext and ensures it is in the `"running"` state
   * before returning. Handles WebKit-specific `"interrupted"` state in addition
   * to the standard `"suspended"`.
   *
   * MUST be called from within a user-gesture handler on the first invocation
   * of the session (Safari requirement). Subsequent calls are safe from any
   * context.
   */
  const getAudioContext = useCallback(async (): Promise<AudioContext> => {
    let ctx = audioCtxRef.current;
    if (!ctx || ctx.state === "closed") {
      ctx = new AudioContext({ sampleRate: 44100 });
      audioCtxRef.current = ctx;
      onCreate?.(ctx);
    }
    if (isNonRunningState(ctx.state)) {
      await ctx.resume();
    }
    return ctx;
  }, [onCreate]);

  /**
   * One-time Safari audio unlock - plays a single-sample silent buffer to
   * fully release WebKit's audio output gate. Idempotent: once the context is
   * `"running"` further calls are no-ops aside from a single zero-length
   * source node that is GC'd immediately.
   *
   * Consumers should invoke this on the first interactive button click of the
   * Guide view (LOAD SAMPLES or PLAY - whichever fires first).
   */
  const unlockAudioContext = useCallback(async (): Promise<void> => {
    const ctx = await getAudioContext();
    if (ctx.state !== "running") return;
    const silentBuffer = ctx.createBuffer(1, 1, 22050);
    const source = ctx.createBufferSource();
    source.buffer = silentBuffer;
    source.connect(ctx.destination);
    source.start(0);
  }, [getAudioContext]);

  return { audioCtxRef, getAudioContext, unlockAudioContext };
}
