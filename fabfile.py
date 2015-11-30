# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et

# fabric task file for building new CI slave images
#
# usage:
#       fab help
#


import os
import sys
from datetime import datetime
from fabric.api import task, env

from bookshelf.api_v1 import (status as f_status,
                              up as f_up,
                              down as f_down,
                              destroy as f_destroy,
                              create_image as f_create_image,
                              create_server as f_create_server)

from bookshelf.api_v1 import (is_there_state,
                              load_state_from_disk,
                              ssh_session)

from lib.mycookbooks import (ec2,
                             rackspace,
                             get_cloud_environment,
                             check_for_missing_environment_variables,
                             segredos)


from lib.bootstrap import (bootstrap_jenkins_slave_centos7,
                           bootstrap_jenkins_slave_ubuntu14)

from tests.acceptance import acceptance_tests


@task
def create_image():
    """ create ami/image for either AWS or Rackspace """
    (year, month, day, hour, mins,
     sec, wday, yday, isdst) = datetime.utcnow().timetuple()
    date = "%s%s%s%s%s" % (year, month, day, hour, mins)

    data = load_state_from_disk()
    cloud_type = data['cloud_type']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    access_key_id = C[cloud_type][distribution]['access_key_id']
    secret_access_key = C[cloud_type][distribution]['secret_access_key']
    instance_name = C[cloud_type][distribution]['instance_name']
    description = C[cloud_type][distribution]['description']

    f_create_image(cloud=cloud_type,
                   region=data['region'],
                   access_key_id=access_key_id,
                   secret_access_key=secret_access_key,
                   instance_id=data['id'],
                   name=instance_name + "_" + date,
                   description=description)


@task
def destroy():
    """ destroy an existing instance """
    data = load_state_from_disk()
    cloud_type = data['cloud_type']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    region = data['region']
    access_key_id = C[cloud_type][distribution]['access_key_id']
    secret_access_key = C[cloud_type][distribution]['secret_access_key']
    instance_id = data['id']
    env.user = data['username']
    env.key_filename = C[cloud_type][distribution]['key_filename']

    f_destroy(cloud=cloud_type,
              region=region,
              instance_id=instance_id,
              access_key_id=access_key_id,
              secret_access_key=secret_access_key)


