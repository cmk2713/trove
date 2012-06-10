# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http: //www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Model classes that form the core of instances functionality."""

import eventlet
import logging
import netaddr

from reddwarf import db

from novaclient import exceptions as nova_exceptions
from reddwarf.common import config
from reddwarf.common import exception as rd_exceptions
from reddwarf.common import pagination
from reddwarf.common import utils
from reddwarf.common.models import ModelBase
from novaclient import exceptions as nova_exceptions
from reddwarf.common.remote import create_dns_client
from reddwarf.common.remote import create_guest_client
from reddwarf.common.remote import create_nova_client
from reddwarf.common.remote import create_nova_volume_client
from reddwarf.common.utils import poll_until
from reddwarf.instance.tasks import InstanceTask
from reddwarf.instance.tasks import InstanceTasks
from reddwarf.taskmanager import api as task_api


from eventlet import greenthread
from reddwarf.instance.views import get_ip_address


CONFIG = config.Config
LOG = logging.getLogger(__name__)


def load_server(context, instance_id, server_id):
    """Loads a server or raises an exception."""
    client = create_nova_client(context)
    try:
        server = client.servers.get(server_id)
    except nova_exceptions.NotFound, e:
        LOG.debug("Could not find nova server_id(%s)" % server_id)
        raise rd_exceptions.ComputeInstanceNotFound(instance_id=instance_id,
                                                    server_id=server_id)
    except nova_exceptions.ClientException, e:
        raise rd_exceptions.ReddwarfError(str(e))
    return server


# This probably should not happen here. Seems like it should
# be in an extension instead
def populate_databases(dbs):
    """
    Create a serializable request with user provided data
    for creating new databases.
    """
    from reddwarf.guestagent.db import models as guest_models
    try:
        databases = []
        for database in dbs:
            mydb = guest_models.MySQLDatabase()
            mydb.name = database.get('name', '')
            mydb.character_set = database.get('character_set', '')
            mydb.collate = database.get('collate', '')
            databases.append(mydb.serialize())
        return databases
    except ValueError as ve:
        raise rd_exceptions.BadRequest(ve.message)


class InstanceStatus(object):

    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    BUILD = "BUILD"
    FAILED = "FAILED"
    REBOOT = "REBOOT"
    RESIZE = "RESIZE"
    SHUTDOWN = "SHUTDOWN"
    ERROR = "ERROR"


def load_simple_instance_server_status(context, db_info):
    """Loads a server or raises an exception."""
    if InstanceTasks.BUILDING == db_info.task_status:
        db_info.server_status = "BUILD"
        db_info.addresses = {}
    else:
        client = create_nova_client(context)
        try:
            server = client.servers.get(db_info.compute_instance_id)
            db_info.server_status = server.status
            db_info.addresses = server.addresses
        except nova_exceptions.NotFound, e:
            db_info.server_status = "ERROR"
            db_info.addresses = {}
            #TODO(tim.simpson): This is another notifications hack. If the
            # task is delelting, and the compute instance isn't found,
            # then assume the delete operation is done and raise an
            # exception.
            if InstanceTasks.DELETING == db_info.task_status:
                raise rd_exceptions.NotFound(uuid=db_info.id)


# If the compute server is in any of these states we can't perform any
# actions (delete, resize, etc).
SERVER_INVALID_ACTION_STATUSES = ["BUILD", "REBOOT", "REBUILD"]

# Statuses in which an instance can have an action performed.
VALID_ACTION_STATUSES = ["ACTIVE"]


