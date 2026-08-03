const tokens = require("./packages/tokens/dist/tailwind.js");

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./packages/**/*.{ts,tsx}"],
  ...tokens,
};
