# based on https://github.com/dask/dask-docker/blob/master/base/Dockerfile
# but more permissive about image size due to read-only requirement in openshift
# FROM daskdev/dask:2.9.0
FROM continuumio/miniconda3:4.10.3

RUN apt-get update -y
RUN apt-get install gnupg2 -y \
    && wget -q -O - https://dist.eugridpma.info/distribution/igtf/current/GPG-KEY-EUGridPMA-RPM-3 | apt-key add - \
    && echo "deb http://repository.egi.eu/sw/production/cas/1/current egi-igtf core" >> /etc/apt/sources.list \
    && apt-get --allow-releaseinfo-change update \
    && apt-get install -y ca-policy-egi-core \
    && apt-get purge -y gnupg2 \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

RUN conda install --yes \
    -c conda-forge \
    lz4 \
    xrootd==5.4.0 \
    tini==0.18.0 \
    && conda clean -tipsy

RUN conda install --yes \
    -c conda-forge \
    python-blosc \
    cytoolz \
    numpy \ 
    pandas \
    numba \
    scipy \
    && conda clean -tipsy

RUN apt update && \
    apt upgrade -y && \
    apt install -y sudo

RUN useradd -ms /bin/bash output -G sudo && passwd -d output
RUN mkdir -p /etc/grid-security/certificates /etc/grid-security/vomsdir

COPY requirements.txt .
RUN /opt/conda/bin/pip install safety==1.9.0

# BenGalewsky Feb 1, 2022 - there is an unfixed numpy vulnerability
# https://github.com/numpy/numpy/issues/19038
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