class SimpleInstance(object):
    """A simple view of an instance.

    This gets loaded directly from the local database, so its cheaper than
    creating the fully loaded Instance.

    """

    def __init__(self, context, db_info, service_status):
        self.context = context
        self.db_info = db_info
        self.service_status = service_status

    @property
    def addresses(self):
        #TODO(tim.simpson): Review whether we should keep this... its a mess.
        return self.db_info.addresses

    @property
    def created(self):
        return self.db_info.created

    @property
    def flavor_id(self):
        return self.db_info.flavor_id

    @property
    def hostname(self):
        return self.db_info.hostname

    @property
    def id(self):
        return self.db_info.id

    @property
    def is_building(self):
        return self.status in [InstanceStatus.BUILD]

    @property
    def is_sql_running(self):
        """True if the service status indicates MySQL is up and running."""
        return self.service_status.status in MYSQL_RESPONSIVE_STATUSES

    @staticmethod
    def load(context, id):
        try:
            db_info = DBInstance.find_by(id=id)
        except rd_exceptions.NotFound:
            raise rd_exceptions.NotFound(uuid=id)
        service_status = InstanceServiceStatus.find_by(instance_id=id)
        LOG.info("service status=%s" % service_status)
        # TODO(tim.simpson): In the future, we'll listen to notifications and
        # update the RDL database when the server status changes, and add
        # server_status as a property to db_info, but for now we have to resort
        # to this.
        db_info = DBInstance.find_by(id=id)
        if not context.is_admin and db_info.tenant_id != context.tenant:
            raise rd_exceptions.NotFound(uuid=id)
        load_simple_instance_server_status(context, db_info)
        return SimpleInstance(context, db_info, service_status)

    @property
    def name(self):
        return self.db_info.name

    @property
    def status(self):
        #TODO(tim.simpson): As we enter more advanced cases dealing with
        # timeouts determine if the task_status should be integrated here
        # or removed entirely.
        if InstanceTasks.BUILDING == self.db_info.task_status:
            return InstanceStatus.BUILD
        if InstanceTasks.REBOOTING == self.db_info.task_status:
            return InstanceStatus.REBOOT
        if InstanceTasks.RESIZING == self.db_info.task_status:
            return InstanceStatus.RESIZE
        # If the server is in any of these states they take precedence.
        if self.db_info.server_status in ["BUILD", "ERROR", "REBOOT",
                                          "RESIZE"]:
            return self.db_info.server_status
        # The service is only paused during a reboot.
        if ServiceStatuses.PAUSED == self.service_status.status:
            return InstanceStatus.REBOOT
        # If the service status is NEW, then we are building.
        if ServiceStatuses.NEW == self.service_status.status:
            return InstanceStatus.BUILD
        if InstanceTasks.DELETING == self.db_info.task_status:
            if self.db_info.server_status in ["ACTIVE", "SHUTDOWN"]:
                return InstanceStatus.SHUTDOWN
            else:
                LOG.error(_("While shutting down instance (%s): server had "
                    " status (%s).") % (self.id, self.db_info.server_status))
                return InstanceStatus.ERROR
        # For everything else we can look at the service status mapping.
        return self.service_status.status.api_status

    @property
    def updated(self):
        return self.db_info.updated

    @property
    def volume_id(self):
        return self.db_info.volume_id

    @property
    def volume_size(self):
        return self.db_info.volume_size


def load_instance(cls, context, id, needs_server=False):
    if context is None:
        raise TypeError("Argument context not defined.")
    elif id is None:
        raise TypeError("Argument id not defined.")
    try:
        db_info = DBInstance.find_by(id=id)
    except rd_exceptions.NotFound:
        raise rd_exceptions.NotFound(uuid=id)
    if not context.is_admin and db_info.tenant_id != context.tenant:
        LOG.error("Tenant %s tried to access instance %s, owned by %s."
                  % (context.tenant, id, db_info.tenant_id))
        raise rd_exceptions.NotFound(uuid=id)
    if not needs_server:
        # TODO(tim.simpson): When we have notifications this won't be
        # necessary and instead we'll just use the server_status field from
        # the instance table.
        load_simple_instance_server_status(context, db_info)
        server = None
    else:
        try:
            server = load_server(context, db_info.id,
                                 db_info.compute_instance_id)
            #TODO(tim.simpson): Remove this hack when we have notifications!
            db_info.server_status = server.status
            db_info.addresses = server.addresses
        except rd_exceptions.ComputeInstanceNotFound:
            LOG.error("COMPUTE ID = %s" % db_info.compute_instance_id)
            raise rd_exceptions.UnprocessableEntity(
                "Instance %s is not ready." % id)

    task_status = db_info.task_status
    service_status = InstanceServiceStatus.find_by(instance_id=id)
    LOG.info("service status=%s" % service_status)
    return cls(context, db_info, server, service_status)


