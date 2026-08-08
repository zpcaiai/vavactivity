/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{vue,ts}"],
  theme: {
    extend: {
      colors: {
        vav: {
          ink: "#24322f",
          primary: "#8c4f5e",
          gold: "#c9985b",
          cream: "#fffdf9"
        }
      },
      fontFamily: {
        sans: ["Inter", "Noto Sans SC", "PingFang SC", "system-ui", "sans-serif"]
      }
    }
  },
  plugins: []
};
