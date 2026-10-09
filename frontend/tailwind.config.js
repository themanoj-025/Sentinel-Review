/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "../backend/sentinel_review/dashboard/templates/**/*.html",
  ],
  theme: {
    extend: {
      colors: {
        sentinel: {
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
        },
      },
    },
  },
  plugins: [],
};
