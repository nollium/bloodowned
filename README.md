# bloodowned

`bloodowned` is a command-line tool to mark a user as "owned" in a BloodHound Neo4j database.

## Installation

You can install the tool from the root of the project directory using pip:

```bash
pip install .
```

## Usage

After installation, the `bloodowned` command will be available in your path.

### Example

```bash
bloodowned -t 'bolt://localhost:7687' -p 'your_neo4j_password' 'SOMEUSER@DOMAIN.COM'
```

### Options

-   `<user_principal_name>`: The user to mark as owned (e.g., `'user@domain.com'` or `'USER'`). (Required)
-   `-t`, `--target`: The URI for the Neo4j database. (Default: `bolt://localhost:7687`)
-   `-u`, `--user`: The username for the Neo4j database. (Default: `neo4j`)
-   `-p`, `--password`: The password for the Neo4j database. (Required)
