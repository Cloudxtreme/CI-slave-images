contains fabric code to build the CI slave images.

usage:

clone the following repos:

     git clone git@github.com:ClusterHQ/segredos.git segredos

export the following environment variables:

    export AWS_ACCESS_KEY_ID=
    export AWS_SECRET_ACCESS_KEY=
    export AMAZON_ACCESS_KEY_ID=
    export AMAZON_SECRET_ACCESS_KEY=
    export AWS_ACCESS_KEY=
    export AWS_SECRET_KEY=

    export OS_USERNAME=
    export OS_TENANT_NAME=
    export OS_AUTH_SYSTEM=
    export OS_PASSWORD=
    export OS_AUTH_URL=
    export OS_REGION_NAME=
    export OS_NO_CACHE=

create your virtualenv:

    virtualenv2 venv
    . venv/bin/activate
    venv/bin/pip2 install -r requirements.txt

then execute as:

    venv/bin/fab aws it
    venv/bin/fab rackspace it


The fab code should bootstrap an AWS/Rackspace instance,
provision it and bake an image before deleting the original instance.