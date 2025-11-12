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


class Logger:
    def __init__(self, use_color: bool = True):
        self._use_color = use_color

    def _colorize(self, text: str, color: str) -> str:
        if not self._use_color:
            return text
        return f"{color}{text}{Colors.RESET}"

    def success(self, message: str) -> None:
        prefix = self._colorize("[+]", Colors.GREEN)
        print(f"{prefix} {message}")

    def error(self, message: str) -> None:
        prefix = self._colorize("[-]", Colors.RED)
        print(f"{prefix} {message}")

    def info(self, message: str) -> None:
        prefix = self._colorize("[*]", Colors.YELLOW)
        print(f"{prefix} {message}")

    def plain(self, message: str) -> None:
        print(message)

    def highlight(self, text: str, color: str = Colors.CYAN) -> str:
        return self._colorize(text, color)


def should_colorize() -> bool:
    """Check if output should be colorized (TTY check)."""
    return sys.stdout.isatty()


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


def mark_as_owned(tx: ManagedTransaction, principal_name: str, is_computer: bool) -> bool:
    """
    Runs the Cypher query to mark a user or computer as owned.
    """
    node_type = "Computer" if is_computer else "User"
    query = (
        f"MATCH (n:{node_type}) "
        "WHERE toUpper(n.name) = $principal_name "
        "WITH n "
        "SET n.owned = true "
        "RETURN count(n) AS updated"
    )
    result: Result = tx.run(query, principal_name=principal_name.upper())
    record = result.single()
    summary = result.consume()
    updated = 0
    if record and "updated" in record:
        updated = int(record["updated"])
    return bool(updated or summary.counters.contains_updates)


def unmark_as_owned(tx: ManagedTransaction, principal_name: str, is_computer: bool) -> bool:
    """
    Runs the Cypher query to unmark a user or computer as owned.
    """
    node_type = "Computer" if is_computer else "User"
    query = (
        f"MATCH (n:{node_type}) "
        "WHERE toUpper(n.name) = $principal_name "
        "WITH n "
        "SET n.owned = false "
        "RETURN count(n) AS updated"
    )
    result: Result = tx.run(query, principal_name=principal_name.upper())
    record = result.single()
    summary = result.consume()
    updated = 0
    if record and "updated" in record:
        updated = int(record["updated"])
    return bool(updated or summary.counters.contains_updates)


def list_owned_principals(tx: ManagedTransaction) -> list[tuple[str, bool, str, int]]:
    """
    Returns a list of all users and computers marked as owned,
    including their high value status, principal type, and control count.
    """
    query = (
        "MATCH (n) "
        "WHERE (n:User OR n:Computer) AND n.owned = true "
        "OPTIONAL MATCH (n)-[r]->(m) WHERE r.isacl = true "
        "RETURN n.name AS name, n.highvalue AS is_high_value, labels(n) as labels, count(m) as control_count "
        "ORDER BY n.name"
    )
    result: Result = tx.run(query)
    records = list(result)
    result.consume()
    principals = []
    for record in records:
        name = str(record["name"]).upper()
        # The highvalue property might not exist, in which case it is None.
        is_high_value = record["is_high_value"] is True
        labels = record["labels"]
        principal_type = "computer" if "Computer" in labels else "user"
        control_count = record["control_count"]
        principals.append((name, is_high_value, principal_type, control_count))
    return principals


def get_users(users_list: list[str], file_path: Optional[str]) -> list[str]:
    """
    Collects a list of users from command-line arguments and/or a file.
    """
    all_users = set(users_list)
    if file_path:
        if file_path == "-":
            for line in sys.stdin:
                user = line.strip()
                if user:
                    all_users.add(user)
        else:
            with open(file_path, "r") as f:
                for line in f:
                    user = line.strip()
                    if user:
                        all_users.add(user)
    return sorted(list(all_users))