class BaseInstance(SimpleInstance):
    """Represents an instance."""

    def __init__(self, context, db_info, server, service_status):
        super(BaseInstance, self).__init__(context, db_info, service_status)
        self.server = server
        self._guest = None
        self._nova_client = None
        self._volume_client = None

    def get_guest(self):
        return create_guest_client(self.context, self.db_info.id)

    @property
    def guest(self):
        if not self._guest:
            self._guest = self.get_guest()
        return self._guest

    @property
    def nova_client(self):
        if not self._nova_client:
            self._nova_client = create_nova_client(self.context)
        return self._nova_client

    def update_db(self, **values):
        row = DBInstance.find_by(id=self.id)
        for key in values:
            setattr(row, key, values[key])
        row.save()

    @property
    def volume_client(self):
        if not self._volume_client:
            self._volume_client = create_nova_volume_client(self.context)
        return self._volume_client


class FreshInstance(BaseInstance):

    @classmethod
    def load(cls, context, id):
        return load_instance(cls, context, id, needs_server=False)


class BuiltInstance(BaseInstance):

    @classmethod
    def load(cls, context, id):
        return load_instance(cls, context, id, needs_server=True)


class Instance(BuiltInstance):
    """Represents an instance.

    The life span of this object should be limited. Do not store them or
    pass them between threads.

    """

    def delete(self, force=False):
        if not force and \
            self.db_info.server_status in SERVER_INVALID_ACTION_STATUSES:
            raise rd_exceptions.UnprocessableEntity("Instance %s is not ready."
                                                    % self.id)
        LOG.debug(_("  ... deleting compute id = %s") %
                  self.db_info.compute_instance_id)
        LOG.debug(_(" ... setting status to DELETING."))
        self.update_db(task_status=InstanceTasks.DELETING)
        task_api.API(self.context).delete_instance(self.id)

    @classmethod
    def create(cls, context, name, flavor_id, image_id,
               databases, service_type, volume_size):
        client = create_nova_client(context)
        try:
            flavor = client.flavors.get(flavor_id)
        except nova_exceptions.NotFound:
            raise rd_exceptions.FlavorNotFound(uuid=flavor_id)

        db_info = DBInstance.create(name=name,
            flavor_id=flavor_id, tenant_id=context.tenant,
            volume_size=volume_size, task_status=InstanceTasks.BUILDING)
        LOG.debug(_("Tenant %s created new Reddwarf instance %s...")
                  % (context.tenant, db_info.id))

        service_status = InstanceServiceStatus.create(instance_id=db_info.id,
            status=ServiceStatuses.NEW)

        task_api.API(context).create_instance(db_info.id, name, flavor_id,
            flavor.ram, image_id, databases, service_type, volume_size)
        dns_client = create_dns_client(context)
        dns_client.update_hostname(db_info)

        return SimpleInstance(context, db_info, service_status)

    def _validate_can_perform_action(self):
        """
        Raises an exception if the instance can't perform an action.
        """
        if self.status not in VALID_ACTION_STATUSES:
            msg = "Instance is not currently available for an action to be " \
                  "performed. Status [%s]"
            LOG.debug(_(msg) % self.status)
            raise rd_exceptions.UnprocessableEntity(_(msg) % self.status)

    def resize_flavor(self, new_flavor_id):
        self.validate_can_perform_resize()
        LOG.debug("resizing instance %s flavor to %s"
                  % (self.id, new_flavor_id))
        # Validate that the flavor can be found and that it isn't the same size
        # as the current one.
        client = create_nova_client(self.context)
        try:
            new_flavor = client.flavors.get(new_flavor_id)
        except nova_exceptions.NotFound:
            raise rd_exceptions.FlavorNotFound(uuid=new_flavor_id)
        old_flavor = client.flavors.get(self.flavor_id)
        new_flavor_size = new_flavor.ram
        old_flavor_size = old_flavor.ram
        if new_flavor_size == old_flavor_size:
            raise rd_exceptions.CannotResizeToSameSize()

        # Set the task to RESIZING and begin the async call before returning.
        self.update_db(task_status=InstanceTasks.RESIZING)
        LOG.debug("Instance %s set to RESIZING." % self.id)
        task_api.API(self.context).resize_flavor(self.id, new_flavor_id,
                    old_flavor_size, new_flavor_size)

    def resize_volume(self, new_size):
        LOG.info("Resizing volume of instance %s..." % self.id)
        if not self.volume_size:
            raise rd_exceptions.BadRequest("Instance %s has no volume."
                                           % self.id)
        old_size = self.volume_size
        if int(new_size) <= old_size:
            raise rd_exceptions.BadRequest("The new volume 'size' cannot be "
                        "less than the current volume size of '%s'" % old_size)
        # Set the task to Resizing before sending off to the taskmanager
        self.update_db(task_status=InstanceTasks.RESIZING)
        task_api.API(self.context).resize_volume(new_size, self.id)


    def restart(self):
        if self.db_info.server_status in SERVER_INVALID_ACTION_STATUSES:
            msg = _("Restart instance not allowed while instance %s is in %s "
                    "status.") % (self.id, instance_state)
            LOG.debug(msg)
            # If the state is building then we throw an exception back
            raise rd_exceptions.UnprocessableEntity(msg)
        else:
            LOG.info("Restarting instance %s..." % self.id)
        # Set our local status since Nova might not change it quick enough.
        #TODO(tim.simpson): Possible bad stuff can happen if this service
        #                   shuts down before it can set status to NONE.
        #                   We need a last updated time to mitigate this;
        #                   after some period of tolerance, we'll assume the
        #                   status is no longer in effect.
        self.update_db(task_status=InstanceTasks.REBOOTING)
        task_api.API(self.context).restart(self.id)

    def validate_can_perform_restart_or_reboot(self):
        """
        Raises exception if an instance action cannot currently be performed.
        """
        if self.db_info.task_status != InstanceTasks.NONE or \
           not self.service_status.status.restart_is_allowed:
            msg = "Instance is not currently available for an action to be " \
                  "performed (task status was %s, service status was %s)." \
                  % (self.db_info.task_status, self.service_status.status)
            LOG.error(msg)
            raise rd_exceptions.UnprocessableEntity(msg)

    def validate_can_perform_resize(self):
        """
        Raises exception if an instance action cannot currently be performed.
        """
        if self.status != InstanceStatus.ACTIVE:
            msg = "Instance is not currently available for an action to be " \
                  "performed (status was %s)." % self.status
            LOG.error(msg)
            raise rd_exceptions.UnprocessableEntity(msg)


