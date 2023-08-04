# DRBD Test Suite GitLab Integration

The DRBD Test Suite includes configuration to run in GitLab CI. This requires
additional infrastructure, such as appropriate GitLab runners and a package
repository.

## Merge request testing

The tests will run for merge requests automatically.

Merge request pipelines use the default test selection `ci`. This means that
the set of tests to run and the VM counts to use is determined by the `vms_ci`
entry in the `### vmshed:` line of the test.

The default variants `tcp`, `tls`, `raw` and `zfs` are used. All tests are run
with the `tcp` variant. Only specific tests run with the other variants. These
tests declare that they should be run with those variants using the
`variants_add` field. The number of such tests is deliberately limited to keep
the test suite fast.

The merge request pipelines for the `drbd` and `drbd-utils` also run the tests
very similarly.

## Stability testing

Stability testing means running the tests repeatedly to determine how stable
each test is. The results are used to detect changes in stability due to
changes in DRBD and the tests themselves. Stability test runs are scheduled
nightly.

These runs are very similar to the merge request test runs. Differences:
* A large number of repeats is configured.
* The test selection `all` is used. The `vms_all` field determines the VM
  counts to use.

## RDMA testing

RDMA tests are run the same as the stability tests, but with fewer repeats and
the variant set to `rdma`. All tests are run with the `rdma` variant.

## Endurance testing

Endurance testing means running tests which place a heavy load on DRBD. These
are scheduled nightly and use the tests in the
`tests_endurance_random` directory.

## Compatibility testing

Compatibility testing means testing the latest version of DRBD against another
version. All tests in the test selection `ci` are run with the variants `tcp`
and `second_is_other`. The latter variant instructs the test to install the
"other" version on node 1 instead of node 0.

Various combinations are tested, including:
* Latest DRBD 9.x against DRBD 8.4
* Latest DRBD 9.x against the last release
* Latest DRBD 9.x against latest DRBD 9.y

When DRBD 8 is involved, only 2 node tests are included.

## Mainline testing

Mainline testing means testing the in-tree DRBD module from a Linux build. All
tests in the test selection `ci` are run, as long as `drbd_version_min`
indicates that they are supported by DRBD 8.4. The variant `mainline` is used.
The `mainline` variant does not affect how the test runs. Instead, it controls
which VM base image is used.

## New kernel module testing

The `kpull` kernel puller project regularly checks for newly released
distribution kernels. When a new kernel is found, a test run is started. The
set of tests to run is explicitly limited, and a special VM base image
configuration is used.

## Custom test suite runs

Custom test suite runs can be started with the [GitLab CLI][1]. To start a run
with the default parameters, simply execute:

```
glab ci run -b "$(git branch --show-current)"
```

To use a specific DRBD branch, add `--variables DRBD_REF:my-branch`. This will
trigger a build of a DRBD branch before running the tests if necessary.

To further customize the run, set additional variables. Examples can be found
in `.gitlab/vars/`. The variables should be fairly self-explanatory. These
snippets can be combined using `jq`. For instance:

```
glab ci run -b "$(git branch --show-current)" \
  -f <(cat .gitlab/vars/base-image.json .gitlab/vars/torun.json | jq -sf .gitlab/combine-vars.jq) \
  --variables DRBD_REF:my-branch
```

Only one of the variables `DRBD_REF` and `DRBD_VERSION` should be used. If both
are set, different versions of DRBD may be built and tested.

[1]: https://gitlab.com/gitlab-org/cli
