# Deployer machine.

FROM ubuntu:latest
MAINTAINER Petr Mrázek, peterix@gmail.com

ENV LANG en_US.UTF-8
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update
RUN apt-get install -y --no-install-recommends sudo
RUN apt-get install -y sudo software-properties-common curl python3 python3-pip python3-requests git wget zip unzip s3cmd rsync
RUN pip3 install 'git+https://github.com/MultiMC/repoman2.git' --break-system-packages --root-user-action=ignore

# add patron scraper script so it can be used by schedulers
RUN pip3 install 'patreon<0.4.0' --break-system-packages --root-user-action=ignore
WORKDIR /usr/bin
RUN wget https://raw.githubusercontent.com/MultiMC/patronupdater/master/patronupdater.py
RUN chmod +x patronupdater.py

# Unknown jank. No idea why it was in the old master container
RUN pip3 install iso8601 lockfile cachecontrol --break-system-packages --root-user-action=ignore

# Oh god, have mercy
RUN mkdir -p ~/.ssh/
RUN ssh-keyscan -t rsa github.com >> ~/.ssh/known_hosts
