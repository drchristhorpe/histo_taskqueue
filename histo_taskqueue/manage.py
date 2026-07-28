"""``histo-taskqueue-keys`` — manage API keys for the JSON API.

Keys live in the JSON keystore (``$HTQ_API_KEYS_PATH`` or ``data/api_keys.json``).
Only the SHA-256 hash is stored, so a freshly created token is printed **once** —
copy it immediately.

    uv run histo-taskqueue-keys create --label "prod worker" --scopes consume
    uv run histo-taskqueue-keys list
    uv run histo-taskqueue-keys revoke <id>
"""

from __future__ import annotations

import argparse
import sys

from .apikeys import SCOPES, APIKeyError, APIKeyStore
from .config import Config


def _store() -> APIKeyStore:
    return APIKeyStore(Config.from_env().resolved_api_keys_path())


def cmd_create(args) -> int:
    store = _store()
    scopes = [s for s in args.scopes.replace(",", " ").split() if s]
    try:
        key, token = store.create(args.label, scopes)
    except APIKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created API key '{key.label}' [{key.id}] with scopes: {', '.join(key.scopes)}")
    print()
    print("  API token (shown once — store it now):")
    print(f"    {token}")
    print()
    print(f"  Keystore: {store.path}")
    return 0


def cmd_list(args) -> int:
    store = _store()
    keys = store.list()
    if not keys:
        print(f"No API keys in {store.path}")
        return 0
    print(f"{'ID':<14}{'LABEL':<24}{'SCOPES':<24}{'STATUS':<10}CREATED")
    for k in keys:
        status = "revoked" if k.revoked else "active"
        print(f"{k.id:<14}{k.label[:22]:<24}{','.join(k.scopes):<24}{status:<10}{k.created_at}")
    return 0


def cmd_revoke(args) -> int:
    store = _store()
    if store.revoke(args.id):
        print(f"Revoked key {args.id}")
        return 0
    print(f"No key with id {args.id}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="histo-taskqueue-keys", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create a new API key")
    p_create.add_argument("--label", default="", help="human-readable label")
    p_create.add_argument(
        "--scopes",
        default="create",
        help=f"comma/space separated scopes ({', '.join(SCOPES)}); default: create",
    )
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser("list", help="list API keys")
    p_list.set_defaults(func=cmd_list)

    p_revoke = sub.add_parser("revoke", help="revoke an API key by id")
    p_revoke.add_argument("id")
    p_revoke.set_defaults(func=cmd_revoke)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    main()
