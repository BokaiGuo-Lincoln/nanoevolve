# Security Policy

## Supported Versions

The current `0.1.x` development line receives security fixes. Older snapshots are not maintained as separate supported release lines.

## Critical Execution Boundary

NanoEvolve evaluates model-generated Python code. Its default `SubprocessRunner` provides process-level fault isolation, timeout handling, and output capture, but it is **not a security sandbox**.

Generated code and evaluator code may still be able to:

- Access the network.
- Read or modify files available to the current user.
- Execute system programs.
- Spawn child processes.
- Interfere with processes owned by the same user.

Run untrusted evolution inside Docker, Podman, a virtual machine, a restricted operating-system account, or another external isolation boundary.

## Credential Handling

The evaluator subprocess removes environment variables whose case-insensitive names contain:

```text
API_KEY
ACCESS_TOKEN
AUTH_TOKEN
SECRET
PASSWORD
```

This reduces accidental credential exposure but is not a complete secret-management system. Credentials stored in files, command arguments, inherited services, or differently named variables may remain accessible.

## Reporting a Vulnerability

Do not publish exploit details, credentials, or sensitive generated artifacts in a public issue.

When this project is hosted on a collaboration platform, use that platform's private security-reporting or security-advisory mechanism. Until an authoritative private contact channel is configured, retain the report privately rather than inventing or guessing a maintainer address.

A useful report includes:

- Affected NanoEvolve version or source snapshot.
- Operating system and Python version.
- Minimal reproduction steps.
- Expected and observed behavior.
- Security impact and required preconditions.
- Whether untrusted candidate code is involved.

## Non-Security Failures

Ordinary evaluator exceptions, invalid model responses, timeouts, and archive validation errors are expected operational states. They become security issues only when they cross an intended trust boundary or allow unauthorized access, execution, disclosure, or persistence.