def search_owned_principals(tx: ManagedTransaction, identifier: str) -> list[str]:
    """
    Search for owned users or computers matching the identifier.
    
    Returns a list of matching owned principals.
    """
    candidate = identifier.strip()
    if not candidate:
        return []
    
    q = candidate
    params = {"q": q}
    query = (
        "MATCH (n:Base) "
        "WHERE (toUpper(n.name) = toUpper($q) OR toUpper(n.azname) = toUpper($q)) "
        "  AND (n:User OR n:Computer) AND n.owned = true "
        "RETURN n.name AS name LIMIT 10 "
        "UNION "
        "MATCH (n) "
        "WHERE (toUpper(n.name) CONTAINS toUpper($q) "
        "   OR toUpper(n.azname) CONTAINS toUpper($q) "
        "   OR toUpper(n.objectid) CONTAINS toUpper($q)) "
        "  AND (n:User OR n:Computer) AND n.owned = true "
        "RETURN n.name AS name LIMIT 10"
    )
    
    result: Result = tx.run(query, **params)
    records = list(result)
    result.consume()
    
    names = [str(r["name"]).upper() for r in records]
    seen = set()
    deduped = []
    for n in names:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    
    return deduped


def resolve_principal_name(
    tx: ManagedTransaction, identifier: str
) -> str:
    """
    Resolve a user or computer identifier to a unique principal name.
    """
    candidate = identifier.strip()
    is_machine_account = False
    if candidate.endswith("$"):
        is_machine_account = True
        candidate = candidate[:-1]

    if not candidate:
        raise UserNotFoundError(identifier)

    q = candidate
    params = {"q": q}
    
    node_type = "Computer" if is_machine_account else "User"

    query = (
        f"MATCH (n:{node_type}) "
        "WHERE toUpper(n.name) = toUpper($q) OR toUpper(n.azname) = toUpper($q) "
        "RETURN n.name AS name LIMIT 10 "
        "UNION "
        f"MATCH (n:{node_type}) "
        "WHERE (toUpper(n.name) CONTAINS toUpper($q) "
        "   OR toUpper(n.azname) CONTAINS toUpper($q) "
        "   OR toUpper(n.objectid) CONTAINS toUpper($q)) "
        "RETURN n.name AS name LIMIT 10"
    )

    result: Result = tx.run(query, **params)
    records = list(result)
    result.consume()
    names = [str(r["name"]).upper() for r in records]
    seen = set()
    deduped = []
    for n in names:
        if n not in seen:
            seen.add(n)
            deduped.append(n)

    if not deduped:
        raise UserNotFoundError(identifier)
    if len(deduped) > 1:
        raise MultipleUsersFoundError(identifier, deduped)

    return deduped[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Mark, unmark, search, and list owned users in a BloodHound Neo4j database.")
    parser.add_argument("users", nargs="*", help="One or more users to mark/unmark as owned.")
    parser.add_argument("-f", "--file", help="File with users to mark/unmark (one per line, '-' for stdin).")
    parser.add_argument("-t", "--target", default="bolt://localhost:7687", help="Neo4j URI (default: bolt://localhost:7687)")
    parser.add_argument("-u", "--user", default="neo4j", help="Neo4j username (default: neo4j)")
    parser.add_argument("-p", "--password", default="exegol4thewin", help="Neo4j password (default: exegol4thewin)")
    parser.add_argument("-d", "--delete", action="store_true", help="Unmark user(s) as owned.")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("-l", "--list", action="store_true", help="List all users marked as owned.")
    mode_group.add_argument("-s", "--search", help="Search for owned users matching a pattern.")
    
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")

    args = parser.parse_args()

    use_color = should_colorize() and not args.no_color
    if not use_color:
        Colors.disable()

    logger = Logger(use_color)

    if args.list and (args.users or args.file):
        parser.error("-l/--list cannot be used with user arguments or -f/--file.")
    if args.search and (args.users or args.file):
        parser.error("-s/--search cannot be used with user arguments or -f/--file.")
    
    users_to_process = []
    if not args.list and not args.search:
        try:
            users_to_process = get_users(args.users, args.file)
        except FileNotFoundError:
            logger.error(f"File not found: {logger.highlight(args.file)}")
            return
        
        if not users_to_process:
            parser.error("You must specify at least one user to mark/unmark, or use -l or -s.")

    uri = args.target
    user = args.user
    password = args.password

    driver: Optional[Driver] = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        with driver.session() as session:
            if args.list:
                owned_principals = session.execute_read(list_owned_principals)
                if not use_color:
                    for name, is_high_value, principal_type, control_count in owned_principals:
                        line = f"{name} ({principal_type})"
                        if is_high_value:
                            line += " (high value)"
                        if control_count > 0:
                            line += f" (controls: {control_count})"
                        logger.plain(line)
                else:
                    if owned_principals:
                        owned_colored = logger.highlight("owned", Colors.BOLD + Colors.BRIGHT_YELLOW)
                        logger.success(f"Found {len(owned_principals)} principal(s) marked as {owned_colored}:")
                        for name, is_high_value, principal_type, control_count in owned_principals:
                            name_colored = logger.highlight(name)
                            type_color = Colors.GREEN if principal_type == "user" else Colors.GOLD
                            type_str = logger.highlight(f"({principal_type})", type_color)
                            high_value_str = ""
                            if is_high_value:
                                high_value_str = f" {logger.highlight('(high value)', Colors.BOLD + Colors.BRIGHT_YELLOW)}"
                            control_str = ""
                            if control_count > 0:
                                control_str = f" {logger.highlight(f'(controls: {control_count})')}"
                            logger.plain(f"  • {name_colored} {type_str}{high_value_str}{control_str}")
                    else:
                        owned_colored = logger.highlight("owned", Colors.BOLD + Colors.BRIGHT_YELLOW)
                        logger.error(f"No principals marked as {owned_colored}.")
                return

            if args.search:
                matching_principals = session.execute_read(search_owned_principals, args.search)
                if not use_color:
                    for name in matching_principals:
                        logger.plain(name)
                else:
                    if matching_principals:
                        pattern_colored = logger.highlight(args.search.upper())
                        owned_colored = logger.highlight("owned", Colors.BOLD + Colors.BRIGHT_YELLOW)
                        logger.success(f"Found {len(matching_principals)} {owned_colored} principal(s) matching '{pattern_colored}':")
                        for name in matching_principals:
                            name_colored = logger.highlight(name)
                            logger.plain(f"  • {name_colored}")
                    else:
                        pattern_colored = logger.highlight(args.search.upper())
                        owned_colored = logger.highlight("owned", Colors.BOLD + Colors.BRIGHT_YELLOW)
                        logger.error(f"No {owned_colored} principals found matching '{pattern_colored}'.")
                return

            for user_identifier in users_to_process:
                try:
                    resolved_principal = session.execute_read(
                        resolve_principal_name,
                        user_identifier,
                    )

                    is_computer = user_identifier.strip().endswith("$")
                    if args.delete:
                        was_updated = session.execute_write(unmark_as_owned, resolved_principal, is_computer)
                        if was_updated:
                            principal_colored = logger.highlight(resolved_principal)
                            logger.success(f"Successfully unmarked '{principal_colored}'.")
                        else:
                            principal_colored = logger.highlight(resolved_principal)
                            logger.error(f"Principal '{principal_colored}' could not be updated.")
                    else:
                        was_marked = session.execute_write(mark_as_owned, resolved_principal, is_computer)
                        if was_marked:
                            principal_colored = logger.highlight(resolved_principal)
                            owned_colored = logger.highlight("owned", Colors.BOLD + Colors.BRIGHT_YELLOW)
                            logger.success(f"Successfully marked '{principal_colored}' as {owned_colored}.")
                        else:
                            principal_colored = logger.highlight(resolved_principal)
                            logger.error(f"Principal '{principal_colored}' could not be updated.")

                except MultipleUsersFoundError as multi_error:
                    matches = ", ".join(sorted(name.upper() for name in multi_error.matches))
                    identifier_colored = logger.highlight(multi_error.identifier.upper())
                    matches_colored = logger.highlight(matches)
                    logger.error(f"Multiple principals matched '{identifier_colored}': {matches_colored}")
                except UserNotFoundError as not_found_error:
                    identifier_colored = logger.highlight(not_found_error.identifier.upper())
                    logger.error(f"Principal '{identifier_colored}' not found.")
    except AuthError:
        user_colored = logger.highlight(user)
        logger.error(f"Authentication failed for user '{user_colored}'. Please check the credentials.")
    except ServiceUnavailable:
        uri_colored = logger.highlight(uri)
        logger.error(f"Could not connect to Neo4j at '{uri_colored}'. Please check the address and ensure the database is running.")
    except Exception as e:
        error_colored = logger.highlight(str(e))
        logger.error(f"An unexpected error occurred: {error_colored}")
    finally:
        if driver:
            driver.close()

if __name__ == "__main__":
    main()
