#!/bin/bash
git pull
sudo docker build -t servicex_func_adl_uproot_transformer .
sudo docker tag servicex_func_adl_uproot_transformer:latest zche/servicex_func_adl_uproot_transformer:develop
sudo docker push zche/servicex_func_adl_uproot_transformer:develop
