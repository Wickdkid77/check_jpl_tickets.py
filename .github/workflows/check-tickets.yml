name: Check JPL Eventbrite tickets

on:
  schedule:
    # Every 5 minutes. GitHub does not guarantee exact timing -- during
    # high load it can be delayed by several extra minutes.
    - cron: "*/5 * * * *"
  workflow_dispatch: {} # lets you trigger a manual run from the Actions tab

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install requests

      # Restores state.json from the previous run so we know whether we
      # already sent a notification for the current status.
      - name: Restore state
        uses: actions/cache@v4
        with:
          path: state.json
          key: jpl-ticket-state-${{ github.run_id }}
          restore-keys: |
            jpl-ticket-state-

      - name: Run checker
        env:
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
        run: python check_jpl_tickets.py

      - name: Save state
        uses: actions/cache@v4
        with:
          path: state.json
          key: jpl-ticket-state-${{ github.run_id }}
