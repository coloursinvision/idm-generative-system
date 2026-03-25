import type { SourceRef } from "../../types";

interface Props {
  sources: SourceRef[];
}

export function SourceTags({ sources }: Props) {
  if (!sources.length) return null;

  return (
    <div className="mt-4">
      <span className="label">Sources</span>
      <div className="flex flex-wrap">
        {sources.map((s, i) => (
          <span key={i} className="tag-accent">
            {s.title.length > 50 ? s.title.slice(0, 50) + "…" : s.title}
            {" "}({s.score.toFixed(3)})
          </span>
        ))}
      </div>
    </div>
  );
}
