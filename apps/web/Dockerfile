# syntax=docker/dockerfile:1.7
ARG NODE_IMAGE=node:22.14.0-alpine
ARG NGINX_IMAGE=nginx:1.27.4-alpine

FROM ${NODE_IMAGE} AS build
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM ${NGINX_IMAGE} AS runtime
ARG BUILD_VERSION=0.1.0-dev
ARG BUILD_REVISION=unknown
ARG BUILD_SOURCE=https://github.com/example/ai-course-tutor-agent
LABEL org.opencontainers.image.title="course-tutor-web" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.revision="${BUILD_REVISION}" \
      org.opencontainers.image.source="${BUILD_SOURCE}"
COPY apps/web/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://127.0.0.1:8080/ || exit 1
ENTRYPOINT ["nginx", "-g", "daemon off;"]
