#!/bin/bash
echo "Start clean.sh"

# user check
if [[ `whoami` != "stack" ]];then
	echo "Current user is not stack"
	exit 1
fi

# args check
if [[ $# -ne 1 ]]; then
	echo "usage: $0 {VM_NAME}"
	exit 1
fi

source ~/devstack/openrc admin

INSTANCE_ID=$(openstack database instance show -c id -f value $VM_NAME)

RESTORE_VM_NAME=$1"_RESTORE"
REPLICA0_VM_NAME=$1"_replica0"
REPLICA1_VM_NAME=$1"_replica1"
SWIFT_CONTAINER_NAME=$1"_backup_strategy"
BACKUP_NAME=$1"_backup"

openstack database instance delete $REPLICA0_VM_NAME
openstack database instance delete $REPLICA1_VM_NAME
openstack database instance delete $RESTORE_VM_NAME
openstack database instance delete $VM_NAME
openstack database backup delete $BACKUP_NAME
openstack database backup strategy delete --instance-id $INSTANCE_ID