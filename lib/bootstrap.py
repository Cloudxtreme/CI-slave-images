# vim: ai ts=4 sts=4 et sw=4 ft=python fdm=indent et foldlevel=0


from fabric.api import sudo, env, run
from fabric.context_managers import settings, cd
from bookshelf.api_v1 import (add_epel_yum_repository,
                              add_usr_local_bin_to_path,
                              add_zfs_yum_repository,
                              apt_install,
                              apt_install_from_url,
                              yum_install_from_url,
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
                              install_centos_development_tools,
                              reboot,
                              systemd,
                              yum_install,
                              install_system_gem,
                              update_system_pip_to_latest_pip,
                              wait_for_ssh,
                              create_docker_group,
                              git_clone,
                              cache_docker_image_locally,
                              install_recent_git_from_source)

from lib.mycookbooks import (symlink_sh_to_bash,
                             fix_umask,
                             create_etc_slave_config,
                             install_python_pypy,
                             add_user_to_docker_group,
                             install_docker,
                             local_docker_images,
                             upgrade_kernel_and_grub,
                             fix_skb_rides_the_rocket,
                             install_nginx)


def bootstrap(distribution):
    # ec2 hosts get their ip addresses using dhcp, we need to know the new
    # ip address of our box before we continue our provisioning tasks.
    # we load the state from disk, and store the ip in ec2_host#
    ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
    with settings(host_string=ec2_host):
        install_os_updates(distribution=distribution)

        if 'centos' in distribution:
            add_epel_yum_repository()

            install_centos_development_tools()

            # installs a bunch of required packages
            yum_install(packages=centos7_required_packages())

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
                "http://archive.zfsonlinux.org/epel/"
                "zfs-release.el7.noarch.rpm",
                "zfs-release")
            install_zfs_from_testing_repository()

            # brings up the firewall
            enable_firewalld_service()

            # note: will reboot the host for us if selinux is disabled
            enable_selinux()
            wait_for_ssh(load_state_from_disk()['ip_address'])

        if 'ubuntu' in distribution:
            enable_apt_repositories('deb',
                                    'http://archive.ubuntu.com/ubuntu',
                                    '$(lsb_release -sc)',
                                    'main universe restricted multiverse')

            install_ubuntu_development_tools()

            # installs a bunch of required packages
            apt_install(packages=ubuntu14_required_packages())

            # install the latest ZFS from testing
            # add_zfs_ubuntu_repository()
            # install_zfs_from_testing_repository()

            # ubuntu uses dash which causes jenkins jobs to fail
            symlink_sh_to_bash()

    # these are likely to happen after a reboot
    ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
    with settings(host_string=ec2_host):

        # make sure our umask is set to 022
        fix_umask()

        # ttys are tricky, lets make sure we don't need them
        disable_requiretty_on_sudoers()
        disable_requiretty_on_sshd_config()

        # when we sudo, we want to keep our original environment variables
        disable_env_reset_on_sudo()

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

        # we create a docker group ourselves, as we want to be part
        # of that group when the daemon first starts.
        create_docker_group()
        add_user_to_docker_group()
        install_docker()

        if 'centos' in distribution:
            systemd(service='docker', restart=True)
            systemd(service='nginx', start=True, unmask=True)

        if 'ubuntu' in distribution:
            apt_install_from_url('rpmlint',
                                 'https://launchpad.net/ubuntu/+archive/'
                                 'primary/+files/rpmlint_1.5-1_all.deb')

        # cache some docker images locally to speed up some of our tests
        for docker_image in local_docker_images():
            cache_docker_image_locally(docker_image)

        # we have a fairly old git, so we install the latest version
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
            run('pip install --quiet --user '
                ' --process-dependency-links ".[dev]"')
            run('pip install --quiet --user python-subunit junitxml')

        # nginx is used during the acceptance tests, the VM built by
        # flocker provision will connect to the jenkins slave on p 80
        # and retrieve the just generated rpm/deb file
        install_nginx()

        # /etc/slave_config is used by the jenkins_slave plugin to
        # transfer files from the master to the slave
        create_etc_slave_config()

        # installs python-pypy onto /opt/python-pypy/2.6.1 and symlinks it
        # to /usr/local/bin/pypy
        install_python_pypy('2.6.1')


