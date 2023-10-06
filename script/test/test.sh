#!/bin/bash
echo "Start test.sh"

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

VM_NAME=test_$1$2

{
	source test_create_instance.sh $1 $2
	if [[ $? -ne 0 ]];then
	    exit 1
	fi
	
	
	source test_manage_database.sh $VM_NAME
	if [[ $? -ne 0 ]];then
	    exit 1
	fi
	
	
	source test_backup_restore_database.sh $1 $2
	if [[ $? -ne 0 ]];then
	    exit 1
	fi

	source test_create_replication.sh $1 $2
	if [[ $? -ne 0 ]];then
	    exit 1
	fi

	source test_manage_replication_database.sh $VM_NAME
	if [[ $? -ne 0 ]];then
	    exit 1
	fi

	echo "Test is completed Successfully"
}

source test_clean.sh $VM_NAME