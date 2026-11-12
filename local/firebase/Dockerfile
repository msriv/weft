FROM node:22-bookworm-slim
# firebase-tools needs Java 21+; bookworm only packages 17.
COPY --from=eclipse-temurin:21-jre /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH=/opt/java/openjdk/bin:$PATH
RUN npm install -g firebase-tools
WORKDIR /fb
COPY firebase.json .
CMD ["firebase", "emulators:start", "--only", "auth,firestore", "--project", "weft-local"]
