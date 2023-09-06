# Copyright 2015 Tesora, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

from oslo_log import log as logging

from trove.common import cfg
from trove.guestagent.datastore.mysql_common import service as mysql_service
from trove.guestagent.utils import mysql as mysql_util
from trove.common import utils
from trove.common import exception
from trove.guestagent.utils import docker as docker_util

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


class MariaDBApp(mysql_service.BaseMySqlApp):
    def __init__(self, status, docker_client):
        super(MariaDBApp, self).__init__(status, docker_client)

    def wait_for_slave_status(self, status, client, max_time):
        def verify_slave_status():
            actual_status = client.execute(
                'SHOW GLOBAL STATUS like "Slave_running";').first()[1]
            return actual_status.upper() == status.upper()

        LOG.debug("Waiting for slave status %s with timeout %s",
                  status, max_time)
        try:
            utils.poll_until(verify_slave_status, sleep_time=3,
                             time_out=max_time)
            LOG.info("Replication status: %s.", status)
        except exception.PollTimeOut:
            raise RuntimeError(
                "Replication is not %(status)s after %(max)d seconds." %
                {'status': status.lower(), 'max': max_time})

    def _get_slave_status(self):
        with mysql_util.SqlClient(self.get_engine()) as client:
            return client.execute('SHOW SLAVE STATUS').first()

    def _get_master_UUID(self):
        slave_status = self._get_slave_status()
        return slave_status and slave_status['Master_Server_Id'] or None

    def _get_gtid_executed(self):
        with mysql_util.SqlClient(self.get_engine()) as client:
            return client.execute('SELECT @@global.gtid_binlog_pos').first()[0]

    def _get_gtid_slave_executed(self):
        with mysql_util.SqlClient(self.get_engine()) as client:
            return client.execute('SELECT @@global.gtid_slave_pos').first()[0]

    def get_last_txn(self):
        master_UUID = self._get_master_UUID()
        last_txn_id = '0'
        gtid_executed = self._get_gtid_slave_executed()
        for gtid_set in gtid_executed.split(','):
            uuid_set = gtid_set.split('-')
            if str(uuid_set[1]) == str(master_UUID):
                last_txn_id = uuid_set[-1]
                break
        return master_UUID, int(last_txn_id)

    def get_latest_txn_id(self):
        return self._get_gtid_executed()

    def wait_for_txn(self, txn):
        cmd = "SELECT MASTER_GTID_WAIT('%s')" % txn
        with mysql_util.SqlClient(self.get_engine()) as client:
            client.execute(cmd)

    def upgrade(self, upgrade_info):
        """Upgrade the database."""
        new_version = upgrade_info.get('datastore_version')
        if new_version == CONF.datastore_version:
             return
        
        #Get root password for upgrade
        try:
            LOG.info('Checking Root Authentication is enabled')
            root_pass = upgrade_info.get('root_pass')
            LOG.info(f'Root_Pass = {root_pass}')
        except:
            raise Exception("root is unable")
        
        # #Check whether upgrading is possible
        from distutils.version import LooseVersion
        # cur_ver = LooseVersion(CONF.datastore_version).version
        new_ver = LooseVersion(new_version).version

        LOG.info('Stopping db container for upgrade')
        self.stop_db()

        LOG.info('Deleting db container for upgrade')
        docker_util.remove_container(self.docker_client)

        LOG.info('Remove unused images before starting new db container')
        docker_util.prune_images(self.docker_client)

        LOG.info('Starting new db container with version %s for upgrade',
                 new_version)
        #Waiting until db is running
        self.start_db(update_db=True, ds_version=new_version)
        LOG.info(f'Excuting "mysql_upgrade -uroot -p{root_pass}" because new version is {new_version}')
        docker_util.run_command(self.docker_client, f'mysql_upgrade -uroot -p{root_pass}')

        LOG.info('Stopping db container for upgrade')
        self.stop_db()

        LOG.info('Starting new db container with version %s for upgrade',
                new_version)
        #Waiting until db is running
        self.start_db(update_db=True, ds_version=new_version)


class MariaDBRootAccess(mysql_service.BaseMySqlRootAccess):
    def __init__(self, app):
        super(MariaDBRootAccess, self).__init__(app)


class MariaDBAdmin(mysql_service.BaseMySqlAdmin):
    def __init__(self, app):
        root_access = MariaDBRootAccess(app)
        super(MariaDBAdmin, self).__init__(root_access, app)
