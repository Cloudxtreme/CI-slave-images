# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et foldlevel=0

# fabric task file for building new CI slave images
#
# usage:
#       fab help
#
# state is kept locally in a file called state.json, it contains metadata
# related to the existing EC2 instance.
#
# the following environment variables must be set:
# AWS_AMI
# AWS_INSTANCE_TYPE
# AWS_ACCESS_KEY_ID
# AWS_ACCESS_KEY_FILENAME
# AWS_ACCESS_KEY_PAIR
# AWS_ACCESS_REGION
# AWS_SECRET_ACCESS_KEY


import os
import yaml
import sys
from time import sleep
from datetime import datetime
from fabric.api import sudo, task, env, run
from fabric.context_managers import cd, settings, hide
from fabric.contrib.files import (sed,
                                  append as file_append)

from bookshelf.api_v1 import (status as f_status,
                              up as f_up,
                              down as f_down,
                              destroy as f_destroy,
                              create_image as f_create_image,
                              create_server as f_create_server,
                              rackspace as f_rackspace,
                              ec2 as f_ec2)

from bookshelf.api_v1 import (add_epel_yum_repository,
                              add_usr_local_bin_to_path,
                              add_zfs_yum_repository,
                              dir_ensure,
                              yum_install_from_url,
                              file_attribs,
                              is_there_state,
                              log_green,
                              load_state_from_disk,
                              install_zfs_from_testing_repository,
                              install_os_updates,
                              disable_selinux,
                              disable_requiretty_on_sudoers,
                              disable_env_reset_on_sudo,
                              enable_firewalld_service,
                              add_firewalld_port,
                              install_docker,
                              install_centos_development_tools,
                              systemd,
                              yum_install,
                              install_system_gem,
                              update_system_pip_to_latest_pip,
                              wait_for_ssh,
                              create_docker_group,
                              git_clone,
                              ssh_session,
                              cache_docker_image_locally,
                              install_recent_git_from_source)

from cuisine import (user_ensure,
                     group_ensure,
                     group_user_ensure)


