BASE_IMAGE_NAME ?=

BASE_IMAGES := $(shell rq -t < vms.toml | jq -r '.vms[] | .base_image')
BASE_IMAGE_TARGETS := $(addprefix base_image_,$(BASE_IMAGES))

base_image_%:
	@printf "Building base image: $*\n"
	VM_JSON="$$(rq -t < vms.toml | jq '[.vms[] | select( .base_image == "$*" )] | first')" && \
	printf "Image definition: %s\n" "$$VM_JSON" && \
	get_meta() { printf %s "$$VM_JSON" | jq -r ".metadata.$$1" ; } && \
	virter image build "$$(get_meta SourceImage)" "$(or $(BASE_IMAGE_NAME),$*)" \
		--set values.KernelRelease="$$(get_meta KernelRelease)" \
		--set values.KernelRepositoryURL="$$(get_meta KernelRepositoryURL)" \
		-p provision-base.toml

all_base_images: $(BASE_IMAGE_TARGETS)

print_base_images:
	@printf "%s\n" $(BASE_IMAGES)
