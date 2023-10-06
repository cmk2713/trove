#!/bin/bash
echo "Start manage_database.sh"

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

VM_NAME=$1
TEST_DB_NAME=testdb
TEST_DB_USERNAME=testuser
TEST_DB_USER_PASSWORD=testpw

INSTANCE_ID=$(openstack database instance show -c id -f value $VM_NAME)


#유저 생성 및 검증
BEFORE_USER_COUNT=$(openstack database user list $INSTANCE_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database user failed"
	exit 1
fi

echo "[1/4]openstack database user create $INSTANCE_ID $TEST_DB_USERNAME $TEST_DB_USER_PASSWORD --databases $TEST_DB_NAME"
openstack database user create $INSTANCE_ID $TEST_DB_USERNAME $TEST_DB_USER_PASSWORD --databases $TEST_DB_NAME
if [[ $? -ne 0 ]]; then
	echo "Create database user failed"
	exit 1
fi

AFTER_USER_COUNT=$(openstack database user list $INSTANCE_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database user failed"
	exit 1
fi

tp=$(($BEFORE_USER_COUNT+1))

if [[ $AFTER_USER_COUNT -ne $tp ]];then
	echo "User didn't added"
	exit 1
fi



#DB 생성
echo "[2/4]openstack database db create $INSTANCE_ID newdb"
openstack database db create $INSTANCE_ID newdb
if [[ $? -ne 0 ]]; then
	echo "Create database failed"
	exit 1
fi

# DB & User 연결
echo "[3/4]openstack database user grant access $INSTANCE_ID $TEST_DB_USERNAME newdb"
openstack database user grant access $INSTANCE_ID $TEST_DB_USERNAME newdb
if [[ $? -ne 0 ]]; then
	echo "Grant access database to user failed"
	exit 1
fi

##delete user
BEFORE_USER_COUNT=$(openstack database user list $INSTANCE_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List user failed"
	exit 1
fi

echo "[4/4]openstack database user delete $INSTANCE_ID $TEST_DB_USERNAME"
openstack database user delete $INSTANCE_ID $TEST_DB_USERNAME
if [[ $? -ne 0 ]]; then
	echo "Delete user failed"
	exit 1
fi

AFTER_USER_COUNT=$(openstack database user list $INSTANCE_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List user failed"
	exit 1
fi
tp=$(($BEFORE_USER_COUNT-1))
if [[ $AFTER_USER_COUNT -ne $tp ]];then
	echo "User didn't deleted"
	exit 1
fi

##delete db
BEFORE_DB_COUNT=$(openstack database db list $INSTANCE_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database failed"
	exit 1
fi

echo "[4/4]openstack database db delete $INSTANCE_ID newdb"
openstack database db delete $INSTANCE_ID newdb
if [[ $? -ne 0 ]]; then
	echo "Delete database failed"
	exit 1
fi

AFTER_DB_COUNT=$(openstack database db list $INSTANCE_ID | wc -l)
if [[ $? -ne 0 ]]; then
	echo "List database failed"
	exit 1
fi
tp=$(($BEFORE_DB_COUNT-1))
if [[ $AFTER_DB_COUNT -ne $tp ]];then
	echo "DB didn't deleted"
	exit 1
fi

echo "Manage database Success"
