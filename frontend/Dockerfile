# ---- Build stage ----
FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPA_ANON_PUB

ENV VITE_API_URL=$VITE_API_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .
RUN VITE_SUPABASE_ANON_KEY=$VITE_SUPA_ANON_PUB npm run build

# ---- Runtime stage ----
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
