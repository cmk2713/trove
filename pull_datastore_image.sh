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

DATASTORE=$1
VERSION=$2
IMAGE=${DATASTORE}:${VERSION}
echo "working image=${IMAGE}"

# pull image
docker pull ${IMAGE}
if [[ $? -ne 0 ]];then
    echo "docker pull ${IMAGE} failed!"
    exit 1
fi

# image url 
LOCAL_REGISTRY=${LOCAL_REGISTRY:-"localhost:4000"}
LOCAL_REPO_NAME=${LOCAL_REPO_NAME:-"trove-datastores"}
IMAGE_URL=${LOCAL_REGISTRY}/${LOCAL_REPO_NAME}/${IMAGE}
echo "registry: ${IMAGE_URL}"

# image tag
docker tag ${IMAGE} ${IMAGE_URL}
if [[ $? -ne 0 ]];then
    echo "docker tag ${IMAGE} ${IMAGE_URL} failed!"
    exit 1
fi

# push image to local registry
docker push ${IMAGE_URL}
if [[ $? -ne 0 ]];then
    echo "docker push ${IMAGE_URL} failed!"
    exit 1
fi

# remove images
docker rmi ${IMAGE} ${IMAGE_URL}

# show tags for the datastore
echo "local registry tags for ${DATASTORE}:"
curl -X GET ${LOCAL_REGISTRY}/v2/${LOCAL_REPO_NAME}/${DATASTORE}/tags/list

echo "push ${IMAGE} to ${IMAGE_URL} completed!"