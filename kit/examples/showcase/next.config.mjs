export default {
  agentRules: false,
  poweredByHeader: false,
  experimental: { externalDir: true },
  serverExternalPackages: ['pdfjs-dist', 'mammoth', '@napi-rs/canvas', 'ws'],
  webpack(config) {
    config.resolve.extensionAlias = {
      ...config.resolve.extensionAlias,
      '.js': ['.ts', '.tsx', '.js'],
    };
    return config;
  },
};
