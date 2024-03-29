# based on https://github.com/dask/dask-docker/blob/master/base/Dockerfile
# but more permissive about image size due to read-only requirement in openshift
# FROM daskdev/dask:2.9.0
FROM continuumio/miniconda3:4.12.0

RUN apt-get update -y && apt-get install gnupg2 -y 

RUN conda install --yes \
    -c conda-forge \
    conda-build \
    lz4 \
    xrootd==5.4.3 \
    tini==0.18.0 \
    && conda build purge-all && conda clean -ti

RUN conda install --yes \
    -c conda-forge \
    python-blosc \
    cytoolz \
    numpy==1.23.3 \
    pandas==1.5.0 \
    scipy==1.6.0 \
    && conda build purge-all && conda clean -ti

RUN apt update && \
    apt upgrade -y && \
    apt install -y sudo

RUN useradd -ms /bin/bash output -G sudo && passwd -d output
RUN mkdir -p /etc/grid-security/certificates /etc/grid-security/vomsdir

COPY requirements.txt .
RUN /opt/conda/bin/pip install safety==1.9.0

RUN safety check -r requirements.txt -i 44715 -i44716 -i 44717
RUN /opt/conda/bin/pip install --no-cache-dir -r requirements.txt

ENV X509_USER_PROXY=/tmp/grid-security/x509up

WORKDIR /servicex
COPY proxy-exporter.sh .
RUN chmod +x proxy-exporter.sh

COPY transformer.py .
ENV PYTHONUNBUFFERED=1
ENV X509_USER_PROXY=/tmp/grid-security/x509up

RUN chgrp -R 0 /home/output && chmod -R g+rwX /home/output
