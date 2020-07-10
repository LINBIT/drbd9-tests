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
* `exxe`

```
virter image build ubuntu-focal-drbd-k40 ubuntu-focal-drbd-k40-t -p virter/provision-test.toml --set values.RepositoryURL=http://10.43.224.1:8020/repository/ubuntu-focal/ --set values.RepositoryDistribution=focal --set values.RepositoryPackages=drbd-module-5.4.0-40-generic=9.0.0.0369cc16dded15d28007cfd2e90776820f842890+5.4.0-40.44
```

### Start cluster

From the test image, a cluster can be started.

```
virter vm run --count 2 --id 130 ubuntu-focal-drbd-k40-t -w
```
