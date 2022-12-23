#!/usr/bin/env python3

import sys
from typing import List

import trigger
import requests

job_name = 'build:for-tests'
downstream_artifact_path = 'build.env'
artifact_output_path = 'downstream.env'


def get_job_artifact(project_url, api_token, job_id, verifyssl, artifact_path, verbose=False):
    r = requests.get(
        f'{project_url}/jobs/{job_id}/artifacts/{artifact_path}',
        headers={
            'PRIVATE-TOKEN': api_token
        },
        verify=verifyssl
    )
    if verbose:
        print(f'Response get_job_artifact: {r.text}')
    assert r.status_code == 200, f'expected status code 200, was {r.status_code}'
    return r.content


def trigger_for_artifact(arg_list: List[str]) -> int:
    # Run the downstream pipeline and get its ID
    pid = trigger.trigger(arg_list)

    # Parse args again so we can use them
    args = trigger.parse_args(arg_list)

    # Process args as trigger.trigger() does internally
    proj_id = args.project_id
    api_token = args.api_token
    verifyssl = args.verifyssl
    verbose = args.verbose
    http = args.http

    prefix_url = 'https://'
    if http:
        prefix_url = 'http://'

    if args.host.startswith('http://') or args.host.startswith('https://'):
        base_url = args.host
    else:
        base_url = f'{prefix_url}{args.host}'

    if not trigger.isint(proj_id):
        proj_id = trigger.get_project_id(f"{base_url}{args.url_path}", args.api_token, proj_id, verifyssl, verbose)

    project_url = f"{base_url}{args.url_path}/{proj_id}"

    # Find job ID
    pipeline_jobs = trigger.get_pipeline_jobs(project_url, api_token, pid, verifyssl, verbose)
    matching_jobs = [j for j in pipeline_jobs if j['name'] == job_name]
    assert len(matching_jobs) == 1, f'expected 1 matching jobs, was {len(matching_jobs)}'
    job = matching_jobs[0]
    job_id = job['id']

    # Get the artifact
    artifact_content = get_job_artifact(project_url, api_token, job_id, verifyssl, downstream_artifact_path, verbose)
    with open(artifact_output_path, 'wb') as f:
        f.write(artifact_content)

    return pid


if __name__ == "__main__":  # pragma: nocover
    try:
        trigger_for_artifact(sys.argv[1:])
        sys.exit(0)
    except trigger.PipelineFailure as e:
        sys.exit(e.return_code)
