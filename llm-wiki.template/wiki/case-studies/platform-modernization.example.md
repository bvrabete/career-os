---
type: case_study
title: "Zero-Downtime Microservices Migration and Event-Driven Decoupling"
organization: [[acme-corporation]]
role: [[acme-principal-engineer]]
dates: { start: "2022-01-01", end: "2023-06-30" }
skills: [Kubernetes, Apache Kafka, Go, Distributed Systems, Microservices]
related: [[acme-corporation]]
status: example  # Files ending with .example.md are ignored by CV generation
---

# Zero-Downtime Microservices Migration and Event-Driven Decoupling

## Context & Challenge
Acme's legacy monolithic order-processing engine struggled with database lock contention during Black Friday peak traffic, causing checkout timeouts and requiring costly vertical database scaling.

## Architectural Decision
Decoupled the monolithic checkout into asynchronous, event-driven Go microservices orchestrated via Apache Kafka and deployed on multi-cluster Kubernetes:
- Implemented outbox pattern with Debezium CDC for guaranteed event delivery.
- Designed idempotency keys across payment gateways to prevent duplicate charges during network partitions.

## Key Outcomes & Metrics
- **Zero Downtime**: Maintained 99.995% uptime throughout peak sale events with zero transaction loss.
- **Latency Cut**: Reduced p99 order-processing latency from 1.2s to 85ms.
- **Cost Reduction**: Replaced $45k/month provisioned database instances with auto-scaling compute pods, saving 38% annual infrastructure cost.
