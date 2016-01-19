# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et

# fabric task file for building new CI slave images
#
# usage:
#       fab help
#


import os
import sys
from datetime import datetime
import uuid
from fabric.api import task, env

from bookshelf.api_v1 import (status as f_status,
                              up as f_up,
                              down as f_down,
                              destroy as f_destroy,
                              create_image as f_create_image,
                              create_server as f_create_server,
                              startup_gce_instance as f_startup_gce_instance)

from bookshelf.api_v1 import (is_there_state,
                              load_state_from_disk,
                              ssh_session)

from lib.mycookbooks import (ec2,
                             rackspace,
                             gce,
                             get_cloud_environment,
                             check_for_missing_environment_variables,
                             segredos)


from lib.bootstrap import (bootstrap_jenkins_slave_centos7,
                           bootstrap_jenkins_slave_ubuntu14)

from tests.acceptance import acceptance_tests


def setup_cloud_env(cloud_type):
    if cloud_type == 'ec2':
        ec2()
    elif cloud_type == 'rackspace':
        rackspace()
    elif cloud_type == 'gce':
        gce()
    else:
        raise ValueError("Unknown cloud type: {}".format(cloud_type))


@task
def create_image():
    """ create ami/image for either AWS, Rackspace or GCE """
    (year, month, day, hour, mins,
     sec, wday, yday, isdst) = datetime.utcnow().timetuple()
    date = "%s%s%s%s%s" % (year, month, day, hour, mins)

    data = load_state_from_disk()
    cloud_type = data['cloud_type']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    description = C[cloud_type][distribution]['description']

    if cloud_type == 'gce':
        kwargs = dict(
            zone=data['zone'],
            project=data['project'],
            instance_name=data['instance_name'],
            name=description + "-" + date,
        )
    else:
        kwargs = dict(
            region=data['region'],
            access_key_id=C[cloud_type][distribution]['access_key_id'],
            secret_access_key=C[cloud_type][distribution]['secret_access_key'],
            instance_id=data['id'],
            name=description + "_" + date,
        )

    f_create_image(cloud=cloud_type,
                   description=description,
                   **kwargs)


@task
def destroy():
    """ destroy an existing instance """
    data = load_state_from_disk()
    cloud_type = data['cloud_type']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    env.user = data['username']
    env.key_filename = C[cloud_type][distribution]['key_filename']

    if cloud_type == 'gce':
        zone = data['zone']
        project = data['project']
        disk_name = data['instance_name']
        f_destroy(cloud='gce',
                  zone=zone,
                  project=project,
                  disk_name=disk_name)
    else:
        region = data['region']
        access_key_id = C[cloud_type][distribution]['access_key_id']
        secret_access_key = C[cloud_type][distribution]['secret_access_key']
        instance_id = data['id']

        f_destroy(cloud=cloud_type,
                  region=region,
                  instance_id=instance_id,
                  access_key_id=access_key_id,
                  secret_access_key=secret_access_key)


@task
def down(cloud=None):
    """ halt an existing instance """
    data = load_state_from_disk()
    cloud_type = data['cloud_type']
    if cloud_type == 'gce':
        zone = data['zone']
        project = data['project']
        instance_name = data['instance_name']
        f_down(cloud=cloud_type, zone=zone,
               project=project, instance_name=instance_name)
    else:
        region = data['region']
        distribution = data['distribution'] + data['os_release']['VERSION_ID']
        access_key_id = C[cloud_type][distribution]['access_key_id']
        secret_access_key = C[cloud_type][distribution]['secret_access_key']
        instance_id = data['id']
        env.key_filename = C[cloud_type][distribution]['key_filename']

        setup_cloud_env(cloud_type)
        f_down(cloud=cloud_type,
               instance_id=instance_id,
               region=region,
               access_key_id=access_key_id,
               secret_access_key=secret_access_key)


