# ============================================================
# Frontend Dockerfile — Lunar Thermal Hazard
# Multi-stage: Node build → Nginx serve
# ============================================================

# ---- Stage 1: Build React / Vite app ----
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (cached layer if package.json unchanged)
COPY package.json package-lock.json ./
RUN npm ci --prefer-offline

# Copy source and build
COPY . .
RUN npm run build

# ---- Stage 2: Production Nginx image ----
FROM nginx:1.27-alpine AS frontend

# Remove default Nginx configuration
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom SPA config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy Vite production build
COPY --from=builder /app/dist /usr/share/nginx/html

# Nginx runs as root by default but we drop to the existing
# nginx user inside the official image for production hardening.
RUN chown -R nginx:nginx /usr/share/nginx/html \
 && chmod -R 755 /usr/share/nginx/html

# Expose HTTP port
EXPOSE 80

# Health check via Nginx stub_status
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -qO- http://localhost/health || exit 1

# Start Nginx in foreground (logs go to stdout/stderr by default in this image)
CMD ["nginx", "-g", "daemon off;"]
