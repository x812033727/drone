import js from "@eslint/js";
import tseslint from "@typescript-eslint/eslint-plugin";
import tsparser from "@typescript-eslint/parser";

export default [
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsparser,
      parserOptions: { ecmaVersion: "latest", sourceType: "module" },
      globals: { window: "readonly", document: "readonly", EventSource: "readonly", console: "readonly", setTimeout: "readonly", clearTimeout: "readonly", fetch: "readonly" },
    },
    plugins: { "@typescript-eslint": tseslint },
    rules: {
      ...tseslint.configs.recommended.rules,
      // TypeScript(tsc)已負責未定義變數檢查,no-undef 對 TS 冗餘且誤報 DOM/Node 全域
      "no-undef": "off",
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
    },
  },
];
