/**
 * components/codegen/CodeBlock.tsx
 *
 * Production code display for SuperCollider (sclang) and
 * TidalCycles (Haskell DSL) output.
 *
 * Features:
 *   - Solarized Dark background (#002b36) — night-use optimised
 *   - Syntax highlighting: sclang keywords/UGens/symbols and
 *     Haskell keywords / Tidal functions / operators
 *   - Line numbers with separate gutter
 *   - Copy to clipboard (Clipboard API + fallback)
 *   - Download as .scd / .tidal
 *
 * Design reference:
 *   UX_UI_ALIGNMENT.md §2 with solarized dark override
 *   (see UX_UI_ALIGNMENT_PATCH.md)
 */

import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import type { CodegenTarget } from "../../types/codegen";

/* ------------------------------------------------------------------ */
/* Solarized Dark palette                                              */
/* ------------------------------------------------------------------ */

const SOL = {
  base03: "#002b36",  // code background
  base02: "#073642",  // gutter background, toolbar
  base01: "#586e75",  // comments, muted text
  base0: "#839496",   // default code text
  base1: "#93a1a1",   // toolbar text (emphasis)
  keyword: "#FF6600", // TE orange — language keywords, operators
  string: "#f59e0b",  // project amber — strings, SC symbols
  comment: "#586e75", // solarized base01
  number: "#2aa198",  // solarized cyan — numeric literals
  type: "#b58900",    // solarized yellow — class names, SynthDef names
  fn: "#d33682",      // solarized magenta — UGens, Tidal functions
  lineNum: "#4a5568", // muted gutter numbers
  lineNumBorder: "#0a3642",
} as const;

/* ------------------------------------------------------------------ */
/* Token types                                                         */
/* ------------------------------------------------------------------ */

interface Token {
  text: string;
  color: string;
}

/* ------------------------------------------------------------------ */
/* Keyword / function sets                                             */
/* ------------------------------------------------------------------ */

const SC_KEYWORDS = new Set([
  "var", "arg", "if", "else", "do", "while", "for", "forBy",
  "switch", "case", "true", "false", "nil", "this", "super",
  "thisProcess", "thisThread", "inf",
]);

const SC_UGENS = new Set([
  "SynthDef", "Synth", "Ndef", "Pdef", "Pbind", "Pseq", "Prand",
  "Pwhite", "Pfunc", "Pn", "Plazy", "Ppar", "Ptpar",
  "SinOsc", "Saw", "Pulse", "WhiteNoise", "PinkNoise", "BrownNoise",
  "LPF", "HPF", "BPF", "RLPF", "RHPF", "BLowPass", "BHiPass",
  "FreeVerb", "GVerb", "CombL", "CombC", "CombN",
  "AllpassL", "AllpassC", "AllpassN",
  "DelayL", "DelayC", "DelayN",
  "Compander", "Limiter", "Normalizer",
  "In", "Out", "ReplaceOut", "XOut", "LocalIn", "LocalOut",
  "Bus", "Group", "Server", "Buffer",
  "EnvGen", "Env", "Line", "XLine",
  "MouseX", "MouseY", "LFNoise0", "LFNoise1", "LFNoise2",
  "PlayBuf", "BufRd", "RecordBuf",
  "Mix", "Splay", "Pan2", "Balance2",
  "TempoClock", "SystemClock", "Routine", "Task",
  "SendTrig", "SendReply", "Poll",
  "Dust", "Impulse", "TDuty", "Demand",
  "Latch", "Gate", "Schmidt", "Trig", "Trig1",
  "Select", "DetectSilence", "Free",
]);

const TIDAL_KEYWORDS = new Set([
  "let", "in", "where", "do", "import", "module",
  "if", "then", "else", "True", "False",
]);