class MyCookbooks():
    """ collection of custom fabric tasks used in this fabfile.
        list them a-z if you must.
    """
    def add_user_to_docker_group(self):
        """ make sure the user running jenkins is part of the docker group """
        log_green('adding the user running jenkins into the docker group')
        data = load_state_from_disk()
        with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                      warn_only=True, capture=True):
            if 'centos' in data['username']:
                user_ensure('centos', home='/home/centos', shell='/bin/bash')
                group_ensure('docker', gid=55)
                group_user_ensure('docker', 'centos')

            if 'ubuntu' in data['username']:
                user_ensure('ubuntu', home='/home/ubuntu', shell='/bin/bash')
                group_ensure('docker', gid=55)
                group_user_ensure('docker', 'ubuntu')

    def check_for_missing_environment_variables(self):
        """ double checks that the minimum environment variables have been
            configured correctly.
        """
        env_var_missing = []
        for env_var in ['AWS_KEY_PAIR',
                        'AWS_KEY_FILENAME',
                        'AWS_SECRET_ACCESS_KEY',
                        'AWS_ACCESS_KEY_ID',
                        'OS_USERNAME',
                        'OS_TENANT_NAME',
                        'OS_PASSWORD',
                        'OS_AUTH_URL',
                        'OS_AUTH_SYSTEM',
                        'OS_REGION_NAME',
                        'OS_NO_CACHE']:
            if env_var not in os.environ:
                env_var_missing.append(env_var)

        if env_var_missing:
            print('the following environment variables must be set:')
            for env_var in env_var_missing:
                print(env_var)
            return True

    def create_etc_slave_config(self):
        """ /etc/slave_config is used by jenkins slave_plugin.
            it allows files to be copied from the master to the slave.
            These files are copied to /etc/slave_config on the slave.
        """
        # TODO: fix these permissions, likely ubuntu/centos/jenkins users
        # need read/write permissions.
        log_green('create /etc/slave_config')
        with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                      warn_only=True, capture=True):
            dir_ensure('/etc/slave_config', mode="777", use_sudo=True)

    def ec2(self):
        f_ec2()

    def fix_umask(self):
        """ fix an issue with the the build package process where it fails, due
            the files in the produced package have the wrong permissions.
        """
        with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                      warn_only=True, capture=True):

            sed('/etc/login.defs',
                'USERGROUPS_ENAB.*yes', 'USERGROUPS_ENAB no',
                use_sudo=True)

            sed('/etc/login.defs',
                'UMASK.*', 'UMASK  022',
                use_sudo=True)

            data = load_state_from_disk()

            homedir = '/home/' + data['username'] + '/'
            for f in [homedir + '.bash_profile',
                      homedir + '.bashrc']:
                file_append(filename=f, text='umask 022')
                file_attribs(f, mode=750, owner=data['username'])

    def install_nginx(self):
        """ installs nginx
            nginx is used for the packaging process.
            the acceptance tests will produce a rpm/deb package.
            that package is then made available on http so that the acceptance
            test node can connect to it as a yub/deb repository and download,
            install the package during the acceptance tests.
        """

        data = load_state_from_disk()
        if 'centos' in data['username']:
            yum_install(packages=['nginx'])
            systemd('nginx', start=False, unmask=True)
            systemd('nginx', start=True, unmask=True)
            enable_firewalld_service()
            add_firewalld_port('80/tcp', permanent=True)
        if 'ubuntu' in data['username']:
            sudo('apt-get -y install nginx')
            systemd('nginx', start=False, unmask=True)
            systemd('nginx', start=True, unmask=True)
            enable_firewalld_service()
            add_firewalld_port('80/tcp', permanent=True)
        # give it some time for the dockerd to restart
        sleep(20)

    def rackspace(self):
        f_rackspace()
        # Rackspace servers use root instead of the 'centos/ubuntu'
        # when they first boot.
        env.user = 'root'

    def segredos(self):
        secrets = yaml.load(open('segredos/ci-platform/all/all.yaml', 'r'))
        return secrets

    def symlink_sh_to_bash(self):
        """ jenkins seems to default to /bin/dash instead of bash
            on ubuntu. There is a shell config parameter that I haven't
            to set, so in order to force ubuntu nodes to execute jobs
            using bash, let's symlink /bin/sh -> /bin/bash
        """
        # read distribution from state file
        data = load_state_from_disk()
        if 'ubuntu' in data['username']:
            sudo('/bin/rm /bin/sh')
            sudo('/bin/ln -s /bin/bash /bin/sh')

    def bootstrap_jenkins_slave_centos7(self):
        # ec2 hosts get their ip addresses using dhcp, we need to know the new
        # ip address of our box before we continue our provisioning tasks.
        # we load the state from disk, and store the ip in ec2_host#
        ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
        with settings(host_string=ec2_host):
            install_os_updates(distribution='centos7')

            # make sure our umask is set to 022
            self.fix_umask()

            # ttys are tricky, lets make sure we don't need them
            disable_requiretty_on_sudoers()

            # when we sudo, we want to keep our original environment variables
            disable_env_reset_on_sudo()

            add_epel_yum_repository()

            install_centos_development_tools()

            # install the latest ZFS from testing
            add_zfs_yum_repository()
            yum_install_from_url(
                "http://archive.zfsonlinux.org/epel/zfs-release.el7.noarch.rpm",
                "zfs-release")
            install_zfs_from_testing_repository()

            # disable selinux()
            # note: will reboot the host for us if selinux is enabled
            disable_selinux()
            wait_for_ssh(load_state_from_disk()['ip_address'])

        # these are likely to happen after a reboot
        ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
        with settings(host_string=ec2_host):
            # brings up the firewall
            enable_firewalld_service()

            # we create a docker group ourselves, as we want to be part
            # of that group when the daemon first starts.
            create_docker_group()
            self.add_user_to_docker_group()
            install_docker()

            # ubuntu uses dash which causes jenkins jobs to fail
            self.symlink_sh_to_bash()

            # some flocker acceptance tests fail when we don't have
            # a know_hosts file
            sudo("touch /root/.ssh/known_hosts")

            # generate a id_rsa_flocker
            sudo("test -e  $HOME/.ssh/id_rsa_flocker || ssh-keygen -N '' "
                 "-f $HOME/.ssh/id_rsa_flocker")

            # and fix perms on /root/,ssh
            sudo("chmod -R 0600 /root/.ssh")

            # installs a bunch of required packages
            yum_install(packages=["kernel-devel",
                                  "kernel",
                                  "git",
                                  "python-devel",
                                  "python-tox",
                                  "python-virtualenv",
                                  "rpmdevtools",
                                  "rpmlint",
                                  "rpm-build",
                                  "docker-io",
                                  "libffi-devel",
                                  "@buildsys-build",
                                  "openssl-devel",
                                  "wget",
                                  "curl",
                                  "enchant",
                                  "python-pip",
                                  "java-1.7.0-openjdk-headless",
                                  "libffi-devel",
                                  "rpmlint",
                                  "ntp",
                                  "createrepo",
                                  "gettext-devel",
                                  "expat-devel",
                                  "curl-devel",
                                  "zlib-devel",
                                  "perl-devel",
                                  "openssl-devel",
                                  "nginx",
                                  "subversion-perl",
                                  "ruby-devel"])

            # TODO: this may not be needed, as packaging is done on a docker img
            install_system_gem('fpm')

            systemd(service='docker', restart=True)
            systemd(service='nginx', start=True, unmask=True)

            # cache some docker images locally to speed up some of our tests
            for docker_image in ['busybox',
                                 'openshift/busybox-http-app',
                                 'python:2.7-slim',
                                 'clusterhqci/fpm-ubuntu-trusty',
                                 'clusterhqci/fpm-ubuntu-vivid',
                                 'clusterhqci/fpm-centos-7']:
                cache_docker_image_locally(docker_image)

            # centos has a fairly old git, so we install the latest version
            # in every box.
            install_recent_git_from_source()
            add_usr_local_bin_to_path()

            # to use wheels, we want the latest pip
            update_system_pip_to_latest_pip()

            # cache the latest python modules and dependencies in the local
            # user cache
            git_clone('https://github.com/ClusterHQ/flocker.git', 'flocker')
            with cd('flocker'):
                run('pip install --quiet --user .')
                run('pip install --quiet --user "Flocker[dev]"')
                run('pip install --quiet --user python-subunit junitxml')

            # nginx is used during the acceptance tests, the VM built by
            # flocker provision will connect to the jenkins slave on p 80
            # and retrieve the just generated rpm/deb file
            self.install_nginx()

            # /etc/slave_config is used by the jenkins_slave plugin to
            # transfer files from the master to the slave
            self.create_etc_slave_config()


