import { z } from 'zod';

const flag = z
  .string()
  .optional()
  .transform((v) => v === 'true');

const schema = z.object({
  // Empty = same origin (production build served by the backend, or the Vite dev proxy)
  VITE_API_BASE_URL: z.union([z.literal(''), z.url()]).default(''),
  VITE_AUTH_DISABLED: flag,
  VITE_MAX_UPLOAD_MB: z.coerce.number().int().positive().default(10),
  VITE_DEMO_MODE: flag,
  VITE_DEMO_EMAIL: z.string().optional(),
  VITE_DEMO_PASSWORD: z.string().optional(),
});

const parsed = schema.safeParse(import.meta.env);

export const envError: string | null = parsed.success
  ? null
  : parsed.error.issues.map((i) => `${i.path.join('.')}: ${i.message}`).join('; ');

export const env = parsed.success
  ? parsed.data
  : { VITE_API_BASE_URL: '', VITE_AUTH_DISABLED: false, VITE_MAX_UPLOAD_MB: 10, VITE_DEMO_MODE: false, VITE_DEMO_EMAIL: undefined, VITE_DEMO_PASSWORD: undefined };