def create_server_list_matcher(server_list):
    # Returns a method which finds a server from the given list.
    def find_server(instance_id, server_id):
        matches = [server for server in server_list if server.id == server_id]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) < 1:
            # The instance was not found in the list and
            # this can happen if the instance is deleted from
            # nova but still in reddwarf database
            raise rd_exceptions.ComputeInstanceNotFound(
                instance_id=instance_id, server_id=server_id)
        else:
            # Should never happen, but never say never.
            LOG.error(_("Server %s for instance %s was found twice!")
                  % (server_id, instance_id))
            raise rd_exceptions.ReddwarfError(uuid=instance_id)
    return find_server


class Instances(object):

    DEFAULT_LIMIT = int(config.Config.get('instances_page_size', '20'))

    @staticmethod
    def load(context):
        if context is None:
            raise TypeError("Argument context not defined.")
        client = create_nova_client(context)
        servers = client.servers.list()

        db_infos = DBInstance.find_all(tenant_id=context.tenant)
        limit = int(context.limit or Instances.DEFAULT_LIMIT)
        if limit > Instances.DEFAULT_LIMIT:
            limit = Instances.DEFAULT_LIMIT
        data_view = DBInstance.find_by_pagination('instances', db_infos, "foo",
                                                  limit=limit,
                                                  marker=context.marker)
        next_marker = data_view.next_page_marker

        ret = []
        find_server = create_server_list_matcher(servers)
        for db in db_infos:
            LOG.debug("checking for db [id=%s, compute_instance_id=%s]" %
                      (db.id, db.compute_instance_id))
        for db in data_view.collection:
            try:
                #TODO(tim.simpson): Delete when we get notifications working!
                if InstanceTasks.BUILDING == db.task_status:
                    db.server_status = "BUILD"
                else:
                    try:
                        server = find_server(db.id, db.compute_instance_id)
                        db.server_status = server.status
                    except rd_exceptions.ComputeInstanceNotFound:
                        if InstanceTasks.DELETING == db.task_status:
                            #TODO(tim.simpson): This instance is actually
                            # deleted, but without notifications we never
                            # update our DB.
                            continue
                        db.server_status = "SHUTDOWN" # Fake it...
                #TODO(tim.simpson): End of hack.

                #volumes = find_volumes(server.id)
                status = InstanceServiceStatus.find_by(instance_id=db.id)
                LOG.info(_("Server api_status(%s)") %
                           (status.status.api_status))
                if not status.status: # This should never happen.
                    LOG.error(_("Server status could not be read for "
                                "instance id(%s)") % (db.id))
                    continue
            except ModelNotFoundError:
                LOG.error(_("Server status could not be read for "
                                "instance id(%s)") % (db.id))
                continue
            ret.append(SimpleInstance(context, db, status))
        return ret, next_marker


