import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0f1720",
        muted: "#5b6b7a",
        line: "#e3e8ee",
        wash: "#f6f8fa",
        good: "#137a4d",
        warn: "#8a6100",
        bad: "#9a2b2b",
      },
    },
  },
  plugins: [],
} satisfies Config;
