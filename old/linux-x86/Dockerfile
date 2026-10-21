# MultiMC 32-bit Linux Build Environment

FROM i386/ubuntu:trusty
MAINTAINER Petr Mrázek, peterix@gmail.com

ENV LANG en_US.UTF-8
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update
RUN apt-get install -y --no-install-recommends sudo

# We need "apt-add-repository"
RUN apt-get install -y software-properties-common python-software-properties curl

# Install Qt
RUN apt-add-repository -y ppa:beineri/opt-qt542-trusty
RUN apt-get update
RUN apt-get install -y qt54base qt54svg qt54tools qt54x11extras

# Install Other Dependencies
RUN apt-get install -y zlib1g-dev

# Install Build Tools
RUN apt-add-repository -y ppa:ubuntu-toolchain-r/test
RUN apt-get update
RUN apt-get install -y g++-5 git build-essential
RUN apt-get install wget
RUN wget --no-check-certificate https://cmake.org/files/v3.6/cmake-3.6.0-Linux-i386.sh
RUN sh cmake-3.6.0-Linux-i386.sh --skip-license --prefix=/

# Install Java
RUN add-apt-repository ppa:openjdk-r/ppa
RUN apt-get update
RUN apt-get install -y openjdk-8-jdk

# Install extra packages
RUN apt-get install -y mesa-common-dev libglu1-mesa-dev libgtk2.0-dev vim
