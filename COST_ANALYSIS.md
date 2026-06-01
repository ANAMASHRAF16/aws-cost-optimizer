# Cost Analysis: Before vs After

## Before (Broken Template)

| Resource | Spec | Count | Monthly Cost (us-east-1) |
|---|---|---|---|
| EC2 t2.2xlarge | 8 vCPU, 32GB RAM | 3 instances 24/7 | 3 x $268 = **$804** |
| EBS gp2 100GB | 100GB per instance | 3 volumes | 3 x $10 = **$30** |
| ALB | Load balancer | 1 | **$22** |
| **Total** | | | **~$856/month** |

## After (Fixed Template)

| Resource | Spec | Count | Monthly Cost (us-east-1) |
|---|---|---|---|
| EC2 t3.medium | 2 vCPU, 4GB RAM | 1-4 instances (avg 2) | 2 x $30 = **$60** |
| EBS gp3 20GB | 20GB per instance | avg 2 volumes | 2 x $1.60 = **$3.20** |
| ALB | Load balancer | 1 | **$22** |
| **Total** | | | **~$85/month** |

## Savings

| Metric | Before | After | Savings |
|---|---|---|---|
| Monthly cost | $856 | $85 | **$771/month (90% reduction)** |
| Annual cost | $10,272 | $1,020 | **$9,252/year** |
| vCPUs running | 24 (always) | 4 (avg) | 83% fewer |
| RAM allocated | 96GB (always) | 8GB (avg) | 92% less |
| Storage | 300GB gp2 | 40GB gp3 | 87% less, faster |

## What Changed

### 1. Right-sized instances
- **Before:** t2.2xlarge (8 vCPU, 32GB) — massive overkill for a web app
- **After:** t3.medium (2 vCPU, 4GB) — right-sized for typical web workload
- **Why t3 over t2:** t3 is newer generation, 10% cheaper, better baseline CPU performance

### 2. Auto-scaling
- **Before:** 3 instances running 24/7, even at 3 AM with zero traffic
- **After:** Min 1, max 4, scales based on CPU utilization (target 70%)
- At night: scales down to 1 instance
- At peak: scales up to 4 instances
- Average: ~2 instances

### 3. Storage optimization
- **Before:** 100GB gp2 per instance (300GB total)
- **After:** 20GB gp3 per instance (~40GB total)
- gp3 is 20% cheaper than gp2 AND faster (3000 IOPS baseline vs 300 for gp2)

### 4. Lifecycle hooks
- **Before:** Instances terminated instantly, dropping active user connections
- **After:** 5-minute graceful shutdown period to drain connections

### 5. Cost tags
- **Before:** No tags — impossible to track spending
- **After:** Every resource tagged with Project, Environment, Team
- Enables AWS Cost Explorer filtering by team/project
