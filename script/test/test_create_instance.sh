#!/bin/bash
echo "Start create_instance.sh"

# user check
if [[ `whoami` != "stack" ]];then
	echo "Current user is not stack"
	exit 1
fi

# args check
if [[ $# -ne 2 ]]; then
	echo "usage: $0 {DATASTORE_NAME} {DATASTORE_VERSION}"
	exit 1
fi

source ~/devstack/openrc admin

# 초기값
VM_STATUS=BUILD 
VM_NAME=test_$1$2
DATASTORE_NAME=$1
DATASTORE_VERSION=$2
DB_NAME=test
DB_USERNAME=test
DB_PASSWORD=test
PRIVATE_NETWORK_ID=$(openstack network list --name private -c ID -f value)

echo "[1/1]openstack datastore version create $DATASTORE_VERSION \
 $DATASTORE_NAME $DATASTORE_NAME "" --image-tags trove --active --default \
--version-number $DATASTORE_VERSION
openstack database instance create $VM_NAME \
	--flavor d3 \
	--size 1 \
	--nic net-id=$PRIVATE_NETWORK_ID \
	--databases $DB_NAME --users $DB_USERNAME:$DB_PASSWORD \
	--datastore $DATASTORE_NAME --datastore-version $DATASTORE_VERSION \
	--is-public \
	--allowed-cidr 0.0.0.0/0"
#Trove 인스턴스 생성
openstack datastore version create $DATASTORE_VERSION \
 $DATASTORE_NAME $DATASTORE_NAME "" --image-tags trove --active --default \
--version-number $DATASTORE_VERSION
openstack database instance create $VM_NAME \
	--flavor d3 \
	--size 1 \
	--nic net-id=$PRIVATE_NETWORK_ID \
	--databases $DB_NAME --users $DB_USERNAME:$DB_PASSWORD \
	--datastore $DATASTORE_NAME --datastore-version $DATASTORE_VERSION \
	--is-public \
	--allowed-cidr 0.0.0.0/0
if [[ $? -ne 0 ]]; then
	echo "Create database instance failed"
	exit 1
fi

#빌드될 때까지 대기
while [[ "$VM_STATUS" == "BUILD" ]]; do
	export VM_STATUS=$(openstack database instance show $VM_NAME -c status -f value)
	case "$VM_STATUS" in
		"ACTIVE")
			echo "Instance is created Successfully"
			break
			;;
		"ERROR")
			echo "Error occurred during creating Instance"
			exit 1
			;;
		* )
			echo "Creating Instance..."
			;;
	esac;
	sleep 20;
done