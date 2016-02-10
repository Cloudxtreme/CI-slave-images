# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et

# fabric task file for building new CI slave images
#
# usage:
#       fab help
#


import os
from datetime import datetime
from fabric.api import task, env
from pprint import PrettyPrinter
import sys


from bookshelf.api_v1 import ssh_session
from bookshelf.api_v2.logging_helpers import log_green, log_red

from bookshelf.api_v3.cloud_instance import Distribution
from bookshelf.api_v3.ec2 import EC2Instance
from bookshelf.api_v3.gce import GCEInstance
from bookshelf.api_v3.rackspace import RackspaceInstance

from lib.mycookbooks import (setup_fab_env,
                             parse_config,
                             has_state,
                             load_state,
                             save_state)


from lib.bootstrap import (bootstrap_jenkins_slave_centos7,
                           bootstrap_jenkins_slave_ubuntu14)

from tests.acceptance import acceptance_tests


CLOUD_YAML_FILE = {
    'gce': 'gce.yaml',
    'ec2': 'ec2.yaml',
    'rackspace': 'rackspace.yaml'
}


@task(default=True)
def help():
    """ help """
    print("""
        usage: fab <action>[:arguments] <action>[:arguments]

        # shows this page
        $ fab help

        # boots an existing instance
        $ fab up

        # creates a new instance
        $ fab cloud:ec2|rackspace|gce region:us-west-2 distribution:centos7 up

        # installs packages on an existing instance
        $ fab bootstrap

        # creates a new ami
        $ fab create_image

        # list our images on the cloud provider
        $ fab list_images

        # delete a specific image from the cloud provider
        $ fab delete_image:ami-636c8d03

        # destroy the box
        $ fab destroy

        # power down the box (not supported on rackspace)
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
        ec2.yaml contains provisioning and configuration parameter

        For Rackspace:
        http://docs.rackspace.com/servers/api/v2/cs-gettingstarted/content/gs_env_vars_summary.html

        # OS_USERNAME
        # OS_PASSWORD
        # RACKSPACE_KEY_PAIR (the name of the rackspace KEY_PAIR to use)
        # RACKSPACE_PUBLIC_KEY_FILENAME (the full path to your public key file)
        # RACKSPACE_PRIVATE_KEY_FILENAME (the full path to your private key file)
        rackspace.yaml contains provisioning and configuration parameter

        For Google Compute Engine (GCE):

        # GCE_CREDENTIALS_PRIVATE_KEY (private key for the GCE service account
               or "" to use your oauth2 creds)
        # GCE_CREDENTIALS_EMAIL (email/id of the GCE service
      			     account or "" to use your oauth2 creds)
        # GCE_PUBLIC_KEY (Absolute file path to a public ssh key to use)
        # GCE_PRIVATE_KEY (Absolute file path to a private ssh key to use)
        # GCE_PROJECT (The GCE project to create the image in)
        gce.yaml contains provisioning and configuration parameter

        Metadata state is stored locally in .state.json.

          """)


def get_config():
    if not has_state():
        raise Exception("Can't get a config without a state file")
    saved_state = load_state()
    cloud = saved_state['cloud']
    config = parse_config(CLOUD_YAML_FILE[cloud])
    return config


def _get_cloud_instance_factory(cloud):
    if cloud == 'ec2':
        return EC2Instance
    elif cloud == 'rackspace':
        return RackspaceInstance
    elif cloud == 'gce':
        return GCEInstance
    else:
        raise KeyError('Unknown cloud %s' % cloud)


def _setup_fab_for_instance(instance):
    log_green('Setting fab environment to work with instance.')
    env.user = instance.username
    env.key_filename = instance.key_filename


def _save_state_from_instance(instance):
    state = {
        'cloud': instance.cloud_type,
        'region': instance.region,
        'distro': instance.distro.value,
        'state': instance.get_state()
    }
    save_state(state)


def _get_platform_config(cloud, region, distro):
    config = parse_config(CLOUD_YAML_FILE[cloud])

    # Get the configurations for all of the regions.
    region_configs = config['configs']['regions']

    # Get the region-specific configurations.
    region_config = region_configs.get(region)
    if not region_config:
        region_config = region_configs['default']

    # Get the different configurations for distributions in this region.
    instance_configs = region_config['distribution']

    # Get the specific configuration for this distribution in this region.
    instance_config = instance_configs.get(distro.value)
    if not instance_config:
        instance_config = instance_configs['default']

    return instance_config


