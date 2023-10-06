#!/bin/bash
echo "Start manage_database_of_replication.sh"

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

PRIMARY_VM_NAME=$1
REPLICA0_VM_NAME=$PRIMARY_VM_NAME"_replica0"
REPLICA1_VM_NAME=$PRIMARY_VM_NAME"_replica1"
DB_NAME=testdb
DB_USERNAME=testuser
DB_USER_PASSWORD=testpw

PRIMARY_ID=$(openstack database instance show -c id -f value $PRIMARY_VM_NAME)
REPLICA0_ID=$(openstack database instance show -c id -f value $REPLICA0_VM_NAME)
REPLICA1_ID=$(openstack database instance show -c id -f value $REPLICA1_VM_NAME)

VM_ARRAY=($PRIMARY_ID $REPLICA0_ID $REPLICA1_ID)

#유저(Primary, Replica0,1) 생성 및 검증
PRIMARY_BEFORE_USER_COUNT=$(openstack database user list $PRIMARY_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database of Primary user failed"
	exit 1
fi

REPLICA0_BEFORE_USER_COUNT=$(openstack database user list $REPLICA0_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database of Replica0 user failed"
	exit 1
fi

REPLICA1_BEFORE_USER_COUNT=$(openstack database user list $REPLICA1_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database of Replica1 user failed"
	exit 1
fi

BEFORE_USER_COUNT_ARRAY=($PRIMARY_BEFORE_USER_COUNT $REPLICA0_BEFORE_USER_COUNT $REPLICA1_BEFORE_USER_COUNT)

echo "[1/4]openstack database user create $PRIMARY_ID $DB_USERNAME $DB_USER_PASSWORD --databases $DB_NAME"
openstack database user create $PRIMARY_ID $DB_USERNAME $DB_USER_PASSWORD --databases $DB_NAME
if [[ $? -ne 0 ]]; then
	echo "Create database user failed"
	exit 1
fi

for i in "${!VM_ARRAY[@]}"; do
		AFTER_USER_COUNT=$(openstack database user list ${VM_ARRAY[$i]} | wc -l)
		if [[ $? -ne 0 ]]; then
			echo "List database user failed"
			exit 1
		fi
		
		tp=$((${BEFORE_USER_COUNT_ARRAY[$i]}+1))
		
		if [[ $AFTER_USER_COUNT -ne $tp ]];then
			echo "User didn't added(expected:$tp, real:$AFTER_USER_COUNT)"
			exit 1
		fi
done

#유저(Primary, Replica0,1) 생성 및 검증
PRIMARY_BEFORE_DB_COUNT=$(openstack database db list $PRIMARY_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database of Primary db failed"
	exit 1
fi

REPLICA0_BEFORE_DB_COUNT=$(openstack database db list $REPLICA0_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database of Replica0 db failed"
	exit 1
fi

REPLICA1_BEFORE_DB_COUNT=$(openstack database db list $REPLICA1_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database of Replica1 db failed"
	exit 1
fi

BEFORE_DB_COUNT_ARRAY=($PRIMARY_BEFORE_DB_COUNT $REPLICA0_BEFORE_DB_COUNT $REPLICA1_BEFORE_DB_COUNT)

#DB 생성 및 삭제
echo "[2/4]openstack database db create $PRIMARY_ID newdb"
openstack database db create $PRIMARY_ID newdb
if [[ $? -ne 0 ]]; then
	echo "Create database failed"
	exit 1
fi

for i in "${!VM_ARRAY[@]}"; do
		AFTER_DB_COUNT=$(openstack database db list ${VM_ARRAY[$i]} | wc -l)
		if [[ $? -ne 0 ]]; then
			echo "List database db failed"
			exit 1
		fi
		
		tp=$((${BEFORE_DB_COUNT_ARRAY[$i]}+1))
		
		if [[ $AFTER_DB_COUNT -ne $tp ]];then
			echo "DB didn't added(expected:$tp, real:$AFTER_DB_COUNT)"
			exit 1
		fi
done

echo "[3/4]openstack database user grant access $PRIMARY_ID $DB_USERNAME newdb"
openstack database user grant access $PRIMARY_ID $DB_USERNAME newdb
if [[ $? -ne 0 ]]; then
	echo "Grant access database to user failed"
	exit 1
fi

##delete db
#유저(Primary, Replica0,1) 삭제 및 검증
PRIMARY_BEFORE_DB_COUNT=$(openstack database db list $PRIMARY_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database of Primary db failed"
	exit 1
fi

REPLICA0_BEFORE_DB_COUNT=$(openstack database db list $REPLICA0_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database of Replica0 db failed"
	exit 1
fi

REPLICA1_BEFORE_DB_COUNT=$(openstack database db list $REPLICA1_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database of Replica1 db failed"
	exit 1
fi

BEFORE_DB_COUNT_ARRAY=($PRIMARY_BEFORE_DB_COUNT $REPLICA0_BEFORE_DB_COUNT $REPLICA1_BEFORE_DB_COUNT)

echo "[4/4]openstack database db delete $PRIMARY_ID newdb"
openstack database db delete $PRIMARY_ID newdb
if [[ $? -ne 0 ]]; then
	echo "Delete database failed"
	exit 1
fi

for i in "${!VM_ARRAY[@]}"; do
		AFTER_DB_COUNT=$(openstack database db list ${VM_ARRAY[$i]} | wc -l)
		if [[ $? -ne 0 ]]; then
			echo "List database db failed"
			exit 1
		fi
		
		tp=$((${BEFORE_DB_COUNT_ARRAY[$i]}-1))
		
		if [[ $AFTER_DB_COUNT -ne $tp ]];then
			echo "DB didn't deleted"
			exit 1
		fi
done

echo "Manage database of Replication Success"