@task(default=True)
def help():
    """ help """
    print("""
          usage: fab <action>[:arguments] <action>[:arguments]

            # shows this page
            $ fab help

            # does the whole thing in one go
            $ fab it:cloud=[ec2|rackspace|gce],distribution=[centos7|ubuntu14.04]

            # boots an existing instance
            $ fab up

            # creates a new instance
            $ fab up:cloud=<ec2|rackspace|gce>,distribution=<centos7|ubuntu14.04>

            # installs packages on an existing instance
            $ fab bootstrap:distribution=<centos7|ubuntu14.04>

            # creates a new ami
            $ fab create_image

            # destroy the box
            $ fab destroy

            # power down the box
            $ fab down

            # ssh to the instance
            $ fab ssh

            # execute a command on the instance
            $ fab ssh:'ls -l'

            # run acceptance tests against new instance
            $ fab tests

            The following environment variables must be set:

            For AWS:
            http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html#cli-environment

            # AWS_ACCESS_KEY_ID
            # AWS_KEY_FILENAME (the full path to your private key file)
            # AWS_KEY_PAIR (the KEY_PAIR to use)
            # AWS_SECRET_ACCESS_KEY
            # AWS_ACCESS_REGION (optional)
            # AWS_AMI (optional)
            # AWS_INSTANCE_TYPE (optional)

            For Rackspace:
            http://docs.rackspace.com/servers/api/v2/cs-gettingstarted/content/gs_env_vars_summary.html

            # OS_USERNAME
            # OS_TENANT_NAME
            # OS_PASSWORD
            # OS_NO_CACHE
            # RACKSPACE_KEY_PAIR (the KEY_PAIR to use)
            # RACKSPACE_KEY_FILENAME (the full path to your private key file)
            # OS_AUTH_SYSTEM (optional)
            # OS_AUTH_URL (optional)
            # OS_REGION_NAME (optional)

            For Google Compute Engine (GCE):
            # GCE_PUBLIC_KEY (Absolute file path to a public ssh key to use)
            # GCE_PRIVATE_KEY (Absolute file path to a private ssh key to use)
            # GCE_PROJECT (The GCE project to create the image in)
            # GCE_ZONE (The GCE zone to use to make the image)
            # GCE_MACHINE_TYPE (The machine type to use to make the image,
              defaults to n1-standard-2)

            Metadata state is stored locally in data.json.
          """)


@task
def it(cloud, distribution):
    """ runs the full stack

    :param string cloud: The cloud type to use 'ec2', 'rackspace'
    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """
    setup_cloud_env(cloud)
    up(cloud=cloud, distribution=distribution)
    bootstrap(distribution)
    tests()
    create_image()
    destroy()


@task
def bootstrap(distribution=None):
    """ bootstraps an existing running instance

    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """

    # read distribution from state file
    data = load_state_from_disk()
    cloud_type = data['cloud_type']
    env.user = data['username']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    env.key_filename = C[cloud_type][distribution]['key_filename']

    # are he just doing a 'fab bootstrap' ?
    # then find out our distro from our state file
    if (distribution is None):
        distribution = data['os_release']['ID'] + \
            data['os_release']['VERSION_ID']

    if distribution == 'centos7':
        bootstrap_jenkins_slave_centos7()

    if 'ubuntu14.04' in distribution:
        bootstrap_jenkins_slave_ubuntu14()


@task
def status():
    """ returns current status of the instance """
    data = load_state_from_disk()
    cloud_type = data['cloud_type']
    username = data['username']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    env.user = data['username']
    env.key_filename = C[cloud_type][distribution]['key_filename']
    if cloud_type == 'gce':
        zone = data['zone']
        project = data['project']
        instance_name = data['instance_name']
        f_status(cloud=cloud_type,
                 zone=zone,
                 project=project,
                 instance_name=instance_name,
                 data=data)
    else:
        region = data['region']
        access_key_id = C[cloud_type][distribution]['access_key_id']
        secret_access_key = C[cloud_type][distribution]['secret_access_key']
        instance_id = data['id']

        setup_cloud_env(cloud_type)
        f_status(cloud=cloud_type,
                 region=region,
                 instance_id=instance_id,
                 access_key_id=access_key_id,
                 secret_access_key=secret_access_key,
                 username=username)