const TIDAL_FUNCTIONS = new Set([
  "d1", "d2", "d3", "d4", "d5", "d6", "d7", "d8", "d9",
  "sound", "s", "n", "gain", "pan", "speed", "crush", "coarse",
  "lpf", "hpf", "bpf", "resonance", "vowel",
  "delay", "delaytime", "delayfeedback",
  "room", "sz", "dry", "orbit", "channel",
  "distort", "squiz", "shape", "triode",
  "rev", "fast", "slow", "hurry", "every", "sometimes",
  "often", "rarely", "almostNever", "almostAlways",
  "jux", "chunk", "scramble", "shuffle", "iter", "rev",
  "degradeBy", "degrade", "unDegradeBy",
  "stack", "cat", "randcat", "fastcat", "slowcat",
  "superimpose", "off", "struct", "euclid", "e",
  "striate", "chop", "gap", "bite", "splice",
  "setcps", "cps", "hush", "solo", "unsolo", "once",
  "note", "up", "cutoff", "release", "attack",
  "begin", "end", "loop", "legato", "sustain",
  "stut", "stut'", "echo", "echoWith",
  "mask", "sew", "stitch", "while",
  "range", "rangex", "quantise",
  "whenmod", "within", "overlay",
]);

/* ------------------------------------------------------------------ */
/* Tokenisers                                                          */
/* ------------------------------------------------------------------ */

/**
 * Tokenise sclang source code.
 *
 * Handles: // line comments, "strings", \symbols, 'symbols',
 * numeric literals (int/float/negative), PascalCase class names,
 * keywords, UGens, and default identifiers.
 */
