DOCKER_IMAGE_NAME ?= drbd9-tests
NOCACHE ?= false

# The 'all' and 'install' targets are used by lbtest.
# This rule can be removed once lbtest is fully replaced.
.DEFAULT_GOAL = all
all install uninstall:
	@$(MAKE) -C target $@

target/%:
	$(MAKE) -C target $*

clean:
	@$(MAKE) -C target clean

.PHONY: docker
docker:
	docker build --no-cache=$(NOCACHE) -t $(DOCKER_IMAGE_NAME) .
