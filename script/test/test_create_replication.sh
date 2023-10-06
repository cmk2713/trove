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
VM_STATUS="BUILD"
VM_NAME=test_$1$2
REPLICA0_NAME=$VM_NAME"_replica0"
REPLICA1_NAME=$VM_NAME"_replica1"
PRIVATE_NETWORK_ID=$(openstack network list --name private -c ID -f value)

echo "openstack database instance create --replica-of $VM_NAME --nic net-id=$PRIVATE_NETWORK_ID $REPLICA0_NAME"

#Trove 레플리카0 생성
openstack database instance create --replica-of $VM_NAME --nic net-id=$PRIVATE_NETWORK_ID $REPLICA0_NAME
if [[ $? -ne 0 ]]; then
	echo "Create replication of instance $VM_NAME failed"
	exit 1
fi

#빌드될 때까지 대기
while [[ "$VM_STATUS" == "BUILD" ]]; do
	export VM_STATUS=$(openstack database instance show $REPLICA0_NAME -c status -f value)
	case "$VM_STATUS" in
		"ACTIVE")
			echo "$REPLICA0_NAME is created Successfully"
			break
			;;
		"ERROR")
			echo "Error occurred during creating $REPLICA0_NAME"
			exit 1
			;;
		* )
			echo "Creating $REPLICA0_NAME..."
			;;
	esac;
	sleep 20;
done

#VM 상태값 초기화
VM_STATUS="BUILD"

#Trove 레플리카1 생성
openstack database instance create --replica-of $VM_NAME --nic net-id=$PRIVATE_NETWORK_ID $REPLICA1_NAME
if [[ $? -ne 0 ]]; then
	echo "Create replication of instance $VM_NAME failed"
	exit 1
fi

#빌드될 때까지 대기
while [[ "$VM_STATUS" == "BUILD" ]]; do
	export VM_STATUS=$(openstack database instance show $REPLICA1_NAME -c status -f value)
	case "$VM_STATUS" in
		"ACTIVE")
			echo "$REPLICA1_NAME is created Successfully"
			break
			;;
		"ERROR")
			echo "Error occurred during creating $REPLICA1_NAME"
			exit 1
			;;
		* )
			echo "Creating $REPLICA1_NAME..."
			;;
	esac;
	sleep 20;
done