@task
def ssh(*cli):
    """ opens an ssh connection to the instance

    :param string cli: the commands to run on the host
    """

    data = load_state_from_disk()
    cloud_type = data['cloud_type']
    ip_address = data['ip_address']
    username = data['username']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    key_filename = C[cloud_type][distribution]['key_filename']

    ssh_session(key_filename,
                username,
                ip_address,
                *cli)


@task
def tests():
    """ run tests against an existing instance """
    data = load_state_from_disk()
    cloud_type = data['cloud_type']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    env.user = data['username']
    env.key_filename = C[cloud_type][distribution]['key_filename']
    setup_cloud_env(cloud_type)

    acceptance_tests(distribution=distribution)


@task
def up(cloud=None, distribution=None):
    """ boots a new instance on amazon or rackspace

    :param string cloud: The cloud type to use 'ec2', 'rackspace'
    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """

    if is_there_state():
        data = load_state_from_disk()
        cloud_type = data['cloud_type']

        if cloud_type == 'gce':

            f_up(cloud_type, disk_name=data['instance_name'],
                 instance_name=data['instance_name'],
                 **C[cloud][distribution]['creation_args'])
        else:

            username = data['username']
            distribution = data['distribution'] + data['os_release']['VERSION_ID']
            region = data['region']
            access_key_id = C[cloud_type][distribution]['access_key_id']
            secret_access_key = C[cloud_type][distribution]['secret_access_key']
            instance_id = data['id']
            env.user = data['username']
            env.key_filename = C[cloud_type][distribution]['key_filename']

            setup_cloud_env(cloud_type)
            f_up(cloud=cloud_type,
                 region=region,
                 instance_id=instance_id,
                 access_key_id=access_key_id,
                 secret_access_key=secret_access_key,
                 username=username)

    else:
        env.user = C[cloud][distribution]['creation_args']['username']
        env.key_filename = C[cloud][distribution]['key_filename']

        # no state file around, lets create a new VM
        # and use defaults values we have in our config 'C' dictionary
        f_create_server(cloud=cloud,
                        **C[cloud][distribution]['creation_args'])


@task
def startup_gce_jenkins_slave(cloud, slave_image):
    """
    Background: At this time, jclouds and the Jenkins jclouds plugin
    don't work correctly on GCE.  Until this is fixed we're going to
    have static slaves running our GCE builds.

    This function will spin up a slave instance in GCE running the
    specified image (that should have already been provisioned via
    ``fab it``.
    """

    if 'ubuntu' in slave_image:
        distribution = 'ubuntu14.04'
    elif 'centos' in slave_image:
        distribution = 'centos7'
    else:
        raise RuntimeError("could not parse distribution from image"
                           "{}".format(slave_image))
    creation_args = C[cloud][distribution]['creation_args']
    jenkins_public_key = (segredos()['env']['default']['ssh']['ssh_keys']
                          [1]['contents'][0])
    username = 'jenkins'
    instance_name = u"jenkins-slave-image-" + unicode(uuid.uuid4())
    f_startup_gce_instance(instance_name,
                           creation_args['project'],
                           creation_args['zone'],
                           username,
                           creation_args['machine_type'],
                           slave_image,
                           jenkins_public_key)

"""
    ___main___
"""
# is this a fab help ?
if 'help' in sys.argv:
    help()
    exit(1)

# make sure we have all the required variables available in the environment
list_of_clouds = []

# look up our state.json file, and load the cloud_type from there
if is_there_state():
    data = load_state_from_disk()
    list_of_clouds.append(data['cloud_type'])
else:
    # no state.json, we expect to find a cloud='' option in our argv
    list_of_clouds = get_cloud_environment()