function tokeniseSclang(code: string): Token[][] {
  return code.split("\n").map((line) => {
    const tokens: Token[] = [];
    let i = 0;

    while (i < line.length) {
      // Line comment
      if (line[i] === "/" && line[i + 1] === "/") {
        tokens.push({ text: line.slice(i), color: SOL.comment });
        break;
      }
      // Block comment (single-line simplified)
      if (line[i] === "/" && line[i + 1] === "*") {
        const end = line.indexOf("*/", i + 2);
        const slice = end >= 0 ? line.slice(i, end + 2) : line.slice(i);
        tokens.push({ text: slice, color: SOL.comment });
        i += slice.length;
        continue;
      }
      // Double-quoted string
      if (line[i] === '"') {
        let j = i + 1;
        while (j < line.length && line[j] !== '"') {
          if (line[j] === "\\") j++;
          j++;
        }
        tokens.push({ text: line.slice(i, j + 1), color: SOL.string });
        i = j + 1;
        continue;
      }
      // Backslash symbol (\name)
      if (
        line[i] === "\\" &&
        i + 1 < line.length &&
        /[a-zA-Z]/.test(line[i + 1])
      ) {
        let j = i + 1;
        while (j < line.length && /[a-zA-Z0-9_]/.test(line[j])) j++;
        tokens.push({ text: line.slice(i, j), color: SOL.string });
        i = j;
        continue;
      }
      // Single-quoted symbol ('name')
      if (line[i] === "'") {
        let j = i + 1;
        while (j < line.length && line[j] !== "'") j++;
        tokens.push({ text: line.slice(i, j + 1), color: SOL.string });
        i = j + 1;
        continue;
      }
      // Numeric literal
      if (
        /[0-9]/.test(line[i]) ||
        (line[i] === "-" &&
          i + 1 < line.length &&
          /[0-9]/.test(line[i + 1]) &&
          (i === 0 || /[\s(,=:;{[]/.test(line[i - 1])))
      ) {
        let j = i;
        if (line[j] === "-") j++;
        while (j < line.length && /[0-9.eE]/.test(line[j])) j++;
        tokens.push({ text: line.slice(i, j), color: SOL.number });
        i = j;
        continue;
      }
      // Identifier / keyword / UGen
      if (/[a-zA-Z_]/.test(line[i])) {
        let j = i;
        while (j < line.length && /[a-zA-Z0-9_]/.test(line[j])) j++;
        const word = line.slice(i, j);
        if (SC_KEYWORDS.has(word)) {
          tokens.push({ text: word, color: SOL.keyword });
        } else if (SC_UGENS.has(word)) {
          tokens.push({ text: word, color: SOL.fn });
        } else if (
          word[0] === word[0].toUpperCase() &&
          word[0] !== "_" &&
          /[a-z]/.test(word.slice(1))
        ) {
          // PascalCase → class/type name
          tokens.push({ text: word, color: SOL.type });
        } else {
          tokens.push({ text: word, color: SOL.base0 });
        }
        i = j;
        continue;
      }
      // Default — punctuation, whitespace, operators
      tokens.push({ text: line[i], color: SOL.base0 });
      i++;
    }

    if (tokens.length === 0) tokens.push({ text: "", color: SOL.base0 });
    return tokens;
  });
}

/**
 * Tokenise Haskell / TidalCycles source code.
 *
 * Handles: -- line comments, "strings", numeric literals,
 * # and $ operators (TE orange), Haskell keywords,
 * Tidal functions, and default identifiers.
 */
function tokeniseTidal(code: string): Token[][] {
  return code.split("\n").map((line) => {
    const tokens: Token[] = [];
    let i = 0;

    while (i < line.length) {
      // Line comment (--)
      if (line[i] === "-" && line[i + 1] === "-") {
        tokens.push({ text: line.slice(i), color: SOL.comment });
        break;
      }
      // Block comment ({- ... -}) — single-line simplified
      if (line[i] === "{" && line[i + 1] === "-") {
        const end = line.indexOf("-}", i + 2);
        const slice = end >= 0 ? line.slice(i, end + 2) : line.slice(i);
        tokens.push({ text: slice, color: SOL.comment });
        i += slice.length;
        continue;
      }
      // String
      if (line[i] === '"') {
        let j = i + 1;
        while (j < line.length && line[j] !== '"') {
          if (line[j] === "\\") j++;
          j++;
        }
        tokens.push({ text: line.slice(i, j + 1), color: SOL.string });
        i = j + 1;
        continue;
      }
      // Numeric literal
      if (
        /[0-9]/.test(line[i]) ||
        (line[i] === "-" &&
          i + 1 < line.length &&
          /[0-9]/.test(line[i + 1]) &&
          (i === 0 || /[\s(,=$#[]/.test(line[i - 1])))
      ) {
        let j = i;
        if (line[j] === "-") j++;
        while (j < line.length && /[0-9./]/.test(line[j])) j++;
        tokens.push({ text: line.slice(i, j), color: SOL.number });
        i = j;
        continue;
      }
      // # operator (Tidal effect application)
      if (line[i] === "#" && i + 1 < line.length && line[i + 1] === " ") {
        tokens.push({ text: "#", color: SOL.keyword });
        i++;
        continue;
      }
      // $ operator (Haskell function application)
      if (line[i] === "$") {
        tokens.push({ text: "$", color: SOL.keyword });
        i++;
        continue;
      }
      // :: type annotation operator
      if (line[i] === ":" && line[i + 1] === ":") {
        tokens.push({ text: "::", color: SOL.keyword });
        i += 2;
        continue;
      }
      // Identifier / keyword / function
      if (/[a-zA-Z_]/.test(line[i])) {
        let j = i;
        while (j < line.length && /[a-zA-Z0-9_']/.test(line[j])) j++;
        const word = line.slice(i, j);
        if (TIDAL_KEYWORDS.has(word)) {
          tokens.push({ text: word, color: SOL.keyword });
        } else if (TIDAL_FUNCTIONS.has(word)) {
          tokens.push({ text: word, color: SOL.fn });
        } else if (
          word[0] === word[0].toUpperCase() &&
          word.length > 1
        ) {
          // Haskell type constructor
          tokens.push({ text: word, color: SOL.type });
        } else {
          tokens.push({ text: word, color: SOL.base0 });
        }
        i = j;
        continue;
      }
      // Default
      tokens.push({ text: line[i], color: SOL.base0 });
      i++;
    }

    if (tokens.length === 0) tokens.push({ text: "", color: SOL.base0 });
    return tokens;
  });
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

interface CodeBlockProps {
  code: string;
  target: CodegenTarget;
  filename?: string;
}

export function CodeBlock({ code, target, filename }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const copyTimeout = useRef<ReturnType<typeof setTimeout>>();

  // Tokenise — memoised to avoid re-tokenising on unrelated re-renders
  const lines = useMemo(
    () =>
      target === "supercollider"
        ? tokeniseSclang(code)
        : tokeniseTidal(code),
    [code, target],
  );

  const lineCount = lines.length;
  const gutterWidth = Math.max(3, String(lineCount).length) * 10 + 16;

  // File extension and label
  const ext = target === "supercollider" ? ".scd" : ".tidal";
  const label =
    target === "supercollider"
      ? "SCLANG .SCD"
      : "HASKELL / TIDAL .TIDAL";

  // Copy to clipboard
  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      // Fallback for non-HTTPS or older browsers
      const textarea = document.createElement("textarea");
      textarea.value = code;
      textarea.style.cssText = "position:fixed;opacity:0;pointer-events:none";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
    setCopied(true);
    if (copyTimeout.current) clearTimeout(copyTimeout.current);
    copyTimeout.current = setTimeout(() => setCopied(false), 2000);
  }, [code]);

  // Download file
  const handleDownload = useCallback(() => {
    const name = filename ?? `codegen_${Date.now()}${ext}`;
    const blob = new Blob([code], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [code, ext, filename]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (copyTimeout.current) clearTimeout(copyTimeout.current);
    };
  }, []);

  return (
    <div style={{ border: "1px solid #27272a", overflow: "hidden" }}>
      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "5px 12px",
          backgroundColor: SOL.base02,
        }}
      >
        <span
          style={{
            fontSize: "10px",
            letterSpacing: "0.12em",
            textTransform: "uppercase" as const,
            color: SOL.base01,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {label} — {lineCount} LINES
        </span>

        <div style={{ display: "flex", gap: "4px" }}>
          <button
            onClick={handleCopy}
            style={{
              padding: "3px 9px",
              fontSize: "9px",
              letterSpacing: "0.1em",
              textTransform: "uppercase" as const,
              border: `1px solid ${copied ? "#00ff88" : SOL.base01}`,
              backgroundColor: copied ? "rgba(0,255,136,0.1)" : "transparent",
              color: copied ? "#00ff88" : SOL.base1,
              cursor: "pointer",
              fontFamily: "inherit",
              transition: "all 0.1s",
            }}
          >
            {copied ? "OK" : "COPY"}
          </button>
          <button
            onClick={handleDownload}
            style={{
              padding: "3px 9px",
              fontSize: "9px",
              letterSpacing: "0.1em",
              textTransform: "uppercase" as const,
              border: `1px solid ${SOL.base01}`,
              backgroundColor: "transparent",
              color: SOL.base1,
              cursor: "pointer",
              fontFamily: "inherit",
              transition: "all 0.1s",
            }}
          >
            SAVE
          </button>
        </div>
      </div>

      {/* Code area */}
      <div
        style={{
          backgroundColor: SOL.base03,
          overflowX: "auto",
          fontSize: "12px",
          lineHeight: "1.7",
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {lines.map((lineTokens, idx) => (
          <div
            key={idx}
            style={{ display: "flex", minHeight: "1.7em" }}
          >
            {/* Line number gutter */}
            <span
              style={{
                flexShrink: 0,
                width: gutterWidth,
                textAlign: "right" as const,
                paddingRight: "8px",
                paddingLeft: "4px",
                color: SOL.lineNum,
                backgroundColor: SOL.base02,
                borderRight: `1px solid ${SOL.lineNumBorder}`,
                userSelect: "none" as const,
                WebkitUserSelect: "none" as const,
              }}
            >
              {idx + 1}
            </span>

            {/* Code content */}
            <code
              style={{
                paddingLeft: "12px",
                paddingRight: "12px",
                whiteSpace: "pre" as const,
              }}
            >
              {lineTokens.map((token, tidx) => (
                <span key={tidx} style={{ color: token.color }}>
                  {token.text}
                </span>
              ))}
            </code>
          </div>
        ))}
      </div>
    </div>
  );
}