def create_new_intance_from_config(cloud, distro, region):
    cloud_instance_factory = _get_cloud_instance_factory(cloud)

    log_green('Creating an instance from configuration...')
    instance = cloud_instance_factory.create_from_config(
        _get_platform_config(cloud, region, distro),
        distro, region)
    log_green('...Done')

    _setup_fab_for_instance(instance)
    _save_state_from_instance(instance)
    return instance


def create_instance_from_saved_state():
    saved_state = load_state()
    cloud = saved_state['cloud']
    specified_cloud = env.config.get('cloud')
    if specified_cloud and specified_cloud != cloud:
        log_red("The specified cloud: {} does not match the cloud "
                "specified in the saved state file: {}".format(
                    specified_cloud, cloud))
        sys.exit(1)

    distro = Distribution(saved_state['distro'])
    region = saved_state['region']

    config = _get_platform_config(cloud, region, distro)

    log_green('Reusing instance from saved state...')
    instance_factory = _get_cloud_instance_factory(cloud)
    instance = instance_factory.create_from_saved_state(
        config, saved_state['state'])
    log_green('...Done')

    _setup_fab_for_instance(instance)
    _save_state_from_instance(instance)

    specified_distribution = env.config.get('distribution')
    if (specified_distribution and
            specified_distribution != instance.distro.value):
        log_red("The specified distribution: {} does not match the distro "
                "specified in the saved state file: {}".format(
                    specified_distribution, instance.distro.value))
        sys.exit(1)
    return instance


@task
def create_image():
    """ create ami/image for either AWS, Rackspace or GCE """
    datestr = datetime.utcnow().strftime("%Y%m%d%H%M")
    instance = create_instance_from_saved_state()
    image_name = "{}-{}".format(instance.image_basename, datestr)
    image_id = instance.create_image(image_name)
    log_green('Created server image {}: {}'.format(image_name, image_id))

    # GCE shuts the instance down before creating an image. In the case where
    # the instance comes back up with a different IP address, we need to
    # re-sync fab and the save state.
    _setup_fab_for_instance(instance)
    _save_state_from_instance(instance)


@task
def destroy():
    """ destroy an existing instance """
    instance = create_instance_from_saved_state()
    instance.destroy()
    os.unlink('.state.json')


@task
def down():
    """ halt an existing instance """
    instance = create_instance_from_saved_state()
    instance.down()


@task
def bootstrap():
    """ bootstraps an existing running instance """
    instance = create_instance_from_saved_state()

    if instance.distro == Distribution.CENTOS7:
        bootstrap_jenkins_slave_centos7(instance)

    if instance.distro == Distribution.UBUNTU1404:
        bootstrap_jenkins_slave_ubuntu14(instance)


@task
def status():
    """ returns current status of the instance """
    config = get_config()
    pp = PrettyPrinter(indent=4)
    pp.pprint(config)
    if has_state():
        state = load_state()
        pp.pprint(state)


@task
def ssh(*cli):
    """ opens an ssh connection to the instance

    :param string cli: the commands to run on the host
    """
    instance = create_instance_from_saved_state()

    ssh_session(key_filename=instance.key_filename,
                username=instance.username,
                ip_address=instance.ip_address,
                *cli)


@task
def list_images():
    """ List images for the cloud provider """
    instance = create_instance_from_saved_state()
    instance.list_images()


@task
def delete_image(image_id):
    """ Delete an image. Todo, don't use an instance """
    instance = create_instance_from_saved_state()
    instance.delete_image(image_id)


@task
def tests():
    """ run tests against an existing instance """
    instance = create_instance_from_saved_state()
    acceptance_tests(instance)


@task
def up():
    """
    boots a new instance on the specified cloud provider
    """
    if not has_state():
        cloud = env.config['cloud']
        distro = Distribution(env.config['distribution'])
        region = env.config['region']
        create_new_intance_from_config(cloud, distro, region)
    else:
        create_instance_from_saved_state()


@task
def cloud(cloud_provider):
    env.config['cloud'] = cloud_provider


@task
def distribution(linux_distro):
    env.config['distribution'] = linux_distro


@task
def region(cloud_region):
    env.config['region'] = cloud_region


"""
    ___main___
"""

setup_fab_env()
