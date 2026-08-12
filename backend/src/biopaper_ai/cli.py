"""Command-line entry point for BioPaper AI."""

import typer

app = typer.Typer(help="BioPaper AI trusted biomedical literature search.")


@app.command()
def main() -> None:
    """Start the BioPaper AI command-line interface."""
