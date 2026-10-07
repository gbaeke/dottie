import { defineConfig } from '@hey-api/openapi-ts'

// src/client/ is generated from the backend's OpenAPI by `npm run gen:api`: types, a fetch client, and TanStack
// Query helpers (listNotesOptions(), createNoteMutation() ...). Never edit it; check.sh fails when it is stale.
export default defineConfig({
  input: './node_modules/.openapi.json',
  output: { path: 'src/client' },
  plugins: ['@hey-api/client-fetch', '@hey-api/sdk', '@tanstack/react-query'],
})
