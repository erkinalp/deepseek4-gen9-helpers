# The G9XC contract, as this repository depends on it

**This is a mirror, not a specification.** The protocol is owned by
`ram-coffers/gen9-cluster`; its normative documentation is
[`gen9-cluster/docs/G9XC.md`](https://github.com/erkinalp/ram-coffers/blob/ds4-ps5-xbox4/gen9-cluster/docs/G9XC.md)
and its normative implementation is `gen9_cluster/protocol.py`. Nothing in this
repository implements G9XC, and nothing here may be treated as authoritative if
the two disagree. Recorded here so that deployment decisions — firewalling,
restart granularity, failure handling, MTU — can be justified without reading
the core.

## What deployment needs to know

**Fixed 32-byte header, little-endian, then `payload_len` bytes.** Magic
`G9XC`, version 2, `payload_len ≤ 64 MiB`. Frames are small (an activation is
tens of KiB) except `LOAD_SHARD`, which is not.

**Version is a hard match.** A node and its coordinator must run the same core
checkout. v2 changed the shape of every expert reply, so a v1 node in a v2
fleet fails at the first frame — loudly, which is the intended outcome; the
alternative would be wrong logits. Roll the core out shelf-at-a-time and
restart the whole shelf, coordinator included.

**Replies are one row per expert, and that is a bandwidth budget item.** The
node does not collapse a batch into a partial sum unless the coordinator asks
(see reproducibility below). Reply volume is roughly `k` × hidden × 4 bytes per
MoE layer per token — order 18 MB/token at the assumed V4-Pro profile, against
~15 MB/token if collapsing were used. Size the upstream links for the former.
Numbers estimated from the assumed model profile; never measured on hardware.

**Persistent TCP with `TCP_NODELAY`, multiplexed by `request_id`.** One
long-lived connection per coordinator↔node pair, many requests in flight. Two
consequences for the network: anything that silently drops idle connections (a
stateful firewall with a short timeout, a NAT) will break a shelf in a way that
looks like random slowness, and per-connection bandwidth shaping punishes this
topology badly. Put the compute VLAN on a flat, unfiltered L2 segment.

**Default port 9713**, per node, from the inventory.

**There is no authentication and no encryption.** None. Any host that can reach
a node's port can load arbitrary shards into it and ask it to compute. The
security model is *network reachability* — an isolated compute VLAN with no
route to anything else. This is the single most important operational fact in
this document, and the reason `G9_HOST=0.0.0.0` in the sample environment file
comes with a warning attached.

## Message types, and which ones hurt

| Type | Deployment relevance |
|---|---|
| `HELLO` / `HELLO_ACK` | The node announces its *actual* identity, memory and backend at connect time. A console back from a repair with fewer CUs is caught here rather than by mystery slowness later — which is why the inventory must be updated when hardware changes. |
| `EXPERT_BATCH` / `EXPERT_RESULT` | The hot path. **Stateless**: safely retried, and re-routable to a replica that holds *every* expert in the batch. A retry that lands back on the *same* node is deduplicated by the node and answered from cache instead of re-run; a retry sent to a replica is not, and cannot be — there is no shared state, by design. |
| `BLOCK_FWD` / `BLOCK_RESULT` | **Stateful** — it appends to the shelf host's MLA KV cache. Never retried automatically, and a shelf host is never failed over, because that cache exists only there. |
| `LOAD_SHARD` / `LOAD_ACK` | How weights get onto a node. This is the expensive part of any restart: a node that reboots comes back empty and must be re-loaded before it is useful. |
| `PING` / `PONG`, `STATUS` | What `g9 health` uses. |
| `ERROR` | A malformed request produces an error frame, not a dropped connection, attributed to the unit that produced it. |
| `SHUTDOWN` | Clean stop. |

## The rules this repository derives from that

1. **Restart node workers, not units.** `systemctl restart g9-node@X` costs a
   re-load; a power cycle costs a re-load *plus* the boot, and on a PS5 a
   manual re-run of the exploit chain. `deploy/start_shelf.sh` exists for this.
2. **Never bounce a shelf host casually.** Losing an expert holder costs a
   re-load. Losing a host ends every generation in flight on that shelf. Prefer
   putting hosts on salvage boards, which reboot unattended.
3. **Prefer shelf-sized blast radius.** Shelf-at-a-time is the granularity all
   the tooling in `deploy/` and `power/` defaults to.
4. **Flat network, jumbo frames if you have them.** `LOAD_SHARD` bodies are
   large and the hot path is latency-bound at a quarter-millisecond per hop.
5. **Isolate the VLAN.** See above; there is no second line of defence.

## Reproducibility, and what an operator can change about it

The core sums a layer's experts in the router's top-k order, not in the order
replies arrive and not per console, so **the same prompt gives the same output
regardless of how the planner spread the experts over a shelf**. Replacing a
dead console and replanning does not change the model's answers. That is a
protocol guarantee, not something deployment has to preserve.

Two operational caveats:

- **Mixed backends break bit-identity, and no protocol change fixes that.**
  `cpu-avx2`, `vulkan` and `rocm` do not accumulate an expert's arithmetic in
  the same order internally. Reduction order is fixed; kernel arithmetic is
  not. A fleet that needs bit-identical output across every unit must set one
  backend for every node in the inventory. A mixed fleet is reproducible only
  as long as each expert stays on the same *kind* of node.
- **`FAST` is an opt-in that gives this up.** It saves roughly 17% of reply
  bandwidth and makes the output depend on the current plan. It is off by
  default and this repository never turns it on. If someone does, a replan
  becomes a change to the model's answers, and that should be a deliberate,
  documented decision rather than a tuning knob.

None of this has been observed on real hardware. It is a property of the core's
tests on x86-64 loopback, which is where every claim in this repository about
numerical behaviour comes from.
