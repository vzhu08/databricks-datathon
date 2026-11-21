FROM node:22.23.2-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY packages/contracts ./packages/contracts
COPY packages/runtime ./packages/runtime
COPY modules/jobs ./modules/jobs
ENV JOB_HOST=0.0.0.0 JOB_PORT=8787 JOB_DB=/data/jobs.sqlite
EXPOSE 8787
VOLUME /data
CMD ["node", "--import", "tsx", "modules/jobs/examples/worker.ts"]
