# AWS Cost Optimizer

Fix an over-provisioned CloudFormation template to reduce AWS costs by ~90%.

## Architecture

A web app behind a load balancer.

```
Internet → ALB → EC2 Instances → (serve web app)
```

## Problem (Baseline)

- 3x t2.2xlarge (8 vCPU, 32GB) running 24/7 — ~$856/month
- No auto-scaling — paying for 3 servers even with zero traffic
- No lifecycle hooks — instances killed abruptly
- No cost tags — can't track spending
- gp2 100GB volumes — oversized, old generation

## Fix

| Change | Before | After |
|---|---|---|
| Instance type | t2.2xlarge (8 vCPU, 32GB) | t3.medium (2 vCPU, 4GB) |
| Instance count | 3 fixed, always on | Auto-scaling: min 1, max 4 |
| Storage | 100GB gp2 | 20GB gp3 |
| Scaling | None | Target tracking at 70% CPU |
| Lifecycle hooks | None | 5-min graceful shutdown |
| Cost tags | None | Project, Environment, Team on all resources |
| Monthly cost | ~$856 | ~$85 (90% reduction) |

## Files

| File | Description |
|---|---|
| `template_broken.yaml` | Over-provisioned baseline (commit to main) |
| `template_fixed.yaml` | Optimized version (commit to fix branch) |
| `COST_ANALYSIS.md` | Detailed cost breakdown and savings |
