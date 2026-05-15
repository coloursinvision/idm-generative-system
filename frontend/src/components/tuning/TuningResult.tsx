import type { TuningResponse } from "../../types";

interface Props {
  result: TuningResponse;
}

export function TuningResult({ result }: Props) {
  return (
    <div className="panel space-y-4">
      <div className="panel-header">Tuning</div>

      {/* Scalar tuning Hz — hero number */}
      <div className="text-center py-4">
        <div className="text-[10px] tracking-[0.3em] text-text-muted uppercase">
          Tuning frequency
        </div>
        <div className="font-display text-4xl font-bold text-accent-green mt-2">
          {result.tuning_hz.toFixed(2)} Hz
        </div>
      </div>

      <div className="divider" />

      {/* Resonant points table */}
      <div>
        <div className="text-[10px] tracking-[0.3em] text-text-muted uppercase mb-2">
          Resonant points ({result.resonant_points.length})
        </div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-text-muted text-[10px] tracking-wider uppercase border-b border-surface-3">
              <th className="text-left py-2">Label</th>
              <th className="text-right py-2">Hz</th>
              <th className="text-right py-2">Confidence</th>
            </tr>
          </thead>
          <tbody>
            {result.resonant_points.map((p, i) => (
              <tr
                key={`${p.label}-${i}`}
                className="border-b border-surface-2 last:border-0"
              >
                <td className="py-2 font-mono">{p.label}</td>
                <td className="py-2 text-right font-mono">
                  {p.hz.toFixed(2)}
                </td>
                <td className="py-2 text-right font-mono">
                  {(p.confidence * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Metadata footer */}
      <div className="divider" />
      <div className="flex justify-between gap-4 text-[10px] text-text-muted tracking-wider">
        <span>model {result.model_version.slice(0, 12)}…</span>
        <span>dataset {result.dataset_dvc_hash.slice(0, 12)}…</span>
        <span>{result.inference_latency_ms.toFixed(2)} ms</span>
      </div>
    </div>
  );
}
