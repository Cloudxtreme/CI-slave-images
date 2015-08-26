# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et foldlevel=0

# fabric task file for building new CI slave images
#
# usage:
#       fab help
#

import os
import yaml
import re
import sys
from time import sleep
from datetime import datetime
from envassert import (file,
                       process,
                       package,
                       user,
                       group,
                       detect,
                       port)
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
                              apt_install,
                              apt_install_from_url,
                              dir_ensure,
                              yum_install_from_url,
                              file_attribs,
                              is_there_state,
                              log_green,
                              load_state_from_disk,
                              install_zfs_from_testing_repository,
                              install_os_updates,
                              install_ubuntu_development_tools,
                              enable_selinux,
                              disable_requiretty_on_sudoers,
                              disable_env_reset_on_sudo,
                              disable_requiretty_on_sshd_config,
                              enable_firewalld_service,
                              enable_apt_repositories,
                              add_firewalld_port,
                              install_docker,
                              install_centos_development_tools,
                              reboot,
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

    def acceptance_tests(self,
                         cloud,
                         region,
                         instance_id,
                         access_key_id,
                         secret_access_key,
                         distribution,
                         username):

        if 'ubuntu' in distribution.lower():
            self.acceptance_tests_ubuntu14(cloud,
                                           region,
                                           instance_id,
                                           access_key_id,
                                           secret_access_key,
                                           distribution,
                                           username)

        if 'centos' in distribution.lower():
            self.acceptance_tests_centos7(cloud,
                                          region,
                                          instance_id,
                                          access_key_id,
                                          secret_access_key,
                                          distribution,
                                          username)

    def acceptance_tests_centos7(self,
                                 cloud,
                                 region,
                                 instance,
                                 access_key_id,
                                 secret_access_key,
                                 distribution,
                                 username):

        ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
        with settings(host_string=ec2_host):

            env.platform_family = detect.detect()

            log_green('check that /bin/sh is symlinked to bash')
            assert file.is_link("/bin/sh")

            # TODO: is this required on centos?
            log_green('check that our umask matches 022')
            # assert command.is_work('su - centos -c "umask | grep 022"')

            log_green("check that tty are not required when sudo'ing")
            assert sudo('grep "^\#Defaults.*requiretty" /etc/sudoers')

            log_green('check that the environment is not reset on sudo')
            assert sudo("sudo grep "
                        "'Defaults:\%wheel\ \!env_reset\,\!secure_path'"
                        " /etc/sudoers")

            log_green('assert that EPEL is installed')
            assert package.installed('epel-release')

            # TODO:
            # assert that centos developments tools is installed

            log_green('assert that required rpm packages are installed')
            for pkg in self.centos7_required_packages():
                if '@' in pkg:
                    continue
                log_green(' checking package: %s' % pkg)
                assert package.installed(pkg)

            log_green('check that the zfs repository is installed')
            assert package.installed('zfs-release')

            log_green('check that zfs from testing repository is installed')
            assert run(
                'grep "SPL_DKMS_DISABLE_STRIP=y" /etc/sysconfig/spl')
            assert run(
                'grep "ZFS_DKMS_DISABLE_STRIP=y" /etc/sysconfig/zfs')
            assert package.installed("zfs")
            assert run('lsmod |grep zfs')

            log_green('check that SElinux is enforcing')
            assert sudo('getenforce | grep -i "enforcing"')

            log_green('check that firewalld is enabled')
            assert sudo("systemctl is-enabled firewalld")

            log_green('check that centos is part of group docker')
            assert user.exists("centos")
            assert group.is_exists("docker")
            assert user.is_belonging_group("centos", "docker")

            log_green('check that nginx is running')
            assert package.installed('nginx')
            assert port.is_listening(80, "tcp")
            assert process.is_up("nginx") is True
            assert sudo("systemctl is-enabled nginx")

            log_green('check that docker is running')
            assert sudo('rpm -q docker-engine | grep "1.8."')
            assert process.is_up("docker") is True
            assert sudo("systemctl is-enabled docker")

            log_green('assert that /bin/sh is symlinked to /bin/bash')
            assert run('ls -l /bin/sh | grep bash')

            log_green('check that /root/.ssh/know_hosts exists')
            assert '-rw-------. 1 root root' in sudo(
                "ls -l /root/.ssh/known_hosts")

            log_green('check that fpm is installed')
            assert 'fpm' in sudo('gem list')

            log_green('check that images have been downloaded locally')
            for image in self.local_docker_images():
                log_green(' checking %s' % image)
                if ':' in image:
                    parts = image.split(':')
                    expression = parts[0] + '.*' + parts[1]
                    assert re.search(expression, run('docker images'))
                else:
                    assert image in run('docker images')

            log_green('check that git is installed locally')
            assert file.exists("/usr/local/bin/git")

            log_green('check that /usr/local/bin is in path')
            assert '/usr/local/bin/git' in run('which git')

            log_green('check that pip is the latest version')
            assert '7.1.' in run('pip --version')

            log_green('check that /etc/slave_config exists')
            assert file.dir_exists("/etc/slave_config")
            assert file.mode_is("/etc/slave_config", "777")

    def acceptance_tests_ubuntu14(self,
                                  cloud,
                                  region,
                                  instance,
                                  access_key_id,
                                  secret_access_key,
                                  distribution,
                                  username):

        ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
        with settings(host_string=ec2_host):

            env.platform_family = detect.detect()

            log_green('check that /bin/sh is symlinked to bash')
            assert 'bash' in run('ls -l /bin/sh')

            log_green('check that our umask matches 022')
            assert '022' in run('umask')

            log_green('check that docker is enabled')
            assert 'docker' in run('ls -l /etc/init')

            log_green("check that tty are not required when sudo'ing")
            assert sudo('grep -v "^Defaults.*requiretty" /etc/sudoers')

            log_green('check that the environment is not reset on sudo')
            assert sudo("sudo grep "
                        "'Defaults:\%wheel\ \!env_reset\,\!secure_path'"
                        " /etc/sudoers")

            log_green('assert that required deb packages are installed')
            for pkg in self.ubuntu14_required_packages():
                log_green(' checking package: %s' % pkg)
                assert package.installed(pkg)

            log_green('check that ubuntu is part of group docker')
            assert user.exists("ubuntu")
            assert group.is_exists("docker")
            assert user.is_belonging_group("ubuntu", "docker")

            log_green('check that nginx is running')
            assert package.installed('nginx')
            assert port.is_listening(80, "tcp")
            assert process.is_up("nginx") is True
            assert 'nginx' in run('ls -l /etc/init.d/')

            log_green('check that docker is running')
            assert sudo('docker --version | grep "1.8."')
            assert process.is_up("docker") is True

            log_green('assert that /bin/sh is symlinked to /bin/bash')
            assert run('ls -l /bin/sh | grep bash')

            log_green('check that /root/.ssh/know_hosts exists')
            assert '-rw------- 1 root root' in sudo(
                "ls -l /root/.ssh/known_hosts")

            log_green('check that fpm is installed')
            assert 'fpm' in sudo('gem list')

            log_green('check that images have been downloaded locally')
            for image in self.local_docker_images():
                log_green(' checking %s' % image)
                if ':' in image:
                    parts = image.split(':')
                    expression = parts[0] + '.*' + parts[1]
                    assert re.search(expression, run('docker images'))
                else:
                    assert image in run('docker images')

            log_green('check that git is installed locally')
            assert file.exists("/usr/local/bin/git")

            log_green('check that /usr/local/bin is in path')
            assert '/usr/local/bin/git' in run('which git')

            log_green('check that pip is the latest version')
            assert '7.1.' in run('pip --version')

            log_green('check that /etc/slave_config exists')
            assert file.dir_exists("/etc/slave_config")
            assert file.mode_is("/etc/slave_config", "777")

    def add_user_to_docker_group(self):
        """ make sure the user running jenkins is part of the docker group """
        log_green('adding the user running jenkins into the docker group')
        data = load_state_from_disk()
        with settings(hide('warnings', 'running', 'stdout', 'stderr'),
                      warn_only=True, capture=True):
            if 'centos' in data['distribution']:
                user_ensure('centos', home='/home/centos', shell='/bin/bash')
                group_ensure('docker', gid=55)
                group_user_ensure('docker', 'centos')

            if 'ubuntu' in data['distribution']:
                user_ensure('ubuntu', home='/home/ubuntu', shell='/bin/bash')
                group_ensure('docker', gid=55)
                group_user_ensure('docker', 'ubuntu')

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

            # installs a bunch of required packages
            yum_install(packages=self.centos7_required_packages())

            # installing the source for the centos kernel is a bit of an odd
            # process these days.
            yum_install_from_url(
                "http://vault.centos.org/7.1.1503/updates/Source/SPackages/"
                "kernel-3.10.0-229.11.1.el7.src.rpm",
                "non-available-kernel-src")

            # we want to be running the latest kernel before installing ZFS
            # so, lets reboot and make sure we do.
            with settings(warn_only=True):
                reboot()
            wait_for_ssh(load_state_from_disk()['ip_address'])

            # install the latest ZFS from testing
            add_zfs_yum_repository()
            yum_install_from_url(
                "http://archive.zfsonlinux.org/epel/zfs-release.el7.noarch.rpm",
                "zfs-release")
            install_zfs_from_testing_repository()

            # note: will reboot the host for us if selinux is disabled
            enable_selinux()
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

            # TODO: this may not be needed, as packaging is done on a docker img
            install_system_gem('fpm')

            systemd(service='docker', restart=True)
            systemd(service='nginx', start=True, unmask=True)

            # cache some docker images locally to speed up some of our tests
            for docker_image in self.local_docker_images():
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

    def bootstrap_jenkins_slave_ubuntu14(self):
        # ec2 hosts get their ip addresses using dhcp, we need to know the new
        # ip address of our box before we continue our provisioning tasks.
        # we load the state from disk, and store the ip in ec2_host#
        ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
        with settings(host_string=ec2_host):
            install_os_updates(distribution='ubuntu14.04')

            enable_apt_repositories('deb',
                                    'http://archive.ubuntu.com/ubuntu',
                                    '$(lsb_release -sc)',
                                    'main universe restricted multiverse')

            # make sure our umask is set to 022
            self.fix_umask()

            # ttys are tricky, lets make sure we don't need them
            disable_requiretty_on_sudoers()
            disable_requiretty_on_sshd_config()

            # when we sudo, we want to keep our original environment variables
            disable_env_reset_on_sudo()

            install_ubuntu_development_tools()

            # installs a bunch of required packages
            apt_install(packages=self.ubuntu14_required_packages())

            # install the latest ZFS from testing
            # add_zfs_ubuntu_repository()
            # install_zfs_from_testing_repository()

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

            apt_install_from_url('rpmlint',
                                 'https://launchpad.net/ubuntu/+archive/'
                                 'primary/+files/rpmlint_1.5-1_all.deb')

            # TODO: this may not be needed, as packaging is done on a docker img
            install_system_gem('fpm')

            # systemd(service='docker', restart=True)
            # systemd(service='nginx', start=True, unmask=True)

            # cache some docker images locally to speed up some of our tests
            for docker_image in self.local_docker_images():
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

    def centos7_required_packages(self):
        return ["kernel-devel",
                "kernel",
                "ncurses-devel",
                "hmaccalc",
                "zlib-devel",
                "binutils-devel",
                "elfutils-libelf-devel",
                "rpm-build",
                "redhat-rpm-config",
                "asciidoc",
                "perl-ExtUtils-Embed",
                "audit-libs-devel",
                "elfutils-devel",
                "newt-devel",
                "numactl-devel",
                "pciutils-devel",
                "pesign",
                "xmlto",
                "git",
                "python-devel",
                "python-tox",
                "python-virtualenv",
                "rpmdevtools",
                "rpmlint",
                "rpm-build",
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
                "libcurl-devel",
                "zlib-devel",
                "perl-devel",
                "openssl-devel",
                "nginx",
                "subversion-perl",
                "docker-selinux",
                "ruby-devel"]

    def ubuntu14_required_packages(self):
        return ["apt-transport-https",
                "software-properties-common",
                "build-essential",
                "python-virtualenv",
                "desktop-file-utils",
                "git",
                "python-dev",
                "python-tox",
                "python-virtualenv",
                "libffi-dev",
                "libssl-dev",
                "wget",
                "curl",
                "enchant",
                "openjdk-7-jre-headless",
                "libffi-dev",
                "lintian",
                "ntp",
                "rpm2cpio",
                "createrepo",
                # "gettext-dev",
                "libexpat1-dev",
                "libcurl4-openssl-dev",
                "zlib1g-dev",
                "libwww-curl-perl",
                "libssl-dev",
                "nginx",
                "libsvn-perl",
                "ruby-dev"]

    def check_for_missing_environment_variables(self, cloud_type=[]):
        """ double checks that the minimum environment variables have been
            configured correctly.
        """
        env_var_missing = []

        cloud_vars = {'ec2': ['AWS_KEY_PAIR',
                              'AWS_KEY_FILENAME',
                              'AWS_SECRET_ACCESS_KEY',
                              'AWS_ACCESS_KEY_ID'],

                      'rackspace': ['OS_USERNAME',
                                    'OS_TENANT_NAME',
                                    'OS_PASSWORD',
                                    'OS_AUTH_URL',
                                    'OS_AUTH_SYSTEM',
                                    'OS_REGION_NAME',
                                    'RACKSPACE_KEY_PAIR',
                                    'RACKSPACE_KEY_FILENAME',
                                    'OS_NO_CACHE']
                      }

        for cloud in cloud_type:
            for env_var in cloud_vars[cloud]:
                if env_var not in os.environ:
                    env_var_missing.append(env_var)

        if env_var_missing:
            return False

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

    def get_cloud_environment(self, string):
        """
            returns the cloud type from a fab execution string:
            fab it:cloud=rackspace,distribution=centos7
        """
        clouds = []
        tasks = string.split(' ')
        for _task in tasks:
            if 'cloud=ec2' in _task:
                clouds.append('ec2')
            if 'cloud=rackspace' in _task:
                clouds.append('rackspace')
        return clouds

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
            # systemd('nginx', start=False, unmask=True)
            # systemd('nginx', start=True, unmask=True)
            # enable_firewalld_service()
            # add_firewalld_port('80/tcp', permanent=True)
        # give it some time for the dockerd to restart
        sleep(20)

    def local_docker_images(self):
            return ['busybox',
                    'openshift/busybox-http-app',
                    'python:2.7-slim',
                    'clusterhqci/fpm-ubuntu-trusty',
                    'clusterhqci/fpm-ubuntu-vivid',
                    'clusterhqci/fpm-centos-7']

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
        if 'ubuntu' in data['distribution'].lower():
            sudo('/bin/rm /bin/sh')
            sudo('/bin/ln -s /bin/bash /bin/sh')


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
            # AWS_ACCESS_KEY_FILENAME
            # AWS_ACCESS_KEY_PAIR
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
            # RACKSPACE_KEY_PAIR
            # RACKSPACE_KEY_FILENAME
            # OS_AUTH_SYSTEM (optional)
            # OS_AUTH_URL (optional)
            # OS_REGION_NAME (optional)

            metadata state is stored locally in state.json.
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
    tests()
    create_image()
    destroy()