@task
def down(cloud=None):
    """ halt an existing instance """
    data = load_state_from_disk()
    region = data['region']
    cloud_type = data['cloud_type']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    access_key_id = C[cloud_type][distribution]['access_key_id']
    secret_access_key = C[cloud_type][distribution]['secret_access_key']
    instance_id = data['id']
    env.key_filename = C[cloud_type][distribution]['key_filename']

    if data['cloud_type'] == 'ec2':
        ec2()
    if data['cloud_type'] == 'rackspace':
        rackspace()
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
            $ fab it:cloud=[ec2|rackspace],distribution=[centos7|ubuntu14.04]

            # boots an existing instance
            $ fab up

            # creates a new instance
            $ fab up:cloud=<ec2|rackspace>,distribution=<centos7|ubuntu14.04>

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

            metadata state is stored locally in state.json.
          """)


@task
def it(cloud, distribution):
    """ runs the full stack

    :param string cloud: The cloud type to use 'ec2', 'rackspace'
    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """
    if cloud == 'ec2':
        ec2()
    if cloud == 'rackspace':
        rackspace()

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
    region = data['region']
    access_key_id = C[cloud_type][distribution]['access_key_id']
    secret_access_key = C[cloud_type][distribution]['secret_access_key']
    instance_id = data['id']
    env.user = data['username']
    env.key_filename = C[cloud_type][distribution]['key_filename']

    if data['cloud_type'] == 'ec2':
        ec2()
    if data['cloud_type'] == 'rackspace':
        rackspace()

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
    username = data['username']
    distribution = data['distribution'] + data['os_release']['VERSION_ID']
    region = data['region']
    access_key_id = C[cloud_type][distribution]['access_key_id']
    secret_access_key = C[cloud_type][distribution]['secret_access_key']
    instance_id = data['id']
    env.user = data['username']
    env.key_filename = C[cloud_type][distribution]['key_filename']

    if data['cloud_type'] == 'ec2':
        ec2()
    if data['cloud_type'] == 'rackspace':
        rackspace()

    acceptance_tests(cloud=cloud_type,
                     region=region,
                     instance_id=instance_id,
                     access_key_id=access_key_id,
                     secret_access_key=secret_access_key,
                     distribution=distribution,
                     username=username)


@task
def up(cloud=None, distribution=None):
    """ boots a new instance on amazon or rackspace

    :param string cloud: The cloud type to use 'ec2', 'rackspace'
    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """

    if is_there_state():
        data = load_state_from_disk()
        cloud_type = data['cloud_type']
        username = data['username']
        distribution = data['distribution'] + data['os_release']['VERSION_ID']
        region = data['region']
        access_key_id = C[cloud_type][distribution]['access_key_id']
        secret_access_key = C[cloud_type][distribution]['secret_access_key']
        instance_id = data['id']
        env.user = data['username']
        env.key_filename = C[cloud_type][distribution]['key_filename']

        if data['cloud_type'] == 'ec2':
            ec2()
        if data['cloud_type'] == 'rackspace':
            rackspace()

        f_up(cloud=cloud_type,
             region=region,
             instance_id=instance_id,
             access_key_id=access_key_id,
             secret_access_key=secret_access_key,
             username=username)
    else:
        env.user = C[cloud][distribution]['username']
        env.key_filename = C[cloud][distribution]['key_filename']

        # no state file around, lets create a new VM
        # and use defaults values we have in our config 'C' dictionary
        f_create_server(cloud=cloud,
                        region=C[cloud][distribution]['region'],
                        access_key_id=C[cloud][distribution]['access_key_id'],
                        secret_access_key=C[cloud][distribution][
                            'secret_access_key'],
                        distribution=distribution,
                        disk_name=C[cloud][distribution]['disk_name'],
                        disk_size=C[cloud][distribution]['disk_size'],
                        ami=C[cloud][distribution]['ami'],
                        key_pair=C[cloud][distribution]['key_pair'],
                        instance_type=C[cloud][distribution]['instance_type'],
                        instance_name=C[cloud][distribution]['instance_name'],
                        username=C[cloud][distribution]['username'],
                        security_groups=C[cloud][distribution][
                            'security_groups'],
                        tags=C[cloud][distribution]['tags'])


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

# We define a dictionary containing API secrets, disk sizes, base amis,
# and other bits and pieces that we will use for creating a new EC2 or Rackspace
# instance and authenticate over ssh.
C = {}
if 'ec2' in list_of_clouds:
    C['ec2'] = {
        'centos7': {
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
            'instance_name': 'jenkins_slave_centos7_ondemand',
            'description': 'jenkins_slave_centos7_ondemand',
            'key_filename': ec2_key_filename,
            'tags': {'name': 'jenkins_slave_centos7_ondemand'}
        },
        'ubuntu14.04': {
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
            'instance_name': 'jenkins_slave_ubuntu14_ondemand',
            'description': 'jenkins_slave_ubuntu14_ondemand',
            'key_filename': ec2_key_filename,
            'tags': {'name': 'jenkins_slave_ubuntu14_ondemand'}
        }
    }

if 'rackspace' in list_of_clouds:
    C['rackspace'] = {
        'centos7': {
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
            'description': 'jenkins_slave_centos7_ondemand',
            'public_key': rackspace_public_key,
            'auth_system': rackspace_auth_system,
            'tenant': rackspace_tenant_name,
            'auth_url': rackspace_auth_url,
            'key_filename': rackspace_key_filename,
            'tags': {'name': 'jenkins_slave_centos7_ondemand'}
        },
        'ubuntu14.04': {
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
            'description': 'jenkins_slave_ubuntu14_ondemand',
            'public_key': rackspace_public_key,
            'auth_system': rackspace_auth_system,
            'tenant': rackspace_tenant_name,
            'auth_url': rackspace_auth_url,
            'key_filename': rackspace_key_filename,
            'tags': {'name': 'jenkins_slave_ubuntu14_ondemand'}
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
