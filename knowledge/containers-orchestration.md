---
priority: support
domain: devops
aspects: Morrigan, Nyx
difficulty: beginner
related: devops-cicd-patterns.md, security-engineering-basics.md
---

# Containers and orchestration (mental model)

## Containers (what they are)

- A container is a **process** with filesystem/network isolation, packaged with dependencies.
- It is **not** a VM: it shares the host kernel.

## Images

- Images are layered filesystems + metadata.
- Builds should be:
  - reproducible
  - minimal
  - cached effectively

Common best practices:

- Multi-stage builds
- Pin base images
- Avoid baking secrets into images

## Docker Compose

Use Compose for local multi-service environments:

- app + DB + cache + workers
- shared networks and env vars

## Kubernetes (concepts)

- **Pod**: smallest deploy unit (one or more containers)
- **Deployment**: desired replica count + rolling updates
- **Service**: stable networking to pods
- **Ingress**: HTTP routing into the cluster
- **ConfigMap/Secret**: configuration injection

## Operational thinking

- Make state explicit: volumes, databases, backups.
- Separate config from code.
- Don’t start with K8s unless you need it.

---
priority: support
domain: devops
aspects: morrigan, nyx
difficulty: beginner
related: devops-cicd-patterns.md, security-engineering-basics.md
---

## Containers & orchestration (baseline mental model)

### Docker fundamentals
- **Image**: built artifact (filesystem + metadata).
- **Container**: running instance of an image.
- Keep images small; avoid baking secrets into images.

### Compose
- Useful for local multi-service development.
- Treat `docker-compose.yml` as documented infrastructure for developers.

### Kubernetes concepts (high level)
- **Pod**: one or more containers scheduled together.
- **Deployment**: declarative desired state for replicas.
- **Service**: stable networking for a set of pods.
- **ConfigMap/Secret**: configuration injection (still handle secrets carefully).

### Operational defaults
- Health checks and timeouts.
- Resource limits.
- Rolling updates with rollback.

