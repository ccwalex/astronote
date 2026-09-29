FROM node:latest

RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY code ./code
COPY product ./product

VOLUME /app/data

WORKDIR /app/product/frontend

RUN npm install
RUN npm run predev:full

# Install backend dependencies into the virtual environment created by predev
RUN ./venv/bin/pip install --no-cache-dir \
    numpy \
    scikit-learn \
    umap-learn \
    requests \
    openai \
    pillow

EXPOSE 5173

CMD ["npm", "run", "dev:full"]
