FROM node:22-slim

RUN apt-get update && apt-get install -y \
    curl \
    git \
    ripgrep \
    python3 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json ./
RUN npm install

COPY server.js ./

EXPOSE 20128

CMD ["npm", "start"]