@task
def create_image():
    """ create ami/image for either AWS or Rackspace """
    (year, month, day, hour, mins,
     sec, wday, yday, isdst) = datetime.utcnow().timetuple()
    date = "%s%s%s%s%s" % (year, month, day, hour, mins)

    if is_there_state():
        data = load_state_from_disk()
        cloud_type = data['cloud_type']
        distribution = data['distribution'] + data['os_release']['VERSION_ID']
        access_key_id = C[cloud_type][distribution]['access_key_id']
        secret_access_key = C[cloud_type][distribution]['secret_access_key']

        f_create_image(cloud=cloud_type,
                       region=data['region'],
                       access_key_id=access_key_id,
                       secret_access_key=secret_access_key,
                       instance_id=data['id'],
                       name="jenkins_slave_template_centos7_" + date,
                       description='jenkins_slave_template_centos7')


@task
def destroy():
    """ destroy an existing instance """
    if is_there_state():
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
    if is_there_state():
        data = load_state_from_disk()
        region = data['region']
        cloud_type = data['cloud_type']
        distribution = data['distribution'] + data['os_release']['VERSION_ID']
        access_key_id = C[cloud_type][distribution]['access_key_id']
        secret_access_key = C[cloud_type][distribution]['secret_access_key']
        instance_id = data['id']
        env.key_filename = C[cloud_type][distribution]['key_filename']

        cookbook = MyCookbooks()
        if data['cloud_type'] == 'ec2':
            cookbook.ec2()
        if data['cloud_type'] == 'rackspace':
            cookbook.rackspace()
        f_down(cloud=cloud_type,
               instance_id=instance_id,
               region=region,
               access_key_id=access_key_id,
               secret_access_key=secret_access_key)


@task(default=True)
def help():
    """ help """
    print("""
          usage: fab <action> <action>

                 # shows this page
                 fab help

                 # does the whole thing in one go
                 fab it:cloud=<ec2|rackspace>,distribution=<centos7|ubuntu14>

                 # boots an existing instance
                 fab up

                 # creates a new instance
                 fab up:cloud=<ec2|rackspace>,distribution=<centos7|ubuntu14>

                 # installs packages on an existing instance
                 fab bootstrap:distribution=<centos7|ubuntu14>

                 # creates a new ami
                fab create_image

                 # destroy the box
                 fab destroy

                 # power down the box
                 fab down

                 # ssh to the instance
                 fab ssh

                 # execute a command on the instance
                 fab ssh:'ls -l'

                 metadata state is stored locally in state.json.
                 the following environment variables must be set:
                 # AWS_AMI
                 # AWS_INSTANCE_TYPE
                 # AWS_ACCESS_KEY_ID
                 # AWS_ACCESS_KEY_FILENAME
                 # AWS_ACCESS_KEY_PAIR
                 # AWS_ACCESS_REGION
                 # AWS_SECRET_ACCESS_KEY
                 # OS_USERNAME
                 # OS_TENANT_NAME
                 # OS_AUTH_SYSTEM
                 # OS_PASSWORD
                 # OS_AUTH_URL
                 # OS_REGION_NAME
                 # OS_NO_CACHE




          """)


@task
def it(cloud, distribution):
    """ runs the full stack """
    cookbook = MyCookbooks()
    if cloud == 'ec2':
        cookbook.ec2()
    if cloud == 'rackspace':
        cookbook.rackspace()

    up(cloud=cloud, distribution=distribution)
    bootstrap(distribution)

    create_image()
    destroy()


