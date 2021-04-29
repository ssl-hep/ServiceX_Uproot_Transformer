#!/usr/bin/env bash

proxydir=$(dirname ${X509_USER_PROXY})

if [[ ! -d $proxydir ]]
then
    mkdir -p $proxydir
fi

while true; do
    cp /etc/grid-security-ro/x509up ${X509_USER_PROXY}
    chmod 600 ${X509_USER_PROXY}

    # Refresh every hour
    sleep 3600

done