class DatabaseModelBase(ModelBase):
    _auto_generated_attrs = ['id']

    @classmethod
    def create(cls, **values):
        values['id'] = utils.generate_uuid()
        values['created'] = utils.utcnow()
        instance = cls(**values).save()
        if not instance.is_valid():
            raise InvalidModelError(instance.errors)
        return instance

    def save(self):
        if not self.is_valid():
            raise InvalidModelError(self.errors)
        self['updated'] = utils.utcnow()
        LOG.debug(_("Saving %s: %s") %
            (self.__class__.__name__, self.__dict__))
        return db.db_api.save(self)

    def delete(self):
        self['updated'] = utils.utcnow()
        LOG.debug(_("Deleting %s: %s") %
            (self.__class__.__name__, self.__dict__))
        return db.db_api.delete(self)

    def __init__(self, **kwargs):
        self.merge_attributes(kwargs)
        if not self.is_valid():
            raise InvalidModelError(self.errors)

    def merge_attributes(self, values):
        """dict.update() behaviour."""
        for k, v in values.iteritems():
            self[k] = v

    @classmethod
    def find_by(cls, **conditions):
        model = cls.get_by(**conditions)
        if model is None:
            raise ModelNotFoundError(_("%s Not Found") % cls.__name__)
        return model

    @classmethod
    def get_by(cls, **kwargs):
        return db.db_api.find_by(cls, **cls._process_conditions(kwargs))

    @classmethod
    def find_all(cls, **kwargs):
        return db.db_query.find_all(cls, **cls._process_conditions(kwargs))

    @classmethod
    def _process_conditions(cls, raw_conditions):
        """Override in inheritors to format/modify any conditions."""
        return raw_conditions

    @classmethod
    def find_by_pagination(cls, collection_type, collection_query,
                            paginated_url, **kwargs):
        elements, next_marker = collection_query.paginated_collection(**kwargs)

        return pagination.PaginatedDataView(collection_type,
                                            elements,
                                            paginated_url,
                                            next_marker)


class DBInstance(DatabaseModelBase):
    """Defines the task being executed plus the start time."""

    #TODO(tim.simpson): Add start time.

    _data_fields = ['name', 'created', 'compute_instance_id',
                    'task_id', 'task_description', 'task_start_time',
                    'volume_id']

    def __init__(self, task_status=None, **kwargs):
        kwargs["task_id"] = task_status.code
        kwargs["task_description"] = task_status.db_text
        super(DBInstance, self).__init__(**kwargs)
        self.set_task_status(task_status)

    def _validate(self, errors):
        if InstanceTask.from_code(self.task_id) is None:
            errors['task_id'] = "Not valid."
        if self.task_status is None:
            errors['task_status'] = "Cannot be none."

    def get_task_status(self):
        return InstanceTask.from_code(self.task_id)

    def set_task_status(self, value):
        self.task_id = value.code
        self.task_description = value.db_text

    task_status = property(get_task_status, set_task_status)


