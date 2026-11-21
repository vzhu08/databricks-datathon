import { defineConfig } from 'vitest/config';
export default defineConfig({
  test: {
    include: [
      'packages/**/tests/**/*.test.ts',
      'modules/**/tests/**/*.test.ts',
      'tests/**/*.test.ts',
    ],
    testTimeout: 15000,
    fileParallelism: false,
  },
});
