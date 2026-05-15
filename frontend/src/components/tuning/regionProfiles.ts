/* ------------------------------------------------------------------ */
/* Region profile metadata — display labels + philosophical captions  */
/*                                                                    */
/* Source: V2_ROADMAP.md §V2.4 — captions per region encode the       */
/* underlying generative aesthetic intent. Single source of truth for */
/* user-facing region selector copy.                                  */
/* ------------------------------------------------------------------ */

import type { RegionCode, SubRegion } from "../../types";

export interface RegionProfile {
  code: RegionCode;
  label: string;
  caption: string;
}

export const REGION_PROFILES: RegionProfile[] = [
  {
    code: "DETROIT_FIRST_WAVE",
    label: "DETROIT FIRST WAVE",
    caption: "May, Atkins, Saunderson — the machine starts to sing.",
  },
  {
    code: "DETROIT_UR",
    label: "DETROIT UR",
    caption: "Underground Resistance — refusal as rhythm.",
  },
  {
    code: "DREXCIYA",
    label: "DREXCIYA",
    caption: "Submerged mythology, 808 as breath.",
  },
  {
    code: "UK_IDM",
    label: "UK IDM",
    caption: "Warp / Rephlex — pattern as thought experiment.",
  },
  {
    code: "UK_BRAINDANCE",
    label: "UK BRAINDANCE",
    caption: "Aphex orbit — broken time signatures, soft melody.",
  },
  {
    code: "JAPAN_IDM",
    label: "JAPAN IDM",
    caption: "Yokota / Aoki / Takemura — silence between the grids.",
  },
];

export interface SubRegionProfile {
  code: SubRegion;
  label: string;
  caption: string;
}

export const SUB_REGION_PROFILES: SubRegionProfile[] = [
  {
    code: "TOKYO",
    label: "TOKYO",
    caption: "50 Hz grid — Yokota, Takemura.",
  },
  {
    code: "OSAKA",
    label: "OSAKA",
    caption: "60 Hz grid — Aoki Takamasa.",
  },
];

export function getRegionCaption(code: RegionCode): string {
  return REGION_PROFILES.find((p) => p.code === code)?.caption ?? "";
}

export function getSubRegionCaption(code: SubRegion): string {
  return SUB_REGION_PROFILES.find((p) => p.code === code)?.caption ?? "";
}
