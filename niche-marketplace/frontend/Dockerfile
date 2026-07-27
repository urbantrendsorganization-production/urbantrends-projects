# syntax=docker/dockerfile:1
FROM node:22-alpine

WORKDIR /app

# Install deps first for layer caching. Uses the lockfile when present.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 3000

# Overridden by docker-compose for dev; runs the production server by default.
CMD ["npm", "run", "start"]