if not len(list_of_clouds):
    # sounds like we are asking for a task that require cloud environment
    # variables and we don't have them defined, let's inform the user what
    # variables we are looking for.
    help()

# right, we have a 'cloud_type' in list_of_clouds, lets find out if the env
# variables we need for that cloud have been defined.
if not check_for_missing_environment_variables(list_of_clouds):
    help()
    exit(1)

# retrieve some of the secrets from the segredos dict
jenkins_plugin_dict = segredos()[
    'env']['default']['jenkins']['clouds']['jclouds_plugin'][0]

# soaks up the environment variables
# AWS environment variables, see:
# http://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html#cli-environment
if 'ec2' in list_of_clouds:
    ec2_instance_type = os.getenv('AWS_INSTANCE_TYPE', 't2.medium')
    ec2_key_filename = os.environ['AWS_KEY_FILENAME']  # path to ssh key
    ec2_key_pair = os.environ['AWS_KEY_PAIR']
    ec2_region = os.getenv('AWS_REGION', 'us-west-2')
    ec2_secret_access_key = os.environ['AWS_SECRET_ACCESS_KEY']
    ec2_access_key_id = os.environ['AWS_ACCESS_KEY_ID']
    ec2_key_filename = os.environ['AWS_KEY_FILENAME']

# Rackspace environment variables, see:
# http://docs.rackspace.com/servers/api/v2/cs-gettingstarted/content/gs_env_vars_summary.html
if 'rackspace' in list_of_clouds:
    rackspace_username = os.environ['OS_USERNAME']
    rackspace_tenant_name = os.environ['OS_TENANT_NAME']
    rackspace_password = os.environ['OS_PASSWORD']
    rackspace_auth_url = os.getenv('OS_AUTH_URL',
                                   'https://identity.api.rackspacecloud.com/'
                                   'v2.0/')
    rackspace_auth_system = os.getenv('OS_AUTH_SYSTEM', 'rackspace')
    rackspace_region = os.getenv('OS_REGION_NAME', 'DFW')
    rackspace_flavor = '1GB Standard Instance'
    rackspace_key_pair = os.environ['RACKSPACE_KEY_PAIR']
    rackspace_public_key = jenkins_plugin_dict['publicKey'][0]
    rackspace_key_filename = os.environ['RACKSPACE_KEY_FILENAME']

# GCE environment variables,
if 'gce' in list_of_clouds:
    gce_private_key_filename = os.environ['GCE_PRIVATE_KEY']
    with open(os.environ['GCE_PUBLIC_KEY'], 'r') as f:
        gce_public_key = f.read()
    gce_project = os.environ['GCE_PROJECT']
    gce_zone = os.environ['GCE_ZONE']
    gce_machine_type = os.getenv('GCE_MACHINE_TYPE', 'n1-standard-2')

# We define a dictionary containing API secrets, disk sizes, base amis,
# and other bits and pieces that we will use for creating a new EC2 or Rackspace
# instance and authenticate over ssh.
C = {}
if 'ec2' in list_of_clouds:
    C['ec2'] = {
        'centos7': {
            'creation_args': {
                'ami': 'ami-c7d092f7',
                'username': 'centos',
                'disk_name': '/dev/sda1',
                'disk_size': '48',
                'instance_type': ec2_instance_type,
                'key_pair': ec2_key_pair,
                'region': ec2_region,
                'secret_access_key': ec2_secret_access_key,
                'access_key_id': ec2_access_key_id,
                'security_groups': ['ssh'],
                'tags': {'name': 'jenkins_slave_centos7_ondemand'}
            },
            'description': 'jenkins_slave_centos7_ondemand',
            'key_filename': ec2_key_filename,
        },
        'ubuntu14.04': {
            'creation_args': {
                'ami': 'ami-87bea5b7',
                'username': 'ubuntu',
                'disk_name': '/dev/sda1',
                'disk_size': '48',
                'instance_type': ec2_instance_type,
                'key_pair': ec2_key_pair,
                'region': ec2_region,
                'secret_access_key': ec2_secret_access_key,
                'access_key_id': ec2_access_key_id,
                'security_groups': ['ssh'],
                'tags': {'name': 'jenkins_slave_ubuntu14_ondemand'}
            },
            'description': 'jenkins_slave_ubuntu14_ondemand',
            'key_filename': ec2_key_filename,
        }
    }

