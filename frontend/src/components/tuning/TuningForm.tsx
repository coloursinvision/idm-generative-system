import { useEffect } from "react";
import type {
  RegionCode,
  SubRegion,
  TuningRequest,
} from "../../types";
import {
  REGION_PROFILES,
  SUB_REGION_PROFILES,
  getRegionCaption,
  getSubRegionCaption,
} from "./regionProfiles";

interface Props {
  value: TuningRequest;
  onChange: (next: TuningRequest) => void;
  onSubmit: () => void;
  loading: boolean;
  error: string;
}

export function TuningForm({
  value,
  onChange,
  onSubmit,
  loading,
  error,
}: Props) {
  // Enforce cross-field rule: sub_region tied to JAPAN_IDM.
  useEffect(() => {
    if (value.region === "JAPAN_IDM" && value.sub_region === null) {
      onChange({ ...value, sub_region: "TOKYO" });
    } else if (value.region !== "JAPAN_IDM" && value.sub_region !== null) {
      onChange({ ...value, sub_region: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value.region]);

  const setField = <K extends keyof TuningRequest>(
    key: K,
    v: TuningRequest[K],
  ) => onChange({ ...value, [key]: v });

  const valid =
    value.bpm >= 60 &&
    value.bpm <= 240 &&
    value.pitch_midi >= 0 &&
    value.pitch_midi <= 127 &&
    value.swing_pct >= 0 &&
    value.swing_pct <= 100;

  return (
    <div className="panel space-y-5">
      <div className="panel-header">Tuning request</div>

      {/* BPM */}
      <div>
        <label className="label">BPM: {value.bpm.toFixed(1)}</label>
        <input
          type="range"
          min={60}
          max={240}
          step={0.5}
          value={value.bpm}
          onChange={(e) => setField("bpm", Number(e.target.value))}
          className="w-full accent-accent-green"
        />
        <div className="flex justify-between text-[10px] text-text-muted tracking-wider mt-1">
          <span>60</span>
          <span>240</span>
        </div>
      </div>

      {/* Pitch MIDI */}
      <div>
        <label className="label">
          Pitch MIDI: {value.pitch_midi.toFixed(0)} (
          {midiToNoteName(value.pitch_midi)})
        </label>
        <input
          type="range"
          min={0}
          max={127}
          step={1}
          value={value.pitch_midi}
          onChange={(e) => setField("pitch_midi", Number(e.target.value))}
          className="w-full accent-accent-green"
        />
        <div className="flex justify-between text-[10px] text-text-muted tracking-wider mt-1">
          <span>0 (C-1)</span>
          <span>69 (A4)</span>
          <span>127 (G9)</span>
        </div>
      </div>

      {/* Swing % */}
      <div>
        <label className="label">Swing: {value.swing_pct.toFixed(0)}%</label>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={value.swing_pct}
          onChange={(e) => setField("swing_pct", Number(e.target.value))}
          className="w-full accent-accent-green"
        />
      </div>

      {/* Region */}
      <div>
        <label className="label">Region</label>
        <select
          className="textarea-field"
          value={value.region}
          onChange={(e) => setField("region", e.target.value as RegionCode)}
        >
          {REGION_PROFILES.map((p) => (
            <option key={p.code} value={p.code}>
              {p.label}
            </option>
          ))}
        </select>
        <div className="text-text-muted text-[10px] tracking-wider mt-1 italic">
          {getRegionCaption(value.region)}
        </div>
      </div>

      {/* Sub-region — conditional */}
      {value.region === "JAPAN_IDM" && (
        <div>
          <label className="label">Sub-region</label>
          <select
            className="textarea-field"
            value={value.sub_region ?? "TOKYO"}
            onChange={(e) => setField("sub_region", e.target.value as SubRegion)}
          >
            {SUB_REGION_PROFILES.map((p) => (
              <option key={p.code} value={p.code}>
                {p.label}
              </option>
            ))}
          </select>
          <div className="text-text-muted text-[10px] tracking-wider mt-1 italic">
            {value.sub_region && getSubRegionCaption(value.sub_region)}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="text-accent-red text-xs">{error}</div>
      )}

      {/* Submit */}
      <button
        className="btn-primary"
        onClick={onSubmit}
        disabled={!valid || loading}
      >
        {loading ? "COMPUTING…" : "GET TUNING"}
      </button>
    </div>
  );
}

// MIDI → note name helper (e.g. 69 → "A4", 60 → "C4").
function midiToNoteName(midi: number): string {
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const m = Math.round(midi);
  const octave = Math.floor(m / 12) - 1;
  const note = names[m % 12];
  return `${note}${octave}`;
}