@task
def bootstrap(distribution=None):
    """ bootstraps an existing running instance """
    # if we get called without parameters, then we require a state.json file
    if (is_there_state() is False):
        help()
        sys.exit(1)

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

    cookbook = MyCookbooks()
    if distribution == 'centos7':
        cookbook.bootstrap_jenkins_slave_centos7()

    if distribution == 'ubuntu14':
        cookbook.bootstrap_jenkins_slave_ubuntu14()


@task
def status():
    """ returns current status of the instance """
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
            cookbook.ec2()
        if data['cloud_type'] == 'rackspace':
            cookbook.rackspace()

        f_status(cloud=cloud_type,
                 region=region,
                 instance_id=instance_id,
                 access_key_id=access_key_id,
                 secret_access_key=secret_access_key,
                 username=username)


@task
def ssh(*cli):
    """ opens an ssh connection to the instance """
    if is_there_state():
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
def up(cloud=None, distribution=None):
    """ boots a new instance on amazon or rackspace """

    # if we get called without parameters, then we require a state.json file
    if (cloud is None or distribution is None) and (is_there_state() is False):
        help()
        sys.exit(1)

    cookbook = MyCookbooks()

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
            cookbook.ec2()
        if data['cloud_type'] == 'rackspace':
            cookbook.rackspace()

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
cookbook = MyCookbooks()
# make sure we have all the required variables available in the environment
if cookbook.check_for_missing_environment_variables():
    exit(1)

# retrieve some of the secrets from the segredos dict
jenkins_plugin_dict = cookbook.segredos()[
    'env']['default']['jenkins']['clouds']['jclouds_plugin'][0]

# soaks up the environment variables
ec2_instance_type = os.getenv('AWS_INSTANCE_TYPE', 't2.micro')
ec2_key_filename = os.environ['AWS_KEY_FILENAME']  # path to ssh key
ec2_key_pair = os.environ['AWS_KEY_PAIR']
ec2_region = os.getenv('AWS_REGION', 'us-west-2')
ec2_secret_access_key = os.environ['AWS_SECRET_ACCESS_KEY']
ec2_access_key_id = os.environ['AWS_ACCESS_KEY_ID']
ec2_key_filename = os.environ['AWS_KEY_FILENAME']  # path to ssh key

rackspace_username = os.environ['OS_USERNAME']
rackspace_tenant_name = os.environ['OS_TENANT_NAME']
rackspace_password = os.environ['OS_PASSWORD']
rackspace_auth_url = os.getenv('OS_AUTH_URL',
                               'https://identity.api.rackspacecloud.com/v2.0/')
rackspace_auth_system = os.getenv('OS_AUTH_SYSTEM', 'rackspace')
rackspace_region = os.getenv('OS_REGION_NAME', 'DFW')
rackspace_flavor = '1GB Standard Instance'
rackspace_key_pair = os.environ['RACKSPACE_KEY_PAIR']
rackspace_public_key = jenkins_plugin_dict['publicKey'][0]
rackspace_key_filename = os.environ['RACKSPACE_KEY_FILENAME']  # path to ssh key

# define what your boxes should look like below
C = {
    'ec2': {
        'centos7': {
            'ami': 'ami-c7d092f7',
            'username': 'centos',
            'disk_name': '/dev/sda1',
            'disk_size': '40',
            'instance_type': ec2_instance_type,
            'key_pair': ec2_key_pair,
            'region': ec2_region,
            'secret_access_key': ec2_secret_access_key,
            'access_key_id': ec2_access_key_id,
            'security_groups': ['ssh'],
            'instance_name': 'jenkins_slave_centos7_template',
            'key_filename': ec2_key_filename,
            'tags': {'name': 'jenkins_slave_centos7_template'}
        },
    },
    'rackspace': {
        'centos7': {
            'ami': 'CentOS 7 (PVHVM)',
            'username': 'root',
            'disk_name': '',
            'disk_size': '',
            'instance_type': rackspace_flavor,
            'key_pair': rackspace_key_pair,
            'region': rackspace_region,
            'secret_access_key': rackspace_password,
            'access_key_id': rackspace_username,
            'security_groups': '',
            'instance_name': 'jenkins_slave_centos7_template',
            'public_key': rackspace_public_key,
            'auth_system': rackspace_auth_system,
            'tenant': rackspace_tenant_name,
            'auth_url': rackspace_auth_url,
            'key_filename': rackspace_key_filename,
            'tags': {'name': 'jenkins_slave_centos7_template'}
        }
    }
}

env.disable_known_hosts = True
env.use_ssh_config = True

# We store the state in a local file as we need to keep track of the
# ec2 instance id and ip_address so that we can run provision multiple times
if is_there_state() is False:
    pass
else:
    data = load_state_from_disk()
    env.hosts = data['ip_address']
    env.cloud = data['cloud_type']
