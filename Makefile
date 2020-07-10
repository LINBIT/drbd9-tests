BUNDLE ?= drbd-test-bundle.tgz
DOCKER_IMAGE_NAME ?= drbd9-tests

# The 'all' and 'install' targets are used by lbtest.
# This rule can be removed once lbtest is fully replaced.
.DEFAULT_GOAL = all
all install uninstall:
	@$(MAKE) -C target $@

target/%:
	$(MAKE) -C target $*

bundle: target/drbd-test-target.tgz virter/vms.toml virter/tests.toml virter/provision-test.toml virter/run.toml
	tar -czf $(BUNDLE) $^

clean:
	@$(MAKE) -C target clean
	rm -f $(BUNDLE)

.PHONY: docker
docker:
	docker build -t $(DOCKER_IMAGE_NAME) .
