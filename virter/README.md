# Virter provisioning for DRBD test suite

## Usage

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
