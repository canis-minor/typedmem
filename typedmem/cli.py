"""``typedmem`` CLI.

Default store: SQLite at $TYPEDMEM_DB or ``~/.typedmem/memories.db``.
Override per invocation with ``--store path.db`` or ``--store path.jsonl``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import (
    ContradictionSurfacer,
    DomainProfile,
    GoalResolver,
    HashingEmbeddingProvider,
    JSONLMemoryStore,
    LLMExtractor,  # noqa: F401  (kept for docs / future use)
    Memory,
    MemoryStore,
    MemoryType,
    PolicyEngine,
    PreferenceDriftDetector,
    Retriever,
    RuleBasedExtractor,
    SQLiteMemoryStore,
    Source,
)
from .profiles import BUILTIN_PROFILES, from_json as _profile_from_json, from_yaml as _profile_from_yaml


def _default_store_path() -> Path:
    env = os.environ.get("TYPEDMEM_DB")
    if env:
        return Path(env)
    return Path.home() / ".typedmem" / "memories.db"


def _load_profile(name: str | None, path: str | None) -> DomainProfile | None:
    if path:
        p = Path(path)
        if p.suffix in {".yaml", ".yml"}:
            return _profile_from_yaml(p)
        return _profile_from_json(p)
    if name:
        return DomainProfile.builtin(name)
    return None


def _open_store(path: Path, workspace: str, profile: DomainProfile | None) -> MemoryStore:
    policy = PolicyEngine.from_profile(profile) if profile else None
    if path.suffix in {".jsonl", ".ndjson"}:
        return JSONLMemoryStore(path, policy=policy, default_workspace=workspace, profile=profile)
    return SQLiteMemoryStore(path, policy=policy, default_workspace=workspace, profile=profile)


def _fmt(m: Memory) -> str:
    subj = f" [{m.subject}]" if m.subject else ""
    tags = f" #{','.join(m.tags)}" if m.tags else ""
    ws = "" if m.workspace == "default" else f" @{m.workspace}"
    return f"{m.timestamp.date()} {m.type:<11}{subj}{ws} conf={m.confidence:.2f}{tags}  {m.content}"


def _source_from_args(args: argparse.Namespace) -> Source | None:
    if not getattr(args, "document_id", None):
        return None
    kwargs = {"document_id": args.document_id}
    if getattr(args, "uri", None):
        kwargs["uri"] = args.uri
    if getattr(args, "authority", None) is not None:
        kwargs["authority"] = args.authority
    return Source(**kwargs)


def cmd_add(args: argparse.Namespace, store: MemoryStore) -> int:
    source = _source_from_args(args)
    if args.type:
        m = Memory(
            type=args.type,                          # any string; profile validates if bound
            content=args.text,
            subject=args.subject,
            tags=args.tags or [],
            confidence=args.confidence,
            workspace=args.workspace,
            sources=[source] if source else [],
        )
        store.add(m)
        print(f"added 1 memory ({m.type}): {m.id}")
        return 0
    extractor = RuleBasedExtractor()
    extracted = extractor.extract(
        args.text, subject=args.subject, workspace=args.workspace, default_source=source,
    )
    if not extracted:
        print("no memories extracted; pass --type to force a single typed memory", file=sys.stderr)
        return 1
    for m in extracted:
        store.add(m)
    print(f"added {len(extracted)} memorie(s) from extractor")
    for m in extracted:
        print("  " + _fmt(m))
    return 0


def cmd_search(args: argparse.Namespace, store: MemoryStore) -> int:
    embedder = None if args.no_embed else HashingEmbeddingProvider(dim=args.dim)
    retriever = Retriever(store, embedder=embedder)
    types = list(args.type) if args.type else None
    tags = args.tag or None
    hits = retriever.relevant(
        args.query, limit=args.limit, types=types, tags=tags,
        workspace=args.workspace, include_superseded=args.include_superseded,
    )
    if not hits:
        print("no matches")
        return 0
    for h in hits:
        print(f"{h.score:.3f}  " + _fmt(h.memory))
    return 0


def cmd_list(args: argparse.Namespace, store: MemoryStore) -> int:
    if args.type:
        items = store.by_type(
            args.type, workspace=args.workspace,
            include_superseded=args.include_superseded,
        )
    else:
        items = store.all(
            workspace=args.workspace, include_superseded=args.include_superseded,
        )
    items.sort(key=lambda m: m.timestamp, reverse=True)
    if args.limit:
        items = items[: args.limit]
    if args.json:
        print(json.dumps([m.to_dict() for m in items], indent=2))
        return 0
    if not items:
        print("no memories")
        return 0
    for m in items:
        print(_fmt(m))
    return 0


def cmd_delete(args: argparse.Namespace, store: MemoryStore) -> int:
    ok = store.delete(args.id)
    print("deleted" if ok else "not found")
    return 0 if ok else 1


def cmd_compact(args: argparse.Namespace, store: MemoryStore) -> int:
    if isinstance(store, JSONLMemoryStore):
        store.compact()
        print("compacted")
        return 0
    print("compact is only supported for JSONL stores", file=sys.stderr)
    return 1


def cmd_contradictions(args: argparse.Namespace, store: MemoryStore) -> int:
    """First-class verb for the killer feature: surface contradiction clusters.

    Identical output to ``typedmem evolve --evolver contradictions`` but
    shorter to type — and easier to recommend in a single tweet.
    """
    clusters = store.contradictions(workspace=args.workspace)
    if not clusters:
        print("no contradictions")
        return 0
    print(f"{len(clusters)} contradiction cluster(s):\n")
    for i, cluster in enumerate(clusters, 1):
        print(f"cluster {i} ({len(cluster)} memories):")
        for m in cluster:
            subj = f" [{m.subject}]" if m.subject else ""
            print(f"  [{m.type}]{subj} {m.content}")
        print()
    return 0


def cmd_workspaces(args: argparse.Namespace, store: MemoryStore) -> int:
    names = store.workspaces()
    if not names:
        print("(no workspaces yet)")
        return 0
    for name in names:
        print(name)
    return 0


def _format_record(r) -> str:
    return f"  [{r.action}] {r.reason}  (in={r.input_ids}, out={r.output_ids})"


def cmd_evolve(args: argparse.Namespace, store: MemoryStore) -> int:
    evolver_kind = args.evolver
    if evolver_kind == "contradictions":
        evolver = ContradictionSurfacer()
        dry_run = False  # read-only; flag is informational
    elif evolver_kind == "drift":
        evolver = PreferenceDriftDetector(
            min_replaces=args.min_replaces, window_days=args.window_days,
        )
        # Drift annotation is reversible (just a metadata key) — default to commit.
        dry_run = not args.apply
    elif evolver_kind == "goals":
        evolver = GoalResolver(
            HashingEmbeddingProvider(dim=args.dim),
            threshold=args.threshold,
        )
        # Destructive: default to dry-run, require --apply to commit.
        dry_run = not args.apply
    else:
        print(f"unknown evolver: {evolver_kind}", file=sys.stderr)
        return 1

    result = evolver.evolve(store, workspace=args.workspace, dry_run=dry_run)
    print(result.summary())

    # For contradictions, show the actual memories in each cluster — much
    # more useful to a human than the bare UUID list of an EvolutionRecord.
    if evolver_kind == "contradictions" and result.records:
        by_id = {m.id: m for m in store}
        for i, r in enumerate(result.records, 1):
            print(f"\ncluster {i} ({len(r.input_ids)} memories):")
            for mid in r.input_ids:
                m = by_id.get(mid)
                if m is not None:
                    print(f"  [{m.type}] {m.content}")
    else:
        for r in result.records:
            print(_format_record(r))
    return 0


def cmd_history(args: argparse.Namespace, store: MemoryStore) -> int:
    entries = store.evolution_history(args.id)
    if not entries:
        print("(no evolution history)")
        return 0
    for e in entries:
        ts = e.get("timestamp", "?")
        print(f"{ts}  [{e.get('evolver','?')}] {e.get('action','?')}: {e.get('reason','')}")
    return 0


def cmd_profiles(args: argparse.Namespace, store: MemoryStore) -> int:
    for name, factory in sorted(BUILTIN_PROFILES.items()):
        profile = factory()
        types = sorted(profile.all_types())
        marker = " (+core)" if profile.include_core_types else ""
        print(f"{name}{marker}: {profile.description}")
        print(f"  types: {', '.join(types)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="typedmem", description="Schema-aware memory for AI agents.")
    p.add_argument("--store", type=Path, default=_default_store_path(),
                   help="path to .db (SQLite) or .jsonl (default: ~/.typedmem/memories.db)")
    p.add_argument("--workspace", default="default",
                   help="memory namespace; isolates one agent/domain from another (default: 'default')")
    p.add_argument("--profile", default=None, choices=sorted(BUILTIN_PROFILES.keys()),
                   help="built-in domain profile to bind (validates types and required fields)")
    p.add_argument("--profile-file", default=None,
                   help="path to a custom profile in .json or .yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    sa = sub.add_parser("add", help="add memory (auto-extract by default)")
    sa.add_argument("text")
    sa.add_argument("--type", help="force a single memory of this type (profile-defined names accepted)")
    sa.add_argument("--subject")
    sa.add_argument("--tags", nargs="*")
    sa.add_argument("--confidence", type=float, default=1.0)
    sa.add_argument("--document-id", help="opaque id of the source document")
    sa.add_argument("--uri", help="URL or path to the source document")
    sa.add_argument("--authority", type=float, help="weight in conflict resolution (default 1.0)")
    sa.set_defaults(func=cmd_add)

    ss = sub.add_parser("search", help="semantic search across stored memories")
    ss.add_argument("query")
    ss.add_argument("--limit", type=int, default=10)
    ss.add_argument("--type", action="append",
                    help="filter by type (repeatable; any profile-defined name)")
    ss.add_argument("--tag", action="append")
    ss.add_argument("--no-embed", action="store_true", help="use token overlap instead of embeddings")
    ss.add_argument("--dim", type=int, default=256, help="hashing embedder dim")
    ss.add_argument("--include-superseded", action="store_true",
                    help="include memories that have been superseded by a newer record")
    ss.set_defaults(func=cmd_search)

    sl = sub.add_parser("list", help="list memories")
    sl.add_argument("--type", help="filter by type (any profile-defined name)")
    sl.add_argument("--limit", type=int, default=0)
    sl.add_argument("--json", action="store_true")
    sl.add_argument("--include-superseded", action="store_true")
    sl.set_defaults(func=cmd_list)

    sd = sub.add_parser("delete", help="delete a memory by id")
    sd.add_argument("id")
    sd.set_defaults(func=cmd_delete)

    sc = sub.add_parser("compact", help="compact a JSONL store")
    sc.set_defaults(func=cmd_compact)

    sw = sub.add_parser("workspaces", help="list workspaces present in this store")
    sw.set_defaults(func=cmd_workspaces)

    sp = sub.add_parser("profiles", help="list built-in domain profiles")
    sp.set_defaults(func=cmd_profiles)

    se = sub.add_parser("evolve", help="run an Evolver over the store")
    se.add_argument("--evolver", required=True,
                    choices=["contradictions", "drift", "goals"],
                    help="which evolver to run (summarize requires Python API + LLM client)")
    se.add_argument("--apply", action="store_true",
                    help="commit changes (drift/goals default to dry-run)")
    se.add_argument("--threshold", type=float, default=0.85,
                    help="goal-resolution similarity threshold (goals only)")
    se.add_argument("--min-replaces", type=int, default=3,
                    help="minimum REPLACE count in window to flag drift (drift only)")
    se.add_argument("--window-days", type=float, default=30.0,
                    help="trailing window for drift detection (drift only)")
    se.add_argument("--dim", type=int, default=256,
                    help="hashing embedder dim (goals only)")
    se.set_defaults(func=cmd_evolve)

    sh = sub.add_parser("history", help="show evolution_history for a memory")
    sh.add_argument("id")
    sh.set_defaults(func=cmd_history)

    sx = sub.add_parser("contradictions",
                        help="surface contradiction clusters (shortcut for 'evolve --evolver contradictions')")
    sx.set_defaults(func=cmd_contradictions)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = _load_profile(args.profile, args.profile_file)
    store = _open_store(args.store, args.workspace, profile)
    try:
        return args.func(args, store)
    finally:
        store.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
