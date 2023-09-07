#!/bin/bash

# should run as stack user
if [[ `whoami` != "stack" ]];then
    echo "you should run this script as stack user"
    exit 1
fi

# check args: e.g run.sh mysql 5.7.29
if [[ $# -ne 2 ]];then
    echo "usage: $0 {REPONAME} {TAG}"
    echo "eg: $0 mysql 5.7.29"
    exit 1
fi

source ~/devstack/openrc admin

DATASTORE_TYPE=$1
DATASTORE_VERSION=$2

# datastore image repo for postgresql
if [[ "$DATASTORE_TYPE" == "postgres"* ]];then
    DATASTORE_REPO="postgres"
fi

# pull datastore image & push datastore image to local registry
source pull_datastore_image.sh ${DATASTORE_REPO:-$DATASTORE_TYPE} ${DATASTORE_VERSION}
if [[ $? -ne 0 ]];then
    exit 1
fi

# create datastore version
source create_datastore_version.sh ${DATASTORE_TYPE} ${DATASTORE_VERSION}
if [[ $? -ne 0 ]];then
    exit 1
fi

echo "install datastore ${DATASTORE_TYPE}-${DATASTORE_VERSION} completed!"