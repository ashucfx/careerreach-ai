FROM node:24-alpine

WORKDIR /app

RUN addgroup --system --gid 10001 careerreach && adduser --system --uid 10001 --ingroup careerreach careerreach

COPY --chown=10001:10001 package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY --chown=10001:10001 . .

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

USER 10001:10001
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
