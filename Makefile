DOCKER_IMAGE_NAME ?= drbd9-tests
NOCACHE ?= false

DRBD_TESTS_DIR ?= tests
VMSHED_TEST_SELECTION ?= ci
DRBD_VERSION ?=
DRBD_VERSION_OTHER ?=
VMSHED_TEST_TIMEOUT ?=

.PHONY: docker
docker:
	docker build --no-cache=$(NOCACHE) -t $(DOCKER_IMAGE_NAME) docker/

virter/tests.toml: tests/* virter/vmshed_tests_generator.py
	virter/vmshed_tests_generator.py \
		--tests-dir "$(DRBD_TESTS_DIR)" \
		--selection "$(VMSHED_TEST_SELECTION)" \
		--drbd-version "$(DRBD_VERSION)" \
		--drbd-version-other "$(DRBD_VERSION_OTHER)" \
		$(if $(VMSHED_TEST_TIMEOUT),--test-timeout $(VMSHED_TEST_TIMEOUT),) \
		> virter/tests.toml
