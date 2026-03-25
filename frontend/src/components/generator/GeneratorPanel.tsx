import { useState, useRef, useCallback } from "react";
import { postGenerate } from "../../api/client";

const GENERATORS = ["glitch_click", "noise_burst", "fm_blip"] as const;

export function GeneratorPanel() {
  const [generator, setGenerator] = useState<string>("glitch_click");
  const [bypassChain, setBypassChain] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [waveform, setWaveform] = useState<number[]>([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const drawWaveform = useCallback((data: number[]) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    const mid = h / 2;

    ctx.fillStyle = "#111113";
    ctx.fillRect(0, 0, w, h);

    // Grid lines
    ctx.strokeStyle = "#27272a";
    ctx.lineWidth = 0.5;
    for (let y = 0; y <= h; y += h / 4) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // Waveform
    ctx.strokeStyle = "#00ff88";
    ctx.lineWidth = 1;
    ctx.beginPath();
    const step = Math.max(1, Math.floor(data.length / w));
    for (let x = 0; x < w; x++) {
      const idx = Math.min(x * step, data.length - 1);
      const val = data[idx] ?? 0;
      const y = mid - val * mid * 0.9;
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Center line
    ctx.strokeStyle = "#52525b";
    ctx.lineWidth = 0.5;
    ctx.beginPath();
    ctx.moveTo(0, mid);
    ctx.lineTo(w, mid);
    ctx.stroke();
  }, []);

  const handleGenerate = async () => {
    if (loading) return;
    setLoading(true);
    setError("");

    // Cleanup previous
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setWaveform([]);

    try {
      const blob = await postGenerate({
        generator,
        bypass_chain: bypassChain,
      });

      // Create playback URL
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);

      // Decode for waveform
      const arrayBuf = await blob.arrayBuffer();
      const audioCtx = new AudioContext({ sampleRate: 44100 });
      const decoded = await audioCtx.decodeAudioData(arrayBuf);
      const channelData = decoded.getChannelData(0);
      const samples = Array.from(channelData);
      setWaveform(samples);
      drawWaveform(samples);
      audioCtx.close();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setLoading(false);
    }
  };

  const handlePlayStop = () => {
    if (!audioRef.current) return;
    if (isPlaying) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setIsPlaying(false);
    } else {
      audioRef.current.play();
      setIsPlaying(true);
    }
  };

  const handleDownload = () => {
    if (!audioUrl) return;
    const a = document.createElement("a");
    a.href = audioUrl;
    a.download = `${generator}_${Date.now()}.wav`;
    a.click();
  };

  // Redraw on waveform change
  if (waveform.length > 0 && canvasRef.current) {
    drawWaveform(waveform);
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="font-display text-lg font-bold tracking-tight">
          GENERATOR
        </h1>
        <p className="text-text-muted text-xs mt-1">
          ALGORITHMIC SAMPLE GENERATION + 10-BLOCK EFFECTS CHAIN PROCESSING.
        </p>
      </div>

      {/* Controls */}
      <div className="panel">
        <div className="flex items-end gap-6">
          {/* Generator selector */}
          <div className="flex-1">
            <label className="label">Generator</label>
            <div className="flex gap-0">
              {GENERATORS.map((g) => (
                <button
                  key={g}
                  onClick={() => setGenerator(g)}
                  className={`flex-1 py-2 text-[11px] uppercase tracking-[0.1em] border transition-colors duration-100 ${
                    generator === g
                      ? "bg-accent-green/10 text-accent-green border-accent-green"
                      : "bg-surface-0 text-text-muted border-surface-3 hover:text-text-secondary"
                  }`}
                >
                  {g.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>

          {/* Bypass */}
          <div>
            <label className="label">Chain</label>
            <button
              onClick={() => setBypassChain(!bypassChain)}
              className={`px-4 py-2 text-[11px] uppercase tracking-[0.1em] border transition-colors duration-100 ${
                bypassChain
                  ? "bg-accent-amber/10 text-accent-amber border-accent-amber"
                  : "bg-surface-0 text-text-muted border-surface-3"
              }`}
            >
              {bypassChain ? "BYPASS" : "ACTIVE"}
            </button>
          </div>

          {/* Generate button */}
          <button
            className="btn-primary"
            onClick={handleGenerate}
            disabled={loading}
          >
            {loading ? "GENERATING…" : "GENERATE"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="panel border-accent-red/50">
          <span className="text-accent-red text-xs">{error}</span>
        </div>
      )}

      {/* Waveform */}
      <div className="panel">
        <div className="panel-header">Waveform</div>
        <canvas
          ref={canvasRef}
          width={720}
          height={160}
          className="w-full border border-surface-3"
          style={{ imageRendering: "pixelated" }}
        />

        {/* Playback controls */}
        {audioUrl && (
          <div className="flex items-center gap-3 mt-3">
            <button className="btn-primary" onClick={handlePlayStop}>
              {isPlaying ? "STOP" : "PLAY"}
            </button>
            <button className="btn-secondary" onClick={handleDownload}>
              DOWNLOAD WAV
            </button>
            <span className="text-[10px] text-text-muted ml-auto">
              {waveform.length} samples / 44100 Hz / 24-bit
            </span>
          </div>
        )}

        {/* Hidden audio element */}
        {audioUrl && (
          <audio
            ref={audioRef}
            src={audioUrl}
            onEnded={() => setIsPlaying(false)}
          />
        )}
      </div>
    </div>
  );
}
