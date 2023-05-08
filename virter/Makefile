BASE_IMAGE_NAME ?=
VIRTER_BUILD_ID ?= 100

BASE_IMAGES := $(shell rq -t < vms.toml | jq -r '.vms[] | .base_image')
BASE_IMAGE_TARGETS := $(addprefix base_image_,$(BASE_IMAGES))

base_image_%:
	@printf "Building base image: $*\n"
	VM_JSON="$$(rq -t < vms.toml | jq '[.vms[] | select( .base_image == "$*" )] | first')" && \
	printf "Image definition: %s\n" "$$VM_JSON" && \
	get_key() { printf %s "$$VM_JSON" | jq -r ".$$1 // empty" ; } && \
	virter image build "$$(get_key metadata.SourceImage)" "$(or $(BASE_IMAGE_NAME),$*)" \
		--id $(VIRTER_BUILD_ID) \
		--set values.KernelRelease="$$(get_key metadata.KernelRelease)" \
		--set values.KernelRepositoryURL="$$(get_key metadata.KernelRepositoryURL)" \
		--set values.RepositoryDistribution="$$(get_key values.RepositoryDistribution)" \
		-p provision-base.toml

pull_source_images:
	IMAGES="$$(rq -t < vms.toml | jq -r '[.vms[].metadata.SourceImage] | unique[]')" && \
		parallel -k virter image pull {} $$LINBIT_DOCKER_REGISTRY/vm/{} ::: $$IMAGES

all_base_images: $(BASE_IMAGE_TARGETS)

print_base_images:
	@printf "%s\n" $(BASE_IMAGES)
