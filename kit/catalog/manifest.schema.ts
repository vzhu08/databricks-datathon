import { z } from 'zod';
const paths = z.array(z.string().min(1));
export const ModuleManifestSchema = z
  .object({
    schemaVersion: z.literal(1),
    id: z.string().regex(/^[a-z][a-z0-9-]*$/),
    title: z.string().min(1),
    description: z.string().min(10),
    tags: paths.min(1),
    useCases: paths.min(1),
    runtime: z.enum(['universal', 'node', 'browser', 'python', 'mixed']),
    environments: paths.min(1),
    source: z.string(),
    entrypoints: z.record(z.string(), z.string()),
    exports: paths.min(1),
    minimalRead: paths.min(1),
    dependencies: paths,
    packages: z.record(z.string(), z.string()),
    optionalIntegrations: paths,
    env: z.array(
      z.object({
        name: z.string().regex(/^[A-Z][A-Z0-9_]*$/),
        required: z.boolean(),
        secret: z.boolean(),
        when: z.enum(['local', 'live', 'optional']),
        description: z.string(),
      }),
    ),
    systemRequirements: paths,
    integration: z.object({ steps: paths.min(1), routes: paths, migrations: paths, assets: paths }),
    contracts: paths.min(1),
    examples: paths.min(1),
    fixtures: paths.min(1),
    checks: paths.min(1),
    modes: z.object({ local: z.string().min(5), live: z.string().min(5) }),
    verification: z.object({
      implementation: z.enum(['implemented', 'partial']),
      local: z.string(),
      exported: z.string(),
      live: z.string(),
      record: z.string(),
    }),
    limitations: paths.min(1),
    cost: z.string(),
    docs: paths,
    license: z.string(),
    provenance: z.string(),
  })
  .strict();
export type ModuleManifest = z.infer<typeof ModuleManifestSchema>;
