# Virter provisioning for DRBD test suite

## Usage

### Base image

The first provisioning stage prepares images with common dependencies
installed.

All images:
```
make all_base_images
```

Or just a specific image:
```
make base_image_ubuntu-focal-drbd-k40
```

### Test image

From the base image a test image can be built containing the packages to be tested.

Packages from the local `packages` directory will be installed. This directory
should contain `drbd-test-target.tgz`. The following components can be provided
as `rpm` or `deb` packages in this directory or via a repository.
* `drbd`
* `drbd-utils`

Packages to be installed from the repository should be specified using
`values.RepositoryPackages`. The package name and version should be separated
by `=`. This will be converted to `-` for `yum` based distributions.

An Ubuntu-based test image can be built using a comand command like:

```
virter image build ubuntu-focal-drbd-k40 ubuntu-focal-drbd-k40-t -p virter/provision-test.toml --set values.RepositoryURL=https://nexus.at.linbit.com/repository/ubuntu-focal/ --set values.RepositoryDistribution=focal --set values.DrbdVersion=9.0.0.0369cc16dded15d28007cfd2e90776820f842890
```

And similarly for RedHat-based images:

```
virter image build centos-8-drbd-k193 centos-8-drbd-k193-t -p provision-test.toml --set values.RepositoryURL=https://nexus.at.linbit.com/repository/rhel8/ --set values.DrbdVersion=9.0.0.0db548ca455a85569031337991f1527cbe34c437
```

### Start cluster

From the test image, a cluster can be started.

```
virter vm run --count 2 --id 130 ubuntu-focal-drbd-k40-t -w
```