class ServiceImage(DatabaseModelBase):
    """Defines the status of the service being run."""

    _data_fields = ['service_name', 'image_id']


class InstanceServiceStatus(DatabaseModelBase):

    _data_fields = ['instance_id', 'status_id', 'status_description']

    def __init__(self, status=None, **kwargs):
        kwargs["status_id"] = status.code
        kwargs["status_description"] = status.description
        super(InstanceServiceStatus, self).__init__(**kwargs)
        self.set_status(status)

    def _validate(self, errors):
        if self.status is None:
            errors['status'] = "Cannot be none."
        if ServiceStatus.from_code(self.status_id) is None:
            errors['status_id'] = "Not valid."

    def get_status(self):
        return ServiceStatus.from_code(self.status_id)

    def set_status(self, value):
        self.status_id = value.code
        self.status_description = value.description

    status = property(get_status, set_status)


def persisted_models():
    return {
        'instance': DBInstance,
        'service_image': ServiceImage,
        'service_statuses': InstanceServiceStatus,
        }


class InvalidModelError(rd_exceptions.ReddwarfError):

    message = _("The following values are invalid: %(errors)s")

    def __init__(self, errors, message=None):
        super(InvalidModelError, self).__init__(message, errors=errors)


class ModelNotFoundError(rd_exceptions.ReddwarfError):

    message = _("Not Found")


class ServiceStatus(object):
    """Represents the status of the app and in some rare cases the agent.

    Code and description are what is stored in the database. "api_status"
    refers to the status which comes back from the REST API.
    """
    _lookup = {}

    def __init__(self, code, description, api_status):
        self._code = code
        self._description = description
        self._api_status = api_status
        ServiceStatus._lookup[code] = self

    @property
    def api_status(self):
        return self._api_status

    @property
    def code(self):
        return self._code

    @property
    def description(self):
        return self._description

    def __eq__(self, other):
        if not isinstance(other, ServiceStatus):
            return False
        return self.code == other.code

    @staticmethod
    def from_code(code):
        if code not in ServiceStatus._lookup:
            msg = 'Status code %s is not a valid ServiceStatus integer code.'
            raise ValueError(msg % code)
        return ServiceStatus._lookup[code]

    @staticmethod
    def from_description(desc):
        all_items = ServiceStatus._lookup.items()
        status_codes = [code for (code, status) in all_items if status == desc]
        if not status_codes:
            msg = 'Status description %s is not a valid ServiceStatus.'
            raise ValueError(msg % desc)
        return ServiceStatus._lookup[status_codes[0]]

    @staticmethod
    def is_valid_code(code):
        return code in ServiceStatus._lookup

    @property
    def restart_is_allowed(self):
        return self._code in [ServiceStatuses.RUNNING._code,
            ServiceStatuses.SHUTDOWN._code, ServiceStatuses.CRASHED._code,
            ServiceStatuses.BLOCKED._code]

    def __str__(self):
        return self._description


class ServiceStatuses(object):
    RUNNING = ServiceStatus(0x01, 'running', 'ACTIVE')
    BLOCKED = ServiceStatus(0x02, 'blocked', 'BLOCKED')
    PAUSED = ServiceStatus(0x03, 'paused', 'SHUTDOWN')
    SHUTDOWN = ServiceStatus(0x04, 'shutdown', 'SHUTDOWN')
    CRASHED = ServiceStatus(0x06, 'crashed', 'SHUTDOWN')
    FAILED = ServiceStatus(0x08, 'failed to spawn', 'FAILED')
    BUILDING = ServiceStatus(0x09, 'building', 'BUILD')
    UNKNOWN = ServiceStatus(0x16, 'unknown', 'ERROR')
    NEW = ServiceStatus(0x17, 'new', 'NEW')


MYSQL_RESPONSIVE_STATUSES = [ServiceStatuses.RUNNING]


# Dissuade further additions at run-time.
ServiceStatus.__init__ = None
