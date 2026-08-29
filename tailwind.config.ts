import type { Config } from "tailwindcss";

// Colours come from CSS custom properties so light and dark resolve through one
// palette. `<alpha-value>` keeps Tailwind's /50 opacity syntax working.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        raised: token("raised"),
        ink: token("ink"),
        muted: token("muted"),
        line: token("line"),
        accent: token("accent"),
        "accent-ink": token("accent-ink"),
        good: token("good"),
        "good-wash": token("good-wash"),
        warn: token("warn"),
        "warn-wash": token("warn-wash"),
        bad: token("bad"),
        "bad-wash": token("bad-wash"),
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Inter", "sans-serif"],
      },
      keyframes: {
        rise: {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: { rise: "rise 220ms ease-out both" },
    },
  },
  plugins: [],
} satisfies Config;
