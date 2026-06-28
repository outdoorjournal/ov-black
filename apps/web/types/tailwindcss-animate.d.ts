// tailwindcss-animate ships no type declarations. Declaring it as a module
// lets us `import` the plugin (required under Node 24's ESM config loading)
// without tripping TS7016 in the typecheck job.
declare module "tailwindcss-animate";
