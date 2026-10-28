# DigiSanchaar — frontend. Build with Node, serve static files with nginx.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
# NOTE: commit a package-lock.json and switch to `npm ci` for reproducible builds.
RUN npm install --no-audit --no-fund
COPY . .
# Leave empty to use the relative default "/api/v1" (nginx below proxies it).
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1/healthz || exit 1
