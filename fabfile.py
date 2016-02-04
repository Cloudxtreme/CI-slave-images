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

from bookshelf.api_v1 import (up as f_up,
                              down as f_down,
                              destroy as f_destroy)


from bookshelf.api_v2.ec2 import (
    up_ec2,
    down_ec2,
    destroy_ec2,
    create_ami
)

from bookshelf.api_v2.rackspace import (
    create_rackspace_image,
    destroy_rackspace
)

from bookshelf.api_v2.logging_helpers import log_green, log_red
from bookshelf.api_v3.gce import GCE
from bookshelf.api_v1 import (ssh_session, create_gce_image)

from lib.mycookbooks import (setup_fab_env,
                             parse_config,
                             has_state,
                             load_state,
                             connect_to_cloud_provider)


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

        Metadata state is stored locally in .state.json.

        config.yaml contains a list of default configuration parameters.
          """)



def get_config():
    if not has_state():
        raise Exception("Can't get a config without a state file")
    saved_state = load_state()
    cloud = saved_state['cloud_type']
    config = parse_config(CLOUD_YAML_FILE[cloud])
    return config

def create_new_intance_from_config(cloud, distro):
    config = parse_config(CLOUD_YAML_FILE[cloud])
    if cloud == 'ec2':
        pass
    elif cloud == 'rackspace':
        pass
    elif cloud == 'gce':
        env.user = config['username']
        env.key_filename = config['public_key_filename']
        return GCE.create_from_config(config, distro)

def create_instance_from_saved_state():
    saved_state = load_state()
    cloud = saved_state['cloud_type']
    config = parse_config(CLOUD_YAML_FILE[cloud])
    if cloud == 'gce':
        env.user = config['username']
        env.key_filename = config['public_key_filename']
        return GCE.create_from_saved_state(config, saved_state)


@task
def create_image():
    """ create ami/image for either AWS, Rackspace or GCE """
    # (year, month, day, hour, mins,
    #  sec, wday, yday, isdst) = datetime.utcnow().timetuple()
    # date = "%s%s%s%s%s" % (year, month, day, hour, mins)

    # cloud, region, distro, k = cloud_region_distro_config()
    # connect_to_cloud_provider()

    # if cloud == 'ec2':
    #     image_id = create_ami(connection=env.connection,
    #                           region=region,
    #                           instance_id=env.config['instance_id'],
    #                           name=k['instance_name'] + date,
    #                           description=k['description'])

    # elif cloud == 'rackspace':
    #     image_id = create_rackspace_image(connection=env.connection,
    #                                       server_id=env.config['instance_id'],
    #                                       name=k['instance_name'] + date,
    #                                       description=k['description'])

    # elif cloud == 'gce':
    #     create_gce_image(description=k['description'],
    #                      project=k['project'],
    #                      instance_name=k['instance_name'] + date,
    #                      name=k['description'])
    datestr = datetime.utcnow().strftime("%Y%m%d%H%M")
    instance = create_from_saved_state()
    image_name = "{}-{}".format(instance.description, datestr)
    instance.create_image(image_name)

    log_green('created server image: %s' % image_name)


@task
def destroy():
    """ destroy an existing instance """
    # cloud, region, distro, k = cloud_region_distro_config()
    # connect_to_cloud_provider()

    # if cloud == 'ec2':
    #     destroy_ec2(connection=env.connection,
    #                 region=region,
    #                 instance_id=env.config['instance_id'])
    #     os.unlink('.state.json')

    # if cloud == 'rackspace':
    #     destroy_rackspace(connection=env.connection,
    #                       region=region,
    #                       instance_id=env.config['instance_id'])
    #     os.unlink('.state.json')

    # if cloud == 'gce':
    #     f_destroy(cloud='gce',
    #               zone=k['region'],
    #               project=k['project'],
    #               disk_name=env.config['instance_name'])
    #     os.unlink('.state.json')

    instance = create_from_saved_state()
    instance.destroy()
    os.unlink('.state.json')

@task
def down():
    """ halt an existing instance """
    instance = create_from_saved_state()
    instance.down()

    # cloud, region, distro, k = cloud_region_distro_config()
    # connect_to_cloud_provider()

    # if cloud == 'ec2':
    #     down_ec2(connection=env.connection,
    #              instance_id=env.config['instance_id'],
    #              region=region)

    # if cloud == 'rackspace':
    #     # rackspace doesn't provide a 'stop' method, it always terminates
    #     # the instance.
    #     destroy()



@task
def bootstrap():
    """ bootstraps an existing running instance

    :param string distribution: which OS to use 'centos7', 'ubuntu1404'
    """

    #cloud, region, distro, k = cloud_region_distro_config()

    #config, state = get_config_and_state()
    config = get_config()
    instance = create_from_saved_state()

    # distro = state['distro']
    # env.user = config['username']


    if 'centos7' in instance.distro:
        bootstrap_jenkins_slave_centos7(config, instance)

    if 'ubuntu14' in instance.distro:
        bootstrap_jenkins_slave_ubuntu14(config, instance)


@task
def status():
    """ returns current status of the instance """

    #cloud, region, distro, k = cloud_region_distro_config()
    #config, state = get_config_and_state()
    config = get_config()
    #data = env.config
    pp = PrettyPrinter(indent=4)
    pp.pprint(config)
    #pp.pprint(state)


@task
def ssh(*cli):
    """ opens an ssh connection to the instance

    :param string cli: the commands to run on the host
    """
    #config, state = get_config_and_state()
    config = get_config()

    instance = create_from_saved_state()

    ssh_session(key_filename=config['public_key_filename'],
                username=config['username'],
                ip_address=instance.ip_address,
                *cli)


@task
def tests():
    """ run tests against an existing instance """
    config = get_config()

    acceptance_tests(state['distro'], config)



@task
def up():
    """
    boots a new instance on the specified cloud provider
    """
    cloud = env.config['cloud']
    distro = env.config['distribution']

    if not has_state():
        create_from_config(cloud, distro)
    else:
        create_from_saved_state()


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