def bootstrap_jenkins_slave_centos7():
    # ec2 hosts get their ip addresses using dhcp, we need to know the new
    # ip address of our box before we continue our provisioning tasks.
    # we load the state from disk, and store the ip in ec2_host#
    ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
    with settings(host_string=ec2_host):
        install_os_updates(distribution='centos7')

        # make sure our umask is set to 022
        fix_umask()

        # ttys are tricky, lets make sure we don't need them
        disable_requiretty_on_sudoers()

        # when we sudo, we want to keep our original environment variables
        disable_env_reset_on_sudo()

        add_epel_yum_repository()

        install_centos_development_tools()

        # installs a bunch of required packages
        yum_install(packages=centos7_required_packages())

        # installing the source for the centos kernel is a bit of an odd
        # process these days.
        yum_install_from_url(
            "http://vault.centos.org/7.1.1503/updates/Source/SPackages/"
            "kernel-3.10.0-229.11.1.el7.src.rpm",
            "non-available-kernel-src")
        fix_skb_rides_the_rocket()

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
        add_user_to_docker_group()
        install_docker()

        # ubuntu uses dash which causes jenkins jobs to fail
        symlink_sh_to_bash()

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
        for docker_image in local_docker_images():
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
            run('pip install --quiet '
                '--user --process-dependency-links ".[dev]"')
            run('pip install --quiet --user python-subunit junitxml')

        # nginx is used during the acceptance tests, the VM built by
        # flocker provision will connect to the jenkins slave on p 80
        # and retrieve the just generated rpm/deb file
        install_nginx()

        # /etc/slave_config is used by the jenkins_slave plugin to
        # transfer files from the master to the slave
        create_etc_slave_config()

        # installs python-pypy onto /opt/python-pypy/2.6.1 and symlinks it
        # to /usr/local/bin/pypy
        install_python_pypy('2.6.1')


def bootstrap_jenkins_slave_ubuntu14():
    # ec2 hosts get their ip addresses using dhcp, we need to know the new
    # ip address of our box before we continue our provisioning tasks.
    # we load the state from disk, and store the ip in ec2_host#
    ec2_host = "%s@%s" % (env.user, load_state_from_disk()['ip_address'])
    with settings(host_string=ec2_host):
        install_os_updates(distribution='ubuntu14.04')
        # we want to be running the latest kernel
        upgrade_kernel_and_grub(do_reboot=True)
        wait_for_ssh(load_state_from_disk()['ip_address'])

        enable_apt_repositories('deb',
                                'http://archive.ubuntu.com/ubuntu',
                                '$(lsb_release -sc)',
                                'main universe restricted multiverse')

        # make sure our umask is set to 022
        fix_umask()

        # ttys are tricky, lets make sure we don't need them
        disable_requiretty_on_sudoers()
        disable_requiretty_on_sshd_config()

        # when we sudo, we want to keep our original environment variables
        disable_env_reset_on_sudo()

        install_ubuntu_development_tools()

        # installs a bunch of required packages
        apt_install(packages=ubuntu14_required_packages())

        # install the latest ZFS from testing
        # add_zfs_ubuntu_repository()
        # install_zfs_from_testing_repository()

        # we create a docker group ourselves, as we want to be part
        # of that group when the daemon first starts.
        create_docker_group()
        add_user_to_docker_group()
        install_docker()

        # ubuntu uses dash which causes jenkins jobs to fail
        symlink_sh_to_bash()

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
        for docker_image in local_docker_images():
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
        install_nginx()

        # /etc/slave_config is used by the jenkins_slave plugin to
        # transfer files from the master to the slave
        create_etc_slave_config()

        # installs python-pypy onto /opt/python-pypy/2.6.1 and symlinks it
        # to /usr/local/bin/pypy
        install_python_pypy('2.6.1')

        fix_skb_rides_the_rocket()


def centos7_required_packages():
    return ["kernel-devel",
            "kernel",
            "ncurses-devel",
            "hmaccalc",
            "zlib-devel",
            "binutils-devel",
            "elfutils-libelf-devel",
            "ethtool",
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
            "ruby-devel"]


def ubuntu14_required_packages():
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
            "ethtool",
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
