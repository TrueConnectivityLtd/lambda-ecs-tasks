FROM python:2.7-alpine

RUN apk --no-cache add zip bash make

COPY . /app
WORKDIR /app

ENTRYPOINT ["make", "build"]
