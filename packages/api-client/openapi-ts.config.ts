import { defineConfig } from "@hey-api/openapi-ts";

// scripts/generate.sh boots apps/api, curls /openapi.json into this path,
// then invokes `openapi-ts` with this config, then deletes the schema.
export default defineConfig({
  input: "./openapi.json",
  output: "./src/generated",
  plugins: ["@hey-api/client-fetch", "@hey-api/sdk", "@hey-api/typescript"],
});
