# bloodowned

`bloodowned` is a command-line tool to mark, unmark, and list users as "owned" in a BloodHound Neo4j database.

## Features

- ✨ Mark users as owned in BloodHound
- 🗑️ Unmark users (remove owned status)
- 📋 List all owned users
- 🔎 Search for owned users by pattern
- 🔧 Script-friendly output when piped

## Installation

### Using pipx (Recommended)

```bash
pipx install git+https://github.com/nollium/bloodowned.git
```

### Using pip

```bash
git clone https://github.com/nollium/bloodowned.git
cd bloodowned
pip install .
```

## Usage

### Mark a user as owned

```bash
bloodowned BIT200293
bloodowned BIT200293@DOMAIN.COM
bloodowned -t 'bolt://localhost:7687' -p 'password' BIT200293
```

### Unmark a user (remove owned status)

```bash
bloodowned -d BIT200293
bloodowned -d BIT200293@DOMAIN.COM
```

### List all owned users

```bash
bloodowned -l
bloodowned -l | grep ADMIN  # raw output when piped
```

### Search for owned users

```bash
bloodowned -s BIT200
bloodowned -s admin
```

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
bloodowned administrator
bloodowned administrator@contoso.local
bloodowned -d administrator@contoso.local
bloodowned -l
bloodowned -l | wc -l
bloodowned -s admin
bloodowned -t bolt://192.168.1.100:7687 -p 'password' administrator
bloodowned --no-color administrator
```
