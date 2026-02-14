"""CLI entry point for the Robot Framework Dashboard."""

import argparse


def main():
    """Main entry point for the dashboard."""
    parser = argparse.ArgumentParser(
        description="Robot Framework Dashboard - Run multiple test sessions"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8050,
        help="Port to bind to (default: 8050)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )

    args = parser.parse_args()

    # Import here to avoid slow startup for --help
    from dashboard.app import app

    print("🚀 Starting Robot Framework Dashboard")
    print(f"   URL: http://{args.host}:{args.port}")
    print(f"   Debug: {args.debug}")
    print()

    app.run_server(debug=args.debug, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
