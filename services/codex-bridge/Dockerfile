FROM node:22-bookworm-slim
WORKDIR /bridge
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && mkdir -p /home/node/.codex && chown -R node:node /home/node/.codex
COPY --chown=node:node *.mjs ./
USER node
ENV CODEX_HOME=/home/node/.codex
EXPOSE 8787
CMD ["node", "server.mjs"]
