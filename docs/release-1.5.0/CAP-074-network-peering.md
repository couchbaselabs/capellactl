# CAP-074 — Network peering

| Epic | Priority | Points | Depends on | Status |
|---|---|---|---|---|
| E13 Private networking & security | P0 | 5 | CAP-011, CAP-038 | Not started |

## User story
As an **operator**, I want to peer a cluster's network with my application's VPC or VNet from capellactl, so that
applications reach the cluster over private addresses and the peering is recreated with the environment.

## Context & discovery

| Operation | Endpoint | Success | Notes |
|---|---|---|---|
| Create | `POST …/clusters/{clusterId}/networkPeers` | 201 | `name` (2–128 chars), `providerType` (`aws`, `gcp`, `azure`), `providerConfig` → `id` |
| List | `GET …/clusters/{clusterId}/networkPeers` | 200 | `id`, `name`, `status` (`state`, `reasoning`), `providerConfig` |
| Get | `GET …/networkPeers/{peerId}` | 200 | Also `commands[]`: the commands to run in the customer's account |
| Delete | `DELETE …/networkPeers/{peerId}` | 204 | |
| Azure command | `POST …/networkPeers/networkPeerCommand` | 200 | `tenantId`, `subscriptionId`, `resourceGroup`, `vnetId`, `vnetPeeringServicePrincipal` → `command` |

`providerConfig`: AWS `accountId`, `vpcId`, `region`, `cidr`; GCP `networkName`, `projectId`, `serviceAccount`,
`cidr`; Azure `azureTenantId`, `subscriptionId`, `resourceGroup`, `vnetId`, `cidr`. There is no update: a changed
peer is replaced.

## Design

### Commands
```
capellactl peer list   CLUSTER
capellactl peer get    CLUSTER NAME
capellactl peer create CLUSTER NAME --aws --account-id ID --vpc-id ID --region R --cidr CIDR
                                    | --gcp --network NAME --gcp-project ID --service-account EMAIL --cidr CIDR
                                    | --azure --tenant-id ID --subscription-id ID --resource-group RG --vnet-id ID --cidr CIDR
capellactl peer delete CLUSTER NAME
capellactl peer azure-command CLUSTER --tenant-id … --subscription-id … --resource-group … --vnet-id … --service-principal …
```
Example:
```
capellactl peer create nova-prod-01 app-vpc --aws --account-id 123456789012 --vpc-id vpc-0a1b2c --region us-east-1 --cidr 10.1.0.0/23
```

### capella.yaml
```yaml
clusters:
  - name: nova-prod-01
    networkPeers:
      - name: app-vpc
        aws: {accountId: "123456789012", vpcId: vpc-0a1b2c, region: us-east-1, cidr: 10.1.0.0/23}
```
- After `create`, the command waits for the peer to leave its pending state and prints `commands[]` (for example the
  AWS route and acceptance steps) with `next: run these in your cloud account`.
- A changed `providerConfig` is a replace (`±`), like allowed CIDRs. The peer CIDR must not overlap the cluster's
  CIDR (exit 3).
- Code: `cli/peer_cmds.py`, `resources/network_peer.py` (prunable), five operations, fake Capella.

## Acceptance criteria & tests

### AC1 — Create
**Given** the AWS example, **then** one `POST` with `providerType: aws` and that `providerConfig`, the commands
printed, and capella.yaml records the peer; `plan` then reports no changes.

| Test | Location | Verifies |
|---|---|---|
| `test_peer_ac1_create_aws` | `tests/scenario/test_network_peers.py` | |
| `test_peer_ac1_create_gcp_azure` | same | Parametrised bodies |

### AC2 — Idempotent
**Given** AC1 completed, **then** a re-run makes zero writes.

| Test | Location | Verifies |
|---|---|---|
| `test_peer_ac2_rerun_zero_writes` | `tests/scenario/test_network_peers.py` | |

### AC3 — Validation
**Given** an overlapping CIDR, a provider that does not match the cluster's, a missing field, or a name outside
2–128 characters, **then** exit 3 before any write.

| Test | Location | Verifies |
|---|---|---|
| `test_peer_ac3_validation` | `tests/unit/config/test_peer_rules.py` | Parametrised |

### AC4 — Change is replace; delete
**Given** `vpcId` changed, **then** `plan` shows `± network peer nova-prod-01/app-vpc` and `apply` deletes then
creates. `peer delete` asks once, and a re-run prints `not found, nothing to do`.

| Test | Location | Verifies |
|---|---|---|
| `test_peer_ac4_replace_and_delete` | `tests/scenario/test_network_peers.py` | |

### AC5 — Lists, Azure command, sync, drift
**Given** peers, **then** `list` prints `S.NO`, `NAME`, `PROVIDER`, `STATE`, `ID`; `azure-command` prints the `az`
command; `sync` writes peers; `drift` lists unmanaged ones and `apply --prune` deletes them.

| Test | Location | Verifies |
|---|---|---|
| `test_peer_ac5_list_command_sync_drift` | `tests/scenario/test_network_peers.py` | |

## Out of scope
- Running the cloud-side commands; capellactl only prints them.

## Open questions
- Which `status.state` values mean "waiting for the customer"? The spec gives only an example (`complete`).