if 'rackspace' in list_of_clouds:
    C['rackspace'] = {
        'centos7': {
            'creation_args': {
                'ami': 'CentOS 7 (PVHVM)',
                'username': 'root',
                'disk_name': '',
                'disk_size': '48',
                'instance_type': rackspace_flavor,
                'key_pair': rackspace_key_pair,
                'region': rackspace_region,
                'secret_access_key': rackspace_password,
                'access_key_id': rackspace_username,
                'security_groups': '',
                'instance_name': 'jenkins_slave_centos7_ondemand',
                'tags': {'name': 'jenkins_slave_centos7_ondemand'}
            },
            'description': 'jenkins_slave_centos7_ondemand',
            'public_key': rackspace_public_key,
            'auth_system': rackspace_auth_system,
            'tenant': rackspace_tenant_name,
            'auth_url': rackspace_auth_url,
            'key_filename': rackspace_key_filename,
        },
        'ubuntu14.04': {
            'creation_args': {
                'ami': 'Ubuntu 14.04 LTS (Trusty Tahr) (PVHVM)',
                'username': 'root',
                'disk_name': '',
                'disk_size': '48',
                'instance_type': rackspace_flavor,
                'key_pair': rackspace_key_pair,
                'region': rackspace_region,
                'secret_access_key': rackspace_password,
                'access_key_id': rackspace_username,
                'security_groups': '',
                'instance_name': 'jenkins_slave_ubuntu14_ondemand',
                'tags': {'name': 'jenkins_slave_ubuntu14_ondemand'}
            },
            'description': 'jenkins_slave_ubuntu14_ondemand',
            'public_key': rackspace_public_key,
            'auth_system': rackspace_auth_system,
            'tenant': rackspace_tenant_name,
            'auth_url': rackspace_auth_url,
            'key_filename': rackspace_key_filename,
        }
    }

if 'gce' in list_of_clouds:
    C['gce'] = {
        'centos7': {
            'creation_args': {
                'base_image_prefix': 'centos-7',
                'base_image_project': 'centos-cloud',
                'username': 'ci-slave-image-preper',
                'project': gce_project,
                'zone': gce_zone,
                'machine_type': gce_machine_type,
                'public_key': gce_public_key,
            },
            'key_filename': gce_private_key_filename,
            'description': 'jenkins-slave-centos7-ondemand',
        },
        'ubuntu14.04': {
            'creation_args': {
                'base_image_prefix': 'ubuntu-1404',
                'base_image_project': 'ubuntu-os-cloud',
                'username': 'ci-slave-image-preper',
                'project': gce_project,
                'zone': gce_zone,
                'machine_type': gce_machine_type,
                'public_key': gce_public_key,
            },
            'key_filename': gce_private_key_filename,
            'description': 'jenkins-slave-ubuntu14-ondemand',
        }
    }

# Modify some global Fabric behaviours:
# Let's disable known_hosts, since on Clouds that behaviour can get in the
# way as we continuosly destroy/create boxes.
env.disable_known_hosts = True
env.use_ssh_config = False
env.eagerly_disconnect = True
env.connection_attemtps = 5

# We store the state in a local file as we need to keep track of the
# ec2 instance id and ip_address so that we can run provision multiple times
# By using some metadata locally about the VM we get a similar workflow to
# vagrant (up, down, destroy, bootstrap).
if not is_there_state():
    pass
else:
    data = load_state_from_disk()
    env.hosts = data['ip_address']
    env.cloud = data['cloud_type']
