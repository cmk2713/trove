# Copyright 2020 Catalyst Cloud
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
import semantic_version
from oslo_log import log as logging

from trove.common import cfg
from trove.guestagent.datastore.mysql_common import service
from trove.guestagent.utils import mysql as mysql_util

import sys
import subprocess
from trove.guestagent.utils import docker as docker_util

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

class MySqlAppStatus(service.BaseMySqlAppStatus):
    def __init__(self, docker_client):
        super(MySqlAppStatus, self).__init__(docker_client)


class MySqlApp(service.BaseMySqlApp):
    def __init__(self, status, docker_client):
        super(MySqlApp, self).__init__(status, docker_client)

    def _get_gtid_executed(self):
        with mysql_util.SqlClient(self.get_engine()) as client:
            return client.execute('SELECT @@global.gtid_executed').first()[0]

    def _get_slave_status(self):
        with mysql_util.SqlClient(self.get_engine()) as client:
            return client.execute('SHOW SLAVE STATUS').first()

    def _get_master_UUID(self):
        slave_status = self._get_slave_status()
        return slave_status and slave_status['Master_UUID'] or None

    def get_latest_txn_id(self):
        return self._get_gtid_executed()

    def get_last_txn(self):
        master_UUID = self._get_master_UUID()
        last_txn_id = '0'
        gtid_executed = self._get_gtid_executed()
        for gtid_set in gtid_executed.split(','):
            uuid_set = gtid_set.split(':')
            if str(uuid_set[0]) == str(master_UUID):
                last_txn_id = uuid_set[-1].split('-')[-1]
                break
        return master_UUID, int(last_txn_id)

    def wait_for_txn(self, txn):
        with mysql_util.SqlClient(self.get_engine()) as client:
            client.execute("SELECT WAIT_UNTIL_SQL_THREAD_AFTER_GTIDS('%s')"
                           % txn)

    def get_backup_image(self):
        """Get the actual container image based on datastore version.

        For example, this method converts openstacktrove/db-backup-mysql:1.0.0
        to openstacktrove/db-backup-mysql5.7:1.0.0
        """
        image = cfg.get_configuration_property('backup_docker_image')
        name, tag = image.rsplit(':', 1)

        # Get minor version
        cur_ver = semantic_version.Version.coerce(CONF.datastore_version)
        minor_ver = f"{cur_ver.major}.{cur_ver.minor}"

        return f"{name}{minor_ver}:{tag}"

    def get_backup_strategy(self):
        """Get backup strategy.

        innobackupex was removed in Percona XtraBackup 8.0, use xtrabackup
        instead.
        """
        strategy = cfg.get_configuration_property('backup_strategy')

        mysql_8 = semantic_version.Version('8.0.0')
        cur_ver = semantic_version.Version.coerce(CONF.datastore_version)
        if cur_ver >= mysql_8:
            strategy = 'xtrabackup'

        return strategy
    
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
        
        if new_ver[0]==8 and new_ver[1]==0 and new_ver[2]>=11:
            LOG.info('Checking it is possible to upgrade Mysql')
            LOG.info('''sudo mysqlsh -h 172.17.0.1 -uroot -p%s -e "util.checkForServerUpgrade('root@172.17.0.1:3306',{'password':'','targetVersion':'%s', 'outputFormat':'JSON'});"''',root_pass, root_pass, new_version)
            upgradeCheckCmd='''sudo mysqlsh -h 172.17.0.1 -uroot -p'''+root_pass+ """ -e "util.checkForServerUpgrade('root@172.17.0.1:3306',{'password':'"""+root_pass+"""','targetVersion':'"""+new_version+"""', 'outputFormat':'JSON'});" """
            upgradecheck = subprocess.Popen(upgradeCheckCmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            LOG.info(f"subprocess running cmd:{upgradecheck.args}")
            (stdout, stderr) = upgradecheck.communicate()
            LOG.info(f'upgrade check result : {upgradecheck.returncode}')
            LOG.info(f'upgrade check stdout : {stdout}')
            LOG.info(f'upgrade check stderr : {stderr}')
            if upgradecheck.returncode != 0 :
                raise Exception("upgrading mysql is unavailable")

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


        # mysql version under 8.0.16 is not supported
        # #if new mysql version <8.0.16, exec 'mysql_upgrade' manually
        # LOG.info(f'Checking new DB version {new_version} is under "8.0.16"')
        # LOG.info(f'new_ver[0]=="8": {new_ver[0]} {new_ver[0]==8}')
        # LOG.info(f'new_ver[1]=="0": {new_ver[1]} {new_ver[1]==0}')
        # LOG.info(f'new_ver[2]<"16": {new_ver[2]} {new_ver[2]<16}')
        # if new_ver[0]==8 and new_ver[1]==0 and new_ver[2]<16:
        #     LOG.info(f'Excuting "mysql_upgrade -uroot -p{root_pass}" because new version is {new_version}')
        #     docker_util.run_command(self.docker_client, f'mysql_upgrade -uroot -p{root_pass}')

        #     LOG.info('Stopping db container for upgrade')
        #     self.stop_db()

        #     LOG.info('Starting new db container with version %s for upgrade',
        #          new_version)
        #     #Waiting until db is running
        #     self.start_db(update_db=True, ds_version=new_version)


class MySqlRootAccess(service.BaseMySqlRootAccess):
    def __init__(self, app):
        super(MySqlRootAccess, self).__init__(app)


class MySqlAdmin(service.BaseMySqlAdmin):
    def __init__(self, app):
        root_access = MySqlRootAccess(app)
        super(MySqlAdmin, self).__init__(root_access, app)
