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

# datastore & version
DATASTORE=$1
VERSION=$2
ADMIN_OPENRC=${ADMIN_OPENRC:-"/opt/stack/kinx/admin-openrc"}

echo "creating datastore version for ${DATASTORE}-${VERSION} started"

# source admin-openrc for openstack
echo "ADMIN_OPENRC=${ADMIN_OPENRC}"
source ${ADMIN_OPENRC}

# create datastore version
openstack datastore version create ${VERSION} ${DATASTORE} ${DATASTORE} "" --image-tags trove --version-number ${VERSION} --active --default
if [[ $? -ne 0 ]];then
    echo "creating datastore version failed!"
    exit 1
fi

# add configuration parameters for version
trove-manage db_load_datastore_config_parameters ${DATASTORE} ${VERSION} ~/trove/trove/templates/${DATASTORE}/validation-rules.json
if [[ $? -ne 0 ]];then
    echo "adding configuration parameter for ${DATASTORE}-${VERSION} failed"
    exit 1
fi

# show current datastore version list
openstack datastore version list ${DATASTORE}

echo "creating datastore version for ${DATASTORE}-${VERSION} completed"