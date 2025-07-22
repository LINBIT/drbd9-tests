# Virter provisioning for DRBD test suite

## Usage

### Base image

The first provisioning stage prepares images with common dependencies
installed.

All images:
```
make -C virter/ all_base_images
```

Or just a specific image:
```
make -C virter/ base_image_ubuntu-noble-drbd-k39
```

### Test image

From the base image a test image can be built containing the packages to be tested.

Packages from the local `packages` directory will be installed. The following
components can be provided as `rpm` or `deb` packages in this directory or via
a repository.
* `drbd`
* `drbd-utils`

Packages to be installed from the repository should be specified using
`values.RepositoryPackages`. The package name and version should be separated
by `=`. This will be converted to `-` for `yum` based distributions.

An Ubuntu-based test image can be built using a comand command like:

```
virter image build ubuntu-noble-drbd-k39 ubuntu-noble-drbd-k39-a -p virter/provision-test.toml --set values.RepositoryURL=https://nexus.at.linbit.com/repository/ubuntu-noble/ --set values.RepositoryDistribution=noble --set values.DrbdVersion=9.2.14 --set 'values.RepositoryPackages=drbd-utils=9.31.0-*'
```

And similarly for RedHat-based images:

```
virter image build rhel-9-drbd-k427 rhel-9-drbd-k427-a -p virter/provision-test.toml --set values.RepositoryURL=https://nexus.at.linbit.com/repository/ci-yum/rhel9/ --set values.DrbdVersion=9.2.14 --set values.RepositoryPackages=drbd-utils=9.31.0
```

### Start cluster

From the test image, a cluster can be started.

```
virter vm run --count 2 --id 130 ubuntu-noble-drbd-k39-a -w
```
