import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          0: "#09090b",
          1: "#111113",
          2: "#18181b",
          3: "#27272a",
        },
        text: {
          primary: "#e4e4e7",
          secondary: "#a1a1aa",
          muted: "#52525b",
        },
        accent: {
          green: "#00ff88",
          amber: "#f59e0b",
          red: "#ef4444",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', "monospace"],
        display: ['"Space Grotesk"', "sans-serif"],
      },
      borderRadius: {
        none: "0",
        sm: "2px",
      },
    },
  },
  plugins: [],
} satisfies Config;
