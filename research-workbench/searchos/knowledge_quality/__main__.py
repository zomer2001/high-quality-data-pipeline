"""Local tools with no model/search calls. Writes require an explicit command or --save."""

import argparse
import json
from pathlib import Path

from .materials import CollectionDelivery, from_archive
from .ontology import Context, Fact, load_ontology
from .reasoning import compare
from .registry import policy_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ontology")
    validate = commands.add_parser("validate-delivery")
    validate.add_argument("path", type=Path)
    archive = commands.add_parser("export-archive")
    archive.add_argument("path", type=Path)
    archive.add_argument("--run-id", required=True)
    pair = commands.add_parser("compare")
    pair.add_argument("path", type=Path, help='JSON with "left" and "right" fact objects')
    analysis = commands.add_parser("analyze", help="Read-only unless --save is given")
    analysis.add_argument("--as-of")
    analysis.add_argument("--save", action="store_true")
    inspect = commands.add_parser("inspect-claim")
    inspect.add_argument("claim_id")
    review = commands.add_parser("review-evidence", help="Append an explicit evidence review")
    review.add_argument("path", type=Path)
    install = commands.add_parser("install-ledger", help="Install the additive SQL extension")
    for command in (analysis, inspect, review, install):
        command.add_argument("--database", type=Path, required=True)
        command.add_argument("--slug", default="anduril")
    args = parser.parse_args()
    try:
        if args.command == "ontology":
            output = {
                "policy": policy_version(),
                "ontology": load_ontology().model_dump(),
                "context_schema": Context.model_json_schema(),
                "fact_schema": Fact.model_json_schema(),
                "delivery_schema": CollectionDelivery.model_json_schema(),
            }
        elif args.command == "validate-delivery":
            delivery = CollectionDelivery.model_validate_json(args.path.read_text())
            output = {
                "valid": True,
                "materials": len(delivery.materials),
                "run_id": delivery.run_id,
            }
        elif args.command == "export-archive":
            output = from_archive(args.path, run_id=args.run_id).model_dump(mode="json")
        elif args.command == "compare":
            data = json.loads(args.path.read_text())
            output = {
                "policy": policy_version(),
                **compare(Fact.model_validate(data["left"]), Fact.model_validate(data["right"])),
            }
        else:
            from searchos.knowledge_store.database import ResearchDatabase

            from .analysis import analyze
            from .ledger import inspect_claim, review_evidence
            from .ledger import install as install_schema

            store = ResearchDatabase(args.database)
            if args.command == "analyze":
                output = analyze(store, args.slug, as_of=args.as_of, persist=args.save)
            elif args.command == "inspect-claim":
                output = inspect_claim(store, args.slug, args.claim_id)
            elif args.command == "review-evidence":
                output = review_evidence(store, args.slug, json.loads(args.path.read_text()))
                updated = analyze(store, args.slug, persist=True)
                output["analysis_run_id"] = updated["run_id"]
            else:
                install_schema(store)
                output = {"installed": True, "model_calls": 0}
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"输入未通过检查：{exc}\n")


if __name__ == "__main__":
    main()