@task
def bootstrap(distribution=None):
    """ bootstraps an existing running instance """

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

    if 'ubuntu14.04' in distribution:
        cookbook.bootstrap_jenkins_slave_ubuntu14()


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
        cookbook.ec2()
    if data['cloud_type'] == 'rackspace':
        cookbook.rackspace()

    cookbook.acceptance_tests(cloud=cloud_type,
                              region=region,
                              instance_id=instance_id,
                              access_key_id=access_key_id,
                              secret_access_key=secret_access_key,
                              distribution=distribution,
                              username=username)


@task
def up(cloud=None, distribution=None):
    """ boots a new instance on amazon or rackspace """

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
    list_of_clouds = cookbook.get_cloud_environment(' '.join(sys.argv))

if list_of_clouds == []:
    # sounds like we are asking for a task that require cloud environment
    # variables and we don't have them defined, lets inform the user what
    # variables we are looking for.
    help()
    exit(1)

# right, we have a 'cloud_type' in list_of_clouds, lets find out if the env
# variables we need for that cloud have been defined.
if cookbook.check_for_missing_environment_variables(list_of_clouds) is False:
    help()
    exit(1)

# retrieve some of the secrets from the segredos dict
jenkins_plugin_dict = cookbook.segredos()[
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
                                'https://identity.api.rackspacecloud.com/v2.0/')
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
            'disk_size': '40',
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
            'ami': 'ami-bddbcf8d',
            'username': 'ubuntu',
            'disk_name': '/dev/sda1',
            'disk_size': '40',
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
            'disk_size': '',
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
            'disk_size': '',
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
# Let's disable know_hosts, since on Clouds that behaviour can get in the
# way as we continuosly destroy/create boxes.
env.disable_known_hosts = True
env.use_ssh_config = True

# We store the state in a local file as we need to keep track of the
# ec2 instance id and ip_address so that we can run provision multiple times
# By using some metadata locally about the VM we get a similar workflow to
# vagrant (up, down, destroy, bootstrap).
if is_there_state() is False:
    pass
else:
    data = load_state_from_disk()
    env.hosts = data['ip_address']
    env.cloud = data['cloud_type']
