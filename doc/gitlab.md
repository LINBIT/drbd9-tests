# DRBD Test Suite GitLab Integration

The DRBD Test Suite includes configuration to run in GitLab CI. This requires
additional infrastructure, such as appropriate GitLab runners and a package
repository.

## Merge requests

The tests will run for merge requests automatically.

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
