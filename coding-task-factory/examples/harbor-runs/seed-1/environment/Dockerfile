FROM golang:1.27.3
WORKDIR /workspace
COPY source.tar.gz /tmp/task-source.tar.gz
RUN tar -xzf /tmp/task-source.tar.gz -C /workspace && rm /tmp/task-source.tar.gz
RUN command -v git
RUN cd /workspace/plugins/fraudguard && go mod download
ENV GOPROXY=off GOSUMDB=off GOTOOLCHAIN=local GOFLAGS=-mod=readonly
