# Voyage-Site Third-Party Integrations Map

## Authentication & OAuth
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Supabase Auth | User auth & sessions | `src/utils/supabase-server.ts`, `src/utils/supabase-browser.ts`, `src/middleware.ts` | `@supabase/ssr`, `@supabase/supabase-js` |
| Apple Sign-In | OAuth provider | Configured in Supabase | `apple-auth` |
| GitHub OAuth | OAuth provider | Configured in Supabase | — |
| Google OAuth | OAuth provider | Configured in Supabase | — |

## Email & Communication
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Brevo (Sendinblue) | Transactional & marketing email | `src/core/services/communication/BrevoService.ts`, `src/core/services/marketing/BrevoMarketingService.ts` | `@getbrevo/brevo`, `@sendinblue/client` |
| Resend | Transactional email | `src/core/services/communication/ResendService.ts`, `src/utils/resend.ts` | `resend` |
| React Email | Email template rendering | `src/emails/` | `react-email`, `@react-email/components`, `@react-email/render` |

## Payments
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Braintree (PayPal) | Payment processing | `src/app/api/payments/braintree/process/route.ts`, `src/utils/brainTreeGateway.ts`, `src/utils/validateBraintreeInput.ts` | `braintree` (server), `braintree-web` (client) |

## Flight Booking
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Duffel | Flight search & booking | `src/app/api/flights-duffel/`, `src/utils/duffel-client.ts`, `src/app/api/jobs/duffel/sync-airports/route.ts` | `@duffel/api` |
| Amadeus | Flight search & booking (alt) | `src/app/api/flights/`, `src/utils/amadeus-client.ts` | `amadeus` |

## CMS
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Contentful | Static pages & structured content | `src/core/contentful/contentful.ts` | `contentful`, `@contentful/rich-text-*` |
| Ghost | Blog content | `src/core/ghost/ghost.ts` | HTTP REST (no SDK) |

## Database & Storage
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| PostgreSQL (Supabase) | Primary database | `src/core/database.ts`, `drizzle.config.ts` | `drizzle-orm`, `pg` |
| AWS S3 | File uploads (public & private buckets) | S3 client utils | `@aws-sdk/client-s3`, `@aws-sdk/s3-request-presigner` |
| CloudFront | CDN for S3 files | — | env: `FILES_CLOUDFRONT_HOSTNAME` |
| Supabase Storage | Email asset hosting | Static URLs in email templates | — |

## Caching
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Vercel KV (Redis) | Distributed serverless cache | — | `@vercel/kv` |
| Node Cache | In-process memory cache | — | `node-cache` |

## Maps & Geospatial
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Mapbox GL | Interactive maps | `src/hooks/useMapMarkers.ts`, map components | `mapbox-gl`, `react-map-gl` |
| Mapbox Spiderifier | Marker clustering | — | `mapboxgl-spiderifier` |
| Turf.js | Geospatial calculations | — | `@turf/turf` |

## CRM & Marketing
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| HubSpot | CRM sync | `src/app/api/jobs/hubspot/` | `@hubspot/api-client` |
| Brevo (marketing) | Contact lists & automation | `src/core/services/marketing/BrevoMarketingService.ts` | `@getbrevo/brevo` |

## Analytics & Monitoring
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Google Analytics 4 | Web analytics (via GTM) | `src/app/layout.tsx` | `@next/third-parties/google` |
| Hotjar | Heatmaps & session recordings | `src/components/hotjar-script/HotJarScript.tsx` | `react-hotjar` |
| Vercel Analytics | Web Vitals | `src/app/layout.tsx` | `@vercel/analytics` |
| Vercel Speed Insights | RUM performance | `src/app/layout.tsx` | `@vercel/speed-insights` |

## AI
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| OpenAI | Artemis/VoyagePal AI assistant | `src/core/voyage-pal/voyagePal.ts`, `src/core/voyage-pal/initializer/VoyagePal.ts` | `openai` |
| Vercel AI SDK | AI abstraction layer | — | `ai` |

## External Data APIs
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Exchange Rates API | Currency conversion | `src/app/api/jobs/exchange-rates/route.ts`, `src/core/services/finance/Currencies.ts` | HTTP (exchangeratesapi.io) |
| IPInfo | IP geolocation | — | `node-ipinfo` |
| Country API | Country/location data | — | env: `COUNTRY_API_TOKEN` |

## PDF & Image Processing
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| React PDF Renderer | Invoice PDF generation | `src/components/invoice-pdf-document/InvoicePdfDocument.tsx` | `@react-pdf/renderer` |
| Sharp | Server-side image optimization | — | `sharp` |
| Compressor.js | Client-side image compression | — | `compressorjs` |
| HEIC conversion | iPhone image support | — | `heic-convert`, `heic-decode`, `heic2any` |

## GraphQL Stack
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Apollo Server | GraphQL API server | `src/app/api/graphql/route.ts` | `@apollo/server`, `@as-integrations/next` |
| Pothos | Schema builder | `src/core/graphql/schemaBuilder.ts` | `@pothos/core` + plugins (errors, scope-auth, validation) |
| urql | GraphQL client | `src/app/graphql/client.ts` | `@urql/next`, `@urql/exchange-graphcache`, `@urql/exchange-auth` |
| GraphQL Codegen | Type generation | `codegen.ts` | `@graphql-codegen/cli`, `@graphql-codegen/client-preset` |

## Platform & Hosting
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Vercel | Hosting, serverless, cron | `vercel.json` | — |
| Next.js 14 (App Router) | React framework | `next.config.js` | `next` |
| next-intl | i18n | `src/i18n.ts`, `messages/en.json` | `next-intl` |

## Rich Text & UI
| Service | Purpose | Key Files | Package |
|---------|---------|-----------|---------|
| Tiptap | WYSIWYG editor | — | `@tiptap/react`, `@tiptap/starter-kit` |
| Headless UI | Accessible UI primitives | — | `@headlessui/react` |
| Tailwind CSS | Styling | `tailwind.config.js` | `tailwindcss` |
