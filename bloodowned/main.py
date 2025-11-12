from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

try:
    from neo4j import Driver, ManagedTransaction, Result
except ImportError:  # pragma: no cover - fallback for older neo4j versions
    Driver = ManagedTransaction = Result = object  # type: ignore[misc,assignment]


# ANSI color codes
class Colors:
    """ANSI color escape codes."""
    RESET = "\033[0m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    BRIGHT_YELLOW = "\033[38;5;226m"  # Saturated yellow (more yellow, less white)
    CYAN = "\033[36m"
    BOLD = "\033[1m"
    GOLD = "\033[38;5;214m"  # Golden/yellow color similar to netexec
    
    @staticmethod
    def disable() -> None:
        """Disable colors by setting all codes to empty strings."""
        Colors.RESET = ""
        Colors.GREEN = ""
        Colors.RED = ""
        Colors.YELLOW = ""
        Colors.BRIGHT_YELLOW = ""
        Colors.CYAN = ""
        Colors.BOLD = ""
        Colors.GOLD = ""


def should_colorize() -> bool:
    """Check if output should be colorized (TTY check)."""
    return sys.stdout.isatty()


def colorize(text: str, color: str, enabled: bool = True) -> str:
    """Apply color to text if colorization is enabled."""
    if not enabled:
        return text
    return f"{color}{text}{Colors.RESET}"


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


def unmark_user_as_owned(tx: ManagedTransaction, user_principal_name: str) -> bool:
    """
    Runs the Cypher query to unmark a user as owned.
    """
    query = (
        "MATCH (u:User) "
        "WHERE toUpper(u.name) = $upn "
        "WITH u "
        "SET u.owned = false "
        "RETURN count(u) AS updated"
    )
    result: Result = tx.run(query, upn=user_principal_name.upper())
    record = result.single()
    summary = result.consume()
    updated = 0
    if record and "updated" in record:
        updated = int(record["updated"])
    return bool(updated or summary.counters.contains_updates)


def list_owned_users(tx: ManagedTransaction) -> list[str]:
    """
    Returns a list of all users marked as owned.
    """
    query = (
        "MATCH (u:User) "
        "WHERE u.owned = true "
        "RETURN u.name AS name "
        "ORDER BY u.name"
    )
    result: Result = tx.run(query)
    records = list(result)
    result.consume()
    return [str(record["name"]).upper() for record in records]


def search_owned_users(tx: ManagedTransaction, identifier: str) -> list[str]:
    """
    Search for owned users matching the identifier using the same logic as user resolution.
    
    Returns a list of matching owned users.
    """
    candidate = identifier.strip()
    if not candidate:
        return []
    
    q = candidate
    params = {"q": q}
    query = (
        "MATCH (n:Base) "
        "WHERE (toUpper(n.name) = toUpper($q) OR toUpper(n.azname) = toUpper($q)) "
        "  AND n:User AND n.owned = true "
        "RETURN n.name AS name LIMIT 10 "
        "UNION "
        "MATCH (n) "
        "WHERE (toUpper(n.name) CONTAINS toUpper($q) "
        "   OR toUpper(n.azname) CONTAINS toUpper($q) "
        "   OR toUpper(n.objectid) CONTAINS toUpper($q)) "
        "  AND n:User AND n.owned = true "
        "RETURN n.name AS name LIMIT 10"
    )
    
    result: Result = tx.run(query, **params)
    records = list(result)
    result.consume()
    
    names = [str(r["name"]).upper() for r in records]
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for n in names:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    
    return deduped


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
    parser = argparse.ArgumentParser(description="Mark or unmark a user as owned in a BloodHound Neo4j database.")
    parser.add_argument("user_principal_name", nargs="?", help="The user to mark/unmark/search as owned (e.g., 'user@domain.com' or 'USER'). Required unless using -l.")
    parser.add_argument("-t", "--target", default="bolt://localhost:7687", help="Neo4j URI (default: bolt://localhost:7687)")
    parser.add_argument("-u", "--user", default="neo4j", help="Neo4j username (default: neo4j)")
    parser.add_argument("-p", "--password", default="exegol4thewin", help="Neo4j password (default: exegol4thewin)")
    parser.add_argument("-d", "--delete", action="store_true", help="Unmark the user as owned (set owned to false)")
    parser.add_argument("-l", "--list", action="store_true", help="List all users marked as owned")
    parser.add_argument("-s", "--search", action="store_true", help="Search for owned users matching the identifier")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")

    args = parser.parse_args()

    # Initialize color support
    use_color = should_colorize() and not args.no_color
    if not use_color:
        Colors.disable()

    # Validate arguments
    if args.list and args.user_principal_name:
        parser.error("Cannot specify both -l/--list and a user name.")
    if args.search and not args.user_principal_name:
        parser.error("Search (-s/--search) requires a user name or pattern.")
    if not args.list and not args.search and not args.user_principal_name:
        parser.error("Either specify a user name or use -l/--list to list owned users or -s/--search to search.")

    uri = args.target
    user = args.user
    password = args.password

    driver: Optional[Driver] = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        with driver.session() as session:
            if args.list:
                owned_users = session.execute_read(list_owned_users)
                if not should_colorize():
                    # Non-TTY output: just raw data, one per line
                    for upn in owned_users:
                        print(upn)
                else:
                    # TTY output: formatted with colors
                    if owned_users:
                        owned_colored = colorize("owned", Colors.BOLD + Colors.BRIGHT_YELLOW, use_color)
                        print(f"{colorize('[+]', Colors.GREEN, use_color)} Found {len(owned_users)} user(s) marked as {owned_colored}:")
                        for upn in owned_users:
                            upn_colored = colorize(upn, Colors.CYAN, use_color)
                            print(f"  • {upn_colored}")
                    else:
                        owned_colored = colorize("owned", Colors.BOLD + Colors.BRIGHT_YELLOW, use_color)
                        print(f"{colorize('[-]', Colors.RED, use_color)} No users marked as {owned_colored}.")
                return

            if args.search:
                matching_users = session.execute_read(search_owned_users, args.user_principal_name)
                if not should_colorize():
                    # Non-TTY output: just raw data, one per line
                    for upn in matching_users:
                        print(upn)
                else:
                    # TTY output: formatted with colors
                    if matching_users:
                        pattern_colored = colorize(args.user_principal_name.upper(), Colors.CYAN, use_color)
                        owned_colored = colorize("owned", Colors.BOLD + Colors.BRIGHT_YELLOW, use_color)
                        print(f"{colorize('[+]', Colors.GREEN, use_color)} Found {len(matching_users)} {owned_colored} user(s) matching '{pattern_colored}':")
                        for upn in matching_users:
                            upn_colored = colorize(upn, Colors.CYAN, use_color)
                            print(f"  • {upn_colored}")
                    else:
                        pattern_colored = colorize(args.user_principal_name.upper(), Colors.CYAN, use_color)
                        owned_colored = colorize("owned", Colors.BOLD + Colors.BRIGHT_YELLOW, use_color)
                        print(f"{colorize('[-]', Colors.RED, use_color)} No {owned_colored} users found matching '{pattern_colored}'.")
                return

            # User operation (mark/unmark)
            try:
                resolved_upn = session.execute_read(
                    resolve_user_principal_name,
                    args.user_principal_name,
                )
            except MultipleUsersFoundError as multi_error:
                matches = ", ".join(sorted(name.upper() for name in multi_error.matches))
                upn_colored = colorize(multi_error.identifier.upper(), Colors.CYAN, use_color)
                matches_colored = colorize(matches, Colors.CYAN, use_color)
                print(
                    f"{colorize('[-]', Colors.RED, use_color)} Multiple users matched '{upn_colored}': {matches_colored}"
                )
                return
            except UserNotFoundError as not_found_error:
                upn_colored = colorize(not_found_error.identifier.upper(), Colors.CYAN, use_color)
                print(f"{colorize('[-]', Colors.RED, use_color)} User '{upn_colored}' not found.")
                return

            if args.delete:
                was_updated = session.execute_write(unmark_user_as_owned, resolved_upn)
                if was_updated:
                    upn_colored = colorize(resolved_upn, Colors.CYAN, use_color)
                    print(f"{colorize('[+]', Colors.GREEN, use_color)} Successfully unmarked user '{upn_colored}' as owned.")
                else:
                    upn_colored = colorize(resolved_upn, Colors.CYAN, use_color)
                    print(f"{colorize('[-]', Colors.RED, use_color)} User '{upn_colored}' could not be updated.")
            else:
                was_marked = session.execute_write(mark_user_as_owned, resolved_upn)
                if was_marked:
                    upn_colored = colorize(resolved_upn, Colors.CYAN, use_color)
                    owned_colored = colorize("owned", Colors.BOLD + Colors.BRIGHT_YELLOW, use_color)
                    print(f"{colorize('[+]', Colors.GREEN, use_color)} Successfully marked user '{upn_colored}' as {owned_colored}.")
                else:
                    upn_colored = colorize(resolved_upn, Colors.CYAN, use_color)
                    print(f"{colorize('[-]', Colors.RED, use_color)} User '{upn_colored}' could not be updated.")
    except AuthError:
        user_colored = colorize(user, Colors.CYAN, use_color)
        print(f"{colorize('[-]', Colors.RED, use_color)} Authentication failed for user '{user_colored}'. Please check the credentials.")
    except ServiceUnavailable:
        uri_colored = colorize(uri, Colors.CYAN, use_color)
        print(f"{colorize('[-]', Colors.RED, use_color)} Could not connect to Neo4j at '{uri_colored}'. Please check the address and ensure the database is running.")
    except Exception as e:
        error_colored = colorize(str(e), Colors.CYAN, use_color)
        print(f"{colorize('[-]', Colors.RED, use_color)} An unexpected error occurred: {error_colored}")
    finally:
        if driver:
            driver.close()

if __name__ == "__main__":
    main()
