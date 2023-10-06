#!/bin/bash
echo "Start backup_restore_database.sh"

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

BACKUP_STATUS=BUILDING
VM_NAME=test_$1$2
RESTORE_VM_NAME=$VM_NAME"_RESTORE"
SWIFT_CONTAINER_NAME=$VM_NAME"_backup_strategy"
BACKUP_NAME=$VM_NAME"_backup"
PRIVATE_NETWORK_ID=$(openstack network list --name private -c ID -f value)

INSTANCE_ID=$(openstack database instance show -c id -f value $VM_NAME)

#백업 전략 생성
openstack database backup strategy create --instance-id $INSTANCE_ID --swift-container $SWIFT_CONTAINER_NAME
if [[ $? -ne 0 ]]; then
	echo "Create backup strategy failed"
	exit 1
fi

#백업 생성
openstack database backup create $BACKUP_NAME --instance $INSTANCE_ID --swift-container $SWIFT_CONTAINER_NAME
if [[ $? -ne 0 ]]; then
	echo "Create backup failed"
	exit 1
fi

#백업 완료까지 대기
while [[ "$BACKUP_STATUS" == "BUILDING" ]]; do
	export BACKUP_STATUS=$(openstack database backup show $BACKUP_NAME -c status -f value)
	case "$BACKUP_STATUS" in
		"COMPLETED")
			echo "Backup is created Successfully"
			break
			;;
		"ERROR")
			echo "Error occurred during creating backup"
			exit 1
			;;
		* )
			echo "Creating Backup..."
			;;
	esac;
	sleep 20;
done

#컨테이너에 백업 오브젝트가 잘 들어갔는지 확인
BACKUP_COUNT=$(openstack object list $SWIFT_CONTAINER_NAME -f value | wc -l)
if [[ $BACKUP_COUNT -le 0 ]]; then
    echo "Container has no backup object"
    exit 1
fi

#백업 오브젝트로 복구
openstack database instance create $RESTORE_VM_NAME --flavor d3 --is-public --nic net-id=$PRIVATE_NETWORK_ID --size 1 --datastore $1 --datastore-version $2 --backup $BACKUP_NAME
if [[ $? -ne 0 ]]; then
	echo "Restore instance failed"
	exit 1
fi

VM_STATUS=BUILD
#복구 완료까지 대기
while [[ "$VM_STATUS" == "BUILD" ]]; do
	export VM_STATUS=$(openstack database instance show $RESTORE_VM_NAME -c status -f value)
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
