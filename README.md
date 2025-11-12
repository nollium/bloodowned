# bloodowned

`bloodowned` is a command-line tool to mark, unmark, and list users as "owned" in a BloodHound Neo4j database.

## Features

- ✨ Mark users as owned in BloodHound
- 🗑️ Unmark users (remove owned status)
- 📋 List all owned users
- 🔎 Search for owned users by pattern
- 🔧 Script-friendly output when piped

## Installation

Install the tool from the root of the project directory using pip:

```bash
pip install .
```

After installation, the `bloodowned` command will be available in your PATH.

## Usage

### Mark a user as owned

```bash
bloodowned BIT200293
bloodowned BIT200293@DOMAIN.COM
bloodowned -t 'bolt://localhost:7687' -p 'password' BIT200293
```

The tool will automatically resolve users even if you only provide the username without the domain. If multiple users match, it will show all matches and ask for clarification.

### Unmark a user (remove owned status)

```bash
bloodowned -d BIT200293
bloodowned -d BIT200293@DOMAIN.COM
```

### List all owned users

```bash
bloodowned -l
```

When piped or redirected, outputs only the user names (one per line):
```bash
bloodowned -l | grep ADMIN
bloodowned -l > owned_users.txt
```

### Search for owned users

Search for owned users matching a pattern:
```bash
bloodowned -s BIT200
bloodowned -s admin
bloodowned -s @contoso.local
```

The search uses fuzzy matching on user names, Azure names, and object IDs, and only returns users already marked as owned.

### Options

-   `<user_principal_name>`: The user to mark/unmark/search as owned (e.g., `'user@domain.com'` or `'USER'`). Optional when using `-l`.
-   `-t`, `--target`: Neo4j URI. (Default: `bolt://localhost:7687`)
-   `-u`, `--user`: Neo4j username. (Default: `neo4j`)
-   `-p`, `--password`: Neo4j password. (Default: `exegol4thewin`)
-   `-d`, `--delete`: Unmark the user as owned (remove owned status)
-   `-l`, `--list`: List all users marked as owned
-   `-s`, `--search`: Search for owned users matching the identifier
-   `--no-color`: Disable colored output

## Examples

```bash
# Mark a user as owned
bloodowned administrator

# Mark a user with full UPN
bloodowned administrator@contoso.local

# Unmark a user
bloodowned -d administrator@contoso.local

# List all owned users (formatted)
bloodowned -l

# List owned users for scripting (raw output)
bloodowned -l | wc -l

# Search for owned users matching a pattern
bloodowned -s BIT200
bloodowned -s admin
bloodowned -s @domain.local

# Connect to remote Neo4j
bloodowned -t bolt://192.168.1.100:7687 -p 'MyPassword' administrator

# Disable colored output
bloodowned --no-color administrator
```
