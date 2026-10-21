# MultiMC website build environment

FROM ubuntu:latest
MAINTAINER Petr Mrázek, peterix@gmail.com

ENV LANG en_US.UTF-8
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update
RUN apt-get install -y --no-install-recommends sudo

RUN apt-get install -y software-properties-common curl

# Download and install hugo
ENV HUGO_VERSION 0.31.1
ENV HUGO_BINARY hugo_${HUGO_VERSION}_Linux-64bit.deb
ADD https://github.com/spf13/hugo/releases/download/v${HUGO_VERSION}/${HUGO_BINARY} /tmp/hugo.deb
RUN dpkg -i /tmp/hugo.deb && rm /tmp/hugo.deb

