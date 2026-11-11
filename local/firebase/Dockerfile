FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless \
 && rm -rf /var/lib/apt/lists/* && npm install -g firebase-tools
WORKDIR /fb
COPY firebase.json .
CMD ["firebase", "emulators:start", "--only", "auth,firestore", "--project", "weft-local"]
