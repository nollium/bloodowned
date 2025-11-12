from __future__ import annotations

import argparse
from typing import Optional, Sequence

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

try:
    from neo4j import Driver, ManagedTransaction, Result
except ImportError:  # pragma: no cover - fallback for older neo4j versions
    Driver = ManagedTransaction = Result = object  # type: ignore[misc,assignment]


class UserLookupError(Exception):
    """Base exception for user lookup issues."""


class UserNotFoundError(UserLookupError):
    def __init__(self, identifier: str) -> None:
        super().__init__(f"User '{identifier}' not found.")
        self.identifier = identifier


class MultipleUsersFoundError(UserLookupError):
    def __init__(self, identifier: str, matches: Sequence[str]) -> None:
        matches_list = list(matches)
        super().__init__(
            "Multiple users matched "
            f"'{identifier}': {', '.join(sorted(matches_list))}"
        )
        self.identifier = identifier
        self.matches = matches_list


def mark_user_as_owned(tx: ManagedTransaction, user_principal_name: str) -> bool:
    """
    Runs the Cypher query to mark a user as owned.
    """
    query = (
        "MATCH (u:User) "
        "WHERE toUpper(u.name) = $upn "
        "WITH u "
        "SET u.owned = true "
        "RETURN count(u) AS updated"
    )
    result: Result = tx.run(query, upn=user_principal_name.upper())
    record = result.single()
    summary = result.consume()
    updated = 0
    if record and "updated" in record:
        updated = int(record["updated"])
    return bool(updated or summary.counters.contains_updates)


def resolve_user_principal_name(
    tx: ManagedTransaction, identifier: str
) -> str:
    """
    Resolve a user identifier to a unique UPN.

    If the identifier already contains a domain, match it directly. Otherwise,
    attempt to find a single user whose UPN's local part matches the provided
    identifier. If multiple matches are found, raise an error.
    """

    candidate = identifier.strip()
    if not candidate:
        raise UserNotFoundError(identifier)

    q = candidate
    params = {"q": q}
    query = (
        "MATCH (n:Base) "
        "WHERE toUpper(n.name) = toUpper($q) OR toUpper(n.azname) = toUpper($q) "
        "RETURN n.name AS name, n:User AS isUser LIMIT 10 "
        "UNION "
        "MATCH (n) "
        "WHERE toUpper(n.name) CONTAINS toUpper($q) "
        "   OR toUpper(n.azname) CONTAINS toUpper($q) "
        "   OR toUpper(n.objectid) CONTAINS toUpper($q) "
        "RETURN n.name AS name, n:User AS isUser LIMIT 10"
    )

    result: Result = tx.run(query, **params)
    records = list(result)
    result.consume()
    # Consider only User nodes
    names = [str(r["name"]).upper() for r in records if r.get("isUser")]
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for n in names:
        if n not in seen:
            seen.add(n)
            deduped.append(n)

    if not deduped:
        raise UserNotFoundError(candidate)
    if len(deduped) > 1:
        raise MultipleUsersFoundError(candidate, deduped)

    return deduped[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Mark a user as owned in a BloodHound Neo4j database.")
    parser.add_argument("user_principal_name", help="The user to mark as owned (e.g., 'user@domain.com' or 'USER').")
    parser.add_argument("-t", "--target", default="bolt://localhost:7687", help="Neo4j URI (default: bolt://localhost:7687)")
    parser.add_argument("-u", "--user", default="neo4j", help="Neo4j username (default: neo4j)")
    parser.add_argument("-p", "--password", default="exegol4thewin", help="Neo4j password (default: exegol4thewin)")

    args = parser.parse_args()

    uri = args.target
    user = args.user
    password = args.password

    driver: Optional[Driver] = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        with driver.session() as session:
            try:
                resolved_upn = session.execute_read(
                    resolve_user_principal_name,
                    args.user_principal_name,
                )
            except MultipleUsersFoundError as multi_error:
                matches = ", ".join(sorted(name.upper() for name in multi_error.matches))
                print(
                    f"[-] Multiple users matched '{multi_error.identifier.upper()}': {matches}"
                )
                return
            except UserNotFoundError as not_found_error:
                print(f"[-] User '{not_found_error.identifier.upper()}' not found.")
                return

            was_marked = session.execute_write(mark_user_as_owned, resolved_upn)
            if was_marked:
                print(f"[+] Successfully marked user '{resolved_upn}' as owned.")
            else:
                print(f"[-] User '{resolved_upn}' could not be updated.")
    except AuthError:
        print(f"[-] Authentication failed for user '{user}'. Please check the credentials.")
    except ServiceUnavailable:
        print(f"[-] Could not connect to Neo4j at '{uri}'. Please check the address and ensure the database is running.")
    except Exception as e:
        print(f"[-] An unexpected error occurred: {e}")
    finally:
        if driver:
            driver.close()

if __name__ == "__main__":
    main()
