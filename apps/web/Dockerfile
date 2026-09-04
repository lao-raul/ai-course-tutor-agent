# ---- Web Docker image ----
FROM node:22-alpine AS build

WORKDIR /app

# Install dependencies first (layer cache)
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm install

# Copy source
COPY apps/web/vite.config.ts apps/web/tsconfig.json apps/web/tsconfig.app.json apps/web/tsconfig.node.json ./
COPY apps/web/src ./src
COPY apps/web/index.html .

# Build
RUN npm run build

# ---- nginx runtime stage ----
FROM nginx:alpine AS runtime

# Remove default nginx site
RUN rm -rf /usr/share/nginx/html/*

# Copy built assets
COPY --from=build /app/dist /usr/share/nginx/html

# Custom nginx config with SPA fallback
RUN cat > /etc/nginx/conf.d/default.conf << 'EOF'
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # Serve static assets with long cache
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # SPA fallback — all routes go to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Proxy API and V1 endpoints to API server
    location /v1/ {
        proxy_pass http://api:8000/v1/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }

    # Also proxy /admin for ingestion admin endpoints
    location /admin/ {
        proxy_pass http://api:8000/admin/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
}

EOF

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
